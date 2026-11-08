"""Employees, attendance, salary advances and monthly payroll."""
from datetime import date

from sqlalchemy import JSON, Date, Float, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TenantMixin, TimestampMixin


class Employee(Base, TenantMixin, TimestampMixin):
    __tablename__ = "employees"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    full_name: Mapped[str] = mapped_column(String(200))
    job_title: Mapped[str | None] = mapped_column(String(120))
    phone: Mapped[str | None] = mapped_column(String(50))
    national_id: Mapped[str | None] = mapped_column(String(50))
    hire_date: Mapped[date | None] = mapped_column(Date)
    base_salary: Mapped[float] = mapped_column(Float, default=0)
    allowances: Mapped[float] = mapped_column(Float, default=0)  # transport, phone... per month
    working_days: Mapped[int] = mapped_column(Integer, default=26)  # used to value one absent day
    branch_id: Mapped[int | None] = mapped_column(ForeignKey("branches.id"))
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    is_active: Mapped[bool] = mapped_column(default=True)
    notes: Mapped[str | None] = mapped_column(String(500))


class Attendance(Base, TenantMixin):
    __tablename__ = "attendance"
    __table_args__ = (UniqueConstraint("employee_id", "day", name="uq_attendance_day"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    employee_id: Mapped[int] = mapped_column(ForeignKey("employees.id", ondelete="CASCADE"), index=True)
    day: Mapped[date] = mapped_column(Date, index=True)
    status: Mapped[str] = mapped_column(String(20), default="present")  # present / absent / leave / sick / late
    overtime_hours: Mapped[float] = mapped_column(Float, default=0)
    note: Mapped[str | None] = mapped_column(String(200))


class Advance(Base, TenantMixin, TimestampMixin):
    """Salary advance (سلفة), paid back through monthly payroll deductions."""

    __tablename__ = "advances"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    employee_id: Mapped[int] = mapped_column(ForeignKey("employees.id", ondelete="CASCADE"), index=True)
    amount: Mapped[float] = mapped_column(Float)
    monthly_deduction: Mapped[float] = mapped_column(Float)
    repaid: Mapped[float] = mapped_column(Float, default=0)
    given_on: Mapped[date] = mapped_column(Date, default=date.today)
    account_id: Mapped[int | None] = mapped_column(ForeignKey("accounts.id"))
    note: Mapped[str | None] = mapped_column(String(200))


class PayrollRun(Base, TenantMixin, TimestampMixin):
    __tablename__ = "payroll_runs"
    __table_args__ = (UniqueConstraint("company_id", "month", name="uq_payroll_month"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    month: Mapped[str] = mapped_column(String(7))  # 2026-09
    status: Mapped[str] = mapped_column(String(20), default="draft")  # draft / paid
    total_net: Mapped[float] = mapped_column(Float, default=0)
    account_id: Mapped[int | None] = mapped_column(ForeignKey("accounts.id"))
    paid_on: Mapped[date | None] = mapped_column(Date)


class Payslip(Base, TenantMixin):
    __tablename__ = "payslips"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("payroll_runs.id", ondelete="CASCADE"), index=True)
    employee_id: Mapped[int] = mapped_column(ForeignKey("employees.id"))
    base_salary: Mapped[float] = mapped_column(Float, default=0)
    allowances: Mapped[float] = mapped_column(Float, default=0)
    overtime: Mapped[float] = mapped_column(Float, default=0)
    bonus: Mapped[float] = mapped_column(Float, default=0)
    absence_days: Mapped[float] = mapped_column(Float, default=0)
    absence_deduction: Mapped[float] = mapped_column(Float, default=0)
    advance_deduction: Mapped[float] = mapped_column(Float, default=0)
    other_deduction: Mapped[float] = mapped_column(Float, default=0)
    net: Mapped[float] = mapped_column(Float, default=0)
    details: Mapped[dict] = mapped_column(JSON, default=dict)
