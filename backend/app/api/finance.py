from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import branch_scope, has_permission, require_permission
from app.core.pagination import page
from app.models import Company, Expense, Transaction, User
from app.services.money import get_account, post
from app.schemas.finance import CashflowPoint, ExpenseIn, ExpenseOut, FinanceSummary
from app.services import analytics

router = APIRouter(prefix="/finance", tags=["finance"])


@router.get("/expenses", response_model=list[ExpenseOut])
def list_expenses(response: Response, category: str | None = None, q: str | None = None, offset: int = 0, limit: int = Query(200, le=5000),
                  user: User = Depends(require_permission("finance:read")), db: Session = Depends(get_db)):
    stmt = select(Expense).where(Expense.company_id == user.company_id)
    if (scope := branch_scope(user)):
        stmt = stmt.where((Expense.branch_id == scope) | Expense.branch_id.is_(None))
    if category:
        stmt = stmt.where(Expense.category == category)
    if q:
        stmt = stmt.where(Expense.category.ilike(f"%{q}%") | Expense.description.ilike(f"%{q}%"))
    return page(db, stmt.order_by(Expense.expense_date.desc(), Expense.id.desc()), response, offset, limit)


@router.post("/expenses", response_model=ExpenseOut, status_code=201)
def create_expense(payload: ExpenseIn, user: User = Depends(require_permission("finance:write")), db: Session = Depends(get_db)):
    if payload.amount <= 0:
        raise HTTPException(400, "Amount must be greater than zero")
    e = Expense(company_id=user.company_id, **payload.model_dump(exclude_none=True))
    e.branch_id = e.branch_id or branch_scope(user)
    e.requested_by = user.full_name
    from app.services import approvals
    if approvals.needs(db, user, "large_expense", e.amount):
        e.approval_status = "pending"  # nothing leaves the cash box until a manager approves
    db.add(e)
    db.flush()
    if e.approval_status == "pending":
        approvals.request(db, user, "large_expense", "expenses", e.id, f"{e.category} {e.amount:,.2f}", e.amount, e.description)
    if e.is_paid and e.approval_status == "approved":
        acc = get_account(db, user.company_id, payload.account_id)
        e.account_id = acc.id
        post(db, user.company_id, acc.id, -e.amount, "expense", prefix="PV", tx_date=e.expense_date, expense_id=e.id,
             description=f"{e.category}{' - ' + e.description if e.description else ''}", user_id=user.id)
    db.commit()
    db.refresh(e)
    return e


@router.delete("/expenses/{expense_id}", status_code=204)
def delete_expense(expense_id: int, user: User = Depends(require_permission("finance:write")), db: Session = Depends(get_db)):
    e = db.get(Expense, expense_id)
    if not e or e.company_id != user.company_id:
        raise HTTPException(404, "Expense not found")
    if db.scalar(select(Transaction.id).where(Transaction.expense_id == e.id, Transaction.kind == "salary")):
        raise HTTPException(400, "Payroll expenses are managed from the payroll page")
    for t in db.scalars(select(Transaction).where(Transaction.expense_id == e.id)).all():
        db.delete(t)
    db.delete(e)
    db.commit()


@router.get("/summary", response_model=FinanceSummary)
def summary(start: date | None = None, end: date | None = None, user: User = Depends(require_permission("finance:read")), db: Session = Depends(get_db)):
    cid = user.company_id
    if not start or not end:
        start, end = analytics.month_bounds(date.today())
    rev, cogs = analytics.revenue_between(db, cid, start, end)
    exp = analytics.expenses_between(db, cid, start, end)
    cf = analytics.cashflow_series(db, cid, 1)[0]
    net = rev - cogs - exp
    return FinanceSummary(period_start=start, period_end=end, revenue=round(rev, 2), cogs=round(cogs, 2), gross_profit=round(rev - cogs, 2), expenses=round(exp, 2),
                          net_profit=round(net, 2), margin_pct=round(net / rev * 100, 1) if rev else 0, receivables=round(analytics.receivables(db, cid), 2),
                          payables=round(analytics.payables(db, cid), 2), cash_in=cf["cash_in"], cash_out=cf["cash_out"])


@router.get("/cashflow", response_model=list[CashflowPoint])
def cashflow(months: int = 6, user: User = Depends(require_permission("finance:read")), db: Session = Depends(get_db)):
    return analytics.cashflow_series(db, user.company_id, months)


@router.get("/expenses-by-category")
def expenses_by_category(months: int = 1, user: User = Depends(require_permission("finance:read")), db: Session = Depends(get_db)):
    start = (date.today().replace(day=1) - timedelta(days=30 * (months - 1))).replace(day=1)
    rows = db.scalars(select(Expense).where(Expense.company_id == user.company_id, Expense.expense_date >= start)).all()
    agg: dict[str, float] = {}
    for r in rows:
        agg[r.category] = agg.get(r.category, 0) + r.amount
    return [{"category": k, "amount": round(v, 2)} for k, v in sorted(agg.items(), key=lambda x: -x[1])]


@router.patch("/expenses/{expense_id}", response_model=ExpenseOut)
def update_expense(expense_id: int, payload: ExpenseIn, user: User = Depends(require_permission("finance:write")), db: Session = Depends(get_db)):
    e = db.get(Expense, expense_id)
    if not e or e.company_id != user.company_id:
        raise HTTPException(404, "Expense not found")
    if db.scalar(select(Transaction.id).where(Transaction.expense_id == e.id, Transaction.kind == "salary")):
        raise HTTPException(400, "Payroll expenses are managed from the payroll page")
    for k, v in payload.model_dump(exclude_none=True).items():
        setattr(e, k, v)
    tx = db.scalar(select(Transaction).where(Transaction.expense_id == e.id))
    if tx:
        tx.amount, tx.tx_date = -e.amount, e.expense_date
        if payload.account_id:
            tx.account_id = get_account(db, user.company_id, payload.account_id).id
        tx.description = f"{e.category}{' - ' + e.description if e.description else ''}"
    db.commit()
    db.refresh(e)
    return e
