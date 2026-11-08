"""Operations: approvals, price lists & promotions, stock counts, attachments, manufacturing, deliveries, field sales,
API keys & webhooks, and the company's own subscription bills."""
import mimetypes
import os
import secrets
import uuid
from datetime import date, datetime, timedelta

from fastapi import APIRouter, Depends, File, HTTPException, Response, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.api.inventory import _product, _warehouse, apply_stock, take_fefo
from app.core.config import settings
from app.core.database import get_db
from app.core.deps import get_current_user, has_permission, local_day_utc, require_permission
from app.core.security import sha256
from app.models import (
    ApiKey, Attachment, BillOfMaterials, BOMLine, Connection, Customer, Delivery, Expense, Invoice, LoginEvent, PlatformInvoice, PriceList,
    PriceListItem, Product, ProductionOrder, Promotion, SalesOrder, StockCount, StockCountLine, StockLevel, User, Visit, Webhook, WebhookDelivery,
)
from app.services import integrations as integrations_svc
from app.services import sales_ops, webhooks
from app.services.money import get_account, post
from app.services.numbering import next_number

router = APIRouter(tags=["operations"])


def _own(db: Session, model, obj_id: int, cid: int, label: str = "Record"):
    obj = db.get(model, obj_id)
    if not obj or obj.company_id != cid:
        raise HTTPException(404, f"{label} not found")
    return obj


# ================================================================ approvals
@router.get("/approvals")
def pending_approvals(user: User = Depends(require_permission("approvals:approve")), db: Session = Depends(get_db)):
    cid = user.company_id
    names = dict(db.execute(select(Customer.id, Customer.name).where(Customer.company_id == cid)).all())
    users = dict(db.execute(select(User.id, User.full_name).where(User.company_id == cid)).all())
    orders = db.scalars(select(SalesOrder).where(SalesOrder.company_id == cid, SalesOrder.status == "pending_approval").order_by(SalesOrder.id)).all()
    expenses = db.scalars(select(Expense).where(Expense.company_id == cid, Expense.approval_status == "pending").order_by(Expense.id)).all()
    return {"orders": [{"id": o.id, "number": o.number, "customer": names.get(o.customer_id), "total": o.total, "currency": o.currency,
                        "reason": o.approval_reason, "by": users.get(o.salesperson_id), "date": o.order_date} for o in orders],
            "expenses": [{"id": e.id, "category": e.category, "description": e.description, "amount": e.amount, "date": e.expense_date,
                          "by": e.requested_by} for e in expenses]}


@router.post("/approvals/expenses/{expense_id}")
def decide_expense(expense_id: int, approve: bool = True, user: User = Depends(require_permission("approvals:approve")), db: Session = Depends(get_db)):
    e = _own(db, Expense, expense_id, user.company_id, "Expense")
    if e.approval_status != "pending":
        raise HTTPException(400, "This expense is not waiting for approval")
    e.approval_status = "approved" if approve else "rejected"
    from app.services import approvals
    approvals.resolve_for(db, "expenses", e.id, "APPROVED" if approve else "REJECTED", user)
    if approve and e.is_paid:
        acc = get_account(db, user.company_id, e.account_id)
        e.account_id = acc.id
        post(db, user.company_id, acc.id, -e.amount, "expense", prefix="PV", tx_date=e.expense_date, expense_id=e.id,
             description=f"{e.category}{' - ' + e.description if e.description else ''}", user_id=user.id)
    db.commit()
    return {"status": e.approval_status}


@router.post("/approvals/orders/{order_id}/reject")
def reject_order(order_id: int, user: User = Depends(require_permission("approvals:approve")), db: Session = Depends(get_db)):
    o = _own(db, SalesOrder, order_id, user.company_id, "Order")
    if o.status != "pending_approval":
        raise HTTPException(400, "This order is not waiting for approval")
    o.status, o.approved_by = "cancelled", f"rejected by {user.full_name}"
    from app.services import approvals
    approvals.resolve_for(db, "sales_orders", o.id, "REJECTED", user)
    db.commit()
    return {"status": o.status}


# ================================================================ price lists & promotions
class PriceListIn(BaseModel):
    name: str
    discount_pct: float = 0
    is_active: bool = True
    items: list[dict] = []  # [{product_id, price}]


def _pl_out(pl: PriceList, db: Session) -> dict:
    customers = db.scalar(select(func.count(Customer.id)).where(Customer.price_list_id == pl.id)) or 0
    return {"id": pl.id, "name": pl.name, "discount_pct": pl.discount_pct, "is_active": pl.is_active, "customers": customers,
            "items": [{"product_id": i.product_id, "price": i.price} for i in pl.items]}


@router.get("/price-lists")
def price_lists(user: User = Depends(require_permission("sales:read")), db: Session = Depends(get_db)):
    return [_pl_out(p, db) for p in db.scalars(select(PriceList).where(PriceList.company_id == user.company_id).order_by(PriceList.name)).all()]


@router.post("/price-lists", status_code=201)
def create_price_list(payload: PriceListIn, user: User = Depends(require_permission("settings:write")), db: Session = Depends(get_db)):
    pl = PriceList(company_id=user.company_id, name=payload.name, discount_pct=payload.discount_pct, is_active=payload.is_active)
    db.add(pl)
    db.flush()
    _set_items(db, user.company_id, pl, payload.items)
    db.commit()
    return _pl_out(pl, db)


@router.put("/price-lists/{pl_id}")
def update_price_list(pl_id: int, payload: PriceListIn, user: User = Depends(require_permission("settings:write")), db: Session = Depends(get_db)):
    pl = _own(db, PriceList, pl_id, user.company_id, "Price list")
    pl.name, pl.discount_pct, pl.is_active = payload.name, payload.discount_pct, payload.is_active
    _set_items(db, user.company_id, pl, payload.items)
    db.commit()
    db.refresh(pl)
    return _pl_out(pl, db)


def _set_items(db: Session, cid: int, pl: PriceList, items: list[dict]) -> None:
    for old in list(pl.items):
        db.delete(old)
    db.flush()
    seen = set()
    for it in items:
        pid, price = int(it.get("product_id", 0)), it.get("price")
        if not pid or price in (None, "") or pid in seen:
            continue
        _product(db, cid, pid)
        seen.add(pid)
        db.add(PriceListItem(company_id=cid, price_list_id=pl.id, product_id=pid, price=float(price)))


class PromotionIn(BaseModel):
    name: str
    kind: str  # percent / bxgy
    product_id: int | None = None
    category: str | None = None
    percent: float = 0
    buy_qty: float = 0
    free_qty: float = 0
    starts_on: date | None = None
    ends_on: date | None = None
    is_active: bool = True


@router.get("/promotions")
def promotions(user: User = Depends(require_permission("sales:read")), db: Session = Depends(get_db)):
    return [{c: getattr(p, c) for c in ("id", "name", "kind", "product_id", "category", "percent", "buy_qty", "free_qty", "starts_on", "ends_on", "is_active")}
            for p in db.scalars(select(Promotion).where(Promotion.company_id == user.company_id).order_by(Promotion.id.desc())).all()]


@router.post("/promotions", status_code=201)
def create_promotion(payload: PromotionIn, user: User = Depends(require_permission("settings:write")), db: Session = Depends(get_db)):
    _validate_promo(db, user.company_id, payload)
    p = Promotion(company_id=user.company_id, **payload.model_dump())
    db.add(p)
    db.commit()
    return {"id": p.id}


@router.put("/promotions/{promo_id}")
def update_promotion(promo_id: int, payload: PromotionIn, user: User = Depends(require_permission("settings:write")), db: Session = Depends(get_db)):
    _validate_promo(db, user.company_id, payload)
    p = _own(db, Promotion, promo_id, user.company_id, "Promotion")
    for k, v in payload.model_dump().items():
        setattr(p, k, v)
    db.commit()
    return {"id": p.id}


def _validate_promo(db: Session, cid: int, p: PromotionIn) -> None:
    if p.kind not in ("percent", "bxgy"):
        raise HTTPException(400, "Unknown promotion type")
    if not p.product_id and not p.category:
        raise HTTPException(400, "Choose a product or a category")
    if p.product_id:
        _product(db, cid, p.product_id)
    if p.kind == "percent" and not (0 < p.percent < 100):
        raise HTTPException(400, "Percent must be between 0 and 100")
    if p.kind == "bxgy" and (p.buy_qty <= 0 or p.free_qty <= 0):
        raise HTTPException(400, "Quantities must be greater than zero")


# ================================================================ stock counts
class CountLineIn(BaseModel):
    product_id: int
    counted: float | None


def _count_out(db: Session, c: StockCount) -> dict:
    names = dict(db.execute(select(Product.id, Product.name).where(Product.company_id == c.company_id)).all())
    lines = [{"product_id": ln.product_id, "product": names.get(ln.product_id), "expected": ln.expected, "counted": ln.counted, "unit_cost": ln.unit_cost,
              "difference": None if ln.counted is None else round(ln.counted - ln.expected, 4),
              "value": None if ln.counted is None else round((ln.counted - ln.expected) * ln.unit_cost, 2)} for ln in c.lines]
    counted = [x for x in lines if x["counted"] is not None]
    return {"id": c.id, "number": c.number, "warehouse_id": c.warehouse_id, "status": c.status, "note": c.note, "created_at": c.created_at,
            "applied_at": c.applied_at, "lines": sorted(lines, key=lambda x: x["product"] or ""), "counted_lines": len(counted),
            "shortage_value": round(sum(x["value"] for x in counted if x["value"] < 0), 2), "surplus_value": round(sum(x["value"] for x in counted if x["value"] > 0), 2)}


@router.get("/stock-counts")
def stock_counts(user: User = Depends(require_permission("inventory:read")), db: Session = Depends(get_db)):
    return [{"id": c.id, "number": c.number, "warehouse_id": c.warehouse_id, "status": c.status, "created_at": c.created_at, "applied_at": c.applied_at}
            for c in db.scalars(select(StockCount).where(StockCount.company_id == user.company_id).order_by(StockCount.id.desc())).all()]


@router.post("/stock-counts", status_code=201)
def start_count(warehouse_id: int, note: str | None = None, user: User = Depends(require_permission("inventory.count")), db: Session = Depends(get_db)):
    """Snapshot what the system thinks is in the warehouse; staff then enter what they actually find."""
    wh = _warehouse(db, user.company_id, warehouse_id, user)
    c = StockCount(company_id=user.company_id, number=next_number(db, StockCount, user.company_id, "SC"), warehouse_id=wh.id, note=note, user_id=user.id)
    db.add(c)
    db.flush()
    levels = dict(db.execute(select(StockLevel.product_id, func.sum(StockLevel.quantity)).where(StockLevel.warehouse_id == wh.id)
                             .group_by(StockLevel.product_id)).all())
    for p in db.scalars(select(Product).where(Product.company_id == user.company_id, Product.is_active.is_(True))).all():
        db.add(StockCountLine(company_id=user.company_id, count_id=c.id, product_id=p.id, expected=float(levels.get(p.id, 0)), unit_cost=p.cost_price))
    db.commit()
    db.refresh(c)
    return _count_out(db, c)


@router.get("/stock-counts/{count_id}")
def get_count(count_id: int, user: User = Depends(require_permission("inventory:read")), db: Session = Depends(get_db)):
    return _count_out(db, _own(db, StockCount, count_id, user.company_id, "Stock count"))


@router.put("/stock-counts/{count_id}/lines")
def save_count_lines(count_id: int, lines: list[CountLineIn], user: User = Depends(require_permission("inventory:write")), db: Session = Depends(get_db)):
    c = _own(db, StockCount, count_id, user.company_id, "Stock count")
    if c.status != "open":
        raise HTTPException(400, "This count is already closed")
    by_product = {ln.product_id: ln for ln in c.lines}
    for ln in lines:
        row = by_product.get(ln.product_id)
        if row is None:
            p = _product(db, user.company_id, ln.product_id)
            row = StockCountLine(company_id=user.company_id, count_id=c.id, product_id=p.id, expected=0, unit_cost=p.cost_price)
            db.add(row)
        row.counted = ln.counted
    db.commit()
    db.refresh(c)
    return _count_out(db, c)


@router.post("/stock-counts/{count_id}/apply")
def apply_count(count_id: int, user: User = Depends(require_permission("inventory:write")), db: Session = Depends(get_db)):
    """Set the warehouse stock to what was counted (only lines that were counted)."""
    c = _own(db, StockCount, count_id, user.company_id, "Stock count")
    if c.status != "open":
        raise HTTPException(400, "This count is already closed")
    for ln in c.lines:
        if ln.counted is None:
            continue
        current = float(db.scalar(select(func.coalesce(func.sum(StockLevel.quantity), 0)).where(StockLevel.product_id == ln.product_id,
                                                                                                  StockLevel.warehouse_id == c.warehouse_id)) or 0)
        diff = round(ln.counted - current, 4)
        if diff > 0:
            apply_stock(db, user.company_id, ln.product_id, c.warehouse_id, diff, "adjustment", f"Stock count {c.number}")
        elif diff < 0:
            take_fefo(db, user.company_id, ln.product_id, c.warehouse_id, -diff, "adjustment", f"Stock count {c.number}")
    c.status, c.applied_at = "applied", datetime.utcnow()
    db.commit()
    db.refresh(c)
    return _count_out(db, c)


# ================================================================ attachments
ATTACHABLE = {"expense", "customer", "supplier", "purchase_order", "invoice", "sales_order", "employee", "product", "payment_proof"}


@router.get("/attachments")
def list_attachments(entity: str, entity_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return [{"id": a.id, "filename": a.filename, "size": a.size, "content_type": a.content_type, "uploaded_by": a.uploaded_by, "created_at": a.created_at}
            for a in db.scalars(select(Attachment).where(Attachment.company_id == user.company_id, Attachment.entity == entity,
                                                         Attachment.entity_id == entity_id).order_by(Attachment.id)).all()]


def _attachable_model(entity: str):
    from app.models import Employee, PaymentProof, PurchaseOrder, Supplier
    return {"expense": Expense, "customer": Customer, "supplier": Supplier, "purchase_order": PurchaseOrder, "invoice": Invoice,
            "sales_order": SalesOrder, "employee": Employee, "product": Product, "payment_proof": PaymentProof}[entity]


def save_attachment(db: Session, cid: int, entity: str, entity_id: int, filename: str, data: bytes, by: str | None) -> Attachment:
    if entity not in ATTACHABLE:
        raise HTTPException(400, "Files can't be attached here")
    _own(db, _attachable_model(entity), entity_id, cid)  # the record must exist and belong to this company
    if len(data) > 15 * 1024 * 1024:
        raise HTTPException(413, "File too large (max 15MB)")
    from app.services import saas
    saas.check_storage(db, cid, len(data))
    folder = os.path.join(settings.UPLOAD_DIR, "attachments", str(cid))
    os.makedirs(folder, exist_ok=True)
    safe = os.path.basename(filename or "file")[:120]
    path = os.path.join(folder, f"{uuid.uuid4().hex}-{safe}")
    with open(path, "wb") as f:
        f.write(data)
    a = Attachment(company_id=cid, entity=entity, entity_id=entity_id, filename=safe, path=path, size=len(data),
                   content_type=mimetypes.guess_type(safe)[0], uploaded_by=by)
    db.add(a)
    db.flush()
    return a


@router.post("/attachments", status_code=201)
async def upload_attachment(entity: str, entity_id: int, file: UploadFile = File(...), user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    a = save_attachment(db, user.company_id, entity, entity_id, file.filename or "file", await file.read(), user.full_name)
    db.commit()
    return {"id": a.id}


@router.get("/attachments/{att_id}")
def download_attachment(att_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    a = _own(db, Attachment, att_id, user.company_id, "File")
    if not os.path.exists(a.path):
        raise HTTPException(404, "File not found")
    return FileResponse(a.path, filename=a.filename, media_type=a.content_type or "application/octet-stream")


@router.delete("/attachments/{att_id}", status_code=204)
def delete_attachment(att_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    a = _own(db, Attachment, att_id, user.company_id, "File")
    if os.path.exists(a.path):
        os.remove(a.path)
    db.delete(a)
    db.commit()


# ================================================================ manufacturing
class BOMIn(BaseModel):
    product_id: int
    output_qty: float = 1
    note: str | None = None
    lines: list[dict]  # [{product_id, quantity}]


def _bom_out(db: Session, b: BillOfMaterials) -> dict:
    names = dict(db.execute(select(Product.id, Product.name).where(Product.company_id == b.company_id)).all())
    costs = dict(db.execute(select(Product.id, Product.cost_price).where(Product.company_id == b.company_id)).all())
    batch_cost = sum(ln.quantity * (costs.get(ln.product_id) or 0) for ln in b.lines)
    return {"id": b.id, "product_id": b.product_id, "product": names.get(b.product_id), "output_qty": b.output_qty, "note": b.note,
            "unit_cost": round(batch_cost / b.output_qty, 4) if b.output_qty else 0,
            "lines": [{"product_id": ln.product_id, "product": names.get(ln.product_id), "quantity": ln.quantity} for ln in b.lines]}


@router.get("/manufacturing/boms")
def boms(user: User = Depends(require_permission("inventory:read")), db: Session = Depends(get_db)):
    return [_bom_out(db, b) for b in db.scalars(select(BillOfMaterials).where(BillOfMaterials.company_id == user.company_id)).all()]


@router.post("/manufacturing/boms", status_code=201)
def create_bom(payload: BOMIn, user: User = Depends(require_permission("inventory:write")), db: Session = Depends(get_db)):
    _product(db, user.company_id, payload.product_id)
    lines = [ln for ln in payload.lines if ln.get("product_id") and float(ln.get("quantity") or 0) > 0]
    if not lines or payload.output_qty <= 0:
        raise HTTPException(400, "Add at least one component")
    if any(int(ln["product_id"]) == payload.product_id for ln in lines):
        raise HTTPException(400, "A product can't be a component of itself")
    b = BillOfMaterials(company_id=user.company_id, product_id=payload.product_id, output_qty=payload.output_qty, note=payload.note)
    db.add(b)
    db.flush()
    for ln in lines:
        _product(db, user.company_id, int(ln["product_id"]))
        db.add(BOMLine(company_id=user.company_id, bom_id=b.id, product_id=int(ln["product_id"]), quantity=float(ln["quantity"])))
    db.commit()
    db.refresh(b)
    return _bom_out(db, b)


@router.get("/manufacturing/orders")
def production_orders(user: User = Depends(require_permission("inventory:read")), db: Session = Depends(get_db)):
    names = dict(db.execute(select(Product.id, Product.name).where(Product.company_id == user.company_id)).all())
    return [{"id": p.id, "number": p.number, "bom_id": p.bom_id, "product": names.get(p.product_id), "quantity": p.quantity, "warehouse_id": p.warehouse_id,
             "status": p.status, "unit_cost": p.unit_cost, "done_at": p.done_at, "created_at": p.created_at}
            for p in db.scalars(select(ProductionOrder).where(ProductionOrder.company_id == user.company_id).order_by(ProductionOrder.id.desc())).all()]


@router.post("/manufacturing/orders", status_code=201)
def produce(bom_id: int, quantity: float, warehouse_id: int, user: User = Depends(require_permission("inventory:write")), db: Session = Depends(get_db)):
    """Make `quantity` units now: components leave the warehouse (earliest expiry first), the finished product comes in at their cost."""
    b = _own(db, BillOfMaterials, bom_id, user.company_id, "Recipe")
    wh = _warehouse(db, user.company_id, warehouse_id, user)
    if quantity <= 0:
        raise HTTPException(400, "Quantities must be greater than zero")
    po = ProductionOrder(company_id=user.company_id, number=next_number(db, ProductionOrder, user.company_id, "MO"), bom_id=b.id, product_id=b.product_id,
                         quantity=quantity, warehouse_id=wh.id)
    db.add(po)
    db.flush()
    factor = quantity / b.output_qty
    total_cost = 0.0
    from app.api.inventory import take_stock
    for ln in b.lines:  # components leave at their real cost (FIFO / average)
        _taken, cost = take_stock(db, user.company_id, ln.product_id, wh.id, round(ln.quantity * factor, 4), "production_out", po.number)
        total_cost += cost
    po.unit_cost = round(total_cost / quantity, 4)
    # the finished product comes in at the cost of its components; the costing engine keeps its average
    apply_stock(db, user.company_id, b.product_id, wh.id, quantity, "production_in", po.number, unit_cost=po.unit_cost)
    po.status, po.done_at = "done", datetime.utcnow()
    db.commit()
    return {"id": po.id, "number": po.number, "unit_cost": po.unit_cost}


# ================================================================ deliveries
class DeliveryIn(BaseModel):
    order_id: int
    driver_id: int | None = None
    address: str | None = None
    scheduled_for: date | None = None
    note: str | None = None


class DeliveryUpdate(BaseModel):
    status: str
    received_by: str | None = None
    cash_collected: float = 0
    note: str | None = None


def _del_out(db: Session, d: Delivery) -> dict:
    o = db.get(SalesOrder, d.order_id)
    c = db.get(Customer, o.customer_id) if o else None
    drv = db.get(User, d.driver_id) if d.driver_id else None
    return {"id": d.id, "order_id": d.order_id, "order_number": o.number if o else None, "total": o.total if o else None, "customer": c.name if c else None,
            "phone": c.phone if c else None, "address": d.address or (c.address if c else None), "driver_id": d.driver_id, "driver": drv.full_name if drv else None,
            "status": d.status, "scheduled_for": d.scheduled_for, "delivered_at": d.delivered_at, "received_by": d.received_by,
            "cash_collected": d.cash_collected, "amount_due": d.amount_due, "note": d.note}


@router.get("/deliveries")
def deliveries(mine: bool = False, status: str | None = None, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    stmt = select(Delivery).where(Delivery.company_id == user.company_id)
    if mine or not has_permission(user, "sales:read"):
        stmt = stmt.where(Delivery.driver_id == user.id)
    if status:
        stmt = stmt.where(Delivery.status.in_(status.split(",")))
    return [_del_out(db, d) for d in db.scalars(stmt.order_by(Delivery.scheduled_for.is_(None), Delivery.scheduled_for, Delivery.id.desc()).limit(500)).all()]


@router.post("/deliveries", status_code=201)
def create_delivery(payload: DeliveryIn, user: User = Depends(require_permission("sales:write")), db: Session = Depends(get_db)):
    o = _own(db, SalesOrder, payload.order_id, user.company_id, "Order")
    if payload.driver_id:
        _own(db, User, payload.driver_id, user.company_id, "Driver")
    d = Delivery(company_id=user.company_id, **payload.model_dump())
    d.address = d.address or (db.get(Customer, o.customer_id).address)
    db.add(d)
    db.commit()
    return _del_out(db, d)


@router.post("/deliveries/{delivery_id}/status")
def delivery_status(delivery_id: int, payload: DeliveryUpdate, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """The driver (or office) updates the delivery. Cash collected on delivery is recorded as a payment on the order's invoice."""
    d = _own(db, Delivery, delivery_id, user.company_id, "Delivery")
    if d.driver_id != user.id and not has_permission(user, "sales:write"):
        raise HTTPException(403, "This delivery isn't assigned to you")
    if payload.status not in ("assigned", "out", "delivered", "failed", "returned"):
        raise HTTPException(400, "Unknown status")
    d.status, d.note = payload.status, payload.note or d.note
    o = db.get(SalesOrder, d.order_id)
    if payload.status == "delivered":
        d.delivered_at, d.received_by = datetime.utcnow(), payload.received_by
        if o and o.status == "confirmed":
            o.status = "delivered"
        if payload.cash_collected > 0:
            from app.services.sales_ops import invoice_for_order, pay_invoice
            inv = db.scalar(select(Invoice).where(Invoice.order_id == d.order_id, Invoice.status != "cancelled")) or invoice_for_order(db, user.company_id, o, 0)
            pay_invoice(db, user, inv, payload.cash_collected, "cash", f"Delivery {d.id}")
            d.cash_collected = payload.cash_collected
        d.amount_due = round(max((o.total if o else 0) - d.cash_collected, 0), 2)
        webhooks.emit(db, user.company_id, "delivery.completed", {"id": d.id, "order_number": o.number if o else None,
                                                                   "cash_collected": d.cash_collected, "amount_due": d.amount_due})
    elif payload.status == "returned":
        # the driver brought some or all of the order back — no cash to collect, nothing owed by the customer for it.
        # stock isn't put back automatically: office reviews the returned goods (condition may vary) and records a
        # proper return from the order/customer return screen, which values stock correctly (good/damaged/expired).
        d.delivered_at = datetime.utcnow()
        d.cash_collected, d.amount_due = 0, 0
    db.commit()
    return _del_out(db, d)


# ================================================================ field sales (reps)
VISIT_OUTCOMES = ("visited", "ordered", "collected", "no_answer", "closed", "not_interested")


class VisitIn(BaseModel):
    customer_id: int
    outcome: str = "visited"
    note: str | None = None
    lat: float | None = None
    lng: float | None = None
    order_id: int | None = None
    amount_collected: float = 0


@router.get("/field/today")
def field_today(user: User = Depends(require_permission("customers:read")), db: Session = Depends(get_db)):
    """The rep's route for today: their customers scheduled for this weekday, with balance and whether they were visited."""
    from app.services.company_tz import company_today, company_tz
    from app.services.analytics import INVOICE_BALANCE_BASE, OPEN_INVOICE
    today = company_today(db, user.company_id)
    wd = str(today.weekday())
    custs = db.scalars(select(Customer).where(Customer.company_id == user.company_id, Customer.assigned_user_id == user.id)).all()
    start, _end = local_day_utc(today, company_tz(db, user.company_id))
    visited = {v.customer_id: v.outcome for v in db.scalars(select(Visit).where(Visit.user_id == user.id, Visit.visited_at >= start)).all()}
    bal = dict(db.execute(select(Invoice.customer_id, func.sum(INVOICE_BALANCE_BASE)).where(Invoice.company_id == user.company_id,
                                                                                           Invoice.status.in_(OPEN_INVOICE)).group_by(Invoice.customer_id)).all())
    rows = [{"id": c.id, "name": c.name, "phone": c.phone, "address": c.address, "lat": c.lat, "lng": c.lng, "balance": round(float(bal.get(c.id, 0) or 0), 2),
             "scheduled": wd in (c.visit_days or "").split(","), "visited": visited.get(c.id)} for c in custs]
    return sorted(rows, key=lambda r: (not r["scheduled"], r["visited"] is not None, r["name"]))


@router.post("/field/visits", status_code=201)
def log_visit(payload: VisitIn, user: User = Depends(require_permission("customers:read")), db: Session = Depends(get_db)):
    if payload.outcome not in VISIT_OUTCOMES:
        raise HTTPException(400, "Unknown visit outcome")
    _own(db, Customer, payload.customer_id, user.company_id, "Customer")
    data = payload.model_dump(exclude={"amount_collected"})
    if not has_permission(user, "field.track_location"):
        # the rep didn't opt in (or wasn't granted the right) — location is never recorded without it, even if the
        # phone sent coordinates
        data["lat"] = data["lng"] = None
    v = Visit(company_id=user.company_id, user_id=user.id, visited_at=datetime.utcnow(), **data)
    db.add(v)
    c = db.get(Customer, payload.customer_id)
    if data["lat"] and data["lng"] and not c.lat:
        c.lat, c.lng = data["lat"], data["lng"]
    pay = None
    if payload.amount_collected > 0:
        if not has_permission(user, "field.collect_payment"):
            raise HTTPException(403, "You are not allowed to collect payments")
        pays = sales_ops.receive_from_customer(db, user, payload.customer_id, payload.amount_collected, "cash", f"Visit {v.id}", None, None)
        pay = pays[0].number if pays else None
    db.commit()
    return {"id": v.id, "payment": pay}


@router.get("/field/visits")
def visits(user_id: int | None = None, days: int = 7, user: User = Depends(require_permission("customers:read")), db: Session = Depends(get_db)):
    stmt = select(Visit).where(Visit.company_id == user.company_id, Visit.visited_at >= datetime.utcnow() - timedelta(days=days))
    if user_id or not has_permission(user, "reports:read"):
        stmt = stmt.where(Visit.user_id == (user_id or user.id))
    names = dict(db.execute(select(Customer.id, Customer.name).where(Customer.company_id == user.company_id)).all())
    users = dict(db.execute(select(User.id, User.full_name).where(User.company_id == user.company_id)).all())
    return [{"id": v.id, "customer": names.get(v.customer_id), "customer_id": v.customer_id, "user": users.get(v.user_id), "at": v.visited_at,
             "outcome": v.outcome, "note": v.note, "lat": v.lat, "lng": v.lng, "order_id": v.order_id}
            for v in db.scalars(stmt.order_by(Visit.visited_at.desc()).limit(500)).all()]


# ================================================================ API keys & webhooks
class ApiKeyIn(BaseModel):
    name: str
    scopes: list[str] = []  # empty = the key acts with all of the creating user's own permissions
    expires_days: int | None = None  # None = never expires
    rate_limit_per_min: int = 120


class WebhookIn(BaseModel):
    url: str
    events: list[str]
    is_active: bool = True


@router.get("/integrations")
def integrations(user: User = Depends(require_permission("settings:write")), db: Session = Depends(get_db)):
    keys = db.scalars(select(ApiKey).where(ApiKey.company_id == user.company_id).order_by(ApiKey.id.desc())).all()
    hooks = db.scalars(select(Webhook).where(Webhook.company_id == user.company_id).order_by(Webhook.id.desc())).all()
    recent = db.scalars(select(WebhookDelivery).where(WebhookDelivery.company_id == user.company_id).order_by(WebhookDelivery.id.desc()).limit(30)).all()
    conns = db.scalars(select(Connection).where(Connection.company_id == user.company_id)).all()
    return {"events": webhooks.EVENTS,
            "keys": [{"id": k.id, "name": k.name, "prefix": k.prefix, "is_active": k.is_active, "last_used_at": k.last_used_at, "created_at": k.created_at,
                     "scopes": k.scopes, "expires_at": k.expires_at, "rate_limit_per_min": k.rate_limit_per_min, "request_count": k.request_count,
                     "expired": bool(k.expires_at and k.expires_at < datetime.utcnow())} for k in keys],
            "webhooks": [{"id": h.id, "url": h.url, "events": h.events, "is_active": h.is_active, "secret": h.secret} for h in hooks],
            "deliveries": [{"id": d.id, "event": d.event, "status": d.status, "response_code": d.response_code, "attempts": d.attempts, "created_at": d.created_at}
                           for d in recent],
            "connections": [{"id": c.id, "provider": c.provider, "config": c.config, "is_active": c.is_active, "connected": bool(c.secret),
                             "last_used_at": c.last_used_at, "last_error": c.last_error} for c in conns]}


class ConnectionIn(BaseModel):
    provider: str
    config: dict = {}
    secret: str | None = None  # omit to keep the existing secret (e.g. when only changing config)
    is_active: bool = True


PROVIDERS = ("whatsapp",)


@router.put("/integrations/connections/{provider}")
def upsert_connection(provider: str, payload: ConnectionIn, user: User = Depends(require_permission("settings:write")), db: Session = Depends(get_db)):
    """One connection per provider per company. Re-saving without a new secret keeps the one already stored."""
    if provider not in PROVIDERS:
        raise HTTPException(400, f"Unknown provider. Supported: {', '.join(PROVIDERS)}")
    c = db.scalar(select(Connection).where(Connection.company_id == user.company_id, Connection.provider == provider))
    if not c:
        c = Connection(company_id=user.company_id, provider=provider)
        db.add(c)
    c.config, c.is_active = payload.config, payload.is_active
    if payload.secret:
        c.secret, c.last_error = payload.secret, None
    db.commit()
    return {"id": c.id, "provider": c.provider, "config": c.config, "is_active": c.is_active, "connected": bool(c.secret)}


@router.delete("/integrations/connections/{provider}", status_code=204)
def delete_connection(provider: str, user: User = Depends(require_permission("settings:write")), db: Session = Depends(get_db)):
    c = db.scalar(select(Connection).where(Connection.company_id == user.company_id, Connection.provider == provider))
    if c:
        db.delete(c)
        db.commit()


@router.post("/integrations/connections/{provider}/test")
def test_connection(provider: str, phone: str = "", user: User = Depends(require_permission("settings:write")), db: Session = Depends(get_db)):
    if provider != "whatsapp":
        raise HTTPException(400, "Nothing to test for this provider yet")
    if not phone:
        raise HTTPException(400, "Give a phone number to send the test message to")
    ok = integrations_svc.whatsapp_send(db, user.company_id, phone, "Test message from BizOS. Your WhatsApp connection works.")
    c = db.scalar(select(Connection).where(Connection.company_id == user.company_id, Connection.provider == provider))
    return {"sent": ok, "error": c.last_error if c and not ok else None}


@router.get("/integrations/keys/scopes")
def key_scopes(user: User = Depends(require_permission("settings:write"))):
    """Coarse permissions a key's scope can be limited to (on top of whatever the creating user is themselves allowed)."""
    from app.core.permissions import LEGACY
    return sorted(LEGACY.keys())


@router.post("/integrations/keys", status_code=201)
def create_key(payload: ApiKeyIn, user: User = Depends(require_permission("settings:write")), db: Session = Depends(get_db)):
    """The full key is shown only once. It acts with the permissions of the user who created it, narrowed further by
    `scopes` if given (a key can only ever do less than its owner, never more)."""
    from app.core.permissions import LEGACY
    bad = [s for s in payload.scopes if s not in LEGACY]
    if bad:
        raise HTTPException(400, f"Unknown scope(s): {', '.join(bad)}")
    if payload.rate_limit_per_min < 1 or payload.rate_limit_per_min > 6000:
        raise HTTPException(400, "Rate limit must be between 1 and 6000 requests/minute")
    raw = "bos_" + secrets.token_urlsafe(32)
    expires = datetime.utcnow() + timedelta(days=payload.expires_days) if payload.expires_days else None
    k = ApiKey(company_id=user.company_id, name=payload.name, prefix=raw[:10], key_hash=sha256(raw), user_id=user.id,
              scopes=payload.scopes, expires_at=expires, rate_limit_per_min=payload.rate_limit_per_min)
    db.add(k)
    db.commit()
    return {"id": k.id, "key": raw}


@router.delete("/integrations/keys/{key_id}", status_code=204)
def revoke_key(key_id: int, user: User = Depends(require_permission("settings:write")), db: Session = Depends(get_db)):
    k = _own(db, ApiKey, key_id, user.company_id, "Key")
    k.is_active = False
    db.commit()


@router.post("/integrations/webhooks", status_code=201)
def create_webhook(payload: WebhookIn, user: User = Depends(require_permission("settings:write")), db: Session = Depends(get_db)):
    if not payload.url.startswith(("https://", "http://")):
        raise HTTPException(400, "The address must start with https://")
    h = Webhook(company_id=user.company_id, url=payload.url, events=payload.events or ["*"], is_active=payload.is_active, secret=secrets.token_hex(16))
    db.add(h)
    db.commit()
    return {"id": h.id, "secret": h.secret}


@router.delete("/integrations/webhooks/{hook_id}", status_code=204)
def delete_webhook(hook_id: int, user: User = Depends(require_permission("settings:write")), db: Session = Depends(get_db)):
    db.delete(_own(db, Webhook, hook_id, user.company_id, "Webhook"))
    db.commit()


@router.post("/integrations/webhooks/{hook_id}/test")
def test_webhook(hook_id: int, user: User = Depends(require_permission("settings:write")), db: Session = Depends(get_db)):
    h = _own(db, Webhook, hook_id, user.company_id, "Webhook")
    db.add(WebhookDelivery(company_id=user.company_id, webhook_id=h.id, event="test", next_attempt_at=datetime.utcnow(),
                           payload={"event": "test", "company_id": user.company_id, "data": {"hello": "world"}}))
    db.commit()
    webhooks.deliver_pending(db)
    d = db.scalar(select(WebhookDelivery).where(WebhookDelivery.webhook_id == h.id).order_by(WebhookDelivery.id.desc()))
    return {"status": d.status, "response_code": d.response_code}


# ================================================================ security (company admins) & subscription bills
@router.get("/security/logins")
def company_logins(user: User = Depends(require_permission("users:write")), db: Session = Depends(get_db)):
    rows = db.scalars(select(LoginEvent).where(LoginEvent.company_id == user.company_id).order_by(LoginEvent.id.desc()).limit(300)).all()
    return [{"at": r.created_at, "email": r.email, "success": r.success, "reason": r.reason, "ip": r.ip, "user_agent": r.user_agent} for r in rows]


@router.post("/users/{user_id}/logout-all", status_code=204)
def force_logout(user_id: int, user: User = Depends(require_permission("users:write")), db: Session = Depends(get_db)):
    u = _own(db, User, user_id, user.company_id, "User")
    u.token_version = (u.token_version or 0) + 1
    db.commit()


@router.get("/billing")
def my_bills(user: User = Depends(require_permission("settings:write")), db: Session = Depends(get_db)):
    return [{"number": i.number, "period": i.period, "plan_name": i.plan_name, "amount": i.amount, "due_date": i.due_date, "status": i.status, "paid_at": i.paid_at}
            for i in db.scalars(select(PlatformInvoice).where(PlatformInvoice.company_id == user.company_id).order_by(PlatformInvoice.id.desc())).all()]
