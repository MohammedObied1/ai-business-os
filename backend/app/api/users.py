from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import get_current_user, require_permission
from app.core.security import hash_password, validate_password
from app.models import Role, User
from app.schemas.auth import RoleIn, RoleOut, UserCreate, UserOut, UserUpdate
from app.services.companies import email_taken

router = APIRouter(prefix="/users", tags=["users & roles"])


def _check_warehouses(db: Session, cid: int, ids: list[int] | None) -> list[int] | None:
    """A JSON list isn't covered by the tenant guard: every id must be one of this company's warehouses."""
    if not ids:
        return None
    from app.models import Warehouse
    own = set(db.scalars(select(Warehouse.id).where(Warehouse.company_id == cid, Warehouse.id.in_(ids))).all())
    if own != set(ids):
        raise HTTPException(404, "Warehouse not found")
    return sorted(own)


@router.get("", response_model=list[UserOut])
def list_users(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return db.scalars(select(User).where(User.company_id == user.company_id)).all()


@router.post("", response_model=UserOut, status_code=201)
def create_user(payload: UserCreate, user: User = Depends(require_permission("users:write")), db: Session = Depends(get_db)):
    if email_taken(db, payload.email):
        raise HTTPException(400, "Email already exists")
    from app.api.org import plan_limit
    limit = plan_limit(db, user.company_id, "max_users")
    if limit and (db.scalar(select(func.count(User.id)).where(User.company_id == user.company_id, User.is_active.is_(True))) or 0) >= limit:
        raise HTTPException(403, f"Your plan allows {limit} user(s). Contact the platform admin to upgrade.")
    if (err := validate_password(payload.password)) is not None:
        raise HTTPException(400, err)
    if payload.role_id:
        role = db.get(Role, payload.role_id)
        if not role or role.company_id != user.company_id:
            raise HTTPException(404, "Role not found")
    u = User(company_id=user.company_id, email=payload.email.strip().lower(), full_name=payload.full_name, department=payload.department,
             hashed_password=hash_password(payload.password), role_id=payload.role_id, branch_id=payload.branch_id, phone=payload.phone,
             allowed_warehouse_ids=_check_warehouses(db, user.company_id, payload.allowed_warehouse_ids))
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


@router.patch("/{user_id}", response_model=UserOut)
def update_user(user_id: int, payload: UserUpdate, user: User = Depends(require_permission("users:write")), db: Session = Depends(get_db)):
    u = db.get(User, user_id)
    if not u or u.company_id != user.company_id:
        raise HTTPException(404, "User not found")
    data = payload.model_dump(exclude_unset=True)
    if "role_id" in data and data["role_id"]:
        role = db.get(Role, data["role_id"])
        if not role or role.company_id != user.company_id:
            raise HTTPException(404, "Role not found")
    if u.id == user.id and (data.get("is_active") is False or ("role_id" in data and data["role_id"] != u.role_id)):
        raise HTTPException(400, "You cannot deactivate yourself or change your own role")
    if data.get("password"):
        if (err := validate_password(data["password"])) is not None:
            raise HTTPException(400, err)
        u.hashed_password = hash_password(data.pop("password"))
    data.pop("password", None)
    if "allowed_warehouse_ids" in data:
        data["allowed_warehouse_ids"] = _check_warehouses(db, user.company_id, data["allowed_warehouse_ids"])
    for k, v in data.items():
        setattr(u, k, v)
    db.commit()
    db.refresh(u)
    return u


@router.get("/roles", response_model=list[RoleOut])
def list_roles(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    from app.core.permissions import ALL_GRANULAR, effective
    out = []
    for r in db.scalars(select(Role).where(Role.company_id == user.company_id)).all():
        held = effective(r.permissions)
        out.append(RoleOut.model_validate(r).model_copy(update={"granted": ALL_GRANULAR if "*" in held else [p for p in ALL_GRANULAR if p in held]}))
    return out


def _check_perms(perms: list[str]) -> None:
    from app.core.permissions import ALL_GRANULAR, LEGACY
    unknown = [p for p in perms if p != "*" and p not in LEGACY and p not in ALL_GRANULAR]
    if unknown:
        raise HTTPException(400, f"Unknown permission(s): {', '.join(unknown)}")


@router.post("/roles", response_model=RoleOut, status_code=201)
def create_role(payload: RoleIn, user: User = Depends(require_permission("users:write")), db: Session = Depends(get_db)):
    _check_perms(payload.permissions)
    r = Role(company_id=user.company_id, **payload.model_dump())
    db.add(r)
    db.commit()
    db.refresh(r)
    return r


@router.put("/roles/{role_id}", response_model=RoleOut)
def update_role(role_id: int, payload: RoleIn, user: User = Depends(require_permission("users:write")), db: Session = Depends(get_db)):
    r = db.get(Role, role_id)
    if not r or r.company_id != user.company_id:
        raise HTTPException(404, "Role not found")
    _check_perms(payload.permissions)
    if "*" in (r.permissions or []) and "*" not in payload.permissions:
        raise HTTPException(400, "The owner role keeps full access")
    for k, v in payload.model_dump().items():
        setattr(r, k, v)
    db.commit()
    db.refresh(r)
    return r


@router.get("/permissions")
def permissions(user: User = Depends(get_current_user)):
    """Legacy flat list (kept for old clients)."""
    from app.services.companies import ALL_PERMISSIONS
    return ALL_PERMISSIONS


@router.get("/permission-catalog")
def permission_catalog(user: User = Depends(get_current_user)):
    """Granular permissions grouped for the role editor."""
    from app.core.permissions import catalog_for_ui
    return catalog_for_ui()
