"""Observability: request timing, error capture, slow queries, background job runs, structured logs, system resources.

- Every request is timed; 5xx responses and exceptions are stored in `error_logs` (with the company when known).
- Slow SQL (> SLOW_QUERY_MS) and slow requests (> SLOW_REQUEST_MS) are kept too.
- `tracked_job(name)` wraps a scheduler job: a `job_runs` row per run (ok / failed + error).
- Logs are JSON lines; passwords, tokens, API keys and secrets are redacted before anything is written.
"""
import json
import logging
import os
import re
import shutil
import threading
import time
import traceback
from collections import defaultdict, deque
from datetime import datetime
from functools import wraps

SLOW_QUERY_MS = 500
SLOW_REQUEST_MS = 2000
_SECRET = re.compile(r"(?i)(password|passwd|secret|token|api[_-]?key|authorization|totp)([\"']?\s*[:=]\s*[\"']?)([^\s\"'&,}]+)")
_BEARER = re.compile(r"(?i)bearer\s+[a-z0-9._\-]+")


def redact(text: str | None) -> str | None:
    if not text:
        return text
    return _BEARER.sub("Bearer ***", _SECRET.sub(lambda m: f"{m.group(1)}{m.group(2)}***", str(text)))


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        out = {"ts": datetime.utcnow().isoformat(timespec="milliseconds") + "Z", "level": record.levelname, "logger": record.name,
               "msg": redact(record.getMessage())}
        for k in ("method", "path", "status", "ms", "company_id", "request_id", "job"):
            if hasattr(record, k):
                out[k] = getattr(record, k)
        if record.exc_info:
            out["exc"] = redact("".join(traceback.format_exception(*record.exc_info))[-4000:])
        return json.dumps(out, ensure_ascii=False, default=str)


def setup_logging(json_logs: bool) -> None:
    root = logging.getLogger()
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter() if json_logs else logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    root.handlers = [handler]
    root.setLevel(logging.INFO)


# ---------------------------------------------------------------- in-process metrics (reset on restart)
class Metrics:
    def __init__(self):
        self.lock = threading.Lock()
        self.started = time.time()
        self.requests = 0
        self.by_status: dict[str, int] = defaultdict(int)
        self.latencies: deque = deque(maxlen=2000)
        self.routes: dict[str, list] = defaultdict(lambda: [0, 0.0, 0])  # count, total ms, errors
        self.slow_queries: deque = deque(maxlen=50)

    def record(self, method: str, route: str, status: int, ms: float) -> None:
        with self.lock:
            self.requests += 1
            self.by_status[f"{status // 100}xx"] += 1
            self.latencies.append(ms)
            r = self.routes[f"{method} {route}"]
            r[0] += 1
            r[1] += ms
            r[2] += 1 if status >= 500 else 0

    def snapshot(self) -> dict:
        with self.lock:
            lat = sorted(self.latencies)
            pct = lambda p: round(lat[min(len(lat) - 1, int(len(lat) * p))], 1) if lat else 0  # noqa: E731
            top = sorted(self.routes.items(), key=lambda kv: kv[1][1] / max(kv[1][0], 1), reverse=True)[:15]
            return {"uptime_s": int(time.time() - self.started), "requests": self.requests, "by_status": dict(self.by_status),
                    "latency_ms": {"p50": pct(0.5), "p95": pct(0.95), "p99": pct(0.99)},
                    "slowest_routes": [{"route": k, "count": v[0], "avg_ms": round(v[1] / max(v[0], 1), 1), "errors": v[2]} for k, v in top],
                    "slow_queries": list(self.slow_queries)}


METRICS = Metrics()


def log_error(source: str, message: str, detail: str | None = None, company_id: int | None = None, level: str = "error", **kw) -> None:
    """Store a problem in error_logs (own session, never breaks the caller)."""
    try:
        from app.core.database import SessionLocal
        from app.models.monitor import ErrorLog
        with SessionLocal() as db:
            db.info["system"] = True
            db.add(ErrorLog(source=source, level=level, message=redact(message)[:500], detail=redact(detail)[:8000] if detail else None,
                            company_id=company_id, **{k: v for k, v in kw.items() if k in ("method", "path", "status", "duration_ms")}))
            db.commit()
    except Exception:  # noqa: BLE001
        logging.getLogger("observability").exception("could not store an error log")


def install(app, engine) -> None:
    """Request timing + error capture middleware and slow-query timing."""
    from fastapi import Request
    from sqlalchemy import event
    from starlette.responses import JSONResponse

    log = logging.getLogger("http")

    @app.middleware("http")
    async def _observe(request: Request, call_next):
        start = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception as ex:  # noqa: BLE001
            ms = (time.perf_counter() - start) * 1000
            route = getattr(request.scope.get("route"), "path", request.url.path)
            METRICS.record(request.method, route, 500, ms)
            log_error("http", f"{type(ex).__name__}: {ex}", traceback.format_exc(), request.state.__dict__.get("company_id"),
                      method=request.method, path=request.url.path, status=500, duration_ms=round(ms, 1))
            log.exception("unhandled error", extra={"method": request.method, "path": request.url.path})
            return JSONResponse(status_code=500, content={"detail": "Something went wrong on our side. It was recorded; please try again."})
        ms = (time.perf_counter() - start) * 1000
        route = getattr(request.scope.get("route"), "path", request.url.path)
        METRICS.record(request.method, route, response.status_code, ms)
        if response.status_code >= 500:
            log_error("http", f"HTTP {response.status_code}", None, None, method=request.method, path=request.url.path, status=response.status_code,
                      duration_ms=round(ms, 1))
        elif ms > SLOW_REQUEST_MS:
            log_error("http", f"Slow request {ms:.0f} ms", None, None, level="warning", method=request.method, path=request.url.path,
                      status=response.status_code, duration_ms=round(ms, 1))
        log.info("request", extra={"method": request.method, "path": request.url.path, "status": response.status_code, "ms": round(ms, 1)})
        response.headers["X-Response-Time-ms"] = f"{ms:.0f}"
        return response

    @event.listens_for(engine, "before_cursor_execute")
    def _q_start(conn, cursor, statement, params, context, executemany):
        conn.info.setdefault("q_start", []).append(time.perf_counter())

    @event.listens_for(engine, "after_cursor_execute")
    def _q_end(conn, cursor, statement, params, context, executemany):
        stack = conn.info.get("q_start") or []
        if not stack:
            return
        ms = (time.perf_counter() - stack.pop()) * 1000
        if ms > SLOW_QUERY_MS:
            METRICS.slow_queries.append({"at": datetime.utcnow().isoformat(timespec="seconds"), "ms": round(ms, 1), "sql": redact(statement[:300])})


LAST_RUNS: dict[str, dict] = {}  # job -> last status / time (in memory, for the health page)


def tracked_job(name: str, keep_ok: bool = True):
    """Decorator for scheduler jobs: a job_runs row per run (frequent jobs: only failures), errors stored instead of lost."""
    def deco(fn):
        @wraps(fn)
        def run(*a, **kw):
            from app.core.database import SessionLocal
            from app.models.monitor import JobRun
            started, began = time.perf_counter(), datetime.utcnow()
            status, detail, result = "ok", None, None
            try:
                result = fn(*a, **kw)
                detail = str(result)[:1000] if result is not None else None
            except Exception as ex:  # noqa: BLE001
                status, detail = "failed", f"{type(ex).__name__}: {ex}"
                log_error("job", f"Job {name} failed: {ex}", traceback.format_exc())
                logging.getLogger("jobs").exception("job failed", extra={"job": name})
            ms = round((time.perf_counter() - started) * 1000, 1)
            LAST_RUNS[name] = {"status": status, "at": datetime.utcnow().isoformat(timespec="seconds"), "ms": ms}
            if keep_ok or status != "ok":
                try:
                    with SessionLocal() as db:
                        db.add(JobRun(job=name, started_at=began, finished_at=datetime.utcnow(), status=status, duration_ms=ms, detail=redact(detail)))
                        db.commit()
                except Exception:  # noqa: BLE001
                    logging.getLogger("jobs").exception("could not record the job run")
            return result
        return run
    return deco


def system_resources() -> dict:
    """CPU / RAM from /proc on Linux servers (the Docker image); disk everywhere. Unknown values are None."""
    out: dict = {"cpu_count": os.cpu_count(), "load_avg": None, "memory": None}
    try:
        out["load_avg"] = [round(x, 2) for x in os.getloadavg()]
    except (AttributeError, OSError):
        pass
    try:
        with open("/proc/meminfo") as f:
            info = {line.split(":")[0]: int(line.split()[1]) for line in f if ":" in line}
        total, avail = info.get("MemTotal", 0), info.get("MemAvailable", 0)
        out["memory"] = {"total_mb": round(total / 1024), "used_mb": round((total - avail) / 1024), "used_pct": round((total - avail) / total * 100, 1) if total else None}
    except OSError:
        pass
    from app.core.config import settings
    paths = {"data": os.path.dirname(os.path.abspath(settings.DATABASE_URL.replace("sqlite:///", ""))) if settings.DATABASE_URL.startswith("sqlite") else ".",
             "uploads": settings.UPLOAD_DIR}
    disks = {}
    for k, p in paths.items():
        try:
            u = shutil.disk_usage(p if os.path.exists(p) else ".")
            disks[k] = {"total_gb": round(u.total / 1e9, 1), "free_gb": round(u.free / 1e9, 1), "used_pct": round(u.used / u.total * 100, 1)}
        except OSError:
            disks[k] = None
    out["disk"] = disks
    return out
