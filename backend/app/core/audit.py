"""Automatic, append-only audit trail.

`get_current_user` stores the acting user (+ IP, device, branch, impersonating admin, optional reason) on the DB session
(session.info["actor"]). After every flush we write one audit row per created / changed / deleted business record,
inside the same transaction, so the log can never disagree with the data. Audit rows can't be edited or deleted
through the ORM (only a whole company removal clears them).
"""
from datetime import date, datetime

from sqlalchemy import event, insert, inspect
from sqlalchemy.orm import Session

IGNORED_FIELDS = {"updated_at", "created_at", "hashed_password", "embedding", "score", "last_run_at", "totp_secret", "key_hash", "secret",
                  "token_version", "failed_logins", "locked_until", "last_login_at", "last_used_at", "portal_token", "public_token"}
# derived data, logs of their own, or high-volume technical rows: not worth an audit line each
NOT_TRACKED = {"audit_logs", "login_events", "stock_levels", "stock_movements", "document_chunks", "ai_conversations", "email_outbox",
               "webhook_deliveries", "journal_lines", "notifications", "password_reset_tokens", "usage_records", "metric_samples", "job_runs"}


def _json(v):
    if isinstance(v, (date, datetime)):
        return v.isoformat()
    if isinstance(v, (str, int, float, bool)) or v is None:
        return v
    return str(v)


def _label(obj) -> str | None:
    for attr in ("number", "name", "full_name", "title", "label", "email", "category", "period", "kind"):
        v = getattr(obj, attr, None)
        if v:
            return str(v)[:300]
    return None


def _tracked(obj) -> bool:
    table = getattr(obj, "__tablename__", None)
    if not table or table in NOT_TRACKED:
        return False
    if table == "journal_entries":  # automatic entries are rebuilt from documents; only manual ones are audited
        return getattr(obj, "source", None) == "manual"
    return True


@event.listens_for(Session, "before_flush")
def _audit_is_append_only(session: Session, _ctx, _instances) -> None:
    from app.models.platform import AuditLog
    for obj in list(session.dirty) + list(session.deleted):
        if isinstance(obj, AuditLog):
            raise PermissionError("The audit log can't be changed or deleted")


@event.listens_for(Session, "after_flush")
def _write_audit(session: Session, _ctx) -> None:
    actor = session.info.get("actor")
    if not actor:
        return  # system jobs, seed scripts, tests without a user
    from app.models.platform import AuditLog  # local import: models import this module indirectly

    rows = []
    reason = session.info.get("audit_reason")

    def add(obj, action: str, changes: dict | None = None):
        if not _tracked(obj):
            return
        table = obj.__tablename__
        cid = getattr(obj, "company_id", None) if table != "companies" else obj.id
        if cid != actor["cid"]:
            return
        rows.append({"company_id": cid, "user_id": actor["id"], "user_name": actor["name"], "action": action, "entity": table,
                     "entity_id": getattr(obj, "id", None), "label": _label(obj), "changes": changes or {}, "created_at": datetime.utcnow(),
                     "ip": actor.get("ip"), "user_agent": actor.get("ua"), "branch_id": actor.get("branch_id"),
                     "impersonated_by": actor.get("imp"), "note": reason})

    for obj in session.new:
        add(obj, "create")
    for obj in session.dirty:
        if not session.is_modified(obj, include_collections=False):
            continue
        changes = {}
        for attr in inspect(obj).mapper.column_attrs:
            if attr.key in IGNORED_FIELDS:
                continue
            h = inspect(obj).attrs[attr.key].history
            if h.has_changes() and h.deleted:
                old, new = h.deleted[0], h.added[0] if h.added else None
                if old != new:
                    changes[attr.key] = [_json(old), _json(new)]
        if changes:
            add(obj, "update", changes)
    for obj in session.deleted:
        add(obj, "delete")
    if rows:
        session.connection().execute(insert(AuditLog.__table__), rows)
        from app.services import ledger  # the books must be rebuilt after any business change
        ledger._last_build.pop(actor["cid"], None)


def set_actor(session: Session, user, impersonated: bool = False, ip: str | None = None, user_agent: str | None = None,
              impersonated_by: int | None = None, reason: str | None = None) -> None:
    session.info["actor"] = {"id": user.id, "cid": user.company_id, "name": user.full_name + (" (platform admin)" if impersonated else ""),
                             "ip": ip, "ua": (user_agent or "")[:300] or None, "branch_id": user.branch_id, "imp": impersonated_by}
    if reason:
        session.info["audit_reason"] = reason[:1000]


def log_event(session: Session, company_id: int, action: str, entity: str, label: str | None = None, changes: dict | None = None,
              user_id: int | None = None, user_name: str | None = None, ip: str | None = None, note: str | None = None,
              impersonated_by: int | None = None) -> None:
    """An audit line for something that isn't a row change (sign-in as a company, period close, export…)."""
    from app.models.platform import AuditLog
    session.connection().execute(insert(AuditLog.__table__), [{
        "company_id": company_id, "user_id": user_id, "user_name": user_name, "action": action, "entity": entity, "entity_id": None,
        "label": label, "changes": changes or {}, "created_at": datetime.utcnow(), "ip": ip, "note": note, "impersonated_by": impersonated_by}])
