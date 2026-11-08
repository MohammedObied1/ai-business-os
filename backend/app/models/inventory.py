from datetime import date, datetime

from sqlalchemy import Date, DateTime, Float, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TenantMixin, TimestampMixin


class Product(Base, TenantMixin, TimestampMixin):
    __tablename__ = "products"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    sku: Mapped[str] = mapped_column(String(80), index=True)
    name: Mapped[str] = mapped_column(String(200), index=True)
    category: Mapped[str | None] = mapped_column(String(100), index=True)
    unit: Mapped[str] = mapped_column(String(30), default="unit")
    cost_price: Mapped[float] = mapped_column(Float, default=0)
    sale_price: Mapped[float] = mapped_column(Float, default=0)
    min_stock: Mapped[float] = mapped_column(Float, default=0)
    supplier_lead_time_days: Mapped[int] = mapped_column(Integer, default=7)
    track_batches: Mapped[bool] = mapped_column(default=False)
    track_serials: Mapped[bool] = mapped_column(default=False)
    is_active: Mapped[bool] = mapped_column(default=True)
    barcode: Mapped[str | None] = mapped_column(String(80), index=True)
    pack_unit: Mapped[str | None] = mapped_column(String(30))  # e.g. "كرتونة"
    pack_size: Mapped[float] = mapped_column(Float, default=0)  # base units in one pack (0 = no pack)
    pack_price: Mapped[float | None] = mapped_column(Float)  # optional special price for a whole pack
    pack_barcode: Mapped[str | None] = mapped_column(String(80), index=True)


class Warehouse(Base, TenantMixin, TimestampMixin):
    __tablename__ = "warehouses"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(150))
    location: Mapped[str | None] = mapped_column(String(200))
    branch_id: Mapped[int | None] = mapped_column(ForeignKey("branches.id"))


class StockLevel(Base, TenantMixin):
    __tablename__ = "stock_levels"
    __table_args__ = (UniqueConstraint("product_id", "warehouse_id", "batch", name="uq_stock_pwb"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id", ondelete="CASCADE"), index=True)
    warehouse_id: Mapped[int] = mapped_column(ForeignKey("warehouses.id", ondelete="CASCADE"), index=True)
    quantity: Mapped[float] = mapped_column(Float, default=0)
    batch: Mapped[str] = mapped_column(String(80), default="")
    expiry_date: Mapped[date | None] = mapped_column(Date)


class StockMovement(Base, TenantMixin):
    """Audit trail of every stock change: in / out / transfer / adjustment."""

    __tablename__ = "stock_movements"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id", ondelete="CASCADE"), index=True)
    warehouse_id: Mapped[int] = mapped_column(ForeignKey("warehouses.id", ondelete="CASCADE"))
    to_warehouse_id: Mapped[int | None] = mapped_column(ForeignKey("warehouses.id"))
    quantity: Mapped[float] = mapped_column(Float)  # positive = in, negative = out
    movement_type: Mapped[str] = mapped_column(String(30))  # sale / purchase / transfer / adjustment
    reference: Mapped[str | None] = mapped_column(String(120))
    batch: Mapped[str] = mapped_column(String(80), default="")
    serial: Mapped[str | None] = mapped_column(String(120))
    occurred_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    unit_cost: Mapped[float | None] = mapped_column(Float)  # cost per unit of this movement (costing method)
