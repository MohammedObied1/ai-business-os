"""Tenant health for the platform admin: one row per company with HEALTHY / WARNING / CRITICAL and the reasons.

Only the platform admin sees this; nothing here is exposed to companies.
"""
from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import AuditLog, Company, EmailMessage, User, WebhookDelivery
from app.models.monitor import ErrorLog, JobRun
from app.services import saas


def _backup_status(db: Session) -> dict:
    """Backups are platform-wide: latest file and the latest restore test."""
    from app.services import backup
    files = backup.list_backups() if hasattr(backup, "list_backups") else []
    latest = files[0] if files else None
    test = db.scalar(select(JobRun).where(JobRun.job == "backup_restore_test").order_by(JobRun.id.desc()))
    return {"latest": latest, "restore_test": {"status": test.status, "at": test.started_at} if test else None}


def company_health(db: Session, c: Company) -> dict:
    day, month = datetime.utcnow() - timedelta(days=1), datetime.utcnow() - timedelta(days=30)
    sub = saas.subscription(db, c)
    status = saas.status_for(db, c.id)
    errors_24h = db.scalar(select(func.count(ErrorLog.id)).where(ErrorLog.company_id == c.id, ErrorLog.created_at >= day, ErrorLog.level == "error")) or 0
    email_failed = db.scalar(select(func.count(EmailMessage.id)).where(EmailMessage.company_id == c.id, EmailMessage.status == "failed",
                                                                       EmailMessage.created_at >= month)) or 0
    hooks_failed = db.scalar(select(func.count(WebhookDelivery.id)).where(WebhookDelivery.company_id == c.id, WebhookDelivery.status == "failed",
                                                                         WebhookDelivery.created_at >= month)) or 0
    last_activity = db.scalar(select(func.max(AuditLog.created_at)).where(AuditLog.company_id == c.id))
    last_login = db.scalar(select(func.max(User.last_login_at)).where(User.company_id == c.id))
    users = db.scalar(select(func.count(User.id)).where(User.company_id == c.id, User.is_active.is_(True))) or 0
    near = [lim["key"] for lim in status["limits"] if lim["limit"] and lim["used"] >= lim["limit"] * 0.9]

    reasons, level = [], "HEALTHY"

    def flag(lvl: str, why: str):
        nonlocal level
        reasons.append(why)
        if lvl == "CRITICAL" or (lvl == "WARNING" and level == "HEALTHY"):
            level = lvl

    if not c.is_active or sub.status == "suspended":
        flag("CRITICAL", "suspended")
    elif sub.status in ("grace", "past_due"):
        flag("WARNING", f"subscription {sub.status}")
    if errors_24h >= 10:
        flag("CRITICAL", f"{errors_24h} errors in 24h")
    elif errors_24h:
        flag("WARNING", f"{errors_24h} errors in 24h")
    if email_failed or hooks_failed:
        flag("WARNING", f"{email_failed} emails / {hooks_failed} webhooks failed (30 days)")
    if near:
        flag("WARNING", "near limit: " + ", ".join(near))
    if not last_activity or last_activity < datetime.utcnow() - timedelta(days=30):
        flag("WARNING", "no activity for 30 days")
    return {"company_id": c.id, "company": c.name, "level": level, "reasons": reasons, "subscription": sub.status, "plan": status["plan"],
            "users": users, "storage_mb": saas.storage_mb(db, c.id), "ai_requests": saas.usage(db, c.id, "ai_requests"),
            "api_requests": saas.usage(db, c.id, "api_requests"), "errors_24h": errors_24h, "email_failed": email_failed, "webhooks_failed": hooks_failed,
            "last_activity": last_activity, "last_login": last_login, "limits": status["limits"]}


def platform_health(db: Session) -> dict:
    rows = [company_health(db, c) for c in db.scalars(select(Company).order_by(Company.name)).all()]
    db.commit()  # subscriptions may have been created on the fly
    order = {"CRITICAL": 0, "WARNING": 1, "HEALTHY": 2}
    rows.sort(key=lambda r: (order[r["level"]], r["company"]))
    return {"summary": {k: sum(1 for r in rows if r["level"] == k) for k in order}, "companies": rows, "backups": _backup_status(db)}
