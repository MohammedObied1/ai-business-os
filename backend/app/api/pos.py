"""Point of sale: one call sells, invoices and takes payment."""
from datetime import date, datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import require_permission
from app.models import Company, Customer, Invoice, Payment, SalesOrder, User, Warehouse
from app.schemas.sales import ChequeIn, OrderIn, OrderItemIn
from app.services import sales_ops

router = APIRouter(prefix="/pos", tags=["point of sale"])


class PosPayment(BaseModel):
    method: str = "cash"
    amount: float  # in `currency` (default: the company currency)
    account_id: int | None = None
    reference: str | None = None
    cheque: ChequeIn | None = None
    currency: str | None = None


class PosSale(BaseModel):
    items: list[OrderItemIn]
    customer_id: int | None = None  # empty = walk-in customer
    warehouse_id: int | None = None
    discount_pct: float = 0
    payments: list[PosPayment] = []  # may be less than the total → the rest stays on the customer's account
    cash_received: float | None = None  # to compute change (in the company currency)
    notes: str | None = None
    client_ref: str | None = None  # unique id from the till, so a sale synced twice (offline mode) is saved once


def walk_in_customer(db: Session, cid: int) -> Customer:
    company = db.get(Company, cid)
    settings = dict(company.settings or {})
    c = db.get(Customer, settings.get("walk_in_customer_id") or 0)
    if not c or c.company_id != cid:
        c = Customer(company_id=cid, name="زبون نقدي", customer_type="individual", notes="Walk-in / cash customer (point of sale)")
        db.add(c)
        db.flush()
        settings["walk_in_customer_id"] = c.id
        company.settings = settings
    return c


@router.get("/setup")
def setup(user: User = Depends(require_permission("pos:use")), db: Session = Depends(get_db)):
    c = walk_in_customer(db, user.company_id)
    db.commit()
    warehouses = db.scalars(select(Warehouse).where(Warehouse.company_id == user.company_id)).all()
    if user.branch_id:
        warehouses = [w for w in warehouses if w.branch_id in (None, user.branch_id)] or warehouses
    from app.core.deps import warehouse_scope
    if (allowed := warehouse_scope(user)) is not None:
        warehouses = [w for w in warehouses if w.id in allowed]
    from app.models import Currency
    rates = db.scalars(select(Currency).where(Currency.company_id == user.company_id).order_by(Currency.code)).all()
    return {"walk_in_customer_id": c.id, "warehouses": [{"id": w.id, "name": w.name} for w in warehouses],
            "currencies": [{"code": r.code, "rate": r.rate} for r in rates]}


@router.post("/sale", status_code=201)
def sale(payload: PosSale, user: User = Depends(require_permission("pos:use")), db: Session = Depends(get_db)):
    cid = user.company_id
    if payload.client_ref:
        dup = db.scalar(select(SalesOrder).where(SalesOrder.company_id == cid, SalesOrder.client_ref == payload.client_ref))
        if dup:
            inv = db.scalar(select(Invoice).where(Invoice.order_id == dup.id))
            return {"order_id": dup.id, "order_number": dup.number, "invoice_id": inv.id if inv else None, "invoice_number": inv.number if inv else None,
                    "total": dup.total, "tax_amount": dup.tax_amount, "paid": inv.paid_amount if inv else 0, "balance": inv.balance if inv else 0,
                    "change": 0, "receipt_number": None, "duplicate": True}
    cust = sales_ops.customer(db, cid, payload.customer_id) if payload.customer_id else walk_in_customer(db, cid)
    order = sales_ops.create_order(db, user, OrderIn(customer_id=cust.id, warehouse_id=payload.warehouse_id, status="delivered",
                                                     discount_pct=payload.discount_pct, items=payload.items, notes=payload.notes,
                                                     client_ref=payload.client_ref), source="pos")
    if order.status == "pending_approval":
        raise HTTPException(403, "This sale needs a manager's approval (discount or price below cost). Use the sales screen.")
    inv = sales_ops.invoice_for_order(db, cid, order, due_days=0 if not payload.customer_id else 30)
    from app.services import currency as fx
    paid = round(sum(p.amount * fx.rate(db, cid, fx.normalize(db, cid, p.currency)) for p in payload.payments), 2)
    tol = max([0.01] + [fx.rate(db, cid, fx.normalize(db, cid, p.currency)) * 0.006 for p in payload.payments if p.currency])
    if abs(paid - inv.total) <= tol:
        paid = inv.total
    if paid > inv.total + 0.01:
        raise HTTPException(400, f"Payments ({paid:g}) are more than the total ({inv.total:g})")
    if not payload.customer_id and paid + 0.01 < inv.total:
        raise HTTPException(400, "A walk-in customer must pay the full amount. Choose a customer to sell on credit.")
    number = None
    for p in payload.payments:
        if p.amount <= 0:
            continue
        pay = sales_ops.pay_invoice(db, user, inv, p.amount, p.method, p.reference, p.account_id, p.cheque, number=number, pay_currency=p.currency)
        number = pay.number
    cash_paid = sum(p.amount * fx.rate(db, cid, fx.normalize(db, cid, p.currency)) for p in payload.payments if p.method == "cash")
    change = round(payload.cash_received - cash_paid, 2) if payload.cash_received is not None else 0
    if change < -0.01:
        raise HTTPException(400, "Cash received is less than the cash amount")
    db.commit()
    return {"order_id": order.id, "order_number": order.number, "invoice_id": inv.id, "invoice_number": inv.number, "total": inv.total,
            "tax_amount": inv.tax_amount, "paid": paid, "balance": inv.balance, "change": max(change, 0), "receipt_number": number}


@router.get("/today")
def today(user: User = Depends(require_permission("pos:use")), db: Session = Depends(get_db)):
    """Cashier's end-of-day summary for the signed-in user."""
    from app.core.deps import local_day_utc
    from app.services.company_tz import company_today, company_tz
    cid = user.company_id
    d = company_today(db, cid)
    start, end = local_day_utc(d, company_tz(db, cid))
    orders = db.scalars(select(SalesOrder).where(SalesOrder.company_id == cid, SalesOrder.salesperson_id == user.id, SalesOrder.order_date == d,
                                                 SalesOrder.status.in_(("confirmed", "delivered")))).all()
    by_method = dict(db.execute(select(Payment.method, func.sum(Payment.amount)).join(Invoice, Invoice.id == Payment.invoice_id)
                                .join(SalesOrder, SalesOrder.id == Invoice.order_id)
                                .where(Payment.company_id == cid, SalesOrder.salesperson_id == user.id, Payment.paid_at.between(start, end),
                                       Payment.status != "bounced")
                                .group_by(Payment.method)).all())
    return {"date": d, "sales_count": len(orders), "total": round(sum(o.total for o in orders), 2),
            "tax": round(sum(o.tax_amount or 0 for o in orders), 2), "by_method": {k: round(v, 2) for k, v in by_method.items()}}



# ---------------------------------------------------------------- cashier shifts
class ShiftOpen(BaseModel):
    opening_float: float = 0
    account_id: int | None = None


class ShiftClose(BaseModel):
    counted_cash: float
    note: str | None = None


def _expected(db: Session, sh) -> float:
    """Opening float + cash this cashier took into the till account since the shift opened − refunds they paid out."""
    from app.models import Transaction
    moved = db.scalar(select(func.coalesce(func.sum(Transaction.amount), 0)).where(
        Transaction.account_id == sh.account_id, Transaction.user_id == sh.user_id, Transaction.id > (sh.start_tx_id or 0),
        Transaction.kind.in_(("customer_payment", "refund"))))
    return round((sh.opening_float or 0) + float(moved or 0), 2)


def _shift_out(db: Session, sh) -> dict:
    return {"id": sh.id, "opened_at": sh.opened_at, "closed_at": sh.closed_at, "opening_float": sh.opening_float, "account_id": sh.account_id,
            "expected_cash": sh.expected_cash if sh.closed_at else _expected(db, sh), "counted_cash": sh.counted_cash, "difference": sh.difference,
            "note": sh.note}


@router.get("/shift")
def current_shift(user: User = Depends(require_permission("pos:use")), db: Session = Depends(get_db)):
    from app.models import PosShift
    sh = db.scalar(select(PosShift).where(PosShift.user_id == user.id, PosShift.closed_at.is_(None)))
    return _shift_out(db, sh) if sh else None


@router.post("/shift/open")
def open_shift(payload: ShiftOpen, user: User = Depends(require_permission("pos:use")), db: Session = Depends(get_db)):
    from app.models import PosShift
    from app.services.money import get_account
    if db.scalar(select(PosShift.id).where(PosShift.user_id == user.id, PosShift.closed_at.is_(None))):
        raise HTTPException(400, "You already have an open shift")
    acc = get_account(db, user.company_id, payload.account_id)
    from app.models import Transaction
    last_tx = db.scalar(select(func.max(Transaction.id))) or 0
    sh = PosShift(company_id=user.company_id, user_id=user.id, account_id=acc.id, opened_at=datetime.utcnow(), opening_float=payload.opening_float,
                  start_tx_id=last_tx)
    db.add(sh)
    db.commit()
    return _shift_out(db, sh)


@router.post("/shift/close")
def close_shift(payload: ShiftClose, user: User = Depends(require_permission("pos:use")), db: Session = Depends(get_db)):
    from app.models import Alert, PosShift
    sh = db.scalar(select(PosShift).where(PosShift.user_id == user.id, PosShift.closed_at.is_(None)))
    if not sh:
        raise HTTPException(400, "No open shift")
    sh.expected_cash = _expected(db, sh)
    sh.counted_cash = payload.counted_cash
    sh.difference = round(payload.counted_cash - sh.expected_cash, 2)
    sh.closed_at, sh.note = datetime.utcnow(), payload.note
    if abs(sh.difference) >= 1:
        db.add(Alert(company_id=user.company_id, severity="critical" if abs(sh.difference) >= 50 else "warning", category="cash",
                     title=f"Cash difference {sh.difference:+,.2f}: {user.full_name}",
                     message=f"Shift {sh.opened_at:%Y-%m-%d %H:%M}: expected {sh.expected_cash:,.2f}, counted {sh.counted_cash:,.2f}.",
                     recommended_action="Review the shift sales and refunds", dedupe_key=f"shift:{sh.id}"))
    db.commit()
    return _shift_out(db, sh)


@router.get("/shifts")
def shifts(user: User = Depends(require_permission("reports:read")), db: Session = Depends(get_db)):
    from app.models import PosShift
    names = dict(db.execute(select(User.id, User.full_name).where(User.company_id == user.company_id)).all())
    return [{**_shift_out(db, sh), "user": names.get(sh.user_id)}
            for sh in db.scalars(select(PosShift).where(PosShift.company_id == user.company_id).order_by(PosShift.id.desc()).limit(200)).all()]
