"""Business intelligence beyond the dashboard: pricing suggestions, risk (fraud) signals per employee and the daily summary."""
from collections import defaultdict
from datetime import date, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import (
    Cheque, Company, CreditNote, Expense, Invoice, Payment, PosShift, Product, SalesOrder, SalesOrderItem, StockLevel, Transaction, User,
)
from app.services import analytics


def pricing_suggestions(db: Session, cid: int, days: int = 90) -> list[dict]:
    """Where a price change would help: selling below cost, fast sellers with a thin margin, and slow stock worth discounting."""
    since = date.today() - timedelta(days=days)
    sold = {pid: (float(q), float(rev)) for pid, q, rev in db.execute(
        select(SalesOrderItem.product_id, func.sum(SalesOrderItem.quantity), func.sum(SalesOrderItem.line_total * analytics.ORDER_RATE))
        .join(SalesOrder, SalesOrder.id == SalesOrderItem.order_id)
        .where(SalesOrder.company_id == cid, SalesOrder.status.in_(analytics.ACTIVE_ORDER_STATUSES), SalesOrder.order_date >= since)
        .group_by(SalesOrderItem.product_id)).all()}
    stock = dict(db.execute(select(StockLevel.product_id, func.sum(StockLevel.quantity)).where(StockLevel.company_id == cid).group_by(StockLevel.product_id)).all())
    products = db.scalars(select(Product).where(Product.company_id == cid, Product.is_active.is_(True))).all()
    margin = {p.id: ((p.sale_price - p.cost_price) / p.sale_price * 100) if p.sale_price else 0 for p in products}
    by_cat: dict[str, list[float]] = defaultdict(list)
    for p in products:
        by_cat[p.category or ""].append(margin[p.id])
    cat_avg = {c: sum(v) / len(v) for c, v in by_cat.items() if v}
    velocities = sorted((sold.get(p.id, (0, 0))[0] / days for p in products), reverse=True)
    fast_cut = velocities[max(len(velocities) // 4 - 1, 0)] if velocities else 0
    out = []
    for p in products:
        q, _rev = sold.get(p.id, (0, 0))
        per_day = q / days
        on_hand = float(stock.get(p.id, 0) or 0)
        avg = cat_avg.get(p.category or "", 0)
        base = {"product_id": p.id, "name": p.name, "category": p.category, "price": p.sale_price, "cost": p.cost_price,
                "margin_pct": round(margin[p.id], 1), "category_margin_pct": round(avg, 1), "sold_per_day": round(per_day, 2), "stock": on_hand}
        if p.sale_price and p.sale_price < p.cost_price:
            out.append({**base, "kind": "below_cost", "suggested_price": round(p.cost_price / (1 - max(avg, 15) / 100), 2), "priority": 1})
        elif per_day > 0 and per_day >= fast_cut and margin[p.id] < avg - 5:
            out.append({**base, "kind": "raise", "suggested_price": round(p.cost_price / (1 - avg / 100), 2) if avg < 95 else p.sale_price,
                        "priority": 2, "extra_profit_month": round((p.cost_price / (1 - avg / 100) - p.sale_price) * per_day * 30, 2) if avg < 95 else 0})
        elif on_hand > 0 and (per_day == 0 or on_hand / per_day > 120) and on_hand * p.cost_price > 100:
            out.append({**base, "kind": "slow", "suggested_price": round(p.sale_price * 0.9, 2), "priority": 3,
                        "days_of_stock": None if per_day == 0 else round(on_hand / per_day), "tied_up_value": round(on_hand * p.cost_price, 2)})
    return sorted(out, key=lambda x: (x["priority"], -(x.get("extra_profit_month") or x.get("tied_up_value") or 0)))


def risk_signals(db: Session, cid: int, days: int = 30) -> list[dict]:
    """Per employee: things worth a second look. Nothing here proves wrongdoing — it points to where to check."""
    since = date.today() - timedelta(days=days)
    since_dt = datetime.combine(since, datetime.min.time())
    users = {u.id: u for u in db.scalars(select(User).where(User.company_id == cid)).all()}
    stats: dict[int, dict] = defaultdict(lambda: {"orders": 0, "cancelled": 0, "discount_sum": 0.0, "high_discounts": 0, "below_cost_lines": 0,
                                                  "refunds": 0, "refund_amount": 0.0, "cash_diff": 0.0, "short_shifts": 0})
    for o in db.scalars(select(SalesOrder).where(SalesOrder.company_id == cid, SalesOrder.order_date >= since, SalesOrder.salesperson_id.is_not(None))).all():
        s = stats[o.salesperson_id]
        s["orders"] += 1
        if o.status == "cancelled":
            s["cancelled"] += 1
        s["discount_sum"] += o.discount_pct or 0
        if (o.discount_pct or 0) >= 15:
            s["high_discounts"] += 1
    for it, sp in db.execute(select(SalesOrderItem, SalesOrder.salesperson_id).join(SalesOrder, SalesOrder.id == SalesOrderItem.order_id)
                             .where(SalesOrder.company_id == cid, SalesOrder.order_date >= since, SalesOrder.status != "cancelled",
                                    SalesOrderItem.unit_price * (1 - SalesOrderItem.discount_pct / 100) < SalesOrderItem.unit_cost - 0.001,
                                    SalesOrderItem.line_total > 0)).all():
        if sp:
            stats[sp]["below_cost_lines"] += 1
    for t in db.scalars(select(Transaction).where(Transaction.company_id == cid, Transaction.kind == "refund", Transaction.created_at >= since_dt)).all():
        if t.user_id:
            stats[t.user_id]["refunds"] += 1
            stats[t.user_id]["refund_amount"] += abs(t.amount)
    for sh in db.scalars(select(PosShift).where(PosShift.company_id == cid, PosShift.closed_at.is_not(None), PosShift.opened_at >= since_dt)).all():
        stats[sh.user_id]["cash_diff"] += sh.difference or 0
        if (sh.difference or 0) <= -1:
            stats[sh.user_id]["short_shifts"] += 1
    out = []
    for uid, s in stats.items():
        flags = []
        if s["orders"] >= 5 and s["cancelled"] / s["orders"] > 0.15:
            flags.append("many_cancellations")
        if s["high_discounts"] >= 3:
            flags.append("high_discounts")
        if s["below_cost_lines"] >= 1:
            flags.append("below_cost")
        if s["refunds"] >= 3:
            flags.append("many_refunds")
        if s["short_shifts"] >= 1:
            flags.append("cash_short")
        u = users.get(uid)
        out.append({"user_id": uid, "name": u.full_name if u else "?", **{k: round(v, 2) if isinstance(v, float) else v for k, v in s.items()},
                    "avg_discount": round(s["discount_sum"] / s["orders"], 1) if s["orders"] else 0, "flags": flags})
    return sorted(out, key=lambda x: (-len(x["flags"]), -x["orders"]))


def detect_anomalies(db: Session, cid: int, days: int = 14, baseline_days: int = 60) -> list[dict]:
    """Days in the recent window whose sales or expenses fall well outside the company's own baseline (the trailing
    `baseline_days` before them) — a statistical z-score, not a fixed threshold, so it adapts to each business's
    normal size and swings instead of everyone sharing one rule."""
    start = date.today() - timedelta(days=baseline_days + days)
    sales_by_day: dict[date, float] = defaultdict(float)
    for d, net in db.execute(select(SalesOrder.order_date, analytics.ORDER_NET).where(
            SalesOrder.company_id == cid, SalesOrder.status.in_(analytics.ACTIVE_ORDER_STATUSES), SalesOrder.order_date >= start)).all():
        sales_by_day[d] += float(net)
    exp_by_day: dict[date, float] = defaultdict(float)
    for d, amt in db.execute(select(Expense.expense_date, Expense.amount).where(Expense.company_id == cid, Expense.expense_date >= start)).all():
        exp_by_day[d] += float(amt)

    def scan(by_day: dict[date, float], metric: str) -> list[dict]:
        out = []
        for i in range(days):
            d = date.today() - timedelta(days=i + 1)  # yesterday back to `days` ago
            base_start = d - timedelta(days=baseline_days)
            baseline = [by_day.get(base_start + timedelta(days=j), 0.0) for j in range(baseline_days)]
            if sum(1 for v in baseline if v > 0) < 10:  # not enough history to have a meaningful baseline yet
                continue
            mean = sum(baseline) / len(baseline)
            var = sum((v - mean) ** 2 for v in baseline) / len(baseline)
            std = var ** 0.5
            if std < 0.01:
                continue
            value = by_day.get(d, 0.0)
            z = (value - mean) / std
            if abs(z) >= 2.5:
                out.append({"date": d.isoformat(), "metric": metric, "value": round(value, 2), "baseline_avg": round(mean, 2),
                           "direction": "spike" if z > 0 else "drop", "z_score": round(z, 1)})
        return out

    return sorted(scan(sales_by_day, "sales") + scan(exp_by_day, "expenses"), key=lambda x: x["date"], reverse=True)


def daily_summary(db: Session, cid: int) -> dict:
    """Yesterday at a glance, for the owner's morning message."""
    from app.core.deps import local_day_utc
    from app.services.company_tz import company_today, company_tz
    y = company_today(db, cid) - timedelta(days=1)
    ys, ye = local_day_utc(y, company_tz(db, cid))
    rev, cogs = analytics.revenue_between(db, cid, y, y)
    orders = db.scalar(select(func.count(SalesOrder.id)).where(SalesOrder.company_id == cid, SalesOrder.order_date == y,
                                                                SalesOrder.status.in_(analytics.ACTIVE_ORDER_STATUSES))) or 0
    received = float(db.scalar(select(func.coalesce(func.sum(Payment.amount * func.coalesce(Payment.exchange_rate, 1)), 0)).where(
        Payment.company_id == cid, Payment.status != "bounced", Payment.paid_at.between(ys, ye))) or 0)
    spent = float(db.scalar(select(func.coalesce(func.sum(Expense.amount), 0)).where(Expense.company_id == cid, Expense.expense_date == y)) or 0)
    top = analytics.top_products(db, cid, y, y, limit=1, by="revenue")
    overdue = analytics.overdue_invoices(db, cid)
    overdue_total = round(sum(i.balance * (i.exchange_rate or 1) for i in overdue), 2)
    cheques_today = db.scalars(select(Cheque).where(Cheque.company_id == cid, Cheque.status.in_(("pending", "deposited")), Cheque.due_date <= y + timedelta(days=1))).all()
    pending = (db.scalar(select(func.count(SalesOrder.id)).where(SalesOrder.company_id == cid, SalesOrder.status == "pending_approval")) or 0) + \
              (db.scalar(select(func.count(Expense.id)).where(Expense.company_id == cid, Expense.approval_status == "pending")) or 0)
    return {"date": y, "sales": round(rev, 2), "gross_profit": round(rev - cogs, 2), "orders": orders, "received": round(received, 2),
            "expenses": round(spent, 2), "top_product": top[0]["name"] if top else None, "overdue_count": len(overdue), "overdue_total": overdue_total,
            "low_stock": len(analytics.low_stock_products(db, cid)), "cheques_due": len(cheques_today),
            "cheques_due_total": round(sum(c.amount for c in cheques_today), 2), "pending_approvals": pending}


def summary_text(s: dict, company: str, currency: str) -> str:
    m = lambda v: f"{v:,.0f} {currency}"  # noqa: E731
    lines = [f"☀️ صباح الخير! ملخص {company} ليوم {s['date']}:",
             f"• المبيعات: {m(s['sales'])} ({s['orders']} طلب) — الربح الإجمالي {m(s['gross_profit'])}",
             f"• المصاري اللي دخلت: {m(s['received'])} — المصاريف: {m(s['expenses'])}"]
    if s["top_product"]:
        lines.append(f"• أكثر منتج انباع: {s['top_product']}")
    if s["overdue_count"]:
        lines.append(f"• فواتير متأخرة: {s['overdue_count']} بقيمة {m(s['overdue_total'])}")
    if s["cheques_due"]:
        lines.append(f"• شيكات مستحقة اليوم: {s['cheques_due']} بقيمة {m(s['cheques_due_total'])}")
    if s["low_stock"]:
        lines.append(f"• منتجات قربت تخلص: {s['low_stock']}")
    if s["pending_approvals"]:
        lines.append(f"• بانتظار موافقتك: {s['pending_approvals']}")
    return "\n".join(lines)


def send_daily_summaries() -> None:
    """Runs every morning: emails yesterday's summary to each company owner."""
    import html

    from app.core.database import SessionLocal
    from app.services import email as mail
    from app.services.companies import company_owner
    with SessionLocal() as db:
        for c in db.scalars(select(Company).where(Company.is_active.is_(True))).all():
            owner = company_owner(db, c.id)
            if not owner:
                continue
            text = summary_text(daily_summary(db, c.id), c.name, c.currency)
            body = "".join(f"<p style='margin:6px 0'>{html.escape(line)}</p>" for line in text.split("\n"))
            mail.queue(db, owner.email, f"ملخص {c.name} اليومي", mail.layout("ملخص الأمس", body, c.name), "daily_summary", c.id)
        db.commit()
