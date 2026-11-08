"""Warehouse transfers: DRAFT → REQUESTED → APPROVED → IN_TRANSIT → RECEIVED (or CANCELLED).

APPROVED reserves the stock at the source (it leaves "available" at its cost); IN_TRANSIT moves the reservation to
the destination's in-transit stock; RECEIVED makes it available at the destination at the same cost. Received less
than shipped → the shortfall is written off. Cancelling returns reserved / in-transit stock to the source.
"""
from datetime import datetime

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.core.deps import check_warehouse, has_permission
from app.models import User
from app.models.stock import StockTransfer, StockTransferLine
from app.services import stock_states
from app.services.numbering import next_number

FLOW = {"DRAFT": {"REQUESTED", "CANCELLED"}, "REQUESTED": {"APPROVED", "CANCELLED", "DRAFT"}, "APPROVED": {"IN_TRANSIT", "CANCELLED"},
        "IN_TRANSIT": {"RECEIVED", "CANCELLED"}, "RECEIVED": set(), "CANCELLED": set()}


def _step(t: StockTransfer, to: str) -> None:
    if to not in FLOW[t.status]:
        raise HTTPException(400, f"A {t.status.lower().replace('_', ' ')} transfer can't become {to.lower().replace('_', ' ')}")


def create(db: Session, user: User, from_wh: int, to_wh: int, lines: list[dict], note: str | None) -> StockTransfer:
    from app.api.inventory import _product, _warehouse
    if from_wh == to_wh:
        raise HTTPException(400, "Choose two different warehouses")
    _warehouse(db, user.company_id, from_wh, user)
    _warehouse(db, user.company_id, to_wh)
    clean = [ln for ln in lines if ln.get("product_id") and float(ln.get("quantity") or 0) > 0]
    if not clean:
        raise HTTPException(400, "Add at least one product with a quantity above zero")
    t = StockTransfer(company_id=user.company_id, number=next_number(db, StockTransfer, user.company_id, "ST"), from_warehouse_id=from_wh,
                      to_warehouse_id=to_wh, note=note, requested_by=user.full_name)
    db.add(t)
    db.flush()
    for ln in clean:
        _product(db, user.company_id, int(ln["product_id"]))
        db.add(StockTransferLine(company_id=user.company_id, transfer_id=t.id, product_id=int(ln["product_id"]), quantity=float(ln["quantity"]),
                                 batch=ln.get("batch") or ""))
    db.flush()
    db.refresh(t)
    return t


def submit(db: Session, user: User, t: StockTransfer) -> StockTransfer:
    _step(t, "REQUESTED")
    t.status = "REQUESTED"
    from app.services import notify
    notify.send(db, t.company_id, "approval_request", f"Transfer {t.number} waits for approval", t.note or "", link="/transfers",
                dedupe=f"transfer-req:{t.id}", permission="inventory.approve_adjustment")
    return t


def approve(db: Session, user: User, t: StockTransfer) -> StockTransfer:
    """Reserve the stock at the source: it stops being available there."""
    from app.api.inventory import take_stock
    if not (has_permission(user, "inventory.approve_adjustment") or has_permission(user, "approvals.approve")):
        raise HTTPException(403, "Missing permission(s): inventory.approve_adjustment")
    _step(t, "APPROVED")
    for ln in t.lines:
        taken, cost = take_stock(db, t.company_id, ln.product_id, t.from_warehouse_id, ln.quantity, "transfer_reserve", t.number,
                                 t.to_warehouse_id, ln.batch or None)
        for b, e, q, unit in taken:
            stock_states.to_bucket(db, t.company_id, ln.product_id, t.from_warehouse_id, "reserved", q, unit, b, e)
        ln.unit_cost = round(cost / ln.quantity, 6) if ln.quantity else 0
    t.status, t.approved_by = "APPROVED", user.full_name
    return t


def ship(db: Session, user: User, t: StockTransfer) -> StockTransfer:
    check_warehouse(user, t.from_warehouse_id)
    _step(t, "IN_TRANSIT")
    for ln in t.lines:
        for b, e, q, unit in stock_states.from_bucket(db, t.company_id, ln.product_id, t.from_warehouse_id, "reserved", ln.quantity, ln.batch or None):
            stock_states.to_bucket(db, t.company_id, ln.product_id, t.to_warehouse_id, "in_transit", q, unit, b, e)
    t.status, t.shipped_at = "IN_TRANSIT", datetime.utcnow()
    return t


def receive(db: Session, user: User, t: StockTransfer, received: dict[int, float] | None = None) -> StockTransfer:
    """Destination confirms what arrived (default: everything). Only now it's available there."""
    from app.api.inventory import _movement, apply_stock
    check_warehouse(user, t.to_warehouse_id)
    _step(t, "RECEIVED")
    for ln in t.lines:
        got = ln.quantity if not received or ln.id not in received else max(0.0, min(float(received[ln.id]), ln.quantity))
        chunks = stock_states.from_bucket(db, t.company_id, ln.product_id, t.to_warehouse_id, "in_transit", ln.quantity, ln.batch or None)
        left = got
        for b, e, q, unit in chunks:
            use = min(q, left)
            if use > 0:
                apply_stock(db, t.company_id, ln.product_id, t.to_warehouse_id, use, "transfer_in", t.number, b, e, unit_cost=unit)
            if q - use > 1e-9:  # shortfall: lost on the way → written off
                _movement(db, t.company_id, ln.product_id, t.to_warehouse_id, -(q - use), "transfer_loss", t.number, b, unit_cost=unit)
            left -= use
        ln.received_quantity = got
    t.status, t.received_at, t.received_by = "RECEIVED", datetime.utcnow(), user.full_name
    return t


def cancel(db: Session, user: User, t: StockTransfer) -> StockTransfer:
    from app.api.inventory import apply_stock
    _step(t, "CANCELLED")
    state, wh = {"APPROVED": ("reserved", t.from_warehouse_id), "IN_TRANSIT": ("in_transit", t.to_warehouse_id)}.get(t.status, (None, None))
    if state:
        for ln in t.lines:
            for b, e, q, unit in stock_states.from_bucket(db, t.company_id, ln.product_id, wh, state, ln.quantity, ln.batch or None):
                apply_stock(db, t.company_id, ln.product_id, t.from_warehouse_id, q, "transfer_cancel", t.number, b, e, unit_cost=unit)
    t.status = "CANCELLED"
    return t


def out(db: Session, t: StockTransfer) -> dict:
    from sqlalchemy import select
    from app.models import Product, Warehouse
    names = dict(db.execute(select(Product.id, Product.name).where(Product.company_id == t.company_id)).all())
    whs = dict(db.execute(select(Warehouse.id, Warehouse.name).where(Warehouse.company_id == t.company_id)).all())
    return {"id": t.id, "number": t.number, "status": t.status, "from_warehouse_id": t.from_warehouse_id, "from_warehouse": whs.get(t.from_warehouse_id),
            "to_warehouse_id": t.to_warehouse_id, "to_warehouse": whs.get(t.to_warehouse_id), "note": t.note, "requested_by": t.requested_by,
            "approved_by": t.approved_by, "shipped_at": t.shipped_at, "received_at": t.received_at, "received_by": t.received_by, "created_at": t.created_at,
            "lines": [{"id": ln.id, "product_id": ln.product_id, "product": names.get(ln.product_id), "batch": ln.batch, "quantity": ln.quantity,
                       "received_quantity": ln.received_quantity, "unit_cost": ln.unit_cost} for ln in t.lines],
            "value": round(sum(ln.quantity * (ln.unit_cost or 0) for ln in t.lines), 2)}
