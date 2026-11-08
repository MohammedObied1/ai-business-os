"""External integrations. Each provider's credentials live in a per-company `Connection` row (Settings → Integrations),
never in code or environment variables — different companies connect different accounts."""
from datetime import datetime

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Connection


def connection(db: Session, cid: int, provider: str) -> Connection | None:
    c = db.scalar(select(Connection).where(Connection.company_id == cid, Connection.provider == provider, Connection.is_active.is_(True)))
    return c if c and c.secret else None


def _mark(db: Session, c: Connection, error: str | None) -> None:
    c.last_used_at, c.last_error = datetime.utcnow(), error
    db.commit()


def whatsapp_send(db: Session, cid: int, phone: str, text: str) -> bool:
    """Send a WhatsApp message through the company's connected WhatsApp Cloud API number. False when none is
    connected or the send failed (never raises — callers fall back to logging/notifications)."""
    c = connection(db, cid, "whatsapp")
    if not c:
        return False
    phone_number_id = (c.config or {}).get("phone_number_id")
    to = "".join(ch for ch in phone if ch.isdigit())
    if not phone_number_id or not to:
        _mark(db, c, "Missing phone_number_id or an invalid recipient number")
        return False
    try:
        r = httpx.post(
            f"https://graph.facebook.com/v20.0/{phone_number_id}/messages",
            headers={"Authorization": f"Bearer {c.secret}", "Content-Type": "application/json"},
            json={"messaging_product": "whatsapp", "to": to, "type": "text", "text": {"body": text[:4096]}},
            timeout=10,
        )
        if r.status_code >= 400:
            _mark(db, c, f"HTTP {r.status_code}: {r.text[:300]}")
            from app.core.observability import log_error
            log_error("integration", f"WhatsApp send failed (HTTP {r.status_code})", company_id=cid, level="warning")
            return False
    except Exception as ex:  # noqa: BLE001
        _mark(db, c, str(ex)[:300])
        from app.core.observability import log_error
        log_error("integration", f"WhatsApp send failed: {ex}", company_id=cid, level="warning")
        return False
    _mark(db, c, None)
    return True
