"""Creating, inspecting and deleting tenant companies."""
from fastapi import HTTPException
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.core.database import Base
from app.core.security import hash_password, validate_password
from app.models import Company, Customer, Invoice, PlatformAdmin, Product, Role, SalesOrder, User
from app.services.automation import ensure_default_rules

DEFAULT_ROLES = {
    "Company Owner": ["*"],
    "General Manager": ["*"],
    "Sales Manager": ["customers:read", "customers:write", "customers:delete", "sales:read", "sales:write", "invoices:create", "payments:write",
                      "returns:create", "pos:use", "reports:read", "ai:use", "inventory:read"],
    "Finance Manager": ["finance:read", "finance:write", "invoices:create", "payments:write", "purchasing:approve", "purchasing:read", "reports:read", "ai:use",
                        "customers:read", "sales:read", "accounts:read", "accounts:write", "returns:create", "hr:read", "audit:read",
                        "accounting:read", "accounting:write", "approvals:approve", "branches:all"],
    "Sales Employee": ["customers:read", "customers:write", "sales:read", "sales:write", "invoices:create", "inventory:read", "pos:use", "payments:write"],
    "Accountant": ["finance:read", "finance:write", "payments:write", "reports:read", "customers:read", "sales:read", "accounts:read", "accounts:write",
                   "purchasing:read", "hr:read", "accounting:read", "accounting:write", "branches:all"],
    "Warehouse Employee": ["inventory:read", "inventory:write", "purchasing:read", "purchasing:write"],
    "Cashier": ["pos:use", "sales:read", "customers:read", "customers:write", "inventory:read", "payments:write", "invoices:create"],
    "HR Manager": ["hr:read", "hr:write", "accounts:read"],
    "Warehouse Manager": ["inventory:read", "inventory:write", "inventory.approve_adjustment", "purchasing:read", "purchasing:write", "sales:read"],
    "Sales Representative": ["customers.view", "customers.create", "sales.view", "sales.create", "finance.create_payment", "field.rep",
                             "field.track_location", "inventory.view"],
    "Driver": ["deliveries.driver"],
}

ALL_PERMISSIONS = sorted({p for perms in DEFAULT_ROLES.values() for p in perms if p != "*"} | {"users:write", "settings:write", "automation:write",
                                                                                             "documents:write", "purchasing:write"})


def sync_default_roles(db: Session) -> None:
    """Give existing companies the new default roles / permissions added in later versions (never removes anything)."""
    for cid in db.scalars(select(Company.id)).all():
        roles = {r.name: r for r in db.scalars(select(Role).where(Role.company_id == cid)).all()}
        for name, perms in DEFAULT_ROLES.items():
            r = roles.get(name)
            if not r:
                db.add(Role(company_id=cid, name=name, permissions=perms))
            elif "*" not in (r.permissions or []):
                missing = [p for p in perms if p not in (r.permissions or [])]
                if missing:
                    r.permissions = list(r.permissions or []) + missing
    db.commit()


def create_default_roles(db: Session, cid: int) -> dict[str, Role]:
    roles = {}
    for name, perms in DEFAULT_ROLES.items():
        r = Role(company_id=cid, name=name, permissions=perms)
        db.add(r)
        roles[name] = r
    db.flush()
    return roles


def email_taken(db: Session, email: str) -> bool:
    email = email.strip().lower()
    return bool(db.scalar(select(User.id).where(func.lower(User.email) == email)) or db.scalar(select(PlatformAdmin.id).where(func.lower(PlatformAdmin.email) == email)))


def create_company(db: Session, *, name: str, owner_name: str, owner_email: str, password: str, currency: str = "ILS",
                   industry: str | None = None, **extra) -> tuple[Company, User]:
    if email_taken(db, owner_email):
        raise HTTPException(400, "Email already registered")
    if (err := validate_password(password)) is not None:
        raise HTTPException(400, err)
    company = Company(name=name.strip(), currency=currency, industry=industry, **{k: v for k, v in extra.items() if v is not None})
    db.add(company)
    db.flush()
    roles = create_default_roles(db, company.id)
    owner = User(company_id=company.id, email=owner_email.strip().lower(), full_name=owner_name.strip(),
                 hashed_password=hash_password(password), role_id=roles["Company Owner"].id, department="Management")
    db.add(owner)
    db.commit()
    ensure_default_rules(db, company.id)
    db.refresh(company)
    return company, owner


def company_owner(db: Session, cid: int) -> User | None:
    users = db.scalars(select(User).where(User.company_id == cid).order_by(User.id)).all()
    return next((u for u in users if u.role and "*" in (u.role.permissions or [])), users[0] if users else None)


def company_stats(db: Session, cid: int) -> dict:
    count = lambda model: db.scalar(select(func.count(model.id)).where(model.company_id == cid)) or 0  # noqa: E731
    revenue = db.scalar(select(func.coalesce(func.sum(SalesOrder.total), 0)).where(
        SalesOrder.company_id == cid, SalesOrder.status.in_(("confirmed", "delivered")))) or 0
    last_order = db.scalar(select(func.max(SalesOrder.order_date)).where(SalesOrder.company_id == cid))
    return {"users": count(User), "customers": count(Customer), "products": count(Product), "orders": count(SalesOrder),
            "invoices": count(Invoice), "revenue": round(float(revenue), 2), "last_order": last_order}


def delete_company(db: Session, cid: int) -> None:
    """Remove the company and every row that belongs to it (children first)."""
    for table in reversed(Base.metadata.sorted_tables):
        if "company_id" in table.c:
            db.execute(delete(table).where(table.c.company_id == cid))
    db.execute(delete(Company).where(Company.id == cid))
    db.commit()


def ensure_platform_admin(db: Session, email: str, password: str) -> PlatformAdmin | None:
    """Create the first platform admin if none exists yet."""
    if db.scalar(select(PlatformAdmin.id)):
        return None
    admin = PlatformAdmin(email=email.strip().lower(), full_name="Platform Admin", hashed_password=hash_password(password))
    db.add(admin)
    db.commit()
    return admin
