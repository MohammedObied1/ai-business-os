"""Approval Center: configurable rules + one request record per sensitive action.

Two kinds of approval:
- the document already exists and waits in a pending state (sales order `pending_approval`, expense `pending`,
  purchase request): approving continues the existing workflow;
- the action is deferred (cancel an invoice, big return, stock adjustment, payment voucher, price change): nothing
  happens now; the request keeps what to do in `payload` and runs it when a manager approves.
A user who holds `approvals.approve` never waits for anybody.
"""
from datetime import datetime

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.deps import has_permission
from app.models import Company, User
from app.models.control import ApprovalRequest, ApprovalRule

# kind → (unit of the threshold, enabled by default, default threshold)
KINDS: dict[str, tuple[str, bool, float]] = {
    "sales_discount": ("percent", False, 0),      # discount above X %  (mirrors company.approval_discount_pct)
    "below_cost": ("none", True, 0),              # selling below cost: always, when enabled
    "large_expense": ("amount", False, 0),        # expense above X     (mirrors company.approval_expense_amount)
    "invoice_cancel": ("amount", False, 0),       # cancelling an invoice of X or more (0 = every invoice)
    "large_return": ("amount", False, 0),         # customer return worth X or more
    "inventory_adjustment": ("amount", False, 0), # stock adjustment worth X or more (at cost)
    "purchase_order": ("amount", True, 0),        # purchase requests of X or more (0 = all, the historic behaviour)
    "payment_voucher": ("amount", False, 0),      # payment voucher (money out) of X or more
    "price_change": ("percent", False, 0),        # sale price changed by X % or more
}


def rule(db: Session, cid: int, kind: str) -> tuple[bool, float]:
    """(enabled, threshold) for a company. Discount / expense rules keep reading the older company settings."""
    r = db.scalar(select(ApprovalRule).where(ApprovalRule.company_id == cid, ApprovalRule.kind == kind))
    if r:
        return r.enabled, r.threshold or 0
    company = db.get(Company, cid)
    if kind == "sales_discount":
        return bool(company.approval_discount_pct), company.approval_discount_pct or 0
    if kind == "large_expense":
        return bool(company.approval_expense_amount), company.approval_expense_amount or 0
    _, enabled, threshold = KINDS[kind]
    return enabled, threshold


def all_rules(db: Session, cid: int) -> list[dict]:
    return [{"kind": k, "unit": KINDS[k][0], "enabled": rule(db, cid, k)[0], "threshold": rule(db, cid, k)[1]} for k in KINDS]


def save_rules(db: Session, cid: int, rows: list[dict]) -> None:
    company = db.get(Company, cid)
    for row in rows:
        kind = row.get("kind")
        if kind not in KINDS:
            raise HTTPException(400, f"Unknown approval rule {kind}")
        threshold = float(row.get("threshold") or 0)
        if threshold < 0:
            raise HTTPException(400, "Threshold can't be negative")
        r = db.scalar(select(ApprovalRule).where(ApprovalRule.company_id == cid, ApprovalRule.kind == kind))
        if not r:
            r = ApprovalRule(company_id=cid, kind=kind)
            db.add(r)
        r.enabled, r.threshold = bool(row.get("enabled")), threshold
        # keep the older settings in step, the pricing / expense code reads them
        if kind == "sales_discount":
            company.approval_discount_pct = threshold if r.enabled else 0
        if kind == "large_expense":
            company.approval_expense_amount = threshold if r.enabled else 0


def needs(db: Session, user: User, kind: str, value: float | None = None) -> bool:
    """Does this action by this user need a manager? (approvers never wait)"""
    if has_permission(user, "approvals.approve"):
        return False
    enabled, threshold = rule(db, user.company_id, kind)
    if not enabled:
        return False
    if KINDS[kind][0] == "none" or value is None:
        return True
    return abs(value) >= threshold


def request(db: Session, user: User, kind: str, entity: str, entity_id: int | None, label: str | None, value: float | None = None,
            reason: str | None = None, payload: dict | None = None) -> ApprovalRequest:
    _, threshold = rule(db, user.company_id, kind)
    req = ApprovalRequest(company_id=user.company_id, kind=kind, entity=entity, entity_id=entity_id, label=label, requested_value=value,
                          threshold=threshold, reason=reason, payload=payload, requested_by_id=user.id, requested_by=user.full_name)
    db.add(req)
    db.flush()
    from app.services import notify
    notify.send(db, user.company_id, "approval_request", f"Approval needed: {label or kind}", reason or "",
                link="/approvals", dedupe=f"approval:{req.id}", permission="approvals.approve")
    return req


def pending_response(req: ApprovalRequest) -> dict:
    """Body returned (HTTP 202) when an action was sent for approval instead of being done."""
    return {"pending_approval": True, "approval_request_id": req.id, "detail": "Sent to a manager for approval"}


def resolve_for(db: Session, entity: str, entity_id: int, status: str, user: User, reason: str | None = None) -> None:
    """The older screens approve orders / expenses / purchases directly: close the matching request too."""
    for req in db.scalars(select(ApprovalRequest).where(ApprovalRequest.company_id == user.company_id, ApprovalRequest.entity == entity,
                                                        ApprovalRequest.entity_id == entity_id, ApprovalRequest.status == "PENDING")).all():
        req.status, req.approver_id, req.approver, req.decided_at = status, user.id, user.full_name, datetime.utcnow()
        if status == "REJECTED":
            req.rejection_reason = reason


# ---------------------------------------------------------------- deciding
def decide(db: Session, user: User, req: ApprovalRequest, approve: bool, reason: str | None = None) -> ApprovalRequest:
    if req.status != "PENDING":
        raise HTTPException(400, "This request was already decided")
    if not has_permission(user, "approvals.approve"):
        raise HTTPException(403, "Missing permission(s): approvals.approve")
    if req.requested_by_id == user.id and not has_permission(user, "*"):
        raise HTTPException(403, "You can't approve your own request")
    if not approve and not (reason or "").strip():
        raise HTTPException(400, "Write why it is rejected")
    handler = _HANDLERS.get(req.kind)
    if handler:
        handler(db, user, req, approve)
    req.status = "APPROVED" if approve else "REJECTED"
    req.approver_id, req.approver, req.decided_at = user.id, user.full_name, datetime.utcnow()
    req.rejection_reason = None if approve else reason
    if req.requested_by_id:
        from app.services import notify
        notify.send(db, user.company_id, "approval_decided", f"{'Approved' if approve else 'Rejected'}: {req.label or req.kind}",
                    reason or "", link="/approvals", user_id=req.requested_by_id, dedupe=f"approval-done:{req.id}")
    return req


def cancel(db: Session, user: User, req: ApprovalRequest) -> ApprovalRequest:
    if req.status != "PENDING":
        raise HTTPException(400, "This request was already decided")
    if req.requested_by_id != user.id and not has_permission(user, "approvals.approve"):
        raise HTTPException(403, "Only the requester or a manager can cancel it")
    if req.entity == "sales_orders" and req.entity_id:
        from app.models import SalesOrder
        o = db.get(SalesOrder, req.entity_id)
        if o and o.status == "pending_approval":
            o.status = "cancelled"
    if req.entity == "expenses" and req.entity_id:
        from app.models import Expense
        e = db.get(Expense, req.entity_id)
        if e and e.approval_status == "pending":
            e.approval_status = "rejected"
    req.status, req.decided_at = "CANCELLED", datetime.utcnow()
    return req


def _order(db, user, req, approve):
    from app.models import SalesOrder
    from app.services import sales_ops
    o = db.get(SalesOrder, req.entity_id)
    if not o or o.company_id != user.company_id:
        raise HTTPException(404, "Order not found")
    if o.status != "pending_approval":
        return
    if approve:
        sales_ops.approve_order(db, user, o)
    else:
        o.status, o.approved_by = "cancelled", f"rejected by {user.full_name}"


def _expense(db, user, req, approve):
    from app.models import Expense
    from app.services.money import get_account, post
    e = db.get(Expense, req.entity_id)
    if not e or e.company_id != user.company_id or e.approval_status != "pending":
        return
    e.approval_status = "approved" if approve else "rejected"
    if approve and e.is_paid:
        acc = get_account(db, user.company_id, e.account_id)
        e.account_id = acc.id
        post(db, user.company_id, acc.id, -e.amount, "expense", prefix="PV", tx_date=e.expense_date, expense_id=e.id,
             description=f"{e.category}{' - ' + e.description if e.description else ''}", user_id=user.id)


def _invoice_cancel(db, user, req, approve):
    from app.models import Invoice
    if not approve:
        return
    inv = db.get(Invoice, req.entity_id)
    if not inv or inv.company_id != user.company_id:
        raise HTTPException(404, "Invoice not found")
    if inv.paid_amount > 0 or (inv.credited_amount or 0) > 0:
        raise HTTPException(400, "Invoice has payments and cannot be cancelled")
    from app.services import periods
    periods.check_open(db, user.company_id, inv.issue_date)
    inv.status = "cancelled"


def _return(db, user, req, approve):
    if not approve:
        return
    from app.schemas.sales import ReturnIn
    from app.services import sales_ops
    sales_ops.create_return(db, user, ReturnIn(**req.payload))


def _adjustment(db, user, req, approve):
    if not approve:
        return
    from app.api.inventory import apply_stock
    p = req.payload
    apply_stock(db, user.company_id, p["product_id"], p["warehouse_id"], p["quantity"], "adjustment", p.get("reference") or f"Approved #{req.id}",
                p.get("batch") or "", p.get("expiry_date"), p.get("serial"))


def _purchase(db, user, req, approve):
    from app.api.purchasing import _transition
    from app.models import PurchaseOrder
    po = db.get(PurchaseOrder, req.entity_id)
    if not po or po.status != "request":
        return
    _transition(po.id, "approved" if approve else "cancelled", user, db)


def _voucher(db, user, req, approve):
    if not approve:
        return
    from datetime import date as _date
    from app.services.money import post
    p = req.payload
    post(db, user.company_id, p["account_id"], -abs(p["amount"]), "other_out", prefix="PV", tx_date=_date.fromisoformat(p["tx_date"]) if p.get("tx_date") else None,
         party_name=p.get("party_name"), description=p.get("description"), reference=p.get("reference"), user_id=req.requested_by_id,
         gl_account_id=p.get("gl_account_id"))


def _price(db, user, req, approve):
    if not approve:
        return
    from app.models import Product
    p = db.get(Product, req.entity_id)
    if not p or p.company_id != user.company_id:
        raise HTTPException(404, "Product not found")
    p.sale_price = float(req.payload["sale_price"])


_HANDLERS = {"sales_discount": _order, "below_cost": _order, "large_expense": _expense, "invoice_cancel": _invoice_cancel, "large_return": _return,
             "inventory_adjustment": _adjustment, "purchase_order": _purchase, "payment_voucher": _voucher, "price_change": _price}


