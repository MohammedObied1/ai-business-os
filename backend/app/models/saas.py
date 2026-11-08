"""Billing of the platform itself: subscriptions, add-ons, coupons, payments and usage."""
from datetime import date, datetime

from sqlalchemy import JSON, Boolean, Date, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin


class Subscription(Base, TimestampMixin):
    """One per company. trialing / active / past_due / grace / suspended / cancelled."""

    __tablename__ = "subscriptions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id", ondelete="CASCADE"), unique=True)
    plan_id: Mapped[int | None] = mapped_column(ForeignKey("plans.id"))
    interval: Mapped[str] = mapped_column(String(10), default="monthly")
    status: Mapped[str] = mapped_column(String(20), default="active", index=True)
    trial_ends_at: Mapped[date | None] = mapped_column(Date)
    current_period_start: Mapped[date | None] = mapped_column(Date)
    current_period_end: Mapped[date | None] = mapped_column(Date)
    grace_days: Mapped[int | None] = mapped_column(Integer)  # None = the plan's
    cancel_at_period_end: Mapped[bool] = mapped_column(Boolean, default=False)
    pending_plan_id: Mapped[int | None] = mapped_column(ForeignKey("plans.id"))  # downgrade at the end of the period
    pending_interval: Mapped[str | None] = mapped_column(String(10))
    coupon_id: Mapped[int | None] = mapped_column(ForeignKey("coupons.id"))
    coupon_cycles_left: Mapped[int | None] = mapped_column(Integer)  # None = forever
    notes: Mapped[str | None] = mapped_column(Text)
    items: Mapped[list["SubscriptionItem"]] = relationship(cascade="all, delete-orphan", lazy="selectin")


class AddOn(Base, TimestampMixin):
    """Something sold on top of a plan (extra users, more AI…). `grants` raises limits, e.g. {"max_users": 5}."""

    __tablename__ = "addons"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(40), unique=True)
    name: Mapped[str] = mapped_column(String(120))
    price_monthly: Mapped[float] = mapped_column(Float, default=0)
    price_yearly: Mapped[float] = mapped_column(Float, default=0)
    grants: Mapped[dict] = mapped_column(JSON, default=dict)
    features: Mapped[list] = mapped_column(JSON, default=list)  # features it unlocks
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class SubscriptionItem(Base):
    __tablename__ = "subscription_items"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    subscription_id: Mapped[int] = mapped_column(ForeignKey("subscriptions.id", ondelete="CASCADE"), index=True)
    addon_id: Mapped[int] = mapped_column(ForeignKey("addons.id"))
    quantity: Mapped[int] = mapped_column(Integer, default=1)


class Coupon(Base, TimestampMixin):
    __tablename__ = "coupons"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(40), unique=True)
    percent_off: Mapped[float] = mapped_column(Float, default=0)
    amount_off: Mapped[float] = mapped_column(Float, default=0)
    duration: Mapped[str] = mapped_column(String(10), default="once")  # once / repeating / forever
    cycles: Mapped[int | None] = mapped_column(Integer)  # for repeating
    max_redemptions: Mapped[int | None] = mapped_column(Integer)
    redeemed: Mapped[int] = mapped_column(Integer, default=0)
    valid_until: Mapped[date | None] = mapped_column(Date)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class PlatformPayment(Base):
    """Money received from a company for a subscription invoice."""

    __tablename__ = "platform_payments"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id", ondelete="CASCADE"), index=True)
    invoice_id: Mapped[int] = mapped_column(ForeignKey("platform_invoices.id", ondelete="CASCADE"), index=True)
    amount: Mapped[float] = mapped_column(Float)
    method: Mapped[str] = mapped_column(String(30), default="bank")
    reference: Mapped[str | None] = mapped_column(String(120))
    paid_at: Mapped[date] = mapped_column(Date, default=date.today)
    recorded_by: Mapped[str | None] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class UsageRecord(Base):
    """Metered usage per company per month: ai_requests, api_requests."""

    __tablename__ = "usage_records"
    __table_args__ = (UniqueConstraint("company_id", "metric", "period", name="uq_usage"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id", ondelete="CASCADE"), index=True)
    metric: Mapped[str] = mapped_column(String(30))
    period: Mapped[str] = mapped_column(String(7))
    quantity: Mapped[int] = mapped_column(Integer, default=0)
