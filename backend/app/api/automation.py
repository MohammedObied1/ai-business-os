from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import get_current_user, require_permission
from app.models import Alert, AutomationRule, Task, User
from app.schemas.automation import AlertOut, RuleIn, RuleOut, TaskIn, TaskOut
from app.services.automation import ACTIONS, CONDITIONS, ensure_default_rules, run_company, sync_event_rule


def _validate(payload: RuleIn) -> None:
    if payload.condition_type not in CONDITIONS:
        raise HTTPException(400, f"Unknown condition {payload.condition_type}")
    for a in payload.actions or []:
        if a.get("type") not in ACTIONS:
            raise HTTPException(400, f"Unknown action {a.get('type')}")
        if a.get("type") == "require_approval" and "event" not in CONDITIONS[payload.condition_type]:
            raise HTTPException(400, "Require approval only works with expense / discount rules")
        if a.get("type") != "require_approval" and "event" in CONDITIONS[payload.condition_type]:
            raise HTTPException(400, "Expense / discount rules can only require approval")

router = APIRouter(tags=["alerts & automation"])


@router.get("/alerts", response_model=list[AlertOut])
def list_alerts(unresolved_only: bool = True, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    stmt = select(Alert).where(Alert.company_id == user.company_id)
    if unresolved_only:
        stmt = stmt.where(Alert.is_resolved.is_(False))
    return db.scalars(stmt.order_by(Alert.id.desc()).limit(200)).all()


@router.post("/alerts/{alert_id}/resolve", response_model=AlertOut)
def resolve_alert(alert_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    a = db.get(Alert, alert_id)
    if not a or a.company_id != user.company_id:
        raise HTTPException(404, "Alert not found")
    a.is_resolved = a.is_read = True
    db.commit()
    db.refresh(a)
    return a


@router.get("/automation/rules", response_model=list[RuleOut])
def rules(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    ensure_default_rules(db, user.company_id)
    return db.scalars(select(AutomationRule).where(AutomationRule.company_id == user.company_id)).all()


@router.post("/automation/rules", response_model=RuleOut, status_code=201)
def create_rule(payload: RuleIn, user: User = Depends(require_permission("automation:write")), db: Session = Depends(get_db)):
    _validate(payload)
    r = AutomationRule(company_id=user.company_id, **payload.model_dump())
    db.add(r)
    db.flush()
    sync_event_rule(db, user.company_id, r)
    db.commit()
    db.refresh(r)
    return r


@router.patch("/automation/rules/{rule_id}", response_model=RuleOut)
def update_rule(rule_id: int, payload: RuleIn, user: User = Depends(require_permission("automation:write")), db: Session = Depends(get_db)):
    r = db.get(AutomationRule, rule_id)
    if not r or r.company_id != user.company_id:
        raise HTTPException(404, "Rule not found")
    _validate(payload)
    for k, v in payload.model_dump().items():
        setattr(r, k, v)
    sync_event_rule(db, user.company_id, r)
    db.commit()
    db.refresh(r)
    return r


@router.get("/automation/catalog")
def catalog(user: User = Depends(get_current_user)):
    """Conditions (with their default parameters) and actions for the rule builder."""
    return {"conditions": [{"type": k, **v} for k, v in CONDITIONS.items()], "actions": ACTIONS}


@router.get("/automation/logs")
def logs(rule_id: int | None = None, limit: int = 100, user: User = Depends(require_permission("automation:write")), db: Session = Depends(get_db)):
    from app.models import AutomationLog
    stmt = select(AutomationLog).where(AutomationLog.company_id == user.company_id)
    if rule_id:
        stmt = stmt.where(AutomationLog.rule_id == rule_id)
    return [{"id": x.id, "rule_id": x.rule_id, "match_key": x.match_key, "action": x.action, "detail": x.detail, "created_at": x.created_at}
            for x in db.scalars(stmt.order_by(AutomationLog.id.desc()).limit(min(limit, 500))).all()]


@router.post("/automation/run")
def run_now(user: User = Depends(require_permission("automation:write")), db: Session = Depends(get_db)):
    return {"created": run_company(db, user.company_id)}


@router.get("/tasks", response_model=list[TaskOut])
def tasks(status: str | None = "open", user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    stmt = select(Task).where(Task.company_id == user.company_id)
    if status:
        stmt = stmt.where(Task.status == status)
    return db.scalars(stmt.order_by(Task.id.desc()).limit(200)).all()


@router.post("/tasks", response_model=TaskOut, status_code=201)
def create_task(payload: TaskIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    t = Task(company_id=user.company_id, created_by=user.full_name, **payload.model_dump())
    db.add(t)
    db.flush()
    if t.assigned_to_id and t.assigned_to_id != user.id:
        from app.services import notify
        notify.send(db, user.company_id, "task", f"New task: {t.title}", t.description or "", link="/alerts", user_id=t.assigned_to_id, dedupe=f"task:{t.id}")
    db.commit()
    db.refresh(t)
    return t


@router.post("/tasks/{task_id}/status", response_model=TaskOut)
def task_status(task_id: int, status: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    t = db.get(Task, task_id)
    if not t or t.company_id != user.company_id:
        raise HTTPException(404, "Task not found")
    t.status = status
    db.commit()
    db.refresh(t)
    return t
