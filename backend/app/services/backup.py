"""Database backups: a consistent copy of the whole database, kept outside the synced project folder.

Retention is tiered (GFS-style, like most backup tools): the last few days are kept in full, then it thins out to
one a week, then one a month — so a year of history costs a dozen files, not 365. Backups are encrypted at rest
when BACKUP_ENCRYPTION_KEY is set (Fernet/AES — see core/config.py); unset, they're written in the open, which is
fine for local development but should never be true for anything holding real customer data.
"""
import os
import shutil
import sqlite3
import subprocess
import tempfile
from datetime import date, datetime, timedelta

from app.core.config import settings
from app.core.database import engine

ENC_SUFFIX = ".enc"


def backup_dir() -> str:
    path = settings.BACKUP_DIR or os.path.join(os.environ.get("LOCALAPPDATA") or os.path.expanduser("~"), "BizOS", "backups")
    os.makedirs(path, exist_ok=True)
    return path


def _fernet():
    if not settings.BACKUP_ENCRYPTION_KEY:
        return None
    from cryptography.fernet import Fernet
    return Fernet(settings.BACKUP_ENCRYPTION_KEY.encode())


def list_backups() -> list[dict]:
    d = backup_dir()
    out = []
    for name in sorted(os.listdir(d), reverse=True):
        base = name[: -len(ENC_SUFFIX)] if name.endswith(ENC_SUFFIX) else name
        if name.startswith("bizos-") and (base.endswith(".db") or base.endswith(".sql")):
            p = os.path.join(d, name)
            out.append({"name": name, "size": os.path.getsize(p), "created_at": datetime.fromtimestamp(os.path.getmtime(p)),
                       "encrypted": name.endswith(ENC_SUFFIX)})
    return out


def _dump(dest: str) -> None:
    """Write a fresh, consistent dump to `dest` (plain, unencrypted)."""
    if engine.dialect.name == "sqlite":
        src = sqlite3.connect(engine.url.database)
        dst = sqlite3.connect(dest)
        with dst:
            src.backup(dst)  # safe while the app is running
        dst.close()
        src.close()
    else:
        if not shutil.which("pg_dump"):
            raise RuntimeError("pg_dump is not installed on this server")
        url = engine.url.set(drivername="postgresql")
        subprocess.run(["pg_dump", "--no-owner", "-f", dest, url.render_as_string(hide_password=False)], check=True)


def create_backup() -> dict:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    ext = "db" if engine.dialect.name == "sqlite" else "sql"
    d = backup_dir()
    plain = os.path.join(d, f"bizos-{stamp}.{ext}")
    _dump(plain)
    fernet = _fernet()
    if fernet:
        with open(plain, "rb") as f:
            enc = fernet.encrypt(f.read())
        dest = plain + ENC_SUFFIX
        with open(dest, "wb") as f:
            f.write(enc)
        os.remove(plain)
    else:
        dest = plain
    prune()
    return {"name": os.path.basename(dest), "size": os.path.getsize(dest), "encrypted": bool(fernet)}


def prune() -> None:
    """GFS retention: keep every backup from the last BACKUP_DAILY_KEEP days, then the newest one per week for
    BACKUP_WEEKLY_KEEP weeks, then the newest one per month for BACKUP_MONTHLY_KEEP months. Everything older is removed."""
    rows = list_backups()  # newest first
    today = date.today()
    keep: set[str] = set()
    for b in rows:
        if (today - b["created_at"].date()).days < max(settings.BACKUP_DAILY_KEEP, 1):
            keep.add(b["name"])

    def newest_per_bucket(bucket_of, limit: int) -> None:
        seen: dict = {}
        for b in rows:
            if b["name"] in keep:
                continue
            key = bucket_of(b["created_at"].date())
            if key not in seen:
                seen[key] = b["name"]
        for name in list(seen.values())[:limit]:
            keep.add(name)

    newest_per_bucket(lambda d_: (d_.isocalendar().year, d_.isocalendar().week), settings.BACKUP_WEEKLY_KEEP)
    newest_per_bucket(lambda d_: (d_.year, d_.month), settings.BACKUP_MONTHLY_KEEP)
    for b in rows:
        if b["name"] not in keep:
            os.remove(os.path.join(backup_dir(), b["name"]))


def backup_if_due() -> None:
    """Called by the scheduler: make a backup when the newest one is older than a day."""
    latest = list_backups()[:1]
    if not latest or latest[0]["created_at"] < datetime.now() - timedelta(hours=23):
        create_backup()


def backup_path(name: str) -> str:
    safe = os.path.basename(name)
    path = os.path.join(backup_dir(), safe)
    if not safe.startswith("bizos-") or not os.path.exists(path):
        raise FileNotFoundError(name)
    return path


def decrypt_to(name: str, out_path: str) -> None:
    """Write `name`'s plain content to `out_path`, decrypting first if it's encrypted."""
    src = backup_path(name)
    if not name.endswith(ENC_SUFFIX):
        shutil.copyfile(src, out_path)
        return
    fernet = _fernet()
    if not fernet:
        raise RuntimeError("This backup is encrypted but BACKUP_ENCRYPTION_KEY isn't set — it can't be read")
    with open(src, "rb") as f:
        data = fernet.decrypt(f.read())
    with open(out_path, "wb") as f:
        f.write(data)


def restore_test() -> str:
    """Disaster-recovery check: take the newest backup, decrypt it if needed, and prove it actually opens and holds
    data — a backup nobody has restored is not a backup, it's a hope. Returns a short human-readable result;
    raises on failure so the scheduler records it as a failed job."""
    latest = list_backups()[:1]
    if not latest:
        raise RuntimeError("No backup exists yet to test")
    name = latest[0]["name"]
    if engine.dialect.name != "sqlite":
        # a full pg_restore into a scratch database is a heavier operation; here we at least confirm the dump file
        # is non-empty and readable, which catches the most common failure (a broken/partial dump)
        with tempfile.TemporaryDirectory() as tmp:
            out = os.path.join(tmp, "test.sql")
            decrypt_to(name, out)
            size = os.path.getsize(out)
            if size < 100:
                raise RuntimeError(f"{name} looks empty/truncated ({size} bytes)")
        return f"{name}: {size:,} bytes, readable (full pg_restore not run — Postgres SQL dump)"
    with tempfile.TemporaryDirectory() as tmp:
        out = os.path.join(tmp, "test.db")
        decrypt_to(name, out)
        conn = sqlite3.connect(out)
        try:
            ok = conn.execute("PRAGMA integrity_check").fetchone()[0]
            if ok != "ok":
                raise RuntimeError(f"{name} failed integrity check: {ok}")
            tables = conn.execute("SELECT count(*) FROM sqlite_master WHERE type='table'").fetchone()[0]
            companies = conn.execute("SELECT count(*) FROM companies").fetchone()[0] if tables else 0
        finally:
            conn.close()
    return f"{name}: opened OK, {tables} tables, {companies} companies"
