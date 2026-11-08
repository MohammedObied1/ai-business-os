import logging
import os
from datetime import datetime, timedelta

from apscheduler.schedulers.background import BackgroundScheduler
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware

from app.api.router import api_router
from app.core import audit  # noqa: F401  (registers the audit-log session hook)
from app.core.tenant_guard import TenantViolation  # also registers the tenant write guard
from app.core.period_guard import PeriodClosed  # also registers the closed-period guard
from app.services import notify  # noqa: F401  (alerts → notification inbox)
from app.core.config import settings
from app.core.database import SessionLocal, engine
from app.core.migrate import sync_schema
from app.services.automation import run_all_companies
from app.services.backup import backup_if_due, restore_test
from app.services.companies import ensure_platform_admin, sync_default_roles
from app.services.email import flush_job
from app.services.saas import billing_job
from app.services.recurring import run_all as run_recurring
from app.services.smart import send_daily_summaries
from app.services.webhooks import deliver_job

from app.core.observability import install as install_observability, setup_logging, tracked_job  # noqa: E402

setup_logging(settings.JSON_LOGS or settings.ENV == "production")

if settings.SENTRY_DSN:  # optional error monitoring
    import sentry_sdk
    sentry_sdk.init(dsn=settings.SENTRY_DSN, environment=settings.ENV, traces_sample_rate=0.1, send_default_pii=False)

if settings.ENV == "production":
    # a default secret or a guessable admin password in production is a full account-takeover waiting to happen —
    # refuse to boot rather than run insecurely and hope someone notices
    _bad = []
    if settings.SECRET_KEY == "change-me-in-production":
        _bad.append("SECRET_KEY is still the default")
    if settings.PLATFORM_ADMIN_PASSWORD == "admin1234":
        _bad.append("PLATFORM_ADMIN_PASSWORD is still the default (admin1234)")
    if _bad:
        raise RuntimeError("Refusing to start in production: " + "; ".join(_bad) + ". Set real values in the environment.")

app = FastAPI(title=settings.APP_NAME, version="1.0.0", description="Your business has a database. Our AI turns that data into decisions and actions.")


@app.middleware("http")
async def _security_headers(request: Request, call_next):
    resp = await call_next(request)
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["X-Frame-Options"] = "DENY"
    resp.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    resp.headers["Permissions-Policy"] = "geolocation=(self), camera=(), microphone=()"
    if settings.ENV == "production":
        resp.headers["Strict-Transport-Security"] = "max-age=63072000; includeSubDomains"
    return resp

app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in settings.CORS_ORIGINS.split(",")],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Total-Count", "Content-Disposition"],
)
app.include_router(api_router)
install_observability(app, engine)  # request timing, error capture, slow queries


@app.exception_handler(TenantViolation)
def _tenant_violation(_request: Request, exc: TenantViolation):
    # same answer as an unknown id: never confirm that another company's record exists
    logging.getLogger("security").warning("Blocked cross-tenant reference %s.%s", exc.table, exc.column)
    return JSONResponse(status_code=404, content={"detail": str(exc)})


@app.exception_handler(PeriodClosed)
def _period_closed(_request: Request, exc: PeriodClosed):
    return JSONResponse(status_code=409, content={"detail": str(exc), "period": exc.period})

scheduler = BackgroundScheduler()


@app.on_event("startup")
def startup():
    sync_schema(engine)
    with SessionLocal() as db:
        ensure_platform_admin(db, settings.PLATFORM_ADMIN_EMAIL, settings.PLATFORM_ADMIN_PASSWORD)
        sync_default_roles(db)
    os.makedirs(settings.UPLOAD_DIR, exist_ok=True)
    if settings.ENV != "test" and settings.SCHEDULER_ENABLED:
        soon = datetime.now() + timedelta(minutes=1)
        scheduler.add_job(tracked_job("automation")(run_all_companies), "interval", minutes=settings.AUTOMATION_INTERVAL_MINUTES, id="automation")
        scheduler.add_job(tracked_job("backup", keep_ok=False)(backup_if_due), "interval", hours=1, id="backup", next_run_time=soon)
        scheduler.add_job(tracked_job("backup_restore_test")(restore_test), "cron", day_of_week="sun", hour=5, minute=0, id="backup_restore_test")
        scheduler.add_job(tracked_job("email", keep_ok=False)(flush_job), "interval", minutes=1, id="email")
        scheduler.add_job(tracked_job("webhooks", keep_ok=False)(deliver_job), "interval", minutes=1, id="webhooks")
        scheduler.add_job(tracked_job("recurring")(run_recurring), "interval", hours=1, id="recurring", next_run_time=soon)
        scheduler.add_job(tracked_job("billing")(billing_job), "cron", hour=6, minute=0, id="platform_billing")  # daily: renewals, grace, suspension
        scheduler.add_job(tracked_job("daily_summary")(send_daily_summaries), "cron", hour=7, minute=0, id="daily_summary")
        scheduler.start()


@app.on_event("shutdown")
def shutdown():
    if scheduler.running:
        scheduler.shutdown(wait=False)


@app.get("/health")
def health():
    """Liveness: the process answers."""
    return {"status": "ok", "app": settings.APP_NAME, "ai_enabled": bool(settings.ANTHROPIC_API_KEY)}


@app.get("/health/ready")
def ready():
    """Readiness: database reachable, scheduler alive (where enabled), enough disk. 503 when not ready."""
    from sqlalchemy import text
    from app.core.observability import system_resources
    checks: dict = {}
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        checks["database"] = "ok"
    except Exception as ex:  # noqa: BLE001
        checks["database"] = f"error: {type(ex).__name__}"
    checks["scheduler"] = "ok" if (scheduler.running or not settings.SCHEDULER_ENABLED or settings.ENV == "test") else "stopped"
    disk = (system_resources().get("disk") or {}).get("data")
    checks["disk"] = "ok" if not disk or disk["free_gb"] > 1 else f"low: {disk['free_gb']} GB free"
    ok = all(v == "ok" for v in checks.values())
    return JSONResponse(status_code=200 if ok else 503, content={"status": "ready" if ok else "not ready", "checks": checks})
