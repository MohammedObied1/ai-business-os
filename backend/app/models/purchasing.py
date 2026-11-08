from datetime import date

from sqlalchemy import Date, Float, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TenantMixin, TimestampMixin


class Supplier(Base, TenantMixin, TimestampMixin):
    __tablename__ = "suppliers"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(200), index=True)
    email: Mapped[str | None] = mapped_column(String(200))
    phone: Mapped[str | None] = mapped_column(String(50))
    lead_time_days: Mapped[int] = mapped_column(Integer, default=7)
    payment_terms_days: Mapped[int] = mapped_column(Integer, default=30)
    address: Mapped[str | None] = mapped_column(String(300))
    tax_number: Mapped[str | None] = mapped_column(String(80))
    opening_balance: Mapped[float] = mapped_column(Float, default=0)  # what we owed them before the system


class PurchaseOrder(Base, TenantMixin, TimestampMixin):
    __tablename__ = "purchase_orders"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    number: Mapped[str] = mapped_column(String(50), index=True)
    supplier_id: Mapped[int] = mapped_column(ForeignKey("suppliers.id"), index=True)
    warehouse_id: Mapped[int | None] = mapped_column(ForeignKey("warehouses.id"))
    # request (needs approval) / approved / ordered / received / cancelled
    status: Mapped[str] = mapped_column(String(30), default="request")
    order_date: Mapped[date] = mapped_column(Date, default=date.today, index=True)
    expected_date: Mapped[date | None] = mapped_column(Date)
    total: Mapped[float] = mapped_column(Float, default=0)
    paid_amount: Mapped[float] = mapped_column(Float, default=0)
    requested_by: Mapped[str | None] = mapped_column(String(100))  # user name or "AI Agent"
    approved_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    notes: Mapped[str | None] = mapped_column(String(500))
    tax_amount: Mapped[float] = mapped_column(Float, default=0)
    received_on: Mapped[date | None] = mapped_column(Date)
    supplier_invoice_no: Mapped[str | None] = mapped_column(String(80))
    currency: Mapped[str | None] = mapped_column(String(10))
    exchange_rate: Mapped[float] = mapped_column(Float, default=1)
    branch_id: Mapped[int | None] = mapped_column(ForeignKey("branches.id"))

    items: Mapped[list["PurchaseOrderItem"]] = relationship(cascade="all, delete-orphan", lazy="selectin")


class PurchaseOrderItem(Base, TenantMixin):
    __tablename__ = "purchase_order_items"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    po_id: Mapped[int] = mapped_column(ForeignKey("purchase_orders.id", ondelete="CASCADE"), index=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"))
    quantity: Mapped[float] = mapped_column(Float)
    unit_cost: Mapped[float] = mapped_column(Float)
    line_total: Mapped[float] = mapped_column(Float)
    batch: Mapped[str] = mapped_column(String(80), default="")
    expiry_date: Mapped[date | None] = mapped_column(Date)
    uom_label: Mapped[str | None] = mapped_column(String(30))
    uom_qty: Mapped[float | None] = mapped_column(Float)
