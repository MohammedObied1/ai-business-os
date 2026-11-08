from datetime import date, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import branch_scope, get_current_user, require_permission
from app.core.pagination import page
from app.models import Customer, CustomerInteraction, Invoice, SalesOrder, User
from pydantic import BaseModel

from app.schemas.crm import CustomerIn, CustomerOut, CustomerProfile, CustomerUpdate, InteractionIn, InteractionOut
from app.services.analytics import INVOICE_BALANCE_BASE, OPEN_INVOICE, ORDER_NET
from app.services.scoring import rescore_all, score_customer

router = APIRouter(prefix="/customers", tags=["crm"])


def _get(db: Session, cid: int, customer_id: int) -> Customer:
    c = db.get(Customer, customer_id)
    if not c or c.company_id != cid:
        raise HTTPException(404, "Customer not found")
    return c


@router.get("", response_model=list[CustomerOut])
def list_customers(response: Response, q: str | None = None, offset: int = 0, limit: int = Query(100, le=5000), assigned_to_me: bool = False,
                   user: User = Depends(require_permission("customers:read")), db: Session = Depends(get_db)):
    stmt = select(Customer).where(Customer.company_id == user.company_id)
    if (scope := branch_scope(user)):
        stmt = stmt.where((Customer.branch_id == scope) | Customer.branch_id.is_(None))
    if assigned_to_me:
        stmt = stmt.where(Customer.assigned_user_id == user.id)
    if q:
        stmt = stmt.where(Customer.name.ilike(f"%{q}%") | Customer.phone.ilike(f"%{q}%"))
    return page(db, stmt.order_by(Customer.name), response, offset, limit)


@router.post("", response_model=CustomerOut, status_code=201)
def create_customer(payload: CustomerIn, user: User = Depends(require_permission("customers:write")), db: Session = Depends(get_db)):
    c = Customer(company_id=user.company_id, **payload.model_dump())
    c.branch_id = c.branch_id or branch_scope(user)
    db.add(c)
    db.flush()
    from app.services import webhooks
    webhooks.emit(db, user.company_id, "customer.created", {"id": c.id, "name": c.name, "phone": c.phone})
    db.commit()
    db.refresh(c)
    return c


@router.get("/{customer_id}", response_model=CustomerProfile)
def customer_profile(customer_id: int, user: User = Depends(require_permission("customers:read")), db: Session = Depends(get_db)):
    c = _get(db, user.company_id, customer_id)
    rev, cnt, last = db.execute(
        select(func.coalesce(func.sum(ORDER_NET), 0), func.count(SalesOrder.id), func.max(SalesOrder.order_date)).where(
            SalesOrder.customer_id == c.id, SalesOrder.status.in_(("confirmed", "delivered")))
    ).one()
    bal = db.scalar(select(func.coalesce(func.sum(INVOICE_BALANCE_BASE), 0)).where(
        Invoice.customer_id == c.id, Invoice.status.in_(OPEN_INVOICE)))
    inter = db.scalars(select(CustomerInteraction).where(CustomerInteraction.customer_id == c.id).order_by(CustomerInteraction.occurred_at.desc()).limit(50)).all()
    c.score = score_customer(db, user.company_id, c)
    db.commit()
    return CustomerProfile(**CustomerOut.model_validate(c).model_dump(), total_revenue=float(rev), open_balance=float(bal), orders_count=cnt,
                           last_purchase=datetime.combine(last, datetime.min.time()) if last else None,
                           interactions=[InteractionOut.model_validate(i) for i in inter])


@router.patch("/{customer_id}", response_model=CustomerOut)
def update_customer(customer_id: int, payload: CustomerUpdate, user: User = Depends(require_permission("customers:write")), db: Session = Depends(get_db)):
    c = _get(db, user.company_id, customer_id)
    for k, v in payload.model_dump(exclude_unset=True).items():
        setattr(c, k, v)
    db.commit()
    db.refresh(c)
    return c


@router.delete("/{customer_id}", status_code=204)
def delete_customer(customer_id: int, user: User = Depends(require_permission("customers:delete")), db: Session = Depends(get_db)):
    c = _get(db, user.company_id, customer_id)
    if db.scalar(select(func.count(SalesOrder.id)).where(SalesOrder.customer_id == c.id)) or \
            db.scalar(select(func.count(Invoice.id)).where(Invoice.customer_id == c.id)):
        raise HTTPException(400, "This customer has orders or invoices and cannot be deleted")
    db.delete(c)
    db.commit()


@router.post("/{customer_id}/interactions", response_model=InteractionOut, status_code=201)
def add_interaction(customer_id: int, payload: InteractionIn, user: User = Depends(require_permission("customers:write")), db: Session = Depends(get_db)):
    _get(db, user.company_id, customer_id)
    i = CustomerInteraction(company_id=user.company_id, customer_id=customer_id, user_id=user.id, kind=payload.kind, summary=payload.summary,
                            occurred_at=payload.occurred_at or datetime.utcnow())
    db.add(i)
    db.commit()
    db.refresh(i)
    return i


@router.post("/rescore")
def rescore(user: User = Depends(require_permission("customers:write")), db: Session = Depends(get_db)):
    return {"rescored": rescore_all(db, user.company_id)}


def statement_rows(db: Session, c: Customer, start: date | None, end: date | None) -> dict:
    """Account statement (كشف حساب) in the company currency: invoices add to what the customer owes; payments and returns reduce it."""
    from app.models import Cheque, CreditNote, Payment
    ev = []  # (date, order, number, kind, debit, credit)
    for inv in db.scalars(select(Invoice).where(Invoice.customer_id == c.id, Invoice.status != "cancelled")).all():
        ev.append((inv.issue_date, 0, inv.number, "invoice", inv.total * (inv.exchange_rate or 1), 0.0))
    inv_rate = dict(db.execute(select(Invoice.id, Invoice.exchange_rate).where(Invoice.customer_id == c.id)).all())
    for p in db.scalars(select(Payment).where(Payment.customer_id == c.id)).all():
        d = p.paid_at.date()
        v = p.amount * (inv_rate.get(p.invoice_id) or 1)
        ev.append((d, 1, p.number or "", f"payment_{p.method}", 0.0, v))
        if p.status == "bounced":
            ch = db.scalar(select(Cheque).where(Cheque.customer_id == c.id, Cheque.number == (p.reference or "").removeprefix("Cheque ")))
            ev.append((ch.bounced_at if ch and ch.bounced_at else d, 2, p.number or "", "cheque_bounced", v, 0.0))
    for n in db.scalars(select(CreditNote).where(CreditNote.customer_id == c.id)).all():
        r = n.exchange_rate or 1
        ev.append((n.note_date, 1, n.number, "return", 0.0, n.total * r))
        if n.refunded:
            ev.append((n.note_date, 2, n.number, "refund", n.refunded * r, 0.0))
    ev.sort(key=lambda e: (e[0], e[1]))
    opening = bal = 0.0
    rows = []
    for d, _o, number, kind, debit, credit in ev:
        if start and d < start:
            opening = bal = round(bal + debit - credit, 2)
            continue
        if end and d > end:
            continue
        bal = round(bal + debit - credit, 2)
        rows.append({"date": d, "number": number, "kind": kind, "debit": round(debit, 2), "credit": round(credit, 2), "balance": bal})
    return {"customer": {"id": c.id, "name": c.name, "phone": c.phone, "address": c.address}, "opening": round(opening, 2),
            "closing": bal, "rows": rows, "total_debit": round(sum(r["debit"] for r in rows), 2), "total_credit": round(sum(r["credit"] for r in rows), 2)}


@router.get("/{customer_id}/statement")
def statement(customer_id: int, start: date | None = None, end: date | None = None,
              user: User = Depends(require_permission("customers:read")), db: Session = Depends(get_db)):
    return statement_rows(db, _get(db, user.company_id, customer_id), start, end)


def _portal_out(c) -> dict:
    from app.core.config import settings
    active = bool(c.portal_token) and (c.portal_expires_at is None or c.portal_expires_at > datetime.utcnow())
    return {"token": c.portal_token if active else None, "active": active, "expires_at": c.portal_expires_at, "last_seen_at": c.portal_last_seen_at,
            "url": f"{settings.PUBLIC_APP_URL.rstrip('/')}/portal/{c.portal_token}" if active else None}


@router.get("/{customer_id}/portal-link")
def portal_link_status(customer_id: int, user: User = Depends(require_permission("customers:read")), db: Session = Depends(get_db)):
    return _portal_out(_get(db, user.company_id, customer_id))


@router.post("/{customer_id}/portal-link")
def portal_link(customer_id: int, days: int = 90, renew: bool = False, user: User = Depends(require_permission("customers:write")),
                db: Session = Depends(get_db)):
    """A private link the customer can open to see their account. It always expires (1–365 days, default 90).
    `renew=true` issues a new token, so any old link stops working."""
    import secrets
    from app.core.audit import log_event
    c = _get(db, user.company_id, customer_id)
    days = max(1, min(days, 365))
    expired = not c.portal_token or (c.portal_expires_at and c.portal_expires_at <= datetime.utcnow())
    if renew or expired:
        c.portal_token = secrets.token_urlsafe(24)
    c.portal_expires_at = datetime.utcnow() + timedelta(days=days)
    log_event(db, user.company_id, "portal_link", "customers", c.name, {"days": days, "new_token": bool(renew or expired)}, user.id, user.full_name)
    db.commit()
    return _portal_out(c)


@router.delete("/{customer_id}/portal-link", status_code=204)
def revoke_portal_link(customer_id: int, user: User = Depends(require_permission("customers:write")), db: Session = Depends(get_db)):
    from app.core.audit import log_event
    c = _get(db, user.company_id, customer_id)
    c.portal_token, c.portal_expires_at = None, None
    log_event(db, user.company_id, "portal_revoked", "customers", c.name, None, user.id, user.full_name)
    db.commit()


@router.get("/payment-proofs/pending")
def pending_proofs(user: User = Depends(require_permission("payments:write")), db: Session = Depends(get_db)):
    from app.models import PaymentProof
    names = dict(db.execute(select(Customer.id, Customer.name).where(Customer.company_id == user.company_id)).all())
    return [{"id": p.id, "customer_id": p.customer_id, "customer": names.get(p.customer_id), "amount": p.amount, "reference": p.reference, "note": p.note,
             "attachment_id": p.attachment_id, "created_at": p.created_at}
            for p in db.scalars(select(PaymentProof).where(PaymentProof.company_id == user.company_id, PaymentProof.status == "pending")
                                .order_by(PaymentProof.id)).all()]


class ProofDecision(BaseModel):
    approve: bool = True
    account_id: int | None = None
    method: str = "bank"


@router.post("/payment-proofs/{proof_id}")
def decide_proof(proof_id: int, payload: ProofDecision, user: User = Depends(require_permission("payments:write")), db: Session = Depends(get_db)):
    from app.models import PaymentProof
    from app.services.sales_ops import receive_from_customer
    pr = db.get(PaymentProof, proof_id)
    if not pr or pr.company_id != user.company_id or pr.status != "pending":
        raise HTTPException(404, "Payment notice not found")
    if payload.approve:
        receive_from_customer(db, user, pr.customer_id, pr.amount, payload.method, pr.reference or "Portal payment", payload.account_id, None)
    pr.status = "confirmed" if payload.approve else "rejected"
    db.commit()
    return {"status": pr.status}
