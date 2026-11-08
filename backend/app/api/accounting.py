"""Accountant's view: chart of accounts, journal, trial balance, balance sheet, income statement."""
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import require_permission
from app.core.pagination import page
from app.models import GLAccount, JournalEntry, JournalLine, User
from app.services import ledger
from app.services.numbering import next_number

router = APIRouter(prefix="/accounting", tags=["accounting"])


class GLAccountIn(BaseModel):
    code: str
    name: str
    name_en: str | None = None
    type: str
    is_active: bool = True


class JournalLineIn(BaseModel):
    account_id: int
    debit: float = 0
    credit: float = 0
    description: str | None = None


class JournalIn(BaseModel):
    entry_date: date
    memo: str
    lines: list[JournalLineIn]


def _fresh(db: Session, user: User, refresh: bool = False) -> None:
    ledger.rebuild(db, user.company_id, force=refresh)


@router.get("/accounts")
def chart(refresh: bool = False, user: User = Depends(require_permission("accounting:read")), db: Session = Depends(get_db)):
    _fresh(db, user, refresh)
    totals = ledger.account_totals(db, user.company_id)
    return [{"id": a.id, "code": a.code, "name": a.name, "name_en": a.name_en, "type": a.type, "system_key": a.system_key, "is_active": a.is_active,
             "balance": round(totals.get(a.id, (0, 0))[0] - totals.get(a.id, (0, 0))[1], 2)}
            for a in db.scalars(select(GLAccount).where(GLAccount.company_id == user.company_id).order_by(GLAccount.code)).all()]


@router.post("/accounts", status_code=201)
def add_account(payload: GLAccountIn, user: User = Depends(require_permission("accounting:write")), db: Session = Depends(get_db)):
    if payload.type not in ledger.TYPES:
        raise HTTPException(400, "Unknown account type")
    if db.scalar(select(GLAccount.id).where(GLAccount.company_id == user.company_id, GLAccount.code == payload.code.strip())):
        raise HTTPException(400, "This account code is already used")
    a = GLAccount(company_id=user.company_id, code=payload.code.strip(), name=payload.name.strip(), name_en=payload.name_en, type=payload.type,
                  is_active=payload.is_active)
    db.add(a)
    db.commit()
    return {"id": a.id}


@router.patch("/accounts/{account_id}")
def edit_account(account_id: int, payload: GLAccountIn, user: User = Depends(require_permission("accounting:write")), db: Session = Depends(get_db)):
    a = db.get(GLAccount, account_id)
    if not a or a.company_id != user.company_id:
        raise HTTPException(404, "Account not found")
    a.name, a.name_en, a.is_active = payload.name, payload.name_en, payload.is_active
    if not a.system_key:  # system accounts keep their code and type
        a.code, a.type = payload.code, payload.type
    db.commit()
    return {"id": a.id}


@router.get("/accounts/{account_id}/ledger")
def gl_ledger(account_id: int, start: date | None = None, end: date | None = None, user: User = Depends(require_permission("accounting:read")),
              db: Session = Depends(get_db)):
    _fresh(db, user)
    return ledger.account_ledger(db, user.company_id, account_id, start, end)


@router.get("/journal")
def journal(response: Response, source: str | None = None, start: date | None = None, end: date | None = None, offset: int = 0,
            limit: int = Query(50, le=1000), user: User = Depends(require_permission("accounting:read")), db: Session = Depends(get_db)):
    _fresh(db, user)
    stmt = select(JournalEntry).where(JournalEntry.company_id == user.company_id)
    if source:
        stmt = stmt.where(JournalEntry.source == source)
    if start:
        stmt = stmt.where(JournalEntry.entry_date >= start)
    if end:
        stmt = stmt.where(JournalEntry.entry_date <= end)
    names = {a.id: (a.code, a.name) for a in db.scalars(select(GLAccount).where(GLAccount.company_id == user.company_id)).all()}
    return [{"id": e.id, "date": e.entry_date, "number": e.number, "memo": e.memo, "source": e.source, "source_type": e.source_type,
             "source_id": e.source_id, "lines": [{"account_id": ln.account_id, "code": names[ln.account_id][0], "account": names[ln.account_id][1],
                                                  "debit": ln.debit, "credit": ln.credit, "description": ln.description} for ln in e.lines]}
            for e in page(db, stmt.order_by(JournalEntry.entry_date.desc(), JournalEntry.id.desc()), response, offset, limit)]


@router.post("/journal", status_code=201)
def add_journal(payload: JournalIn, user: User = Depends(require_permission("accounting:write")), db: Session = Depends(get_db)):
    lines = [ln for ln in payload.lines if ln.debit or ln.credit]
    if len(lines) < 2:
        raise HTTPException(400, "A journal entry needs at least two lines")
    if any(ln.debit < 0 or ln.credit < 0 or (ln.debit and ln.credit) for ln in lines):
        raise HTTPException(400, "Each line is either a debit or a credit, not negative")
    if round(sum(ln.debit for ln in lines), 2) != round(sum(ln.credit for ln in lines), 2):
        raise HTTPException(400, "Debits and credits must be equal")
    for ln in lines:
        a = db.get(GLAccount, ln.account_id)
        if not a or a.company_id != user.company_id:
            raise HTTPException(404, "Account not found")
    e = JournalEntry(company_id=user.company_id, entry_date=payload.entry_date, memo=payload.memo, source="manual",
                     number=next_number(db, JournalEntry, user.company_id, "JV"))
    db.add(e)
    db.flush()
    for ln in lines:
        db.add(JournalLine(company_id=user.company_id, entry_id=e.id, account_id=ln.account_id, debit=round(ln.debit, 2), credit=round(ln.credit, 2),
                           description=ln.description))
    db.commit()
    return {"id": e.id, "number": e.number}


@router.delete("/journal/{entry_id}", status_code=204)
def delete_journal(entry_id: int, user: User = Depends(require_permission("accounting:write")), db: Session = Depends(get_db)):
    e = db.get(JournalEntry, entry_id)
    if not e or e.company_id != user.company_id:
        raise HTTPException(404, "Entry not found")
    if e.source != "manual":
        raise HTTPException(400, "Automatic entries change by editing the original document")
    db.delete(e)
    db.commit()


@router.get("/integrity")
def integrity(user: User = Depends(require_permission("accounting:read")), db: Session = Depends(get_db)):
    """Accounting integrity audit: every journal entry balances, and receivables/payables/inventory tie to the ledger."""
    result = ledger.integrity_check(db, user.company_id)
    db.commit()  # rebuild() may have posted reconciliation entries
    return result


@router.get("/trial-balance")
def trial_balance(start: date | None = None, end: date | None = None, user: User = Depends(require_permission("accounting:read")), db: Session = Depends(get_db)):
    _fresh(db, user)
    return ledger.trial_balance(db, user.company_id, start, end)


@router.get("/balance-sheet")
def balance_sheet(as_of: date | None = None, user: User = Depends(require_permission("accounting:read")), db: Session = Depends(get_db)):
    _fresh(db, user)
    return ledger.balance_sheet(db, user.company_id, as_of or date.today())


@router.get("/income-statement")
def income_statement(start: date | None = None, end: date | None = None, user: User = Depends(require_permission("accounting:read")),
                     db: Session = Depends(get_db)):
    _fresh(db, user)
    from app.services.analytics import month_bounds
    s, e = (start, end) if start and end else month_bounds(date.today())
    return ledger.income_statement(db, user.company_id, s, e)


# ---------------------------------------------------------------- periods (month-end close)
class PeriodAction(BaseModel):
    note: str | None = None


@router.get("/periods")
def periods_list(user: User = Depends(require_permission("accounting:read")), db: Session = Depends(get_db)):
    from app.services import periods
    return periods.listing(db, user.company_id)


@router.post("/periods/{period}/close")
def period_close(period: str, payload: PeriodAction | None = None, user: User = Depends(require_permission("accounting.close_period")),
                 db: Session = Depends(get_db)):
    from app.services import periods
    periods.close(db, user, period, payload.note if payload else None)
    db.commit()
    return periods.listing(db, user.company_id)


@router.post("/periods/{period}/reopen")
def period_reopen(period: str, payload: PeriodAction, user: User = Depends(require_permission("accounting.close_period")),
                  db: Session = Depends(get_db)):
    from app.services import periods
    periods.reopen(db, user, period, payload.note or "")
    db.commit()
    return periods.listing(db, user.company_id)
