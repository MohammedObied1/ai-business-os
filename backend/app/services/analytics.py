"""Business analytics used by dashboard, reports and the AI agent's tools."""
from datetime import date, datetime, timedelta

from sqlalchemy import and_, func, select
from sqlalchemy.orm import Session

from app.models import (
    Branch, CreditNote, Customer, Expense, Invoice, Payment, Product, PurchaseOrder, SalesOrder, SalesOrderItem, StockLevel, StockMovement, Supplier,
    Warehouse,
)

ACTIVE_ORDER_STATUSES = ("confirmed", "delivered")
OPEN_INVOICE = ("open", "partial", "overdue")
# what the customer still owes on an invoice, in the invoice's currency (returns reduce it through credited_amount)
INVOICE_BALANCE = Invoice.total - Invoice.paid_amount - func.coalesce(Invoice.credited_amount, 0)
# the same in the company's base currency, for totals across currencies
INVOICE_BALANCE_BASE = INVOICE_BALANCE * func.coalesce(Invoice.exchange_rate, 1)
# sales revenue excludes VAT (it belongs to the tax authority), converted to the base currency
ORDER_RATE = func.coalesce(SalesOrder.exchange_rate, 1)
ORDER_NET = (SalesOrder.total - func.coalesce(SalesOrder.tax_amount, 0)) * ORDER_RATE


def month_bounds(d: date) -> tuple[date, date]:
    start = d.replace(day=1)
    nxt = (start + timedelta(days=32)).replace(day=1)
    return start, nxt - timedelta(days=1)


def revenue_between(db: Session, cid: int, start: date, end: date, branch_id: int | None = None) -> tuple[float, float]:
    """(net revenue, cost of goods sold) for the period, after sales returns."""
    stmt = select(func.coalesce(func.sum(ORDER_NET), 0), func.coalesce(func.sum(SalesOrder.cost_total), 0)).where(
        SalesOrder.company_id == cid,
        SalesOrder.status.in_(ACTIVE_ORDER_STATUSES),
        SalesOrder.order_date.between(start, end),
    )
    if branch_id:
        stmt = stmt.where(SalesOrder.branch_id == branch_id)
    row = db.execute(stmt).one()
    ret = db.execute(select(func.coalesce(func.sum(CreditNote.subtotal * func.coalesce(CreditNote.exchange_rate, 1)), 0),
                            func.coalesce(func.sum(CreditNote.cost_total), 0)).where(
        CreditNote.company_id == cid, CreditNote.note_date.between(start, end))).one()
    return float(row[0]) - float(ret[0]), float(row[1]) - float(ret[1])


def expenses_between(db: Session, cid: int, start: date, end: date) -> float:
    return float(
        db.scalar(
            select(func.coalesce(func.sum(Expense.amount), 0)).where(
                Expense.company_id == cid, Expense.expense_date.between(start, end)
            )
        )
    )


def receivables(db: Session, cid: int) -> float:
    return float(
        db.scalar(
            select(func.coalesce(func.sum(INVOICE_BALANCE_BASE), 0)).where(
                Invoice.company_id == cid, Invoice.status.in_(OPEN_INVOICE)
            )
        )
    )


def payables(db: Session, cid: int) -> float:
    owed = float(
        db.scalar(
            select(func.coalesce(func.sum((PurchaseOrder.total - PurchaseOrder.paid_amount) * func.coalesce(PurchaseOrder.exchange_rate, 1)), 0)).where(
                PurchaseOrder.company_id == cid, PurchaseOrder.status.in_(("ordered", "received"))
            )
        )
    )
    from app.models.stock import SupplierReturn
    returned = float(db.scalar(select(func.coalesce(func.sum(SupplierReturn.total), 0)).where(SupplierReturn.company_id == cid)) or 0)
    return owed - returned + float(db.scalar(select(func.coalesce(func.sum(Supplier.opening_balance), 0)).where(Supplier.company_id == cid)) or 0)


def inventory_value(db: Session, cid: int) -> float:
    """Value of stock on hand (available + reserved + in transit) under the company's costing method."""
    from app.services import costing
    return costing.valuation(db, cid)


def overdue_invoices(db: Session, cid: int, min_days: int = 0) -> list[Invoice]:
    cutoff = date.today() - timedelta(days=min_days)
    return list(
        db.scalars(
            select(Invoice).where(
                Invoice.company_id == cid,
                Invoice.status.in_(OPEN_INVOICE),
                Invoice.due_date < cutoff,
                INVOICE_BALANCE > 0.009,
            )
        )
    )


def low_stock_products(db: Session, cid: int) -> list[dict]:
    rows = db.execute(
        select(Product, func.coalesce(func.sum(StockLevel.quantity), 0).label("qty"))
        .outerjoin(StockLevel, StockLevel.product_id == Product.id)
        .where(Product.company_id == cid, Product.is_active.is_(True))
        .group_by(Product.id)
    ).all()
    return [
        {"product_id": p.id, "sku": p.sku, "name": p.name, "stock": float(q), "min_stock": p.min_stock}
        for p, q in rows
        if p.min_stock > 0 and float(q) < p.min_stock
    ]


def top_customers(db: Session, cid: int, start: date, end: date, limit: int = 20) -> list[dict]:
    rows = db.execute(
        select(Customer.id, Customer.name, func.sum(ORDER_NET).label("rev"), func.count(SalesOrder.id))
        .join(SalesOrder, SalesOrder.customer_id == Customer.id)
        .where(
            SalesOrder.company_id == cid,
            SalesOrder.status.in_(ACTIVE_ORDER_STATUSES),
            SalesOrder.order_date.between(start, end),
        )
        .group_by(Customer.id, Customer.name)
        .order_by(func.sum(ORDER_NET).desc())
        .limit(limit)
    ).all()
    return [{"customer_id": r[0], "name": r[1], "revenue": round(float(r[2]), 2), "orders": r[3]} for r in rows]


def top_products(db: Session, cid: int, start: date, end: date, limit: int = 20, by: str = "profit") -> list[dict]:
    rows = db.execute(
        select(
            Product.id,
            Product.name,
            Product.category,
            func.sum(SalesOrderItem.quantity),
            func.sum(SalesOrderItem.line_total * ORDER_RATE),
            func.sum(SalesOrderItem.line_total * ORDER_RATE - SalesOrderItem.quantity * SalesOrderItem.unit_cost),
        )
        .join(SalesOrderItem, SalesOrderItem.product_id == Product.id)
        .join(SalesOrder, SalesOrder.id == SalesOrderItem.order_id)
        .where(
            SalesOrder.company_id == cid,
            SalesOrder.status.in_(ACTIVE_ORDER_STATUSES),
            SalesOrder.order_date.between(start, end),
        )
        .group_by(Product.id, Product.name, Product.category)
    ).all()
    data = [
        {
            "product_id": r[0], "name": r[1], "category": r[2], "quantity": float(r[3]),
            "revenue": round(float(r[4]), 2), "profit": round(float(r[5]), 2),
            "margin_pct": round(float(r[5]) / float(r[4]) * 100, 1) if r[4] else 0,
        }
        for r in rows
    ]
    data.sort(key=lambda x: x[by], reverse=True)
    return data[:limit]


def category_margins(db: Session, cid: int, start: date, end: date) -> list[dict]:
    agg: dict[str, dict] = {}
    for p in top_products(db, cid, start, end, limit=10_000):
        cat = p["category"] or "Uncategorized"
        a = agg.setdefault(cat, {"category": cat, "revenue": 0.0, "profit": 0.0})
        a["revenue"] += p["revenue"]
        a["profit"] += p["profit"]
    out = []
    for a in agg.values():
        a["margin_pct"] = round(a["profit"] / a["revenue"] * 100, 1) if a["revenue"] else 0
        a["revenue"] = round(a["revenue"], 2)
        a["profit"] = round(a["profit"], 2)
        out.append(a)
    return sorted(out, key=lambda x: x["revenue"], reverse=True)


def sales_by_warehouse(db: Session, cid: int, start: date, end: date) -> list[dict]:
    rows = db.execute(
        select(Warehouse.id, Warehouse.name, func.coalesce(func.sum(ORDER_NET), 0), func.count(SalesOrder.id))
        .outerjoin(
            SalesOrder,
            and_(
                SalesOrder.warehouse_id == Warehouse.id,
                SalesOrder.status.in_(ACTIVE_ORDER_STATUSES),
                SalesOrder.order_date.between(start, end),
            ),
        )
        .where(Warehouse.company_id == cid)
        .group_by(Warehouse.id, Warehouse.name)
    ).all()
    return [{"warehouse_id": r[0], "name": r[1], "revenue": round(float(r[2]), 2), "orders": r[3]} for r in rows]


def sales_by_branch(db: Session, cid: int, start: date, end: date) -> list[dict]:
    """Revenue attributed to the order's own branch, falling back to its warehouse's branch (orders taken with no
    warehouse — e.g. quotations — land under "no branch")."""
    rows = db.execute(
        select(Branch.id, Branch.name, func.coalesce(func.sum(ORDER_NET), 0), func.count(SalesOrder.id))
        .outerjoin(
            SalesOrder,
            and_(
                func.coalesce(SalesOrder.branch_id, Warehouse.branch_id) == Branch.id,
                SalesOrder.status.in_(ACTIVE_ORDER_STATUSES),
                SalesOrder.order_date.between(start, end),
            ),
        )
        .outerjoin(Warehouse, Warehouse.id == SalesOrder.warehouse_id)
        .where(Branch.company_id == cid)
        .group_by(Branch.id, Branch.name)
    ).all()
    return [{"branch_id": r[0], "name": r[1], "revenue": round(float(r[2]), 2), "orders": r[3]} for r in rows]


def dead_stock(db: Session, cid: int, days: int = 90) -> list[dict]:
    """Products sitting in stock with no outgoing movement (sale, transfer out, write-off) in `days` — money tied up
    doing nothing. Cost is valued at the product's current cost price (a simple estimate, not the costing engine's
    layered value, since this only needs to rank slow movers)."""
    cutoff = datetime.utcnow() - timedelta(days=days)
    on_hand = dict(db.execute(select(StockLevel.product_id, func.sum(StockLevel.quantity)).where(StockLevel.company_id == cid)
                              .group_by(StockLevel.product_id)).all())
    last_out = dict(db.execute(select(StockMovement.product_id, func.max(StockMovement.occurred_at))
                               .where(StockMovement.company_id == cid, StockMovement.quantity < 0)
                               .group_by(StockMovement.product_id)).all())
    products = {p.id: p for p in db.scalars(select(Product).where(Product.company_id == cid, Product.is_active.is_(True))).all()}
    out = []
    for pid, qty in on_hand.items():
        p = products.get(pid)
        if not p or qty <= 0:
            continue
        last = last_out.get(pid)
        if last and last >= cutoff:
            continue
        out.append({"product_id": pid, "name": p.name, "sku": p.sku, "category": p.category, "on_hand": round(float(qty), 2),
                    "value": round(float(qty) * (p.cost_price or 0), 2), "last_sold": last.isoformat() if last else None})
    return sorted(out, key=lambda x: x["value"], reverse=True)


def customers_owing_more_than(db: Session, cid: int, threshold: float) -> list[dict]:
    rows = db.execute(
        select(Customer.id, Customer.name, func.sum(INVOICE_BALANCE_BASE))
        .join(Invoice, Invoice.customer_id == Customer.id)
        .where(Invoice.company_id == cid, Invoice.status.in_(OPEN_INVOICE))
        .group_by(Customer.id, Customer.name)
        .having(func.sum(INVOICE_BALANCE_BASE) > threshold)
        .order_by(func.sum(INVOICE_BALANCE_BASE).desc())
    ).all()
    return [{"customer_id": r[0], "name": r[1], "balance": round(float(r[2]), 2)} for r in rows]


def high_discount_orders(db: Session, cid: int, start: date, end: date, threshold_pct: float = 15) -> list[dict]:
    rows = db.execute(
        select(SalesOrder.number, Customer.name, SalesOrder.discount_pct, SalesOrder.total)
        .join(Customer, Customer.id == SalesOrder.customer_id)
        .where(
            SalesOrder.company_id == cid,
            SalesOrder.order_date.between(start, end),
            SalesOrder.discount_pct >= threshold_pct,
        )
        .order_by(SalesOrder.discount_pct.desc())
        .limit(10)
    ).all()
    return [{"order": r[0], "customer": r[1], "discount_pct": r[2], "total": r[3]} for r in rows]


def inactive_customers(db: Session, cid: int, days: int = 60) -> list[dict]:
    cutoff = date.today() - timedelta(days=days)
    rows = db.execute(
        select(Customer.id, Customer.name, func.max(SalesOrder.order_date))
        .outerjoin(SalesOrder, SalesOrder.customer_id == Customer.id)
        .where(Customer.company_id == cid)
        .group_by(Customer.id, Customer.name)
    ).all()
    return [
        {"customer_id": r[0], "name": r[1], "last_purchase": r[2].isoformat() if r[2] else None}
        for r in rows
        if r[2] is None or r[2] < cutoff
    ]


def monthly_series(db: Session, cid: int, months: int = 12) -> list[dict]:
    today = date.today()
    out = []
    for i in range(months - 1, -1, -1):
        m = (today.replace(day=1) - timedelta(days=30 * i)).replace(day=1)
        s, e = month_bounds(m)
        rev, cogs = revenue_between(db, cid, s, e)
        exp = expenses_between(db, cid, s, e)
        out.append(
            {"month": s.strftime("%Y-%m"), "revenue": round(rev, 2), "cogs": round(cogs, 2),
             "expenses": round(exp, 2), "profit": round(rev - cogs - exp, 2)}
        )
    return out


def cashflow_series(db: Session, cid: int, months: int = 6) -> list[dict]:
    today = date.today()
    out = []
    for i in range(months - 1, -1, -1):
        m = (today.replace(day=1) - timedelta(days=30 * i)).replace(day=1)
        s, e = month_bounds(m)
        cash_in = float(
            db.scalar(
                select(func.coalesce(func.sum(Payment.amount * func.coalesce(Payment.exchange_rate, 1)), 0)).where(
                    Payment.company_id == cid, Payment.status != "bounced", Payment.paid_at.between(datetime.combine(s, datetime.min.time()), datetime.combine(e, datetime.max.time()))
                )
            )
        )
        cash_out = expenses_between(db, cid, s, e) + float(
            db.scalar(
                select(func.coalesce(func.sum(PurchaseOrder.paid_amount), 0)).where(
                    PurchaseOrder.company_id == cid, PurchaseOrder.order_date.between(s, e)
                )
            )
        )
        out.append({"month": s.strftime("%Y-%m"), "cash_in": round(cash_in, 2), "cash_out": round(cash_out, 2), "net": round(cash_in - cash_out, 2)})
    return out


def dashboard_kpis(db: Session, cid: int) -> dict:
    today = date.today()
    s, e = month_bounds(today)
    ps, pe = month_bounds(s - timedelta(days=1))
    # Month-to-date vs the same elapsed window of the previous month (fair comparison mid-month)
    elapsed = (today - s).days
    pe_window = min(pe, ps + timedelta(days=elapsed))
    rev, cogs = revenue_between(db, cid, s, today)
    prev_rev, prev_cogs = revenue_between(db, cid, ps, pe_window)
    exp = expenses_between(db, cid, s, today)
    prev_exp = expenses_between(db, cid, ps, pe_window)
    profit = rev - cogs - exp
    prev_profit = prev_rev - prev_cogs - prev_exp

    def growth(cur, prev):
        return round((cur - prev) / prev * 100, 1) if prev else None

    return {
        "period": {"start": s.isoformat(), "end": today.isoformat(), "compared_to": {"start": ps.isoformat(), "end": pe_window.isoformat()}},
        "revenue": round(rev, 2),
        "revenue_growth_pct": growth(rev, prev_rev),
        "gross_profit": round(rev - cogs, 2),
        "net_profit": round(profit, 2),
        "profit_growth_pct": growth(profit, prev_profit),
        "expenses": round(exp, 2),
        "expenses_growth_pct": growth(exp, prev_exp),
        "margin_pct": round(profit / rev * 100, 1) if rev else 0,
        "receivables": round(receivables(db, cid), 2),
        "payables": round(payables(db, cid), 2),
        "inventory_value": round(inventory_value(db, cid), 2),
        "overdue_invoices": len(overdue_invoices(db, cid)),
        "low_stock_count": len(low_stock_products(db, cid)),
        "customers_count": db.scalar(select(func.count(Customer.id)).where(Customer.company_id == cid)),
        "orders_this_month": db.scalar(
            select(func.count(SalesOrder.id)).where(SalesOrder.company_id == cid, SalesOrder.order_date.between(s, e))
        ),
    }
