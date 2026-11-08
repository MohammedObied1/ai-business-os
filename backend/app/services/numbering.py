from datetime import date

from sqlalchemy import func, select
from sqlalchemy.orm import Session


def next_number(db: Session, model, company_id: int, prefix: str) -> str:
    """Generates SO-2026-0001 style sequential numbers per company and year."""
    year = date.today().year
    count = db.scalar(
        select(func.count(model.id)).where(model.company_id == company_id, model.number.like(f"{prefix}-{year}-%"))
    ) or 0
    return f"{prefix}-{year}-{count + 1:04d}"
