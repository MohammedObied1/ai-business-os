from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.core.deps import branch_scope, has_permission, require_permission
from app.core.pagination import page
from app.models import Company, CreditNote, Customer, Installment, Invoice, Payment, Product, RecurringInvoice, SalesOrder, SalesOrderItem, User
from app.schemas.sales import (
    CreditNoteOut, CustomerReceiptIn, InvoiceDetail, InvoiceIn, InvoiceOut, OrderIn, OrderOut, PaymentIn, PaymentOut, QuoteIn, ReturnIn,
)
from app.services import currency as fx
from app.services import email as mail
from app.services import sales_ops
from app.services.numbering import next_number
from app.services.pricing import price_cart

router = APIRouter(prefix="/sales", tags=["sales"])


def _order(db: Session, user: User, order_id: int) -> SalesOrder:
    o = db.get(SalesOrder, order_id)
    scope = branch_scope(user)
    if not o or o.company_id != user.company_id or (scope and o.branch_id and o.branch_id != scope):
        raise HTTPException(404, "Order not found")
    return o


def _invoice(db: Session, user: User, invoice_id: int) -> Invoice:
    inv = db.get(Invoice, invoice_id)
    scope = branch_scope(user)
    if not inv or inv.company_id != user.company_id or (scope and inv.branch_id and inv.branch_id != scope):
        raise HTTPException(404, "Invoice not found")
    return inv


def _search_customers(q: str):
    return select(Customer.id).where(Customer.name.ilike(f"%{q}%"))


def _mask(user: User, out):
    """Cost and profit only for people allowed to see costs (a cashier must not)."""
    from app.core.deps import can_see_cost
    if can_see_cost(user):
        return out
    return out.model_copy(update={"cost_total": None, "items": [i.model_copy(update={"unit_cost": None}) for i in out.items]})


def _order_out(db: Session, user: User, o) -> "OrderOut":
    inv = db.scalar(select(Invoice.id).where(Invoice.order_id == o.id, Invoice.status != "cancelled"))
    return _mask(user, _named(db, [o], OrderOut)[0].model_copy(update={"invoice_id": inv}))


def _named(db: Session, rows: list, schema) -> list:
    """List rows + the customer's name, so a page of results doesn't need the whole customer list."""
    ids = {r.customer_id for r in rows}
    names = dict(db.execute(select(Customer.id, Customer.name).where(Customer.id.in_(ids))).all()) if ids else {}
    return [schema.model_validate(r).model_copy(update={"customer_name": names.get(r.customer_id)}) for r in rows]


# ---------------------------------------------------------------- orders
@router.get("/orders", response_model=list[OrderOut])
def list_orders(response: Response, status: str | None = None, customer_id: int | None = None, q: str | None = None, offset: int = 0,
                limit: int = Query(100, le=5000), user: User = Depends(require_permission("sales:read")), db: Session = Depends(get_db)):
    stmt = select(SalesOrder).where(SalesOrder.company_id == user.company_id)
    if (scope := branch_scope(user)):
        stmt = stmt.where(or_(SalesOrder.branch_id == scope, SalesOrder.branch_id.is_(None)))
    if status:
        stmt = stmt.where(SalesOrder.status == status)
    if customer_id:
        stmt = stmt.where(SalesOrder.customer_id == customer_id)
    if q:
        stmt = stmt.where(or_(SalesOrder.number.ilike(f"%{q}%"), SalesOrder.customer_id.in_(_search_customers(q))))
    rows = _named(db, page(db, stmt.order_by(SalesOrder.order_date.desc(), SalesOrder.id.desc()), response, offset, limit), OrderOut)
    inv = dict(db.execute(select(Invoice.order_id, Invoice.id).where(Invoice.order_id.in_([r.id for r in rows]), Invoice.status != "cancelled")).all()) if rows else {}
    return [_mask(user, r.model_copy(update={"invoice_id": inv.get(r.id)})) for r in rows]


@router.post("/quote")
def quote(payload: QuoteIn, user: User = Depends(require_permission("sales:read")), db: Session = Depends(get_db)):
    """Price a cart without saving it (price lists, promotions, VAT, currency) — used by the POS and the sale form."""
    cust = sales_ops.customer(db, user.company_id, payload.customer_id) if payload.customer_id else None
    cur = fx.normalize(db, user.company_id, payload.currency)
    p = price_cart(db, user.company_id, payload.items, cust, payload.discount_pct, fx.rate(db, user.company_id, cur))
    return {"lines": [{"product_id": ln.product.id, "name": ln.product.name, "quantity": ln.uom_qty or ln.base_qty, "unit": ln.uom_label,
                       "price": ln.price, "discount_pct": ln.discount_pct, "line_total": ln.line_total, "promo": ln.promo, "free": ln.free}
                      for ln in p.lines],
            "lines_total": p.lines_total, "net": p.net, "tax": p.tax, "total": p.total, "needs_approval": p.approval_reasons}


@router.post("/orders", response_model=OrderOut, status_code=201)
def create_order(payload: OrderIn, user: User = Depends(require_permission("sales:write")), db: Session = Depends(get_db)):
    order = sales_ops.create_order(db, user, payload)
    db.commit()
    db.refresh(order)
    return _order_out(db, user, order)


@router.get("/orders/{order_id}", response_model=OrderOut)
def get_order(order_id: int, user: User = Depends(require_permission("sales:read")), db: Session = Depends(get_db)):
    return _order_out(db, user, _order(db, user, order_id))


@router.post("/orders/{order_id}/approve", response_model=OrderOut)
def approve_order(order_id: int, user: User = Depends(require_permission("approvals:approve")), db: Session = Depends(get_db)):
    o = sales_ops.approve_order(db, user, _order(db, user, order_id))
    db.commit()
    db.refresh(o)
    return _order_out(db, user, o)


@router.post("/orders/{order_id}/status", response_model=OrderOut)
def set_order_status(order_id: int, status: str, user: User = Depends(require_permission("sales:write")), db: Session = Depends(get_db)):
    o = _order(db, user, order_id)
    need = "sales.delete" if status == "cancelled" else "sales.edit"
    if not has_permission(user, need):
        raise HTTPException(403, f"Missing permission(s): {need}")
    if o.status == "pending_approval" and status in sales_ops.ACTIVE:
        raise HTTPException(403, "This order needs a manager's approval")
    was_active = o.status in sales_ops.ACTIVE
    now_active = status in sales_ops.ACTIVE
    if status == "cancelled" and db.scalar(select(Invoice.id).where(Invoice.order_id == o.id, Invoice.status != "cancelled")):
        raise HTTPException(400, "Cancel the invoice first, or make a return")
    if o.warehouse_id and not was_active and now_active:
        sales_ops._move_stock(db, user.company_id, o, -1)
    if o.warehouse_id and was_active and status == "cancelled":
        sales_ops._move_stock(db, user.company_id, o, +1)
    if o.number.startswith("QT") and now_active:
        o.number = next_number(db, SalesOrder, user.company_id, "SO")
    o.status = status
    from app.services import webhooks
    webhooks.emit(db, user.company_id, "order.updated", {"id": o.id, "number": o.number, "status": o.status, "total": o.total})
    db.commit()
    db.refresh(o)
    return _order_out(db, user, o)


# ---------------------------------------------------------------- invoices
@router.get("/invoices", response_model=list[InvoiceOut])
def list_invoices(response: Response, status: str | None = None, customer_id: int | None = None, q: str | None = None, offset: int = 0,
                  limit: int = Query(100, le=5000), user: User = Depends(require_permission("sales:read")), db: Session = Depends(get_db)):
    stmt = select(Invoice).where(Invoice.company_id == user.company_id)
    if (scope := branch_scope(user)):
        stmt = stmt.where(or_(Invoice.branch_id == scope, Invoice.branch_id.is_(None)))
    if status:
        stmt = stmt.where(Invoice.status.in_(status.split(",")))
    if customer_id:
        stmt = stmt.where(Invoice.customer_id == customer_id)
    if q:
        stmt = stmt.where(or_(Invoice.number.ilike(f"%{q}%"), Invoice.customer_id.in_(_search_customers(q))))
    return _named(db, page(db, stmt.order_by(Invoice.issue_date.desc(), Invoice.id.desc()), response, offset, limit), InvoiceOut)


@router.post("/invoices", response_model=InvoiceOut, status_code=201)
def create_invoice(payload: InvoiceIn, user: User = Depends(require_permission("invoices:create")), db: Session = Depends(get_db)):
    cid = user.company_id
    sales_ops.customer(db, cid, payload.customer_id)
    if payload.order_id:
        inv = sales_ops.invoice_for_order(db, cid, _order(db, user, payload.order_id), payload.due_days)
    else:
        inv = manual_invoice(db, user, payload.customer_id, payload.total, payload.due_days, payload.currency, payload.description)
    db.commit()
    db.refresh(inv)
    return inv


def manual_invoice(db: Session, user: User, customer_id: int, total: float | None, due_days: int, currency: str | None = None,
                   description: str | None = None, recurring_id: int | None = None) -> Invoice:
    """An invoice for a service or amount without items (tax extracted with the company rate when the total includes it)."""
    from app.services import webhooks
    from app.services.money import company_tax
    cid = user.company_id
    if not total or total <= 0:
        raise HTTPException(400, "total or order_id required")
    rate_pct, _ = company_tax(db, cid)
    tax = round(total - total / (1 + rate_pct / 100), 2) if rate_pct else 0
    cur = fx.normalize(db, cid, currency)
    inv = Invoice(company_id=cid, number=next_number(db, Invoice, cid, "INV"), customer_id=customer_id, issue_date=date.today(),
                  due_date=date.today() + timedelta(days=due_days), total=round(total, 2), tax_amount=tax, subtotal=round(total - tax, 2),
                  currency=cur, exchange_rate=fx.rate(db, cid, cur), branch_id=branch_scope(user), description=description, recurring_id=recurring_id)
    db.add(inv)
    db.flush()
    webhooks.emit(db, cid, "invoice.created", {"id": inv.id, "number": inv.number, "customer_id": customer_id, "total": inv.total})
    return inv


def invoice_detail_for(db: Session, inv: Invoice) -> InvoiceDetail:
    customer = db.get(Customer, inv.customer_id)
    order = db.get(SalesOrder, inv.order_id) if inv.order_id else None
    items = []
    if order:
        lines = db.scalars(select(SalesOrderItem).where(SalesOrderItem.order_id == order.id)).all()
        names = {p.id: p for p in db.scalars(select(Product).where(Product.id.in_([i.product_id for i in lines]))).all()}
        for i in lines:
            p = names.get(i.product_id)
            items.append({"product": p.name if p else "?", "sku": p.sku if p else "", "unit": i.uom_label or (p.unit if p else None),
                          "quantity": i.uom_qty or i.quantity, "unit_price": i.uom_price or i.unit_price, "discount_pct": i.discount_pct,
                          "line_total": i.line_total})
    elif inv.description:
        items.append({"product": inv.description, "sku": "", "unit": None, "quantity": 1, "unit_price": inv.subtotal or inv.total,
                      "discount_pct": 0, "line_total": inv.subtotal or inv.total})
    payments = db.scalars(select(Payment).where(Payment.invoice_id == inv.id).order_by(Payment.paid_at)).all()
    notes = db.scalars(select(CreditNote).where(CreditNote.invoice_id == inv.id).order_by(CreditNote.id)).all()
    company = db.get(Company, inv.company_id)
    detail = InvoiceDetail(
        invoice=InvoiceOut.model_validate(inv), company=company, customer=customer,
        order_number=order.number if order else None, order_discount_pct=order.discount_pct if order else 0,
        subtotal=order.subtotal if order else (inv.subtotal or inv.total), tax_rate=order.tax_rate if order else (company.tax_rate or 0), items=items,
        payments=[PaymentOut.model_validate(p) for p in payments], credit_notes=[CreditNoteOut.model_validate(n) for n in notes],
        public_token=inv.public_token,
    )
    detail.currency = inv.currency or company.currency
    detail.installments = installment_schedule(db, inv)
    return detail


@router.get("/invoices/{invoice_id}", response_model=InvoiceDetail)
def invoice_detail(invoice_id: int, user: User = Depends(require_permission("sales:read")), db: Session = Depends(get_db)):
    """Everything needed to show or print an invoice."""
    return invoice_detail_for(db, _invoice(db, user, invoice_id))


@router.post("/invoices/{invoice_id}/share")
def share_invoice(invoice_id: int, user: User = Depends(require_permission("sales:read")), db: Session = Depends(get_db)):
    """Create (once) a secret link the customer can open without logging in."""
    inv = _invoice(db, user, invoice_id)
    token = sales_ops.ensure_public_token(inv)
    db.commit()
    return {"token": token, "url": f"{settings.PUBLIC_APP_URL.rstrip('/')}/i/{token}"}


class EmailIn(BaseModel):
    to: str | None = None
    lang: str = "ar"


@router.post("/invoices/{invoice_id}/email")
def email_invoice(invoice_id: int, payload: EmailIn, user: User = Depends(require_permission("sales:read")), db: Session = Depends(get_db)):
    inv = _invoice(db, user, invoice_id)
    cust = db.get(Customer, inv.customer_id)
    to = (payload.to or cust.email or "").strip()
    if not to:
        raise HTTPException(400, "The customer has no email address")
    company = db.get(Company, user.company_id)
    token = sales_ops.ensure_public_token(inv)
    link = f"{settings.PUBLIC_APP_URL.rstrip('/')}/i/{token}"
    ar = payload.lang == "ar"
    cur = inv.currency or company.currency
    body = (f"<p>{'مرحبا' if ar else 'Hello'} {cust.name},</p>"
            f"<p>{'مرفق فاتورتكم رقم' if ar else 'Here is your invoice'} <b>{inv.number}</b> "
            f"{'بقيمة' if ar else 'for'} <b>{inv.total:,.2f} {cur}</b>. {'آخر موعد للدفع' if ar else 'Due on'} {inv.due_date}.</p>")
    m = mail.queue(db, to, f"{'فاتورة' if ar else 'Invoice'} {inv.number} — {company.name}",
                   mail.layout(f"{'فاتورة' if ar else 'Invoice'} {inv.number}", body, company.name, ("اعرض الفاتورة" if ar else "View invoice", link), rtl=ar),
                   "invoice", company.id)
    db.commit()
    return {"status": m.status, "to": to}


@router.get("/invoices/{invoice_id}/ubl.xml")
def invoice_ubl(invoice_id: int, user: User = Depends(require_permission("sales:read")), db: Session = Depends(get_db)):
    """Electronic invoice in UBL 2.1 XML (the format most e-invoicing systems accept)."""
    from app.services.einvoice import ubl_invoice
    inv = _invoice(db, user, invoice_id)
    xml = ubl_invoice(db, invoice_detail_for(db, inv))
    return Response(xml, media_type="application/xml", headers={"Content-Disposition": f'attachment; filename="{inv.number}.xml"'})


@router.post("/invoices/{invoice_id}/cancel", response_model=InvoiceOut)
def cancel_invoice(invoice_id: int, user: User = Depends(require_permission("invoices:create")), db: Session = Depends(get_db)):
    inv = _invoice(db, user, invoice_id)
    if not has_permission(user, "invoices.cancel"):
        raise HTTPException(403, "Missing permission(s): invoices.cancel")
    if inv.paid_amount > 0 or (inv.credited_amount or 0) > 0:
        raise HTTPException(400, "Invoice has payments and cannot be cancelled")
    from app.services import approvals, periods
    periods.check_open(db, user.company_id, inv.issue_date)
    if approvals.needs(db, user, "invoice_cancel", inv.total * (inv.exchange_rate or 1)):
        req = approvals.request(db, user, "invoice_cancel", "invoices", inv.id, inv.number, round(inv.total * (inv.exchange_rate or 1), 2),
                                "Cancel invoice")
        db.commit()
        return JSONResponse(status_code=202, content=approvals.pending_response(req))
    inv.status = "cancelled"
    db.commit()
    db.refresh(inv)
    return inv


# ---------------------------------------------------------------- instalments
class InstallmentPlanIn(BaseModel):
    count: int
    first_due: date
    every_days: int = 30


def installment_schedule(db: Session, inv: Invoice) -> list[dict]:
    """Instalments with their paid status, derived from what has been paid on the invoice (oldest first)."""
    rows = db.scalars(select(Installment).where(Installment.invoice_id == inv.id).order_by(Installment.seq)).all()
    covered = (inv.paid_amount or 0) + (inv.credited_amount or 0)
    out = []
    for r in rows:
        paid = round(min(r.amount, max(covered, 0)), 2)
        covered -= r.amount
        status = "paid" if paid >= r.amount - 0.009 else ("late" if r.due_date < date.today() else "partial" if paid > 0 else "upcoming")
        out.append({"id": r.id, "seq": r.seq, "due_date": r.due_date, "amount": r.amount, "paid": paid, "status": status})
    return out


@router.post("/invoices/{invoice_id}/installments")
def set_installments(invoice_id: int, payload: InstallmentPlanIn, user: User = Depends(require_permission("invoices:create")),
                     db: Session = Depends(get_db)):
    inv = _invoice(db, user, invoice_id)
    if payload.count < 2 or payload.count > 120:
        raise HTTPException(400, "Choose between 2 and 120 instalments")
    for old in db.scalars(select(Installment).where(Installment.invoice_id == inv.id)).all():
        db.delete(old)
    each = round(inv.total / payload.count, 2)
    for i in range(payload.count):
        amount = each if i < payload.count - 1 else round(inv.total - each * (payload.count - 1), 2)
        db.add(Installment(company_id=user.company_id, invoice_id=inv.id, seq=i + 1, amount=amount,
                           due_date=payload.first_due + timedelta(days=payload.every_days * i)))
    inv.due_date = payload.first_due + timedelta(days=payload.every_days * (payload.count - 1))
    db.commit()
    return installment_schedule(db, inv)


@router.get("/installments/due")
def installments_due(days: int = 7, user: User = Depends(require_permission("sales:read")), db: Session = Depends(get_db)):
    """Unpaid instalments due within `days` (or late), across all invoices."""
    out = []
    names = dict(db.execute(select(Customer.id, Customer.name).where(Customer.company_id == user.company_id)).all())
    inv_ids = {r for r in db.scalars(select(Installment.invoice_id).where(Installment.company_id == user.company_id)).all()}
    for inv in db.scalars(select(Invoice).where(Invoice.id.in_(inv_ids), Invoice.status.in_(("open", "partial", "overdue")))).all():
        for s in installment_schedule(db, inv):
            if s["status"] != "paid" and s["due_date"] <= date.today() + timedelta(days=days):
                out.append({**s, "invoice_id": inv.id, "invoice": inv.number, "customer": names.get(inv.customer_id),
                            "customer_id": inv.customer_id, "remaining": round(s["amount"] - s["paid"], 2)})
    return sorted(out, key=lambda x: x["due_date"])


# ---------------------------------------------------------------- recurring invoices
class RecurringIn(BaseModel):
    customer_id: int
    description: str
    amount: float
    interval_months: int = 1
    next_date: date
    end_date: date | None = None
    due_days: int = 14
    send_email: bool = False
    is_active: bool = True


def _rec_out(r: RecurringInvoice, names: dict) -> dict:
    return {c: getattr(r, c) for c in ("id", "customer_id", "description", "amount", "interval_months", "next_date", "end_date", "due_days",
                                       "send_email", "is_active", "last_invoice_id")} | {"customer": names.get(r.customer_id)}


@router.get("/recurring")
def list_recurring(user: User = Depends(require_permission("sales:read")), db: Session = Depends(get_db)):
    names = dict(db.execute(select(Customer.id, Customer.name).where(Customer.company_id == user.company_id)).all())
    return [_rec_out(r, names) for r in db.scalars(select(RecurringInvoice).where(RecurringInvoice.company_id == user.company_id)
                                                    .order_by(RecurringInvoice.next_date)).all()]


@router.post("/recurring", status_code=201)
def create_recurring(payload: RecurringIn, user: User = Depends(require_permission("invoices:create")), db: Session = Depends(get_db)):
    sales_ops.customer(db, user.company_id, payload.customer_id)
    if payload.amount <= 0 or payload.interval_months < 1:
        raise HTTPException(400, "Amount must be greater than zero")
    r = RecurringInvoice(company_id=user.company_id, **payload.model_dump())
    db.add(r)
    db.commit()
    return {"id": r.id}


@router.patch("/recurring/{rid}")
def update_recurring(rid: int, payload: RecurringIn, user: User = Depends(require_permission("invoices:create")), db: Session = Depends(get_db)):
    r = db.get(RecurringInvoice, rid)
    if not r or r.company_id != user.company_id:
        raise HTTPException(404, "Not found")
    for k, v in payload.model_dump().items():
        setattr(r, k, v)
    db.commit()
    return {"id": r.id}


@router.post("/recurring/run")
def run_recurring_now(user: User = Depends(require_permission("invoices:create")), db: Session = Depends(get_db)):
    from app.services.recurring import run_company
    return {"created": run_company(db, user.company_id)}


# ---------------------------------------------------------------- payments
@router.post("/payments", response_model=PaymentOut, status_code=201)
def record_payment(payload: PaymentIn, user: User = Depends(require_permission("payments:write")), db: Session = Depends(get_db)):
    inv = _invoice(db, user, payload.invoice_id)
    pay = sales_ops.pay_invoice(db, user, inv, payload.amount, payload.method, payload.reference, payload.account_id, payload.cheque,
                                pay_currency=payload.currency)
    db.commit()
    db.refresh(pay)
    return pay


@router.post("/receipts", response_model=list[PaymentOut], status_code=201)
def receive_from_customer(payload: CustomerReceiptIn, user: User = Depends(require_permission("payments:write")), db: Session = Depends(get_db)):
    """Customer pays an amount on account; it settles their oldest invoices first."""
    pays = sales_ops.receive_from_customer(db, user, payload.customer_id, payload.amount, payload.method, payload.reference,
                                           payload.account_id, payload.cheque, payload.currency)
    db.commit()
    return pays


@router.get("/payments", response_model=list[PaymentOut])
def list_payments(response: Response, customer_id: int | None = None, q: str | None = None, offset: int = 0, limit: int = Query(100, le=5000),
                  user: User = Depends(require_permission("sales:read")), db: Session = Depends(get_db)):
    stmt = select(Payment).where(Payment.company_id == user.company_id)
    if (scope := branch_scope(user)):
        stmt = stmt.where(Payment.invoice_id.in_(select(Invoice.id).where(or_(Invoice.branch_id == scope, Invoice.branch_id.is_(None)))))
    if customer_id:
        stmt = stmt.where(Payment.customer_id == customer_id)
    if q:
        stmt = stmt.where(or_(Payment.number.ilike(f"%{q}%"), Payment.reference.ilike(f"%{q}%"), Payment.customer_id.in_(_search_customers(q))))
    return _named(db, page(db, stmt.order_by(Payment.paid_at.desc(), Payment.id.desc()), response, offset, limit), PaymentOut)


@router.get("/receipts/{number}")
def receipt_voucher(number: str, user: User = Depends(require_permission("sales:read")), db: Session = Depends(get_db)):
    """Receipt voucher (سند قبض): one voucher number may cover several invoices."""
    from app.models import Cheque
    pays = db.scalars(select(Payment).where(Payment.company_id == user.company_id, Payment.number == number)).all()
    if not pays:
        raise HTTPException(404, "Voucher not found")
    cust = db.get(Customer, pays[0].customer_id)
    invs = {i.id: i for i in db.scalars(select(Invoice).where(Invoice.id.in_([p.invoice_id for p in pays]))).all()}
    cheque = db.scalar(select(Cheque).where(Cheque.payment_id.in_([p.id for p in pays])))
    company = db.get(Company, user.company_id)
    return {"number": number, "date": pays[0].paid_at, "customer": {"id": cust.id, "name": cust.name, "phone": cust.phone} if cust else None,
            "amount": round(sum(p.account_amount if p.account_amount is not None else p.amount for p in pays), 2), "method": pays[0].method,
            "reference": pays[0].reference, "status": "bounced" if any(p.status == "bounced" for p in pays) else "done",
            "invoices": [{"number": invs[p.invoice_id].number, "amount": p.amount, "currency": invs[p.invoice_id].currency or company.currency} for p in pays],
            "cheque": {"number": cheque.number, "bank": cheque.bank, "due_date": cheque.due_date, "status": cheque.status} if cheque else None,
            "company": {"name": company.name, "logo_path": company.logo_path}}


# ---------------------------------------------------------------- returns
@router.get("/returns", response_model=list[CreditNoteOut])
def list_returns(response: Response, customer_id: int | None = None, q: str | None = None, offset: int = 0, limit: int = Query(200, le=5000),
                 user: User = Depends(require_permission("sales:read")), db: Session = Depends(get_db)):
    stmt = select(CreditNote).where(CreditNote.company_id == user.company_id)
    if customer_id:
        stmt = stmt.where(CreditNote.customer_id == customer_id)
    if q:
        stmt = stmt.where(or_(CreditNote.number.ilike(f"%{q}%"), CreditNote.customer_id.in_(_search_customers(q))))
    return _named(db, page(db, stmt.order_by(CreditNote.id.desc()), response, offset, limit), CreditNoteOut)


@router.post("/returns", response_model=CreditNoteOut, status_code=201)
def create_return(payload: ReturnIn, user: User = Depends(require_permission("returns:create")), db: Session = Depends(get_db)):
    from app.services import approvals
    order = _order(db, user, payload.order_id)
    items = {i.id: i for i in order.items}
    value = sum(ln.quantity * (items[ln.order_item_id].line_total / items[ln.order_item_id].quantity if items[ln.order_item_id].quantity else 0)
                for ln in payload.items if ln.order_item_id in items) * (order.exchange_rate or 1)
    if approvals.needs(db, user, "large_return", value):
        req = approvals.request(db, user, "large_return", "sales_orders", order.id, f"Return {order.number}", round(value, 2), payload.reason,
                                payload=payload.model_dump(mode="json"))
        db.commit()
        return JSONResponse(status_code=202, content=approvals.pending_response(req))
    cn = sales_ops.create_return(db, user, payload)
    db.commit()
    db.refresh(cn)
    return cn
