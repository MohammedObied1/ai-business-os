from datetime import date

from pydantic import BaseModel

from app.schemas.common import ORMModel


class ExpenseIn(BaseModel):
    category: str
    description: str | None = None
    amount: float
    expense_date: date | None = None
    is_paid: bool = True
    account_id: int | None = None
    tax_amount: float = 0
    supplier_id: int | None = None
    branch_id: int | None = None


class ExpenseOut(ORMModel):
    id: int
    category: str
    description: str | None = None
    amount: float
    expense_date: date
    is_paid: bool
    account_id: int | None = None
    tax_amount: float = 0
    supplier_id: int | None = None
    branch_id: int | None = None
    approval_status: str = "approved"
    requested_by: str | None = None


class FinanceSummary(BaseModel):
    period_start: date
    period_end: date
    revenue: float
    cogs: float
    gross_profit: float
    expenses: float
    net_profit: float
    margin_pct: float
    receivables: float
    payables: float
    cash_in: float
    cash_out: float


class CashflowPoint(BaseModel):
    month: str
    cash_in: float
    cash_out: float
    net: float
