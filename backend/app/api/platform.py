"""Platform admin: the account that owns the platform and manages every company in it."""
from datetime import date, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import get_platform_admin
from app.core.security import create_access_token, hash_password, validate_password, verify_password
from app.models import User, Company, Plan, PlatformAdmin
from app.schemas.auth import (
    CompanyOut, CompanyStats, OwnerPasswordReset, PasswordChange, PlatformAdminOut, PlatformCompanyIn, PlatformCompanyOut, PlatformCompanyUpdate, Token,
)
from app.services.companies import company_owner, company_stats, create_company, delete_company

router = APIRouter(prefix="/platform", tags=["platform admin"])


def _company(db: Session, cid: int) -> Company:
    c = db.get(Company, cid)
    if not c:
        raise HTTPException(404, "Company not found")
    return c


def _out(db: Session, c: Company) -> PlatformCompanyOut:
    owner = company_owner(db, c.id)
    # from_attributes picks up every field straight off the ORM row (custom_domain, slug, brand_color, the costing
    # method, all the toggles…) so none of them silently default to empty just because this function forgot to list them
    base = CompanyOut.model_validate(c).model_dump()
    return PlatformCompanyOut(
        **base, notes=c.notes, created_at=c.created_at,
        owner_name=owner.full_name if owner else None, owner_email=owner.email if owner else None,
        stats=CompanyStats(**company_stats(db, c.id)),
    )


@router.get("/me", response_model=PlatformAdminOut)
def me(admin: PlatformAdmin = Depends(get_platform_admin)):
    return admin


@router.post("/change-password", status_code=204)
def change_password(payload: PasswordChange, admin: PlatformAdmin = Depends(get_platform_admin), db: Session = Depends(get_db)):
    if not verify_password(payload.current_password, admin.hashed_password):
        raise HTTPException(400, "Current password is wrong")
    if (err := validate_password(payload.new_password)) is not None:
        raise HTTPException(400, err)
    admin.hashed_password = hash_password(payload.new_password)
    db.commit()


@router.get("/companies", response_model=list[PlatformCompanyOut])
def list_companies(admin: PlatformAdmin = Depends(get_platform_admin), db: Session = Depends(get_db)):
    return [_out(db, c) for c in db.scalars(select(Company).order_by(Company.id.desc())).all()]


@router.post("/companies", response_model=PlatformCompanyOut, status_code=201)
def new_company(payload: PlatformCompanyIn, admin: PlatformAdmin = Depends(get_platform_admin), db: Session = Depends(get_db)):
    data = payload.model_dump()
    company, _ = create_company(
        db, name=data.pop("name"), owner_name=data.pop("owner_name"), owner_email=data.pop("owner_email"),
        password=data.pop("owner_password"), currency=data.pop("currency"), industry=data.pop("industry"), **data,
    )
    from app.services import saas
    plan = db.get(Plan, company.plan_id) if company.plan_id else None
    if not company.subscription_ends_at:  # an explicit end date from the admin wins; otherwise trial / first invoice per the plan
        sub = saas.start(db, company, plan)
        if plan and sub.status == "past_due":
            saas.issue_invoice(db, sub, date.today(), saas.add_period(date.today(), "monthly"), saas.quote(db, sub), "First period")
        db.commit()
    return _out(db, company)


@router.get("/companies/{cid}", response_model=PlatformCompanyOut)
def get_company(cid: int, admin: PlatformAdmin = Depends(get_platform_admin), db: Session = Depends(get_db)):
    return _out(db, _company(db, cid))


@router.patch("/companies/{cid}", response_model=PlatformCompanyOut)
def update_company(cid: int, payload: PlatformCompanyUpdate, admin: PlatformAdmin = Depends(get_platform_admin), db: Session = Depends(get_db)):
    c = _company(db, cid)
    data = payload.model_dump(exclude_unset=True)
    for k, v in data.items():
        setattr(c, k, v)
    if "custom_domain" in data:
        # the platform admin sets this only after confirming ownership out of band (support channel) — treat it as
        # already verified, unlike the company's own self-service flow which requires the DNS TXT proof
        c.domain_verified_at = datetime.utcnow() if data["custom_domain"] else None
        c.domain_verify_token = None
    if "plan_id" in data or "subscription_ends_at" in data:  # a manual change by the admin also moves the subscription
        from app.services import saas
        sub = saas.subscription(db, c)
        if "plan_id" in data:
            sub.plan_id = data["plan_id"]
        if "subscription_ends_at" in data:
            sub.current_period_end, sub.status = data["subscription_ends_at"], "active"
    db.commit()
    return _out(db, c)


@router.post("/companies/{cid}/owner-password", status_code=204)
def reset_owner_password(cid: int, payload: OwnerPasswordReset, admin: PlatformAdmin = Depends(get_platform_admin), db: Session = Depends(get_db)):
    owner = company_owner(db, _company(db, cid).id)
    if not owner:
        raise HTTPException(404, "Company has no users")
    if (err := validate_password(payload.new_password)) is not None:
        raise HTTPException(400, err)
    owner.hashed_password = hash_password(payload.new_password)
    db.commit()


@router.post("/companies/{cid}/enter", response_model=Token)
def enter_company(cid: int, request: Request, user_id: int | None = None, admin: PlatformAdmin = Depends(get_platform_admin),
                  db: Session = Depends(get_db)):
    """Open the company as its owner — or as one chosen user — for support. Needs the admin's impersonation right;
    the session is marked as impersonated and the visit is written to the company's own activity log."""
    if not admin.can_impersonate:
        raise HTTPException(403, "You are not allowed to enter companies")
    _company(db, cid)
    if user_id:
        owner = db.get(User, user_id)
        if not owner or owner.company_id != cid or not owner.is_active:
            raise HTTPException(404, "User not found")
    else:
        owner = company_owner(db, cid)
    if not owner:
        raise HTTPException(404, "Company has no users")
    # never hidden: the company's own activity log shows that the platform admin came in
    from app.core.audit import log_event
    from app.core.deps import client_ip
    log_event(db, cid, "impersonation_start", "companies", label=f"Platform admin {admin.email} entered as {owner.email}",
              user_name=f"{admin.full_name} (platform admin)", ip=client_ip(request), impersonated_by=admin.id)
    db.commit()
    return Token(access_token=create_access_token(owner.id, cid, impersonated_by=admin.id), kind="company")


@router.delete("/companies/{cid}", status_code=204)
def remove_company(cid: int, confirm_name: str, admin: PlatformAdmin = Depends(get_platform_admin), db: Session = Depends(get_db)):
    c = _company(db, cid)
    if confirm_name.strip() != c.name:
        raise HTTPException(400, "Type the exact company name to confirm deletion")
    delete_company(db, cid)



# ---------------------------------------------------------------- plans & subscriptions
class PlanIn(BaseModel):
    name: str
    price_monthly: float = 0
    max_users: int = 5
    max_branches: int = 1
    features: list[str] = []
    is_active: bool = True


def _plan_out(p: Plan) -> dict:
    return {"id": p.id, "name": p.name, "price_monthly": p.price_monthly, "max_users": p.max_users, "max_branches": p.max_branches,
            "features": p.features or [], "is_active": p.is_active}


@router.get("/plans")
def list_plans(admin: PlatformAdmin = Depends(get_platform_admin), db: Session = Depends(get_db)):
    return [_plan_out(p) for p in db.scalars(select(Plan).order_by(Plan.price_monthly)).all()]


@router.post("/plans", status_code=201)
def create_plan(payload: PlanIn, admin: PlatformAdmin = Depends(get_platform_admin), db: Session = Depends(get_db)):
    p = Plan(**payload.model_dump())
    db.add(p)
    db.commit()
    return _plan_out(p)


@router.patch("/plans/{plan_id}")
def update_plan(plan_id: int, payload: PlanIn, admin: PlatformAdmin = Depends(get_platform_admin), db: Session = Depends(get_db)):
    p = db.get(Plan, plan_id)
    if not p:
        raise HTTPException(404, "Plan not found")
    for k, v in payload.model_dump().items():
        setattr(p, k, v)
    db.commit()
    return _plan_out(p)


@router.post("/companies/{cid}/extend", response_model=PlatformCompanyOut)
def extend_subscription(cid: int, months: int = 1, admin: PlatformAdmin = Depends(get_platform_admin), db: Session = Depends(get_db)):
    """Renew: add months from today (or from the current end date if it is still in the future)."""
    c = _company(db, cid)
    base = c.subscription_ends_at if c.subscription_ends_at and c.subscription_ends_at > date.today() else date.today()
    y, m = divmod(base.month - 1 + months, 12)
    day = min(base.day, 28)
    c.subscription_ends_at = date(base.year + y, m + 1, day)
    from app.services import saas
    sub = saas.subscription(db, c)  # the subscription follows the manual extension
    sub.current_period_end, sub.status = c.subscription_ends_at, "active"
    db.commit()
    return _out(db, c)


@router.get("/overview")
def overview(admin: PlatformAdmin = Depends(get_platform_admin), db: Session = Depends(get_db)):
    companies = db.scalars(select(Company)).all()
    plans = {p.id: p for p in db.scalars(select(Plan)).all()}
    today = date.today()
    soon = today + timedelta(days=14)
    mrr = sum(plans[c.plan_id].price_monthly for c in companies if c.is_active and c.plan_id in plans and (not c.subscription_ends_at or c.subscription_ends_at >= today))
    return {"companies": len(companies), "active": sum(1 for c in companies if c.is_active), "mrr": round(mrr, 2),
            "expired": [{"id": c.id, "name": c.name, "ends": c.subscription_ends_at} for c in companies if c.subscription_ends_at and c.subscription_ends_at < today],
            "expiring_soon": [{"id": c.id, "name": c.name, "ends": c.subscription_ends_at} for c in companies
                              if c.subscription_ends_at and today <= c.subscription_ends_at <= soon]}


# ---------------------------------------------------------------- backups
@router.get("/backups")
def backups(admin: PlatformAdmin = Depends(get_platform_admin)):
    from app.services import backup
    return {"folder": backup.backup_dir(), "items": backup.list_backups()}


@router.post("/backups", status_code=201)
def backup_now(admin: PlatformAdmin = Depends(get_platform_admin)):
    from app.services import backup
    try:
        return backup.create_backup()
    except Exception as ex:  # noqa: BLE001
        raise HTTPException(500, f"Backup failed: {ex}")


@router.get("/backups/{name}")
def download_backup(name: str, admin: PlatformAdmin = Depends(get_platform_admin)):
    from app.services import backup
    try:
        return FileResponse(backup.backup_path(name), filename=name, media_type="application/octet-stream")
    except FileNotFoundError:
        raise HTTPException(404, "Backup not found")


@router.post("/backups/restore-test")
def run_restore_test(admin: PlatformAdmin = Depends(get_platform_admin)):
    """Disaster-recovery check, on demand instead of waiting for Sunday's scheduled run."""
    from app.services.backup import restore_test
    try:
        return {"ok": True, "detail": restore_test()}
    except Exception as ex:  # noqa: BLE001
        return {"ok": False, "detail": str(ex)}


# ---------------------------------------------------------------- admin security
class AdminOtpIn(BaseModel):
    code: str


@router.post("/2fa/setup")
def admin_otp_setup(admin: PlatformAdmin = Depends(get_platform_admin), db: Session = Depends(get_db)):
    from app.core.security import new_totp_secret, totp_uri
    if admin.totp_enabled:
        raise HTTPException(400, "Two-step verification is already on")
    admin.totp_secret = new_totp_secret()
    db.commit()
    return {"secret": admin.totp_secret, "uri": totp_uri(admin.totp_secret, admin.email, "AI Business OS Admin")}


@router.post("/2fa/enable", status_code=204)
def admin_otp_enable(payload: AdminOtpIn, admin: PlatformAdmin = Depends(get_platform_admin), db: Session = Depends(get_db)):
    from app.core.security import verify_totp
    if not verify_totp(admin.totp_secret, payload.code):
        raise HTTPException(400, "Wrong verification code")
    admin.totp_enabled = True
    db.commit()


class AdminOtpOff(BaseModel):
    password: str
    code: str


@router.post("/2fa/disable", status_code=204)
def admin_otp_disable(payload: AdminOtpOff, admin: PlatformAdmin = Depends(get_platform_admin), db: Session = Depends(get_db)):
    from app.core.security import verify_password, verify_totp
    if not verify_password(payload.password, admin.hashed_password) or not verify_totp(admin.totp_secret, payload.code):
        raise HTTPException(400, "Wrong password or verification code")
    admin.totp_enabled, admin.totp_secret = False, None
    db.commit()


@router.post("/logout-all", status_code=204)
def admin_logout_all(admin: PlatformAdmin = Depends(get_platform_admin), db: Session = Depends(get_db)):
    admin.token_version = (admin.token_version or 0) + 1
    db.commit()


@router.get("/security")
def security_overview(admin: PlatformAdmin = Depends(get_platform_admin), db: Session = Depends(get_db)):
    """Recent sign-ins across the platform, failed attempts first."""
    from app.models import LoginEvent
    rows = db.scalars(select(LoginEvent).order_by(LoginEvent.id.desc()).limit(300)).all()
    names = {c.id: c.name for c in db.scalars(select(Company)).all()}
    return {"totp_enabled": bool(admin.totp_enabled),
            "events": [{"at": r.created_at, "email": r.email, "success": r.success, "reason": r.reason, "ip": r.ip, "company": names.get(r.company_id)} for r in rows]}


@router.get("/outbox")
def outbox(admin: PlatformAdmin = Depends(get_platform_admin), db: Session = Depends(get_db)):
    from app.models import EmailMessage
    from app.services.email import smtp_configured
    rows = db.scalars(select(EmailMessage).order_by(EmailMessage.id.desc()).limit(200)).all()
    return {"smtp": smtp_configured(), "items": [{"id": m.id, "to": m.to, "subject": m.subject, "kind": m.kind, "status": m.status, "error": m.error,
                                                   "created_at": m.created_at, "body_html": m.body_html} for m in rows]}


# ---------------------------------------------------------------- billing companies (the platform's own invoices)
class PlatformInvoiceIn(BaseModel):
    amount: float
    period: str
    note: str | None = None


def _pinv_out(i, names: dict) -> dict:
    return {"id": i.id, "company_id": i.company_id, "company": names.get(i.company_id), "number": i.number, "period": i.period, "plan_name": i.plan_name,
            "amount": i.amount, "due_date": i.due_date, "status": i.status, "paid_at": i.paid_at, "note": i.note}


@router.get("/billing")
def billing(admin: PlatformAdmin = Depends(get_platform_admin), db: Session = Depends(get_db)):
    from app.models import PlatformInvoice
    names = {c.id: c.name for c in db.scalars(select(Company)).all()}
    rows = db.scalars(select(PlatformInvoice).order_by(PlatformInvoice.id.desc()).limit(500)).all()
    unpaid = sum(i.amount for i in rows if i.status == "unpaid")
    return {"unpaid_total": round(unpaid, 2), "items": [_pinv_out(i, names) for i in rows]}


@router.post("/billing/run")
def run_billing(admin: PlatformAdmin = Depends(get_platform_admin), db: Session = Depends(get_db)):
    """Run the billing cycle now: renewal invoices ahead of time, then grace / suspension (normally daily at 06:00)."""
    from app.services import saas
    return {"created": saas.billing_cycle(db)["invoices"]}


@router.post("/companies/{cid}/invoices", status_code=201)
def add_company_invoice(cid: int, payload: PlatformInvoiceIn, admin: PlatformAdmin = Depends(get_platform_admin), db: Session = Depends(get_db)):
    from app.services.platform_billing import create_invoice
    c = _company(db, cid)
    inv = create_invoice(db, c, payload.amount, payload.period, note=payload.note)
    db.commit()
    return _pinv_out(inv, {c.id: c.name})


@router.post("/billing/{invoice_id}/paid")
def mark_paid(invoice_id: int, extend_months: int = 1, admin: PlatformAdmin = Depends(get_platform_admin), db: Session = Depends(get_db)):
    """Record the company's payment and (optionally) extend its subscription."""
    from app.models import PlatformInvoice
    inv = db.get(PlatformInvoice, invoice_id)
    if not inv:
        raise HTTPException(404, "Invoice not found")
    from app.services import saas
    if inv.subscription_id:  # the invoice knows its period: paying it moves the subscription there
        saas.pay(db, inv, round(inv.amount - (inv.paid_amount or 0), 2), by=admin.full_name)
    else:  # older / manual invoice
        inv.status, inv.paid_at = "paid", date.today()
        if extend_months:
            extend_subscription(inv.company_id, extend_months, admin, db)
    db.commit()
    return {"status": inv.status}


@router.post("/billing/{invoice_id}/void")
def void_invoice(invoice_id: int, admin: PlatformAdmin = Depends(get_platform_admin), db: Session = Depends(get_db)):
    from app.models import PlatformInvoice
    inv = db.get(PlatformInvoice, invoice_id)
    if not inv:
        raise HTTPException(404, "Invoice not found")
    inv.status = "void"
    db.commit()
    return {"status": inv.status}


# ---------------------------------------------------------------- tenant activity (support / investigations)
@router.get("/companies/{cid}/audit")
def company_audit(cid: int, response: Response, entity: str | None = None, action: str | None = None, q: str | None = None, ip: str | None = None,
                  date_from: date | None = None, date_to: date | None = None, offset: int = 0, limit: int = 100,
                  admin: PlatformAdmin = Depends(get_platform_admin), db: Session = Depends(get_db)):
    """One company's activity log, for the platform admin only (never exposed to other companies)."""
    from app.api.org import audit_out, audit_query
    from app.core.pagination import page
    _company(db, cid)
    stmt = audit_query(cid, entity, None, action, q, ip, None, date_from, date_to)
    return [audit_out(a) for a in page(db, stmt, response, offset, min(limit, 1000))]


@router.get("/companies/{cid}/users")
def company_users(cid: int, admin: PlatformAdmin = Depends(get_platform_admin), db: Session = Depends(get_db)):
    """The company's users (names and roles only) — so support can enter as the person who reported a problem."""
    _company(db, cid)
    return [{"id": u.id, "full_name": u.full_name, "email": u.email, "role": u.role.name if u.role else None, "is_active": u.is_active,
             "last_login_at": u.last_login_at}
            for u in db.scalars(select(User).where(User.company_id == cid).order_by(User.id)).all()]


# ---------------------------------------------------------------- platform admins (who can do what)
class AdminIn(BaseModel):
    email: str
    full_name: str
    password: str | None = None
    is_owner: bool = False
    can_impersonate: bool = False
    is_active: bool = True


def _admin_out(a: PlatformAdmin) -> dict:
    return {"id": a.id, "email": a.email, "full_name": a.full_name, "is_owner": a.is_owner, "can_impersonate": a.can_impersonate,
            "is_active": a.is_active, "totp_enabled": a.totp_enabled}


def _owner_only(admin: PlatformAdmin) -> None:
    if not admin.is_owner:
        raise HTTPException(403, "Only a platform owner can manage platform admins")


@router.get("/admins")
def list_admins(admin: PlatformAdmin = Depends(get_platform_admin), db: Session = Depends(get_db)):
    return [_admin_out(a) for a in db.scalars(select(PlatformAdmin).order_by(PlatformAdmin.id)).all()]


@router.post("/admins", status_code=201)
def create_admin(payload: AdminIn, admin: PlatformAdmin = Depends(get_platform_admin), db: Session = Depends(get_db)):
    from app.services.companies import email_taken
    _owner_only(admin)
    if email_taken(db, payload.email):
        raise HTTPException(400, "Email already exists")
    if not payload.password or (err := validate_password(payload.password)) is not None:
        raise HTTPException(400, err if payload.password else "Password is required")
    a = PlatformAdmin(email=payload.email.strip().lower(), full_name=payload.full_name, hashed_password=hash_password(payload.password),
                      is_owner=payload.is_owner, can_impersonate=payload.can_impersonate, is_active=payload.is_active)
    db.add(a)
    db.commit()
    return _admin_out(a)


@router.patch("/admins/{admin_id}")
def update_admin(admin_id: int, payload: AdminIn, admin: PlatformAdmin = Depends(get_platform_admin), db: Session = Depends(get_db)):
    _owner_only(admin)
    a = db.get(PlatformAdmin, admin_id)
    if not a:
        raise HTTPException(404, "Admin not found")
    if a.id == admin.id and (not payload.is_owner or not payload.is_active):
        raise HTTPException(400, "You can't remove your own owner rights")
    a.full_name, a.is_owner, a.can_impersonate, a.is_active = payload.full_name, payload.is_owner, payload.can_impersonate, payload.is_active
    if payload.password:
        if (err := validate_password(payload.password)) is not None:
            raise HTTPException(400, err)
        a.hashed_password = hash_password(payload.password)
        a.token_version = (a.token_version or 0) + 1
    db.commit()
    return _admin_out(a)


# ---------------------------------------------------------------- system: health of the platform and of each company
@router.get("/system")
def system(admin: PlatformAdmin = Depends(get_platform_admin), db: Session = Depends(get_db)):
    """Request metrics (since the last restart), server resources, background jobs, recent problems."""
    from datetime import datetime, timedelta
    from sqlalchemy import func
    from app.core.observability import LAST_RUNS, METRICS, system_resources
    from app.models import EmailMessage, WebhookDelivery
    from app.models.monitor import ErrorLog, JobRun
    day = datetime.utcnow() - timedelta(days=1)
    jobs = {}
    for name in ("automation", "backup", "email", "webhooks", "recurring", "billing", "daily_summary", "backup_restore_test"):
        last = db.scalar(select(JobRun).where(JobRun.job == name).order_by(JobRun.id.desc()))
        jobs[name] = {"last_recorded": {"status": last.status, "at": last.started_at, "ms": last.duration_ms, "detail": last.detail} if last else None,
                      "last_in_memory": LAST_RUNS.get(name),
                      "failures_24h": db.scalar(select(func.count(JobRun.id)).where(JobRun.job == name, JobRun.status == "failed", JobRun.started_at >= day)) or 0}
    by_source = dict(db.execute(select(ErrorLog.source, func.count(ErrorLog.id)).where(ErrorLog.created_at >= day).group_by(ErrorLog.source)).all())
    return {"metrics": METRICS.snapshot(), "resources": system_resources(), "jobs": jobs, "errors_24h": by_source,
            "email_failed_24h": db.scalar(select(func.count(EmailMessage.id)).where(EmailMessage.status == "failed", EmailMessage.created_at >= day)) or 0,
            "email_waiting": db.scalar(select(func.count(EmailMessage.id)).where(EmailMessage.status.in_(("queued", "saved")))) or 0,
            "webhooks_failed_24h": db.scalar(select(func.count(WebhookDelivery.id)).where(WebhookDelivery.status == "failed", WebhookDelivery.created_at >= day)) or 0,
            "webhooks_pending": db.scalar(select(func.count(WebhookDelivery.id)).where(WebhookDelivery.status == "pending")) or 0}


@router.get("/errors")
def errors(response: Response, source: str | None = None, company_id: int | None = None, level: str | None = None, offset: int = 0, limit: int = 100,
           admin: PlatformAdmin = Depends(get_platform_admin), db: Session = Depends(get_db)):
    from app.core.pagination import page
    from app.models.monitor import ErrorLog
    stmt = select(ErrorLog)
    if source:
        stmt = stmt.where(ErrorLog.source == source)
    if company_id:
        stmt = stmt.where(ErrorLog.company_id == company_id)
    if level:
        stmt = stmt.where(ErrorLog.level == level)
    names = {c.id: c.name for c in db.scalars(select(Company)).all()}
    return [{"id": e.id, "at": e.created_at, "level": e.level, "source": e.source, "company": names.get(e.company_id), "method": e.method, "path": e.path,
             "status": e.status, "ms": e.duration_ms, "message": e.message, "detail": e.detail}
            for e in page(db, stmt.order_by(ErrorLog.id.desc()), response, offset, min(limit, 500))]


@router.get("/jobs")
def job_runs(response: Response, job: str | None = None, offset: int = 0, limit: int = 100, admin: PlatformAdmin = Depends(get_platform_admin),
             db: Session = Depends(get_db)):
    from app.core.pagination import page
    from app.models.monitor import JobRun
    stmt = select(JobRun)
    if job:
        stmt = stmt.where(JobRun.job == job)
    return [{"id": j.id, "job": j.job, "started_at": j.started_at, "finished_at": j.finished_at, "status": j.status, "ms": j.duration_ms, "detail": j.detail}
            for j in page(db, stmt.order_by(JobRun.id.desc()), response, offset, min(limit, 500))]


@router.get("/health")
def tenants_health(admin: PlatformAdmin = Depends(get_platform_admin), db: Session = Depends(get_db)):
    from app.services.health import platform_health
    return platform_health(db)
