from datetime import date, datetime

from pydantic import BaseModel

from app.schemas.common import ORMModel


class OrderItemIn(BaseModel):
    product_id: int
    quantity: float
    unit_price: float | None = None  # price per chosen unit; defaults to the product price
    discount_pct: float = 0
    unit: str = "unit"  # unit / pack


class OrderIn(BaseModel):
    customer_id: int
    warehouse_id: int | None = None
    status: str = "confirmed"
    order_date: date | None = None
    discount_pct: float = 0
    notes: str | None = None
    currency: str | None = None  # empty = company currency
    client_ref: str | None = None
    items: list[OrderItemIn]


class OrderItemOut(ORMModel):
    id: int
    product_id: int
    quantity: float
    unit_price: float
    unit_cost: float | None  # hidden without products.view_cost
    discount_pct: float
    line_total: float
    uom_label: str | None = None
    uom_qty: float | None = None
    uom_price: float | None = None


class OrderOut(ORMModel):
    customer_name: str | None = None  # filled in by the list endpoints
    invoice_id: int | None = None
    id: int
    number: str
    customer_id: int
    warehouse_id: int | None = None
    status: str
    order_date: date
    discount_pct: float
    subtotal: float
    total: float
    cost_total: float | None  # hidden without products.view_cost
    tax_rate: float = 0
    tax_amount: float = 0
    source: str = "manual"
    salesperson_id: int | None = None
    notes: str | None = None
    currency: str | None = None
    exchange_rate: float = 1
    branch_id: int | None = None
    approval_reason: str | None = None
    approved_by: str | None = None
    items: list[OrderItemOut]


class InvoiceIn(BaseModel):
    customer_id: int
    order_id: int | None = None
    total: float | None = None  # for invoices without an order (includes tax)
    due_days: int = 30
    currency: str | None = None
    description: str | None = None


class InvoiceOut(ORMModel):
    customer_name: str | None = None  # filled in by the list endpoints
    id: int
    number: str
    customer_id: int
    order_id: int | None = None
    issue_date: date
    due_date: date
    total: float
    paid_amount: float
    credited_amount: float = 0
    tax_amount: float = 0
    subtotal: float | None = None
    status: str
    currency: str | None = None
    exchange_rate: float = 1
    description: str | None = None


class ChequeIn(BaseModel):
    number: str
    bank: str | None = None
    due_date: date


class PaymentIn(BaseModel):
    invoice_id: int
    amount: float
    method: str = "cash"  # cash / bank / card / cheque
    reference: str | None = None
    account_id: int | None = None
    cheque: ChequeIn | None = None
    currency: str | None = None  # currency the customer paid in (default: the invoice currency)


class CustomerReceiptIn(BaseModel):
    """Money received from a customer, spread over their oldest open invoices."""
    customer_id: int
    amount: float
    method: str = "cash"
    reference: str | None = None
    account_id: int | None = None
    cheque: ChequeIn | None = None
    currency: str | None = None


class PaymentOut(ORMModel):
    customer_name: str | None = None  # filled in by the list endpoints
    id: int
    invoice_id: int
    customer_id: int
    amount: float
    method: str
    paid_at: datetime
    reference: str | None = None
    number: str | None = None
    account_id: int | None = None
    status: str = "done"
    account_amount: float | None = None


class ReturnItemIn(BaseModel):
    order_item_id: int
    quantity: float
    condition: str = "good"  # good → back to sale; damaged / expired → written-off stock


class ReturnIn(BaseModel):
    order_id: int
    items: list[ReturnItemIn]
    reason: str | None = None
    warehouse_id: int | None = None
    refund_account_id: int | None = None  # used only if the customer had already paid more than they now owe


class CreditNoteItemOut(ORMModel):
    id: int
    product_id: int
    quantity: float
    unit_price: float
    line_total: float


class CreditNoteOut(ORMModel):
    customer_name: str | None = None  # filled in by the list endpoints
    id: int
    number: str
    customer_id: int
    invoice_id: int | None = None
    order_id: int | None = None
    note_date: date
    reason: str | None = None
    subtotal: float
    tax_amount: float
    total: float
    applied_to_invoice: float
    refunded: float
    currency: str | None = None
    items: list[CreditNoteItemOut]


class InvoiceParty(ORMModel):
    name: str
    email: str | None = None
    phone: str | None = None
    address: str | None = None


class InvoiceCompany(InvoiceParty):
    id: int
    currency: str
    payment_instructions: str | None = None
    tax_number: str | None = None
    tax_rate: float = 0
    logo_path: str | None = None
    invoice_footer: str | None = None


class InvoiceLine(BaseModel):
    product: str
    sku: str
    quantity: float
    unit_price: float
    discount_pct: float
    line_total: float
    unit: str | None = None


class InvoiceDetail(BaseModel):
    invoice: InvoiceOut
    company: InvoiceCompany
    customer: InvoiceParty
    order_number: str | None = None
    order_discount_pct: float = 0
    subtotal: float
    tax_rate: float = 0
    items: list[InvoiceLine]
    payments: list[PaymentOut]
    credit_notes: list[CreditNoteOut] = []
    public_token: str | None = None
    currency: str | None = None
    installments: list[dict] = []


class QuoteIn(BaseModel):
    customer_id: int | None = None
    items: list[OrderItemIn]
    discount_pct: float = 0
    currency: str | None = None
