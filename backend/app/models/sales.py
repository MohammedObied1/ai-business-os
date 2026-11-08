from datetime import date, datetime

from sqlalchemy import Date, DateTime, Float, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TenantMixin, TimestampMixin


class SalesOrder(Base, TenantMixin, TimestampMixin):
    __tablename__ = "sales_orders"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    number: Mapped[str] = mapped_column(String(50), index=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id"), index=True)
    warehouse_id: Mapped[int | None] = mapped_column(ForeignKey("warehouses.id"))
    status: Mapped[str] = mapped_column(String(30), default="draft")  # quotation/draft/confirmed/delivered/cancelled
    order_date: Mapped[date] = mapped_column(Date, default=date.today, index=True)
    discount_pct: Mapped[float] = mapped_column(Float, default=0)
    subtotal: Mapped[float] = mapped_column(Float, default=0)
    total: Mapped[float] = mapped_column(Float, default=0)
    cost_total: Mapped[float] = mapped_column(Float, default=0)
    salesperson_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    tax_rate: Mapped[float] = mapped_column(Float, default=0)
    tax_amount: Mapped[float] = mapped_column(Float, default=0)
    branch_id: Mapped[int | None] = mapped_column(ForeignKey("branches.id"))
    source: Mapped[str] = mapped_column(String(20), default="manual")  # manual / pos / online / field
    notes: Mapped[str | None] = mapped_column(String(500))
    currency: Mapped[str | None] = mapped_column(String(10))  # None = company currency
    exchange_rate: Mapped[float] = mapped_column(Float, default=1)  # base units per 1 unit of `currency`
    client_ref: Mapped[str | None] = mapped_column(String(64), index=True)  # offline POS de-duplication
    approval_reason: Mapped[str | None] = mapped_column(String(200))
    approved_by: Mapped[str | None] = mapped_column(String(200))

    items: Mapped[list["SalesOrderItem"]] = relationship(cascade="all, delete-orphan", lazy="selectin")


class SalesOrderItem(Base, TenantMixin):
    __tablename__ = "sales_order_items"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("sales_orders.id", ondelete="CASCADE"), index=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), index=True)
    quantity: Mapped[float] = mapped_column(Float)
    unit_price: Mapped[float] = mapped_column(Float)
    unit_cost: Mapped[float] = mapped_column(Float, default=0)
    discount_pct: Mapped[float] = mapped_column(Float, default=0)
    line_total: Mapped[float] = mapped_column(Float)
    # how the line was entered, e.g. 2 × "كرتونة" at 90 (quantity/unit_price above are always in base units)
    uom_label: Mapped[str | None] = mapped_column(String(30))
    uom_qty: Mapped[float | None] = mapped_column(Float)
    uom_price: Mapped[float | None] = mapped_column(Float)


class Invoice(Base, TenantMixin, TimestampMixin):
    __tablename__ = "invoices"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    number: Mapped[str] = mapped_column(String(50), index=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id"), index=True)
    order_id: Mapped[int | None] = mapped_column(ForeignKey("sales_orders.id"))
    issue_date: Mapped[date] = mapped_column(Date, default=date.today, index=True)
    due_date: Mapped[date] = mapped_column(Date)
    total: Mapped[float] = mapped_column(Float)
    paid_amount: Mapped[float] = mapped_column(Float, default=0)
    status: Mapped[str] = mapped_column(String(20), default="open")  # open / partial / paid / overdue / cancelled
    subtotal: Mapped[float | None] = mapped_column(Float)  # before tax
    tax_amount: Mapped[float] = mapped_column(Float, default=0)
    credited_amount: Mapped[float] = mapped_column(Float, default=0)  # reduced by sales returns
    public_token: Mapped[str | None] = mapped_column(String(64), index=True)  # shareable link
    currency: Mapped[str | None] = mapped_column(String(10))
    exchange_rate: Mapped[float] = mapped_column(Float, default=1)
    branch_id: Mapped[int | None] = mapped_column(ForeignKey("branches.id"))
    recurring_id: Mapped[int | None] = mapped_column(Integer)
    description: Mapped[str | None] = mapped_column(String(300))  # for invoices without an order

    @property
    def balance(self) -> float:
        return round(self.total - self.paid_amount - (self.credited_amount or 0), 2)


class Payment(Base, TenantMixin, TimestampMixin):
    __tablename__ = "payments"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    invoice_id: Mapped[int] = mapped_column(ForeignKey("invoices.id", ondelete="CASCADE"), index=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id"))
    amount: Mapped[float] = mapped_column(Float)
    method: Mapped[str] = mapped_column(String(30), default="bank")  # cash / bank / card / cheque
    paid_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    reference: Mapped[str | None] = mapped_column(String(120))
    number: Mapped[str | None] = mapped_column(String(50), index=True)  # receipt voucher (سند قبض)
    account_id: Mapped[int | None] = mapped_column(ForeignKey("accounts.id"))
    status: Mapped[str] = mapped_column(String(20), default="done")  # done / pending_cheque / bounced
    exchange_rate: Mapped[float | None] = mapped_column(Float)  # invoice currency → base at the time of payment
    account_amount: Mapped[float | None] = mapped_column(Float)  # what landed in the cash/bank account, in its currency
