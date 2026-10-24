"""Runtime configuration, read once from environment variables.

Every limit has a conservative default so the platform is safe to start with no configuration.
No secret is required for the core audit workflow.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
ENGINE_ENTRYPOINT = REPO_ROOT / "skills" / "audit-orchestrator" / "scripts" / "run_audit.py"
ENGINE_MANIFEST = REPO_ROOT / "marketplace.json"


def _int(name: str, default: int, low: int, high: int) -> int:
    try:
        value = int(os.environ.get(name, default))
    except ValueError:
        value = default
    return max(low, min(high, value))


def _float(name: str, default: float, low: float, high: float) -> float:
    try:
        value = float(os.environ.get(name, default))
    except ValueError:
        value = default
    return max(low, min(high, value))


def _list(name: str, default: str) -> list[str]:
    return [x.strip() for x in os.environ.get(name, default).split(",") if x.strip()]


RETENTION_MIN_DAYS, RETENTION_MAX_DAYS = 1, 3650


def parse_retention_days(raw: str | None, source: str = "BRAND_PLATFORM_RETENTION_DAYS") -> int | None:
    """Strict parser for the retention period. Unset or empty means retention is disabled (None).

    Unlike the other numeric settings, a bad value is never clamped or ignored: it raises, so a typo can neither
    delete data under a guessed period nor silently switch an intended policy off.
    """
    if raw is None or not raw.strip():
        return None
    text = raw.strip()
    if not text.isascii() or not text.isdigit() or not RETENTION_MIN_DAYS <= int(text) <= RETENTION_MAX_DAYS:
        raise ValueError(f"{source} must be a whole number of days from {RETENTION_MIN_DAYS} to {RETENTION_MAX_DAYS} "
                         f"(leave it unset to keep audits indefinitely); got {raw!r}.")
    return int(text)


@dataclass(frozen=True)
class Settings:
    data_dir: Path = field(default_factory=lambda: Path(os.environ.get("BRAND_PLATFORM_DATA_DIR", REPO_ROOT / "backend" / "var")))
    # Job runner bounds.
    max_concurrent_jobs: int = field(default_factory=lambda: _int("BRAND_PLATFORM_MAX_CONCURRENT_JOBS", 2, 1, 8))
    max_queued_jobs: int = field(default_factory=lambda: _int("BRAND_PLATFORM_MAX_QUEUED_JOBS", 10, 1, 100))
    max_pages_cap: int = 6  # hard cap enforced by the engine itself
    default_max_pages: int = field(default_factory=lambda: _int("BRAND_PLATFORM_DEFAULT_MAX_PAGES", 4, 1, 6))
    stage_timeout_seconds: float = field(default_factory=lambda: _float("BRAND_PLATFORM_STAGE_TIMEOUT", 60.0, 5.0, 120.0))
    runtime_limit_seconds: float = field(default_factory=lambda: _float("BRAND_PLATFORM_RUNTIME_LIMIT", 240.0, 30.0, 300.0))
    kill_grace_seconds: float = 20.0
    # URL policy.
    allowed_ports: tuple[int, ...] = field(default_factory=lambda: tuple(int(p) for p in _list("BRAND_PLATFORM_ALLOWED_PORTS", "80,443")))
    # Test-only: allows exactly http://127.0.0.1:<port>/ so the offline end-to-end tests can audit a local
    # fixture server, and passes the engine's BRAND_AUDIT_LOCAL_FIXTURE to that audit's process. It can be set
    # only in code (Settings(local_fixture_port=...)). It is deliberately NOT read from the environment, so no
    # deployment configuration can re-enable local targets (the former BRAND_PLATFORM_LOCAL_FIXTURE_PORT is ignored).
    local_fixture_port: int | None = None
    # Skip Wikipedia/Wikidata corroboration (reported as unavailable, never as a pass). Used by tests.
    offline_corroboration: bool = field(default_factory=lambda: os.environ.get("BRAND_PLATFORM_OFFLINE_CORROBORATION") == "1")
    creation_rate_limit: int = field(default_factory=lambda: _int("BRAND_PLATFORM_CREATE_RATE_LIMIT", 12, 1, 10000))  # per client per 10 min
    cors_origins: list[str] = field(default_factory=lambda: _list("BRAND_PLATFORM_CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173"))
    frontend_dist: Path = field(default_factory=lambda: Path(os.environ.get("BRAND_PLATFORM_FRONTEND_DIST", REPO_ROOT / "frontend" / "dist")))
    # Largest accepted request body (the only body is {"url", "max_pages"}). Not environment-configurable.
    max_request_bytes: int = 64 * 1024
    # Audit retention in days; None (the default) keeps audits indefinitely and nothing is ever deleted.
    retention_days: int | None = field(default_factory=lambda: parse_retention_days(os.environ.get("BRAND_PLATFORM_RETENTION_DAYS")))

    def __post_init__(self):
        if self.retention_days is not None and not (
                isinstance(self.retention_days, int) and not isinstance(self.retention_days, bool)
                and RETENTION_MIN_DAYS <= self.retention_days <= RETENTION_MAX_DAYS):
            raise ValueError(f"retention_days must be None or an int from {RETENTION_MIN_DAYS} to {RETENTION_MAX_DAYS}; "
                             f"got {self.retention_days!r}.")

    @property
    def db_path(self) -> Path:
        return self.data_dir / "platform.sqlite3"

    @property
    def work_dir(self) -> Path:
        return self.data_dir / "jobs"
