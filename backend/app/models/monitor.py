"""Platform observability: errors, background job runs."""
from datetime import datetime

from sqlalchemy import DateTime, Float, Index, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class ErrorLog(Base):
    """Something went wrong: an HTTP 5xx, a failed job, e-mail / webhook / AI / backup failure, a slow query."""

    __tablename__ = "error_logs"
    __table_args__ = (Index("ix_error_logs_company_created", "company_id", "created_at"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), index=True)
    level: Mapped[str] = mapped_column(String(10), default="error")  # error / warning
    source: Mapped[str] = mapped_column(String(20), index=True)  # http / job / db / email / webhook / ai / backup
    company_id: Mapped[int | None] = mapped_column(Integer)
    method: Mapped[str | None] = mapped_column(String(10))
    path: Mapped[str | None] = mapped_column(String(300))
    status: Mapped[int | None] = mapped_column(Integer)
    duration_ms: Mapped[float | None] = mapped_column(Float)
    message: Mapped[str] = mapped_column(String(500))
    detail: Mapped[str | None] = mapped_column(Text)


class JobRun(Base):
    __tablename__ = "job_runs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    job: Mapped[str] = mapped_column(String(60), index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime)
    status: Mapped[str] = mapped_column(String(10), default="running")  # running / ok / failed
    duration_ms: Mapped[float | None] = mapped_column(Float)
    detail: Mapped[str | None] = mapped_column(Text)
