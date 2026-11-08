"""Automation engine: IF <condition> THEN <actions>.

Each condition finds its matches (an overdue invoice, a product running low, a cheque due…); the rule's actions run on
every match: raise an alert (which reaches the right people's inbox), notify people holding a permission, email or
WhatsApp the customer, create a task, or prepare a purchase suggestion (a purchase *request* that still needs approval).
Event rules (expense above X, discount above Y → require approval) are stored here but enforced by the approval center.
Nothing here moves money: dangerous financial actions are not available to automation.
"""
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from app.models import (
    Alert, AutomationLog, AutomationRule, Cheque, Company, Customer, Invoice, Product, PurchaseOrder, PurchaseOrderItem, StockLevel, Supplier, Task,
    Warehouse,
)
from app.services import analytics
from app.services.forecasting import forecast_all
from app.services.numbering import next_number

DEFAULT_RULES = [
    {"name": "Low stock", "condition_type": "low_stock", "params": {}, "action_type": "create_alert", "severity": "warning"},
    {"name": "Invoice overdue > 30 days", "condition_type": "invoice_overdue", "params": {"days": 30}, "action_type": "create_alert", "severity": "critical"},
    {"name": "Sales drop > 15%", "condition_type": "sales_drop", "params": {"pct": 15}, "action_type": "create_alert", "severity": "critical"},
    {"name": "Customer inactive 60 days", "condition_type": "inactive_customer", "params": {"days": 60}, "action_type": "create_task", "severity": "info"},
    {"name": "Stock-out risk → purchase request", "condition_type": "stockout_risk", "params": {}, "action_type": "create_purchase_request", "severity": "warning"},
    {"name": "Batches expiring within 30 days", "condition_type": "expiring_batches", "params": {"days": 30}, "action_type": "create_alert", "severity": "warning"},
    {"name": "Cheques due within 3 days", "condition_type": "cheques_due", "params": {"days": 3}, "action_type": "create_alert", "severity": "warning"},
    {"name": "Instalments due within 3 days", "condition_type": "installments_due", "params": {"days": 3}, "action_type": "create_alert", "severity": "warning"},
    {"name": "Suspicious activity by an employee", "condition_type": "risk_signals", "params": {"days": 30}, "action_type": "create_alert", "severity": "critical"},
]

# what each condition needs (shown by the rule builder)
CONDITIONS = {
    "invoice_overdue": {"params": {"days": 30}, "subject": "invoice"},
    "low_stock": {"params": {}, "subject": "product"},
    "stockout_risk": {"params": {}, "subject": "product"},
    "expiring_batches": {"params": {"days": 30}, "subject": "product"},
    "cheques_due": {"params": {"days": 3}, "subject": "cheque"},
    "installments_due": {"params": {"days": 3}, "subject": "invoice"},
    "sales_drop": {"params": {"pct": 15}, "subject": "company"},
    "inactive_customer": {"params": {"days": 60}, "subject": "customer"},
    "risk_signals": {"params": {"days": 30}, "subject": "user"},
    # event rules: checked when the action happens (approval center), not on a schedule
    "expense_above": {"params": {"amount": 1000}, "subject": "event", "event": "large_expense"},
    "discount_above": {"params": {"pct": 10}, "subject": "event", "event": "sales_discount"},
}
ACTIONS = ["alert", "notify", "email_customer", "whatsapp_customer", "create_task", "purchase_suggestion", "require_approval"]
LEGACY_ACTION = {"create_alert": "alert", "notify": "notify", "create_task": "create_task", "create_purchase_request": "purchase_suggestion"}


@dataclass
class Match:
    key: str
    title: str
    message: str = ""
    recommended: str = ""
    severity: str | None = None
    category: str = "general"
    customer_id: int | None = None
    product_id: int | None = None
    qty: float = 0
    data: dict = field(default_factory=dict)


def ensure_default_rules(db: Session, cid: int) -> None:
    """Add any default rule the company doesn't have yet (matched by condition type)."""
    have = set(db.scalars(select(AutomationRule.condition_type).where(AutomationRule.company_id == cid)).all())
    added = False
    for r in DEFAULT_RULES:
        if r["condition_type"] not in have:
            db.add(AutomationRule(company_id=cid, **r))
            added = True
    if added:
        db.commit()


def rule_actions(rule: AutomationRule) -> list[dict]:
    if rule.actions:
        return rule.actions
    return [{"type": LEGACY_ACTION.get(rule.action_type, "alert"), "params": {}}]


# ---------------------------------------------------------------- conditions → matches
def _matches(db: Session, cid: int, rule: AutomationRule) -> list[Match]:
    today, p, ct = date.today(), rule.params or {}, rule.condition_type
    out: list[Match] = []
    if ct == "low_stock":
        for x in analytics.low_stock_products(db, cid):
            out.append(Match(f"low_stock:{x['product_id']}", f"Low stock: {x['name']}", f"Stock {x['stock']:.0f} is below minimum {x['min_stock']:.0f}.",
                             "Create purchase request", category="inventory", product_id=x["product_id"], qty=max(x["min_stock"] * 2 - x["stock"], 0)))
    elif ct == "invoice_overdue":
        for inv in analytics.overdue_invoices(db, cid, int(p.get("days", 30))):
            inv.status = "overdue"
            out.append(Match(f"overdue:{inv.id}", f"Invoice {inv.number} overdue {(today - inv.due_date).days} days",
                             f"Balance {inv.balance:.2f} due since {inv.due_date}.", "Notify finance manager / contact customer", category="finance",
                             customer_id=inv.customer_id, data={"invoice": inv.number, "balance": round(inv.balance, 2), "due": str(inv.due_date),
                                                                "token": inv.public_token}))
    elif ct == "sales_drop":
        s, _e = analytics.month_bounds(today)
        ps, pe = analytics.month_bounds(s - timedelta(days=1))
        elapsed = (today - s).days + 1
        cur, _ = analytics.revenue_between(db, cid, s, today)
        prev, _ = analytics.revenue_between(db, cid, ps, min(pe, ps + timedelta(days=elapsed - 1)))
        if prev > 0 and (prev - cur) / prev * 100 > float(p.get("pct", 15)):
            drop = (prev - cur) / prev * 100
            out.append(Match(f"sales_drop:{s.isoformat()}", f"Sales decreased {drop:.1f}%",
                             f"Month-to-date revenue {cur:,.0f} vs {prev:,.0f} in the same period last month.", "Analyze sales decline", category="sales"))
    elif ct == "inactive_customer":
        for c in analytics.inactive_customers(db, cid, int(p.get("days", 60))):
            out.append(Match(f"inactive:{c['customer_id']}:{today.strftime('%Y-%m')}", f"Inactive customer: {c['name']}",
                             f"No purchase since {c['last_purchase'] or 'ever'}.", "Create sales follow-up", severity="info", category="crm",
                             customer_id=c["customer_id"]))
    elif ct == "stockout_risk":
        for f in forecast_all(db, cid, only_risky=True):
            if f["risk"] == "HIGH" and f["recommended_order_qty"] > 0:
                out.append(Match(f"stockout:{f['product_id']}", f"May stock out: {f['product_name']}", f["explanation"],
                                 f"Order {f['recommended_order_qty']:.0f} units", category="inventory", product_id=f["product_id"],
                                 qty=f["recommended_order_qty"]))
    elif ct == "expiring_batches":
        rows = db.execute(select(StockLevel, Product.name, Warehouse.name).join(Product, Product.id == StockLevel.product_id)
                          .join(Warehouse, Warehouse.id == StockLevel.warehouse_id)
                          .where(StockLevel.company_id == cid, StockLevel.quantity > 0, StockLevel.expiry_date.is_not(None),
                                 StockLevel.expiry_date <= today + timedelta(days=int(p.get("days", 30))))).all()
        for lv, pname, wname in rows:
            out.append(Match(f"expiry:{lv.id}:{lv.expiry_date}", f"Expires {lv.expiry_date}: {pname}", f"{lv.quantity:g} in {wname}, batch {lv.batch or '-'}.",
                             "Sell first or return to supplier", severity="critical" if lv.expiry_date < today else None, category="inventory",
                             product_id=lv.product_id))
    elif ct == "cheques_due":
        for ch in db.scalars(select(Cheque).where(Cheque.company_id == cid, Cheque.status.in_(("pending", "deposited")),
                                                  Cheque.due_date <= today + timedelta(days=int(p.get("days", 3))))).all():
            party = db.get(Customer, ch.customer_id).name if ch.customer_id else (db.get(Supplier, ch.supplier_id).name if ch.supplier_id else "")
            out.append(Match(f"cheque:{ch.id}", f"Cheque {ch.number} due {ch.due_date}",
                             f"{party}: {ch.amount:,.2f} ({'incoming' if ch.direction == 'in' else 'outgoing'})",
                             "Deposit the cheque" if ch.direction == "in" else "Make sure the bank account has enough money", category="finance",
                             customer_id=ch.customer_id))
    elif ct == "installments_due":
        from app.api.sales import installments_due
        from app.models import User
        owner = db.scalar(select(User).where(User.company_id == cid).order_by(User.id))
        for i in installments_due(int(p.get("days", 3)), owner, db) if owner else []:
            out.append(Match(f"inst:{i['id']}", f"Instalment {i['seq']} of {i['invoice']} due {i['due_date']}", f"{i['customer']}: {i['remaining']:,.2f}",
                             "Contact the customer", severity="critical" if i["status"] == "late" else None, category="finance", customer_id=i["customer_id"],
                             data={"invoice": i["invoice"], "balance": i["remaining"], "due": str(i["due_date"])}))
    elif ct == "risk_signals":
        from app.services.smart import risk_signals
        for r in risk_signals(db, cid, int(p.get("days", 30))):
            if r["flags"]:
                out.append(Match(f"risk:{r['user_id']}:{','.join(sorted(r['flags']))}", f"Check activity: {r['name']}", ", ".join(r["flags"]),
                                 "Open the risk report", category="security"))
    return out


# ---------------------------------------------------------------- actions
def _done_recently(db: Session, cid: int, rule: AutomationRule, key: str, action: str, repeat_days: int | None) -> bool:
    stmt = select(AutomationLog.id).where(AutomationLog.company_id == cid, AutomationLog.rule_id == rule.id, AutomationLog.match_key == key,
                                          AutomationLog.action == action)
    if repeat_days:
        stmt = stmt.where(AutomationLog.created_at >= datetime.utcnow() - timedelta(days=repeat_days))
    return bool(db.scalar(stmt))


def _log(db: Session, cid: int, rule: AutomationRule, key: str, action: str, detail: str = "") -> None:
    db.add(AutomationLog(company_id=cid, rule_id=rule.id, match_key=key, action=action, detail=detail[:1000]))


def _upsert_alert(db: Session, cid: int, rule: AutomationRule | None, key: str, **fields) -> bool:
    if db.scalar(select(Alert.id).where(Alert.company_id == cid, Alert.dedupe_key == key, Alert.is_resolved.is_(False))):
        return False
    db.add(Alert(company_id=cid, rule_id=rule.id if rule else None, dedupe_key=key, **fields))
    return True


def _customer_message(db: Session, cid: int, m: Match) -> tuple[Customer | None, str, str]:
    c = db.get(Customer, m.customer_id) if m.customer_id else None
    company = db.get(Company, cid)
    if m.data.get("invoice"):
        from app.core.config import settings
        link = f"\n{settings.PUBLIC_APP_URL.rstrip('/')}/i/{m.data['token']}" if m.data.get("token") else ""
        subject = f"Payment reminder — {m.data['invoice']}"
        text = (f"مرحبا {c.name if c else ''}، تذكير لطيف من {company.name}: فاتورة {m.data['invoice']} بقيمة {m.data['balance']:,.2f} "
                f"كانت مستحقة بتاريخ {m.data['due']}. شكراً لكم.{link}")
    else:
        subject, text = m.title, f"{m.title}\n{m.message}"
    return c, subject, text


def _run_action(db: Session, cid: int, rule: AutomationRule, action: dict, m: Match) -> bool:
    kind, params = action.get("type", "alert"), action.get("params") or {}
    repeat = params.get("repeat_days")
    if kind == "alert":
        return _upsert_alert(db, cid, rule, m.key, severity=m.severity or rule.severity, category=m.category, title=m.title, message=m.message,
                             recommended_action=m.recommended)
    if _done_recently(db, cid, rule, m.key, kind, repeat):
        return False
    if kind == "notify":
        from app.services import notify
        told = notify.send(db, cid, params.get("kind") or notify.ALERT_KINDS.get(m.key.split(":")[0], "general"), m.title, m.message,
                           link="/alerts", permission=params.get("permission") or None, severity=m.severity or rule.severity,
                           dedupe=f"rule:{rule.id}:{m.key}:{date.today().isoformat() if repeat else ''}")
        _log(db, cid, rule, m.key, kind, f"{told} people")
        return told > 0
    if kind in ("email_customer", "whatsapp_customer"):
        c, subject, text = _customer_message(db, cid, m)
        if not c:
            return False
        if kind == "email_customer":
            if not c.email:
                return False
            from app.services import email as mail
            mail.queue(db, c.email, subject, mail.layout(subject, "<p>" + text.replace("\n", "<br>") + "</p>"), "reminder", cid)
        else:
            from app.services import integrations
            if not c.phone or not integrations.whatsapp_send(db, cid, c.phone, text):
                return False
        _log(db, cid, rule, m.key, kind, c.email if kind == "email_customer" else c.phone)
        return True
    if kind == "create_task":
        if m.customer_id and db.scalar(select(Task.id).where(Task.company_id == cid, Task.related_customer_id == m.customer_id, Task.status == "open")):
            return False
        db.add(Task(company_id=cid, title=m.title if not m.customer_id else f"Sales follow-up: {m.title.split(': ', 1)[-1]}", description=m.message,
                    related_customer_id=m.customer_id, assigned_to_id=params.get("assign_to") or None, created_by="automation"))
        _log(db, cid, rule, m.key, kind)
        return True
    return False  # purchase_suggestion is grouped per run; require_approval is enforced by the approval center


def _purchase_suggestion(db: Session, cid: int, rule: AutomationRule, matches: list[Match]) -> bool:
    """One purchase REQUEST (still needs approval) for everything the rule found."""
    items = [m for m in matches if m.product_id and m.qty > 0]
    if not items or db.scalar(select(PurchaseOrder.id).where(PurchaseOrder.company_id == cid, PurchaseOrder.status == "request",
                                                             PurchaseOrder.requested_by == "AI Agent")):
        return False
    supplier = db.scalar(select(Supplier).where(Supplier.company_id == cid))
    if not supplier:
        return False
    po = PurchaseOrder(company_id=cid, number=next_number(db, PurchaseOrder, cid, "PR"), supplier_id=supplier.id, status="request",
                       requested_by="AI Agent", notes=f"Suggested by the rule “{rule.name}”. Review and approve.")
    db.add(po)
    db.flush()
    total = 0.0
    for m in items:
        prod = db.get(Product, m.product_id)
        lt = m.qty * (prod.cost_price or 0)
        db.add(PurchaseOrderItem(company_id=cid, po_id=po.id, product_id=prod.id, quantity=m.qty, unit_cost=prod.cost_price or 0, line_total=lt))
        total += lt
    po.total = round(total, 2)
    _log(db, cid, rule, f"po:{po.number}", "purchase_suggestion", po.number)
    return True


def run_rule(db: Session, cid: int, rule: AutomationRule) -> int:
    if CONDITIONS.get(rule.condition_type, {}).get("subject") == "event":
        return 0  # enforced when it happens
    created = 0
    matches = _matches(db, cid, rule)
    actions = rule_actions(rule)
    for action in actions:
        if action.get("type") == "purchase_suggestion":
            created += _purchase_suggestion(db, cid, rule, matches)
            if not any(a.get("type") == "alert" for a in actions):  # keep the old behaviour: suggestions came with alerts
                created += sum(_run_action(db, cid, rule, {"type": "alert"}, m) for m in matches)
            continue
        created += sum(_run_action(db, cid, rule, action, m) for m in matches)
    rule.last_run_at = datetime.utcnow()
    return created


def sync_event_rule(db: Session, cid: int, rule: AutomationRule) -> None:
    """"IF expense > X THEN require approval" and "IF discount > Y% THEN require approval" live in the approval center."""
    event = CONDITIONS.get(rule.condition_type, {}).get("event")
    if not event:
        return
    from app.services import approvals
    wants = rule.is_active and any(a.get("type") == "require_approval" for a in rule_actions(rule))
    threshold = float((rule.params or {}).get("amount" if event == "large_expense" else "pct", 0))
    approvals.save_rules(db, cid, [{"kind": event, "enabled": wants, "threshold": threshold}])


def run_company(db: Session, cid: int) -> dict:
    ensure_default_rules(db, cid)
    rules = db.scalars(select(AutomationRule).where(AutomationRule.company_id == cid, AutomationRule.is_active.is_(True))).all()
    results = {r.name: run_rule(db, cid, r) for r in rules}
    db.commit()
    return results


def run_all_companies() -> None:
    db = SessionLocal()
    try:
        for cid in db.scalars(select(Company.id).where(Company.is_active.is_(True))).all():
            run_company(db, cid)
    finally:
        db.close()
