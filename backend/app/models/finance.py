from datetime import date

from sqlalchemy import Date, Float, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TenantMixin, TimestampMixin


class Expense(Base, TenantMixin, TimestampMixin):
    __tablename__ = "expenses"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    category: Mapped[str] = mapped_column(String(100), index=True)  # rent / salaries / marketing / utilities ...
    description: Mapped[str | None] = mapped_column(String(300))
    amount: Mapped[float] = mapped_column(Float)
    expense_date: Mapped[date] = mapped_column(Date, default=date.today, index=True)
    is_paid: Mapped[bool] = mapped_column(default=True)
    account_id: Mapped[int | None] = mapped_column(ForeignKey("accounts.id"))
    branch_id: Mapped[int | None] = mapped_column(ForeignKey("branches.id"))
    tax_amount: Mapped[float] = mapped_column(Float, default=0)  # VAT paid on the expense (claimable)
    supplier_id: Mapped[int | None] = mapped_column(ForeignKey("suppliers.id"))
    approval_status: Mapped[str] = mapped_column(String(20), default="approved")  # pending / approved / rejected
    requested_by: Mapped[str | None] = mapped_column(String(200))
