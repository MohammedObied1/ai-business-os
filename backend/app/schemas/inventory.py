from datetime import date, datetime

from pydantic import BaseModel

from app.schemas.common import ORMModel


class ProductIn(BaseModel):
    sku: str = ""  # auto-generated when empty
    name: str
    category: str | None = None
    unit: str = "unit"
    cost_price: float = 0
    sale_price: float = 0
    min_stock: float = 0
    supplier_lead_time_days: int = 7
    track_batches: bool = False
    track_serials: bool = False
    opening_stock: float = 0
    warehouse_id: int | None = None
    barcode: str | None = None
    pack_unit: str | None = None
    pack_size: float = 0
    pack_price: float | None = None
    pack_barcode: str | None = None


class ProductUpdate(BaseModel):
    sku: str | None = None
    name: str | None = None
    category: str | None = None
    unit: str | None = None
    cost_price: float | None = None
    sale_price: float | None = None
    min_stock: float | None = None
    supplier_lead_time_days: int | None = None
    is_active: bool | None = None
    barcode: str | None = None
    pack_unit: str | None = None
    pack_size: float | None = None
    pack_price: float | None = None
    pack_barcode: str | None = None


class ProductOut(ORMModel):
    id: int
    sku: str
    name: str
    category: str | None = None
    unit: str
    cost_price: float | None  # hidden (None) without products.view_cost
    sale_price: float
    min_stock: float
    supplier_lead_time_days: int
    track_batches: bool
    track_serials: bool
    is_active: bool
    barcode: str | None = None
    pack_unit: str | None = None
    pack_size: float = 0
    pack_price: float | None = None
    pack_barcode: str | None = None


class ProductWithStock(ProductOut):
    total_stock: float
    pending_approval: bool = False  # a price change was sent to a manager instead of being applied


class WarehouseIn(BaseModel):
    name: str
    location: str | None = None
    branch_id: int | None = None


class WarehouseOut(ORMModel):
    id: int
    name: str
    location: str | None = None
    branch_id: int | None = None


class StockLevelOut(ORMModel):
    id: int
    product_id: int
    warehouse_id: int
    quantity: float
    batch: str
    expiry_date: date | None = None


class StockAdjust(BaseModel):
    product_id: int
    warehouse_id: int
    quantity: float  # positive to add, negative to remove
    batch: str = ""
    expiry_date: date | None = None
    serial: str | None = None
    reference: str | None = None


class StockTransfer(BaseModel):
    product_id: int
    from_warehouse_id: int
    to_warehouse_id: int
    quantity: float
    batch: str = ""


class MovementOut(ORMModel):
    id: int
    product_id: int
    warehouse_id: int
    to_warehouse_id: int | None = None
    quantity: float
    movement_type: str
    reference: str | None = None
    batch: str
    occurred_at: datetime


class ForecastOut(BaseModel):
    product_id: int
    product_name: str
    current_stock: float
    avg_daily_sales: float
    lead_time_days: int
    predicted_7d_demand: float
    predicted_30d_demand: float
    days_of_cover: float | None
    risk: str
    recommended_order_qty: float
    explanation: str


class WarehouseStock(BaseModel):
    warehouse_id: int
    warehouse: str
    quantity: float


class ProductDetail(ProductWithStock):
    by_warehouse: list[WarehouseStock]
    movements: list[MovementOut]
