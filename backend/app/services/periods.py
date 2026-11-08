"""Accounting periods (months). Documents dated inside a CLOSED month can't be created, changed or deleted."""
from datetime import date, datetime

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.control import AccountingPeriod


def key(d: date) -> str:
    return f"{d.year:04d}-{d.month:02d}"


def is_closed(db: Session, cid: int, d: date | datetime | None) -> bool:
    if d is None:
        return False
    if isinstance(d, datetime):
        d = d.date()
    return bool(db.scalar(select(AccountingPeriod.id).where(AccountingPeriod.company_id == cid, AccountingPeriod.period == key(d),
                                                           AccountingPeriod.status == "CLOSED")))


def check_open(db: Session, cid: int, d: date | datetime | None) -> None:
    if is_closed(db, cid, d):
        raise HTTPException(409, f"The accounting period {key(d if isinstance(d, date) else d.date())} is closed. Post an adjustment in an open period instead.")


def months_between(first: date, last: date) -> list[str]:
    out, y, m = [], first.year, first.month
    while (y, m) <= (last.year, last.month):
        out.append(f"{y:04d}-{m:02d}")
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


def listing(db: Session, cid: int) -> list[dict]:
    """Every month from the first document to this month, with its status (months never closed are OPEN)."""
    from sqlalchemy import func
    from app.models import Expense, Invoice, SalesOrder
    firsts = [db.scalar(select(func.min(col)).where(model.company_id == cid)) for model, col in
              ((Invoice, Invoice.issue_date), (SalesOrder, SalesOrder.order_date), (Expense, Expense.expense_date))]
    firsts = [f if isinstance(f, date) else date.fromisoformat(str(f)[:10]) for f in firsts if f]
    first = min(firsts) if firsts else date.today()
    rows = {p.period: p for p in db.scalars(select(AccountingPeriod).where(AccountingPeriod.company_id == cid)).all()}
    out = []
    for k in reversed(months_between(first, date.today())):
        p = rows.get(k)
        out.append({"period": k, "status": p.status if p else "OPEN", "closed_by": p.closed_by if p else None,
                    "closed_at": p.closed_at if p else None, "note": p.note if p else None})
    return out


def _row(db: Session, cid: int, period: str) -> AccountingPeriod:
    try:
        start = date.fromisoformat(period + "-01")
    except ValueError:
        raise HTTPException(400, "Period must look like 2026-09")
    end = (date(start.year + (start.month == 12), start.month % 12 + 1, 1)).toordinal() - 1
    p = db.scalar(select(AccountingPeriod).where(AccountingPeriod.company_id == cid, AccountingPeriod.period == period))
    if not p:
        p = AccountingPeriod(company_id=cid, period=period, start_date=start, end_date=date.fromordinal(end))
        db.add(p)
    return p


def close(db: Session, user, period: str, note: str | None = None) -> AccountingPeriod:
    from app.core.audit import log_event
    p = _row(db, user.company_id, period)
    if p.start_date > date.today():
        raise HTTPException(400, "A future month can't be closed")
    if p.status == "CLOSED":
        raise HTTPException(400, "This period is already closed")
    p.status, p.closed_by, p.closed_at, p.note = "CLOSED", user.full_name, datetime.utcnow(), note
    db.flush()
    log_event(db, user.company_id, "period_close", "accounting_periods", label=period, user_id=user.id, user_name=user.full_name, note=note)
    return p


def reopen(db: Session, user, period: str, reason: str) -> AccountingPeriod:
    from app.core.audit import log_event
    if not (reason or "").strip():
        raise HTTPException(400, "Write why the period is reopened")
    p = _row(db, user.company_id, period)
    if p.status != "CLOSED":
        raise HTTPException(400, "This period is not closed")
    p.status, p.note = "OPEN", reason
    db.flush()
    log_event(db, user.company_id, "period_reopen", "accounting_periods", label=period, user_id=user.id, user_name=user.full_name, note=reason)
    return p
