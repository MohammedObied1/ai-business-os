from datetime import date

from pydantic import BaseModel

from app.schemas.common import ORMModel
from app.schemas.sales import ChequeIn


class SupplierIn(BaseModel):
    name: str
    email: str | None = None
    phone: str | None = None
    address: str | None = None
    tax_number: str | None = None
    lead_time_days: int = 7
    payment_terms_days: int = 30
    opening_balance: float = 0


class SupplierOut(ORMModel):
    id: int
    name: str
    email: str | None = None
    phone: str | None = None
    address: str | None = None
    tax_number: str | None = None
    lead_time_days: int
    payment_terms_days: int
    opening_balance: float = 0


class POItemIn(BaseModel):
    product_id: int
    quantity: float
    unit_cost: float | None = None  # per chosen unit
    unit: str = "unit"  # unit / pack


class POIn(BaseModel):
    supplier_id: int
    warehouse_id: int | None = None
    expected_date: date | None = None
    notes: str | None = None
    include_tax: bool = True  # add the company VAT rate on top of the costs
    currency: str | None = None  # empty = company currency
    items: list[POItemIn]


class POItemOut(ORMModel):
    id: int
    product_id: int
    quantity: float
    unit_cost: float
    line_total: float
    batch: str = ""
    expiry_date: date | None = None
    uom_label: str | None = None
    uom_qty: float | None = None


class POOut(ORMModel):
    id: int
    number: str
    supplier_id: int
    warehouse_id: int | None = None
    status: str
    order_date: date
    expected_date: date | None = None
    total: float
    tax_amount: float = 0
    paid_amount: float
    requested_by: str | None = None
    notes: str | None = None
    received_on: date | None = None
    supplier_invoice_no: str | None = None
    currency: str | None = None
    exchange_rate: float = 1
    items: list[POItemOut]


class ReceiveLine(BaseModel):
    item_id: int
    batch: str = ""
    expiry_date: date | None = None


class ReceiveIn(BaseModel):
    warehouse_id: int | None = None
    supplier_invoice_no: str | None = None
    lines: list[ReceiveLine] = []


class SupplierPaymentIn(BaseModel):
    supplier_id: int
    amount: float
    po_id: int | None = None
    method: str = "cash"  # cash / bank / card / cheque
    account_id: int | None = None
    reference: str | None = None
    cheque: ChequeIn | None = None
    currency: str | None = None  # default: the purchase order's currency


class SupplierPaymentOut(ORMModel):
    id: int
    number: str
    supplier_id: int
    po_id: int | None = None
    amount: float
    method: str
    account_id: int | None = None
    paid_at: date
    reference: str | None = None
    status: str
    currency: str | None = None
