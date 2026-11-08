"""Internal controls: approval rules & requests, accounting periods."""
from datetime import date, datetime

from sqlalchemy import JSON, Boolean, Date, DateTime, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TenantMixin, TimestampMixin


class ApprovalRule(Base, TenantMixin, TimestampMixin):
    """One row per kind of sensitive action. `threshold` meaning depends on the kind (percent, amount…)."""

    __tablename__ = "approval_rules"
    __table_args__ = (UniqueConstraint("company_id", "kind", name="uq_approval_rule_kind"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    kind: Mapped[str] = mapped_column(String(40))
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    threshold: Mapped[float] = mapped_column(Float, default=0)


class ApprovalRequest(Base, TenantMixin):
    """A sensitive action waiting for (or decided by) a manager. For deferred actions `payload` holds what to run on approval."""

    __tablename__ = "approval_requests"
    __table_args__ = (Index("ix_approval_requests_company_status", "company_id", "status"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    kind: Mapped[str] = mapped_column(String(40))
    entity: Mapped[str] = mapped_column(String(40))  # sales_orders / expenses / invoices / products / stock / vouchers / credit_notes / purchase_orders
    entity_id: Mapped[int | None] = mapped_column(Integer)
    label: Mapped[str | None] = mapped_column(String(200))  # e.g. the order number, shown in the list
    requested_value: Mapped[float | None] = mapped_column(Float)
    threshold: Mapped[float | None] = mapped_column(Float)
    reason: Mapped[str | None] = mapped_column(Text)  # why it needs approval / what the requester wrote
    payload: Mapped[dict | None] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(20), default="PENDING", index=True)  # PENDING / APPROVED / REJECTED / CANCELLED
    requested_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    requested_by: Mapped[str | None] = mapped_column(String(200))
    approver_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    approver: Mapped[str | None] = mapped_column(String(200))
    rejection_reason: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), index=True)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime)


class AiDraft(Base, TenantMixin):
    """A data-modifying action the AI wants to take. It is never executed on its own — the user who asked reviews the
    plain-language summary and explicitly confirms (or rejects) it before anything is written."""

    __tablename__ = "ai_drafts"
    __table_args__ = (Index("ix_ai_drafts_company_status", "company_id", "status"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    tool: Mapped[str] = mapped_column(String(40))
    args: Mapped[dict] = mapped_column(JSON, default=dict)
    summary: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default="pending", index=True)  # pending / confirmed / rejected
    result: Mapped[dict | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    decided_at: Mapped[datetime | None] = mapped_column(DateTime)


class Connection(Base, TenantMixin, TimestampMixin):
    """A third-party account the company connected (WhatsApp, and future providers). `secret` holds the credential
    (e.g. an access token) — shown to the frontend once, masked after. Never returned in list endpoints in full."""

    __tablename__ = "connections"
    __table_args__ = (UniqueConstraint("company_id", "provider", name="uq_connection_provider"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    provider: Mapped[str] = mapped_column(String(40))  # "whatsapp" for now
    config: Mapped[dict] = mapped_column(JSON, default=dict)  # non-secret settings, e.g. {"phone_number_id": "..."}
    secret: Mapped[str | None] = mapped_column(String(500))  # e.g. the access token
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime)
    last_error: Mapped[str | None] = mapped_column(Text)


class AccountingPeriod(Base, TenantMixin, TimestampMixin):
    """A month of the books. CLOSED = documents dated inside it can't be created, changed or deleted."""

    __tablename__ = "accounting_periods"
    __table_args__ = (UniqueConstraint("company_id", "period", name="uq_accounting_period"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    period: Mapped[str] = mapped_column(String(7))  # YYYY-MM
    start_date: Mapped[date] = mapped_column(Date)
    end_date: Mapped[date] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(10), default="OPEN")  # OPEN / CLOSED
    closed_by: Mapped[str | None] = mapped_column(String(200))
    closed_at: Mapped[datetime | None] = mapped_column(DateTime)
    note: Mapped[str | None] = mapped_column(Text)
