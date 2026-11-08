"""SaaS billing: plans, add-ons, coupons and each company's subscription (platform admin) + a company's own view."""
from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import get_current_user, get_platform_admin
from app.models import Company, Plan, PlatformAdmin, PlatformInvoice, User
from app.models.saas import AddOn, Coupon, PlatformPayment, SubscriptionItem
from app.services import saas

router = APIRouter(tags=["saas billing"])


class PlanFull(BaseModel):
    name: str
    price_monthly: float = 0
    price_yearly: float = 0
    max_users: int = 0
    max_branches: int = 0
    max_warehouses: int = 0
    max_storage_mb: int = 0
    max_ai_requests: int = 0
    max_api_requests: int = 0
    trial_days: int = 0
    grace_days: int = 7
    features: list[str] = []
    description: str | None = None
    is_active: bool = True


class AddOnIn(BaseModel):
    code: str
    name: str
    price_monthly: float = 0
    price_yearly: float = 0
    grants: dict = {}
    features: list[str] = []
    is_active: bool = True


class CouponIn(BaseModel):
    code: str
    percent_off: float = 0
    amount_off: float = 0
    duration: str = "once"
    cycles: int | None = None
    max_redemptions: int | None = None
    valid_until: date | None = None
    is_active: bool = True


class SubscriptionUpdate(BaseModel):
    plan_id: int | None = None
    interval: str | None = None
    immediately: bool | None = None  # None = upgrade now / downgrade at period end
    coupon: str | None = None
    addons: list[dict] | None = None  # [{"addon_id", "quantity"}]
    cancel_at_period_end: bool | None = None
    grace_days: int | None = None
    status: str | None = None  # manual override: active / suspended / cancelled
    trial_days: int | None = None  # start / extend a trial from today
    notes: str | None = None


class PaymentIn(BaseModel):
    amount: float
    method: str = "bank"
    reference: str | None = None


def _plan(p: Plan) -> dict:
    return {c: getattr(p, c) for c in ("id", "name", "price_monthly", "price_yearly", "max_users", "max_branches", "max_warehouses", "max_storage_mb",
                                       "max_ai_requests", "max_api_requests", "trial_days", "grace_days", "description", "is_active")} | {"features": p.features or []}


def _validate_features(features: list[str]) -> None:
    bad = [f for f in features if f not in saas.FEATURES]
    if bad:
        raise HTTPException(400, f"Unknown feature(s): {', '.join(bad)}")


# ---------------------------------------------------------------- plans (full editor; the older /platform/plans stays for old clients)
@router.get("/platform/billing/catalog")
def catalog(admin: PlatformAdmin = Depends(get_platform_admin), db: Session = Depends(get_db)):
    return {"features": saas.FEATURES, "limits": saas.LIMIT_KEYS,
            "plans": [_plan(p) for p in db.scalars(select(Plan).order_by(Plan.price_monthly)).all()],
            "addons": [{c: getattr(a, c) for c in ("id", "code", "name", "price_monthly", "price_yearly", "grants", "features", "is_active")}
                       for a in db.scalars(select(AddOn).order_by(AddOn.id)).all()],
            "coupons": [{c: getattr(x, c) for c in ("id", "code", "percent_off", "amount_off", "duration", "cycles", "max_redemptions", "redeemed",
                                                    "valid_until", "is_active")} for x in db.scalars(select(Coupon).order_by(Coupon.id.desc())).all()]}


@router.post("/platform/billing/plans", status_code=201)
def create_plan(payload: PlanFull, admin: PlatformAdmin = Depends(get_platform_admin), db: Session = Depends(get_db)):
    _validate_features(payload.features)
    p = Plan(**payload.model_dump())
    db.add(p)
    db.commit()
    return _plan(p)


@router.put("/platform/billing/plans/{plan_id}")
def update_plan(plan_id: int, payload: PlanFull, admin: PlatformAdmin = Depends(get_platform_admin), db: Session = Depends(get_db)):
    _validate_features(payload.features)
    p = db.get(Plan, plan_id)
    if not p:
        raise HTTPException(404, "Plan not found")
    for k, v in payload.model_dump().items():
        setattr(p, k, v)
    db.commit()
    return _plan(p)


@router.post("/platform/billing/addons", status_code=201)
def create_addon(payload: AddOnIn, admin: PlatformAdmin = Depends(get_platform_admin), db: Session = Depends(get_db)):
    if any(k not in saas.LIMIT_KEYS for k in payload.grants):
        raise HTTPException(400, "Add-ons can only raise these limits: " + ", ".join(saas.LIMIT_KEYS))
    _validate_features(payload.features)
    if db.scalar(select(AddOn.id).where(AddOn.code == payload.code)):
        raise HTTPException(400, "This code is already used")
    a = AddOn(**payload.model_dump())
    db.add(a)
    db.commit()
    return {"id": a.id}


@router.put("/platform/billing/addons/{addon_id}")
def update_addon(addon_id: int, payload: AddOnIn, admin: PlatformAdmin = Depends(get_platform_admin), db: Session = Depends(get_db)):
    a = db.get(AddOn, addon_id)
    if not a:
        raise HTTPException(404, "Add-on not found")
    for k, v in payload.model_dump().items():
        setattr(a, k, v)
    db.commit()
    return {"id": a.id}


@router.post("/platform/billing/coupons", status_code=201)
def create_coupon(payload: CouponIn, admin: PlatformAdmin = Depends(get_platform_admin), db: Session = Depends(get_db)):
    if payload.duration not in ("once", "repeating", "forever"):
        raise HTTPException(400, "Duration must be once, repeating or forever")
    if not (0 <= payload.percent_off <= 100) or payload.amount_off < 0:
        raise HTTPException(400, "Discount out of range")
    if db.scalar(select(Coupon.id).where(Coupon.code == payload.code)):
        raise HTTPException(400, "This code is already used")
    c = Coupon(**payload.model_dump())
    db.add(c)
    db.commit()
    return {"id": c.id}


@router.put("/platform/billing/coupons/{coupon_id}")
def update_coupon(coupon_id: int, payload: CouponIn, admin: PlatformAdmin = Depends(get_platform_admin), db: Session = Depends(get_db)):
    c = db.get(Coupon, coupon_id)
    if not c:
        raise HTTPException(404, "Coupon not found")
    for k, v in payload.model_dump().items():
        setattr(c, k, v)
    db.commit()
    return {"id": c.id}


# ---------------------------------------------------------------- a company's subscription
def _company(db: Session, cid: int) -> Company:
    c = db.get(Company, cid)
    if not c:
        raise HTTPException(404, "Company not found")
    return c


def _sub_out(db: Session, c: Company) -> dict:
    sub = saas.subscription(db, c)
    out = saas.status_for(db, c.id)
    invoices = db.scalars(select(PlatformInvoice).where(PlatformInvoice.company_id == c.id).order_by(PlatformInvoice.id.desc()).limit(24)).all()
    payments = db.scalars(select(PlatformPayment).where(PlatformPayment.company_id == c.id).order_by(PlatformPayment.id.desc()).limit(24)).all()
    return {**out, "plan_id": sub.plan_id, "grace_days": sub.grace_days, "notes": sub.notes, "coupon_id": sub.coupon_id,
            "items": [{"addon_id": it.addon_id, "quantity": it.quantity} for it in sub.items],
            "invoices": [{"id": i.id, "number": i.number, "period_start": i.period_start, "period_end": i.period_end, "amount": i.amount,
                          "paid_amount": i.paid_amount, "status": i.status, "due_date": i.due_date, "lines": i.lines} for i in invoices],
            "payments": [{"id": p.id, "invoice_id": p.invoice_id, "amount": p.amount, "method": p.method, "reference": p.reference, "paid_at": p.paid_at,
                          "recorded_by": p.recorded_by} for p in payments]}


@router.get("/platform/companies/{cid}/subscription")
def get_subscription(cid: int, admin: PlatformAdmin = Depends(get_platform_admin), db: Session = Depends(get_db)):
    out = _sub_out(db, _company(db, cid))
    db.commit()
    return out


@router.put("/platform/companies/{cid}/subscription")
def update_subscription(cid: int, payload: SubscriptionUpdate, admin: PlatformAdmin = Depends(get_platform_admin), db: Session = Depends(get_db)):
    from datetime import timedelta
    c = _company(db, cid)
    sub = saas.subscription(db, c)
    result = {}
    if payload.plan_id and (payload.plan_id != sub.plan_id or (payload.interval and payload.interval != sub.interval)):
        plan = db.get(Plan, payload.plan_id)
        if not plan:
            raise HTTPException(404, "Plan not found")
        result = saas.change_plan(db, sub, plan, payload.interval, payload.immediately)
    if payload.coupon:
        saas.apply_coupon(db, sub, payload.coupon)
    if payload.addons is not None:
        for it in list(sub.items):
            db.delete(it)
        db.flush()
        for row in payload.addons:
            a = db.get(AddOn, int(row.get("addon_id", 0)))
            if not a:
                raise HTTPException(404, "Add-on not found")
            db.add(SubscriptionItem(subscription_id=sub.id, addon_id=a.id, quantity=max(int(row.get("quantity", 1)), 1)))
        db.flush()
        db.refresh(sub)
    if payload.cancel_at_period_end is not None:
        sub.cancel_at_period_end = payload.cancel_at_period_end
    if payload.grace_days is not None:
        sub.grace_days = max(payload.grace_days, 0)
    if payload.trial_days:
        sub.status, sub.trial_ends_at = "trialing", date.today() + timedelta(days=payload.trial_days)
        sub.current_period_start, sub.current_period_end = date.today(), sub.trial_ends_at
    if payload.status:
        if payload.status not in ("active", "suspended", "cancelled"):
            raise HTTPException(400, "Status must be active, suspended or cancelled")
        sub.status = payload.status
        if payload.status == "active" and (not sub.current_period_end or sub.current_period_end < date.today()):
            sub.current_period_start, sub.current_period_end = date.today(), saas.add_period(date.today(), sub.interval)
    if payload.notes is not None:
        sub.notes = payload.notes
    saas.sync_company(db, sub)
    db.commit()
    return {**_sub_out(db, c), "change": result}


@router.post("/platform/companies/{cid}/subscription/invoice", status_code=201)
def invoice_now(cid: int, admin: PlatformAdmin = Depends(get_platform_admin), db: Session = Depends(get_db)):
    """Bill the next period now (e.g. a company that wants to pay in advance)."""
    c = _company(db, cid)
    sub = saas.subscription(db, c)
    start = max(sub.current_period_end or date.today(), date.today())
    inv = saas.issue_invoice(db, sub, start, saas.add_period(start, sub.interval), saas.quote(db, sub))
    db.commit()
    return {"number": inv.number, "amount": inv.amount}


@router.post("/platform/billing/{invoice_id}/payments", status_code=201)
def record_payment(invoice_id: int, payload: PaymentIn, admin: PlatformAdmin = Depends(get_platform_admin), db: Session = Depends(get_db)):
    """Partial or full payment of a subscription invoice (fully paid → the subscription moves to the paid period)."""
    inv = db.get(PlatformInvoice, invoice_id)
    if not inv:
        raise HTTPException(404, "Invoice not found")
    p = saas.pay(db, inv, payload.amount, payload.method, payload.reference, admin.full_name)
    db.commit()
    return {"payment_id": p.id, "status": inv.status, "paid_amount": inv.paid_amount}


# ---------------------------------------------------------------- the company's own view
@router.get("/subscription")
def my_subscription(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Plan, status, limits vs usage and bills — for the company itself (no platform-private notes)."""
    from app.core.deps import has_permission
    out = saas.status_for(db, user.company_id)
    if has_permission(user, "settings.manage"):
        out["invoices"] = [{"number": i.number, "period_start": i.period_start, "period_end": i.period_end, "amount": i.amount, "paid_amount": i.paid_amount,
                            "status": i.status, "due_date": i.due_date}
                           for i in db.scalars(select(PlatformInvoice).where(PlatformInvoice.company_id == user.company_id)
                                               .order_by(PlatformInvoice.id.desc()).limit(24)).all()]
    db.commit()
    return out
