"""Notification center: per-user inbox, per-user channel preferences, company routing rules."""
from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TenantMixin, TimestampMixin


class Notification(Base, TenantMixin):
    __tablename__ = "notifications"
    __table_args__ = (Index("ix_notifications_user_unread", "user_id", "read_at"), Index("ix_notifications_company_created", "company_id", "created_at"))
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    kind: Mapped[str] = mapped_column(String(40))
    severity: Mapped[str] = mapped_column(String(20), default="info")
    title: Mapped[str] = mapped_column(String(300))
    message: Mapped[str | None] = mapped_column(Text)
    link: Mapped[str | None] = mapped_column(String(300))
    dedupe_key: Mapped[str | None] = mapped_column(String(200))
    channels: Mapped[list | None] = mapped_column(JSON)  # where it was sent: in_app / email / whatsapp / push
    read_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class NotificationPreference(Base, TenantMixin):
    """A user's own choice of channels for one kind of notification."""

    __tablename__ = "notification_preferences"
    __table_args__ = (UniqueConstraint("user_id", "kind", name="uq_notification_pref"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(40))
    in_app: Mapped[bool] = mapped_column(Boolean, default=True)
    email: Mapped[bool] = mapped_column(Boolean, default=False)
    whatsapp: Mapped[bool] = mapped_column(Boolean, default=False)
    push: Mapped[bool] = mapped_column(Boolean, default=True)


class NotificationRule(Base, TenantMixin, TimestampMixin):
    """Company routing: who gets a kind of notification (people holding `permission`) and which channels by default."""

    __tablename__ = "notification_rules"
    __table_args__ = (UniqueConstraint("company_id", "kind", name="uq_notification_rule"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    kind: Mapped[str] = mapped_column(String(40))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    permission: Mapped[str | None] = mapped_column(String(60))
    email: Mapped[bool] = mapped_column(Boolean, default=False)
    whatsapp: Mapped[bool] = mapped_column(Boolean, default=False)
    note: Mapped[str | None] = mapped_column(Text)


class DashboardLayout(Base, TenantMixin, TimestampMixin):
    """A user's own dashboard: ordered widgets with their width (1-4 columns)."""

    __tablename__ = "dashboard_layouts"
    __table_args__ = (UniqueConstraint("user_id", name="uq_dashboard_user"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    widgets: Mapped[list] = mapped_column(JSON, default=list)  # [{"type": "sales_today", "w": 1}]
