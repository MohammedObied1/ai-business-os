from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TenantMixin, TimestampMixin


class AutomationRule(Base, TenantMixin, TimestampMixin):
    """IF <condition> THEN <action>. Conditions are evaluated by the automation engine."""

    __tablename__ = "automation_rules"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    # low_stock / invoice_overdue / sales_drop / inactive_customer
    condition_type: Mapped[str] = mapped_column(String(50))
    params: Mapped[dict] = mapped_column(JSON, default=dict)  # e.g. {"days": 30} / {"pct": 15}
    # create_alert / create_task / notify / create_purchase_request
    action_type: Mapped[str] = mapped_column(String(50), default="create_alert")
    severity: Mapped[str] = mapped_column(String(20), default="warning")
    requires_approval: Mapped[bool] = mapped_column(Boolean, default=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime)
    # [{"type": "alert" | "notify" | "email_customer" | "whatsapp_customer" | "create_task" | "purchase_suggestion" | "require_approval",
    #   "params": {...}}]; empty = the single legacy `action_type`
    actions: Mapped[list | None] = mapped_column(JSON)


class AutomationLog(Base, TenantMixin):
    """What an automation rule did, to whom — also stops the same action repeating on the same thing too often."""

    __tablename__ = "automation_logs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    rule_id: Mapped[int | None] = mapped_column(ForeignKey("automation_rules.id", ondelete="SET NULL"), index=True)
    match_key: Mapped[str] = mapped_column(String(200), index=True)
    action: Mapped[str] = mapped_column(String(40))
    detail: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)


class Alert(Base, TenantMixin, TimestampMixin):
    __tablename__ = "alerts"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    rule_id: Mapped[int | None] = mapped_column(ForeignKey("automation_rules.id", ondelete="SET NULL"))
    severity: Mapped[str] = mapped_column(String(20), default="warning")  # info / warning / critical / success
    category: Mapped[str] = mapped_column(String(50))  # inventory / finance / sales / crm
    title: Mapped[str] = mapped_column(String(300))
    message: Mapped[str | None] = mapped_column(Text)
    dedupe_key: Mapped[str | None] = mapped_column(String(200), index=True)
    recommended_action: Mapped[str | None] = mapped_column(String(300))
    is_read: Mapped[bool] = mapped_column(Boolean, default=False)
    is_resolved: Mapped[bool] = mapped_column(Boolean, default=False)


class Task(Base, TenantMixin, TimestampMixin):
    __tablename__ = "tasks"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(String(300))
    description: Mapped[str | None] = mapped_column(Text)
    assigned_to_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    related_customer_id: Mapped[int | None] = mapped_column(ForeignKey("customers.id"))
    status: Mapped[str] = mapped_column(String(20), default="open")
    due_date: Mapped[datetime | None] = mapped_column(DateTime)
    created_by: Mapped[str] = mapped_column(String(100), default="system")


class AIConversation(Base, TenantMixin, TimestampMixin):
    __tablename__ = "ai_conversations"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    question: Mapped[str] = mapped_column(Text)
    answer: Mapped[str] = mapped_column(Text)
    tools_used: Mapped[list] = mapped_column(JSON, default=list)
