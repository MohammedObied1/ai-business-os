"""SaaS billing of the platform: subscriptions, renewal invoices, payments, grace period, suspension, limits and usage.

`Company.subscription_ends_at` stays the single switch the rest of the app checks (402 after that date). It is kept at
"end of the paid period + grace days", so an unpaid company keeps working through its grace period and is then locked.
Prices always come from the plan / add-ons / coupons in the database, never from code.
"""
from datetime import date, timedelta

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Company, Plan, PlatformInvoice
from app.models.saas import AddOn, Coupon, PlatformPayment, Subscription, SubscriptionItem, UsageRecord

LIMIT_KEYS = ["max_users", "max_branches", "max_warehouses", "max_storage_mb", "max_ai_requests", "max_api_requests"]
FEATURES = ["pos", "ai", "api", "online_store", "manufacturing", "deliveries", "field_sales", "multi_currency", "accounting", "hr"]
RENEW_DAYS_BEFORE = 7


def add_period(d: date, interval: str) -> date:
    months = 12 if interval == "yearly" else 1
    y, m = divmod(d.month - 1 + months, 12)
    return date(d.year + y, m + 1, min(d.day, 28))


def subscription(db: Session, company: Company) -> Subscription:
    """The company's subscription (created from its older plan / end date the first time)."""
    sub = db.scalar(select(Subscription).where(Subscription.company_id == company.id))
    if not sub:
        end = company.subscription_ends_at
        sub = Subscription(company_id=company.id, plan_id=company.plan_id, interval="monthly", status="active",
                           current_period_start=(end - timedelta(days=30)) if end else date.today(), current_period_end=end)
        db.add(sub)
        db.flush()
    return sub


def _grace(db: Session, sub: Subscription) -> int:
    if sub.grace_days is not None:
        return sub.grace_days
    plan = db.get(Plan, sub.plan_id) if sub.plan_id else None
    return plan.grace_days if plan and plan.grace_days is not None else 7


def sync_company(db: Session, sub: Subscription) -> None:
    """Mirror the subscription onto the company switches the app already uses."""
    c = db.get(Company, sub.company_id)
    c.plan_id = sub.plan_id
    if sub.status == "cancelled" or sub.status == "suspended":
        c.subscription_ends_at = min(sub.current_period_end or date.today(), date.today() - timedelta(days=1))
    elif sub.current_period_end:
        c.subscription_ends_at = sub.current_period_end + timedelta(days=_grace(db, sub))
    else:
        c.subscription_ends_at = None  # no end date: free / unlimited


def start(db: Session, company: Company, plan: Plan | None, interval: str = "monthly", trial: bool = True) -> Subscription:
    """New company (or new plan from scratch): trial first when the plan has one."""
    sub = subscription(db, company)
    sub.plan_id, sub.interval = (plan.id if plan else None), interval
    today = date.today()
    if plan and trial and plan.trial_days:
        sub.status, sub.trial_ends_at = "trialing", today + timedelta(days=plan.trial_days)
        sub.current_period_start, sub.current_period_end = today, sub.trial_ends_at
    elif plan and _plan_price(plan, interval) > 0:
        sub.status = "past_due"  # first invoice to pay
        sub.current_period_start, sub.current_period_end = today, today
    else:
        sub.status, sub.current_period_start, sub.current_period_end = "active", today, None
    sync_company(db, sub)
    return sub


def _plan_price(plan: Plan, interval: str) -> float:
    if interval == "yearly":
        return plan.price_yearly or round((plan.price_monthly or 0) * 12, 2)
    return plan.price_monthly or 0


def quote(db: Session, sub: Subscription, plan: Plan | None = None, interval: str | None = None) -> dict:
    """What the next period costs: plan + add-ons − coupon."""
    plan = plan or (db.get(Plan, sub.plan_id) if sub.plan_id else None)
    interval = interval or sub.interval
    lines = []
    if plan:
        lines.append({"label": f"{plan.name} ({interval})", "amount": _plan_price(plan, interval)})
    for it in sub.items:
        a = db.get(AddOn, it.addon_id)
        if a and a.is_active:
            unit = a.price_yearly if interval == "yearly" and a.price_yearly else (a.price_monthly * (12 if interval == "yearly" else 1))
            lines.append({"label": f"{a.name} × {it.quantity}", "amount": round(unit * it.quantity, 2)})
    subtotal = round(sum(ln["amount"] for ln in lines), 2)
    discount = 0.0
    coupon = db.get(Coupon, sub.coupon_id) if sub.coupon_id else None
    if coupon and coupon.is_active and (sub.coupon_cycles_left is None or sub.coupon_cycles_left > 0):
        discount = round(min(subtotal, subtotal * (coupon.percent_off or 0) / 100 + (coupon.amount_off or 0)), 2)
        if discount:
            lines.append({"label": f"Coupon {coupon.code}", "amount": -discount})
    return {"lines": lines, "subtotal": subtotal, "discount": discount, "total": round(subtotal - discount, 2), "interval": interval}


def _number(db: Session) -> str:
    n = (db.scalar(select(func.count(PlatformInvoice.id))) or 0) + 1
    return f"SUB-{date.today().year}-{n:05d}"


def issue_invoice(db: Session, sub: Subscription, start_d: date, end_d: date, amount_quote: dict, note: str | None = None) -> PlatformInvoice:
    from app.services import email as mail
    from app.services.companies import company_owner
    plan = db.get(Plan, sub.plan_id) if sub.plan_id else None
    inv = PlatformInvoice(company_id=sub.company_id, number=_number(db), period=start_d.strftime("%Y-%m"), plan_name=plan.name if plan else None,
                          amount=amount_quote["total"], subtotal=amount_quote["subtotal"], discount=amount_quote["discount"], lines=amount_quote["lines"],
                          # due when the period starts (or in 3 days if that's already past)
                          due_date=start_d if start_d >= date.today() else date.today() + timedelta(days=3),
                          subscription_id=sub.id, interval=amount_quote["interval"], period_start=start_d, period_end=end_d, note=note)
    db.add(inv)
    db.flush()
    owner = company_owner(db, sub.company_id)
    if owner:
        body = (f"<p>مرحبا {owner.full_name},</p><p>فاتورة الاشتراك من {start_d} لغاية {end_d} بقيمة <b>{inv.amount:,.2f}</b>. "
                f"آخر موعد للدفع {inv.due_date}.</p>")
        mail.queue(db, owner.email, f"فاتورة الاشتراك {inv.number}", mail.layout("فاتورة اشتراك", body), "billing", sub.company_id)
    return inv


def _open_invoice(db: Session, sub: Subscription) -> PlatformInvoice | None:
    return db.scalar(select(PlatformInvoice).where(PlatformInvoice.subscription_id == sub.id, PlatformInvoice.status == "unpaid")
                     .order_by(PlatformInvoice.id.desc()))


def pay(db: Session, inv: PlatformInvoice, amount: float, method: str = "bank", reference: str | None = None, by: str | None = None) -> PlatformPayment:
    """Record money received. When the invoice is fully paid the subscription moves to the invoiced period."""
    if inv.status != "unpaid":
        raise HTTPException(400, "This invoice is not open")
    if amount <= 0:
        raise HTTPException(400, "Amount must be greater than zero")
    p = PlatformPayment(company_id=inv.company_id, invoice_id=inv.id, amount=round(amount, 2), method=method, reference=reference, recorded_by=by)
    db.add(p)
    inv.paid_amount = round((inv.paid_amount or 0) + amount, 2)
    if inv.paid_amount + 0.009 >= inv.amount:
        inv.status, inv.paid_at = "paid", date.today()
        sub = db.get(Subscription, inv.subscription_id) if inv.subscription_id else None
        if sub:
            _apply_paid_period(db, sub, inv)
    return p


def _apply_paid_period(db: Session, sub: Subscription, inv: PlatformInvoice) -> None:
    today = date.today()
    start_d = inv.period_start or today
    end_d = inv.period_end or add_period(start_d, inv.interval or sub.interval)
    if sub.current_period_end and sub.current_period_end > end_d:
        return  # an older invoice: nothing to extend
    if sub.status in ("suspended", "past_due", "grace") and (sub.current_period_end or today) < today:
        # paid late: the paid length starts today, not in the past
        length = (end_d - start_d)
        start_d, end_d = today, today + length
    sub.current_period_start, sub.current_period_end, sub.status = start_d, end_d, "active"
    sub.trial_ends_at = None
    if sub.coupon_id and sub.coupon_cycles_left is not None:
        sub.coupon_cycles_left = max(sub.coupon_cycles_left - 1, 0)
    sync_company(db, sub)


def renew_if_due(db: Session, sub: Subscription) -> PlatformInvoice | None:
    """Issue the next period's invoice ahead of time (once), applying a scheduled downgrade first."""
    today = date.today()
    if sub.status == "cancelled" or not sub.plan_id or sub.current_period_end is None:
        return None
    if sub.current_period_end - timedelta(days=RENEW_DAYS_BEFORE) > today or _open_invoice(db, sub):
        return None
    if sub.cancel_at_period_end:
        return None
    if sub.pending_plan_id:
        sub.plan_id, sub.pending_plan_id = sub.pending_plan_id, None
        sub.interval, sub.pending_interval = sub.pending_interval or sub.interval, None
    q = quote(db, sub)
    start_d = max(sub.current_period_end, today) if sub.status in ("suspended",) else sub.current_period_end
    end_d = add_period(start_d, sub.interval)
    if q["total"] <= 0:  # free plan or fully discounted: renew straight away
        sub.current_period_start, sub.current_period_end, sub.status = start_d, end_d, "active"
        sync_company(db, sub)
        return None
    return issue_invoice(db, sub, start_d, end_d, q)


def enforce(db: Session, sub: Subscription) -> None:
    """Move the subscription through its states after the paid period ends."""
    today = date.today()
    end = sub.current_period_end
    if end is None or end >= today or sub.status == "suspended":
        return
    if sub.cancel_at_period_end or sub.status == "cancelled":
        sub.status = "cancelled"
    elif today > end + timedelta(days=_grace(db, sub)):
        sub.status = "suspended"  # grace is over and nothing was paid
    elif sub.status == "trialing":
        sub.status = "past_due"  # trial over: the first paid period must be paid
        if not _open_invoice(db, sub) and quote(db, sub)["total"] > 0:
            issue_invoice(db, sub, today, add_period(today, sub.interval), quote(db, sub), "First paid period after the trial")
    elif sub.status != "past_due":
        sub.status = "grace"
    sync_company(db, sub)


def change_plan(db: Session, sub: Subscription, plan: Plan, interval: str | None = None, immediately: bool | None = None) -> dict:
    """Upgrade = now, with a prorated invoice for the rest of the period. Downgrade = from the next period."""
    interval = interval or sub.interval
    if interval not in ("monthly", "yearly"):
        raise HTTPException(400, "Interval must be monthly or yearly")
    old = db.get(Plan, sub.plan_id) if sub.plan_id else None
    old_price, new_price = (_plan_price(old, sub.interval) if old else 0), _plan_price(plan, interval)
    upgrade = new_price >= old_price if immediately is None else immediately
    today = date.today()
    if not upgrade and sub.current_period_end and sub.current_period_end > today:
        sub.pending_plan_id, sub.pending_interval = plan.id, interval
        return {"applied": "at_period_end", "effective": sub.current_period_end}
    invoice = None
    if sub.status == "active" and sub.current_period_end and sub.current_period_end > today and sub.current_period_start:
        total_days = max((sub.current_period_end - sub.current_period_start).days, 1)
        left = (sub.current_period_end - today).days
        credit = old_price * left / total_days
        charge = new_price * left / total_days if interval == sub.interval else new_price
        diff = round(charge - credit, 2)
        if diff > 0:
            q = {"lines": [{"label": f"Upgrade to {plan.name} ({left} days)", "amount": diff}], "subtotal": diff, "discount": 0, "total": diff, "interval": interval}
            invoice = issue_invoice(db, sub, today, sub.current_period_end, q, "Prorated upgrade")
    sub.plan_id, sub.interval, sub.pending_plan_id, sub.pending_interval = plan.id, interval, None, None
    if sub.status in ("trialing",) and plan.trial_days == 0:
        sub.status = "active"
    sync_company(db, sub)
    return {"applied": "now", "invoice": invoice.number if invoice else None}


def apply_coupon(db: Session, sub: Subscription, code: str) -> Coupon:
    c = db.scalar(select(Coupon).where(func.lower(Coupon.code) == code.strip().lower(), Coupon.is_active.is_(True)))
    if not c or (c.valid_until and c.valid_until < date.today()) or (c.max_redemptions and c.redeemed >= c.max_redemptions):
        raise HTTPException(404, "Coupon not valid")
    sub.coupon_id = c.id
    sub.coupon_cycles_left = 1 if c.duration == "once" else (c.cycles if c.duration == "repeating" else None)
    c.redeemed = (c.redeemed or 0) + 1
    return c


def billing_cycle(db: Session) -> dict:
    """Daily: renewal invoices ahead of time, then grace / suspension / cancellation."""
    issued = 0
    for c in db.scalars(select(Company)).all():
        sub = subscription(db, c)
        if renew_if_due(db, sub):
            issued += 1
        enforce(db, sub)
    db.commit()
    return {"invoices": issued}


def billing_job() -> None:
    from app.core.database import SessionLocal
    with SessionLocal() as db:
        billing_cycle(db)


# ---------------------------------------------------------------- limits, features, usage
def limit(db: Session, cid: int, key: str) -> int:
    """Plan limit + what add-ons grant. 0 = unlimited."""
    c = db.get(Company, cid)
    plan = db.get(Plan, c.plan_id) if c and c.plan_id else None
    base = (getattr(plan, key, 0) or 0) if plan else 0
    if not base:
        return 0
    sub = db.scalar(select(Subscription).where(Subscription.company_id == cid))
    extra = 0
    for it in (sub.items if sub else []):
        a = db.get(AddOn, it.addon_id)
        if a and a.is_active:
            extra += int((a.grants or {}).get(key, 0)) * it.quantity
    return base + extra


def has_feature(db: Session, cid: int, feature: str) -> bool:
    c = db.get(Company, cid)
    plan = db.get(Plan, c.plan_id) if c and c.plan_id else None
    if not plan or not plan.features:
        return True  # no plan / no list = everything (older plans)
    if feature in plan.features:
        return True
    sub = db.scalar(select(Subscription).where(Subscription.company_id == cid))
    return any(feature in ((db.get(AddOn, it.addon_id).features or []) if db.get(AddOn, it.addon_id) else []) for it in (sub.items if sub else []))


def require_feature(db: Session, cid: int, feature: str) -> None:
    if not has_feature(db, cid, feature):
        raise HTTPException(402, f"Your plan doesn't include this feature ({feature}). Ask the platform admin to upgrade.")


def usage(db: Session, cid: int, metric: str, period: str | None = None) -> int:
    period = period or date.today().strftime("%Y-%m")
    return db.scalar(select(UsageRecord.quantity).where(UsageRecord.company_id == cid, UsageRecord.metric == metric, UsageRecord.period == period)) or 0


def consume(db: Session, cid: int, metric: str, limit_key: str, qty: int = 1) -> None:
    """Count one use of a metered feature; refuse when the month's limit is reached."""
    cap = limit(db, cid, limit_key)
    used = usage(db, cid, metric)
    if cap and used + qty > cap:
        raise HTTPException(429, f"Monthly limit reached ({cap}). Ask the platform admin for more.")
    period = date.today().strftime("%Y-%m")
    rec = db.scalar(select(UsageRecord).where(UsageRecord.company_id == cid, UsageRecord.metric == metric, UsageRecord.period == period))
    if not rec:
        rec = UsageRecord(company_id=cid, metric=metric, period=period, quantity=0)
        db.add(rec)
    rec.quantity = (rec.quantity or 0) + qty


def storage_mb(db: Session, cid: int) -> float:
    from app.models import Attachment
    return round(float(db.scalar(select(func.coalesce(func.sum(Attachment.size), 0)).where(Attachment.company_id == cid)) or 0) / 1024 / 1024, 2)


def check_storage(db: Session, cid: int, extra_bytes: int) -> None:
    cap = limit(db, cid, "max_storage_mb")
    if cap and storage_mb(db, cid) + extra_bytes / 1024 / 1024 > cap:
        raise HTTPException(413, f"Storage limit reached ({cap} MB). Ask the platform admin for more space.")


def status_for(db: Session, cid: int) -> dict:
    """What the company sees about its own subscription."""
    c = db.get(Company, cid)
    sub = subscription(db, c)
    plan = db.get(Plan, sub.plan_id) if sub.plan_id else None
    from app.models import Branch, User, Warehouse
    count = lambda m: db.scalar(select(func.count(m.id)).where(m.company_id == cid)) or 0  # noqa: E731
    used = {"max_users": db.scalar(select(func.count(User.id)).where(User.company_id == cid, User.is_active.is_(True))) or 0,
            "max_branches": count(Branch), "max_warehouses": count(Warehouse), "max_storage_mb": storage_mb(db, cid),
            "max_ai_requests": usage(db, cid, "ai_requests"), "max_api_requests": usage(db, cid, "api_requests")}
    return {"status": sub.status, "plan": plan.name if plan else None, "interval": sub.interval, "trial_ends_at": sub.trial_ends_at,
            "current_period_end": sub.current_period_end, "access_until": c.subscription_ends_at, "cancel_at_period_end": sub.cancel_at_period_end,
            "pending_plan": db.get(Plan, sub.pending_plan_id).name if sub.pending_plan_id else None,
            "limits": [{"key": k, "limit": limit(db, cid, k), "used": used[k]} for k in LIMIT_KEYS],
            "features": (plan.features or FEATURES) if plan else FEATURES, "next": quote(db, sub) if plan else None}
