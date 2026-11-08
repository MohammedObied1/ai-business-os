"""Endpoints that work without logging in: shared invoice links and company logos."""
import os

from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models import Alert, Company, Customer, Invoice, PaymentProof, Product, SalesOrder, StockLevel
from app.schemas.sales import InvoiceDetail

router = APIRouter(prefix="/public", tags=["public"])


@router.get("/invoices/{token}", response_model=InvoiceDetail)
def shared_invoice(token: str, db: Session = Depends(get_db)):
    if len(token) < 20:
        raise HTTPException(404, "Invoice not found")
    inv = db.scalar(select(Invoice).where(Invoice.public_token == token))
    company = db.get(Company, inv.company_id) if inv else None
    if not inv or not company or not company.is_active:
        raise HTTPException(404, "Invoice not found")
    from app.api.sales import invoice_detail_for
    return invoice_detail_for(db, inv)


@router.get("/logo/{company_id}")
def logo(company_id: int, db: Session = Depends(get_db)):
    c = db.get(Company, company_id)
    if not c or not c.logo_path or not os.path.exists(c.logo_path):
        raise HTTPException(404, "No logo")
    return FileResponse(c.logo_path, headers={"Cache-Control": "public, max-age=300"})



# ---------------------------------------------------------------- white-label branding
@router.get("/brand")
def brand(host: str | None = None, slug: str | None = None, db: Session = Depends(get_db)):
    """Company name / logo / colour for a custom domain or shop link, so the login page can show the company's brand."""
    c = None
    if host:
        c = db.scalar(select(Company).where(func.lower(Company.custom_domain) == host.split(":")[0].lower(), Company.is_active.is_(True),
                                            Company.domain_verified_at.is_not(None)))
    if not c and slug:
        c = db.scalar(select(Company).where(Company.slug == slug.lower(), Company.is_active.is_(True)))
    if not c:
        return None
    return {"id": c.id, "name": c.name, "logo": bool(c.logo_path), "logo_version": c.logo_path, "brand_color": c.brand_color, "slug": c.slug}


@router.get("/domain-check")
def domain_check(domain: str, db: Session = Depends(get_db)):
    """Asked by Caddy before issuing an HTTPS certificate for a company's own domain."""
    if not db.scalar(select(Company.id).where(func.lower(Company.custom_domain) == domain.lower(), Company.is_active.is_(True),
                                              Company.domain_verified_at.is_not(None))):
        raise HTTPException(404, "Unknown domain")
    return {"ok": True}


# ---------------------------------------------------------------- customer portal
def _portal_customer(db: Session, token: str) -> Customer:
    """The only thing that identifies the customer is the secret token — never an id from the browser."""
    c = db.scalar(select(Customer).where(Customer.portal_token == token)) if token and len(token) >= 20 else None
    company = db.get(Company, c.company_id) if c else None
    if not c or not company or not company.is_active:
        raise HTTPException(404, "This link is not valid")
    if c.portal_expires_at and c.portal_expires_at <= datetime.utcnow():
        raise HTTPException(410, "This link has expired. Ask the company for a new one.")
    return c


def _intake_status(company: Company) -> str:
    """Orders from the shop or the portal arrive as the company chose: a quotation or a draft sales order. Never confirmed —
    staff always confirm (stock and credit checks run then)."""
    return company.online_order_status if company.online_order_status in ("quotation", "draft") else "quotation"


@router.get("/portal/{token}")
def portal(token: str, db: Session = Depends(get_db)):
    from app.api.customers import statement_rows
    from app.services.sales_ops import ensure_public_token
    c = _portal_customer(db, token)
    company = db.get(Company, c.company_id)
    invoices = db.scalars(select(Invoice).where(Invoice.customer_id == c.id, Invoice.status != "cancelled").order_by(Invoice.issue_date.desc()).limit(100)).all()
    for i in invoices:
        ensure_public_token(i)
    db.commit()
    st = statement_rows(db, c, None, None)
    proofs = db.scalars(select(PaymentProof).where(PaymentProof.customer_id == c.id).order_by(PaymentProof.id.desc()).limit(20)).all()
    orders = db.scalars(select(SalesOrder).where(SalesOrder.customer_id == c.id, SalesOrder.company_id == c.company_id)
                        .order_by(SalesOrder.id.desc()).limit(50)).all()
    c.portal_last_seen_at = datetime.utcnow()
    db.commit()
    return {"customer": {"name": c.name, "phone": c.phone}, "company": {"id": company.id, "name": company.name, "phone": company.phone,
            "logo": bool(company.logo_path), "logo_version": company.logo_path, "currency": company.currency, "brand_color": company.brand_color,
            "payment_instructions": company.payment_instructions},
            "balance": st["closing"], "statement": st["rows"][-50:],
            "invoices": [{"number": i.number, "date": i.issue_date, "due": i.due_date, "total": i.total, "balance": i.balance, "status": i.status,
                          "currency": i.currency or company.currency, "token": i.public_token} for i in invoices],
            "proofs": [{"amount": pr.amount, "reference": pr.reference, "status": pr.status, "created_at": pr.created_at} for pr in proofs],
            "orders": [{"number": o.number, "date": o.order_date, "status": o.status, "total": o.total, "source": o.source} for o in orders],
            "installments": _portal_installments(db, invoices),
            "can_order": bool(company.portal_orders_enabled), "expires_at": c.portal_expires_at}


def _portal_installments(db: Session, invoices) -> list[dict]:
    from app.api.sales import installment_schedule
    out = []
    for i in invoices:
        if i.status in ("open", "partial", "overdue"):
            out += [{**s, "invoice": i.number, "remaining": round(s["amount"] - s["paid"], 2)} for s in installment_schedule(db, i) if s["status"] != "paid"]
    return sorted(out, key=lambda x: x["due_date"])


@router.get("/portal/{token}/catalog")
def portal_catalog(token: str, db: Session = Depends(get_db)):
    """Products the customer can ask for. Prices shown are the list price; the final price is set when staff confirm."""
    c = _portal_customer(db, token)
    company = db.get(Company, c.company_id)
    if not company.portal_orders_enabled:
        raise HTTPException(404, "Ordering from the portal is off")
    products = db.scalars(select(Product).where(Product.company_id == c.company_id, Product.is_active.is_(True)).order_by(Product.category, Product.name)).all()
    return [{"id": p.id, "name": p.name, "category": p.category, "price": p.sale_price, "unit": p.unit} for p in products if p.sale_price > 0]


class PortalOrderIn(BaseModel):
    note: str | None = None
    items: list[dict]  # [{product_id, quantity}]


@router.post("/portal/{token}/order", status_code=201)
def portal_order(token: str, payload: PortalOrderIn, db: Session = Depends(get_db)):
    """The customer asks for an order. It arrives as a quotation or draft (company setting) for staff to confirm."""
    from app.schemas.sales import OrderIn, OrderItemIn
    from app.services import webhooks
    from app.services.companies import company_owner
    from app.services.sales_ops import create_order
    c = _portal_customer(db, token)
    company = db.get(Company, c.company_id)
    if not company.portal_orders_enabled:
        raise HTTPException(404, "Ordering from the portal is off")
    valid = set(db.scalars(select(Product.id).where(Product.company_id == c.company_id, Product.is_active.is_(True))).all())
    items = []
    for i in payload.items[:100]:
        pid, qty = int(i.get("product_id") or 0), float(i.get("quantity") or 0)
        if qty > 0 and pid in valid:  # products of another company are silently dropped (tenant guard would refuse them anyway)
            items.append(OrderItemIn(product_id=pid, quantity=min(qty, 1_000_000)))
    if not items:
        raise HTTPException(400, "Order needs at least one item")
    recent = db.scalar(select(func.count(SalesOrder.id)).where(SalesOrder.customer_id == c.id, SalesOrder.source == "portal",
                                                                SalesOrder.created_at >= datetime.utcnow() - timedelta(hours=1))) or 0
    if recent >= 5:
        raise HTTPException(429, "Too many orders. Please call us.")
    order = create_order(db, company_owner(db, c.company_id), OrderIn(customer_id=c.id, status=_intake_status(company), items=items,
                                                                       notes=f"Portal request. {payload.note or ''}".strip()[:1000]), source="portal")
    db.add(Alert(company_id=c.company_id, severity="warning", category="sales", title=f"Order request {order.number} from {c.name}",
                 message=f"{order.total:,.2f}", recommended_action="Review and confirm the order", dedupe_key=f"portal:{order.id}"))
    webhooks.emit(db, c.company_id, "online_order.created", {"number": order.number, "customer": c.name, "total": order.total, "source": "portal"})
    db.commit()
    return {"number": order.number, "total": order.total, "status": order.status}


@router.post("/portal/{token}/payment-proof", status_code=201)
async def payment_proof(token: str, amount: float = Form(...), reference: str | None = Form(default=None), note: str | None = Form(default=None),
                        file: UploadFile | None = File(default=None), db: Session = Depends(get_db)):
    """The customer tells us they paid (e.g. bank transfer) and uploads the receipt. Staff confirm it into a real payment."""
    from app.api.ops import save_attachment
    c = _portal_customer(db, token)
    if amount <= 0:
        raise HTTPException(400, "Amount must be greater than zero")
    recent = db.scalar(select(func.count(PaymentProof.id)).where(PaymentProof.customer_id == c.id,
                                                                  PaymentProof.created_at >= datetime.utcnow() - timedelta(hours=1))) or 0
    if recent >= 5:
        raise HTTPException(429, "Too many requests. Try again later.")
    pr = PaymentProof(company_id=c.company_id, customer_id=c.id, amount=amount, reference=reference, note=note)
    db.add(pr)
    db.flush()
    if file is not None and file.filename:
        pr.attachment_id = save_attachment(db, c.company_id, "payment_proof", pr.id, file.filename, await file.read(), c.name).id
    db.add(Alert(company_id=c.company_id, severity="info", category="finance", title=f"Payment notice from {c.name}: {amount:,.2f}",
                 message=reference or note, recommended_action="Check the bank and confirm the payment", dedupe_key=f"proof:{pr.id}"))
    db.commit()
    return {"id": pr.id, "status": pr.status}


# ---------------------------------------------------------------- online shop
class ShopOrderIn(BaseModel):
    name: str
    phone: str
    address: str | None = None
    note: str | None = None
    items: list[dict]  # [{product_id, quantity}]


def _shop_company(db: Session, slug: str) -> Company:
    from app.services import saas
    c = db.scalar(select(Company).where(Company.slug == slug.lower()))
    if not c or not c.is_active or not c.catalog_enabled or not saas.has_feature(db, c.id, "online_store"):
        raise HTTPException(404, "Shop not found")
    return c


@router.get("/shop/{slug}")
def shop(slug: str, db: Session = Depends(get_db)):
    c = _shop_company(db, slug)
    stock = dict(db.execute(select(StockLevel.product_id, func.sum(StockLevel.quantity)).where(StockLevel.company_id == c.id)
                            .group_by(StockLevel.product_id)).all())
    products = db.scalars(select(Product).where(Product.company_id == c.id, Product.is_active.is_(True)).order_by(Product.category, Product.name)).all()
    return {"company": {"id": c.id, "name": c.name, "phone": c.phone, "address": c.address, "logo": bool(c.logo_path), "logo_version": c.logo_path,
                        "currency": c.currency, "brand_color": c.brand_color},
            "products": [{"id": p.id, "name": p.name, "category": p.category, "price": p.sale_price, "unit": p.unit,
                          "in_stock": float(stock.get(p.id, 0) or 0) > 0} for p in products if p.sale_price > 0]}


@router.post("/shop/{slug}/order", status_code=201)
def shop_order(slug: str, payload: ShopOrderIn, db: Session = Depends(get_db)):
    """An online order becomes a quotation or a draft order (company setting) for staff to confirm, plus an alert."""
    from app.schemas.sales import OrderIn, OrderItemIn
    from app.services import webhooks
    from app.services.companies import company_owner
    from app.services.sales_ops import create_order
    c = _shop_company(db, slug)
    phone = "".join(ch for ch in payload.phone if ch.isdigit() or ch == "+")
    if len(phone) < 7 or not payload.name.strip():
        raise HTTPException(400, "Please enter your name and a valid phone number")
    items = [OrderItemIn(product_id=int(i["product_id"]), quantity=float(i["quantity"])) for i in payload.items if float(i.get("quantity") or 0) > 0]
    if not items:
        raise HTTPException(400, "Order needs at least one item")
    cust = db.scalar(select(Customer).where(Customer.company_id == c.id, Customer.phone == phone))
    if cust:
        recent = db.scalar(select(func.count(SalesOrder.id)).where(SalesOrder.customer_id == cust.id, SalesOrder.source == "online",
                                                                    SalesOrder.created_at >= datetime.utcnow() - timedelta(hours=1))) or 0
        if recent >= 5:
            raise HTTPException(429, "Too many orders. Please call us.")
    else:
        cust = Customer(company_id=c.id, name=payload.name.strip()[:200], phone=phone, address=payload.address, customer_type="individual",
                        notes="Created from the online shop")
        db.add(cust)
        db.flush()
    owner = company_owner(db, c.id)
    order = create_order(db, owner, OrderIn(customer_id=cust.id, status=_intake_status(c), items=items,
                                            notes=f"Online order. {payload.address or ''} {payload.note or ''}".strip()), source="online")
    db.add(Alert(company_id=c.id, severity="warning", category="sales", title=f"New online order {order.number}: {cust.name}",
                 message=f"{phone} · {order.total:,.2f}", recommended_action="Call the customer and confirm the order", dedupe_key=f"online:{order.id}"))
    webhooks.emit(db, c.id, "online_order.created", {"number": order.number, "customer": cust.name, "phone": phone, "total": order.total})
    db.commit()
    return {"number": order.number, "total": order.total}
