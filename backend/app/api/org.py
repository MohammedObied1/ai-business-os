"""Company organisation: branches, logo, audit log and payment reminders."""
import os
from datetime import date

from fastapi import APIRouter, Depends, File, HTTPException, Response, UploadFile
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.core.deps import get_current_user, require_permission
from app.core.pagination import page
from app.models import AuditLog, Branch, Company, Customer, Invoice, Plan, User
from app.services import analytics
from app.services.sales_ops import ensure_public_token

router = APIRouter(tags=["organisation"])


class BranchIn(BaseModel):
    name: str
    address: str | None = None
    phone: str | None = None
    is_active: bool = True


def plan_limit(db: Session, cid: int, field: str) -> int:
    """Plan limit plus add-ons (0 = unlimited)."""
    from app.services import saas
    return saas.limit(db, cid, field)


# ---------------------------------------------------------------- branches
@router.get("/branches")
def branches(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return [{"id": b.id, "name": b.name, "address": b.address, "phone": b.phone, "is_active": b.is_active}
            for b in db.scalars(select(Branch).where(Branch.company_id == user.company_id).order_by(Branch.id)).all()]


@router.post("/branches", status_code=201)
def create_branch(payload: BranchIn, user: User = Depends(require_permission("settings:write")), db: Session = Depends(get_db)):
    limit = plan_limit(db, user.company_id, "max_branches")
    count = db.scalar(select(func.count(Branch.id)).where(Branch.company_id == user.company_id)) or 0
    if limit and count >= limit:
        raise HTTPException(403, f"Your plan allows {limit} branch(es). Contact the platform admin to upgrade.")
    b = Branch(company_id=user.company_id, **payload.model_dump())
    db.add(b)
    db.commit()
    return {"id": b.id}


@router.patch("/branches/{branch_id}")
def update_branch(branch_id: int, payload: BranchIn, user: User = Depends(require_permission("settings:write")), db: Session = Depends(get_db)):
    b = db.get(Branch, branch_id)
    if not b or b.company_id != user.company_id:
        raise HTTPException(404, "Branch not found")
    for k, v in payload.model_dump().items():
        setattr(b, k, v)
    db.commit()
    return {"id": b.id}


# ---------------------------------------------------------------- logo
ALLOWED_LOGO = {".png", ".jpg", ".jpeg", ".webp", ".svg"}


@router.post("/company/logo")
async def upload_logo(file: UploadFile = File(...), user: User = Depends(require_permission("settings:write")), db: Session = Depends(get_db)):
    ext = os.path.splitext(file.filename or "")[1].lower()
    if ext not in ALLOWED_LOGO:
        raise HTTPException(400, "Logo must be PNG, JPG, WEBP or SVG")
    data = await file.read()
    if len(data) > 2 * 1024 * 1024:
        raise HTTPException(413, "Logo too large (max 2MB)")
    folder = os.path.join(settings.UPLOAD_DIR, "logos")
    os.makedirs(folder, exist_ok=True)
    c = db.get(Company, user.company_id)
    if c.logo_path and os.path.exists(c.logo_path):
        os.remove(c.logo_path)
    path = os.path.join(folder, f"{c.id}-{int(date.today().strftime('%Y%m%d'))}{ext}")
    with open(path, "wb") as f:
        f.write(data)
    c.logo_path = path
    db.commit()
    return {"logo_path": path}


@router.delete("/company/logo", status_code=204)
def delete_logo(user: User = Depends(require_permission("settings:write")), db: Session = Depends(get_db)):
    c = db.get(Company, user.company_id)
    if c.logo_path and os.path.exists(c.logo_path):
        os.remove(c.logo_path)
    c.logo_path = None
    db.commit()


# ---------------------------------------------------------------- audit log
def audit_query(cid: int, entity: str | None = None, user_id: int | None = None, action: str | None = None, q: str | None = None,
                ip: str | None = None, branch_id: int | None = None, date_from: date | None = None, date_to: date | None = None):
    """Audit rows of one company with the usual filters (also used by the platform admin)."""
    from datetime import datetime, time
    stmt = select(AuditLog).where(AuditLog.company_id == cid)
    if entity:
        stmt = stmt.where(AuditLog.entity == entity)
    if user_id:
        stmt = stmt.where(AuditLog.user_id == user_id)
    if action:
        stmt = stmt.where(AuditLog.action == action)
    if q:
        stmt = stmt.where(AuditLog.label.ilike(f"%{q}%"))
    if ip:
        stmt = stmt.where(AuditLog.ip.ilike(f"{ip}%"))
    if branch_id:
        stmt = stmt.where(AuditLog.branch_id == branch_id)
    if date_from:
        stmt = stmt.where(AuditLog.created_at >= datetime.combine(date_from, time.min))
    if date_to:
        stmt = stmt.where(AuditLog.created_at <= datetime.combine(date_to, time.max))
    return stmt.order_by(AuditLog.id.desc())


def audit_out(a: AuditLog) -> dict:
    return {"id": a.id, "user_id": a.user_id, "user_name": a.user_name, "action": a.action, "entity": a.entity, "entity_id": a.entity_id,
            "label": a.label, "changes": a.changes, "created_at": a.created_at, "ip": a.ip, "user_agent": a.user_agent, "branch_id": a.branch_id,
            "reason": a.note, "impersonated_by": a.impersonated_by}


@router.get("/audit")
def audit_log(response: Response, entity: str | None = None, user_id: int | None = None, action: str | None = None, q: str | None = None,
              ip: str | None = None, branch_id: int | None = None, date_from: date | None = None, date_to: date | None = None, offset: int = 0,
              limit: int = 100, user: User = Depends(require_permission("audit:read")), db: Session = Depends(get_db)):
    stmt = audit_query(user.company_id, entity, user_id, action, q, ip, branch_id, date_from, date_to)
    return [audit_out(a) for a in page(db, stmt, response, offset, min(limit, 2000))]


# ---------------------------------------------------------------- WhatsApp reminders
@router.get("/reminders")
def reminders(user: User = Depends(require_permission("customers:read")), db: Session = Depends(get_db)):
    """Customers with overdue balances, each with a ready WhatsApp message and a link to their oldest invoice."""
    cid = user.company_id
    company = db.get(Company, cid)
    out = []
    for row in analytics.customers_owing_more_than(db, cid, 0):
        overdue = db.scalars(select(Invoice).where(Invoice.company_id == cid, Invoice.customer_id == row["customer_id"],
                                                   Invoice.status.in_(analytics.OPEN_INVOICE), Invoice.due_date < date.today())
                             .order_by(Invoice.due_date)).all()
        if not overdue:
            continue
        cust = db.get(Customer, row["customer_id"])
        oldest = overdue[0]
        token = ensure_public_token(oldest)
        out.append({"customer_id": cust.id, "name": cust.name, "phone": cust.phone, "balance": row["balance"], "overdue_invoices": len(overdue),
                    "oldest_due": oldest.due_date, "days_late": (date.today() - oldest.due_date).days, "invoice_id": oldest.id,
                    "invoice_number": oldest.number, "public_token": token, "company": company.name, "currency": company.currency})
    db.commit()
    return sorted(out, key=lambda x: -x["days_late"])
