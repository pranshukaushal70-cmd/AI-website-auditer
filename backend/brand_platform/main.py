"""FastAPI application: audit submission, status, findings, history, comparison, export."""

from __future__ import annotations

import logging
import re
import threading
import time
import uuid
from collections import deque
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response
from starlette.exceptions import HTTPException as StarletteHTTPException

from . import __version__, readiness
from .compare import compare_runs
from .config import Settings
from .db import Database
from .exposure import ExposureGuard, is_loopback_origin
from .logging_setup import configure_logging, request_id_var
from .pdf_report import render_pdf
from .prioritization import MODEL_VERSION
from .retention import RetentionScheduler
from .runner import AdmissionError, JobManager, engine_version
from .schemas import Audit, AuditList, AuditStatus, CreateAuditRequest, FindingList, PublicConfig
from .urlsafety import UnsafeURLError, validate_audit_url

log = logging.getLogger("brand_platform.api")
_REQUEST_ID = re.compile(r"^[A-Za-z0-9-]{8,64}$")
_AUDIT_ID = re.compile(r"^[0-9a-f]{32}$")
SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Content-Security-Policy": "default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; "
                               "connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'",
}


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str, details=None):
        super().__init__(message)
        self.status, self.code, self.message, self.details = status, code, message, details


class CreationRateLimiter:
    """Sliding-window limit on audit creation per client address (in-memory, single node)."""

    def __init__(self, limit: int = 12, window_seconds: float = 600.0):
        self.limit, self.window = limit, window_seconds
        self._hits: dict[str, deque] = {}
        self._lock = threading.Lock()

    def allow(self, key: str) -> bool:
        now = time.monotonic()
        with self._lock:
            hits = self._hits.setdefault(key, deque())
            while hits and now - hits[0] > self.window:
                hits.popleft()
            if len(hits) >= self.limit:
                return False
            hits.append(now)
            return True


def _error(status: int, code: str, message: str, details=None) -> JSONResponse:
    body = {"error": {"code": code, "message": message, "request_id": request_id_var.get()}}
    if details is not None:
        body["error"]["details"] = details
    return JSONResponse(status_code=status, content=body)


# Built-UI path segments: letters, digits, '_' and '-', with '.' allowed except first or last. This excludes '..',
# empty segments ('//'), backslashes, ':' (drive letters, NTFS streams), NUL and every other separator or encoding.
_UI_SEGMENT = re.compile(r"[A-Za-z0-9_-](?:[A-Za-z0-9_.-]*[A-Za-z0-9_-])?")
_WINDOWS_DEVICE_NAMES = frozenset({"con", "prn", "aux", "nul", *(f"com{i}" for i in range(10)), *(f"lpt{i}" for i in range(10))})


def ui_file(dist: Path, path: str) -> tuple[str, Path | None]:
    """Map a request path to a file of the built UI: ("file", path), ("fallback", None) for index.html, or
    ("reject", None) for a 404.

    Security phase 7 (H1): the path is checked as a string before any filesystem call. The previous code resolved
    `dist / path` first, and on Windows a path such as `\\\\host\\share\\x` (sent as /%5C%5Chost%5Cshare%5Cx or
    /%2F%2Fhost/share/x) is a UNC path, and resolving and stat-ing it makes Windows try to reach that host over SMB
    (which can leak the user's NTLM hash). Any web page could trigger that with an <img> pointing at the local server. Only a path made of allow-listed
    segments is joined under dist; it is resolved and its containment re-checked, which also refuses a symlink that
    leads out of dist."""
    if not path:
        return "fallback", None
    segments = path.split("/")
    if len(path) > 1024 or not all(
        _UI_SEGMENT.fullmatch(s) and s.split(".", 1)[0].lower() not in _WINDOWS_DEVICE_NAMES for s in segments
    ):
        return "reject", None
    try:
        resolved = dist.joinpath(*segments).resolve(strict=True)
    except (OSError, RuntimeError):
        return "fallback", None  # missing: client-side routes such as /audits/<id> load the UI
    if not resolved.is_relative_to(dist):
        return "reject", None
    return ("file", resolved) if resolved.is_file() else ("fallback", None)


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()
    foreign = [o for o in settings.cors_origins if not is_loopback_origin(o)]
    if foreign:
        # A CORS origin is a site allowed to read API responses; with no authentication only local ones are safe.
        raise ValueError(f"BRAND_PLATFORM_CORS_ORIGINS may only list loopback origins; refusing {foreign}")
    configure_logging()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.db = Database(settings.db_path)
        app.state.jobs = JobManager(settings, app.state.db)
        app.state.rate_limiter = CreationRateLimiter(limit=settings.creation_rate_limit)
        # Retention runs only when a policy is configured; it never blocks startup and stops before the job runner.
        app.state.retention = RetentionScheduler(app.state.db, settings.retention_days) if settings.retention_days else None
        if app.state.retention:
            app.state.retention.start()
        yield
        if app.state.retention:
            app.state.retention.stop()
        app.state.jobs.shutdown()

    app = FastAPI(title="Brand AI-Readiness Intelligence Platform API", version=__version__, lifespan=lifespan,
                  docs_url="/api/docs", openapi_url="/api/openapi.json", redoc_url=None)
    app.state.settings = settings
    app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins, allow_methods=["GET", "POST"],
                       allow_headers=["Content-Type", "X-Request-ID"], expose_headers=["X-Request-ID", "Content-Disposition"])
    # Added after CORS so it runs before it; request_context (below) wraps both, so rejections still
    # carry X-Request-ID and the security headers.
    app.add_middleware(ExposureGuard, max_body_bytes=settings.max_request_bytes)

    @app.middleware("http")
    async def request_context(request: Request, call_next):
        incoming = request.headers.get("x-request-id", "")
        rid = incoming if _REQUEST_ID.match(incoming) else uuid.uuid4().hex
        token = request_id_var.set(rid)
        started = time.perf_counter()
        try:
            response = await call_next(request)
        finally:
            request_id_var.reset(token)
        response.headers["X-Request-ID"] = rid
        # The raw ASGI path, not request.url: building request.url parses the Host header, and a malformed
        # Host (e.g. "[::1") raised before ExposureGuard could reject it.
        path = request.scope.get("path", "")
        for k, v in SECURITY_HEADERS.items():
            if k == "Content-Security-Policy" and path == "/api/docs":
                continue  # Swagger UI loads its assets from a CDN with inline bootstrap code.
            response.headers.setdefault(k, v)
        if path.startswith("/api/"):
            log.info("request", extra={"method": request.method, "path": path, "status_code": response.status_code,
                                       "duration_ms": round((time.perf_counter() - started) * 1000, 1)})
        return response

    @app.exception_handler(ApiError)
    async def api_error_handler(_: Request, exc: ApiError):
        return _error(exc.status, exc.code, exc.message, exc.details)

    @app.exception_handler(RequestValidationError)
    async def validation_handler(_: Request, exc: RequestValidationError):
        details = [{"field": ".".join(str(p) for p in e.get("loc", [])[1:]), "message": e.get("msg")} for e in exc.errors()]
        return _error(422, "validation_error", "The request is invalid.", details)

    @app.exception_handler(StarletteHTTPException)
    async def http_error_handler(_: Request, exc: StarletteHTTPException):
        return _error(exc.status_code, "not_found" if exc.status_code == 404 else "http_error", str(exc.detail))

    @app.exception_handler(Exception)
    async def unhandled_handler(_: Request, exc: Exception):
        log.exception("unhandled error")
        return _error(500, "internal_error", "An unexpected error occurred.")

    def db(request: Request) -> Database:
        return request.app.state.db

    def load_audit(request: Request, audit_id: str) -> dict:
        audit = db(request).get_audit(audit_id) if _AUDIT_ID.match(audit_id) else None
        if not audit:
            raise ApiError(404, "audit_not_found", "No audit exists with this id.")
        return audit

    def load_report(request: Request, audit: dict) -> dict:
        report = db(request).get_report(audit["id"])
        if report is None:
            raise ApiError(409, "report_not_ready", f"This audit has no report (status: {audit['status']}).")
        return report

    # --- meta -------------------------------------------------------------------------------

    @app.get("/api/health")
    def health(request: Request):
        return {"status": "ok", "version": __version__, "schema_version": db(request).schema_version()}

    @app.get("/api/config", response_model=PublicConfig)
    def public_config():
        return PublicConfig(max_pages_cap=settings.max_pages_cap, default_max_pages=settings.default_max_pages,
                            allowed_ports=list(settings.allowed_ports), max_concurrent_jobs=settings.max_concurrent_jobs,
                            max_queued_jobs=settings.max_queued_jobs, runtime_limit_seconds=settings.runtime_limit_seconds,
                            rendering_enabled=False, priority_model=MODEL_VERSION, engine_version=engine_version(),
                            external_corroboration_available=not settings.offline_corroboration,
                            retention_days=settings.retention_days)

    # --- audits -----------------------------------------------------------------------------

    @app.post("/api/audits", status_code=202, response_model=Audit)
    def create_audit(body: CreateAuditRequest, request: Request):
        client = request.client.host if request.client else "unknown"
        if not request.app.state.rate_limiter.allow(client):
            raise ApiError(429, "rate_limited", "Too many audits were started from this address recently.")
        try:
            target = validate_audit_url(body.url, settings.allowed_ports, settings.local_fixture_port)
        except UnsafeURLError as exc:
            raise ApiError(422, exc.code, exc.message) from exc
        max_pages = min(body.max_pages or settings.default_max_pages, settings.max_pages_cap)
        try:
            audit_id = request.app.state.jobs.submit(target.url, target.host, max_pages, body.external_corroboration)
        except AdmissionError as exc:
            raise ApiError(exc.status, exc.code, exc.message) from exc
        return db(request).get_audit(audit_id)

    @app.get("/api/audits", response_model=AuditList)
    def list_audits(request: Request, status: AuditStatus | None = None, q: str | None = Query(default=None, max_length=200),
                    host: str | None = Query(default=None, max_length=253),
                    limit: int = Query(default=25, ge=1, le=100), offset: int = Query(default=0, ge=0)):
        items, total = db(request).list_audits(status=status, query=q, host=host, limit=limit, offset=offset)
        return {"items": items, "total": total, "limit": limit, "offset": offset}

    @app.get("/api/audits/{audit_id}", response_model=Audit)
    def get_audit(audit_id: str, request: Request):
        return load_audit(request, audit_id)

    @app.post("/api/audits/{audit_id}/cancel", response_model=Audit)
    def cancel_audit(audit_id: str, request: Request):
        audit = load_audit(request, audit_id)
        if not request.app.state.jobs.cancel(audit_id):
            raise ApiError(409, "not_cancellable", f"Audit is not running or queued (status: {audit['status']}).")
        return db(request).get_audit(audit_id)

    @app.get("/api/audits/{audit_id}/findings", response_model=FindingList)
    def get_findings(audit_id: str, request: Request, category: str | None = None,
                     severity: str | None = None, q: str | None = Query(default=None, max_length=200),
                     include_proactive: bool = True):
        load_audit(request, audit_id)
        items = db(request).get_findings(audit_id)
        if category:
            items = [f for f in items if f["category"] == category]
        if severity:
            items = [f for f in items if f["severity"] == severity]
        if not include_proactive:
            items = [f for f in items if not f["proactive"]]
        if q:
            needle = q.lower()
            items = [f for f in items if needle in f["title"].lower() or needle in f["evidence"].lower()
                     or any(needle in p.lower() for p in f["affected_pages"])]
        return {"items": items, "total": len(items)}

    @app.get("/api/audits/{audit_id}/report")
    def get_report(audit_id: str, request: Request):
        audit = load_audit(request, audit_id)
        report = load_report(request, audit)
        return {"audit": audit, "report": report}

    @app.get("/api/audits/{audit_id}/readiness")
    def get_readiness(audit_id: str, request: Request):
        audit = load_audit(request, audit_id)
        report = load_report(request, audit)
        return readiness.compute(db(request).get_findings(audit_id), report)

    @app.get("/api/audits/{audit_id}/report.json")
    def export_json(audit_id: str, request: Request):
        audit = load_audit(request, audit_id)
        report = load_report(request, audit)
        findings = db(request).get_findings(audit_id)
        payload = {"export_format": "brand-ai-readiness/1", "audit": audit, "report": report,
                   "prioritised_findings": findings, "readiness_v2": readiness.compute(findings, report)}
        return JSONResponse(payload, headers={"Content-Disposition": f'attachment; filename="audit-{audit["host"]}-{audit_id[:8]}.json"'})

    @app.get("/api/audits/{audit_id}/report.pdf")
    def export_pdf(audit_id: str, request: Request):
        audit = load_audit(request, audit_id)
        report = load_report(request, audit)
        pdf = render_pdf(audit, report, db(request).get_findings(audit_id))
        return Response(pdf, media_type="application/pdf",
                        headers={"Content-Disposition": f'attachment; filename="audit-{audit["host"]}-{audit_id[:8]}.pdf"'})

    @app.get("/api/compare")
    def compare(request: Request, base: str, target: str):
        base_audit, target_audit = load_audit(request, base), load_audit(request, target)
        if base == target:
            raise ApiError(422, "same_audit", "Choose two different audits to compare.")
        for a in (base_audit, target_audit):
            if a["report_version"] is None:
                raise ApiError(409, "report_not_ready", f"Audit {a['id']} has no report (status: {a['status']}).")
        d = db(request)
        return compare_runs(base_audit, d.get_findings(base), d.get_report(base),
                            target_audit, d.get_findings(target), d.get_report(target))

    # --- built frontend (optional, for single-process deployment) ----------------------------

    dist = settings.frontend_dist.resolve()
    if (dist / "index.html").is_file():
        @app.get("/{path:path}", include_in_schema=False)
        def spa(path: str):
            if path.startswith("api/"):
                raise HTTPException(404, "Not found")
            kind, file = ui_file(dist, path)
            if kind == "reject":
                raise HTTPException(404, "Not found")
            return FileResponse(file if kind == "file" else dist / "index.html")

    return app


app = create_app()
