from datetime import date

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import get_current_user, has_permission, require_permission
from app.models import User
from app.services import analytics
from app.services.insights import build_command_center

router = APIRouter(tags=["dashboard & reports"])


@router.get("/dashboard")
def dashboard(user: User = Depends(require_permission("reports.view")), db: Session = Depends(get_db)):
    cid = user.company_id
    s, e = analytics.month_bounds(date.today())
    return {
        "kpis": analytics.dashboard_kpis(db, cid),
        "monthly": analytics.monthly_series(db, cid, 12),
        "top_customers": analytics.top_customers(db, cid, s, e, 5),
        "top_products": analytics.top_products(db, cid, s, e, 5, by="revenue"),
        "categories": analytics.category_margins(db, cid, s, e),
        "low_stock": analytics.low_stock_products(db, cid)[:8],
    }


@router.get("/command-center")
def command_center(lang: str = "en", user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    # the home page is open to everyone, but the business numbers only to people allowed to see reports
    if not has_permission(user, "reports.view"):
        return {"health": None, "summary": "", "kpis": None, "signals": [], "limited": True}
    cc = build_command_center(db, user.company_id, lang)
    if not has_permission(user, "reports.view_profit"):
        cc["kpis"] = {k: v for k, v in (cc.get("kpis") or {}).items() if "profit" not in k and "margin" not in k and "cogs" not in k}
    return cc


@router.get("/reports/{report}")
def report(report: str, start: date | None = None, end: date | None = None, user: User = Depends(require_permission("reports.view")), db: Session = Depends(get_db)):
    cid = user.company_id
    if not start or not end:
        start, end = analytics.month_bounds(date.today())
    if report == "sales":
        return {"period": [start, end], "by_customer": analytics.top_customers(db, cid, start, end, 50), "by_product": analytics.top_products(db, cid, start, end, 50, by="revenue"),
                "by_warehouse": analytics.sales_by_warehouse(db, cid, start, end), "by_category": analytics.category_margins(db, cid, start, end)}
    if report == "inventory":
        from app.services.forecasting import forecast_all
        return {"low_stock": analytics.low_stock_products(db, cid), "inventory_value": analytics.inventory_value(db, cid), "forecast": forecast_all(db, cid)}
    if report == "finance":
        return {"period": [start, end], "monthly": analytics.monthly_series(db, cid, 12), "cashflow": analytics.cashflow_series(db, cid, 6),
                "receivables": analytics.receivables(db, cid), "payables": analytics.payables(db, cid),
                "overdue": [{"number": i.number, "due_date": i.due_date, "balance": i.balance} for i in analytics.overdue_invoices(db, cid)],
                "customers_owing": analytics.customers_owing_more_than(db, cid, 0)}
    if report == "management":
        cc = build_command_center(db, cid)
        return {"period": [start, end], "summary": cc["summary"], "signals": cc["signals"], "kpis": cc["kpis"],
                "top_customers": analytics.top_customers(db, cid, start, end, 10), "top_products": analytics.top_products(db, cid, start, end, 10)}
    return {"error": "unknown report; use sales | inventory | finance | management"}


# ---------------------------------------------------------------- dashboard builder
from pydantic import BaseModel  # noqa: E402


class WidgetIn(BaseModel):
    type: str
    w: int = 1


@router.get("/dashboards/widgets")
def widget_catalog(user: User = Depends(get_current_user)):
    """Widgets this user may add (the others are hidden, and their data is never returned)."""
    from app.services import dashboards
    return [{"type": k, "w": dashboards.WIDGETS[k][1], "display": dashboards.WIDGETS[k][2]} for k in dashboards.allowed(user)]


@router.get("/dashboards/mine")
def my_dashboard(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    from sqlalchemy import select
    from app.models import DashboardLayout
    from app.services import dashboards
    lay = db.scalar(select(DashboardLayout).where(DashboardLayout.user_id == user.id))
    ok = set(dashboards.allowed(user))
    widgets = [w for w in (lay.widgets if lay else dashboards.default_layout(user)) if w.get("type") in ok]
    return {"widgets": widgets, "data": dashboards.data(db, user, [w["type"] for w in widgets])}


@router.put("/dashboards/mine")
def save_dashboard(widgets: list[WidgetIn], user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    from sqlalchemy import select
    from app.models import DashboardLayout
    from app.services import dashboards
    ok = set(dashboards.allowed(user))
    clean = [{"type": w.type, "w": max(1, min(4, w.w))} for w in widgets if w.type in ok][:30]
    lay = db.scalar(select(DashboardLayout).where(DashboardLayout.user_id == user.id))
    if not lay:
        lay = DashboardLayout(company_id=user.company_id, user_id=user.id)
        db.add(lay)
    lay.widgets = clean
    db.commit()
    return my_dashboard(user, db)
