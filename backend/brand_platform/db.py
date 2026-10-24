"""SQLite persistence with ordered, idempotent migrations.

Plain SQL keeps the schema portable: each migration is a list of statements that a
PostgreSQL port could translate one-to-one (TEXT/INTEGER/REAL, ISO-8601 UTC timestamps).
Only the composed report is stored; raw page HTML and sub-audit working files are not retained.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

MIGRATIONS: list[tuple[int, str, list[str]]] = [
    (1, "initial schema", [
        """CREATE TABLE audits (
            id TEXT PRIMARY KEY,
            url TEXT NOT NULL,
            host TEXT NOT NULL,
            status TEXT NOT NULL,
            max_pages INTEGER NOT NULL,
            created_at TEXT NOT NULL,
            started_at TEXT,
            finished_at TEXT,
            progress_json TEXT NOT NULL DEFAULT '{}',
            error TEXT,
            readiness_score REAL,
            readiness_band TEXT,
            total_findings INTEGER,
            critical_count INTEGER,
            high_count INTEGER,
            medium_count INTEGER,
            proactive_count INTEGER,
            pages_checked INTEGER,
            partial INTEGER,
            engine_version TEXT,
            report_version INTEGER
        )""",
        "CREATE INDEX idx_audits_created ON audits(created_at DESC)",
        "CREATE INDEX idx_audits_host_created ON audits(host, created_at DESC)",
        "CREATE INDEX idx_audits_status ON audits(status)",
        """CREATE TABLE findings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            audit_id TEXT NOT NULL REFERENCES audits(id) ON DELETE CASCADE,
            finding_code TEXT NOT NULL,
            fingerprint TEXT NOT NULL,
            title TEXT NOT NULL,
            category TEXT NOT NULL,
            severity TEXT NOT NULL,
            confidence REAL NOT NULL,
            proactive INTEGER NOT NULL DEFAULT 0,
            affected_pages_json TEXT NOT NULL,
            evidence TEXT NOT NULL,
            suggested_action_json TEXT NOT NULL,
            priority_score REAL,
            priority_rank INTEGER,
            priority_factors_json TEXT
        )""",
        "CREATE INDEX idx_findings_audit ON findings(audit_id)",
        "CREATE INDEX idx_findings_fingerprint ON findings(fingerprint)",
        """CREATE TABLE reports (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            audit_id TEXT NOT NULL REFERENCES audits(id) ON DELETE CASCADE,
            version INTEGER NOT NULL,
            report_schema TEXT NOT NULL,
            created_at TEXT NOT NULL,
            report_json TEXT NOT NULL,
            UNIQUE(audit_id, version)
        )""",
    ]),
    # Per-audit consent for Wikipedia/Wikidata corroboration (security phase 4). Nullable on purpose: audits
    # created before this migration have no recorded choice and stay NULL ("not recorded"); nothing is backfilled.
    (2, "per-audit external corroboration consent", [
        "ALTER TABLE audits ADD COLUMN external_corroboration INTEGER",
    ]),
]

ACTIVE_STATUSES = ("queued", "running")
TERMINAL_STATUSES = ("completed", "partial", "failed", "timed_out", "cancelled", "interrupted")


def utc_now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


class Database:
    """Thread-safe access through short-lived connections (one per operation)."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._write_lock = threading.Lock()
        self.migrate()

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.path, timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            yield conn
        finally:
            conn.close()

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        with self._write_lock, self.connect() as conn:
            try:
                conn.execute("BEGIN IMMEDIATE")
                yield conn
                conn.commit()
            except Exception:
                conn.rollback()
                raise

    def migrate(self) -> None:
        with self._write_lock, self.connect() as conn:
            conn.execute("PRAGMA journal_mode = WAL")
            conn.execute("""CREATE TABLE IF NOT EXISTS schema_migrations (
                version INTEGER PRIMARY KEY, description TEXT NOT NULL, applied_at TEXT NOT NULL)""")
            applied = {row[0] for row in conn.execute("SELECT version FROM schema_migrations")}
            for version, description, statements in MIGRATIONS:
                if version in applied:
                    continue
                try:
                    conn.execute("BEGIN IMMEDIATE")
                    for statement in statements:
                        conn.execute(statement)
                    conn.execute("INSERT INTO schema_migrations VALUES (?, ?, ?)", (version, description, utc_now()))
                    conn.commit()
                except Exception:
                    conn.rollback()
                    raise

    def schema_version(self) -> int:
        with self.connect() as conn:
            return conn.execute("SELECT COALESCE(MAX(version), 0) FROM schema_migrations").fetchone()[0]

    # --- audits -----------------------------------------------------------------------------

    def create_audit(self, audit_id: str, url: str, host: str, max_pages: int, engine_version: str,
                     external_corroboration: bool = False) -> None:
        with self.transaction() as conn:
            conn.execute(
                "INSERT INTO audits (id, url, host, status, max_pages, created_at, engine_version, external_corroboration) "
                "VALUES (?, ?, ?, 'queued', ?, ?, ?, ?)",
                (audit_id, url, host, max_pages, utc_now(), engine_version, int(bool(external_corroboration))),
            )

    def update_audit(self, audit_id: str, **fields: Any) -> None:
        if not fields:
            return
        if "progress" in fields:
            fields["progress_json"] = json.dumps(fields.pop("progress"))
        allowed = {"status", "started_at", "finished_at", "progress_json", "error", "readiness_score", "readiness_band",
                   "total_findings", "critical_count", "high_count", "medium_count", "proactive_count", "pages_checked",
                   "partial", "report_version"}
        unknown = set(fields) - allowed
        if unknown:
            raise ValueError(f"Unknown audit fields: {sorted(unknown)}")
        assignments = ", ".join(f"{k} = ?" for k in fields)
        with self.transaction() as conn:
            conn.execute(f"UPDATE audits SET {assignments} WHERE id = ?", (*fields.values(), audit_id))

    def get_audit(self, audit_id: str) -> dict | None:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM audits WHERE id = ?", (audit_id,)).fetchone()
        return _audit_row(row) if row else None

    def list_audits(self, status: str | None = None, query: str | None = None, host: str | None = None,
                    limit: int = 50, offset: int = 0) -> tuple[list[dict], int]:
        clauses, params = [], []
        if status:
            clauses.append("status = ?")
            params.append(status)
        if host:
            clauses.append("host = ?")
            params.append(host)
        if query:
            clauses.append("(url LIKE ? ESCAPE '\\' OR host LIKE ? ESCAPE '\\')")
            like = "%" + query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
            params += [like, like]
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        with self.connect() as conn:
            total = conn.execute(f"SELECT COUNT(*) FROM audits {where}", params).fetchone()[0]
            rows = conn.execute(f"SELECT * FROM audits {where} ORDER BY created_at DESC, rowid DESC LIMIT ? OFFSET ?",
                                (*params, limit, offset)).fetchall()
        return [_audit_row(r) for r in rows], total

    def count_active(self) -> int:
        with self.connect() as conn:
            return conn.execute(f"SELECT COUNT(*) FROM audits WHERE status IN {ACTIVE_STATUSES}").fetchone()[0]

    def active_audit_for_host(self, host: str) -> str | None:
        with self.connect() as conn:
            row = conn.execute(f"SELECT id FROM audits WHERE host = ? AND status IN {ACTIVE_STATUSES} LIMIT 1", (host,)).fetchone()
        return row[0] if row else None

    def mark_interrupted(self) -> int:
        """Jobs that were active when the process stopped cannot be resumed; say so explicitly."""
        with self.transaction() as conn:
            cur = conn.execute(
                f"UPDATE audits SET status = 'interrupted', finished_at = ?, error = 'Server stopped before the audit finished.' "
                f"WHERE status IN {ACTIVE_STATUSES}", (utc_now(),))
            return cur.rowcount

    # --- results ----------------------------------------------------------------------------

    def store_result(self, audit_id: str, report: dict, findings: list[dict], audit_fields: dict) -> int:
        """Persist the report version, its findings, and summary columns in one transaction."""
        with self.transaction() as conn:
            version = conn.execute("SELECT COALESCE(MAX(version), 0) + 1 FROM reports WHERE audit_id = ?", (audit_id,)).fetchone()[0]
            conn.execute("INSERT INTO reports (audit_id, version, report_schema, created_at, report_json) VALUES (?, ?, ?, ?, ?)",
                         (audit_id, version, "engine-report/1.4", utc_now(), json.dumps(report)))
            conn.execute("DELETE FROM findings WHERE audit_id = ?", (audit_id,))
            conn.executemany(
                """INSERT INTO findings (audit_id, finding_code, fingerprint, title, category, severity, confidence, proactive,
                   affected_pages_json, evidence, suggested_action_json, priority_score, priority_rank, priority_factors_json)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                [(audit_id, f["id"], f["fingerprint"], f["title"], f["category"], f["severity"], f["confidence"],
                  int(bool(f.get("proactive"))), json.dumps(f["affected_pages"]), f["evidence"], json.dumps(f["suggested_action"]),
                  f.get("priority", {}).get("score"), f.get("priority", {}).get("rank"),
                  json.dumps(f.get("priority")) if f.get("priority") else None) for f in findings],
            )
            fields = dict(audit_fields, report_version=version)
            assignments = ", ".join(f"{k} = ?" for k in fields)
            conn.execute(f"UPDATE audits SET {assignments} WHERE id = ?", (*fields.values(), audit_id))
            return version

    def get_findings(self, audit_id: str) -> list[dict]:
        with self.connect() as conn:
            rows = conn.execute("SELECT * FROM findings WHERE audit_id = ? ORDER BY proactive ASC, COALESCE(priority_rank, 9999) ASC, id ASC",
                                (audit_id,)).fetchall()
        return [_finding_row(r) for r in rows]

    def get_report(self, audit_id: str, version: int | None = None) -> dict | None:
        with self.connect() as conn:
            if version is None:
                row = conn.execute("SELECT report_json FROM reports WHERE audit_id = ? ORDER BY version DESC LIMIT 1", (audit_id,)).fetchone()
            else:
                row = conn.execute("SELECT report_json FROM reports WHERE audit_id = ? AND version = ?", (audit_id, version)).fetchone()
        return json.loads(row[0]) if row else None


def _audit_row(row: sqlite3.Row) -> dict:
    data = dict(row)
    data["progress"] = json.loads(data.pop("progress_json") or "{}")
    data["partial"] = None if data["partial"] is None else bool(data["partial"])
    consent = data.get("external_corroboration")
    data["external_corroboration"] = None if consent is None else bool(consent)  # None: predates consent recording
    return data


def _finding_row(row: sqlite3.Row) -> dict:
    data = dict(row)
    data["affected_pages"] = json.loads(data.pop("affected_pages_json"))
    data["suggested_action"] = json.loads(data.pop("suggested_action_json"))
    factors = data.pop("priority_factors_json")
    data["priority"] = json.loads(factors) if factors else None
    data["proactive"] = bool(data["proactive"])
    data.pop("priority_score", None)
    data.pop("priority_rank", None)
    return data
