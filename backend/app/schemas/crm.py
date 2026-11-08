from datetime import datetime

from pydantic import BaseModel

from app.schemas.common import ORMModel


class CustomerIn(BaseModel):
    name: str
    email: str | None = None
    phone: str | None = None
    address: str | None = None
    customer_type: str = "business"
    credit_limit: float = 0
    notes: str | None = None
    price_list_id: int | None = None
    assigned_user_id: int | None = None
    visit_days: str | None = None
    branch_id: int | None = None


class CustomerUpdate(BaseModel):
    name: str | None = None
    email: str | None = None
    phone: str | None = None
    address: str | None = None
    customer_type: str | None = None
    credit_limit: float | None = None
    notes: str | None = None
    price_list_id: int | None = None
    assigned_user_id: int | None = None
    visit_days: str | None = None
    branch_id: int | None = None


class CustomerOut(ORMModel):
    id: int
    name: str
    email: str | None = None
    phone: str | None = None
    address: str | None = None
    customer_type: str
    credit_limit: float
    score: float
    notes: str | None = None
    created_at: datetime
    price_list_id: int | None = None
    assigned_user_id: int | None = None
    visit_days: str | None = None
    branch_id: int | None = None


class CustomerProfile(CustomerOut):
    total_revenue: float
    open_balance: float
    orders_count: int
    last_purchase: datetime | None = None
    interactions: list["InteractionOut"]


class InteractionIn(BaseModel):
    kind: str
    summary: str
    occurred_at: datetime | None = None


class InteractionOut(ORMModel):
    id: int
    kind: str
    summary: str
    occurred_at: datetime
