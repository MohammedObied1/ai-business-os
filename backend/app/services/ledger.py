"""General ledger (double-entry).

Every business document already in the system is turned into journal entries by `rebuild()`: sales orders, invoices,
payments, returns, purchases, supplier payments, expenses, payroll, cheques, cash/bank movements and stock adjustments.
Automatic entries are regenerated from the documents (so editing a document never leaves the books out of step);
manual journal entries typed by the accountant are kept as they are. Everything is in the company's base currency.

Sales are recognised when an order is confirmed/delivered (Dr receivables, Cr sales and VAT), cost of goods when the
stock leaves a warehouse. Cheques received sit in "cheques under collection" until the bank clears them.
"""
import time
from collections import defaultdict
from datetime import date, datetime

from fastapi import HTTPException
from sqlalchemy import delete, func, insert, select
from sqlalchemy.orm import Session

from app.models import (
    Account, Company, CreditNote, Expense, GLAccount, Invoice, JournalEntry, JournalLine, Payment, Product, PurchaseOrder,
    SalesOrder, StockLevel, StockMovement, Supplier, SupplierPayment, Transaction,
)

# system_key → (code, Arabic name, English name, type)
CHART = {
    "cash": ("1100", "الصناديق", "Cash boxes", "asset"),
    "bank": ("1200", "البنوك", "Bank accounts", "asset"),
    "transit": ("1190", "تحويلات بين الحسابات", "Transfers in transit", "asset"),
    "ar": ("1300", "ذمم الزباين", "Accounts receivable", "asset"),
    "cheques_in": ("1350", "شيكات برسم التحصيل", "Cheques under collection", "asset"),
    "inventory": ("1400", "المخزون", "Inventory", "asset"),
    "vat_in": ("1500", "ضريبة مدفوعة (مدخلات)", "VAT receivable (input)", "asset"),
    "advances": ("1600", "سلف الموظفين", "Employee advances", "asset"),
    "fixed_assets": ("1700", "الأصول الثابتة", "Fixed assets", "asset"),
    "ap": ("2100", "ذمم الموردين", "Accounts payable", "liability"),
    "cheques_out": ("2150", "شيكات صادرة مستحقة", "Cheques payable", "liability"),
    "vat_out": ("2200", "ضريبة مستحقة (مخرجات)", "VAT payable (output)", "liability"),
    "loans": ("2300", "القروض", "Loans", "liability"),
    "capital": ("3100", "رأس المال", "Owner capital", "equity"),
    "drawings": ("3200", "مسحوبات المالك", "Owner drawings", "equity"),
    "opening": ("3300", "أرصدة افتتاحية", "Opening balances", "equity"),
    "pre_system": ("3900", "مبالغ قبل استخدام الصندوق", "Amounts before cash tracking", "equity"),
    "sales": ("4100", "المبيعات", "Sales", "revenue"),
    "sales_returns": ("4200", "مردودات المبيعات", "Sales returns", "revenue"),
    "other_income": ("4900", "إيرادات أخرى", "Other income", "revenue"),
    "fx": ("4950", "فروقات العملة", "Exchange differences", "revenue"),
    "cogs": ("5100", "تكلفة البضاعة المباعة", "Cost of goods sold", "expense"),
    "inventory_adj": ("5200", "فروقات جرد وتسويات مخزون", "Stock adjustments & count differences", "expense"),
    "other_expense": ("6900", "مصاريف أخرى", "Other expenses", "expense"),
}
EXPENSE_NAMES = {"Rent": "إيجار", "Salaries": "رواتب", "Utilities": "كهربا وماي", "Marketing": "تسويق", "Logistics": "نقل وتوصيل",
                 "Insurance": "تأمين", "Other": "غيره"}
TYPES = ("asset", "liability", "equity", "revenue", "expense")
_last_build: dict[int, float] = {}


class _Chart:
    def __init__(self, db: Session, cid: int):
        self.db, self.cid = db, cid
        self.by_key = {a.system_key: a for a in db.scalars(select(GLAccount).where(GLAccount.company_id == cid)).all() if a.system_key}
        self.codes = set(db.scalars(select(GLAccount.code).where(GLAccount.company_id == cid)).all())

    def _make(self, key: str, code: str, name: str, name_en: str, typ: str) -> GLAccount:
        while code in self.codes:
            code = code + "1"
        a = GLAccount(company_id=self.cid, code=code, name=name, name_en=name_en, type=typ, system_key=key)
        self.db.add(a)
        self.db.flush()
        self.codes.add(code)
        self.by_key[key] = a
        return a

    def get(self, key: str) -> int:
        if key in self.by_key:
            return self.by_key[key].id
        if key in CHART:
            code, ar, en, typ = CHART[key]
            return self._make(key, code, ar, en, typ).id
        if key.startswith("money:"):
            acc = self.db.get(Account, int(key.split(":")[1]))
            base = CHART["cash" if acc.kind == "cash" else "bank"][0]
            return self._make(key, f"{base}-{acc.id}", acc.name, acc.name, "asset").id
        if key.startswith("expense:"):
            cat = key.split(":", 1)[1]
            n = sum(1 for k in self.by_key if k.startswith("expense:")) + 1
            return self._make(key, f"6{n:03d}", EXPENSE_NAMES.get(cat, cat), cat, "expense").id
        raise KeyError(key)


def ensure_chart(db: Session, cid: int) -> None:
    ch = _Chart(db, cid)
    for key in CHART:
        ch.get(key)
    db.commit()


def rebuild(db: Session, cid: int, force: bool = False) -> None:
    """Regenerate every automatic journal entry from the documents (manual entries are untouched)."""
    if not force and time.time() - _last_build.get(cid, 0) < 1.5:  # absorbs the parallel requests of one page load
        return
    ch = _Chart(db, cid)
    for key in CHART:
        ch.get(key)
    db.execute(delete(JournalLine).where(JournalLine.entry_id.in_(select(JournalEntry.id).where(JournalEntry.company_id == cid, JournalEntry.source == "auto"))))
    db.execute(delete(JournalEntry).where(JournalEntry.company_id == cid, JournalEntry.source == "auto"))
    entries: list[tuple[dict, list[tuple[int, float, float, str | None]]]] = []

    def E(d: date, memo: str, stype: str, sid: int | None, lines: list[tuple[str, float, float]], branch: int | None = None) -> None:
        ls = [(ch.get(k) if isinstance(k, str) else k, round(dr, 2), round(cr, 2), None) for k, dr, cr in lines if abs(dr) > 0.004 or abs(cr) > 0.004]
        if not ls:
            return
        diff = round(sum(x[1] for x in ls) - sum(x[2] for x in ls), 2)
        if abs(diff) >= 0.01:  # rounding / exchange difference keeps the entry balanced
            ls.append((ch.get("fx"), 0 if diff > 0 else -diff, diff if diff > 0 else 0, "rounding / exchange difference"))
        entries.append(({"company_id": cid, "entry_date": d, "memo": memo[:300], "source": "auto", "source_type": stype, "source_id": sid,
                         "branch_id": branch}, ls))

    money_key = lambda account_id: f"money:{account_id}" if account_id else "pre_system"  # noqa: E731

    # sales orders: revenue, VAT, receivable; cost of goods when stock left a warehouse
    for o in db.scalars(select(SalesOrder).where(SalesOrder.company_id == cid, SalesOrder.status.in_(("confirmed", "delivered")))).all():
        r = o.exchange_rate or 1
        tax = (o.tax_amount or 0) * r
        E(o.order_date, f"Sale {o.number}", "sales_order", o.id, [("ar", o.total * r, 0), ("sales", 0, o.total * r - tax), ("vat_out", 0, tax)], o.branch_id)
        if o.warehouse_id and o.cost_total:
            E(o.order_date, f"Cost of {o.number}", "sales_order_cost", o.id, [("cogs", o.cost_total, 0), ("inventory", 0, o.cost_total)], o.branch_id)
    # invoices without an order (services, opening balances, recurring)
    for i in db.scalars(select(Invoice).where(Invoice.company_id == cid, Invoice.order_id.is_(None), Invoice.status != "cancelled")).all():
        r = i.exchange_rate or 1
        if i.number.startswith("OB"):
            E(i.issue_date, f"Opening balance {i.number}", "invoice", i.id, [("ar", i.total * r, 0), ("opening", 0, i.total * r)], i.branch_id)
        else:
            tax = (i.tax_amount or 0) * r
            E(i.issue_date, f"Invoice {i.number}", "invoice", i.id, [("ar", i.total * r, 0), ("sales", 0, i.total * r - tax), ("vat_out", 0, tax)], i.branch_id)
    # customer payments (cheques go to "under collection" until cleared)
    inv_rate = dict(db.execute(select(Invoice.id, Invoice.exchange_rate).where(Invoice.company_id == cid)).all())
    # cheque payments recorded before cheques were tracked have no cheque behind them: treat them as already collected
    from app.models import Cheque
    cheque_pay_ids = set(db.scalars(select(Cheque.payment_id).where(Cheque.company_id == cid, Cheque.payment_id.is_not(None))).all())
    cheque_numbers = set(db.scalars(select(Payment.number).where(Payment.id.in_(cheque_pay_ids))).all()) if cheque_pay_ids else set()
    for p in db.scalars(select(Payment).where(Payment.company_id == cid, Payment.status != "bounced")).all():
        ar_side = p.amount * (inv_rate.get(p.invoice_id) or 1)
        cash_side = p.amount * (p.exchange_rate or inv_rate.get(p.invoice_id) or 1)
        tracked_cheque = p.method == "cheque" and (p.id in cheque_pay_ids or (p.number and p.number in cheque_numbers))
        dr = "cheques_in" if tracked_cheque else money_key(p.account_id)
        E(p.paid_at.date(), f"Receipt {p.number or ''}", "payment", p.id, [(dr, cash_side, 0), ("ar", 0, ar_side)])
    # returns
    for n in db.scalars(select(CreditNote).where(CreditNote.company_id == cid)).all():
        r = n.exchange_rate or 1
        E(n.note_date, f"Return {n.number}", "credit_note", n.id,
          [("sales_returns", n.subtotal * r, 0), ("vat_out", n.tax_amount * r, 0), ("ar", 0, n.total * r)])
        if n.warehouse_id and n.cost_total:
            E(n.note_date, f"Stock back {n.number}", "credit_note_cost", n.id, [("inventory", n.cost_total, 0), ("cogs", 0, n.cost_total)])
    # purchases received
    for po in db.scalars(select(PurchaseOrder).where(PurchaseOrder.company_id == cid, PurchaseOrder.status == "received")).all():
        r = po.exchange_rate or 1
        tax = (po.tax_amount or 0) * r
        E(po.received_on or po.order_date, f"Purchase {po.number}", "purchase", po.id,
          [("inventory", po.total * r - tax, 0), ("vat_in", tax, 0), ("ap", 0, po.total * r)], po.branch_id)
    for s in db.scalars(select(Supplier).where(Supplier.company_id == cid, Supplier.opening_balance != 0)).all():
        E(s.created_at.date() if s.created_at else date.today(), f"Opening balance {s.name}", "supplier_opening", s.id,
          [("opening", s.opening_balance, 0), ("ap", 0, s.opening_balance)])
    # goods sent back to suppliers: they owe us the credit; the stock leaves at cost; the difference is a gain / loss
    from app.models.stock import SupplierReturn
    for sr in db.scalars(select(SupplierReturn).where(SupplierReturn.company_id == cid)).all():
        lines = [("ap", sr.total, 0)]
        if sr.cost_total:
            lines.append(("inventory", 0, sr.cost_total))
        diff = round(sr.total - (sr.cost_total or 0), 2)
        if diff > 0:
            lines.append(("inventory_adj", 0, diff))
        elif diff < 0:
            lines.append(("inventory_adj", -diff, 0))
        E(sr.return_date, f"Return to supplier {sr.number}", "supplier_return", sr.id, lines)
    for sp in db.scalars(select(SupplierPayment).where(SupplierPayment.company_id == cid, SupplierPayment.status == "done")).all():
        v = sp.amount * (sp.exchange_rate or 1)
        cr = "cheques_out" if sp.method == "cheque" else money_key(sp.account_id)
        E(sp.paid_at, f"Payment {sp.number}", "supplier_payment", sp.id, [("ap", v, 0), (cr, 0, v)])
    # payroll: gross salary is the expense; net leaves the account; advance deductions settle employee advances
    salary_tx = {t.expense_id: t for t in db.scalars(select(Transaction).where(Transaction.company_id == cid, Transaction.kind == "salary")).all()}
    for e in db.scalars(select(Expense).where(Expense.company_id == cid, Expense.approval_status != "rejected")).all():
        if e.approval_status == "pending":
            continue
        if e.id in salary_tx:
            t = salary_tx[e.id]
            net = abs(t.base_amount if t.base_amount is not None else t.amount)
            E(e.expense_date, f"Payroll {e.description or ''}", "payroll", e.id,
              [(f"expense:{e.category}", e.amount, 0), (money_key(t.account_id), 0, net), ("advances", 0, e.amount - net)], e.branch_id)
            continue
        tax = e.tax_amount or 0
        credit = money_key(e.account_id) if e.is_paid else "ap"
        E(e.expense_date, f"{e.category} {e.description or ''}".strip(), "expense", e.id,
          [(f"expense:{e.category}", e.amount - tax, 0), ("vat_in", tax, 0), (credit, 0, e.amount)], e.branch_id)
    # cash & bank movements that aren't covered by a document above
    for t in db.scalars(select(Transaction).where(Transaction.company_id == cid, Transaction.kind.in_(
            ("refund", "transfer", "cheque_cleared", "other_in", "other_out", "advance")))).all():
        v = t.base_amount if t.base_amount is not None else t.amount
        m = f"money:{t.account_id}"
        memo = f"{t.number or ''} {t.party_name or t.description or ''}".strip()
        if t.kind == "refund":
            E(t.tx_date, memo, "tx", t.id, [("ar", -v, 0), (m, 0, -v)])
        elif t.kind == "transfer":
            E(t.tx_date, memo, "tx", t.id, [(m, v, 0), ("transit", 0, v)] if v > 0 else [("transit", -v, 0), (m, 0, -v)])
        elif t.kind == "cheque_cleared":
            E(t.tx_date, memo, "tx", t.id, [(m, v, 0), ("cheques_in", 0, v)] if v > 0 else [("cheques_out", -v, 0), (m, 0, -v)])
        elif t.kind == "advance":
            E(t.tx_date, memo, "tx", t.id, [("advances", -v, 0), (m, 0, -v)])
        else:
            counter = t.gl_account_id  # any account of the chart (system or custom), chosen on the voucher
            if t.kind == "other_in":
                E(t.tx_date, memo, "tx", t.id, [(m, v, 0), (counter or "other_income", 0, v)])
            else:
                E(t.tx_date, memo, "tx", t.id, [(counter or "other_expense", -v, 0), (m, 0, -v)])
    # opening balances of cash/bank accounts (converted at today's rate)
    from app.services import currency as fx
    for a in db.scalars(select(Account).where(Account.company_id == cid, Account.opening_balance != 0)).all():
        v = a.opening_balance * fx.rate(db, cid, a.currency)
        E(a.created_at.date() if a.created_at else date.today(), f"Opening balance {a.name}", "account_opening", a.id,
          [(f"money:{a.id}", v, 0), ("opening", 0, v)] if v > 0 else [("opening", -v, 0), (f"money:{a.id}", 0, -v)])
    # stock adjustments (valued at the product's current cost)
    costs = dict(db.execute(select(Product.id, Product.cost_price).where(Product.company_id == cid)).all())
    # adjustments / counts, stock written off (damaged, expired, lost in transit) and restored stock
    write_off_types = ("adjustment", "damaged", "expired", "transfer_loss", "restore")
    for mv in db.scalars(select(StockMovement).where(StockMovement.company_id == cid, StockMovement.movement_type.in_(write_off_types))).all():
        ref = mv.reference or ""
        if ref.startswith("cancel "):
            continue
        v = mv.quantity * (mv.unit_cost if mv.unit_cost is not None else (costs.get(mv.product_id) or 0))  # cost at the time of the move
        key = "opening" if ref.startswith("Opening stock") else "inventory_adj"
        label = {"damaged": "Damaged stock written off", "expired": "Expired stock written off", "transfer_loss": "Lost in transfer",
                 "restore": "Stock restored"}.get(mv.movement_type, "Stock adjustment")
        E(mv.occurred_at.date(), f"{label} {ref}".strip(), "stock_adjustment", mv.id,
          [("inventory", v, 0), (key, 0, v)] if v > 0 else [(key, -v, 0), ("inventory", 0, -v)])

    _insert(db, entries)
    # reconcile with the physical stock value and with supplier balances recorded before the system tracked them
    today = date.today()
    gl_inv = balance_of(db, cid, ch.get("inventory"))
    from app.services.analytics import inventory_value
    actual_inv = inventory_value(db, cid)
    diff = round(actual_inv - gl_inv, 2)
    if abs(diff) >= 0.01:
        E(today, "Inventory value adjustment (stock on hand × cost)", "reconcile_inventory", None,
          [("inventory", diff, 0), ("opening", 0, diff)] if diff > 0 else [("opening", -diff, 0), ("inventory", 0, -diff)])
    from app.services.analytics import payables
    gl_ap = -balance_of(db, cid, ch.get("ap"))
    ap_diff = round(gl_ap - payables(db, cid), 2)
    if abs(ap_diff) >= 0.01:
        E(today, "Supplier payments made before the system", "reconcile_ap", None,
          [("ap", ap_diff, 0), ("pre_system", 0, ap_diff)] if ap_diff > 0 else [("pre_system", -ap_diff, 0), ("ap", 0, -ap_diff)])
    _insert(db, entries)
    db.commit()
    _last_build[cid] = time.time()


def _insert(db: Session, entries: list) -> None:
    if not entries:
        return
    ids = db.execute(insert(JournalEntry).returning(JournalEntry.id, sort_by_parameter_order=True), [e for e, _ in entries]).scalars().all()
    rows = [{"company_id": e["company_id"], "entry_id": eid, "account_id": a, "debit": dr, "credit": cr, "description": desc}
            for eid, (e, ls) in zip(ids, entries) for a, dr, cr, desc in ls]
    db.execute(insert(JournalLine), rows)
    entries.clear()


def balance_of(db: Session, cid: int, account_id: int, until: date | None = None, since: date | None = None) -> float:
    """Debit minus credit."""
    stmt = select(func.coalesce(func.sum(JournalLine.debit - JournalLine.credit), 0)).join(JournalEntry, JournalEntry.id == JournalLine.entry_id)\
        .where(JournalLine.company_id == cid, JournalLine.account_id == account_id)
    if until:
        stmt = stmt.where(JournalEntry.entry_date <= until)
    if since:
        stmt = stmt.where(JournalEntry.entry_date >= since)
    return float(db.scalar(stmt) or 0)


def account_totals(db: Session, cid: int, start: date | None = None, end: date | None = None) -> dict[int, tuple[float, float]]:
    stmt = select(JournalLine.account_id, func.sum(JournalLine.debit), func.sum(JournalLine.credit)).join(JournalEntry, JournalEntry.id == JournalLine.entry_id)\
        .where(JournalLine.company_id == cid)
    if start:
        stmt = stmt.where(JournalEntry.entry_date >= start)
    if end:
        stmt = stmt.where(JournalEntry.entry_date <= end)
    return {a: (float(d or 0), float(c or 0)) for a, d, c in db.execute(stmt.group_by(JournalLine.account_id)).all()}


def integrity_check(db: Session, cid: int) -> dict:
    """Accounting integrity audit: structural invariants (every entry balances) plus how well the ledger ties to
    the sub-ledgers it's supposed to summarize (receivables, payables, inventory). Run after `rebuild`, which
    already plugs small timing/rounding gaps automatically — a LARGE gap here means something is actually wrong
    upstream (a costing bug, a document posted with the wrong date…), not just rounding, and is worth investigating
    even though the books still balance to the last cent."""
    rebuild(db, cid)
    checks = []

    unbalanced = db.execute(
        select(JournalEntry.id, JournalEntry.memo, func.sum(JournalLine.debit), func.sum(JournalLine.credit))
        .join(JournalLine, JournalLine.entry_id == JournalEntry.id).where(JournalEntry.company_id == cid)
        .group_by(JournalEntry.id, JournalEntry.memo).having(func.abs(func.sum(JournalLine.debit) - func.sum(JournalLine.credit)) >= 0.01)
    ).all()
    checks.append({"check": "Every journal entry balances (debits = credits)", "ok": not unbalanced,
                   "detail": [{"entry_id": e, "memo": m, "debit": round(float(d), 2), "credit": round(float(c), 2)} for e, m, d, c in unbalanced[:20]]})

    ch = _Chart(db, cid)
    from app.services.analytics import inventory_value, payables

    def tie(key: str, label: str, expected: float, sign: int = 1) -> None:
        gl = sign * balance_of(db, cid, ch.get(key))
        diff = round(gl - expected, 2)
        threshold = max(1.0, abs(expected) * 0.005)  # 0.5% or 1 currency unit, whichever is bigger — tighter than rebuild's rounding plug
        checks.append({"check": f"{label} ties to the ledger", "ok": abs(diff) < threshold,
                       "detail": {"ledger_balance": round(gl, 2), "sub_ledger_total": round(expected, 2), "difference": diff}})

    from app.services.analytics import INVOICE_BALANCE_BASE, OPEN_INVOICE
    ar_total = float(db.scalar(select(func.coalesce(func.sum(INVOICE_BALANCE_BASE), 0)).where(
        Invoice.company_id == cid, Invoice.status.in_(OPEN_INVOICE))) or 0)
    # a confirmed/delivered order is recognised as receivable in the ledger the moment it's confirmed, even before
    # it's billed (see rebuild()) — so an unbilled order's total belongs in the receivable sub-ledger too
    unbilled = float(db.scalar(select(func.coalesce(func.sum(SalesOrder.total * func.coalesce(SalesOrder.exchange_rate, 1)), 0)).where(
        SalesOrder.company_id == cid, SalesOrder.status.in_(("confirmed", "delivered")),
        ~SalesOrder.id.in_(select(Invoice.order_id).where(Invoice.company_id == cid, Invoice.order_id.is_not(None))))) or 0)
    tie("ar", "Accounts receivable", ar_total + unbilled)
    tie("ap", "Accounts payable", payables(db, cid), sign=-1)
    tie("inventory", "Inventory", inventory_value(db, cid))

    healthy = all(c["ok"] for c in checks)
    return {"healthy": healthy, "checked_at": datetime.utcnow(), "checks": checks}


def trial_balance(db: Session, cid: int, start: date | None, end: date | None) -> dict:
    accounts = {a.id: a for a in db.scalars(select(GLAccount).where(GLAccount.company_id == cid)).all()}
    opening = account_totals(db, cid, None, date.fromordinal(start.toordinal() - 1)) if start else {}
    period = account_totals(db, cid, start, end)
    rows = []
    for aid in sorted(set(opening) | set(period), key=lambda i: accounts[i].code):
        a = accounts[aid]
        od, oc = opening.get(aid, (0, 0))
        pd, pc = period.get(aid, (0, 0))
        close = od - oc + pd - pc
        rows.append({"account_id": aid, "code": a.code, "name": a.name, "name_en": a.name_en, "type": a.type, "opening": round(od - oc, 2),
                     "debit": round(pd, 2), "credit": round(pc, 2), "closing_debit": round(max(close, 0), 2), "closing_credit": round(max(-close, 0), 2)})
    return {"rows": rows, "total_debit": round(sum(r["debit"] for r in rows), 2), "total_credit": round(sum(r["credit"] for r in rows), 2),
            "total_closing_debit": round(sum(r["closing_debit"] for r in rows), 2), "total_closing_credit": round(sum(r["closing_credit"] for r in rows), 2)}


def balance_sheet(db: Session, cid: int, as_of: date) -> dict:
    accounts = {a.id: a for a in db.scalars(select(GLAccount).where(GLAccount.company_id == cid)).all()}
    totals = account_totals(db, cid, None, as_of)
    groups: dict[str, list] = defaultdict(list)
    earnings = 0.0
    for aid, (d, c) in totals.items():
        a = accounts[aid]
        if a.type in ("revenue", "expense"):
            earnings += c - d
            continue
        amount = d - c if a.type == "asset" else c - d
        if abs(amount) >= 0.005:
            groups[a.type].append({"account_id": aid, "code": a.code, "name": a.name, "name_en": a.name_en, "amount": round(amount, 2)})
    for g in groups.values():
        g.sort(key=lambda r: r["code"])
    assets = round(sum(r["amount"] for r in groups["asset"]), 2)
    liabilities = round(sum(r["amount"] for r in groups["liability"]), 2)
    equity = round(sum(r["amount"] for r in groups["equity"]) + earnings, 2)
    return {"as_of": as_of, "assets": groups["asset"], "liabilities": groups["liability"], "equity": groups["equity"],
            "retained_earnings": round(earnings, 2), "total_assets": assets, "total_liabilities": liabilities, "total_equity": equity,
            "balanced": abs(assets - liabilities - equity) < 0.05}


def income_statement(db: Session, cid: int, start: date, end: date) -> dict:
    accounts = {a.id: a for a in db.scalars(select(GLAccount).where(GLAccount.company_id == cid)).all()}
    rev, exp = [], []
    for aid, (d, c) in account_totals(db, cid, start, end).items():
        a = accounts[aid]
        if a.type == "revenue":
            rev.append({"code": a.code, "name": a.name, "name_en": a.name_en, "amount": round(c - d, 2)})
        elif a.type == "expense":
            exp.append({"code": a.code, "name": a.name, "name_en": a.name_en, "amount": round(d - c, 2)})
    rev.sort(key=lambda r: r["code"])
    exp.sort(key=lambda r: r["code"])
    tr, te = round(sum(r["amount"] for r in rev), 2), round(sum(r["amount"] for r in exp), 2)
    return {"start": start, "end": end, "revenue": rev, "expenses": exp, "total_revenue": tr, "total_expenses": te, "net_profit": round(tr - te, 2)}


def account_ledger(db: Session, cid: int, account_id: int, start: date | None, end: date | None) -> dict:
    a = db.get(GLAccount, account_id)
    if not a or a.company_id != cid:
        raise HTTPException(404, "Account not found")
    opening = balance_of(db, cid, a.id, until=date.fromordinal(start.toordinal() - 1)) if start else 0.0
    stmt = select(JournalEntry, JournalLine).join(JournalLine, JournalLine.entry_id == JournalEntry.id).where(JournalLine.account_id == a.id)
    if start:
        stmt = stmt.where(JournalEntry.entry_date >= start)
    if end:
        stmt = stmt.where(JournalEntry.entry_date <= end)
    rows, bal = [], opening
    for e, ln in db.execute(stmt.order_by(JournalEntry.entry_date, JournalEntry.id)).all():
        bal += ln.debit - ln.credit
        rows.append({"entry_id": e.id, "date": e.entry_date, "memo": e.memo, "source": e.source, "source_type": e.source_type, "source_id": e.source_id,
                     "debit": ln.debit, "credit": ln.credit, "balance": round(bal, 2)})
    return {"account": {"id": a.id, "code": a.code, "name": a.name, "name_en": a.name_en, "type": a.type}, "opening": round(opening, 2),
            "closing": round(bal, 2), "rows": rows}
