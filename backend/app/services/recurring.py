"""Recurring invoices: on (or after) next_date an invoice is created, optionally emailed, and next_date moves forward."""
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Company, Customer, RecurringInvoice, User
from app.services.companies import company_owner


def _add_months(d: date, months: int) -> date:
    y, m = divmod(d.month - 1 + months, 12)
    return date(d.year + y, m + 1, min(d.day, 28))


def run_company(db: Session, cid: int) -> int:
    from app.api.sales import manual_invoice
    from app.core.config import settings
    from app.services import email as mail
    from app.services.sales_ops import ensure_public_token
    owner: User | None = company_owner(db, cid)
    if not owner:
        return 0
    created = 0
    today = date.today()
    for r in db.scalars(select(RecurringInvoice).where(RecurringInvoice.company_id == cid, RecurringInvoice.is_active.is_(True),
                                                       RecurringInvoice.next_date <= today)).all():
        while r.is_active and r.next_date <= today:
            if r.end_date and r.next_date > r.end_date:
                r.is_active = False
                break
            inv = manual_invoice(db, owner, r.customer_id, r.amount, r.due_days, description=r.description, recurring_id=r.id)
            r.last_invoice_id = inv.id
            created += 1
            cust = db.get(Customer, r.customer_id)
            if r.send_email and cust and cust.email:
                company = db.get(Company, cid)
                link = f"{settings.PUBLIC_APP_URL.rstrip('/')}/i/{ensure_public_token(inv)}"
                mail.queue(db, cust.email, f"فاتورة {inv.number} — {company.name}",
                           mail.layout(f"فاتورة {inv.number}", f"<p>{r.description}: <b>{inv.total:,.2f}</b></p>", company.name, ("اعرض الفاتورة", link)),
                           "invoice", cid)
            r.next_date = _add_months(r.next_date, r.interval_months)
    db.commit()
    return created


def run_all() -> None:
    from app.core.database import SessionLocal
    with SessionLocal() as db:
        for cid in db.scalars(select(Company.id).where(Company.is_active.is_(True))).all():
            run_company(db, cid)
