from datetime import datetime

from pydantic import BaseModel

from app.schemas.common import ORMModel


class RuleIn(BaseModel):
    name: str
    condition_type: str
    params: dict = {}
    action_type: str = "create_alert"
    severity: str = "warning"
    requires_approval: bool = True
    is_active: bool = True
    actions: list[dict] | None = None


class RuleOut(ORMModel):
    id: int
    name: str
    condition_type: str
    params: dict
    action_type: str
    severity: str
    requires_approval: bool
    is_active: bool
    last_run_at: datetime | None = None
    actions: list[dict] | None = None


class AlertOut(ORMModel):
    id: int
    severity: str
    category: str
    title: str
    message: str | None = None
    recommended_action: str | None = None
    is_read: bool
    is_resolved: bool
    created_at: datetime


class TaskIn(BaseModel):
    title: str
    description: str | None = None
    assigned_to_id: int | None = None
    related_customer_id: int | None = None
    due_date: datetime | None = None


class TaskOut(ORMModel):
    id: int
    title: str
    description: str | None = None
    assigned_to_id: int | None = None
    related_customer_id: int | None = None
    status: str
    due_date: datetime | None = None
    created_by: str
    created_at: datetime
