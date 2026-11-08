"""Inventory costing: weighted average (default) or FIFO; batches give specific cost.

Every stock inflow opens a cost layer (quantity + unit cost, per warehouse and batch). Outflows consume layers:
- FIFO: the oldest layers of that warehouse first (the batch that was taken first, if any → specific cost);
- average: the product's running weighted-average cost, while layers are still consumed FIFO so a later switch
  to FIFO starts from correct quantities.
Stock that existed before layers were kept (no layer) is valued at the product's cost price.
`Product.cost_price` always shows the current average cost of what is on hand.
"""
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Company, Product, StockLevel
from app.models.stock import CostLayer


def method(db: Session, cid: int) -> str:
    return getattr(db.get(Company, cid), "costing_method", None) or "average"


def _on_hand(db: Session, product_id: int) -> float:
    db.flush()  # the session doesn't autoflush: earlier moves in this same request must count
    return float(db.scalar(select(func.coalesce(func.sum(StockLevel.quantity), 0)).where(StockLevel.product_id == product_id)) or 0)


def receive(db: Session, cid: int, product: Product, warehouse_id: int, qty: float, unit_cost: float | None, batch: str = "",
            movement_id: int | None = None) -> float:
    """Stock came in (call BEFORE the stock level is raised). Returns the unit cost used."""
    cost = (product.cost_price or 0) if unit_cost is None else float(unit_cost)
    before = _on_hand(db, product.id)
    db.add(CostLayer(company_id=cid, product_id=product.id, warehouse_id=warehouse_id, batch=batch or "", received_at=datetime.utcnow(),
                     qty_in=qty, qty_remaining=qty, unit_cost=round(cost, 6), movement_id=movement_id))
    if before > 0 and product.cost_price is not None:
        product.cost_price = round((before * (product.cost_price or 0) + qty * cost) / (before + qty), 4)
    else:
        product.cost_price = round(cost, 4)
    return cost


def issue(db: Session, cid: int, product: Product, warehouse_id: int, qty: float, batch: str | None = None) -> float:
    """Stock went out: consume layers and return the TOTAL cost of `qty` under the company's method."""
    db.flush()
    layers = db.scalars(select(CostLayer).where(CostLayer.product_id == product.id, CostLayer.warehouse_id == warehouse_id,
                                                CostLayer.qty_remaining > 0)
                        .order_by((CostLayer.batch != (batch or "")) if batch else CostLayer.id, CostLayer.received_at, CostLayer.id)).all()
    remaining, fifo_cost = qty, 0.0
    for layer in layers:
        if remaining <= 1e-9:
            break
        take = min(layer.qty_remaining, remaining)
        layer.qty_remaining = round(layer.qty_remaining - take, 6)
        fifo_cost += take * layer.unit_cost
        remaining -= take
    if remaining > 1e-9:  # stock from before cost layers existed
        fifo_cost += remaining * (product.cost_price or 0)
    if method(db, cid) == "fifo":
        return round(fifo_cost, 4)
    return round(qty * (product.cost_price or 0), 4)


def refresh_average(db: Session, product: Product) -> None:
    """FIFO mode: show the average cost of the layers still on hand."""
    db.flush()
    q, v = db.execute(select(func.coalesce(func.sum(CostLayer.qty_remaining), 0), func.coalesce(func.sum(CostLayer.qty_remaining * CostLayer.unit_cost), 0))
                      .where(CostLayer.product_id == product.id, CostLayer.qty_remaining > 0)).one()
    if q and q > 0:
        product.cost_price = round(float(v) / float(q), 4)


def valuation(db: Session, cid: int) -> float:
    """Value of everything on hand under the company's method: available stock + reserved + in transit
    (damaged / expired stock is written off, so it isn't counted)."""
    db.flush()
    from app.models.stock import StockBucket
    held = float(db.scalar(select(func.coalesce(func.sum(StockBucket.quantity * StockBucket.unit_cost), 0)).where(
        StockBucket.company_id == cid, StockBucket.state.in_(("reserved", "in_transit")))) or 0)
    return round(_available_value(db, cid) + held, 2)


def _available_value(db: Session, cid: int) -> float:
    if method(db, cid) != "fifo":
        return float(db.scalar(select(func.coalesce(func.sum(StockLevel.quantity * Product.cost_price), 0))
                               .join(Product, Product.id == StockLevel.product_id).where(StockLevel.company_id == cid)) or 0)
    stock = dict(db.execute(select(StockLevel.product_id, func.sum(StockLevel.quantity)).where(StockLevel.company_id == cid)
                            .group_by(StockLevel.product_id)).all())
    layered = {pid: (float(q), float(v)) for pid, q, v in db.execute(
        select(CostLayer.product_id, func.sum(CostLayer.qty_remaining), func.sum(CostLayer.qty_remaining * CostLayer.unit_cost))
        .where(CostLayer.company_id == cid, CostLayer.qty_remaining > 0).group_by(CostLayer.product_id)).all()}
    costs = dict(db.execute(select(Product.id, Product.cost_price).where(Product.company_id == cid)).all())
    total = 0.0
    for pid, q in stock.items():
        lq, lv = layered.get(pid, (0.0, 0.0))
        total += lv + max(float(q or 0) - lq, 0) * (costs.get(pid) or 0)
    return round(total, 2)
