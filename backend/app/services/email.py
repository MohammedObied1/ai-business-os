"""Outgoing email through an outbox table.

queue() stores the message; flush() (run by the scheduler every minute) sends queued messages over SMTP.
Without SMTP settings, messages are kept with status "saved" and can be read in the admin panel.
"""
import html
import smtplib
import ssl
from datetime import datetime
from email.message import EmailMessage as MimeMessage

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import EmailMessage


def smtp_configured() -> bool:
    return bool(settings.SMTP_HOST and settings.SMTP_FROM)


def queue(db: Session, to: str, subject: str, body_html: str, kind: str, company_id: int | None = None) -> EmailMessage:
    m = EmailMessage(company_id=company_id, to=to.strip(), subject=subject[:300], body_html=body_html, kind=kind,
                     status="queued" if smtp_configured() else "saved")
    db.add(m)
    db.flush()
    return m


def _send(m: EmailMessage) -> None:
    msg = MimeMessage()
    msg["From"] = settings.SMTP_FROM
    msg["To"] = m.to
    msg["Subject"] = m.subject
    msg.set_content("This message needs an HTML-capable email client.")
    msg.add_alternative(m.body_html, subtype="html")
    if settings.SMTP_PORT == 465:
        with smtplib.SMTP_SSL(settings.SMTP_HOST, settings.SMTP_PORT, context=ssl.create_default_context(), timeout=20) as s:
            if settings.SMTP_USER:
                s.login(settings.SMTP_USER, settings.SMTP_PASSWORD or "")
            s.send_message(msg)
    else:
        with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT, timeout=20) as s:
            if settings.SMTP_TLS:
                s.starttls(context=ssl.create_default_context())
            if settings.SMTP_USER:
                s.login(settings.SMTP_USER, settings.SMTP_PASSWORD or "")
            s.send_message(msg)


def flush(db: Session, limit: int = 50) -> int:
    if not smtp_configured():
        return 0
    sent = 0
    for m in db.scalars(select(EmailMessage).where(EmailMessage.status == "queued", EmailMessage.attempts < 5).order_by(EmailMessage.id).limit(limit)).all():
        m.attempts += 1
        try:
            _send(m)
            m.status, m.sent_at, m.error = "sent", datetime.utcnow(), None
            sent += 1
        except Exception as ex:  # noqa: BLE001
            m.error = str(ex)[:500]
            if m.attempts >= 5:
                m.status = "failed"
                from app.core.observability import log_error
                log_error("email", f"Email to {m.to} failed after {m.attempts} tries: {m.error}", company_id=m.company_id)
        db.commit()
    return sent


def flush_job() -> None:
    from app.core.database import SessionLocal
    with SessionLocal() as db:
        flush(db)


def layout(title: str, body: str, company: str = "AI Business OS", button: tuple[str, str] | None = None, rtl: bool = True) -> str:
    """Simple, email-client-safe HTML wrapper."""
    btn = ""
    if button:
        btn = (f'<p style="margin:24px 0"><a href="{html.escape(button[1])}" style="background:#0F766E;color:#fff;padding:12px 22px;'
               f'border-radius:8px;text-decoration:none;font-weight:600">{html.escape(button[0])}</a></p>')
    d = "rtl" if rtl else "ltr"
    return (f'<div dir="{d}" style="font-family:Tahoma,Segoe UI,Arial,sans-serif;background:#F5F4EF;padding:24px">'
            f'<div style="max-width:560px;margin:auto;background:#fff;border:1px solid #DDD9CF;border-radius:12px;padding:28px;color:#1B2430">'
            f'<div style="font-size:13px;color:#5B6675">{html.escape(company)}</div>'
            f'<h2 style="margin:8px 0 16px">{html.escape(title)}</h2>{body}{btn}</div></div>')
