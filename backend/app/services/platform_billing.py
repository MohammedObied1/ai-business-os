"""The platform owner's billing: one subscription invoice per company per month."""
from datetime import date, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Company, Plan, PlatformInvoice
from app.services import email as mail
from app.services.companies import company_owner


def create_invoice(db: Session, company: Company, amount: float, period: str, plan_name: str | None = None, note: str | None = None) -> PlatformInvoice:
    n = (db.scalar(select(func.count(PlatformInvoice.id))) or 0) + 1
    inv = PlatformInvoice(company_id=company.id, number=f"SUB-{date.today().year}-{n:05d}", period=period, plan_name=plan_name,
                          amount=round(amount, 2), due_date=date.today() + timedelta(days=7), note=note)
    db.add(inv)
    db.flush()
    owner = company_owner(db, company.id)
    if owner:
        body = (f"<p>مرحبا {owner.full_name},</p><p>فاتورة اشتراك شهر {period} بقيمة <b>{amount:,.2f}</b>. "
                f"آخر موعد للدفع {inv.due_date}.</p><p>شكراً لاستخدامكم النظام.</p>")
        mail.queue(db, owner.email, f"فاتورة الاشتراك {inv.number}", mail.layout("فاتورة اشتراك", body), "billing", company.id)
    return inv


def generate_monthly(db: Session) -> int:
    period = date.today().strftime("%Y-%m")
    created = 0
    for c in db.scalars(select(Company).where(Company.is_active.is_(True), Company.plan_id.is_not(None))).all():
        plan = db.get(Plan, c.plan_id)
        if not plan or plan.price_monthly <= 0:
            continue
        if db.scalar(select(PlatformInvoice.id).where(PlatformInvoice.company_id == c.id, PlatformInvoice.period == period, PlatformInvoice.status != "void")):
            continue
        create_invoice(db, c, plan.price_monthly, period, plan.name)
        created += 1
    db.commit()
    return created


def billing_job() -> None:
    from app.core.database import SessionLocal
    if date.today().day != 1:
        return
    with SessionLocal() as db:
        generate_monthly(db)
