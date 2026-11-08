from datetime import date, datetime, timedelta

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.core.deps import get_current_user, oauth2_scheme, require_permission
from app.core.security import (
    create_access_token, create_platform_token, decode_token, hash_password, new_totp_secret, random_token, sha256, totp_uri, validate_password,
    verify_password, verify_totp,
)
from app.models import Company, LoginEvent, PasswordResetToken, PlatformAdmin, User
from app.schemas.auth import CompanyOut, CompanyUpdate, PasswordChange, RegisterCompany, Token, UserOut
from app.services import email as mail
from app.services.companies import DEFAULT_ROLES, create_company, create_default_roles  # noqa: F401  (re-exported for scripts.seed)

router = APIRouter(prefix="/auth", tags=["auth"])


class OtpIn(BaseModel):
    code: str


class DisableOtpIn(BaseModel):
    password: str
    code: str


class ForgotIn(BaseModel):
    email: str
    lang: str = "ar"


class ResetIn(BaseModel):
    token: str
    new_password: str


def _log(db: Session, request: Request, email: str, success: bool, reason: str, user: User | None = None, admin: PlatformAdmin | None = None) -> None:
    db.add(LoginEvent(email=email, success=success, reason=reason, user_id=user.id if user else None, admin_id=admin.id if admin else None,
                      company_id=user.company_id if user else None, ip=request.client.host if request.client else None,
                      user_agent=(request.headers.get("user-agent") or "")[:300]))


def _check_lock(acct) -> None:
    if acct.locked_until and acct.locked_until > datetime.utcnow():
        mins = int((acct.locked_until - datetime.utcnow()).total_seconds() // 60) + 1
        raise HTTPException(429, f"Too many failed attempts. Try again in {mins} minutes.")


def _failed(db: Session, acct) -> None:
    acct.failed_logins = (acct.failed_logins or 0) + 1
    if acct.failed_logins >= settings.LOGIN_MAX_ATTEMPTS:
        acct.locked_until = datetime.utcnow() + timedelta(minutes=settings.LOGIN_LOCK_MINUTES)
        acct.failed_logins = 0


@router.post("/register", response_model=Token)
def register(payload: RegisterCompany, db: Session = Depends(get_db)):
    if not settings.ALLOW_PUBLIC_SIGNUP:
        raise HTTPException(403, "New companies are created by the platform admin")
    company, owner = create_company(db, name=payload.company_name, owner_name=payload.owner_name, owner_email=payload.owner_email,
                                    password=payload.password, currency=payload.currency, industry=payload.industry)
    return Token(access_token=create_access_token(owner.id, company.id))


@router.post("/login", response_model=Token)
def login(request: Request, username: str = Form(...), password: str = Form(...), otp: str | None = Form(default=None), db: Session = Depends(get_db)):
    """Email + password (+ 6-digit code when two-step verification is on). Works for company users and the platform admin."""
    email = username.strip().lower()
    user = db.scalar(select(User).where(func.lower(User.email) == email))
    admin = None if user else db.scalar(select(PlatformAdmin).where(func.lower(PlatformAdmin.email) == email))
    acct = user or admin
    if not acct:
        _log(db, request, email, False, "unknown")
        db.commit()
        raise HTTPException(401, "Incorrect email or password")
    _check_lock(acct)
    if not verify_password(password, acct.hashed_password):
        _failed(db, acct)
        _log(db, request, email, False, "bad_password", user, admin)
        db.commit()
        raise HTTPException(401, "Incorrect email or password")
    if not acct.is_active:
        raise HTTPException(403, "User is inactive")
    if user:
        company = db.get(Company, user.company_id)
        if not company or not company.is_active:
            raise HTTPException(403, "Company account is suspended")
        if company.subscription_ends_at and company.subscription_ends_at < date.today():
            raise HTTPException(402, "Subscription expired")
    if acct.totp_enabled:
        if not otp:
            _log(db, request, email, False, "2fa_required", user, admin)
            db.commit()
            raise HTTPException(401, "2FA code required")
        if not verify_totp(acct.totp_secret, otp):
            _failed(db, acct)
            _log(db, request, email, False, "2fa_failed", user, admin)
            db.commit()
            raise HTTPException(401, "Wrong verification code")
    acct.failed_logins, acct.locked_until = 0, None
    _log(db, request, email, True, "ok", user, admin)
    if user:
        user.last_login_at = datetime.utcnow()
        db.commit()
        return Token(access_token=create_access_token(user.id, user.company_id, token_version=user.token_version), kind="company")
    db.commit()
    return Token(access_token=create_platform_token(admin.id, admin.token_version), kind="platform")


@router.get("/me", response_model=UserOut)
def me(token: str | None = Depends(oauth2_scheme), user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    out = UserOut.model_validate(user)
    out.impersonated = bool((decode_token(token) or {}).get("imp")) if token else False
    company = db.get(Company, user.company_id)
    out.must_setup_2fa = bool(company and company.require_2fa and not user.totp_enabled and not out.impersonated)
    from app.core.permissions import effective
    out.effective_permissions = sorted(effective(user.role.permissions if user.role else []))
    return out


@router.post("/change-password", status_code=204)
def change_password(payload: PasswordChange, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if not verify_password(payload.current_password, user.hashed_password):
        raise HTTPException(400, "Current password is wrong")
    if (err := validate_password(payload.new_password)) is not None:
        raise HTTPException(400, err)
    user.hashed_password = hash_password(payload.new_password)
    db.commit()


# ---------------------------------------------------------------- two-step verification
@router.post("/2fa/setup")
def otp_setup(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Start setup: returns a new secret + otpauth:// link to show as a QR code. Not active until /2fa/enable."""
    if user.totp_enabled:
        raise HTTPException(400, "Two-step verification is already on")
    user.totp_secret = new_totp_secret()
    db.commit()
    return {"secret": user.totp_secret, "uri": totp_uri(user.totp_secret, user.email)}


@router.post("/2fa/enable", status_code=204)
def otp_enable(payload: OtpIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if not verify_totp(user.totp_secret, payload.code):
        raise HTTPException(400, "Wrong verification code")
    user.totp_enabled = True
    db.commit()


@router.post("/2fa/disable", status_code=204)
def otp_disable(payload: DisableOtpIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if not verify_password(payload.password, user.hashed_password) or not verify_totp(user.totp_secret, payload.code):
        raise HTTPException(400, "Wrong password or verification code")
    user.totp_enabled, user.totp_secret = False, None
    db.commit()


@router.post("/logout-all", status_code=204)
def logout_all(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Signs this user out on every device (all existing tokens stop working)."""
    user.token_version = (user.token_version or 0) + 1
    db.commit()


@router.get("/login-history")
def my_login_history(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    rows = db.scalars(select(LoginEvent).where(LoginEvent.user_id == user.id).order_by(LoginEvent.id.desc()).limit(50)).all()
    return [{"at": r.created_at, "success": r.success, "reason": r.reason, "ip": r.ip, "user_agent": r.user_agent} for r in rows]


# ---------------------------------------------------------------- forgotten password
@router.post("/forgot-password", status_code=204)
def forgot_password(payload: ForgotIn, db: Session = Depends(get_db)):
    """Always answers 204 so nobody can find out which emails exist. Sends a one-hour reset link if the account exists."""
    email = payload.email.strip().lower()
    user = db.scalar(select(User).where(func.lower(User.email) == email))
    admin = None if user else db.scalar(select(PlatformAdmin).where(func.lower(PlatformAdmin.email) == email))
    acct = user or admin
    if not acct or not acct.is_active:
        return
    token = random_token()
    db.add(PasswordResetToken(token_hash=sha256(token), user_id=user.id if user else None, admin_id=admin.id if admin else None,
                              expires_at=datetime.utcnow() + timedelta(hours=1)))
    link = f"{settings.PUBLIC_APP_URL.rstrip('/')}/reset-password?token={token}"
    ar = payload.lang == "ar"
    body = (f"<p>{'مرحبا' if ar else 'Hello'} {acct.full_name},</p><p>"
            + ("طلبت تغيير كلمة المرور. الرابط صالح لمدة ساعة واحدة. إذا ما طلبت هالإشي، تجاهل الرسالة." if ar
               else "You asked to reset your password. The link works for one hour. If this wasn't you, ignore this email.") + "</p>")
    mail.queue(db, acct.email, "تغيير كلمة المرور" if ar else "Reset your password",
               mail.layout("تغيير كلمة المرور" if ar else "Reset your password", body, button=("غيّر كلمة المرور" if ar else "Reset password", link), rtl=ar),
               "password_reset", user.company_id if user else None)
    db.commit()


@router.post("/reset-password", status_code=204)
def reset_password(payload: ResetIn, db: Session = Depends(get_db)):
    t = db.scalar(select(PasswordResetToken).where(PasswordResetToken.token_hash == sha256(payload.token)))
    if not t or t.used_at or t.expires_at < datetime.utcnow():
        raise HTTPException(400, "This reset link is invalid or has expired")
    if (err := validate_password(payload.new_password)) is not None:
        raise HTTPException(400, err)
    acct = db.get(User, t.user_id) if t.user_id else db.get(PlatformAdmin, t.admin_id)
    acct.hashed_password = hash_password(payload.new_password)
    acct.token_version = (acct.token_version or 0) + 1
    acct.failed_logins, acct.locked_until = 0, None
    t.used_at = datetime.utcnow()
    db.commit()


# ---------------------------------------------------------------- company
@router.get("/company", response_model=CompanyOut)
def company(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return db.get(Company, user.company_id)


@router.get("/timezones")
def timezones():
    from app.services.company_tz import COMMON_TIMEZONES
    return COMMON_TIMEZONES


@router.patch("/company", response_model=CompanyOut)
def update_company(payload: CompanyUpdate, user: User = Depends(require_permission("settings:write")), db: Session = Depends(get_db)):
    c = db.get(Company, user.company_id)
    data = payload.model_dump(exclude_unset=True)
    if "online_order_status" in data and data["online_order_status"] not in ("quotation", "draft"):
        raise HTTPException(400, "Online orders arrive as a quotation or as a draft order")
    if "costing_method" in data and data["costing_method"] not in ("average", "fifo"):
        raise HTTPException(400, "Costing method must be average or fifo")
    if "timezone" in data:
        from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
        try:
            ZoneInfo(data["timezone"])
        except ZoneInfoNotFoundError:
            raise HTTPException(400, "Unknown timezone")
    if data.get("slug"):
        import re
        slug = re.sub(r"[^a-z0-9-]", "", data["slug"].strip().lower())
        if not slug or db.scalar(select(Company.id).where(Company.slug == slug, Company.id != c.id)):
            raise HTTPException(400, "This shop link name is taken or invalid")
        data["slug"] = slug
    for k, v in data.items():
        setattr(c, k, v)
    db.commit()
    db.refresh(c)
    return c


# ---------------------------------------------------------------- custom domain (white-label), DNS-verified
@router.post("/company/domain/start")
def start_domain(payload: dict, user: User = Depends(require_permission("settings:write")), db: Session = Depends(get_db)):
    """Step 1: the company names a domain. It does nothing yet — a TXT record must prove they control it before any
    request for that host is treated as theirs (see verify_domain, and app/api/public.py)."""
    from app.services import domains
    c = db.get(Company, user.company_id)
    try:
        domain = domains.clean_domain(payload.get("domain", ""))
    except ValueError as ex:
        raise HTTPException(400, str(ex))
    if db.scalar(select(Company.id).where(Company.custom_domain == domain, Company.id != c.id, Company.domain_verified_at.is_not(None))):
        raise HTTPException(400, "Another company already verified this domain")
    c.custom_domain, c.domain_verify_token, c.domain_verified_at = domain, domains.new_token(), None
    db.commit()
    return {"domain": domain, "record_type": "TXT", "record_name": f"_bizos-verify.{domain}", "record_value": c.domain_verify_token}


@router.post("/company/domain/verify")
def verify_domain(user: User = Depends(require_permission("settings:write")), db: Session = Depends(get_db)):
    from app.services import domains
    c = db.get(Company, user.company_id)
    if not c.custom_domain or not c.domain_verify_token:
        raise HTTPException(400, "Start by naming a domain first")
    if not domains.verify_txt(c.custom_domain, c.domain_verify_token):
        raise HTTPException(400, "TXT record not found yet. DNS changes can take a few minutes to propagate — try again shortly.")
    c.domain_verified_at = datetime.utcnow()
    db.commit()
    return {"verified": True, "domain": c.custom_domain}


@router.delete("/company/domain", status_code=204)
def remove_domain(user: User = Depends(require_permission("settings:write")), db: Session = Depends(get_db)):
    c = db.get(Company, user.company_id)
    c.custom_domain, c.domain_verify_token, c.domain_verified_at = None, None, None
    db.commit()
