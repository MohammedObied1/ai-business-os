from datetime import date, datetime

from sqlalchemy import JSON, Boolean, Date, DateTime, Float, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TenantMixin, TimestampMixin


class Company(Base, TimestampMixin):
    __tablename__ = "companies"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    currency: Mapped[str] = mapped_column(String(10), default="ILS")
    industry: Mapped[str | None] = mapped_column(String(100))
    settings: Mapped[dict] = mapped_column(JSON, default=dict)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    email: Mapped[str | None] = mapped_column(String(200))
    phone: Mapped[str | None] = mapped_column(String(50))
    address: Mapped[str | None] = mapped_column(String(300))
    tax_number: Mapped[str | None] = mapped_column(String(80))
    notes: Mapped[str | None] = mapped_column(String(1000))  # platform-admin notes (plan, contact person...)
    tax_rate: Mapped[float] = mapped_column(Float, default=0)  # VAT %, e.g. 16
    prices_include_tax: Mapped[bool] = mapped_column(Boolean, default=False)
    logo_path: Mapped[str | None] = mapped_column(String(300))
    invoice_footer: Mapped[str | None] = mapped_column(String(500))
    plan_id: Mapped[int | None] = mapped_column(ForeignKey("plans.id"))
    subscription_ends_at: Mapped[date | None] = mapped_column(Date)
    # white-label & public pages
    slug: Mapped[str | None] = mapped_column(String(80), unique=True, index=True)
    custom_domain: Mapped[str | None] = mapped_column(String(200), index=True)
    domain_verify_token: Mapped[str | None] = mapped_column(String(64))
    domain_verified_at: Mapped[datetime | None] = mapped_column(DateTime)  # custom_domain only takes effect once this is set
    brand_color: Mapped[str | None] = mapped_column(String(9))  # "#0F766E"
    catalog_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    portal_orders_enabled: Mapped[bool] = mapped_column(Boolean, default=True, server_default="1")  # customers may request orders from the portal
    online_order_status: Mapped[str] = mapped_column(String(20), default="quotation", server_default="quotation")  # quotation / draft
    payment_instructions: Mapped[str | None] = mapped_column(String(1000))  # bank details shown to customers
    # approvals
    approval_discount_pct: Mapped[float] = mapped_column(Float, default=0)  # 0 = no approval needed
    approval_expense_amount: Mapped[float] = mapped_column(Float, default=0)
    require_2fa: Mapped[bool] = mapped_column(Boolean, default=False)
    costing_method: Mapped[str] = mapped_column(String(10), default="average", server_default="average")  # average / fifo
    timezone: Mapped[str] = mapped_column(String(50), default="Asia/Hebron", server_default="Asia/Hebron")  # IANA name; used for "today" boundaries

    users: Mapped[list["User"]] = relationship(back_populates="company")


class Role(Base, TenantMixin, TimestampMixin):
    __tablename__ = "roles"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    description: Mapped[str | None] = mapped_column(String(300))
    # e.g. ["customers:read", "customers:write", "invoices:create", "finance:read", "*"]
    permissions: Mapped[list] = mapped_column(JSON, default=list)


class User(Base, TenantMixin, TimestampMixin):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(String(200), unique=True, index=True)
    full_name: Mapped[str] = mapped_column(String(200))
    hashed_password: Mapped[str] = mapped_column(String(300))
    department: Mapped[str | None] = mapped_column(String(100))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    role_id: Mapped[int | None] = mapped_column(ForeignKey("roles.id"))
    branch_id: Mapped[int | None] = mapped_column(ForeignKey("branches.id"))  # None = all branches
    phone: Mapped[str | None] = mapped_column(String(50))
    totp_secret: Mapped[str | None] = mapped_column(String(64))
    totp_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    token_version: Mapped[int] = mapped_column(Integer, default=0)  # bump = sign out everywhere
    failed_logins: Mapped[int] = mapped_column(Integer, default=0)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime)
    allowed_warehouse_ids: Mapped[list | None] = mapped_column(JSON)  # None / [] = every warehouse

    role: Mapped[Role | None] = relationship(lazy="joined")
    company: Mapped[Company] = relationship(back_populates="users")


class PlatformAdmin(Base, TimestampMixin):
    """Owner of the whole platform: creates and manages companies. Not tied to any company."""

    __tablename__ = "platform_admins"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(String(200), unique=True, index=True)
    full_name: Mapped[str] = mapped_column(String(200))
    hashed_password: Mapped[str] = mapped_column(String(300))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    is_owner: Mapped[bool] = mapped_column(Boolean, default=True, server_default="1")  # can manage other platform admins
    can_impersonate: Mapped[bool] = mapped_column(Boolean, default=True, server_default="1")  # may "enter" a company for support
    totp_secret: Mapped[str | None] = mapped_column(String(64))
    totp_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    token_version: Mapped[int] = mapped_column(Integer, default=0)
    failed_logins: Mapped[int] = mapped_column(Integer, default=0)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime)
