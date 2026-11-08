"""Shared FastAPI dependencies: current user, tenant scoping, permissions."""
from datetime import date, datetime, timezone
from typing import TypeVar

from fastapi import Depends, Header, HTTPException, Request, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.audit import set_actor
from app.core.database import get_db
from app.core.security import decode_token, sha256
from app.models.company import Company, PlatformAdmin, User

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login", auto_error=False)

M = TypeVar("M")


def _check_company(company: Company | None, impersonated: bool) -> None:
    # an impersonating platform admin can still open a suspended/expired company to help fix it
    if not company or (not company.is_active and not impersonated):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Company account is suspended")
    if company.subscription_ends_at and company.subscription_ends_at < date.today() and not impersonated:
        raise HTTPException(status_code=status.HTTP_402_PAYMENT_REQUIRED, detail="Subscription expired")


_KEY_CALLS: dict[int, list[float]] = {}  # key id -> recent call timestamps, for the per-minute rate limit (in-process)


def _rate_limited(key_id: int, per_min: int) -> bool:
    import time
    now = time.monotonic()
    calls = [t for t in _KEY_CALLS.get(key_id, []) if now - t < 60]
    calls.append(now)
    _KEY_CALLS[key_id] = calls
    return len(calls) > max(1, per_min)


def _user_from_api_key(key: str, db: Session) -> User:
    from app.models import ApiKey
    k = db.scalar(select(ApiKey).where(ApiKey.key_hash == sha256(key), ApiKey.is_active.is_(True)))
    user = db.get(User, k.user_id) if k else None
    if not k or not user or not user.is_active or user.company_id != k.company_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid API key")
    if k.expires_at and k.expires_at < datetime.utcnow():
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="API key expired")
    if _rate_limited(k.id, k.rate_limit_per_min or 120):
        raise HTTPException(status_code=429, detail="Rate limit exceeded for this API key")
    k.last_used_at = datetime.utcnow()
    k.request_count = (k.request_count or 0) + 1
    if k.scopes:
        user._api_scopes = k.scopes  # further ceiling on top of the user's own permissions, checked in has_permission()
    return user


def client_ip(request: Request | None) -> str | None:
    """Real client address (Caddy / a proxy puts it in X-Forwarded-For)."""
    if request is None:
        return None
    fwd = request.headers.get("x-forwarded-for")
    return (fwd.split(",")[0].strip() if fwd else (request.client.host if request.client else None))


def get_current_user(request: Request, token: str | None = Depends(oauth2_scheme), x_api_key: str | None = Header(default=None),
                     db: Session = Depends(get_db)) -> User:
    ip, ua = client_ip(request), request.headers.get("user-agent")
    reason = request.headers.get("x-audit-reason")  # optional: the UI can send why a change is made
    if not token and x_api_key:
        user = _user_from_api_key(x_api_key, db)
        _check_company(db.get(Company, user.company_id), False)
        from app.services import saas
        saas.require_feature(db, user.company_id, "api")
        saas.consume(db, user.company_id, "api_requests", "max_api_requests")
        set_actor(db, user, ip=ip, user_agent=f"API key · {ua or ''}", reason=reason)
        db.info["via_api_key"] = True
        return user
    payload = decode_token(token) if token else None
    if not payload or payload.get("scope", "company") != "company":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token")
    user = db.get(User, int(payload["sub"]))
    if not user or not user.is_active or user.company_id != payload.get("cid"):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found or inactive")
    if payload.get("tv", 0) != (user.token_version or 0) and not payload.get("imp"):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Signed out. Please sign in again.")
    _check_company(db.get(Company, user.company_id), bool(payload.get("imp")))
    set_actor(db, user, impersonated=bool(payload.get("imp")), ip=ip, user_agent=ua, impersonated_by=payload.get("imp"), reason=reason)
    db.info["impersonated"] = bool(payload.get("imp"))
    return user


def get_platform_admin(token: str | None = Depends(oauth2_scheme), db: Session = Depends(get_db)) -> PlatformAdmin:
    payload = decode_token(token) if token else None
    if not payload or payload.get("scope") != "platform":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Platform admin login required")
    admin = db.get(PlatformAdmin, int(payload["sub"]))
    if not admin or not admin.is_active or payload.get("tv", 0) != (admin.token_version or 0):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Platform admin not found or inactive")
    return admin


def local_day_utc(d: date, tz: str | None = None) -> tuple[datetime, datetime]:
    """Start/end of a local calendar day expressed in UTC (timestamps are stored in UTC). Pass the company's own
    `timezone` when the day boundary matters for that company — a rep's "today" or "daily" report should follow
    where the business is, not where the server happens to run. Without one, falls back to the server's own clock."""
    if tz:
        from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
        try:
            zone = ZoneInfo(tz)
        except ZoneInfoNotFoundError:
            zone = None
        if zone:
            start_local = datetime.combine(d, datetime.min.time(), tzinfo=zone)
            end_local = datetime.combine(d, datetime.max.time(), tzinfo=zone)
            return start_local.astimezone(timezone.utc).replace(tzinfo=None), end_local.astimezone(timezone.utc).replace(tzinfo=None)
    offset = datetime.now() - datetime.utcnow()
    start = datetime.combine(d, datetime.min.time()) - offset
    return start, start + (datetime.combine(d, datetime.max.time()) - datetime.combine(d, datetime.min.time()))


def owned(db: Session, model: type[M], obj_id: int | None, company_id: int, label: str = "Record") -> M:
    """Fetch a row by id and make sure it belongs to the caller's company (404 otherwise)."""
    obj = db.get(model, obj_id) if obj_id else None
    if not obj or getattr(obj, "company_id", None) != company_id:
        raise HTTPException(404, f"{label} not found")
    return obj


def has_permission(user: User, perm: str) -> bool:
    """Legacy (`sales:read`) and granular (`sales.discount`) names both work; see core/permissions.py.
    An API key with scopes narrows this further: the request must pass the user's own role AND the key's scopes."""
    from app.core.permissions import effective
    held = effective(user.role.permissions if user.role else [])
    if not ("*" in held or perm in held):
        return False
    scopes = getattr(user, "_api_scopes", None)
    if scopes:
        scoped = effective(scopes)
        return "*" in scoped or perm in scoped
    return True


def branch_scope(user: User) -> int | None:
    """Branch the user is limited to (None = sees every branch). Owners/managers with '*' always see everything."""
    return None if has_permission(user, "branches:all") else user.branch_id


def warehouse_scope(user: User) -> set[int] | None:
    """Warehouses the user may work in (None = all)."""
    ids = set(user.allowed_warehouse_ids or [])
    return None if not ids or has_permission(user, "warehouses.all") else ids


def check_warehouse(user: User, warehouse_id: int | None) -> None:
    scope = warehouse_scope(user)
    if warehouse_id and scope is not None and warehouse_id not in scope:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "You are not allowed to work in this warehouse")


def can_see_cost(user: User) -> bool:
    return has_permission(user, "products.view_cost")


def require_feature(feature: str):
    """Dependency: the company's plan must include this feature (plans without a feature list include everything)."""

    def checker(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> User:
        from app.services import saas
        saas.require_feature(db, user.company_id, feature)
        return user

    return checker


def require_permission(*permissions: str):
    """Dependency factory: user must hold ALL listed permissions (or the wildcard '*')."""

    def checker(user: User = Depends(get_current_user)) -> User:
        missing = [p for p in permissions if not has_permission(user, p)]
        if missing:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Missing permission(s): {', '.join(missing)}",
            )
        return user

    return checker
