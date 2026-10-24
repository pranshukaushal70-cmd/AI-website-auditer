"""Security phase 4: per-audit consent for Wikipedia/Wikidata corroboration (off by default)."""

import json
import sqlite3
from io import BytesIO

import pytest
from conftest import make_settings, wait_for_terminal
from pypdf import PdfReader

from brand_platform import db as db_module
from brand_platform.db import Database
from brand_platform.pdf_report import consent_label, render_pdf
from brand_platform.runner import JobManager


def pdf_text(content: bytes) -> str:
    return " ".join(page.extract_text() for page in PdfReader(BytesIO(content)).pages)


# --- migration ---------------------------------------------------------------------------------------

def test_migration_2_preserves_legacy_audits_and_leaves_consent_unrecorded(tmp_path, monkeypatch):
    path = tmp_path / "legacy.sqlite3"
    monkeypatch.setattr(db_module, "MIGRATIONS", db_module.MIGRATIONS[:1])  # a database as it was before phase 4
    Database(path)
    legacy_report = {"site": "https://old.example/", "scope": {"external_sources_checked": 2}, "findings": []}
    with sqlite3.connect(path) as conn:
        conn.execute("INSERT INTO audits (id, url, host, status, max_pages, created_at, engine_version, readiness_score, report_version) "
                     "VALUES (?, ?, ?, 'completed', 4, '2026-10-20T10:00:00Z', 'marketplace-1.4.0', 81.5, 1)",
                     ("b" * 32, "https://old.example/", "old.example"))
        conn.execute("INSERT INTO reports (audit_id, version, report_schema, created_at, report_json) VALUES (?, 1, 'engine-report/1.4', "
                     "'2026-10-20T10:01:00Z', ?)", ("b" * 32, json.dumps(legacy_report)))
        columns_before = {r[1] for r in conn.execute("PRAGMA table_info(audits)")}
    assert "external_corroboration" not in columns_before

    monkeypatch.undo()
    upgraded = Database(path)
    assert upgraded.schema_version() == db_module.MIGRATIONS[-1][0]  # fully upgraded (2 when written; 3 since phase 5)
    audit = upgraded.get_audit("b" * 32)
    assert audit["external_corroboration"] is None  # not backfilled, not guessed
    assert (audit["url"], audit["status"], audit["readiness_score"], audit["report_version"]) == ("https://old.example/", "completed", 81.5, 1)
    assert upgraded.get_report("b" * 32) == legacy_report
    assert Database(path).schema_version() == db_module.MIGRATIONS[-1][0]  # re-running migrations is a no-op


def test_new_audits_always_record_an_explicit_choice(tmp_path):
    database = Database(tmp_path / "db.sqlite3")
    database.create_audit("c" * 32, "https://a.example/", "a.example", 2, "v")
    database.create_audit("d" * 32, "https://b.example/", "b.example", 2, "v", external_corroboration=True)
    assert database.get_audit("c" * 32)["external_corroboration"] is False
    assert database.get_audit("d" * 32)["external_corroboration"] is True


# --- child process environment ----------------------------------------------------------------------

def test_every_audit_without_opt_in_gets_the_off_switch_and_the_kill_switch_still_applies(tmp_path, monkeypatch):
    monkeypatch.setenv("BRAND_AUDIT_EXTERNAL_CORROBORATION", "on")  # a server-environment value must never leak through
    for offline in (False, True):
        settings = make_settings(tmp_path / str(offline), offline_corroboration=offline)
        jobs = JobManager(settings, Database(settings.db_path))
        try:
            opted_out, opted_in = jobs._child_env(False), jobs._child_env(True)
        finally:
            jobs.shutdown()
        assert opted_out["BRAND_AUDIT_EXTERNAL_CORROBORATION"] == "off"
        assert "BRAND_AUDIT_EXTERNAL_CORROBORATION" not in opted_in
        assert ("BRAND_AUDIT_OFFLINE" in opted_in) is offline  # the operator kill switch overrides an opt-in
    assert jobs._child_env()["BRAND_AUDIT_EXTERNAL_CORROBORATION"] == "off"  # the default is opt-out


# --- request validation and config ---------------------------------------------------------------------

@pytest.mark.parametrize("value", ["yes", "true", 1, "1", None])
def test_consent_must_be_an_explicit_json_boolean(make_client, value):
    r = make_client().post("/api/audits", json={"url": "https://example.com/", "external_corroboration": value})
    assert r.status_code == 422 and r.json()["error"]["code"] == "validation_error"


def test_config_reports_whether_external_lookups_are_available(make_client):
    assert make_client(offline_corroboration=True).get("/api/config").json()["external_corroboration_available"] is False
    assert make_client(offline_corroboration=False).get("/api/config").json()["external_corroboration_available"] is True


# --- end to end ----------------------------------------------------------------------------------------

def test_default_audit_opts_out_sends_nothing_and_records_the_choice_everywhere(make_client, fixture_site):
    client = make_client(local_fixture_port=fixture_site.port)
    created = client.post("/api/audits", json={"url": fixture_site.base + "/", "max_pages": 2}).json()
    assert created["external_corroboration"] is False
    done = wait_for_terminal(client, created["id"])
    assert done["status"] in ("completed", "partial") and done["external_corroboration"] is False

    report = client.get(f"/api/audits/{created['id']}/report").json()["report"]
    assert report["scope"]["external_corroboration"] == "skipped_by_user"
    assert report["scope"]["external_sources_checked"] == 0
    assert [c["check"] for c in report["execution"]["skipped_checks"]] == ["corroboration_check"]
    assert not any(c["check"] == "corroboration_check" for c in report["execution"]["unavailable_checks"])

    history = client.get("/api/audits").json()["items"]
    assert [a["external_corroboration"] for a in history if a["id"] == created["id"]] == [False]
    exported = client.get(f"/api/audits/{created['id']}/report.json").json()
    assert exported["audit"]["external_corroboration"] is False
    assert exported["report"]["scope"]["external_corroboration"] == "skipped_by_user"
    text = pdf_text(client.get(f"/api/audits/{created['id']}/report.pdf").content)
    assert "not requested (user did not opt in)" in text and "skipped_by_user" in text

    opted = client.post("/api/audits", json={"url": fixture_site.base + "/", "max_pages": 2, "external_corroboration": True}).json()
    assert wait_for_terminal(client, opted["id"])["external_corroboration"] is True
    opted_report = client.get(f"/api/audits/{opted['id']}/report").json()["report"]
    assert opted_report["scope"]["external_corroboration"] == "unavailable"  # opted in, but the test server is offline
    assert "opted in" in pdf_text(client.get(f"/api/audits/{opted['id']}/report.pdf").content)


def test_legacy_audit_shows_not_recorded_in_history_and_pdf(tmp_path, make_client):
    client = make_client()
    database = client.app.app.state.db  # the LoopbackPeer shim wraps the FastAPI app
    database.create_audit("e" * 32, "https://legacy.example/", "legacy.example", 2, "v")
    with database.transaction() as conn:
        conn.execute("UPDATE audits SET external_corroboration = NULL WHERE id = ?", ("e" * 32,))
    item = next(a for a in client.get("/api/audits").json()["items"] if a["id"] == "e" * 32)
    assert item["external_corroboration"] is None
    assert consent_label(None) == "Not recorded (predates consent)"
    audit = dict(database.get_audit("e" * 32), engine_version="v")
    report = {"site": "https://legacy.example/", "audited_at": "2026-10-20T10:00:00Z", "summary": {}, "scope": {}, "execution": {}, "findings": []}
    assert "Not recorded (predates consent)" in pdf_text(render_pdf(audit, report, []))
