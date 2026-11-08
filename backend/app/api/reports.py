"""Accounting reports with a chosen date range (and branch)."""
import csv
import io
from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import require_permission
from app.models import CreditNote, Customer, Expense, Payment, Product, PurchaseOrder, SalesOrder, SalesOrderItem, SavedReport, User
from app.services import analytics

router = APIRouter(prefix="/reports", tags=["reports"])


def _range(start: date | None, end: date | None) -> tuple[date, date]:
    if start and end:
        return start, end
    return analytics.month_bounds(date.today())


@router.get("/pnl")
def profit_and_loss(start: date | None = None, end: date | None = None, branch_id: int | None = None,
                    user: User = Depends(require_permission("reports:read")), db: Session = Depends(get_db)):
    """Profit & loss (قائمة الدخل) for any period."""
    cid = user.company_id
    s, e = _range(start, end)
    stmt = select(func.coalesce(func.sum(analytics.ORDER_NET), 0), func.coalesce(func.sum(SalesOrder.cost_total), 0)).where(
        SalesOrder.company_id == cid, SalesOrder.status.in_(analytics.ACTIVE_ORDER_STATUSES), SalesOrder.order_date.between(s, e))
    if branch_id:
        stmt = stmt.where(SalesOrder.branch_id == branch_id)
    gross_sales, cogs = (float(x) for x in db.execute(stmt).one())
    ret, ret_cost = (float(x) for x in db.execute(select(func.coalesce(func.sum(CreditNote.subtotal * func.coalesce(CreditNote.exchange_rate, 1)), 0), func.coalesce(func.sum(CreditNote.cost_total), 0))
                                                   .where(CreditNote.company_id == cid, CreditNote.note_date.between(s, e))).one())
    exp_stmt = select(Expense.category, func.sum(Expense.amount - func.coalesce(Expense.tax_amount, 0))).where(
        Expense.company_id == cid, Expense.expense_date.between(s, e))
    if branch_id:
        exp_stmt = exp_stmt.where(Expense.branch_id == branch_id)
    expenses = [{"category": c, "amount": round(float(a), 2)} for c, a in db.execute(exp_stmt.group_by(Expense.category)).all()]
    expenses.sort(key=lambda x: -x["amount"])
    net_sales = gross_sales - ret
    net_cogs = cogs - ret_cost
    total_exp = sum(x["amount"] for x in expenses)
    gross_profit = net_sales - net_cogs
    return {"start": s, "end": e, "sales": round(gross_sales, 2), "returns": round(ret, 2), "net_sales": round(net_sales, 2),
            "cogs": round(net_cogs, 2), "gross_profit": round(gross_profit, 2),
            "gross_margin_pct": round(gross_profit / net_sales * 100, 1) if net_sales else 0,
            "expenses": expenses, "total_expenses": round(total_exp, 2), "net_profit": round(gross_profit - total_exp, 2),
            "net_margin_pct": round((gross_profit - total_exp) / net_sales * 100, 1) if net_sales else 0}


@router.get("/vat")
def vat(start: date | None = None, end: date | None = None, user: User = Depends(require_permission("reports:read")), db: Session = Depends(get_db)):
    """VAT return helper: tax charged on sales minus tax paid on purchases and expenses."""
    cid = user.company_id
    s, e = _range(start, end)
    out_sales = float(db.scalar(select(func.coalesce(func.sum(SalesOrder.tax_amount * analytics.ORDER_RATE), 0)).where(
        SalesOrder.company_id == cid, SalesOrder.status.in_(analytics.ACTIVE_ORDER_STATUSES), SalesOrder.order_date.between(s, e))))
    taxable_sales = float(db.scalar(select(func.coalesce(func.sum(analytics.ORDER_NET), 0)).where(
        SalesOrder.company_id == cid, SalesOrder.status.in_(analytics.ACTIVE_ORDER_STATUSES), SalesOrder.order_date.between(s, e))))
    out_returns = float(db.scalar(select(func.coalesce(func.sum(CreditNote.tax_amount * func.coalesce(CreditNote.exchange_rate, 1)), 0)).where(CreditNote.company_id == cid, CreditNote.note_date.between(s, e))))
    in_purchases = float(db.scalar(select(func.coalesce(func.sum(PurchaseOrder.tax_amount * func.coalesce(PurchaseOrder.exchange_rate, 1)), 0)).where(
        PurchaseOrder.company_id == cid, PurchaseOrder.status == "received", func.coalesce(PurchaseOrder.received_on, PurchaseOrder.order_date).between(s, e))))
    in_expenses = float(db.scalar(select(func.coalesce(func.sum(Expense.tax_amount), 0)).where(Expense.company_id == cid, Expense.expense_date.between(s, e))))
    output_tax = out_sales - out_returns
    input_tax = in_purchases + in_expenses
    return {"start": s, "end": e, "taxable_sales": round(taxable_sales, 2), "output_tax": round(output_tax, 2), "returns_tax": round(out_returns, 2),
            "input_tax_purchases": round(in_purchases, 2), "input_tax_expenses": round(in_expenses, 2), "input_tax": round(input_tax, 2),
            "tax_due": round(output_tax - input_tax, 2)}


@router.get("/sales-by-user")
def sales_by_user(start: date | None = None, end: date | None = None, user: User = Depends(require_permission("reports:read")), db: Session = Depends(get_db)):
    cid = user.company_id
    s, e = _range(start, end)
    rows = db.execute(select(User.id, User.full_name, func.count(SalesOrder.id), func.coalesce(func.sum(analytics.ORDER_NET), 0),
                             func.coalesce(func.sum(analytics.ORDER_NET - SalesOrder.cost_total), 0))
                      .join(SalesOrder, SalesOrder.salesperson_id == User.id)
                      .where(SalesOrder.company_id == cid, SalesOrder.status.in_(analytics.ACTIVE_ORDER_STATUSES), SalesOrder.order_date.between(s, e))
                      .group_by(User.id, User.full_name).order_by(func.sum(analytics.ORDER_NET).desc())).all()
    return [{"user_id": r[0], "name": r[1], "orders": r[2], "revenue": round(float(r[3]), 2), "profit": round(float(r[4]), 2)} for r in rows]


@router.get("/sales-by-product")
def sales_by_product(start: date | None = None, end: date | None = None, user: User = Depends(require_permission("reports:read")), db: Session = Depends(get_db)):
    s, e = _range(start, end)
    return analytics.top_products(db, user.company_id, s, e, limit=100000, by="revenue")


@router.get("/sales-by-customer")
def sales_by_customer(start: date | None = None, end: date | None = None, user: User = Depends(require_permission("reports:read")), db: Session = Depends(get_db)):
    s, e = _range(start, end)
    return analytics.top_customers(db, user.company_id, s, e, limit=100000)


@router.get("/aging")
def receivables_aging(user: User = Depends(require_permission("reports:read")), db: Session = Depends(get_db)):
    """Who owes what, split by how late it is (0-30, 31-60, 61-90, 90+ days past due)."""
    from app.models import Invoice
    cid = user.company_id
    today = date.today()
    names = dict(db.execute(select(Customer.id, Customer.name).where(Customer.company_id == cid)).all())
    phones = dict(db.execute(select(Customer.id, Customer.phone).where(Customer.company_id == cid)).all())
    agg: dict[int, dict] = {}
    for inv in db.scalars(select(Invoice).where(Invoice.company_id == cid, Invoice.status.in_(analytics.OPEN_INVOICE))).all():
        bal = round(inv.balance * (inv.exchange_rate or 1), 2)
        if bal <= 0.009:
            continue
        late = (today - inv.due_date).days
        bucket = "current" if late <= 0 else "d30" if late <= 30 else "d60" if late <= 60 else "d90" if late <= 90 else "older"
        a = agg.setdefault(inv.customer_id, {"customer_id": inv.customer_id, "name": names.get(inv.customer_id), "phone": phones.get(inv.customer_id),
                                             "current": 0.0, "d30": 0.0, "d60": 0.0, "d90": 0.0, "older": 0.0, "total": 0.0, "oldest_days": 0})
        a[bucket] = round(a[bucket] + bal, 2)
        a["total"] = round(a["total"] + bal, 2)
        a["oldest_days"] = max(a["oldest_days"], late)
    return sorted(agg.values(), key=lambda x: -x["total"])


@router.get("/daily-sales")
def daily_sales(start: date | None = None, end: date | None = None, user: User = Depends(require_permission("reports:read")), db: Session = Depends(get_db)):
    cid = user.company_id
    s, e = _range(start, end)
    rows = db.execute(select(SalesOrder.order_date, func.count(SalesOrder.id), func.coalesce(func.sum(analytics.ORDER_NET), 0),
                             func.coalesce(func.sum(SalesOrder.tax_amount * analytics.ORDER_RATE), 0))
                      .where(SalesOrder.company_id == cid, SalesOrder.status.in_(analytics.ACTIVE_ORDER_STATUSES), SalesOrder.order_date.between(s, e))
                      .group_by(SalesOrder.order_date).order_by(SalesOrder.order_date)).all()
    received = {str(k): v for k, v in db.execute(select(func.date(Payment.paid_at), func.sum(Payment.amount * func.coalesce(Payment.exchange_rate, 1))).where(Payment.company_id == cid, Payment.status != "bounced")
                               .group_by(func.date(Payment.paid_at))).all()}
    return [{"date": d, "orders": n, "net_sales": round(float(net), 2), "tax": round(float(tax), 2), "received": round(float(received.get(str(d), 0) or 0), 2)}
            for d, n, net, tax in rows]


@router.get("/branch")
def branch_report(start: date | None = None, end: date | None = None, user: User = Depends(require_permission("reports:read")), db: Session = Depends(get_db)):
    """Revenue by branch and by warehouse, for companies with more than one location."""
    s, e = _range(start, end)
    return {"start": s, "end": e, "by_branch": analytics.sales_by_branch(db, user.company_id, s, e),
            "by_warehouse": analytics.sales_by_warehouse(db, user.company_id, s, e)}


@router.get("/cashflow")
def cashflow_report(months: int = 6, user: User = Depends(require_permission("reports:read")), db: Session = Depends(get_db)):
    return analytics.cashflow_series(db, user.company_id, max(1, min(months, 24)))


@router.get("/dead-stock")
def dead_stock_report(days: int = 90, user: User = Depends(require_permission("reports:read")), db: Session = Depends(get_db)):
    """Stock that hasn't moved out in `days` — a candidate list for clearance sales or write-offs."""
    return analytics.dead_stock(db, user.company_id, max(1, min(days, 3650)))


# ---------------------------------------------------------------- saved reports (a name + a report tab + its filters)
class SavedReportIn(BaseModel):
    name: str
    report: str
    params: dict = {}


@router.get("/saved")
def list_saved(user: User = Depends(require_permission("reports:read")), db: Session = Depends(get_db)):
    rows = db.scalars(select(SavedReport).where(SavedReport.company_id == user.company_id, SavedReport.user_id == user.id)
                      .order_by(SavedReport.id.desc())).all()
    return [{"id": r.id, "name": r.name, "report": r.report, "params": r.params, "created_at": r.created_at} for r in rows]


@router.post("/saved", status_code=201)
def save_report(payload: SavedReportIn, user: User = Depends(require_permission("reports:read")), db: Session = Depends(get_db)):
    if not payload.name.strip():
        raise HTTPException(400, "Give it a name")
    r = SavedReport(company_id=user.company_id, user_id=user.id, name=payload.name.strip()[:150], report=payload.report, params=payload.params)
    db.add(r)
    db.commit()
    return {"id": r.id, "name": r.name, "report": r.report, "params": r.params, "created_at": r.created_at}


@router.delete("/saved/{report_id}", status_code=204)
def delete_saved(report_id: int, user: User = Depends(require_permission("reports:read")), db: Session = Depends(get_db)):
    r = db.get(SavedReport, report_id)
    if not r or r.company_id != user.company_id or r.user_id != user.id:
        raise HTTPException(404, "Not found")
    db.delete(r)
    db.commit()


# ---------------------------------------------------------------- CSV export (only for the tabular reports)
_TABULAR = {
    "sales-by-user": (sales_by_user, ["user_id", "name", "orders", "revenue", "profit"]),
    "sales-by-product": (lambda s, e, u, db: analytics.top_products(db, u.company_id, s, e, limit=100000, by="revenue"),
                          ["name", "category", "quantity", "revenue", "profit", "margin_pct"]),
    "sales-by-customer": (lambda s, e, u, db: analytics.top_customers(db, u.company_id, s, e, limit=100000),
                           ["name", "orders", "revenue"]),
    "daily-sales": (daily_sales, ["date", "orders", "net_sales", "tax", "received"]),
    "aging": (lambda s, e, u, db: receivables_aging(u, db), ["name", "current", "d30", "d60", "d90", "older", "total"]),
    "dead-stock": (lambda s, e, u, db: analytics.dead_stock(db, u.company_id), ["sku", "name", "category", "on_hand", "value", "last_sold"]),
}


@router.get("/export/{report}")
def export_csv(report: str, start: date | None = None, end: date | None = None,
               user: User = Depends(require_permission("reports:read", "reports.export")), db: Session = Depends(get_db)):
    if report not in _TABULAR:
        raise HTTPException(404, "This report can't be exported as CSV")
    fn, cols = _TABULAR[report]
    s, e = _range(start, end)
    rows = fn(s, e, user, db)
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=cols, extrasaction="ignore")
    w.writeheader()
    for r in rows:
        # guard against CSV formula injection: a cell starting with =/+/-/@ runs as a formula in Excel/Sheets
        w.writerow({k: ("'" + v if isinstance(v, str) and v[:1] in "=+-@" else v) for k, v in r.items()})
    buf.seek(0)
    return StreamingResponse(iter([buf.getvalue()]), media_type="text/csv",
                             headers={"Content-Disposition": f'attachment; filename="{report}.csv"'})
