"""Cash boxes & bank accounts, their ledger, manual vouchers, transfers and cheques."""
import uuid
from datetime import date

from fastapi.responses import JSONResponse
from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import branch_scope, get_current_user, require_permission
from app.core.pagination import page
from app.services import currency as fx
from app.models import Account, Alert, Cheque, Customer, Invoice, Payment, PurchaseOrder, Supplier, SupplierPayment, Transaction, User
from app.services.money import account_balance, default_cash_account, get_account, post
from app.services.sales_ops import refresh_invoice_status

router = APIRouter(tags=["cash, banks & cheques"])


# ---------------------------------------------------------------- schemas
class AccountIn(BaseModel):
    name: str
    kind: str = "cash"
    bank_name: str | None = None
    account_number: str | None = None
    opening_balance: float = 0
    branch_id: int | None = None
    is_active: bool = True
    currency: str | None = None


class VoucherIn(BaseModel):
    direction: str  # in / out
    account_id: int | None = None
    amount: float
    party_name: str | None = None
    description: str | None = None
    reference: str | None = None
    tx_date: date | None = None
    gl_account_id: int | None = None  # what the money is for (capital, loan, drawings...); default: other income / other expense


class TransferIn(BaseModel):
    from_account_id: int
    to_account_id: int
    amount: float
    description: str | None = None
    tx_date: date | None = None


class ChequeAction(BaseModel):
    account_id: int | None = None  # where an incoming cheque was deposited / from which account an outgoing one was paid
    on: date | None = None
    note: str | None = None


def _tx_out(t: Transaction) -> dict:
    return {"id": t.id, "account_id": t.account_id, "date": t.tx_date, "amount": t.amount, "kind": t.kind, "number": t.number,
            "description": t.description, "reference": t.reference, "party_name": t.party_name, "customer_id": t.customer_id,
            "supplier_id": t.supplier_id, "cheque_id": t.cheque_id, "base_amount": t.base_amount, "gl_account_id": t.gl_account_id}


# ---------------------------------------------------------------- accounts
@router.get("/accounts")
def list_accounts(user: User = Depends(require_permission("accounts:read")), db: Session = Depends(get_db)):
    default_cash_account(db, user.company_id)
    db.commit()
    stmt = select(Account).where(Account.company_id == user.company_id)
    if (scope := branch_scope(user)):
        stmt = stmt.where((Account.branch_id == scope) | Account.branch_id.is_(None))
    base = fx.base(db, user.company_id)
    out = []
    for a in db.scalars(stmt.order_by(Account.kind, Account.id)).all():
        bal = account_balance(db, a)
        out.append({"id": a.id, "name": a.name, "kind": a.kind, "bank_name": a.bank_name, "account_number": a.account_number, "branch_id": a.branch_id,
                    "opening_balance": a.opening_balance, "is_active": a.is_active, "balance": bal, "currency": a.currency or base,
                    "balance_base": round(bal * fx.rate(db, user.company_id, a.currency), 2)})
    return out


@router.post("/accounts", status_code=201)
def create_account(payload: AccountIn, user: User = Depends(require_permission("accounts:write")), db: Session = Depends(get_db)):
    if payload.kind not in ("cash", "bank"):
        raise HTTPException(400, "Account type must be cash or bank")
    data = payload.model_dump()
    data["currency"] = fx.normalize(db, user.company_id, data.get("currency"))
    a = Account(company_id=user.company_id, **data)
    db.add(a)
    db.commit()
    return {"id": a.id}


@router.patch("/accounts/{account_id}")
def update_account(account_id: int, payload: AccountIn, user: User = Depends(require_permission("accounts:write")), db: Session = Depends(get_db)):
    a = get_account(db, user.company_id, account_id)
    data = payload.model_dump()
    data["currency"] = fx.normalize(db, user.company_id, data.get("currency"))
    if data["currency"] != a.currency and db.scalar(select(Transaction.id).where(Transaction.account_id == a.id)):
        raise HTTPException(400, "The currency of an account with movements cannot be changed")
    for k, v in data.items():
        setattr(a, k, v)
    db.commit()
    return {"id": a.id}


@router.get("/accounts/{account_id}/ledger")
def ledger(account_id: int, start: date | None = None, end: date | None = None, user: User = Depends(require_permission("accounts:read")),
           db: Session = Depends(get_db)):
    a = get_account(db, user.company_id, account_id)
    stmt = select(Transaction).where(Transaction.account_id == a.id)
    opening = a.opening_balance or 0
    if start:
        opening = account_balance(db, a, until=date.fromordinal(start.toordinal() - 1))
        stmt = stmt.where(Transaction.tx_date >= start)
    if end:
        stmt = stmt.where(Transaction.tx_date <= end)
    rows, running = [], opening
    for t in db.scalars(stmt.order_by(Transaction.tx_date, Transaction.id)).all():
        running = round(running + t.amount, 2)
        rows.append({**_tx_out(t), "balance": running})
    return {"account": {"id": a.id, "name": a.name, "kind": a.kind}, "opening": round(opening, 2), "closing": running, "rows": rows}


@router.get("/transactions")
def transactions(response: Response, offset: int = 0, limit: int = Query(100, le=5000), kind: str | None = None, q: str | None = None,
                 user: User = Depends(require_permission("accounts:read")), db: Session = Depends(get_db)):
    stmt = select(Transaction).where(Transaction.company_id == user.company_id)
    if kind:
        stmt = stmt.where(Transaction.kind == kind)
    if q:
        stmt = stmt.where(Transaction.number.ilike(f"%{q}%") | Transaction.party_name.ilike(f"%{q}%") | Transaction.description.ilike(f"%{q}%"))
    return [_tx_out(t) for t in page(db, stmt.order_by(Transaction.tx_date.desc(), Transaction.id.desc()), response, offset, limit)]


@router.post("/vouchers", status_code=201)
def voucher(payload: VoucherIn, user: User = Depends(require_permission("accounts:write")), db: Session = Depends(get_db)):
    """Manual receipt (سند قبض) or payment (سند صرف) not tied to an invoice: capital, loans, owner withdrawals, misc income…"""
    if payload.amount <= 0:
        raise HTTPException(400, "Amount must be greater than zero")
    if payload.direction not in ("in", "out"):
        raise HTTPException(400, "direction must be in or out")
    sign = 1 if payload.direction == "in" else -1
    from app.services import approvals
    if sign < 0 and approvals.needs(db, user, "payment_voucher", payload.amount):
        get_account(db, user.company_id, payload.account_id)
        req = approvals.request(db, user, "payment_voucher", "vouchers", None, f"{payload.party_name or payload.description or 'Payment'} {payload.amount:,.2f}",
                                payload.amount, payload.description, payload=payload.model_dump(mode="json"))
        db.commit()
        return JSONResponse(status_code=202, content=approvals.pending_response(req))
    if payload.gl_account_id:
        from app.models import GLAccount
        g = db.get(GLAccount, payload.gl_account_id)
        if not g or g.company_id != user.company_id:
            raise HTTPException(404, "Account not found")
    t = post(db, user.company_id, payload.account_id, sign * payload.amount, "other_in" if sign > 0 else "other_out",
             prefix="RV" if sign > 0 else "PV", tx_date=payload.tx_date, party_name=payload.party_name, description=payload.description,
             reference=payload.reference, user_id=user.id, gl_account_id=payload.gl_account_id)
    db.commit()
    return _tx_out(t)


@router.post("/transfers", status_code=201)
def transfer(payload: TransferIn, user: User = Depends(require_permission("accounts:write")), db: Session = Depends(get_db)):
    if payload.from_account_id == payload.to_account_id:
        raise HTTPException(400, "Choose two different accounts")
    if payload.amount <= 0:
        raise HTTPException(400, "Amount must be greater than zero")
    group = uuid.uuid4().hex[:12]
    src, dst = get_account(db, user.company_id, payload.from_account_id), get_account(db, user.company_id, payload.to_account_id)
    # amount is in the source account's currency; the destination receives the converted amount
    dst_amount = round(payload.amount * fx.rate(db, user.company_id, src.currency) / fx.rate(db, user.company_id, dst.currency), 2)
    out = post(db, user.company_id, src.id, -payload.amount, "transfer", prefix="TR", tx_date=payload.tx_date, transfer_group=group,
               description=payload.description or f"→ {dst.name}", user_id=user.id)
    post(db, user.company_id, dst.id, dst_amount, "transfer", number=out.number, tx_date=payload.tx_date, transfer_group=group,
         description=payload.description or f"← {src.name}", user_id=user.id)
    db.commit()
    return {"number": out.number}


@router.get("/vouchers/{number}")
def voucher_detail(number: str, user: User = Depends(require_permission("accounts:read")), db: Session = Depends(get_db)):
    rows = db.scalars(select(Transaction).where(Transaction.company_id == user.company_id, Transaction.number == number)).all()
    if not rows:
        raise HTTPException(404, "Voucher not found")
    accounts = {a.id: a.name for a in db.scalars(select(Account).where(Account.company_id == user.company_id)).all()}
    return {"number": number, "rows": [{**_tx_out(t), "account": accounts.get(t.account_id)} for t in rows]}


# ---------------------------------------------------------------- cheques
def _cheque(db: Session, cid: int, cheque_id: int) -> Cheque:
    c = db.get(Cheque, cheque_id)
    if not c or c.company_id != cid:
        raise HTTPException(404, "Cheque not found")
    return c


def _cheque_out(db: Session, c: Cheque, names: dict) -> dict:
    today = date.today()
    return {"id": c.id, "direction": c.direction, "number": c.number, "bank": c.bank, "amount": c.amount, "issue_date": c.issue_date,
            "due_date": c.due_date, "status": c.status, "customer_id": c.customer_id, "supplier_id": c.supplier_id,
            "party": names.get(("c", c.customer_id)) or names.get(("s", c.supplier_id)), "account_id": c.account_id,
            "days_to_due": (c.due_date - today).days, "currency": c.currency, "cleared_at": c.cleared_at, "bounced_at": c.bounced_at, "notes": c.notes}


@router.get("/cheques")
def list_cheques(direction: str | None = None, status: str | None = None, user: User = Depends(require_permission("accounts:read")), db: Session = Depends(get_db)):
    cid = user.company_id
    stmt = select(Cheque).where(Cheque.company_id == cid)
    if direction:
        stmt = stmt.where(Cheque.direction == direction)
    if status:
        stmt = stmt.where(Cheque.status == status)
    rows = db.scalars(stmt.order_by(Cheque.due_date)).all()
    names = {("c", i): n for i, n in db.execute(select(Customer.id, Customer.name).where(Customer.company_id == cid)).all()}
    names |= {("s", i): n for i, n in db.execute(select(Supplier.id, Supplier.name).where(Supplier.company_id == cid)).all()}
    return [_cheque_out(db, c, names) for c in rows]


@router.post("/cheques/{cheque_id}/deposit")
def deposit(cheque_id: int, payload: ChequeAction, user: User = Depends(require_permission("accounts:write")), db: Session = Depends(get_db)):
    c = _cheque(db, user.company_id, cheque_id)
    if c.direction != "in" or c.status != "pending":
        raise HTTPException(400, "Only pending incoming cheques can be deposited")
    c.account_id = get_account(db, user.company_id, payload.account_id).id
    c.status = "deposited"
    db.commit()
    return {"status": c.status}


@router.post("/cheques/{cheque_id}/clear")
def clear(cheque_id: int, payload: ChequeAction, user: User = Depends(require_permission("accounts:write")), db: Session = Depends(get_db)):
    """The bank paid the cheque: money actually moves into (incoming) or out of (outgoing) the account."""
    c = _cheque(db, user.company_id, cheque_id)
    if c.status not in ("pending", "deposited"):
        raise HTTPException(400, "This cheque is already settled")
    acc = get_account(db, user.company_id, payload.account_id or c.account_id)
    party = db.get(Customer, c.customer_id).name if c.customer_id else (db.get(Supplier, c.supplier_id).name if c.supplier_id else None)
    sign = 1 if c.direction == "in" else -1
    acc_amount = round(c.amount * fx.rate(db, user.company_id, c.currency) / fx.rate(db, user.company_id, acc.currency), 2)
    post(db, user.company_id, acc.id, sign * acc_amount, "cheque_cleared", tx_date=payload.on, cheque_id=c.id, reference=f"Cheque {c.number}",
         customer_id=c.customer_id, supplier_id=c.supplier_id, party_name=party, description=c.bank, user_id=user.id)
    c.account_id, c.status, c.cleared_at = acc.id, "cleared", payload.on or date.today()
    db.commit()
    return {"status": c.status}


@router.post("/cheques/{cheque_id}/bounce")
def bounce(cheque_id: int, payload: ChequeAction, user: User = Depends(require_permission("accounts:write")), db: Session = Depends(get_db)):
    """Returned cheque: the debt comes back on the customer's (or our) books."""
    cid = user.company_id
    c = _cheque(db, cid, cheque_id)
    if c.status not in ("pending", "deposited"):
        raise HTTPException(400, "This cheque is already settled")
    c.status, c.bounced_at, c.notes = "bounced", payload.on or date.today(), payload.note or c.notes
    if c.direction == "in":
        pays = db.scalars(select(Payment).where(Payment.company_id == cid, Payment.reference == f"Cheque {c.number}", Payment.customer_id == c.customer_id,
                                                Payment.status != "bounced")).all()
        if c.payment_id:
            first = db.get(Payment, c.payment_id)
            pays = db.scalars(select(Payment).where(Payment.company_id == cid, Payment.number == first.number)).all() if first else pays
        for p in pays:
            inv = db.get(Invoice, p.invoice_id)
            inv.paid_amount = round(inv.paid_amount - p.amount, 2)
            p.status = "bounced"
            refresh_invoice_status(inv)
        cust = db.get(Customer, c.customer_id)
        db.add(Alert(company_id=cid, severity="critical", category="finance", title=f"Cheque {c.number} bounced",
                     message=f"{cust.name if cust else ''}: {c.amount:,.2f}", recommended_action="Contact the customer", dedupe_key=f"bounce:{c.id}"))
    else:
        _undo_supplier_payment(db, c)
    db.commit()
    return {"status": c.status}


@router.post("/cheques/{cheque_id}/cancel")
def cancel_cheque(cheque_id: int, user: User = Depends(require_permission("accounts:write")), db: Session = Depends(get_db)):
    """Tear up an outgoing cheque that was never cashed: the supplier is owed that money again."""
    c = _cheque(db, user.company_id, cheque_id)
    if c.status != "pending" or c.direction != "out":
        raise HTTPException(400, "Only pending outgoing cheques can be cancelled")
    c.status = "cancelled"
    _undo_supplier_payment(db, c)
    db.commit()
    return {"status": c.status}


def _undo_supplier_payment(db: Session, c: Cheque) -> None:
    sp = db.get(SupplierPayment, c.supplier_payment_id) if c.supplier_payment_id else None
    if sp and sp.status != "bounced":
        sp.status = "bounced"
        if sp.po_id:
            po = db.get(PurchaseOrder, sp.po_id)
            po.paid_amount = round(max(po.paid_amount - sp.amount, 0), 2)


@router.get("/cheques/summary")
def cheques_summary(user: User = Depends(require_permission("accounts:read")), db: Session = Depends(get_db)):
    cid = user.company_id
    today = date.today()

    def total(direction: str, due_before: date | None = None) -> float:
        stmt = select(func.coalesce(func.sum(Cheque.amount), 0)).where(Cheque.company_id == cid, Cheque.direction == direction,
                                                                       Cheque.status.in_(("pending", "deposited")))
        if due_before:
            stmt = stmt.where(Cheque.due_date <= due_before)
        return round(float(db.scalar(stmt)), 2)
    week = date.fromordinal(today.toordinal() + 7)
    return {"in_hand": total("in"), "in_due_week": total("in", week), "issued": total("out"), "out_due_week": total("out", week),
            "bounced_count": db.scalar(select(func.count(Cheque.id)).where(Cheque.company_id == cid, Cheque.status == "bounced")) or 0}



# ---------------------------------------------------------------- currencies
class CurrencyIn(BaseModel):
    code: str
    rate: float


@router.get("/currencies")
def currencies(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    from app.models import Currency
    rows = db.scalars(select(Currency).where(Currency.company_id == user.company_id).order_by(Currency.code)).all()
    return {"base": fx.base(db, user.company_id), "items": [{"id": c.id, "code": c.code, "rate": c.rate, "updated_at": c.updated_at} for c in rows]}


@router.put("/currencies")
def upsert_currency(payload: CurrencyIn, user: User = Depends(require_permission("settings:write")), db: Session = Depends(get_db)):
    from app.models import Currency
    code = payload.code.strip().upper()
    if len(code) != 3 or not code.isalpha():
        raise HTTPException(400, "Use a 3-letter currency code like USD or JOD")
    if code == fx.base(db, user.company_id):
        raise HTTPException(400, "This is already your main currency")
    if payload.rate <= 0:
        raise HTTPException(400, "Amount must be greater than zero")
    c = db.scalar(select(Currency).where(Currency.company_id == user.company_id, Currency.code == code))
    if not c:
        c = Currency(company_id=user.company_id, code=code, rate=payload.rate)
        db.add(c)
    c.rate = payload.rate
    db.commit()
    return {"code": c.code, "rate": c.rate}
