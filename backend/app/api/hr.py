"""Employees, attendance, salary advances and monthly payroll."""
from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import require_permission
from app.models import Advance, Attendance, Employee, Expense, PayrollRun, Payslip, User
from app.services.money import get_account, post

router = APIRouter(prefix="/hr", tags=["hr & payroll"])


class EmployeeIn(BaseModel):
    full_name: str
    job_title: str | None = None
    phone: str | None = None
    national_id: str | None = None
    hire_date: date | None = None
    base_salary: float = 0
    allowances: float = 0
    working_days: int = 26
    branch_id: int | None = None
    user_id: int | None = None
    is_active: bool = True
    notes: str | None = None


class AttendanceIn(BaseModel):
    employee_id: int
    day: date
    status: str = "present"
    overtime_hours: float = 0
    note: str | None = None


class AdvanceIn(BaseModel):
    employee_id: int
    amount: float
    monthly_deduction: float
    given_on: date | None = None
    account_id: int | None = None
    note: str | None = None


class PayslipEdit(BaseModel):
    bonus: float | None = None
    other_deduction: float | None = None
    advance_deduction: float | None = None


class PayIn(BaseModel):
    account_id: int | None = None
    on: date | None = None


ATT_STATUSES = ("present", "absent", "leave", "sick", "late")
OVERTIME_RATE = 1.5


def _emp(db: Session, cid: int, eid: int) -> Employee:
    e = db.get(Employee, eid)
    if not e or e.company_id != cid:
        raise HTTPException(404, "Employee not found")
    return e


def _emp_out(e: Employee) -> dict:
    return {c: getattr(e, c) for c in ("id", "full_name", "job_title", "phone", "national_id", "hire_date", "base_salary", "allowances", "working_days",
                                       "branch_id", "user_id", "is_active", "notes")}


@router.get("/employees")
def employees(user: User = Depends(require_permission("hr:read")), db: Session = Depends(get_db)):
    rows = db.scalars(select(Employee).where(Employee.company_id == user.company_id).order_by(Employee.is_active.desc(), Employee.full_name)).all()
    owed = dict(db.execute(select(Advance.employee_id, func.sum(Advance.amount - Advance.repaid)).where(Advance.company_id == user.company_id)
                           .group_by(Advance.employee_id)).all())
    return [{**_emp_out(e), "advance_balance": round(float(owed.get(e.id, 0) or 0), 2)} for e in rows]


@router.post("/employees", status_code=201)
def create_employee(payload: EmployeeIn, user: User = Depends(require_permission("hr:write")), db: Session = Depends(get_db)):
    if not payload.full_name.strip():
        raise HTTPException(400, "Name is required")
    e = Employee(company_id=user.company_id, **payload.model_dump())
    db.add(e)
    db.commit()
    return _emp_out(e)


@router.patch("/employees/{eid}")
def update_employee(eid: int, payload: EmployeeIn, user: User = Depends(require_permission("hr:write")), db: Session = Depends(get_db)):
    e = _emp(db, user.company_id, eid)
    for k, v in payload.model_dump().items():
        setattr(e, k, v)
    db.commit()
    return _emp_out(e)


# ---------------------------------------------------------------- attendance
@router.get("/attendance")
def attendance(day: date | None = None, month: str | None = None, user: User = Depends(require_permission("hr:read")), db: Session = Depends(get_db)):
    """One day (for the daily sheet) or a whole month (for the summary)."""
    stmt = select(Attendance).where(Attendance.company_id == user.company_id)
    if day:
        stmt = stmt.where(Attendance.day == day)
    if month:
        s = date.fromisoformat(month + "-01")
        e = (s + timedelta(days=32)).replace(day=1) - timedelta(days=1)
        stmt = stmt.where(Attendance.day.between(s, e))
    return [{"id": a.id, "employee_id": a.employee_id, "day": a.day, "status": a.status, "overtime_hours": a.overtime_hours, "note": a.note}
            for a in db.scalars(stmt).all()]


@router.post("/attendance")
def mark_attendance(rows: list[AttendanceIn], user: User = Depends(require_permission("hr:write")), db: Session = Depends(get_db)):
    """Save a whole day's sheet at once (upsert per employee + day)."""
    for r in rows:
        _emp(db, user.company_id, r.employee_id)
        if r.status not in ATT_STATUSES:
            raise HTTPException(400, f"Unknown attendance status {r.status}")
        a = db.scalar(select(Attendance).where(Attendance.employee_id == r.employee_id, Attendance.day == r.day))
        if not a:
            a = Attendance(company_id=user.company_id, employee_id=r.employee_id, day=r.day)
            db.add(a)
        a.status, a.overtime_hours, a.note = r.status, r.overtime_hours, r.note
    db.commit()
    return {"saved": len(rows)}


# ---------------------------------------------------------------- advances
@router.get("/advances")
def advances(user: User = Depends(require_permission("hr:read")), db: Session = Depends(get_db)):
    return [{"id": a.id, "employee_id": a.employee_id, "amount": a.amount, "monthly_deduction": a.monthly_deduction, "repaid": a.repaid,
             "remaining": round(a.amount - a.repaid, 2), "given_on": a.given_on, "note": a.note}
            for a in db.scalars(select(Advance).where(Advance.company_id == user.company_id).order_by(Advance.given_on.desc())).all()]


@router.post("/advances", status_code=201)
def give_advance(payload: AdvanceIn, user: User = Depends(require_permission("hr:write")), db: Session = Depends(get_db)):
    e = _emp(db, user.company_id, payload.employee_id)
    if payload.amount <= 0 or payload.monthly_deduction <= 0:
        raise HTTPException(400, "Amount must be greater than zero")
    acc = get_account(db, user.company_id, payload.account_id)
    a = Advance(company_id=user.company_id, employee_id=e.id, amount=payload.amount, monthly_deduction=min(payload.monthly_deduction, payload.amount),
                given_on=payload.given_on or date.today(), account_id=acc.id, note=payload.note)
    db.add(a)
    db.flush()
    post(db, user.company_id, acc.id, -payload.amount, "advance", prefix="PV", tx_date=a.given_on, party_name=e.full_name,
         description=f"Salary advance{' - ' + payload.note if payload.note else ''}", user_id=user.id)
    db.commit()
    return {"id": a.id}


# ---------------------------------------------------------------- payroll
def _run(db: Session, cid: int, run_id: int) -> PayrollRun:
    r = db.get(PayrollRun, run_id)
    if not r or r.company_id != cid:
        raise HTTPException(404, "Payroll not found")
    return r


def _slip_net(p: Payslip) -> float:
    return round(p.base_salary + p.allowances + p.overtime + p.bonus - p.absence_deduction - p.advance_deduction - p.other_deduction, 2)


def _run_out(db: Session, r: PayrollRun) -> dict:
    slips = db.scalars(select(Payslip).where(Payslip.run_id == r.id)).all()
    names = {e.id: e.full_name for e in db.scalars(select(Employee).where(Employee.company_id == r.company_id)).all()}
    return {"id": r.id, "month": r.month, "status": r.status, "total_net": r.total_net, "paid_on": r.paid_on, "account_id": r.account_id,
            "slips": [{"id": p.id, "employee_id": p.employee_id, "employee": names.get(p.employee_id), "base_salary": p.base_salary,
                       "allowances": p.allowances, "overtime": p.overtime, "bonus": p.bonus, "absence_days": p.absence_days,
                       "absence_deduction": p.absence_deduction, "advance_deduction": p.advance_deduction, "other_deduction": p.other_deduction,
                       "net": p.net, "details": p.details} for p in slips]}


@router.get("/payroll")
def payroll_runs(user: User = Depends(require_permission("hr:read")), db: Session = Depends(get_db)):
    return [{"id": r.id, "month": r.month, "status": r.status, "total_net": r.total_net, "paid_on": r.paid_on}
            for r in db.scalars(select(PayrollRun).where(PayrollRun.company_id == user.company_id).order_by(PayrollRun.month.desc())).all()]


@router.post("/payroll", status_code=201)
def prepare_payroll(month: str, user: User = Depends(require_permission("hr:write")), db: Session = Depends(get_db)):
    """Build (or rebuild, while still a draft) the payslips of a month from salaries, attendance and advances."""
    cid = user.company_id
    try:
        s = date.fromisoformat(month + "-01")
    except ValueError:
        raise HTTPException(400, "Month must look like 2026-09")
    e_ = (s + timedelta(days=32)).replace(day=1) - timedelta(days=1)
    r = db.scalar(select(PayrollRun).where(PayrollRun.company_id == cid, PayrollRun.month == month))
    if r and r.status == "paid":
        raise HTTPException(400, "This month's payroll is already paid")
    if not r:
        r = PayrollRun(company_id=cid, month=month)
        db.add(r)
        db.flush()
    for old in db.scalars(select(Payslip).where(Payslip.run_id == r.id)).all():
        db.delete(old)
    db.flush()
    total = 0.0
    for emp in db.scalars(select(Employee).where(Employee.company_id == cid, Employee.is_active.is_(True))).all():
        att = db.scalars(select(Attendance).where(Attendance.employee_id == emp.id, Attendance.day.between(s, e_))).all()
        absent = sum(1 for a in att if a.status == "absent")
        ot_hours = sum(a.overtime_hours or 0 for a in att)
        day_value = emp.base_salary / (emp.working_days or 26)
        hour_value = day_value / 8
        adv = sum(min(a.monthly_deduction, a.amount - a.repaid) for a in db.scalars(select(Advance).where(Advance.employee_id == emp.id, Advance.amount > Advance.repaid)).all())
        p = Payslip(company_id=cid, run_id=r.id, employee_id=emp.id, base_salary=emp.base_salary, allowances=emp.allowances,
                    overtime=round(ot_hours * hour_value * OVERTIME_RATE, 2), absence_days=absent, absence_deduction=round(absent * day_value, 2),
                    advance_deduction=round(adv, 2), bonus=0, other_deduction=0,
                    details={"overtime_hours": ot_hours, "day_value": round(day_value, 2)})
        p.net = _slip_net(p)
        total += p.net
        db.add(p)
    r.total_net = round(total, 2)
    db.commit()
    return _run_out(db, r)


@router.get("/payroll/{run_id}")
def get_payroll(run_id: int, user: User = Depends(require_permission("hr:read")), db: Session = Depends(get_db)):
    return _run_out(db, _run(db, user.company_id, run_id))


@router.patch("/payroll/{run_id}/slips/{slip_id}")
def edit_slip(run_id: int, slip_id: int, payload: PayslipEdit, user: User = Depends(require_permission("hr:write")), db: Session = Depends(get_db)):
    r = _run(db, user.company_id, run_id)
    if r.status == "paid":
        raise HTTPException(400, "This month's payroll is already paid")
    p = db.get(Payslip, slip_id)
    if not p or p.run_id != r.id:
        raise HTTPException(404, "Payslip not found")
    for k, v in payload.model_dump(exclude_none=True).items():
        setattr(p, k, v)
    p.net = _slip_net(p)
    r.total_net = round(sum(x.net for x in db.scalars(select(Payslip).where(Payslip.run_id == r.id)).all()), 2)
    db.commit()
    return _run_out(db, r)


@router.post("/payroll/{run_id}/pay")
def pay_payroll(run_id: int, payload: PayIn, user: User = Depends(require_permission("hr:write")), db: Session = Depends(get_db)):
    """Pay the salaries: money leaves the account, the salary expense is recorded and advances are reduced."""
    cid = user.company_id
    r = _run(db, cid, run_id)
    if r.status == "paid":
        raise HTTPException(400, "This month's payroll is already paid")
    acc = get_account(db, cid, payload.account_id)
    on = payload.on or date.today()
    slips = db.scalars(select(Payslip).where(Payslip.run_id == r.id)).all()
    if not slips:
        raise HTTPException(400, "No payslips in this payroll")
    gross = 0.0
    for p in slips:
        remaining = p.advance_deduction
        for a in db.scalars(select(Advance).where(Advance.employee_id == p.employee_id, Advance.amount > Advance.repaid).order_by(Advance.given_on)).all():
            if remaining <= 0.009:
                break
            take = min(a.amount - a.repaid, remaining)
            a.repaid = round(a.repaid + take, 2)
            remaining -= take
        gross += p.net + p.advance_deduction
    # the salary cost is the full amount earned; the advance part was already paid out earlier
    exp = Expense(company_id=cid, category="Salaries", description=f"Payroll {r.month}", amount=round(gross, 2), expense_date=on, account_id=acc.id)
    db.add(exp)
    db.flush()
    post(db, cid, acc.id, -r.total_net, "salary", prefix="PV", tx_date=on, expense_id=exp.id, description=f"Payroll {r.month}", user_id=user.id)
    r.status, r.paid_on, r.account_id = "paid", on, acc.id
    db.commit()
    return _run_out(db, r)
