"""AI inventory forecasting: weighted moving average + weekday seasonality + lead-time risk."""
from datetime import date, timedelta

import numpy as np
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Product, SalesOrder, SalesOrderItem, StockLevel


def _daily_sales(db: Session, cid: int, product_id: int, days: int) -> np.ndarray:
    start = date.today() - timedelta(days=days)
    rows = db.execute(
        select(SalesOrder.order_date, func.sum(SalesOrderItem.quantity))
        .join(SalesOrder, SalesOrder.id == SalesOrderItem.order_id)
        .where(
            SalesOrderItem.product_id == product_id,
            SalesOrder.company_id == cid,
            SalesOrder.status.in_(("confirmed", "delivered")),
            SalesOrder.order_date >= start,
        )
        .group_by(SalesOrder.order_date)
    ).all()
    series = np.zeros(days)
    by_day = {r[0]: float(r[1]) for r in rows}
    for i in range(days):
        d = start + timedelta(days=i + 1)
        series[i] = by_day.get(d, 0.0)
    return series


def forecast_product(db: Session, cid: int, product: Product, history_days: int = 90) -> dict:
    series = _daily_sales(db, cid, product.id, history_days)
    stock = float(
        db.scalar(
            select(func.coalesce(func.sum(StockLevel.quantity), 0)).where(
                StockLevel.product_id == product.id, StockLevel.company_id == cid
            )
        )
    )

    if series.sum() == 0:
        avg = 0.0
        trend = 0.0
        seasonal = np.ones(7)
    else:
        # exponentially weighted average: recent days matter more
        weights = np.exp(np.linspace(-2, 0, history_days))
        avg = float(np.average(series, weights=weights))
        # trend: compare last 30 days vs previous 30
        last, prev = series[-30:].mean(), series[-60:-30].mean() if history_days >= 60 else series[-30:].mean()
        trend = (last - prev) / prev if prev > 0 else 0.0
        trend = max(min(trend, 0.5), -0.5)
        # weekday seasonality index
        weekday_sums = np.zeros(7)
        weekday_counts = np.zeros(7)
        start = date.today() - timedelta(days=history_days)
        for i, v in enumerate(series):
            wd = (start + timedelta(days=i + 1)).weekday()
            weekday_sums[wd] += v
            weekday_counts[wd] += 1
        weekday_avg = np.divide(weekday_sums, weekday_counts, out=np.zeros(7), where=weekday_counts > 0)
        seasonal = weekday_avg / weekday_avg.mean() if weekday_avg.mean() > 0 else np.ones(7)

    def predict(days: int) -> float:
        total = 0.0
        for i in range(days):
            wd = (date.today() + timedelta(days=i + 1)).weekday()
            total += avg * (1 + trend * 0.5) * seasonal[wd]
        return round(total, 1)

    d7, d30 = predict(7), predict(30)
    lead = product.supplier_lead_time_days
    demand_during_lead = predict(lead)
    safety_stock = avg * 3  # three days buffer
    days_of_cover = round(stock / avg, 1) if avg > 0 else None

    if avg == 0:
        risk = "NONE"
    elif stock < demand_during_lead:
        risk = "HIGH"
    elif stock < demand_during_lead + safety_stock + d7:
        risk = "MEDIUM"
    else:
        risk = "LOW"

    target = d30 + demand_during_lead + safety_stock
    recommended = max(0.0, round(target - stock))
    if risk == "LOW":
        recommended = 0.0

    # confidence: how much to trust the prediction — needs enough history and fairly steady demand.
    # (coefficient of variation: high day-to-day swing on a thin history means the average is a weak guide)
    days_with_data = int((series > 0).sum())
    if avg == 0 or days_with_data < 5:
        confidence, confidence_pct = "LOW", 20
    else:
        cv = float(series.std() / avg) if avg > 0 else 0
        history_factor = min(days_with_data / 30, 1.0)  # ramps up to full trust after ~30 selling days
        confidence_pct = max(15, min(95, round((1 - min(cv, 1.5) / 1.5) * 70 * history_factor + 25)))
        confidence = "HIGH" if confidence_pct >= 70 else "MEDIUM" if confidence_pct >= 40 else "LOW"

    explanation = (
        f"Average daily sales {avg:.1f} {product.unit}, trend {trend * 100:+.0f}%. Stock {stock:.0f} covers "
        f"{days_of_cover if days_of_cover is not None else '∞'} days; supplier needs {lead} days. "
        f"Predicted 7-day demand {d7:.0f} ({confidence.lower()} confidence)."
    )
    return {
        "product_id": product.id,
        "product_name": product.name,
        "current_stock": stock,
        "avg_daily_sales": round(avg, 2),
        "lead_time_days": lead,
        "predicted_7d_demand": d7,
        "predicted_30d_demand": d30,
        "days_of_cover": days_of_cover,
        "risk": risk,
        "recommended_order_qty": recommended,
        "confidence": confidence,
        "confidence_pct": confidence_pct,
        "explanation": explanation,
    }


def forecast_all(db: Session, cid: int, only_risky: bool = False) -> list[dict]:
    products = db.scalars(select(Product).where(Product.company_id == cid, Product.is_active.is_(True))).all()
    out = [forecast_product(db, cid, p) for p in products]
    order = {"HIGH": 0, "MEDIUM": 1, "LOW": 2, "NONE": 3}
    out.sort(key=lambda x: (order[x["risk"]], -x["avg_daily_sales"]))
    if only_risky:
        out = [o for o in out if o["risk"] in ("HIGH", "MEDIUM")]
    return out
