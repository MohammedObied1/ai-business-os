"""Dashboard builder: a catalogue of widgets (each guarded by a permission) and the data behind each one."""
from datetime import date

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.deps import has_permission
from app.models import Account, SalesOrder, User
from app.services import analytics

# type → (permission, default width 1-4, kind of display)
WIDGETS: dict[str, tuple[str, int, str]] = {
    "sales_today": ("reports.view", 1, "stat"),
    "sales_month": ("reports.view", 1, "stat"),
    "profit_month": ("reports.view_profit", 1, "stat"),
    "expenses_month": ("finance.view", 1, "stat"),
    "receivables": ("finance.view", 1, "stat"),
    "payables": ("finance.view", 1, "stat"),
    "cash": ("accounts.view", 1, "stat"),
    "bank": ("accounts.view", 1, "stat"),
    "inventory_value": ("products.view_cost", 1, "stat"),
    "overdue_invoices": ("finance.view", 2, "table"),
    "low_stock": ("inventory.view", 2, "table"),
    "top_products": ("reports.view", 2, "table"),
    "top_customers": ("reports.view", 2, "table"),
    "sales_by_employee": ("reports.view", 2, "table"),
    "sales_chart": ("reports.view", 4, "chart"),
}
DEFAULT_LAYOUT = ["sales_today", "sales_month", "profit_month", "receivables", "sales_chart", "overdue_invoices", "low_stock", "top_products", "top_customers"]


def allowed(user: User) -> list[str]:
    return [k for k, (perm, _w, _d) in WIDGETS.items() if has_permission(user, perm)]


def default_layout(user: User) -> list[dict]:
    ok = set(allowed(user))
    return [{"type": k, "w": WIDGETS[k][1]} for k in DEFAULT_LAYOUT if k in ok]


def _money_accounts(db: Session, cid: int, kind: str) -> float:
    from app.services import currency as fx
    from app.services.money import account_balance
    total = 0.0
    for a in db.scalars(select(Account).where(Account.company_id == cid, Account.kind == kind, Account.is_active.is_(True))).all():
        total += account_balance(db, a) * fx.rate(db, cid, a.currency)
    return round(total, 2)


def data(db: Session, user: User, types: list[str]) -> dict:
    """Numbers for the requested widgets — only the ones this user is allowed to see."""
    cid, today = user.company_id, date.today()
    s, e = analytics.month_bounds(today)
    ok = set(allowed(user))
    out: dict = {}
    for t in types:
        if t not in ok:
            continue
        if t == "sales_today":
            rev, _ = analytics.revenue_between(db, cid, today, today)
            n = db.scalar(select(func.count(SalesOrder.id)).where(SalesOrder.company_id == cid, SalesOrder.order_date == today,
                                                                 SalesOrder.status.in_(analytics.ACTIVE_ORDER_STATUSES))) or 0
            out[t] = {"value": round(rev, 2), "note": n}
        elif t == "sales_month":
            k = analytics.dashboard_kpis(db, cid)
            out[t] = {"value": k["revenue"], "growth": k["revenue_growth_pct"]}
        elif t == "profit_month":
            k = analytics.dashboard_kpis(db, cid)
            out[t] = {"value": k["net_profit"], "growth": k["profit_growth_pct"], "note": k["margin_pct"]}
        elif t == "expenses_month":
            out[t] = {"value": round(analytics.expenses_between(db, cid, s, today), 2)}
        elif t == "receivables":
            out[t] = {"value": round(analytics.receivables(db, cid), 2)}
        elif t == "payables":
            out[t] = {"value": round(analytics.payables(db, cid), 2)}
        elif t == "cash":
            out[t] = {"value": _money_accounts(db, cid, "cash")}
        elif t == "bank":
            out[t] = {"value": _money_accounts(db, cid, "bank")}
        elif t == "inventory_value":
            out[t] = {"value": round(analytics.inventory_value(db, cid), 2)}
        elif t == "overdue_invoices":
            out[t] = {"rows": [{"id": i.id, "number": i.number, "due_date": i.due_date, "balance": round(i.balance, 2)}
                               for i in analytics.overdue_invoices(db, cid)[:10]]}
        elif t == "low_stock":
            out[t] = {"rows": analytics.low_stock_products(db, cid)[:10]}
        elif t == "top_products":
            rows = analytics.top_products(db, cid, s, e, 8, by="revenue")
            if not has_permission(user, "reports.view_profit"):
                rows = [{k: v for k, v in r.items() if k not in ("profit", "margin_pct", "cost")} for r in rows]
            out[t] = {"rows": rows}
        elif t == "top_customers":
            out[t] = {"rows": analytics.top_customers(db, cid, s, e, 8)}
        elif t == "sales_by_employee":
            rows = db.execute(select(User.full_name, func.count(SalesOrder.id), func.coalesce(func.sum(analytics.ORDER_NET), 0))
                              .join(SalesOrder, SalesOrder.salesperson_id == User.id)
                              .where(SalesOrder.company_id == cid, SalesOrder.status.in_(analytics.ACTIVE_ORDER_STATUSES), SalesOrder.order_date.between(s, e))
                              .group_by(User.full_name).order_by(func.sum(analytics.ORDER_NET).desc()).limit(10)).all()
            out[t] = {"rows": [{"name": r[0], "orders": r[1], "revenue": round(float(r[2]), 2)} for r in rows]}
        elif t == "sales_chart":
            series = analytics.monthly_series(db, cid, 12)
            if not has_permission(user, "reports.view_profit"):
                series = [{k: v for k, v in m.items() if k not in ("profit", "cogs")} for m in series]
            out[t] = {"series": series}
    return out
