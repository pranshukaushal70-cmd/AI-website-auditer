"""Audit retention (security phase 5): which finished audits have expired, preview, apply, and the scheduler.

Policy: with ``BRAND_PLATFORM_RETENTION_DAYS = N`` an audit is expired when it is in a finished state and its age
basis is strictly earlier than ``now - N days``. The age basis is ``finished_at``; ``created_at`` is used only for a
finished audit that has no ``finished_at`` (documented fallback). Queued and running audits are never candidates.
An audit whose timestamp cannot be parsed is never deleted; it is counted as "undated". With no policy configured,
nothing is ever deleted. Deletion is transactional (``Database.purge_audits``) and each run is logged without any
content of the deleted audits.
"""

from __future__ import annotations

import logging
import threading
from datetime import UTC, datetime, timedelta

from .db import Database

log = logging.getLogger("brand_platform.retention")

PURGE_INTERVAL_SECONDS = 24 * 3600
TIMESTAMP_FORMAT = "%Y-%m-%dT%H:%M:%SZ"


def parse_timestamp(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.strptime(value, TIMESTAMP_FORMAT).replace(tzinfo=UTC)
    except (TypeError, ValueError):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except (TypeError, ValueError):
            return None
        return parsed.astimezone(UTC) if parsed.tzinfo else None  # naive timestamps are ambiguous: treat as undated


def plan(db: Database, retention_days: int, now: datetime | None = None) -> dict:
    """What a purge would delete right now. Reads only; deletes nothing."""
    now = now or datetime.now(UTC)
    cutoff = now - timedelta(days=retention_days)
    eligible, undated = [], []
    for audit in db.retention_candidates():
        basis_field = "finished_at" if audit["finished_at"] else "created_at"
        basis = parse_timestamp(audit[basis_field])
        if basis is None:
            undated.append(audit["id"])
        elif basis < cutoff:
            eligible.append({"id": audit["id"], "host": audit["host"], "status": audit["status"],
                             "age_basis": basis_field, "age_basis_at": audit[basis_field]})
    eligible.sort(key=lambda a: (a["age_basis_at"], a["id"]))
    return {"retention_days": retention_days, "now": now.strftime(TIMESTAMP_FORMAT),
            "cutoff": cutoff.strftime(TIMESTAMP_FORMAT), "eligible": eligible, "undated": undated}


def apply(db: Database, retention_days: int, trigger: str, now: datetime | None = None) -> dict:
    """Delete every expired audit (with its reports and findings) in one transaction and log the run."""
    preview = plan(db, retention_days, now)
    result = db.purge_audits([a["id"] for a in preview["eligible"]], ran_at=preview["now"], trigger=trigger,
                             retention_days=retention_days, cutoff=preview["cutoff"], skipped_undated=len(preview["undated"]))
    # Counts only: never log hosts, URLs or ids of deleted audits.
    log.info("retention purge", extra={"trigger": trigger, "retention_days": retention_days, **result})
    return dict(result, cutoff=preview["cutoff"], skipped_undated=len(preview["undated"]))


class RetentionScheduler:
    """Runs a purge at startup and then every 24 hours while the server runs, only when a policy is configured.

    It runs in a daemon thread, so a slow or failing purge never delays or blocks startup. Errors are logged and
    retried at the next interval. stop() returns promptly (the wait is interruptible) and is called at shutdown.
    """

    def __init__(self, db: Database, retention_days: int, interval_seconds: float = PURGE_INTERVAL_SECONDS):
        if not retention_days:
            raise ValueError("RetentionScheduler requires a configured retention period")
        self.db, self.retention_days, self.interval = db, retention_days, interval_seconds
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._loop, name="retention", daemon=True)
        self.runs = 0
        self.errors = 0

    def start(self) -> None:
        self._thread.start()

    def stop(self, timeout: float = 30.0) -> None:
        self._stop.set()
        if self._thread.is_alive():
            self._thread.join(timeout)

    @property
    def alive(self) -> bool:
        return self._thread.is_alive()

    def _loop(self) -> None:
        trigger = "startup"
        while not self._stop.is_set():
            try:
                apply(self.db, self.retention_days, trigger)
                self.runs += 1
            except Exception:  # never let a purge failure take the server down; try again next interval
                self.errors += 1
                log.exception("retention purge failed", extra={"trigger": trigger})
            trigger = "scheduled"
            self._stop.wait(self.interval)
