"""Platform-level (not tenant) records: subscription plans, branches and the audit trail."""
from datetime import datetime

from sqlalchemy import Index, JSON, DateTime, Float, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TenantMixin, TimestampMixin


class Plan(Base, TimestampMixin):
    __tablename__ = "plans"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    price_monthly: Mapped[float] = mapped_column(Float, default=0)
    max_users: Mapped[int] = mapped_column(Integer, default=5)  # 0 = unlimited
    max_branches: Mapped[int] = mapped_column(Integer, default=1)
    features: Mapped[list] = mapped_column(JSON, default=list)  # empty = every feature
    is_active: Mapped[bool] = mapped_column(default=True)
    # SaaS billing (0 = unlimited / none)
    price_yearly: Mapped[float] = mapped_column(Float, default=0, server_default="0")
    max_warehouses: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    max_storage_mb: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    max_ai_requests: Mapped[int] = mapped_column(Integer, default=0, server_default="0")  # per month
    max_api_requests: Mapped[int] = mapped_column(Integer, default=0, server_default="0")  # per month
    trial_days: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    grace_days: Mapped[int] = mapped_column(Integer, default=7, server_default="7")
    description: Mapped[str | None] = mapped_column(Text)


class Branch(Base, TenantMixin, TimestampMixin):
    __tablename__ = "branches"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(150))
    address: Mapped[str | None] = mapped_column(String(300))
    phone: Mapped[str | None] = mapped_column(String(50))
    is_active: Mapped[bool] = mapped_column(default=True)


class AuditLog(Base, TenantMixin):
    """Who changed what. Written automatically by a session hook (app.core.audit)."""

    __tablename__ = "audit_logs"
    __table_args__ = (Index("ix_audit_logs_company_created", "company_id", "created_at"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int | None] = mapped_column(Integer)
    user_name: Mapped[str | None] = mapped_column(String(200))
    action: Mapped[str] = mapped_column(String(20))  # create / update / delete
    entity: Mapped[str] = mapped_column(String(60), index=True)
    entity_id: Mapped[int | None] = mapped_column(Integer)
    label: Mapped[str | None] = mapped_column(String(300))  # human name of the record (invoice number, product name…)
    changes: Mapped[dict] = mapped_column(JSON, default=dict)  # {field: [old, new]}
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), index=True)
    ip: Mapped[str | None] = mapped_column(String(64))
    note: Mapped[str | None] = mapped_column(Text)  # reason given by the user, when there is one
    user_agent: Mapped[str | None] = mapped_column(String(300))
    branch_id: Mapped[int | None] = mapped_column(Integer)  # branch of the user who acted
    impersonated_by: Mapped[int | None] = mapped_column(Integer)  # platform admin id when acting through "enter company"
