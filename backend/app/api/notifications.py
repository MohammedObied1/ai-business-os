"""Notification center: my inbox, my channel preferences, and (managers) the company's routing rules."""
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import get_current_user, require_permission
from app.core.pagination import page
from app.models import User
from app.models.comms import Notification, NotificationPreference, NotificationRule
from app.services import notify

router = APIRouter(prefix="/notifications", tags=["notifications"])


class PrefIn(BaseModel):
    kind: str
    in_app: bool = True
    email: bool = False
    whatsapp: bool = False
    push: bool = True


class RuleIn(BaseModel):
    kind: str
    enabled: bool = True
    permission: str | None = None
    email: bool = False
    whatsapp: bool = False


def _out(n: Notification) -> dict:
    return {"id": n.id, "kind": n.kind, "severity": n.severity, "title": n.title, "message": n.message, "link": n.link, "channels": n.channels,
            "read": n.read_at is not None, "created_at": n.created_at}


@router.get("")
def my_notifications(response: Response, unread: bool = False, offset: int = 0, limit: int = Query(30, le=200),
                     user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    stmt = select(Notification).where(Notification.company_id == user.company_id, Notification.user_id == user.id)
    if unread:
        stmt = stmt.where(Notification.read_at.is_(None))
    return [_out(n) for n in page(db, stmt.order_by(Notification.id.desc()), response, offset, limit)]


@router.get("/unread-count")
def unread_count(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    n = db.scalar(select(func.count(Notification.id)).where(Notification.user_id == user.id, Notification.read_at.is_(None))) or 0
    latest = db.scalar(select(Notification).where(Notification.user_id == user.id, Notification.read_at.is_(None)).order_by(Notification.id.desc()))
    return {"count": n, "latest": _out(latest) if latest else None}


@router.post("/{nid}/read", status_code=204)
def mark_read(nid: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    n = db.get(Notification, nid)
    if not n or n.user_id != user.id:
        raise HTTPException(404, "Notification not found")
    n.read_at = n.read_at or datetime.utcnow()
    db.commit()


@router.post("/read-all", status_code=204)
def mark_all_read(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    db.execute(update(Notification).where(Notification.user_id == user.id, Notification.read_at.is_(None)).values(read_at=datetime.utcnow()))
    db.commit()


@router.get("/preferences")
def my_preferences(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    mine = {p.kind: p for p in db.scalars(select(NotificationPreference).where(NotificationPreference.user_id == user.id)).all()}
    out = []
    for kind, (_perm, label) in notify.KINDS.items():
        r = notify.rule(db, user.company_id, kind)
        p = mine.get(kind)
        out.append({"kind": kind, "label": label, "in_app": p.in_app if p else True, "email": p.email if p else r["email"],
                    "whatsapp": p.whatsapp if p else r["whatsapp"], "push": p.push if p else True})
    return out


@router.put("/preferences")
def save_preferences(rows: list[PrefIn], user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    for row in rows:
        if row.kind not in notify.KINDS:
            raise HTTPException(400, f"Unknown notification kind {row.kind}")
        p = db.scalar(select(NotificationPreference).where(NotificationPreference.user_id == user.id, NotificationPreference.kind == row.kind))
        if not p:
            p = NotificationPreference(company_id=user.company_id, user_id=user.id, kind=row.kind)
            db.add(p)
        p.in_app, p.email, p.whatsapp, p.push = row.in_app, row.email, row.whatsapp, row.push
    db.commit()
    return my_preferences(user, db)


@router.get("/rules")
def company_rules(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return [{**notify.rule(db, user.company_id, k), "label": label, "default_permission": perm} for k, (perm, label) in notify.KINDS.items()]


@router.put("/rules")
def save_rules(rows: list[RuleIn], user: User = Depends(require_permission("settings.manage")), db: Session = Depends(get_db)):
    from app.core.permissions import ALL_GRANULAR, LEGACY
    for row in rows:
        if row.kind not in notify.KINDS:
            raise HTTPException(400, f"Unknown notification kind {row.kind}")
        if row.permission and row.permission not in ALL_GRANULAR and row.permission not in LEGACY:
            raise HTTPException(400, f"Unknown permission {row.permission}")
        r = db.scalar(select(NotificationRule).where(NotificationRule.company_id == user.company_id, NotificationRule.kind == row.kind))
        if not r:
            r = NotificationRule(company_id=user.company_id, kind=row.kind)
            db.add(r)
        r.enabled, r.permission, r.email, r.whatsapp = row.enabled, row.permission, row.email, row.whatsapp
    db.commit()
    return company_rules(user, db)
