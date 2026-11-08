"""Approval Center: rules (Settings → Approval rules) and requests (Management → Approval center)."""
from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import get_current_user, has_permission, require_permission
from app.core.pagination import page
from app.models import User
from app.models.control import ApprovalRequest
from app.services import approvals

router = APIRouter(tags=["approval center"])


class RuleIn(BaseModel):
    kind: str
    enabled: bool
    threshold: float = 0


class DecisionIn(BaseModel):
    reason: str | None = None


def _out(r: ApprovalRequest) -> dict:
    return {c: getattr(r, c) for c in ("id", "kind", "entity", "entity_id", "label", "requested_value", "threshold", "reason", "status",
                                       "requested_by_id", "requested_by", "approver", "rejection_reason", "created_at", "decided_at")}


@router.get("/approval-rules")
def get_rules(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return approvals.all_rules(db, user.company_id)


@router.put("/approval-rules")
def put_rules(rows: list[RuleIn], user: User = Depends(require_permission("approvals.rules")), db: Session = Depends(get_db)):
    approvals.save_rules(db, user.company_id, [r.model_dump() for r in rows])
    db.commit()
    return approvals.all_rules(db, user.company_id)


@router.get("/approval-requests")
def list_requests(response: Response, status: str | None = "PENDING", kind: str | None = None, mine: bool = False, offset: int = 0,
                  limit: int = Query(50, le=500), user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Approvers see every request; everybody else only their own."""
    stmt = select(ApprovalRequest).where(ApprovalRequest.company_id == user.company_id)
    if mine or not has_permission(user, "approvals.approve"):
        stmt = stmt.where(ApprovalRequest.requested_by_id == user.id)
    if status:
        stmt = stmt.where(ApprovalRequest.status.in_(status.upper().split(",")))
    if kind:
        stmt = stmt.where(ApprovalRequest.kind == kind)
    return [_out(r) for r in page(db, stmt.order_by(ApprovalRequest.id.desc()), response, offset, limit)]


@router.get("/approval-requests/summary")
def summary(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if not has_permission(user, "approvals.approve"):
        return {"pending": 0, "by_kind": {}}
    rows = db.execute(select(ApprovalRequest.kind, func.count(ApprovalRequest.id)).where(
        ApprovalRequest.company_id == user.company_id, ApprovalRequest.status == "PENDING").group_by(ApprovalRequest.kind)).all()
    return {"pending": sum(n for _, n in rows), "by_kind": dict(rows)}


def _get(db: Session, user: User, rid: int) -> ApprovalRequest:
    r = db.get(ApprovalRequest, rid)
    if not r or r.company_id != user.company_id:
        raise HTTPException(404, "Request not found")
    return r


@router.post("/approval-requests/{rid}/approve")
def approve(rid: int, payload: DecisionIn | None = None, user: User = Depends(require_permission("approvals.approve")), db: Session = Depends(get_db)):
    r = approvals.decide(db, user, _get(db, user, rid), True, payload.reason if payload else None)
    db.commit()
    return _out(r)


@router.post("/approval-requests/{rid}/reject")
def reject(rid: int, payload: DecisionIn, user: User = Depends(require_permission("approvals.approve")), db: Session = Depends(get_db)):
    r = approvals.decide(db, user, _get(db, user, rid), False, payload.reason)
    db.commit()
    return _out(r)


@router.post("/approval-requests/{rid}/cancel")
def cancel(rid: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    r = approvals.cancel(db, user, _get(db, user, rid))
    db.commit()
    return _out(r)
