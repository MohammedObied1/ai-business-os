import base64
import hashlib
import hmac
import secrets
import struct
import time
from datetime import datetime, timedelta, timezone
from urllib.parse import quote

from jose import JWTError, jwt
from passlib.context import CryptContext

from app.core.config import settings

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
ALGORITHM = "HS256"


COMMON_PASSWORDS = {  # short list of the most-guessed passwords; length/mix rules alone don't stop these
    "password", "password1", "12345678", "123456789", "1234567890", "qwertyui", "qwerty123", "letmein1",
    "admin1234", "welcome1", "iloveyou", "administrator",
}


def validate_password(password: str, min_length: int = 8) -> str | None:
    """Returns an error message (or None if the password is acceptable). Same rule everywhere a password is set:
    at least 8 characters, a letter and a digit, and not one of the passwords everyone tries first."""
    if len(password) < min_length:
        return f"Password must be at least {min_length} characters"
    if not any(c.isalpha() for c in password) or not any(c.isdigit() for c in password):
        return "Password must include both letters and numbers"
    if password.lower() in COMMON_PASSWORDS:
        return "This password is too common. Choose another one."
    return None


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)


def create_access_token(user_id: int, company_id: int, impersonated_by: int | None = None, token_version: int = 0) -> str:
    expire = datetime.now(timezone.utc) + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    payload = {"sub": str(user_id), "cid": company_id, "scope": "company", "tv": token_version or 0, "exp": expire}
    if impersonated_by:
        payload["imp"] = impersonated_by
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=ALGORITHM)


def create_platform_token(admin_id: int, token_version: int = 0) -> str:
    expire = datetime.now(timezone.utc) + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    return jwt.encode({"sub": str(admin_id), "scope": "platform", "tv": token_version or 0, "exp": expire}, settings.SECRET_KEY, algorithm=ALGORITHM)


def decode_token(token: str) -> dict | None:
    try:
        return jwt.decode(token, settings.SECRET_KEY, algorithms=[ALGORITHM])
    except JWTError:
        return None


def sha256(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def random_token(nbytes: int = 32) -> str:
    return secrets.token_urlsafe(nbytes)


# ---------------------------------------------------------------- TOTP (RFC 6238) for two-step verification
def new_totp_secret() -> str:
    return base64.b32encode(secrets.token_bytes(20)).decode().rstrip("=")


def _hotp(secret: str, counter: int) -> str:
    key = base64.b32decode(secret + "=" * (-len(secret) % 8), casefold=True)
    digest = hmac.new(key, struct.pack(">Q", counter), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    code = (struct.unpack(">I", digest[offset:offset + 4])[0] & 0x7FFFFFFF) % 1_000_000
    return f"{code:06d}"


def totp_now(secret: str, at: float | None = None) -> str:
    return _hotp(secret, int((at or time.time()) // 30))


def verify_totp(secret: str | None, code: str | None, window: int = 1) -> bool:
    if not secret or not code:
        return False
    code = code.strip().replace(" ", "")
    now = int(time.time() // 30)
    return any(hmac.compare_digest(_hotp(secret, now + d), code) for d in range(-window, window + 1))


def totp_uri(secret: str, account: str, issuer: str = "AI Business OS") -> str:
    return f"otpauth://totp/{quote(issuer)}:{quote(account)}?secret={secret}&issuer={quote(issuer)}&digits=6&period=30"
