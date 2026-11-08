"""Models added in the "full ERP" round: security, messaging, integrations, general ledger, currencies and operations."""
from datetime import date, datetime

from sqlalchemy import JSON, Boolean, Date, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TenantMixin, TimestampMixin


# ---------------------------------------------------------------- security & messaging (platform-wide)
class LoginEvent(Base):
    __tablename__ = "login_events"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    company_id: Mapped[int | None] = mapped_column(Integer, index=True)
    user_id: Mapped[int | None] = mapped_column(Integer, index=True)
    admin_id: Mapped[int | None] = mapped_column(Integer)
    email: Mapped[str] = mapped_column(String(200), index=True)
    success: Mapped[bool] = mapped_column(Boolean)
    reason: Mapped[str | None] = mapped_column(String(60))  # bad_password / locked / 2fa_required / 2fa_failed / ok
    ip: Mapped[str | None] = mapped_column(String(64))
    user_agent: Mapped[str | None] = mapped_column(String(300))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), index=True)


class EmailMessage(Base):
    """Outbox: every email the system sends. Without SMTP settings they stay here as 'saved' so nothing is lost."""

    __tablename__ = "email_outbox"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    company_id: Mapped[int | None] = mapped_column(Integer, index=True)
    to: Mapped[str] = mapped_column(String(300))
    subject: Mapped[str] = mapped_column(String(300))
    body_html: Mapped[str] = mapped_column(Text)
    kind: Mapped[str] = mapped_column(String(40))  # password_reset / invoice / statement / daily_summary / billing
    status: Mapped[str] = mapped_column(String(20), default="queued")  # queued / sent / failed / saved
    error: Mapped[str | None] = mapped_column(String(500))
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), index=True)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime)


class PasswordResetToken(Base):
    __tablename__ = "password_reset_tokens"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    token_hash: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    user_id: Mapped[int | None] = mapped_column(Integer)
    admin_id: Mapped[int | None] = mapped_column(Integer)
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    used_at: Mapped[datetime | None] = mapped_column(DateTime)


class ApiKey(Base, TenantMixin, TimestampMixin):
    __tablename__ = "api_keys"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    prefix: Mapped[str] = mapped_column(String(16), index=True)
    key_hash: Mapped[str] = mapped_column(String(128), unique=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))  # the key acts with this user's permissions
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    scopes: Mapped[list] = mapped_column(JSON, default=list)  # extra ceiling on the user's permissions; [] = no extra limit
    expires_at: Mapped[datetime | None] = mapped_column(DateTime)  # None = never expires
    rate_limit_per_min: Mapped[int] = mapped_column(Integer, default=120)
    request_count: Mapped[int] = mapped_column(Integer, default=0)


class Webhook(Base, TenantMixin, TimestampMixin):
    __tablename__ = "webhooks"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    url: Mapped[str] = mapped_column(String(500))
    events: Mapped[list] = mapped_column(JSON, default=list)  # ["invoice.created", "payment.received", ...] or ["*"]
    secret: Mapped[str] = mapped_column(String(80))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class WebhookDelivery(Base, TenantMixin):
    __tablename__ = "webhook_deliveries"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    webhook_id: Mapped[int] = mapped_column(ForeignKey("webhooks.id", ondelete="CASCADE"), index=True)
    event: Mapped[str] = mapped_column(String(60))
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(20), default="pending")  # pending / delivered / failed
    response_code: Mapped[int | None] = mapped_column(Integer)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), index=True)


class PlatformInvoice(Base, TimestampMixin):
    """What a company owes the platform owner for its subscription."""

    __tablename__ = "platform_invoices"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id", ondelete="CASCADE"), index=True)
    number: Mapped[str] = mapped_column(String(40), index=True)
    period: Mapped[str] = mapped_column(String(7))  # 2026-10
    plan_name: Mapped[str | None] = mapped_column(String(100))
    amount: Mapped[float] = mapped_column(Float)
    due_date: Mapped[date] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(20), default="unpaid")  # unpaid / paid / void
    paid_at: Mapped[date | None] = mapped_column(Date)
    note: Mapped[str | None] = mapped_column(String(300))
    subscription_id: Mapped[int | None] = mapped_column(Integer, index=True)
    interval: Mapped[str | None] = mapped_column(String(10))  # monthly / yearly
    period_start: Mapped[date | None] = mapped_column(Date)
    period_end: Mapped[date | None] = mapped_column(Date)
    subtotal: Mapped[float | None] = mapped_column(Float)
    discount: Mapped[float | None] = mapped_column(Float)
    paid_amount: Mapped[float] = mapped_column(Float, default=0, server_default="0")
    lines: Mapped[list | None] = mapped_column(JSON)  # [{"label", "amount"}]


# ---------------------------------------------------------------- currencies & general ledger
class Currency(Base, TenantMixin, TimestampMixin):
    """Extra currencies a company deals in. rate = how many base-currency units one unit is worth."""

    __tablename__ = "currencies"
    __table_args__ = (UniqueConstraint("company_id", "code", name="uq_currency_code"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(10))
    rate: Mapped[float] = mapped_column(Float)


class GLAccount(Base, TenantMixin, TimestampMixin):
    __tablename__ = "gl_accounts"
    __table_args__ = (UniqueConstraint("company_id", "code", name="uq_gl_code"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(30))
    name: Mapped[str] = mapped_column(String(200))
    name_en: Mapped[str | None] = mapped_column(String(200))
    type: Mapped[str] = mapped_column(String(20))  # asset / liability / equity / revenue / expense
    system_key: Mapped[str | None] = mapped_column(String(80), index=True)  # e.g. "ar", "cash:5", "expense:Rent"
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class JournalEntry(Base, TenantMixin, TimestampMixin):
    __tablename__ = "journal_entries"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    entry_date: Mapped[date] = mapped_column(Date, index=True)
    number: Mapped[str | None] = mapped_column(String(40))
    memo: Mapped[str | None] = mapped_column(String(300))
    source: Mapped[str] = mapped_column(String(30), index=True)  # manual / auto
    source_type: Mapped[str | None] = mapped_column(String(40))
    source_id: Mapped[int | None] = mapped_column(Integer)
    branch_id: Mapped[int | None] = mapped_column(Integer)
    lines: Mapped[list["JournalLine"]] = relationship(cascade="all, delete-orphan", lazy="selectin")


class JournalLine(Base, TenantMixin):
    __tablename__ = "journal_lines"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    entry_id: Mapped[int] = mapped_column(ForeignKey("journal_entries.id", ondelete="CASCADE"), index=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("gl_accounts.id"), index=True)
    debit: Mapped[float] = mapped_column(Float, default=0)
    credit: Mapped[float] = mapped_column(Float, default=0)
    description: Mapped[str | None] = mapped_column(String(300))


# ---------------------------------------------------------------- pricing, installments, recurring
class PriceList(Base, TenantMixin, TimestampMixin):
    __tablename__ = "price_lists"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    discount_pct: Mapped[float] = mapped_column(Float, default=0)  # applied to products without an explicit price
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    items: Mapped[list["PriceListItem"]] = relationship(cascade="all, delete-orphan", lazy="selectin")


class PriceListItem(Base, TenantMixin):
    __tablename__ = "price_list_items"
    __table_args__ = (UniqueConstraint("price_list_id", "product_id", name="uq_pricelist_product"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    price_list_id: Mapped[int] = mapped_column(ForeignKey("price_lists.id", ondelete="CASCADE"), index=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id", ondelete="CASCADE"))
    price: Mapped[float] = mapped_column(Float)


class Promotion(Base, TenantMixin, TimestampMixin):
    __tablename__ = "promotions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(150))
    kind: Mapped[str] = mapped_column(String(20))  # percent (x% off) / bxgy (buy X get Y free)
    product_id: Mapped[int | None] = mapped_column(ForeignKey("products.id", ondelete="CASCADE"))
    category: Mapped[str | None] = mapped_column(String(100))
    percent: Mapped[float] = mapped_column(Float, default=0)
    buy_qty: Mapped[float] = mapped_column(Float, default=0)
    free_qty: Mapped[float] = mapped_column(Float, default=0)
    starts_on: Mapped[date | None] = mapped_column(Date)
    ends_on: Mapped[date | None] = mapped_column(Date)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class Installment(Base, TenantMixin):
    """One scheduled part of an invoice paid in instalments. Paid status is derived from the invoice's payments."""

    __tablename__ = "installments"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    invoice_id: Mapped[int] = mapped_column(ForeignKey("invoices.id", ondelete="CASCADE"), index=True)
    seq: Mapped[int] = mapped_column(Integer)
    due_date: Mapped[date] = mapped_column(Date, index=True)
    amount: Mapped[float] = mapped_column(Float)


class RecurringInvoice(Base, TenantMixin, TimestampMixin):
    __tablename__ = "recurring_invoices"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id"), index=True)
    description: Mapped[str] = mapped_column(String(300))
    amount: Mapped[float] = mapped_column(Float)  # including tax
    interval_months: Mapped[int] = mapped_column(Integer, default=1)
    next_date: Mapped[date] = mapped_column(Date, index=True)
    end_date: Mapped[date | None] = mapped_column(Date)
    due_days: Mapped[int] = mapped_column(Integer, default=14)
    send_email: Mapped[bool] = mapped_column(Boolean, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    last_invoice_id: Mapped[int | None] = mapped_column(Integer)


# ---------------------------------------------------------------- stock count, attachments, approvals, POS shifts
class StockCount(Base, TenantMixin, TimestampMixin):
    __tablename__ = "stock_counts"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    number: Mapped[str] = mapped_column(String(40))
    warehouse_id: Mapped[int] = mapped_column(ForeignKey("warehouses.id"))
    status: Mapped[str] = mapped_column(String(20), default="open")  # open / applied / cancelled
    note: Mapped[str | None] = mapped_column(String(300))
    applied_at: Mapped[datetime | None] = mapped_column(DateTime)
    user_id: Mapped[int | None] = mapped_column(Integer)
    lines: Mapped[list["StockCountLine"]] = relationship(cascade="all, delete-orphan", lazy="selectin")


class StockCountLine(Base, TenantMixin):
    __tablename__ = "stock_count_lines"
    __table_args__ = (UniqueConstraint("count_id", "product_id", name="uq_count_product"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    count_id: Mapped[int] = mapped_column(ForeignKey("stock_counts.id", ondelete="CASCADE"), index=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"))
    expected: Mapped[float] = mapped_column(Float, default=0)
    counted: Mapped[float | None] = mapped_column(Float)
    unit_cost: Mapped[float] = mapped_column(Float, default=0)


class Attachment(Base, TenantMixin, TimestampMixin):
    __tablename__ = "attachments"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    entity: Mapped[str] = mapped_column(String(40), index=True)
    entity_id: Mapped[int] = mapped_column(Integer, index=True)
    filename: Mapped[str] = mapped_column(String(300))
    path: Mapped[str] = mapped_column(String(500))
    size: Mapped[int] = mapped_column(Integer, default=0)
    content_type: Mapped[str | None] = mapped_column(String(120))
    uploaded_by: Mapped[str | None] = mapped_column(String(200))


class PosShift(Base, TenantMixin, TimestampMixin):
    """A cashier's shift: opening float, and at closing the counted cash vs what the system expected."""

    __tablename__ = "pos_shifts"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    account_id: Mapped[int | None] = mapped_column(ForeignKey("accounts.id"))
    opened_at: Mapped[datetime] = mapped_column(DateTime)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime)
    opening_float: Mapped[float] = mapped_column(Float, default=0)
    start_tx_id: Mapped[int] = mapped_column(Integer, default=0)  # money movements after this id belong to the shift
    expected_cash: Mapped[float | None] = mapped_column(Float)
    counted_cash: Mapped[float | None] = mapped_column(Float)
    difference: Mapped[float | None] = mapped_column(Float)
    note: Mapped[str | None] = mapped_column(String(300))


# ---------------------------------------------------------------- manufacturing, deliveries, field sales
class BillOfMaterials(Base, TenantMixin, TimestampMixin):
    __tablename__ = "boms"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), index=True)  # what gets produced
    output_qty: Mapped[float] = mapped_column(Float, default=1)  # units produced by one batch of the components below
    note: Mapped[str | None] = mapped_column(String(300))
    lines: Mapped[list["BOMLine"]] = relationship(cascade="all, delete-orphan", lazy="selectin")


class BOMLine(Base, TenantMixin):
    __tablename__ = "bom_lines"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    bom_id: Mapped[int] = mapped_column(ForeignKey("boms.id", ondelete="CASCADE"), index=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"))
    quantity: Mapped[float] = mapped_column(Float)


class ProductionOrder(Base, TenantMixin, TimestampMixin):
    __tablename__ = "production_orders"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    number: Mapped[str] = mapped_column(String(40))
    bom_id: Mapped[int] = mapped_column(ForeignKey("boms.id"))
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"))
    quantity: Mapped[float] = mapped_column(Float)
    warehouse_id: Mapped[int] = mapped_column(ForeignKey("warehouses.id"))
    status: Mapped[str] = mapped_column(String(20), default="planned")  # planned / done / cancelled
    unit_cost: Mapped[float | None] = mapped_column(Float)
    done_at: Mapped[datetime | None] = mapped_column(DateTime)


class Delivery(Base, TenantMixin, TimestampMixin):
    __tablename__ = "deliveries"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("sales_orders.id"), index=True)
    driver_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), index=True)
    status: Mapped[str] = mapped_column(String(20), default="assigned")  # assigned / out / delivered / failed / returned
    address: Mapped[str | None] = mapped_column(String(300))
    scheduled_for: Mapped[date | None] = mapped_column(Date)
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime)
    received_by: Mapped[str | None] = mapped_column(String(150))
    cash_collected: Mapped[float] = mapped_column(Float, default=0)
    amount_due: Mapped[float] = mapped_column(Float, default=0)  # what's still owed after this delivery (order total minus cash collected)
    note: Mapped[str | None] = mapped_column(String(300))


class Visit(Base, TenantMixin, TimestampMixin):
    __tablename__ = "visits"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    visited_at: Mapped[datetime] = mapped_column(DateTime)
    lat: Mapped[float | None] = mapped_column(Float)
    lng: Mapped[float | None] = mapped_column(Float)
    outcome: Mapped[str] = mapped_column(String(30), default="visited")  # visited / order / no_answer / closed
    note: Mapped[str | None] = mapped_column(String(500))
    order_id: Mapped[int | None] = mapped_column(Integer)


class PaymentProof(Base, TenantMixin, TimestampMixin):
    """A customer says they paid (bank transfer receipt uploaded from the portal). Staff confirm it into a real payment."""

    __tablename__ = "payment_proofs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id"), index=True)
    invoice_id: Mapped[int | None] = mapped_column(ForeignKey("invoices.id"))
    amount: Mapped[float] = mapped_column(Float)
    reference: Mapped[str | None] = mapped_column(String(120))
    note: Mapped[str | None] = mapped_column(String(500))
    attachment_id: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(20), default="pending")  # pending / confirmed / rejected


class ImportBatch(Base, TenantMixin, TimestampMixin):
    """One Excel/CSV import run — remembers exactly which rows it created, so it can be undone (rows since used
    elsewhere, e.g. a product that already has a sale, are left alone and reported instead of force-deleted)."""

    __tablename__ = "import_batches"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    entity: Mapped[str] = mapped_column(String(30))
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    user_name: Mapped[str | None] = mapped_column(String(200))
    filename: Mapped[str | None] = mapped_column(String(300))
    created_count: Mapped[int] = mapped_column(Integer, default=0)
    updated_count: Mapped[int] = mapped_column(Integer, default=0)
    created_ids: Mapped[list] = mapped_column(JSON, default=list)  # ids of newly created top-level rows (not updates)
    side_effect_ids: Mapped[dict] = mapped_column(JSON, default=dict)  # e.g. {"opening_invoice": {product_id: invoice_id}}
    rolled_back_at: Mapped[datetime | None] = mapped_column(DateTime)
    rollback_report: Mapped[dict | None] = mapped_column(JSON)  # {removed: [...], kept_in_use: [...]}


class SavedReport(Base, TenantMixin, TimestampMixin):
    """A report tab plus filters the user saved for one click, instead of re-picking dates/branch each time."""

    __tablename__ = "saved_reports"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(150))
    report: Mapped[str] = mapped_column(String(50))  # matches a Reports page tab / API report key
    params: Mapped[dict] = mapped_column(JSON, default=dict)  # e.g. {"start": "...", "end": "...", "branch_id": 3}
