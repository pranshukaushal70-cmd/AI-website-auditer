"""Security phase 5: configurable audit retention (disabled by default), preview/apply purge, migration 3."""

import hashlib
import io
import json
import sqlite3
import time
from datetime import UTC, datetime, timedelta

import pytest
from conftest import local_test_client, make_settings

from brand_platform import config, retention
from brand_platform import db as db_module
from brand_platform import purge as purge_cli
from brand_platform.db import Database
from brand_platform.main import create_app

NOW = datetime(2026, 10, 25, 12, 0, 0, tzinfo=UTC)
DAYS = 30  # cutoff = 2026-09-25T12:00:00Z


def ts(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def add_audit(db: Database, key: str, status: str, created: str, finished: str | None, consent=False, findings=2):
    """One audit with a report and findings. URL and host carry a unique marker for the secure-delete check.

    The id is 32 lowercase hex characters, the only format the API accepts; any other id would 404 for reasons
    unrelated to retention and make API assertions meaningless."""
    audit_id = hashlib.sha256(key.encode()).hexdigest()[:32]
    host = f"host-marker-{key}.example"
    url = f"https://{host}/url-marker-{key}"
    db.create_audit(audit_id, url, host, 2, "v", external_corroboration=bool(consent))
    with db.transaction() as conn:
        conn.execute("UPDATE audits SET status = ?, created_at = ?, finished_at = ?, external_corroboration = ?, report_version = 1 "
                     "WHERE id = ?", (status, created, finished, None if consent is None else int(consent), audit_id))
        conn.execute("INSERT INTO reports (audit_id, version, report_schema, created_at, report_json) VALUES (?, 1, 'x', ?, ?)",
                     (audit_id, created, json.dumps({"site": url, "evidence": f"report-marker-{key}"})))
        for i in range(findings):
            conn.execute("INSERT INTO findings (audit_id, finding_code, fingerprint, title, category, severity, confidence, proactive, "
                         "affected_pages_json, evidence, suggested_action_json) VALUES (?, ?, ?, ?, 'trust', 'high', 0.9, 0, ?, ?, '{}')",
                         (audit_id, f"F-{i}", f"fp-{key}-{i}", f"title-marker-{key}", json.dumps([url]), f"evidence-marker-{key}"))
    return audit_id


@pytest.fixture()
def seeded(tmp_path):
    db = Database(tmp_path / "platform.sqlite3")
    cutoff = NOW - timedelta(days=DAYS)
    ids = {
        "A": add_audit(db, "A", "completed", ts(NOW - timedelta(days=60)), ts(cutoff - timedelta(seconds=1))),  # 1 s past: expired
        "B": add_audit(db, "B", "completed", ts(NOW - timedelta(days=60)), ts(cutoff)),                          # exactly N days: kept
        "C": add_audit(db, "C", "partial", ts(NOW - timedelta(days=2)), ts(NOW - timedelta(days=1))),            # recent: kept
        "D": add_audit(db, "D", "queued", ts(NOW - timedelta(days=900)), None),                                  # active: never
        "E": add_audit(db, "E", "running", ts(NOW - timedelta(days=900)), None),                                 # active: never
        "F": add_audit(db, "F", "interrupted", ts(NOW - timedelta(days=85)), None),                              # created_at fallback: expired
        "G": add_audit(db, "G", "failed", ts(NOW - timedelta(days=300)), ts(NOW - timedelta(days=5))),           # finished_at wins: kept
        "H": add_audit(db, "H", "completed", ts(NOW - timedelta(days=150)), ts(NOW - timedelta(days=146)), consent=None),  # legacy: expired
        "I": add_audit(db, "I", "completed", "not-a-date", "also-not-a-date"),                                   # undated: kept
        "J": add_audit(db, "J", "cancelled", ts(NOW - timedelta(days=55)), ts(NOW - timedelta(days=55))),        # expired
        "K": add_audit(db, "K", "completed", ts(NOW - timedelta(days=24)), ts(NOW - timedelta(days=24)), consent=None),   # legacy, recent: kept
    }
    return db, ids


def counts(db: Database, audit_id: str) -> tuple[int, int, int]:
    with db.connect() as conn:
        return tuple(conn.execute(f"SELECT COUNT(*) FROM {table} WHERE {col} = ?", (audit_id,)).fetchone()[0]
                     for table, col in (("audits", "id"), ("reports", "audit_id"), ("findings", "audit_id")))


EXPIRED, KEPT = {"A", "F", "H", "J"}, {"B", "C", "D", "E", "G", "I", "K"}


# --- configuration --------------------------------------------------------------------------------------

@pytest.mark.parametrize("raw,expected", [(None, None), ("", None), ("  ", None), ("1", 1), ("30", 30), (" 90 ", 90), ("3650", 3650)])
def test_retention_values_accepted(raw, expected):
    assert config.parse_retention_days(raw) == expected


@pytest.mark.parametrize("raw", ["0", "3651", "-1", "30d", "1.5", "1e3", "abc", "٣٠", "+30", "30 days"])
def test_invalid_retention_values_are_rejected_with_a_clear_message(raw):
    with pytest.raises(ValueError, match="whole number of days from 1 to 3650"):
        config.parse_retention_days(raw)


def test_retention_is_disabled_by_default_and_invalid_env_stops_startup(tmp_path, monkeypatch):
    monkeypatch.delenv("BRAND_PLATFORM_RETENTION_DAYS", raising=False)
    assert make_settings(tmp_path).retention_days is None
    monkeypatch.setenv("BRAND_PLATFORM_RETENTION_DAYS", "45")
    assert make_settings(tmp_path).retention_days == 45
    monkeypatch.setenv("BRAND_PLATFORM_RETENTION_DAYS", "forever")
    with pytest.raises(ValueError, match="BRAND_PLATFORM_RETENTION_DAYS"):
        make_settings(tmp_path)  # Settings() is built when the server starts, so startup fails loudly
    for bad in (0, 3651, True, "30"):
        with pytest.raises(ValueError):
            make_settings(tmp_path, retention_days=bad)


def test_config_api_reports_the_policy(make_client):
    assert make_client().get("/api/config").json()["retention_days"] is None
    assert make_client(retention_days=30).get("/api/config").json()["retention_days"] == 30


# --- selection and boundaries ---------------------------------------------------------------------------

def test_plan_selects_exactly_the_expired_finished_audits(seeded):
    db, ids = seeded
    preview = retention.plan(db, DAYS, now=NOW)
    assert preview["cutoff"] == "2026-09-25T12:00:00Z"
    assert {a["id"] for a in preview["eligible"]} == {ids[k] for k in EXPIRED}
    assert preview["undated"] == [ids["I"]]
    basis = {a["id"]: a["age_basis"] for a in preview["eligible"]}
    assert basis[ids["F"]] == "created_at" and basis[ids["A"]] == "finished_at"


def test_disabled_retention_or_a_short_period_deletes_nothing_extra(seeded):
    db, ids = seeded
    assert {a["id"] for a in retention.plan(db, 3650, now=NOW)["eligible"]} == set()
    # With N=1 the cutoff is NOW - 1 day: C finished exactly then, so it is not strictly older and is kept.
    assert {a["id"] for a in retention.plan(db, 1, now=NOW)["eligible"]} == {ids[k] for k in ("A", "B", "F", "G", "H", "J", "K")}


def test_preview_deletes_nothing(seeded):
    db, ids = seeded
    before = {k: counts(db, v) for k, v in ids.items()}
    retention.plan(db, DAYS, now=NOW)
    assert {k: counts(db, v) for k, v in ids.items()} == before
    assert db.retention_runs() == []


# --- deletion ---------------------------------------------------------------------------------------------

def test_apply_deletes_only_expired_audits_with_their_reports_and_findings(seeded):
    db, ids = seeded
    kept_reports = {k: db.get_report(ids[k]) for k in KEPT}
    result = retention.apply(db, DAYS, trigger="manual", now=NOW)
    assert (result["deleted_audits"], result["deleted_reports"], result["deleted_findings"]) == (4, 4, 8)
    for k in EXPIRED:
        assert counts(db, ids[k]) == (0, 0, 0), k
    for k in KEPT:
        assert counts(db, ids[k]) == (1, 1, 2), k
        assert db.get_report(ids[k]) == kept_reports[k]
    assert db.get_audit(ids["K"])["external_corroboration"] is None  # legacy consent untouched
    assert db.get_audit(ids["D"])["status"] == "queued" and db.get_audit(ids["E"])["status"] == "running"


def test_active_audits_are_rechecked_inside_the_transaction(seeded):
    db, ids = seeded
    result = db.purge_audits([ids["D"], ids["E"]], ran_at=ts(NOW), trigger="manual", retention_days=1, cutoff=ts(NOW), skipped_undated=0)
    assert result["deleted_audits"] == 0
    assert counts(db, ids["D"]) == (1, 1, 2) and counts(db, ids["E"]) == (1, 1, 2)


def test_a_failure_rolls_back_the_whole_purge(seeded, monkeypatch):
    db, ids = seeded
    before = {k: counts(db, v) for k, v in ids.items()}

    def boom(*args, **kwargs):
        raise RuntimeError("simulated failure while recording the run")

    monkeypatch.setattr(Database, "_record_retention_run", staticmethod(boom))
    with pytest.raises(RuntimeError):
        retention.apply(db, DAYS, trigger="manual", now=NOW)
    assert {k: counts(db, v) for k, v in ids.items()} == before
    assert db.retention_runs() == []


def test_purge_log_records_counts_and_cutoff_but_no_deleted_content(seeded):
    db, ids = seeded
    retention.apply(db, DAYS, trigger="manual", now=NOW)
    runs = db.retention_runs()
    assert len(runs) == 1
    run = runs[0]
    assert set(run) == {"id", "ran_at", "trigger", "retention_days", "cutoff", "deleted_audits", "deleted_reports",
                        "deleted_findings", "skipped_undated"}
    assert (run["ran_at"], run["cutoff"], run["trigger"], run["retention_days"]) == ("2026-10-25T12:00:00Z", "2026-09-25T12:00:00Z", "manual", DAYS)
    assert (run["deleted_audits"], run["deleted_reports"], run["deleted_findings"], run["skipped_undated"]) == (4, 4, 8, 1)
    text = json.dumps(run)
    for k in EXPIRED:
        assert ids[k] not in text and f"marker-{k}" not in text


def test_deleted_content_is_overwritten_in_the_database_files(seeded):
    db, ids = seeded
    retention.apply(db, DAYS, trigger="manual", now=NOW)
    blob = b"".join(p.read_bytes() for p in db.path.parent.glob(db.path.name + "*"))
    for k in EXPIRED:
        for marker in (f"url-marker-{k}", f"host-marker-{k}", f"report-marker-{k}", f"evidence-marker-{k}", f"title-marker-{k}"):
            assert marker.encode() not in blob, f"{marker} still present in the database files"
    for k in ("B", "K"):  # sanity: the search would find content that still exists
        assert f"url-marker-{k}".encode() in blob


# --- API after a purge ------------------------------------------------------------------------------------

def test_purged_audits_are_gone_from_every_api_view(make_client):
    client = make_client()
    db = client.app.app.state.db  # the LoopbackPeer shim wraps the FastAPI app
    old = add_audit(db, "P", "completed", ts(NOW - timedelta(days=99)), ts(NOW - timedelta(days=99)))
    kept = add_audit(db, "Q", "completed", ts(datetime.now(UTC)), ts(datetime.now(UTC)))
    for audit_id in (old, kept):  # both resolve before the purge, so a later 404 can only come from the purge
        assert client.get(f"/api/audits/{audit_id}").status_code == 200
    retention.apply(db, DAYS, trigger="manual")
    for path in (f"/api/audits/{old}", f"/api/audits/{old}/report", f"/api/audits/{old}/report.json",
                 f"/api/audits/{old}/report.pdf", f"/api/audits/{old}/findings", f"/api/audits/{old}/readiness"):
        r = client.get(path)
        assert r.status_code == 404 and r.json()["error"]["code"] == "audit_not_found", path
    assert client.get("/api/compare", params={"base": old, "target": kept}).status_code == 404
    assert [a["id"] for a in client.get("/api/audits").json()["items"]] == [kept]


# --- migration --------------------------------------------------------------------------------------------

@pytest.mark.parametrize("from_version", [1, 2])
def test_migration_3_preserves_existing_audits_reports_findings_and_consent(tmp_path, monkeypatch, from_version):
    path = tmp_path / "old.sqlite3"
    monkeypatch.setattr(db_module, "MIGRATIONS", db_module.MIGRATIONS[:from_version])
    old_db = Database(path)
    with sqlite3.connect(path) as conn:
        conn.execute("INSERT INTO audits (id, url, host, status, max_pages, created_at, finished_at, engine_version, report_version) "
                     "VALUES (?, 'https://old.example/', 'old.example', 'completed', 4, '2026-01-01T00:00:00Z', '2026-01-01T00:05:00Z', 'v', 1)",
                     ("z" * 32,))
        conn.execute("INSERT INTO reports (audit_id, version, report_schema, created_at, report_json) VALUES (?, 1, 'x', '2026-01-01T00:05:00Z', ?)",
                     ("z" * 32, json.dumps({"site": "https://old.example/"})))
        conn.execute("INSERT INTO findings (audit_id, finding_code, fingerprint, title, category, severity, confidence, proactive, "
                     "affected_pages_json, evidence, suggested_action_json) VALUES (?, 'F-1', 'fp', 't', 'trust', 'high', 0.9, 0, '[]', 'e', '{}')",
                     ("z" * 32,))
        if from_version == 2:
            conn.execute("UPDATE audits SET external_corroboration = 1 WHERE id = ?", ("z" * 32,))
    assert old_db.schema_version() == from_version
    monkeypatch.undo()

    upgraded = Database(path)
    assert upgraded.schema_version() == 3
    audit = upgraded.get_audit("z" * 32)
    assert (audit["url"], audit["status"], audit["finished_at"]) == ("https://old.example/", "completed", "2026-01-01T00:05:00Z")
    assert audit["external_corroboration"] == (None if from_version == 1 else True)
    assert upgraded.get_report("z" * 32) == {"site": "https://old.example/"}
    assert len(upgraded.get_findings("z" * 32)) == 1
    assert upgraded.retention_runs() == []
    with upgraded.connect() as conn:
        assert conn.execute("SELECT 1 FROM sqlite_master WHERE type = 'index' AND name = 'idx_audits_finished'").fetchone()
    assert Database(path).schema_version() == 3  # idempotent


# --- command-line interface -------------------------------------------------------------------------------

@pytest.fixture()
def cli_env(tmp_path, monkeypatch):
    data = tmp_path / "cli-data"
    monkeypatch.setenv("BRAND_PLATFORM_DATA_DIR", str(data))
    monkeypatch.delenv("BRAND_PLATFORM_RETENTION_DAYS", raising=False)
    return data


def run_cli(*args):
    out = io.StringIO()
    code = purge_cli.main(list(args), out=out)
    return code, out.getvalue()


def test_cli_does_nothing_without_a_policy_or_database(cli_env):
    code, text = run_cli()
    assert code == 0 and "Retention is disabled" in text
    code, text = run_cli("--older-than-days", "30", "--apply")
    assert code == 0 and "No platform database" in text
    assert not cli_env.exists()  # the command never creates a database


def test_cli_preview_lists_and_apply_deletes(cli_env):
    db = Database(cli_env / "platform.sqlite3")
    now = datetime.now(UTC)
    old = add_audit(db, "X", "completed", ts(now - timedelta(days=40)), ts(now - timedelta(days=40)))
    new = add_audit(db, "Y", "completed", ts(now - timedelta(days=3)), ts(now - timedelta(days=3)))
    active = add_audit(db, "W", "running", ts(now - timedelta(days=400)), None)
    code, text = run_cli("--older-than-days", "30")
    assert code == 0 and old[:8] in text and new[:8] not in text and active[:8] not in text
    assert "Preview only: nothing was deleted" in text
    assert counts(db, old) == (1, 1, 2) and db.retention_runs() == []
    code, text = run_cli("--older-than-days", "30", "--apply")
    assert code == 0 and "Deleted 1 audit(s), 1 report(s) and 2 finding(s)" in text
    assert counts(db, old) == (0, 0, 0) and counts(db, new) == (1, 1, 2) and counts(db, active) == (1, 1, 2)
    assert db.retention_runs()[0]["trigger"] == "manual"


def test_cli_uses_the_configured_policy(cli_env, monkeypatch):
    db = Database(cli_env / "platform.sqlite3")
    old = add_audit(db, "V", "completed", ts(datetime.now(UTC) - timedelta(days=10)), ts(datetime.now(UTC) - timedelta(days=10)))
    monkeypatch.setenv("BRAND_PLATFORM_RETENTION_DAYS", "7")
    code, text = run_cli()
    assert code == 0 and "Retention period: 7 day(s)" in text and old[:8] in text and counts(db, old) == (1, 1, 2)


@pytest.mark.parametrize("bad", ["0", "3651", "-5", "abc", "1.5"])
def test_cli_rejects_invalid_periods(cli_env, bad, capsys):
    with pytest.raises(SystemExit) as exc:
        run_cli("--older-than-days", bad)
    assert exc.value.code == 2 and "--older-than-days" in capsys.readouterr().err


def test_cli_reports_an_invalid_configured_policy(cli_env, monkeypatch, capsys):
    monkeypatch.setenv("BRAND_PLATFORM_RETENTION_DAYS", "never")
    code, _ = run_cli()
    assert code == 2 and "BRAND_PLATFORM_RETENTION_DAYS" in capsys.readouterr().err


# --- server lifecycle -------------------------------------------------------------------------------------

def _wait(predicate, timeout=10.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.05)
    return False


def test_no_scheduler_without_a_policy(make_client):
    assert make_client().app.app.state.retention is None


def test_scheduler_purges_at_startup_and_stops_cleanly(tmp_path):
    settings = make_settings(tmp_path, retention_days=DAYS)
    seed = Database(settings.db_path)
    old = add_audit(seed, "S", "completed", ts(datetime.now(UTC) - timedelta(days=90)), ts(datetime.now(UTC) - timedelta(days=90)))
    # Startup marks leftover running audits "interrupted" with finished_at = now, so this one is kept for N days.
    running = add_audit(seed, "R", "running", ts(datetime.now(UTC) - timedelta(days=900)), None)
    assert counts(seed, old) == (1, 1, 2)
    app = create_app(settings)
    with local_test_client(app) as client:
        scheduler = app.state.retention
        assert _wait(lambda: scheduler.runs >= 1), "startup purge did not run"
        assert client.get(f"/api/audits/{old}").status_code == 404
        assert client.get(f"/api/audits/{running}").json()["status"] == "interrupted"
        assert seed.retention_runs()[0]["trigger"] == "startup"
    assert not scheduler.alive  # stopped at shutdown


def test_a_failing_purge_never_prevents_startup(tmp_path, monkeypatch):
    def boom(*args, **kwargs):
        raise RuntimeError("simulated purge failure")

    monkeypatch.setattr(retention, "apply", boom)
    app = create_app(make_settings(tmp_path, retention_days=DAYS))
    with local_test_client(app) as client:
        assert client.get("/api/health").status_code == 200
        assert _wait(lambda: app.state.retention.errors >= 1)
    assert not app.state.retention.alive


def test_scheduler_stop_is_prompt_during_the_daily_wait(tmp_path):
    db = Database(tmp_path / "p.sqlite3")
    scheduler = retention.RetentionScheduler(db, DAYS)
    scheduler.start()
    assert _wait(lambda: scheduler.runs >= 1)
    started = time.monotonic()
    scheduler.stop()
    assert not scheduler.alive and time.monotonic() - started < 2.0
    with pytest.raises(ValueError):
        retention.RetentionScheduler(db, None)
