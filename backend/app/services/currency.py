"""Currencies: every company has a base currency (Company.currency); other currencies carry a manual exchange rate
(how many base units one foreign unit is worth). Documents store the rate they were made at."""
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Company, Currency


def base(db: Session, cid: int) -> str:
    return db.get(Company, cid).currency


def normalize(db: Session, cid: int, code: str | None) -> str | None:
    """None for the base currency, otherwise the upper-case code (must be defined for the company)."""
    if not code:
        return None
    code = code.strip().upper()
    if code == base(db, cid):
        return None
    rate(db, cid, code)
    return code


def rate(db: Session, cid: int, code: str | None) -> float:
    if not code or code == base(db, cid):
        return 1.0
    c = db.scalar(select(Currency).where(Currency.company_id == cid, Currency.code == code.upper()))
    if not c:
        raise HTTPException(400, f"Currency {code} is not set up. Add it with its exchange rate first.")
    return c.rate


def code_or_base(db: Session, cid: int, code: str | None) -> str:
    return code or base(db, cid)
