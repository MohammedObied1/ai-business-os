"""Outgoing webhooks: events are stored as deliveries inside the business transaction, then a background job POSTs them
with an HMAC-SHA256 signature (header X-BizOS-Signature) and retries failures with back-off."""
import hashlib
import hmac
import json
from datetime import datetime, timedelta

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Webhook, WebhookDelivery

EVENTS = ["order.created", "order.updated", "invoice.created", "invoice.paid", "payment.received", "payment.created", "return.created",
          "purchase.created", "purchase.received", "customer.created", "stock.low", "stock.updated", "cheque.bounced",
          "online_order.created", "delivery.completed"]
BACKOFF_MIN = [1, 5, 30, 120, 720]


def emit(db: Session, cid: int, event: str, data: dict) -> None:
    hooks = db.scalars(select(Webhook).where(Webhook.company_id == cid, Webhook.is_active.is_(True))).all()
    for h in hooks:
        if "*" in (h.events or []) or event in (h.events or []):
            db.add(WebhookDelivery(company_id=cid, webhook_id=h.id, event=event, next_attempt_at=datetime.utcnow(),
                                   payload={"event": event, "company_id": cid, "created_at": datetime.utcnow().isoformat(), "data": data}))


def sign(secret: str, body: bytes) -> str:
    return hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def deliver_pending(db: Session, limit: int = 50) -> int:
    done = 0
    now = datetime.utcnow()
    rows = db.scalars(select(WebhookDelivery).where(WebhookDelivery.status == "pending", WebhookDelivery.next_attempt_at <= now)
                      .order_by(WebhookDelivery.id).limit(limit)).all()
    for d in rows:
        h = db.get(Webhook, d.webhook_id)
        if not h or not h.is_active:
            d.status = "failed"
            continue
        body = json.dumps(d.payload, default=str).encode()
        d.attempts += 1
        try:
            r = httpx.post(h.url, content=body, timeout=10, headers={"Content-Type": "application/json", "X-BizOS-Event": d.event,
                                                                     "X-BizOS-Signature": sign(h.secret, body)})
            d.response_code = r.status_code
            ok = 200 <= r.status_code < 300
        except Exception:  # noqa: BLE001
            ok = False
        if ok:
            d.status = "delivered"
            done += 1
        elif d.attempts >= len(BACKOFF_MIN):
            d.status = "failed"
            from app.core.observability import log_error
            log_error("webhook", f"Webhook {d.event} to {h.url} failed after {d.attempts} tries (HTTP {d.response_code})", company_id=d.company_id)
        else:
            d.next_attempt_at = now + timedelta(minutes=BACKOFF_MIN[d.attempts - 1])
        db.commit()
    return done


def deliver_job() -> None:
    from app.core.database import SessionLocal
    with SessionLocal() as db:
        deliver_pending(db)
