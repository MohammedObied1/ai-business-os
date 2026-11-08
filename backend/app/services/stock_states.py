"""Stock that isn't available: reserved, in transit, damaged, expired.

Moving available stock into damaged / expired writes its cost off (ledger: stock adjustments expense ← inventory).
Restoring it (repaired, found) brings the value back; disposing of written-off stock has no further cost.
Reserved / in-transit stock is still an asset: it's part of the inventory valuation.
"""
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.stock import StockBucket

WRITE_OFF_STATES = {"damaged", "expired"}
STATES = {"reserved", "in_transit", "damaged", "expired"}


def to_bucket(db: Session, cid: int, product_id: int, warehouse_id: int, state: str, qty: float, unit_cost: float,
              batch: str = "", expiry=None) -> StockBucket:
    if state not in STATES:
        raise HTTPException(400, "Unknown stock state")
    b = db.scalar(select(StockBucket).where(StockBucket.warehouse_id == warehouse_id, StockBucket.product_id == product_id,
                                            StockBucket.batch == (batch or ""), StockBucket.state == state))
    if not b:
        b = StockBucket(company_id=cid, product_id=product_id, warehouse_id=warehouse_id, batch=batch or "", state=state, quantity=0, unit_cost=0,
                        expiry_date=expiry)
        db.add(b)
    total = (b.quantity or 0) * (b.unit_cost or 0) + qty * unit_cost
    b.quantity = round((b.quantity or 0) + qty, 4)
    b.unit_cost = round(total / b.quantity, 6) if b.quantity else unit_cost
    if expiry and not b.expiry_date:
        b.expiry_date = expiry
    return b


def from_bucket(db: Session, cid: int, product_id: int, warehouse_id: int, state: str, qty: float, batch: str | None = None) -> list[tuple[str, object, float, float]]:
    """Take qty out of a state (a batch, or any). Returns [(batch, expiry, qty, unit_cost)]."""
    stmt = select(StockBucket).where(StockBucket.company_id == cid, StockBucket.warehouse_id == warehouse_id, StockBucket.product_id == product_id,
                                     StockBucket.state == state, StockBucket.quantity > 0)
    if batch is not None:
        stmt = stmt.where(StockBucket.batch == batch)
    buckets = db.scalars(stmt.order_by(StockBucket.expiry_date.is_(None), StockBucket.expiry_date, StockBucket.id)).all()
    have = round(sum(b.quantity for b in buckets), 4)
    if have + 1e-9 < qty:
        raise HTTPException(400, f"Not enough {state.replace('_', ' ')} stock (have {have:g}, need {qty:g})")
    out, left = [], qty
    for b in buckets:
        if left <= 1e-9:
            break
        t = min(b.quantity, left)
        b.quantity = round(b.quantity - t, 4)
        left -= t
        out.append((b.batch, b.expiry_date, t, b.unit_cost))
    return out


def mark(db: Session, cid: int, product_id: int, warehouse_id: int, qty: float, state: str, reference: str | None, batch: str | None = None) -> float:
    """Available → damaged / expired (written off). Returns the cost written off."""
    from app.api.inventory import take_stock
    if state not in WRITE_OFF_STATES:
        raise HTTPException(400, "Stock can only be marked damaged or expired")
    taken, cost = take_stock(db, cid, product_id, warehouse_id, qty, state, reference, batch=batch)
    for b, e, q, unit in taken:
        to_bucket(db, cid, product_id, warehouse_id, state, q, unit, b, e)
    return cost


def restore(db: Session, cid: int, product_id: int, warehouse_id: int, qty: float, state: str, reference: str | None, batch: str | None = None) -> float:
    """Damaged / expired → available again (repaired, found fine). The written-off value comes back."""
    from app.api.inventory import apply_stock
    if state not in WRITE_OFF_STATES:
        raise HTTPException(400, "Only damaged or expired stock can be restored")
    total = 0.0
    for b, e, q, unit in from_bucket(db, cid, product_id, warehouse_id, state, qty, batch):
        total += apply_stock(db, cid, product_id, warehouse_id, q, "restore", reference, b, e, unit_cost=unit)
    return total


def dispose(db: Session, cid: int, product_id: int, warehouse_id: int, qty: float, state: str, reference: str | None, batch: str | None = None) -> None:
    """Throw away damaged / expired stock (already written off: no further cost)."""
    from app.api.inventory import _movement
    if state not in WRITE_OFF_STATES:
        raise HTTPException(400, "Only damaged or expired stock can be disposed of")
    for b, _e, q, _unit in from_bucket(db, cid, product_id, warehouse_id, state, qty, batch):
        _movement(db, cid, product_id, warehouse_id, 0, f"disposed_{state}", f"{reference or ''} ({q:g})".strip(), b, unit_cost=0)
