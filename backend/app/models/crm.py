from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TenantMixin, TimestampMixin


class Customer(Base, TenantMixin, TimestampMixin):
    __tablename__ = "customers"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(200), index=True)
    email: Mapped[str | None] = mapped_column(String(200))
    phone: Mapped[str | None] = mapped_column(String(50))
    address: Mapped[str | None] = mapped_column(String(300))
    customer_type: Mapped[str] = mapped_column(String(50), default="business")  # business / individual
    credit_limit: Mapped[float] = mapped_column(Float, default=0)
    score: Mapped[float] = mapped_column(Float, default=0)  # AI customer scoring 0-100
    notes: Mapped[str | None] = mapped_column(Text)
    price_list_id: Mapped[int | None] = mapped_column(ForeignKey("price_lists.id", ondelete="SET NULL"))
    assigned_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))  # sales rep
    visit_days: Mapped[str | None] = mapped_column(String(30))  # "0,3" = Sunday & Wednesday (Python weekday: Mon=0)
    lat: Mapped[float | None] = mapped_column(Float)
    lng: Mapped[float | None] = mapped_column(Float)
    portal_token: Mapped[str | None] = mapped_column(String(64), index=True)
    portal_expires_at: Mapped[datetime | None] = mapped_column(DateTime)  # links always expire; staff can renew or revoke
    portal_last_seen_at: Mapped[datetime | None] = mapped_column(DateTime)
    branch_id: Mapped[int | None] = mapped_column(ForeignKey("branches.id"))


class CustomerInteraction(Base, TenantMixin, TimestampMixin):
    """Communication history, complaints, follow-ups."""

    __tablename__ = "customer_interactions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(30))  # call / email / whatsapp / complaint / visit / note
    summary: Mapped[str] = mapped_column(Text)
    occurred_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
