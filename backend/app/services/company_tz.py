"""Small helper so "today" and day boundaries follow the company's own timezone, not the server's."""
from datetime import date, datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Company

# a short, curated list — not all ~400 IANA zones, just what a company picking their country would look for
COMMON_TIMEZONES = [
    "Asia/Hebron", "Asia/Gaza", "Asia/Amman", "Asia/Beirut", "Asia/Damascus", "Asia/Baghdad", "Asia/Riyadh",
    "Asia/Kuwait", "Asia/Qatar", "Asia/Dubai", "Africa/Cairo", "Africa/Tripoli", "Africa/Tunis", "Africa/Algiers",
    "Africa/Casablanca", "Europe/Istanbul", "Europe/London", "Europe/Berlin", "America/New_York", "America/Chicago",
    "America/Los_Angeles", "UTC",
]


def company_tz(db: Session, cid: int) -> str:
    return db.scalar(select(Company.timezone).where(Company.id == cid)) or "UTC"


def company_today(db: Session, cid: int) -> date:
    try:
        return datetime.now(ZoneInfo(company_tz(db, cid))).date()
    except ZoneInfoNotFoundError:
        return date.today()
