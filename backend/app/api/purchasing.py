from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.inventory import _warehouse, apply_stock
from app.core.database import get_db
from app.core.deps import branch_scope, require_permission
from app.core.pagination import page
from app.services import currency as fx
from app.services import webhooks
from app.models import Cheque, Product, PurchaseOrder, PurchaseOrderItem, Supplier, SupplierPayment, User, Warehouse
from app.schemas.purchasing import (
    POIn, POOut, ReceiveIn, SupplierIn, SupplierOut, SupplierPaymentIn, SupplierPaymentOut,
)
from app.services.money import company_tax, get_account, post, split_tax
from app.services.numbering import next_number

router = APIRouter(prefix="/purchasing", tags=["purchasing"])

TRANSITIONS = {"request": ["approved", "cancelled"], "approved": ["ordered", "cancelled"], "ordered": ["received", "cancelled"], "received": [], "cancelled": []}


def _supplier(db: Session, cid: int, supplier_id: int) -> Supplier:
    s = db.get(Supplier, supplier_id)
    if not s or s.company_id != cid:
        raise HTTPException(404, "Supplier not found")
    return s


def _po(db: Session, cid: int, po_id: int) -> PurchaseOrder:
    po = db.get(PurchaseOrder, po_id)
    if not po or po.company_id != cid:
        raise HTTPException(404, "Purchase order not found")
    return po


@router.get("/suppliers", response_model=list[SupplierOut])
def list_suppliers(user: User = Depends(require_permission("purchasing:read")), db: Session = Depends(get_db)):
    return db.scalars(select(Supplier).where(Supplier.company_id == user.company_id).order_by(Supplier.name)).all()


@router.post("/suppliers", response_model=SupplierOut, status_code=201)
def create_supplier(payload: SupplierIn, user: User = Depends(require_permission("purchasing:write")), db: Session = Depends(get_db)):
    s = Supplier(company_id=user.company_id, **payload.model_dump())
    db.add(s)
    db.commit()
    db.refresh(s)
    return s


@router.patch("/suppliers/{supplier_id}", response_model=SupplierOut)
def update_supplier(supplier_id: int, payload: SupplierIn, user: User = Depends(require_permission("purchasing:write")), db: Session = Depends(get_db)):
    s = _supplier(db, user.company_id, supplier_id)
    for k, v in payload.model_dump().items():
        setattr(s, k, v)
    db.commit()
    db.refresh(s)
    return s


@router.delete("/suppliers/{supplier_id}", status_code=204)
def delete_supplier(supplier_id: int, user: User = Depends(require_permission("purchasing:write")), db: Session = Depends(get_db)):
    s = _supplier(db, user.company_id, supplier_id)
    if db.scalar(select(func.count(PurchaseOrder.id)).where(PurchaseOrder.supplier_id == s.id)) or \
            db.scalar(select(func.count(SupplierPayment.id)).where(SupplierPayment.supplier_id == s.id)):
        raise HTTPException(400, "This supplier has purchase orders and cannot be deleted")
    db.delete(s)
    db.commit()


@router.get("/orders", response_model=list[POOut])
def list_pos(response: Response, status: str | None = None, supplier_id: int | None = None, q: str | None = None, offset: int = 0,
             limit: int = Query(100, le=5000), user: User = Depends(require_permission("purchasing:read")), db: Session = Depends(get_db)):
    stmt = select(PurchaseOrder).where(PurchaseOrder.company_id == user.company_id)
    if (scope := branch_scope(user)):
        stmt = stmt.where((PurchaseOrder.branch_id == scope) | PurchaseOrder.branch_id.is_(None))
    if q:
        stmt = stmt.where(PurchaseOrder.number.ilike(f"%{q}%") | PurchaseOrder.supplier_id.in_(select(Supplier.id).where(Supplier.name.ilike(f"%{q}%"))))
    if status:
        stmt = stmt.where(PurchaseOrder.status == status)
    if supplier_id:
        stmt = stmt.where(PurchaseOrder.supplier_id == supplier_id)
    return page(db, stmt.order_by(PurchaseOrder.order_date.desc(), PurchaseOrder.id.desc()), response, offset, limit)


@router.post("/orders", response_model=POOut, status_code=201)
def create_po(payload: POIn, user: User = Depends(require_permission("purchasing:write")), db: Session = Depends(get_db)):
    cid = user.company_id
    s = _supplier(db, cid, payload.supplier_id)
    if payload.warehouse_id:
        _warehouse(db, cid, payload.warehouse_id)
    items = [i for i in payload.items if i.product_id]
    if not items or any(it.quantity <= 0 for it in items):
        raise HTTPException(400, "Add at least one product with a quantity above zero")
    cur = fx.normalize(db, cid, payload.currency)
    rate = fx.rate(db, cid, cur)
    wh_branch = db.get(Warehouse, payload.warehouse_id).branch_id if payload.warehouse_id else None
    po = PurchaseOrder(company_id=cid, number=next_number(db, PurchaseOrder, cid, "PR"), supplier_id=s.id, warehouse_id=payload.warehouse_id,
                       expected_date=payload.expected_date, notes=payload.notes, requested_by=user.full_name, status="request",
                       currency=cur, exchange_rate=rate, branch_id=wh_branch or branch_scope(user))
    db.add(po)
    db.flush()
    total = 0.0
    for it in items:
        p = db.get(Product, it.product_id)
        if not p or p.company_id != cid:
            raise HTTPException(404, f"Product {it.product_id} not found")
        factor, label = (p.pack_size, p.pack_unit or "pack") if it.unit == "pack" and p.pack_size else (1.0, None)
        cost = it.unit_cost if it.unit_cost is not None else round(p.cost_price * factor / rate, 4)
        line = round(it.quantity * cost, 2)
        db.add(PurchaseOrderItem(company_id=cid, po_id=po.id, product_id=p.id, quantity=it.quantity * factor, unit_cost=round(cost / factor, 4),
                                 line_total=line, uom_label=label, uom_qty=it.quantity if label else None))
        total += line
    rate, _inclusive = company_tax(db, cid)
    _net, tax, gross = split_tax(total, rate if payload.include_tax else 0, False)
    po.tax_amount, po.total = tax, gross
    from app.services import approvals
    enabled, threshold = approvals.rule(db, cid, "purchase_order")
    if enabled and gross * (rate_po := po.exchange_rate or 1) >= threshold:
        db.flush()
        approvals.request(db, user, "purchase_order", "purchase_orders", po.id, po.number, round(gross * rate_po, 2), po.notes)
    else:  # under the approval limit (or approvals off): approved straight away
        po.status, po.approved_by_id = "approved", user.id
        po.number = po.number.replace("PR-", "PO-", 1)
    webhooks.emit(db, cid, "purchase.created", {"number": po.number, "supplier_id": s.id, "total": po.total, "status": po.status})
    db.commit()
    db.refresh(po)
    return po


@router.get("/orders/{po_id}", response_model=POOut)
def get_po(po_id: int, user: User = Depends(require_permission("purchasing:read")), db: Session = Depends(get_db)):
    return _po(db, user.company_id, po_id)


@router.post("/orders/{po_id}/approve", response_model=POOut)
def approve(po_id: int, user: User = Depends(require_permission("purchasing:approve")), db: Session = Depends(get_db)):
    return _transition(po_id, "approved", user, db)


@router.post("/orders/{po_id}/status", response_model=POOut)
def set_status(po_id: int, status: str, warehouse_id: int | None = None, user: User = Depends(require_permission("purchasing:write")), db: Session = Depends(get_db)):
    if status == "approved":
        raise HTTPException(400, "Use /approve (requires purchasing:approve)")
    return _transition(po_id, status, user, db, ReceiveIn(warehouse_id=warehouse_id) if status == "received" else None)


@router.post("/orders/{po_id}/receive", response_model=POOut)
def receive(po_id: int, payload: ReceiveIn, user: User = Depends(require_permission("purchasing:write")), db: Session = Depends(get_db)):
    """Goods arrived: add them to stock, optionally with batch numbers and expiry dates."""
    return _transition(po_id, "received", user, db, payload)


def _transition(po_id: int, status: str, user: User, db: Session, receive_info: ReceiveIn | None = None) -> PurchaseOrder:
    po = _po(db, user.company_id, po_id)
    if status not in TRANSITIONS[po.status]:
        raise HTTPException(400, f"Cannot move from {po.status} to {status}")
    if status == "approved":
        po.approved_by_id = user.id
        po.number = po.number.replace("PR-", "PO-", 1)
    if status in ("approved", "cancelled"):
        from app.services import approvals
        approvals.resolve_for(db, "purchase_orders", po.id, "APPROVED" if status == "approved" else "CANCELLED", user)
    if status == "received":
        info = receive_info or ReceiveIn()
        wid = info.warehouse_id or po.warehouse_id
        if not wid:
            raise HTTPException(400, "warehouse_id required to receive goods")
        _warehouse(db, user.company_id, wid, user)
        lines = {ln.item_id: ln for ln in info.lines}
        for it in po.items:
            ln = lines.get(it.id)
            if ln:
                it.batch, it.expiry_date = ln.batch or "", ln.expiry_date
            # stock comes in at its real purchase cost (base currency); the costing engine updates the product's average
            apply_stock(db, user.company_id, it.product_id, wid, it.quantity, "purchase", po.number, it.batch or "", it.expiry_date,
                        unit_cost=(it.unit_cost or 0) * (po.exchange_rate or 1) if it.unit_cost else None)
        po.warehouse_id = wid
        po.received_on = date.today()
        webhooks.emit(db, user.company_id, "purchase.received", {"number": po.number, "supplier_id": po.supplier_id, "total": po.total})
        if info.supplier_invoice_no:
            po.supplier_invoice_no = info.supplier_invoice_no
    po.status = status
    db.commit()
    db.refresh(po)
    return po


# ---------------------------------------------------------------- paying suppliers
@router.get("/payments", response_model=list[SupplierPaymentOut])
def list_supplier_payments(supplier_id: int | None = None, user: User = Depends(require_permission("purchasing:read")), db: Session = Depends(get_db)):
    stmt = select(SupplierPayment).where(SupplierPayment.company_id == user.company_id)
    if supplier_id:
        stmt = stmt.where(SupplierPayment.supplier_id == supplier_id)
    return db.scalars(stmt.order_by(SupplierPayment.paid_at.desc(), SupplierPayment.id.desc()).limit(2000)).all()


def pay_supplier_core(db: Session, user: User, payload: SupplierPaymentIn) -> SupplierPayment:
    cid = user.company_id
    s = _supplier(db, cid, payload.supplier_id)
    if payload.amount <= 0:
        raise HTTPException(400, "Amount must be greater than zero")
    if payload.method not in ("cash", "bank", "card", "cheque"):
        raise HTTPException(400, f"Unknown payment method {payload.method}")
    po = _po(db, cid, payload.po_id) if payload.po_id else None
    cur = fx.normalize(db, cid, payload.currency) if payload.currency else (po.currency if po else None)
    rate = fx.rate(db, cid, cur)
    amount_po = round(payload.amount * rate / (po.exchange_rate or 1), 2) if po else None
    if po and amount_po > round(po.total - po.paid_amount, 2) + 0.01:
        raise HTTPException(400, f"Amount must be between 0 and {round((po.total - po.paid_amount) * (po.exchange_rate or 1) / rate, 2)}")
    sp = SupplierPayment(company_id=cid, number=next_number(db, SupplierPayment, cid, "PV"), supplier_id=s.id, po_id=po.id if po else None,
                         amount=round(payload.amount, 2), method=payload.method, reference=payload.reference, currency=cur, exchange_rate=rate)
    db.add(sp)
    db.flush()
    if payload.method == "cheque":
        if not payload.cheque or not payload.cheque.number or not payload.cheque.due_date:
            raise HTTPException(400, "Cheque number and due date are required")
        acc = get_account(db, cid, payload.account_id) if payload.account_id else None
        db.add(Cheque(company_id=cid, direction="out", number=payload.cheque.number, bank=payload.cheque.bank, amount=sp.amount,
                      due_date=payload.cheque.due_date, supplier_id=s.id, supplier_payment_id=sp.id, account_id=acc.id if acc else None, currency=cur))
        sp.reference = sp.reference or f"Cheque {payload.cheque.number}"
    else:
        acc = get_account(db, cid, payload.account_id, cur)
        acc_amount = round(sp.amount * rate / fx.rate(db, cid, acc.currency), 2)
        sp.account_id, sp.account_amount = acc.id, acc_amount
        post(db, cid, acc.id, -acc_amount, "supplier_payment", number=sp.number, description=po.number if po else None, reference=payload.reference,
             supplier_id=s.id, supplier_payment_id=sp.id, party_name=s.name, user_id=user.id)
    if po:
        po.paid_amount = round(po.paid_amount + amount_po, 2)
    else:
        # spread over the oldest unpaid received orders (converted through the base currency)
        remaining_base = sp.amount * rate
        for o in db.scalars(select(PurchaseOrder).where(PurchaseOrder.company_id == cid, PurchaseOrder.supplier_id == s.id,
                                                        PurchaseOrder.status.in_(("ordered", "received")), PurchaseOrder.total > PurchaseOrder.paid_amount)
                            .order_by(PurchaseOrder.order_date, PurchaseOrder.id)).all():
            if remaining_base <= 0.009:
                break
            o_rate = o.exchange_rate or 1
            part = min(round(o.total - o.paid_amount, 2), remaining_base / o_rate)
            o.paid_amount = round(o.paid_amount + part, 2)
            remaining_base = round(remaining_base - part * o_rate, 2)
    db.flush()
    return sp


@router.post("/payments", response_model=SupplierPaymentOut, status_code=201)
def pay_supplier(payload: SupplierPaymentIn, user: User = Depends(require_permission("payments:write")), db: Session = Depends(get_db)):
    sp = pay_supplier_core(db, user, payload)
    db.commit()
    db.refresh(sp)
    return sp


@router.post("/orders/{po_id}/pay", response_model=POOut)
def pay_po(po_id: int, amount: float, method: str = "cash", account_id: int | None = None, user: User = Depends(require_permission("payments:write")),
           db: Session = Depends(get_db)):
    po = _po(db, user.company_id, po_id)
    pay_supplier_core(db, user, SupplierPaymentIn(supplier_id=po.supplier_id, po_id=po.id, amount=amount, method=method, account_id=account_id))
    db.commit()
    db.refresh(po)
    return po


@router.get("/suppliers/{supplier_id}/statement")
def supplier_statement(supplier_id: int, start: date | None = None, end: date | None = None,
                       user: User = Depends(require_permission("purchasing:read")), db: Session = Depends(get_db)):
    """What we owe the supplier: received orders increase it, payments decrease it."""
    cid = user.company_id
    s = _supplier(db, cid, supplier_id)
    events = [(po.received_on or po.order_date, 0, po.number, "purchase", round(po.total * (po.exchange_rate or 1), 2), 0.0) for po in db.scalars(
        select(PurchaseOrder).where(PurchaseOrder.supplier_id == s.id, PurchaseOrder.status.in_(("ordered", "received")))).all()]
    from app.models.stock import SupplierReturn
    for sr in db.scalars(select(SupplierReturn).where(SupplierReturn.supplier_id == s.id)).all():
        events.append((sr.return_date, 1, sr.number, "supplier_return", 0.0, round(sr.total, 2)))
    for sp in db.scalars(select(SupplierPayment).where(SupplierPayment.supplier_id == s.id)).all():
        base_amt = round(sp.amount * (sp.exchange_rate or 1), 2)
        events.append((sp.paid_at, 1, sp.number, "payment", 0.0, base_amt))
        if sp.status == "bounced":
            events.append((sp.updated_at.date() if sp.updated_at else sp.paid_at, 2, sp.number, "payment_reversed", base_amt, 0.0))
    events.sort(key=lambda e: (e[0], e[1]))
    opening = s.opening_balance or 0
    rows, bal = [], opening
    for d, _o, number, kind, credit, debit in events:
        if start and d < start:
            opening = bal = round(bal + credit - debit, 2)
            continue
        if end and d > end:
            continue
        bal = round(bal + credit - debit, 2)
        rows.append({"date": d, "number": number, "kind": kind, "amount_owed": credit, "paid": debit, "balance": bal})
    return {"supplier": {"id": s.id, "name": s.name, "phone": s.phone}, "opening": round(opening, 2), "closing": bal, "rows": rows}
