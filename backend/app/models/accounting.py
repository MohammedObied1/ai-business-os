"""Money: cash boxes & bank accounts, their ledger, cheques, supplier payments and sales returns."""
from datetime import date, datetime

from sqlalchemy import Date, DateTime, Float, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TenantMixin, TimestampMixin


class Account(Base, TenantMixin, TimestampMixin):
    """A place money sits in: a cash box (الصندوق) or a bank account."""

    __tablename__ = "accounts"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(150))
    kind: Mapped[str] = mapped_column(String(20), default="cash")  # cash / bank
    bank_name: Mapped[str | None] = mapped_column(String(150))
    account_number: Mapped[str | None] = mapped_column(String(80))
    opening_balance: Mapped[float] = mapped_column(Float, default=0)
    branch_id: Mapped[int | None] = mapped_column(ForeignKey("branches.id"))
    is_active: Mapped[bool] = mapped_column(default=True)
    currency: Mapped[str | None] = mapped_column(String(10))  # None = company currency


class Transaction(Base, TenantMixin, TimestampMixin):
    """One line in an account's ledger. amount > 0 = money in, < 0 = money out."""

    __tablename__ = "transactions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"), index=True)
    tx_date: Mapped[date] = mapped_column(Date, default=date.today, index=True)
    amount: Mapped[float] = mapped_column(Float)
    # customer_payment / supplier_payment / expense / refund / transfer / cheque_cleared / other_in / other_out / salary
    kind: Mapped[str] = mapped_column(String(30), index=True)
    number: Mapped[str | None] = mapped_column(String(50), index=True)  # voucher number (RV- / PV-)
    description: Mapped[str | None] = mapped_column(String(300))
    reference: Mapped[str | None] = mapped_column(String(120))
    customer_id: Mapped[int | None] = mapped_column(ForeignKey("customers.id"))
    supplier_id: Mapped[int | None] = mapped_column(ForeignKey("suppliers.id"))
    payment_id: Mapped[int | None] = mapped_column(ForeignKey("payments.id"))
    supplier_payment_id: Mapped[int | None] = mapped_column(ForeignKey("supplier_payments.id"))
    expense_id: Mapped[int | None] = mapped_column(ForeignKey("expenses.id"))
    cheque_id: Mapped[int | None] = mapped_column(ForeignKey("cheques.id"))
    transfer_group: Mapped[str | None] = mapped_column(String(40))
    party_name: Mapped[str | None] = mapped_column(String(200))  # free-text "received from / paid to"
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    gl_account_id: Mapped[int | None] = mapped_column(ForeignKey("gl_accounts.id"))  # counter-account for manual vouchers
    base_amount: Mapped[float | None] = mapped_column(Float)  # amount in company currency when the account is foreign


class Cheque(Base, TenantMixin, TimestampMixin):
    """Post-dated cheques. Incoming (from customers) or outgoing (to suppliers)."""

    __tablename__ = "cheques"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    direction: Mapped[str] = mapped_column(String(10))  # in / out
    number: Mapped[str] = mapped_column(String(80))
    bank: Mapped[str | None] = mapped_column(String(150))
    amount: Mapped[float] = mapped_column(Float)
    issue_date: Mapped[date] = mapped_column(Date, default=date.today)
    due_date: Mapped[date] = mapped_column(Date, index=True)
    # pending (in hand / issued) / deposited / cleared / bounced / cancelled
    status: Mapped[str] = mapped_column(String(20), default="pending", index=True)
    customer_id: Mapped[int | None] = mapped_column(ForeignKey("customers.id"))
    supplier_id: Mapped[int | None] = mapped_column(ForeignKey("suppliers.id"))
    payment_id: Mapped[int | None] = mapped_column(ForeignKey("payments.id"))
    supplier_payment_id: Mapped[int | None] = mapped_column(ForeignKey("supplier_payments.id"))
    account_id: Mapped[int | None] = mapped_column(ForeignKey("accounts.id"))  # where it was deposited / drawn
    cleared_at: Mapped[date | None] = mapped_column(Date)
    bounced_at: Mapped[date | None] = mapped_column(Date)
    notes: Mapped[str | None] = mapped_column(String(300))
    currency: Mapped[str | None] = mapped_column(String(10))


class SupplierPayment(Base, TenantMixin, TimestampMixin):
    __tablename__ = "supplier_payments"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    number: Mapped[str] = mapped_column(String(50), index=True)
    supplier_id: Mapped[int] = mapped_column(ForeignKey("suppliers.id"), index=True)
    po_id: Mapped[int | None] = mapped_column(ForeignKey("purchase_orders.id"))
    amount: Mapped[float] = mapped_column(Float)
    method: Mapped[str] = mapped_column(String(30), default="cash")
    account_id: Mapped[int | None] = mapped_column(ForeignKey("accounts.id"))
    paid_at: Mapped[date] = mapped_column(Date, default=date.today, index=True)
    reference: Mapped[str | None] = mapped_column(String(120))
    status: Mapped[str] = mapped_column(String(20), default="done")  # done / bounced
    currency: Mapped[str | None] = mapped_column(String(10))
    exchange_rate: Mapped[float] = mapped_column(Float, default=1)
    account_amount: Mapped[float | None] = mapped_column(Float)


class CreditNote(Base, TenantMixin, TimestampMixin):
    """Sales return: goods come back, the customer's balance goes down (or they get a refund)."""

    __tablename__ = "credit_notes"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    number: Mapped[str] = mapped_column(String(50), index=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id"), index=True)
    invoice_id: Mapped[int | None] = mapped_column(ForeignKey("invoices.id"))
    order_id: Mapped[int | None] = mapped_column(ForeignKey("sales_orders.id"))
    warehouse_id: Mapped[int | None] = mapped_column(ForeignKey("warehouses.id"))
    note_date: Mapped[date] = mapped_column(Date, default=date.today, index=True)
    reason: Mapped[str | None] = mapped_column(String(300))
    subtotal: Mapped[float] = mapped_column(Float, default=0)  # before tax
    tax_amount: Mapped[float] = mapped_column(Float, default=0)
    total: Mapped[float] = mapped_column(Float, default=0)
    cost_total: Mapped[float] = mapped_column(Float, default=0)
    applied_to_invoice: Mapped[float] = mapped_column(Float, default=0)
    refunded: Mapped[float] = mapped_column(Float, default=0)
    currency: Mapped[str | None] = mapped_column(String(10))
    exchange_rate: Mapped[float] = mapped_column(Float, default=1)

    items: Mapped[list["CreditNoteItem"]] = relationship(cascade="all, delete-orphan", lazy="selectin")


class CreditNoteItem(Base, TenantMixin):
    __tablename__ = "credit_note_items"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    credit_note_id: Mapped[int] = mapped_column(ForeignKey("credit_notes.id", ondelete="CASCADE"), index=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"))
    order_item_id: Mapped[int | None] = mapped_column(ForeignKey("sales_order_items.id"))
    quantity: Mapped[float] = mapped_column(Float)
    unit_price: Mapped[float] = mapped_column(Float)
    unit_cost: Mapped[float] = mapped_column(Float, default=0)
    line_total: Mapped[float] = mapped_column(Float)
    condition: Mapped[str] = mapped_column(String(10), default="good", server_default="good")  # good / damaged / expired
