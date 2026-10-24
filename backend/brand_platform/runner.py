"""Bounded background execution of the original audit engine.

Each audit runs `skills/audit-orchestrator/scripts/run_audit.py` in its own process group:
- concurrency is capped by a fixed-size thread pool; admission is capped by a queue limit;
- the engine enforces per-stage and whole-pipeline timeouts, and this runner adds a hard kill
  (whole process tree) shortly after the engine's own deadline;
- cancellation kills the process tree and records `cancelled`;
- the child receives a minimal environment (no inherited secrets) with rendering disabled;
- only the composed report is kept; the per-job working directory is deleted afterwards.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import signal
import subprocess
import sys
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from . import prioritization
from .config import ENGINE_ENTRYPOINT, ENGINE_MANIFEST, Settings
from .db import Database, utc_now

log = logging.getLogger("brand_platform.runner")

STAGE_ORDER = ("technical", "trust", "engagement", "compose")
_ENV_PASSTHROUGH = ("PATH", "SYSTEMROOT", "SYSTEMDRIVE", "WINDIR", "TEMP", "TMP", "TMPDIR", "HOME", "USERPROFILE",
                    "LANG", "LC_ALL", "SSL_CERT_FILE", "SSL_CERT_DIR", "REQUESTS_CA_BUNDLE",
                    "HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY", "http_proxy", "https_proxy", "no_proxy")


class AdmissionError(Exception):
    def __init__(self, code: str, message: str, status: int):
        super().__init__(message)
        self.code, self.message, self.status = code, message, status


def engine_version() -> str:
    try:
        return "marketplace-" + json.loads(ENGINE_MANIFEST.read_text(encoding="utf-8")).get("version", "unknown")
    except (OSError, ValueError):
        return "marketplace-unknown"


def validate_report(report: object) -> list[str]:
    """Minimal structural check of the engine's output contract before it is trusted."""
    problems = []
    if not isinstance(report, dict):
        return ["report is not a JSON object"]
    for key, kind in (("site", str), ("audited_at", str), ("summary", dict), ("scope", dict), ("findings", list), ("execution", dict)):
        if not isinstance(report.get(key), kind):
            problems.append(f"missing or invalid '{key}'")
    for i, f in enumerate(report.get("findings") or []):
        if not isinstance(f, dict):
            problems.append(f"finding {i} is not an object")
            continue
        for key in ("id", "title", "category", "severity", "confidence", "affected_pages", "evidence", "suggested_action"):
            if key not in f:
                problems.append(f"finding {i} missing '{key}'")
        if f.get("severity") not in ("critical", "high", "medium"):
            problems.append(f"finding {i} has invalid severity")
    return problems


def kill_tree(proc: subprocess.Popen) -> None:
    if proc.poll() is not None:
        return
    try:
        if os.name == "nt":
            subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"], capture_output=True, timeout=15)
        else:
            os.killpg(proc.pid, signal.SIGKILL)
    except (OSError, subprocess.SubprocessError):
        pass
    try:
        proc.kill()
    except OSError:
        pass


class JobManager:
    def __init__(self, settings: Settings, db: Database):
        self.settings = settings
        self.db = db
        self._pool = ThreadPoolExecutor(max_workers=settings.max_concurrent_jobs, thread_name_prefix="audit")
        self._cancel_events: dict[str, threading.Event] = {}
        self._lock = threading.Lock()
        settings.work_dir.mkdir(parents=True, exist_ok=True)
        interrupted = db.mark_interrupted()
        if interrupted:
            log.warning("marked %d stale audit(s) as interrupted", interrupted)

    # --- admission ----------------------------------------------------------------------------

    def submit(self, url: str, host: str, max_pages: int, external_corroboration: bool = False) -> str:
        with self._lock:
            if self.db.count_active() >= self.settings.max_queued_jobs:
                raise AdmissionError("queue_full", "Too many audits are queued or running. Try again shortly.", 429)
            existing = self.db.active_audit_for_host(host)
            if existing:
                raise AdmissionError("host_busy", f"An audit of {host} is already in progress ({existing}).", 409)
            audit_id = uuid.uuid4().hex
            self.db.create_audit(audit_id, url, host, max_pages, engine_version(), external_corroboration)
            self._cancel_events[audit_id] = threading.Event()
        self._pool.submit(self._run_safely, audit_id, url, max_pages, external_corroboration)
        log.info("audit queued", extra={"audit_id": audit_id, "host": host})
        return audit_id

    def cancel(self, audit_id: str) -> bool:
        event = self._cancel_events.get(audit_id)
        audit = self.db.get_audit(audit_id)
        if not audit or audit["status"] not in ("queued", "running") or event is None:
            return False
        event.set()
        return True

    def shutdown(self) -> None:
        for event in self._cancel_events.values():
            event.set()
        self._pool.shutdown(wait=True, cancel_futures=True)

    # --- execution ----------------------------------------------------------------------------

    def _run_safely(self, audit_id: str, url: str, max_pages: int, external_corroboration: bool = False) -> None:
        try:
            self._run(audit_id, url, max_pages, external_corroboration)
        except Exception as exc:  # never leave a job stuck in 'running'
            log.exception("audit crashed", extra={"audit_id": audit_id})
            self.db.update_audit(audit_id, status="failed", finished_at=utc_now(), error=f"Internal runner error: {type(exc).__name__}")
        finally:
            self._cancel_events.pop(audit_id, None)

    def _child_env(self, external_corroboration: bool = False) -> dict[str, str]:
        env = {k: v for k, v in os.environ.items() if k in _ENV_PASSTHROUGH}
        env.update({"PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1", "PYTHONDONTWRITEBYTECODE": "1",
                    "BRAND_AUDIT_DISABLE_RENDER": "1"})
        if not external_corroboration:
            # Every audit without an explicit opt-in: the trust stage sends nothing to Wikipedia/Wikidata.
            env["BRAND_AUDIT_EXTERNAL_CORROBORATION"] = "off"
        if self.settings.offline_corroboration:
            # Operator kill switch: also applies to audits that opted in.
            env["BRAND_AUDIT_OFFLINE"] = "1"
        if self.settings.local_fixture_port is not None:
            env["BRAND_AUDIT_LOCAL_FIXTURE"] = str(self.settings.local_fixture_port)
        return env

    def _run(self, audit_id: str, url: str, max_pages: int, external_corroboration: bool = False) -> None:
        cancel = self._cancel_events.get(audit_id) or threading.Event()
        if cancel.is_set():
            self.db.update_audit(audit_id, status="cancelled", finished_at=utc_now())
            return
        workdir = self.settings.work_dir / audit_id
        workdir.mkdir(parents=True, exist_ok=True)
        report_path, progress_path = workdir / "report.json", workdir / "progress.json"
        # Not `-I`: isolated mode would drop the PYTHONIOENCODING/PYTHONUTF8 settings above.
        # The environment is already minimal and the script is trusted repository code.
        cmd = [sys.executable, str(ENGINE_ENTRYPOINT), url, "--max-pages", str(max_pages),
               "--output", str(report_path), "--progress-file", str(progress_path),
               "--stage-timeout", str(self.settings.stage_timeout_seconds),
               "--runtime-limit", str(self.settings.runtime_limit_seconds)]
        self.db.update_audit(audit_id, status="running", started_at=utc_now(),
                             progress={"stages": {s: "pending" for s in STAGE_ORDER}, "current": None})
        popen_kwargs = {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP} if os.name == "nt" else {"start_new_session": True}
        hard_deadline = time.monotonic() + self.settings.runtime_limit_seconds + self.settings.kill_grace_seconds
        stderr_path = workdir / "stderr.txt"
        try:
            with open(stderr_path, "w", encoding="utf-8", errors="replace") as stderr_file:
                proc = subprocess.Popen(cmd, cwd=str(ENGINE_ENTRYPOINT.parents[3]), env=self._child_env(external_corroboration),
                                        stdout=subprocess.DEVNULL, stderr=stderr_file, **popen_kwargs)
                outcome = self._watch(audit_id, proc, progress_path, cancel, hard_deadline)
            stderr_tail = stderr_path.read_text(encoding="utf-8", errors="replace")[-1500:]
            self._finish(audit_id, outcome, proc.returncode, report_path, stderr_tail)
        finally:
            shutil.rmtree(workdir, ignore_errors=True)

    def _watch(self, audit_id, proc, progress_path: Path, cancel: threading.Event, hard_deadline: float) -> str:
        last_progress = None
        while True:
            try:
                proc.wait(timeout=0.5)
                self._sync_progress(audit_id, progress_path, last_progress)
                return "exited"
            except subprocess.TimeoutExpired:
                pass
            last_progress = self._sync_progress(audit_id, progress_path, last_progress)
            if cancel.is_set():
                kill_tree(proc)
                proc.wait(timeout=30)
                return "cancelled"
            if time.monotonic() > hard_deadline:
                kill_tree(proc)
                proc.wait(timeout=30)
                return "timed_out"

    def _sync_progress(self, audit_id: str, progress_path: Path, last):
        try:
            progress = json.loads(progress_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return last
        if progress != last:
            self.db.update_audit(audit_id, progress={"stages": progress.get("stages", {}), "current": progress.get("current")})
        return progress

    def _finish(self, audit_id: str, outcome: str, returncode: int | None, report_path: Path, stderr_tail: str) -> None:
        if outcome == "cancelled":
            self.db.update_audit(audit_id, status="cancelled", finished_at=utc_now(), error="Cancelled by user.")
            return
        if outcome == "timed_out":
            self.db.update_audit(audit_id, status="timed_out", finished_at=utc_now(),
                                 error="The audit exceeded the hard runtime limit and was stopped.")
            return
        try:
            report = json.loads(report_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            report = None
        problems = validate_report(report) if report is not None else ["engine produced no report"]
        if returncode != 0 or problems:
            detail = "; ".join(problems) if problems else f"engine exited with code {returncode}"
            self.db.update_audit(audit_id, status="failed", finished_at=utc_now(),
                                 error=f"{detail}. {stderr_tail.strip()[-600:]}".strip())
            return
        findings = [dict(f, confidence=float(f["confidence"])) for f in report["findings"]]
        pages_checked = int(report["scope"].get("pages_checked") or 1)
        prioritization.prioritise(findings, pages_checked)
        summary, readiness, execution = report["summary"], report.get("readiness") or {}, report["execution"]
        partial = bool(execution.get("partial"))
        version = self.db.store_result(audit_id, report, findings, {
            "status": "partial" if partial else "completed",
            "finished_at": utc_now(),
            "readiness_score": readiness.get("score"),
            "readiness_band": readiness.get("band"),
            "total_findings": summary.get("total_findings"),
            "critical_count": summary.get("critical"),
            "high_count": summary.get("high"),
            "medium_count": summary.get("medium"),
            "proactive_count": summary.get("proactive_suggestions_count"),
            "pages_checked": pages_checked,
            "partial": int(partial),
        })
        log.info("audit finished", extra={"audit_id": audit_id, "partial": partial, "report_version": version})
