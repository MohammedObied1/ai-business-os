"""Closed accounting periods can't be changed.

Before every flush: a financial document dated inside a CLOSED month can't be created or deleted, and its financial
fields (amount, date, party, cancellation…) can't change. Operational fields stay editable (an invoice's paid amount
goes up when a payment is received today; automation marks it overdue). Corrections go in an open month as
adjustments. Automatic journal entries are rebuilt from the (locked) documents, so they are exempt.
"""
from datetime import date, datetime

from sqlalchemy import event, inspect, select
from sqlalchemy.orm import Session

# table → (date field, locked fields). A change to any locked field (or a create / delete) is checked.
LOCKED: dict[str, tuple[str, set[str]]] = {
    "invoices": ("issue_date", {"issue_date", "total", "subtotal", "tax_amount", "customer_id", "currency", "exchange_rate", "order_id", "status"}),
    "payments": ("paid_at", {"paid_at", "amount", "account_amount", "invoice_id", "method", "exchange_rate", "account_id"}),
    "sales_orders": ("order_date", {"order_date", "total", "subtotal", "discount_pct", "tax_amount", "cost_total", "customer_id", "warehouse_id", "status"}),
    "credit_notes": ("note_date", {"note_date", "total", "tax_amount", "invoice_id", "refunded"}),
    "expenses": ("expense_date", {"expense_date", "amount", "tax_amount", "category", "account_id", "is_paid"}),
    "transactions": ("tx_date", {"tx_date", "amount", "account_id", "base_amount", "gl_account_id"}),
    "supplier_payments": ("paid_at", {"paid_at", "amount", "account_amount", "po_id", "supplier_id"}),
    "purchase_orders": ("order_date", {"order_date", "total", "tax_amount", "supplier_id"}),
    "journal_entries": ("entry_date", {"entry_date", "memo"}),
}
# a status change only matters when it cancels / reverses the document
STATUS_LOCK = {"invoices": {"cancelled"}, "sales_orders": {"cancelled"}}


class PeriodClosed(Exception):
    def __init__(self, period: str):
        self.period = period
        super().__init__(f"The accounting period {period} is closed. Post an adjustment in an open period instead.")


def _day(v) -> date | None:
    if isinstance(v, datetime):
        return v.date()
    return v if isinstance(v, date) else None


@event.listens_for(Session, "before_flush")
def _check_closed_periods(session: Session, _ctx, _instances) -> None:
    candidates = []
    for obj, op in [(o, "new") for o in session.new] + [(o, "dirty") for o in session.dirty] + [(o, "deleted") for o in session.deleted]:
        table = getattr(obj, "__tablename__", None)
        if table not in LOCKED or getattr(obj, "company_id", None) is None:
            continue
        if table == "journal_entries" and getattr(obj, "source", "manual") != "manual":
            continue
        candidates.append((obj, op, table))
    if not candidates:
        return
    from app.models.control import AccountingPeriod
    closed_cache: dict[int, set[str]] = {}

    def closed(cid: int) -> set[str]:
        if cid not in closed_cache:
            with session.no_autoflush:
                closed_cache[cid] = set(session.execute(select(AccountingPeriod.period).where(
                    AccountingPeriod.company_id == cid, AccountingPeriod.status == "CLOSED")).scalars())
        return closed_cache[cid]

    for obj, op, table in candidates:
        periods = closed(obj.company_id)
        if not periods:
            continue
        date_field, locked = LOCKED[table]
        days = []
        if op in ("new", "deleted"):
            days.append(_day(getattr(obj, date_field, None)) or date.today())
        else:
            state = inspect(obj)
            changed = {a.key for a in state.mapper.column_attrs if a.key in locked and state.attrs[a.key].history.has_changes()}
            if "status" in changed and table in STATUS_LOCK:
                if getattr(obj, "status", None) not in STATUS_LOCK[table]:
                    changed.discard("status")
            elif "status" in changed:
                changed.discard("status")
            if not changed:
                continue
            h = state.attrs[date_field].history
            days += [_day(v) for v in (h.deleted or [])] + [_day(getattr(obj, date_field, None))]
        for d in days:
            if d and f"{d.year:04d}-{d.month:02d}" in periods:
                raise PeriodClosed(f"{d.year:04d}-{d.month:02d}")
