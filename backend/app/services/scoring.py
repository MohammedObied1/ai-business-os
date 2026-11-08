"""Customer scoring (0-100): recency, frequency, monetary value, payment behaviour."""
from datetime import date, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Customer, Invoice, SalesOrder


def score_customer(db: Session, cid: int, customer: Customer) -> float:
    rev, cnt, last = db.execute(
        select(func.coalesce(func.sum(SalesOrder.total), 0), func.count(SalesOrder.id), func.max(SalesOrder.order_date)).where(
            SalesOrder.customer_id == customer.id, SalesOrder.company_id == cid, SalesOrder.status.in_(("confirmed", "delivered"))
        )
    ).one()
    overdue = db.scalar(
        select(func.count(Invoice.id)).where(
            Invoice.customer_id == customer.id, Invoice.status.in_(("open", "partial", "overdue")), Invoice.due_date < date.today()
        )
    )
    max_rev = db.scalar(
        select(func.max(SalesOrder.total)).where(SalesOrder.company_id == cid)
    ) or 1
    monetary = min(float(rev) / (max_rev * 5), 1.0) * 40
    frequency = min(cnt / 10, 1.0) * 25
    if last:
        days = (date.today() - last).days
        recency = max(0.0, 1 - days / 180) * 25
    else:
        recency = 0
    payment = max(0.0, 1 - overdue / 3) * 10
    return round(monetary + frequency + recency + payment, 1)


def rescore_all(db: Session, cid: int) -> int:
    customers = db.scalars(select(Customer).where(Customer.company_id == cid)).all()
    for c in customers:
        c.score = score_customer(db, cid, c)
    db.commit()
    return len(customers)
