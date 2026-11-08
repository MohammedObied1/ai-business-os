from datetime import datetime

from fastapi.responses import JSONResponse
from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import branch_scope, can_see_cost, check_warehouse, has_permission, require_permission, warehouse_scope
from app.core.pagination import page
from app.models import Product, PurchaseOrderItem, SalesOrderItem, StockLevel, StockMovement, User, Warehouse
from app.schemas.inventory import (
    ForecastOut, MovementOut, ProductDetail, ProductIn, ProductUpdate, ProductWithStock, StockAdjust, StockLevelOut, StockTransfer, WarehouseIn, WarehouseOut,
)
from app.services.analytics import low_stock_products
from app.services.forecasting import forecast_all, forecast_product

router = APIRouter(prefix="/inventory", tags=["inventory"])


def _product(db: Session, cid: int, pid: int) -> Product:
    p = db.get(Product, pid)
    if not p or p.company_id != cid:
        raise HTTPException(404, "Product not found")
    return p


def _warehouse(db: Session, cid: int, wid: int | None, user: User | None = None) -> Warehouse:
    """The company's warehouse; with `user`, also one that user is allowed to work in."""
    w = db.get(Warehouse, wid) if wid else None
    if not w or w.company_id != cid:
        raise HTTPException(404, "Warehouse not found")
    if user is not None:
        check_warehouse(user, w.id)
    return w


def _movement(db: Session, cid: int, product_id: int, warehouse_id: int, qty: float, movement_type: str, reference, batch: str, serial=None,
              to_warehouse_id=None, unit_cost: float | None = None) -> StockMovement:
    mv = StockMovement(company_id=cid, product_id=product_id, warehouse_id=warehouse_id, to_warehouse_id=to_warehouse_id, quantity=qty,
                       movement_type=movement_type, reference=reference, batch=batch, serial=serial, occurred_at=datetime.utcnow(),
                       unit_cost=None if unit_cost is None else round(unit_cost, 4))
    db.add(mv)
    return mv


def take_stock(db: Session, cid: int, product_id: int, warehouse_id: int, qty: float, movement_type: str, reference: str | None = None,
               to_warehouse_id: int | None = None, batch: str | None = None) -> tuple[list[tuple[str, object, float, float]], float]:
    """Remove qty from a warehouse (a given batch, or earliest-expiring first) and cost it with the company's method.
    Returns ([(batch, expiry, taken, unit_cost)], total_cost)."""
    from app.services import costing
    stmt = select(StockLevel).where(StockLevel.product_id == product_id, StockLevel.warehouse_id == warehouse_id, StockLevel.quantity > 0)
    if batch is not None:
        stmt = stmt.where(StockLevel.batch == batch)
    levels = db.scalars(stmt.order_by(StockLevel.expiry_date.is_(None), StockLevel.expiry_date, StockLevel.id)).all()
    available = round(sum(lv.quantity for lv in levels), 4)
    if available + 1e-9 < qty:
        raise HTTPException(400, f"Insufficient stock (available {available:g}, requested {qty:g})")
    product = db.get(Product, product_id)
    taken, remaining, total = [], qty, 0.0
    for lv in levels:
        if remaining <= 1e-9:
            break
        t = min(lv.quantity, remaining)
        lv.quantity = round(lv.quantity - t, 4)
        remaining -= t
        cost = costing.issue(db, cid, product, warehouse_id, t, lv.batch)
        unit = cost / t if t else 0
        total += cost
        taken.append((lv.batch, lv.expiry_date, t, unit))
        _movement(db, cid, product_id, warehouse_id, -t, movement_type, reference, lv.batch, to_warehouse_id=to_warehouse_id, unit_cost=unit)
    if costing.method(db, cid) == "fifo":
        costing.refresh_average(db, product)
    return taken, round(total, 4)


def take_fefo(db: Session, cid: int, product_id: int, warehouse_id: int, qty: float, movement_type: str, reference: str | None = None,
              to_warehouse_id: int | None = None) -> list[tuple[str, object, float]]:
    """Remove qty, earliest-expiring batch first. Returns [(batch, expiry, taken)] (see take_stock for the cost)."""
    taken, _cost = take_stock(db, cid, product_id, warehouse_id, qty, movement_type, reference, to_warehouse_id)
    return [(b, e, q) for b, e, q, _u in taken]


def apply_stock(db: Session, cid: int, product_id: int, warehouse_id: int, qty: float, movement_type: str,
                reference: str | None = None, batch: str = "", expiry=None, serial: str | None = None, to_warehouse_id: int | None = None,
                unit_cost: float | None = None) -> float:
    """Add (qty > 0, at `unit_cost` or the current cost) or remove (qty < 0) stock. Returns the total cost moved."""
    from app.services import costing
    if qty < 0:
        _taken, cost = take_stock(db, cid, product_id, warehouse_id, -qty, movement_type, reference, to_warehouse_id, batch or None)
        return cost
    lvl = db.scalar(select(StockLevel).where(StockLevel.product_id == product_id, StockLevel.warehouse_id == warehouse_id, StockLevel.batch == batch))
    if not lvl:
        lvl = StockLevel(company_id=cid, product_id=product_id, warehouse_id=warehouse_id, batch=batch, quantity=0, expiry_date=expiry)
        db.add(lvl)
    product = db.get(Product, product_id)
    unit = costing.receive(db, cid, product, warehouse_id, qty, unit_cost, batch)  # before the level goes up (running average)
    lvl.quantity = round(lvl.quantity + qty, 4)
    if expiry:
        lvl.expiry_date = expiry
    _movement(db, cid, product_id, warehouse_id, qty, movement_type, reference, batch, serial, to_warehouse_id, unit_cost=unit)
    return round(qty * unit, 4)


@router.get("/products", response_model=list[ProductWithStock])
def list_products(q: str | None = None, category: str | None = None, include_archived: bool = False, user: User = Depends(require_permission("inventory:read")), db: Session = Depends(get_db)):
    stmt = (select(Product, func.coalesce(func.sum(StockLevel.quantity), 0)).outerjoin(StockLevel, StockLevel.product_id == Product.id)
            .where(Product.company_id == user.company_id).group_by(Product.id).order_by(Product.name))
    if q:
        stmt = stmt.where(Product.name.ilike(f"%{q}%") | Product.sku.ilike(f"%{q}%") | (Product.barcode == q) | (Product.pack_barcode == q))
    if category:
        stmt = stmt.where(Product.category == category)
    if not include_archived:
        stmt = stmt.where(Product.is_active.is_(True))
    see_cost = can_see_cost(user)
    skip = {"total_stock", "pending_approval"}
    return [ProductWithStock(**{c: getattr(p, c) for c in ProductWithStock.model_fields if c not in skip}, total_stock=float(s))
            .model_copy(update={} if see_cost else {"cost_price": None}) for p, s in db.execute(stmt).all()]


def _with_stock(db: Session, p: Product) -> ProductWithStock:
    stock = db.scalar(select(func.coalesce(func.sum(StockLevel.quantity), 0)).where(StockLevel.product_id == p.id))
    # only fields that are real columns on Product — pending_approval isn't one (it's set by the caller afterwards via model_copy)
    skip = {"total_stock", "pending_approval"}
    return ProductWithStock(**{c: getattr(p, c) for c in ProductWithStock.model_fields if c not in skip}, total_stock=float(stock))


def check_sku(db: Session, cid: int, sku: str, exclude_id: int | None = None) -> None:
    stmt = select(Product.id).where(Product.company_id == cid, func.lower(Product.sku) == sku.strip().lower())
    if exclude_id:
        stmt = stmt.where(Product.id != exclude_id)
    if db.scalar(stmt):
        raise HTTPException(400, f"SKU {sku} already exists")


def check_barcode(db: Session, cid: int, code: str | None, exclude_id: int | None = None) -> None:
    if not code:
        return
    stmt = select(Product.id).where(Product.company_id == cid, (Product.barcode == code) | (Product.pack_barcode == code))
    if exclude_id:
        stmt = stmt.where(Product.id != exclude_id)
    if db.scalar(stmt):
        raise HTTPException(400, f"Barcode {code} already used by another product")


def next_sku(db: Session, cid: int) -> str:
    n = (db.scalar(select(func.count(Product.id)).where(Product.company_id == cid)) or 0) + 1
    while db.scalar(select(Product.id).where(Product.company_id == cid, Product.sku == f"P-{n:04d}")):
        n += 1
    return f"P-{n:04d}"


@router.post("/products", response_model=ProductWithStock, status_code=201)
def create_product(payload: ProductIn, user: User = Depends(require_permission("inventory:write")), db: Session = Depends(get_db)):
    data = payload.model_dump(exclude={"opening_stock", "warehouse_id"})
    data["sku"] = (data["sku"] or "").strip() or next_sku(db, user.company_id)
    if not data["name"].strip():
        raise HTTPException(400, "Product name is required")
    check_sku(db, user.company_id, data["sku"])
    check_barcode(db, user.company_id, data.get("barcode"))
    check_barcode(db, user.company_id, data.get("pack_barcode"))
    p = Product(company_id=user.company_id, **data)
    db.add(p)
    db.flush()
    if payload.opening_stock:
        _warehouse(db, user.company_id, payload.warehouse_id)
        apply_stock(db, user.company_id, p.id, payload.warehouse_id, payload.opening_stock, "adjustment", "Opening stock")
    db.commit()
    db.refresh(p)
    return _with_stock(db, p)


@router.get("/products/{product_id}", response_model=ProductDetail)
def product_detail(product_id: int, user: User = Depends(require_permission("inventory:read")), db: Session = Depends(get_db)):
    p = _product(db, user.company_id, product_id)
    levels = db.execute(select(Warehouse.id, Warehouse.name, func.sum(StockLevel.quantity)).join(StockLevel, StockLevel.warehouse_id == Warehouse.id)
                        .where(StockLevel.product_id == p.id).group_by(Warehouse.id, Warehouse.name)).all()
    moves = db.scalars(select(StockMovement).where(StockMovement.product_id == p.id).order_by(StockMovement.occurred_at.desc()).limit(50)).all()
    base = _with_stock(db, p).model_dump()
    if not can_see_cost(user):
        base["cost_price"] = None
    return ProductDetail(**base, by_warehouse=[{"warehouse_id": w, "warehouse": n, "quantity": float(q)} for w, n, q in levels],
                         movements=[MovementOut.model_validate(m) for m in moves])


@router.delete("/products/{product_id}")
def delete_product(product_id: int, user: User = Depends(require_permission("inventory:write")), db: Session = Depends(get_db)):
    """Products with history are archived (hidden) instead of deleted, so old invoices stay intact."""
    p = _product(db, user.company_id, product_id)
    used = db.scalar(select(func.count(StockMovement.id)).where(StockMovement.product_id == p.id)) or \
        db.scalar(select(func.count(SalesOrderItem.id)).where(SalesOrderItem.product_id == p.id)) or \
        db.scalar(select(func.count(PurchaseOrderItem.id)).where(PurchaseOrderItem.product_id == p.id))
    if used:
        p.is_active = False
        db.commit()
        return {"archived": True}
    db.execute(delete(StockLevel).where(StockLevel.product_id == p.id))
    db.delete(p)
    db.commit()
    return {"archived": False}


@router.patch("/products/{product_id}", response_model=ProductWithStock)
def update_product(product_id: int, payload: ProductUpdate, response: Response, user: User = Depends(require_permission("inventory:write")), db: Session = Depends(get_db)):
    p = _product(db, user.company_id, product_id)
    data = payload.model_dump(exclude_unset=True)
    if not can_see_cost(user) or data.get("cost_price", 0) is None:
        data.pop("cost_price", None)  # can't see it → can't change it (and never blank it)
    from app.services import approvals
    pending = False
    new_price = data.get("sale_price")
    if new_price is not None and p.sale_price and new_price != p.sale_price:
        change = abs(new_price - p.sale_price) / p.sale_price * 100
        if approvals.needs(db, user, "price_change", change):
            data.pop("sale_price")
            approvals.request(db, user, "price_change", "products", p.id, f"{p.name}: {p.sale_price:g} → {new_price:g}", round(change, 1),
                              payload={"sale_price": new_price})
            response.headers["X-Approval-Pending"] = "price_change"
            pending = True
    if data.get("sku"):
        check_sku(db, user.company_id, data["sku"], exclude_id=p.id)
    check_barcode(db, user.company_id, data.get("barcode"), exclude_id=p.id)
    check_barcode(db, user.company_id, data.get("pack_barcode"), exclude_id=p.id)
    for k, v in data.items():
        setattr(p, k, v)
    db.commit()
    return _with_stock(db, p).model_copy(update={"pending_approval": pending})


@router.get("/warehouses", response_model=list[WarehouseOut])
def list_warehouses(user: User = Depends(require_permission("inventory:read")), db: Session = Depends(get_db)):
    stmt = select(Warehouse).where(Warehouse.company_id == user.company_id)
    if (scope := branch_scope(user)):
        stmt = stmt.where((Warehouse.branch_id == scope) | Warehouse.branch_id.is_(None))
    if (allowed := warehouse_scope(user)) is not None:
        stmt = stmt.where(Warehouse.id.in_(allowed))
    return db.scalars(stmt).all()


@router.post("/warehouses", response_model=WarehouseOut, status_code=201)
def create_warehouse(payload: WarehouseIn, user: User = Depends(require_permission("inventory:write")), db: Session = Depends(get_db)):
    from app.services import saas
    cap = saas.limit(db, user.company_id, "max_warehouses")
    if cap and (db.scalar(select(func.count(Warehouse.id)).where(Warehouse.company_id == user.company_id)) or 0) >= cap:
        raise HTTPException(403, f"Your plan allows {cap} warehouse(s). Contact the platform admin to upgrade.")
    w = Warehouse(company_id=user.company_id, **payload.model_dump())
    db.add(w)
    db.commit()
    db.refresh(w)
    return w


@router.patch("/warehouses/{warehouse_id}", response_model=WarehouseOut)
def update_warehouse(warehouse_id: int, payload: WarehouseIn, user: User = Depends(require_permission("inventory:write")), db: Session = Depends(get_db)):
    w = _warehouse(db, user.company_id, warehouse_id)
    w.name, w.location, w.branch_id = payload.name, payload.location, payload.branch_id
    db.commit()
    db.refresh(w)
    return w


@router.delete("/warehouses/{warehouse_id}", status_code=204)
def delete_warehouse(warehouse_id: int, user: User = Depends(require_permission("inventory:write")), db: Session = Depends(get_db)):
    w = _warehouse(db, user.company_id, warehouse_id)
    if db.scalar(select(func.count(StockMovement.id)).where((StockMovement.warehouse_id == w.id) | (StockMovement.to_warehouse_id == w.id))):
        raise HTTPException(400, "This warehouse has stock history and cannot be deleted")
    db.execute(delete(StockLevel).where(StockLevel.warehouse_id == w.id))
    db.delete(w)
    db.commit()


@router.get("/stock", response_model=list[StockLevelOut])
def stock_levels(product_id: int | None = None, warehouse_id: int | None = None, user: User = Depends(require_permission("inventory:read")), db: Session = Depends(get_db)):
    stmt = select(StockLevel).where(StockLevel.company_id == user.company_id)
    if product_id:
        stmt = stmt.where(StockLevel.product_id == product_id)
    if warehouse_id:
        stmt = stmt.where(StockLevel.warehouse_id == warehouse_id)
    return db.scalars(stmt).all()


@router.post("/stock/adjust", response_model=StockLevelOut)
def adjust_stock(payload: StockAdjust, user: User = Depends(require_permission("inventory.adjust")), db: Session = Depends(get_db)):
    p = _product(db, user.company_id, payload.product_id)
    _warehouse(db, user.company_id, payload.warehouse_id, user)
    from app.services import approvals
    value = abs(payload.quantity) * (p.cost_price or 0)
    if approvals.needs(db, user, "inventory_adjustment", value) and not has_permission(user, "inventory.approve_adjustment"):
        req = approvals.request(db, user, "inventory_adjustment", "products", p.id, f"{p.name} {payload.quantity:+g}", round(value, 2),
                                payload.reference, payload=payload.model_dump(mode="json"))
        db.commit()
        return JSONResponse(status_code=202, content=approvals.pending_response(req))
    apply_stock(db, user.company_id, payload.product_id, payload.warehouse_id, payload.quantity, "adjustment", payload.reference, payload.batch, payload.expiry_date, payload.serial)
    from app.services import webhooks
    webhooks.emit(db, user.company_id, "stock.updated", {"product_id": p.id, "product": p.name, "warehouse_id": payload.warehouse_id,
                                                          "quantity_change": payload.quantity, "reason": "adjustment"})
    db.commit()
    return db.scalar(select(StockLevel).where(StockLevel.product_id == payload.product_id, StockLevel.warehouse_id == payload.warehouse_id, StockLevel.batch == payload.batch))


@router.post("/stock/transfer")
def transfer_stock(payload: StockTransfer, user: User = Depends(require_permission("inventory.transfer")), db: Session = Depends(get_db)):
    _product(db, user.company_id, payload.product_id)
    _warehouse(db, user.company_id, payload.from_warehouse_id, user)
    _warehouse(db, user.company_id, payload.to_warehouse_id)
    if payload.from_warehouse_id == payload.to_warehouse_id:
        raise HTTPException(400, "Choose two different warehouses")
    if payload.quantity <= 0:
        raise HTTPException(400, "Quantities must be greater than zero")
    ref = f"TR:{payload.from_warehouse_id}->{payload.to_warehouse_id}"
    # the stock keeps its cost when it moves (each batch at the cost it left with)
    taken, _cost = take_stock(db, user.company_id, payload.product_id, payload.from_warehouse_id, payload.quantity, "transfer", ref,
                              payload.to_warehouse_id, payload.batch or None)
    for batch, expiry, qty, unit in taken:
        apply_stock(db, user.company_id, payload.product_id, payload.to_warehouse_id, qty, "transfer", ref, batch, expiry, unit_cost=unit)
    db.commit()
    return {"detail": "Transferred"}


@router.get("/movements", response_model=list[MovementOut])
def movements(response: Response, product_id: int | None = None, offset: int = 0, limit: int = Query(100, le=5000),
              user: User = Depends(require_permission("inventory:read")), db: Session = Depends(get_db)):
    stmt = select(StockMovement).where(StockMovement.company_id == user.company_id)
    if product_id:
        stmt = stmt.where(StockMovement.product_id == product_id)
    return page(db, stmt.order_by(StockMovement.occurred_at.desc(), StockMovement.id.desc()), response, offset, limit)


@router.get("/low-stock")
def low_stock(user: User = Depends(require_permission("inventory:read")), db: Session = Depends(get_db)):
    return low_stock_products(db, user.company_id)


@router.get("/forecast", response_model=list[ForecastOut])
def forecast(only_risky: bool = False, user: User = Depends(require_permission("inventory:read")), db: Session = Depends(get_db)):
    return forecast_all(db, user.company_id, only_risky)


@router.get("/forecast/{product_id}", response_model=ForecastOut)
def forecast_one(product_id: int, user: User = Depends(require_permission("inventory:read")), db: Session = Depends(get_db)):
    return forecast_product(db, user.company_id, _product(db, user.company_id, product_id))


@router.get("/barcode/{code}")
def by_barcode(code: str, user: User = Depends(require_permission("inventory:read")), db: Session = Depends(get_db)):
    """Scanner lookup: returns the product and whether the code is the single-unit or the pack barcode."""
    p = db.scalar(select(Product).where(Product.company_id == user.company_id, Product.is_active.is_(True),
                                        (Product.barcode == code) | (Product.pack_barcode == code) | (Product.sku == code)))
    if not p:
        raise HTTPException(404, "No product with this barcode")
    return {"product": _with_stock(db, p), "unit": "pack" if p.pack_barcode == code and p.pack_size else "unit"}


@router.get("/expiring")
def expiring(days: int = 60, user: User = Depends(require_permission("inventory:read")), db: Session = Depends(get_db)):
    """Batches that expire within `days` (or already expired) and still have stock."""
    from datetime import date, timedelta
    limit = date.today() + timedelta(days=days)
    rows = db.execute(select(StockLevel, Product.name, Product.sku, Warehouse.name).join(Product, Product.id == StockLevel.product_id)
                      .join(Warehouse, Warehouse.id == StockLevel.warehouse_id)
                      .where(StockLevel.company_id == user.company_id, StockLevel.quantity > 0, StockLevel.expiry_date.is_not(None), StockLevel.expiry_date <= limit)
                      .order_by(StockLevel.expiry_date)).all()
    today = date.today()
    return [{"product_id": lv.product_id, "product": pn, "sku": sku, "warehouse": wn, "batch": lv.batch, "quantity": lv.quantity,
             "expiry_date": lv.expiry_date, "days_left": (lv.expiry_date - today).days,
             "value": round(lv.quantity * (db.get(Product, lv.product_id).cost_price or 0), 2)} for lv, pn, sku, wn in rows]


@router.get("/valuation")
def valuation(user: User = Depends(require_permission("inventory:read")), db: Session = Depends(get_db)):
    """Stock value at cost and at sale price, per product."""
    rows = db.execute(select(Product, func.coalesce(func.sum(StockLevel.quantity), 0)).outerjoin(StockLevel, StockLevel.product_id == Product.id)
                      .where(Product.company_id == user.company_id, Product.is_active.is_(True)).group_by(Product.id).order_by(Product.name)).all()
    items = [{"product_id": p.id, "name": p.name, "sku": p.sku, "category": p.category, "quantity": float(q), "cost_price": p.cost_price,
              "sale_price": p.sale_price, "cost_value": round(float(q) * p.cost_price, 2), "sale_value": round(float(q) * p.sale_price, 2)} for p, q in rows]
    return {"items": items, "total_cost": round(sum(i["cost_value"] for i in items), 2), "total_sale": round(sum(i["sale_value"] for i in items), 2)}
