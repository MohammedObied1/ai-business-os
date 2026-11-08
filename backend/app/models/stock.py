"""Inventory costing layers, non-available stock (reserved / in transit / damaged / expired), transfers and supplier returns.

`stock_levels` keeps meaning "available stock" so every existing screen and report stays correct; stock that is
not available lives in `stock_buckets` until it becomes available again (received, repaired) or is written off.
"""
from datetime import date, datetime

from sqlalchemy import Date, DateTime, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TenantMixin, TimestampMixin


class CostLayer(Base, TenantMixin):
    __tablename__ = "cost_layers"
    __table_args__ = (Index("ix_cost_layers_product_wh", "product_id", "warehouse_id", "qty_remaining"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id", ondelete="CASCADE"), index=True)
    warehouse_id: Mapped[int] = mapped_column(ForeignKey("warehouses.id", ondelete="CASCADE"))
    batch: Mapped[str] = mapped_column(String(80), default="")
    received_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    qty_in: Mapped[float] = mapped_column(Float)
    qty_remaining: Mapped[float] = mapped_column(Float)
    unit_cost: Mapped[float] = mapped_column(Float)
    movement_id: Mapped[int | None] = mapped_column(Integer)


class StockBucket(Base, TenantMixin):
    """Stock that exists but can't be sold: reserved (approved transfer), in_transit, damaged, expired."""

    __tablename__ = "stock_buckets"
    __table_args__ = (UniqueConstraint("warehouse_id", "product_id", "batch", "state", name="uq_stock_bucket"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id", ondelete="CASCADE"), index=True)
    warehouse_id: Mapped[int] = mapped_column(ForeignKey("warehouses.id", ondelete="CASCADE"))
    batch: Mapped[str] = mapped_column(String(80), default="")
    expiry_date: Mapped[date | None] = mapped_column(Date)
    state: Mapped[str] = mapped_column(String(20))  # reserved / in_transit / damaged / expired
    quantity: Mapped[float] = mapped_column(Float, default=0)
    unit_cost: Mapped[float] = mapped_column(Float, default=0)  # average cost of what sits here (in_transit keeps its value)


class StockTransfer(Base, TenantMixin, TimestampMixin):
    """DRAFT → REQUESTED → APPROVED → IN_TRANSIT → RECEIVED (or CANCELLED). Destination stock counts only when RECEIVED."""

    __tablename__ = "stock_transfers"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    number: Mapped[str] = mapped_column(String(40), index=True)
    from_warehouse_id: Mapped[int] = mapped_column(ForeignKey("warehouses.id"))
    to_warehouse_id: Mapped[int] = mapped_column(ForeignKey("warehouses.id"))
    status: Mapped[str] = mapped_column(String(20), default="DRAFT", index=True)
    note: Mapped[str | None] = mapped_column(Text)
    requested_by: Mapped[str | None] = mapped_column(String(200))
    approved_by: Mapped[str | None] = mapped_column(String(200))
    shipped_at: Mapped[datetime | None] = mapped_column(DateTime)
    received_at: Mapped[datetime | None] = mapped_column(DateTime)
    received_by: Mapped[str | None] = mapped_column(String(200))
    lines: Mapped[list["StockTransferLine"]] = relationship(cascade="all, delete-orphan", lazy="selectin", order_by="StockTransferLine.id")


class StockTransferLine(Base, TenantMixin):
    __tablename__ = "stock_transfer_lines"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    transfer_id: Mapped[int] = mapped_column(ForeignKey("stock_transfers.id", ondelete="CASCADE"), index=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"))
    batch: Mapped[str] = mapped_column(String(80), default="")  # empty = any batch (earliest expiry first)
    expiry_date: Mapped[date | None] = mapped_column(Date)
    quantity: Mapped[float] = mapped_column(Float)
    received_quantity: Mapped[float | None] = mapped_column(Float)
    unit_cost: Mapped[float | None] = mapped_column(Float)  # fixed when shipped


class SupplierReturn(Base, TenantMixin, TimestampMixin):
    """Goods sent back to a supplier: stock goes out at cost, the supplier owes us (reduces what we owe them)."""

    __tablename__ = "supplier_returns"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    number: Mapped[str] = mapped_column(String(40), index=True)
    supplier_id: Mapped[int] = mapped_column(ForeignKey("suppliers.id"))
    po_id: Mapped[int | None] = mapped_column(ForeignKey("purchase_orders.id"))
    warehouse_id: Mapped[int] = mapped_column(ForeignKey("warehouses.id"))
    return_date: Mapped[date] = mapped_column(Date, default=date.today, index=True)
    reason: Mapped[str | None] = mapped_column(Text)
    total: Mapped[float] = mapped_column(Float, default=0)  # value credited by the supplier
    cost_total: Mapped[float] = mapped_column(Float, default=0)  # value of the stock that left
    created_by: Mapped[str | None] = mapped_column(String(200))
    lines: Mapped[list["SupplierReturnLine"]] = relationship(cascade="all, delete-orphan", lazy="selectin")


class SupplierReturnLine(Base, TenantMixin):
    __tablename__ = "supplier_return_lines"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    return_id: Mapped[int] = mapped_column(ForeignKey("supplier_returns.id", ondelete="CASCADE"), index=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"))
    quantity: Mapped[float] = mapped_column(Float)
    unit_price: Mapped[float] = mapped_column(Float)  # credited by the supplier
    unit_cost: Mapped[float] = mapped_column(Float, default=0)
    state: Mapped[str] = mapped_column(String(20), default="available")  # which stock it came out of: available / damaged / expired
