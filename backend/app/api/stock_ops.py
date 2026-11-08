"""Warehouse transfers (workflow), non-available stock (damaged / expired / reserved / in transit) and supplier returns."""
from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import require_permission, warehouse_scope
from app.core.pagination import page
from app.models import Product, User, Warehouse
from app.models.stock import StockBucket, StockTransfer
from app.services import stock_states, transfers

router = APIRouter(tags=["stock operations"])


class TransferLineIn(BaseModel):
    product_id: int
    quantity: float
    batch: str | None = None


class TransferIn(BaseModel):
    from_warehouse_id: int
    to_warehouse_id: int
    note: str | None = None
    lines: list[TransferLineIn]
    submit: bool = True  # straight to REQUESTED (False = keep as draft)


class ReceiveIn(BaseModel):
    lines: dict[int, float] | None = None  # line id → quantity that arrived (default: everything)


def _transfer(db: Session, user: User, tid: int) -> StockTransfer:
    t = db.get(StockTransfer, tid)
    if not t or t.company_id != user.company_id:
        raise HTTPException(404, "Transfer not found")
    return t


@router.get("/inventory/transfers")
def list_transfers(response: Response, status: str | None = None, offset: int = 0, limit: int = Query(50, le=500),
                   user: User = Depends(require_permission("inventory.view")), db: Session = Depends(get_db)):
    stmt = select(StockTransfer).where(StockTransfer.company_id == user.company_id)
    if status:
        stmt = stmt.where(StockTransfer.status.in_(status.upper().split(",")))
    if (allowed := warehouse_scope(user)) is not None:
        stmt = stmt.where(StockTransfer.from_warehouse_id.in_(allowed) | StockTransfer.to_warehouse_id.in_(allowed))
    return [transfers.out(db, t) for t in page(db, stmt.order_by(StockTransfer.id.desc()), response, offset, limit)]


@router.get("/inventory/transfers/{tid}")
def get_transfer(tid: int, user: User = Depends(require_permission("inventory.view")), db: Session = Depends(get_db)):
    return transfers.out(db, _transfer(db, user, tid))


@router.post("/inventory/transfers", status_code=201)
def create_transfer(payload: TransferIn, user: User = Depends(require_permission("inventory.transfer")), db: Session = Depends(get_db)):
    t = transfers.create(db, user, payload.from_warehouse_id, payload.to_warehouse_id, [ln.model_dump() for ln in payload.lines], payload.note)
    if payload.submit:
        transfers.submit(db, user, t)
    db.commit()
    return transfers.out(db, t)


def _act(action):
    def run(tid: int, payload: ReceiveIn | None = None, user: User = Depends(require_permission("inventory.transfer")), db: Session = Depends(get_db)):
        t = _transfer(db, user, tid)
        if action is transfers.receive:
            transfers.receive(db, user, t, payload.lines if payload else None)
        else:
            action(db, user, t)
        db.commit()
        db.refresh(t)
        return transfers.out(db, t)
    return run


router.add_api_route("/inventory/transfers/{tid}/submit", _act(transfers.submit), methods=["POST"])
router.add_api_route("/inventory/transfers/{tid}/approve", _act(transfers.approve), methods=["POST"])
router.add_api_route("/inventory/transfers/{tid}/ship", _act(transfers.ship), methods=["POST"])
router.add_api_route("/inventory/transfers/{tid}/receive", _act(transfers.receive), methods=["POST"])
router.add_api_route("/inventory/transfers/{tid}/cancel", _act(transfers.cancel), methods=["POST"])


# ---------------------------------------------------------------- stock states
class StateMoveIn(BaseModel):
    product_id: int
    warehouse_id: int
    quantity: float
    state: str  # damaged / expired
    batch: str | None = None
    reason: str | None = None


@router.get("/stock-states")
def stock_state_list(state: str | None = None, warehouse_id: int | None = None, user: User = Depends(require_permission("inventory.view")),
                     db: Session = Depends(get_db)):
    """Summary per state + every non-available line (reserved, in transit, damaged, expired)."""
    stmt = select(StockBucket).where(StockBucket.company_id == user.company_id, StockBucket.quantity > 0)
    if state:
        stmt = stmt.where(StockBucket.state == state)
    if warehouse_id:
        stmt = stmt.where(StockBucket.warehouse_id == warehouse_id)
    if (allowed := warehouse_scope(user)) is not None:
        stmt = stmt.where(StockBucket.warehouse_id.in_(allowed))
    rows = db.scalars(stmt.order_by(StockBucket.state, StockBucket.id)).all()
    names = dict(db.execute(select(Product.id, Product.name).where(Product.company_id == user.company_id)).all())
    whs = dict(db.execute(select(Warehouse.id, Warehouse.name).where(Warehouse.company_id == user.company_id)).all())
    summary: dict[str, dict] = {}
    for b in rows:
        s = summary.setdefault(b.state, {"quantity": 0.0, "value": 0.0})
        s["quantity"] += b.quantity
        s["value"] = round(s["value"] + b.quantity * b.unit_cost, 2)
    return {"summary": summary, "rows": [{"id": b.id, "state": b.state, "product_id": b.product_id, "product": names.get(b.product_id),
                                          "warehouse_id": b.warehouse_id, "warehouse": whs.get(b.warehouse_id), "batch": b.batch, "expiry_date": b.expiry_date,
                                          "quantity": b.quantity, "unit_cost": b.unit_cost, "value": round(b.quantity * b.unit_cost, 2)} for b in rows]}


def _state_move(fn):
    def run(payload: StateMoveIn, user: User = Depends(require_permission("inventory.adjust")), db: Session = Depends(get_db)):
        from app.api.inventory import _product, _warehouse
        if payload.quantity <= 0:
            raise HTTPException(400, "Quantities must be greater than zero")
        _product(db, user.company_id, payload.product_id)
        _warehouse(db, user.company_id, payload.warehouse_id, user)
        if payload.reason:
            db.info["audit_reason"] = payload.reason
        result = fn(db, user.company_id, payload.product_id, payload.warehouse_id, payload.quantity, payload.state, payload.reason, payload.batch)
        db.commit()
        return {"status": "done", "value": round(result or 0, 2)}
    return run


router.add_api_route("/stock-states/mark", _state_move(stock_states.mark), methods=["POST"], summary="Available → damaged / expired (written off)")
router.add_api_route("/stock-states/restore", _state_move(stock_states.restore), methods=["POST"], summary="Damaged / expired → available")
router.add_api_route("/stock-states/dispose", _state_move(stock_states.dispose), methods=["POST"], summary="Throw away damaged / expired stock")


# ---------------------------------------------------------------- returns to suppliers
class SupplierReturnLineIn(BaseModel):
    product_id: int
    quantity: float
    unit_price: float | None = None  # credit per unit (default: current cost)
    state: str = "available"  # take from available stock, or from damaged / expired stock
    batch: str | None = None


class SupplierReturnIn(BaseModel):
    supplier_id: int
    warehouse_id: int
    po_id: int | None = None
    reason: str | None = None
    lines: list[SupplierReturnLineIn]


def _sr_out(db: Session, r) -> dict:
    from app.models import Supplier
    names = dict(db.execute(select(Product.id, Product.name).where(Product.company_id == r.company_id)).all())
    sup = db.get(Supplier, r.supplier_id)
    return {"id": r.id, "number": r.number, "supplier_id": r.supplier_id, "supplier": sup.name if sup else None, "po_id": r.po_id,
            "warehouse_id": r.warehouse_id, "return_date": r.return_date, "reason": r.reason, "total": r.total, "cost_total": r.cost_total,
            "created_by": r.created_by, "lines": [{"product_id": ln.product_id, "product": names.get(ln.product_id), "quantity": ln.quantity,
                                                   "unit_price": ln.unit_price, "state": ln.state} for ln in r.lines]}


@router.get("/supplier-returns")
def supplier_returns(response: Response, supplier_id: int | None = None, offset: int = 0, limit: int = Query(50, le=500),
                     user: User = Depends(require_permission("purchasing.view")), db: Session = Depends(get_db)):
    from app.models.stock import SupplierReturn
    stmt = select(SupplierReturn).where(SupplierReturn.company_id == user.company_id)
    if supplier_id:
        stmt = stmt.where(SupplierReturn.supplier_id == supplier_id)
    return [_sr_out(db, r) for r in page(db, stmt.order_by(SupplierReturn.id.desc()), response, offset, limit)]


@router.post("/supplier-returns", status_code=201)
def create_supplier_return(payload: SupplierReturnIn, user: User = Depends(require_permission("purchasing.create")), db: Session = Depends(get_db)):
    """Send goods back: stock leaves (at cost, or out of damaged / expired stock), the supplier owes us the credit."""
    from app.api.inventory import _movement, _product, _warehouse, take_stock
    from app.api.purchasing import _supplier
    from app.models.stock import SupplierReturn, SupplierReturnLine
    from app.services.numbering import next_number
    cid = user.company_id
    _supplier(db, cid, payload.supplier_id)
    _warehouse(db, cid, payload.warehouse_id, user)
    lines = [ln for ln in payload.lines if ln.quantity > 0]
    if not lines:
        raise HTTPException(400, "Add at least one product with a quantity above zero")
    r = SupplierReturn(company_id=cid, number=next_number(db, SupplierReturn, cid, "SR"), supplier_id=payload.supplier_id, po_id=payload.po_id,
                       warehouse_id=payload.warehouse_id, reason=payload.reason, created_by=user.full_name)
    db.add(r)
    db.flush()
    total = cost_total = 0.0
    for ln in lines:
        p = _product(db, cid, ln.product_id)
        if ln.state == "available":
            _taken, cost = take_stock(db, cid, p.id, payload.warehouse_id, ln.quantity, "supplier_return", r.number, batch=ln.batch)
        elif ln.state in stock_states.WRITE_OFF_STATES:  # already written off: no stock value left
            stock_states.from_bucket(db, cid, p.id, payload.warehouse_id, ln.state, ln.quantity, ln.batch)
            _movement(db, cid, p.id, payload.warehouse_id, 0, f"supplier_return_{ln.state}", f"{r.number} ({ln.quantity:g})", ln.batch or "", unit_cost=0)
            cost = 0.0
        else:
            raise HTTPException(400, "State must be available, damaged or expired")
        price = ln.unit_price if ln.unit_price is not None else (p.cost_price or 0)
        db.add(SupplierReturnLine(company_id=cid, return_id=r.id, product_id=p.id, quantity=ln.quantity, unit_price=round(price, 4),
                                  unit_cost=round(cost / ln.quantity, 4) if ln.quantity else 0, state=ln.state))
        total += ln.quantity * price
        cost_total += cost
    r.total, r.cost_total = round(total, 2), round(cost_total, 2)
    db.commit()
    db.refresh(r)
    return _sr_out(db, r)
