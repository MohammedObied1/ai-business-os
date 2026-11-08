"""Notification center: the single way the system tells people something.

send() works out who should hear about it (one user, or everyone holding the permission the company routes that
kind to), writes an in-app notification for each, and — per the user's preferences / the company rule — also
emails them or sends WhatsApp (when a WhatsApp integration is connected). Browser notifications are shown by the
app itself for new unread items. Duplicates are skipped by `dedupe`.
"""
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import User
from app.models.comms import Notification, NotificationPreference, NotificationRule

# kind → (who receives it by default, English label)
KINDS: dict[str, tuple[str, str]] = {
    "overdue_invoice": ("finance.view", "Overdue invoices"),
    "overdue_installment": ("finance.view", "Late instalments"),
    "due_cheque": ("accounts.view", "Cheques due"),
    "low_stock": ("inventory.view", "Low stock"),
    "expiring_product": ("inventory.view", "Products expiring"),
    "cash_mismatch": ("reports.view", "Cash drawer differences"),
    "approval_request": ("approvals.approve", "Approval requests"),
    "approval_decided": ("", "My requests approved / rejected"),
    "failed_payment": ("finance.view", "Failed payments & bounced cheques"),
    "subscription_expiring": ("settings.manage", "Subscription expiring"),
    "unusual_activity": ("audit.view", "Unusual activity"),
    "system_error": ("settings.manage", "System errors"),
    "sales_drop": ("reports.view", "Sales drop"),
    "online_order": ("sales.view", "Online orders & payment notices"),
    "task": ("", "Tasks assigned to me"),
    "general": ("reports.view", "Other notices"),
}

# automation alert key prefix → notification kind
ALERT_KINDS = {"low_stock": "low_stock", "stockout": "low_stock", "overdue": "overdue_invoice", "sales_drop": "sales_drop", "expiry": "expiring_product",
               "cheque": "due_cheque", "inst": "overdue_installment", "risk": "unusual_activity", "shift": "cash_mismatch", "proof": "online_order",
               "online": "online_order", "bounced": "failed_payment", "bounce": "failed_payment", "sub": "subscription_expiring"}


def rule(db: Session, cid: int, kind: str) -> dict:
    r = db.scalar(select(NotificationRule).where(NotificationRule.company_id == cid, NotificationRule.kind == kind))
    default_perm = KINDS.get(kind, ("reports.view", ""))[0]
    return {"kind": kind, "enabled": r.enabled if r else True, "permission": (r.permission if r and r.permission is not None else default_perm),
            "email": bool(r and r.email), "whatsapp": bool(r and r.whatsapp)}


def _recipients(db: Session, cid: int, permission: str | None) -> list[User]:
    from app.core.deps import has_permission
    users = db.scalars(select(User).where(User.company_id == cid, User.is_active.is_(True))).all()
    return [u for u in users if not permission or has_permission(u, permission)]


def _prefs(db: Session, user: User, kind: str, company_rule: dict) -> dict:
    p = db.scalar(select(NotificationPreference).where(NotificationPreference.user_id == user.id, NotificationPreference.kind == kind))
    if p:
        return {"in_app": p.in_app, "email": p.email, "whatsapp": p.whatsapp, "push": p.push}
    return {"in_app": True, "email": company_rule["email"], "whatsapp": company_rule["whatsapp"], "push": True}


def send(db: Session, cid: int, kind: str, title: str, message: str = "", link: str | None = None, dedupe: str | None = None,
         permission: str | None = None, user_id: int | None = None, severity: str = "info") -> int:
    """Notify one user (user_id) or everyone the company routes this kind to. Returns how many people were told."""
    r = rule(db, cid, kind)
    if not r["enabled"] and not user_id:
        return 0
    if user_id:
        u = db.get(User, user_id)
        people = [u] if u and u.company_id == cid and u.is_active else []
    else:
        people = _recipients(db, cid, permission if permission is not None else r["permission"])
    told = 0
    for u in people:
        if dedupe and db.scalar(select(Notification.id).where(Notification.user_id == u.id, Notification.dedupe_key == dedupe)):
            continue
        prefs = _prefs(db, u, kind, r)
        channels = []
        if prefs["in_app"] or prefs["push"]:
            channels.append("in_app")
        if prefs["email"] and u.email:
            from app.services import email as mail
            mail.queue(db, u.email, title, mail.layout(title, f"<p>{message or ''}</p>"), kind, cid)
            channels.append("email")
        if prefs["whatsapp"] and u.phone:
            from app.services import integrations
            if integrations.whatsapp_send(db, cid, u.phone, f"{title}\n{message or ''}".strip()):
                channels.append("whatsapp")
        db.add(Notification(company_id=cid, user_id=u.id, kind=kind, severity=severity, title=title[:300], message=message, link=link,
                            dedupe_key=dedupe, channels=channels))
        told += 1
    return told


def from_alert(db: Session, alert) -> None:
    """Every alert the automation (or any module) raises also reaches the right people's inbox."""
    prefix = (alert.dedupe_key or "").split(":")[0]
    kind = ALERT_KINDS.get(prefix, "general")
    send(db, alert.company_id, kind, alert.title, alert.message or alert.recommended_action or "", link="/alerts",
         dedupe=f"alert:{alert.dedupe_key or alert.id}", severity=alert.severity or "info")


# every Alert created anywhere (automation, cashier shifts, bounced cheques, online orders, portal payment notices…)
# is fanned out to the inbox of the people it concerns, in the same transaction
from sqlalchemy import event  # noqa: E402
from sqlalchemy.orm import Session as _Session  # noqa: E402


@event.listens_for(_Session, "before_flush")
def _alerts_to_notifications(session: _Session, _ctx, _instances) -> None:
    from app.models import Alert
    new_alerts = [o for o in session.new if isinstance(o, Alert) and not getattr(o, "_notified", False)]
    if not new_alerts:
        return
    with session.no_autoflush:
        for a in new_alerts:
            a._notified = True
            from_alert(session, a)
