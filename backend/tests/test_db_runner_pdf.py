import os
import sqlite3

from conftest import make_settings

from brand_platform.db import MIGRATIONS, Database
from brand_platform.pdf_report import render_pdf
from brand_platform.prioritization import prioritise
from brand_platform.runner import JobManager, validate_report


def sample_report():
    return {"site": "https://e.example/", "audited_at": "2026-10-23T10:00:00Z",
            "summary": {"total_findings": 1, "critical": 0, "high": 1, "medium": 0, "proactive_suggestions_count": 1, "total_items": 2},
            "scope": {"pages_checked": 2, "audited_urls": ["https://e.example/", "https://e.example/a"]},
            "execution": {"partial": True, "unavailable_checks": [{"category": "technical", "check": "js_render_gap", "evidence": "off"}],
                          "unavailable_categories": [], "failed_pages": ["https://e.example/b"], "errors": ["trust: something failed"]},
            "readiness": {"score": 84.0, "band": "strong", "dimensions": {"technical": 87.4, "trust": 100.0, "engagement": 64.6}},
            "findings": [
                {"id": "F-001", "title": "Low Web Agreement / Fact Contradiction", "category": "trust", "severity": "high", "confidence": 0.95,
                 "affected_pages": ["https://e.example/"], "evidence": "Site says Ünïcødé “quotes” — 東京 → München.",
                 "suggested_action": {"summary": "Align facts.", "priority": "high", "how_to_fix": "Edit <address> & Wikidata."}},
                {"id": "F-002", "title": "Proactive idea", "category": "engagement", "severity": "medium", "confidence": 0.95, "proactive": True,
                 "affected_pages": ["https://e.example/"], "evidence": "ok", "suggested_action": {"summary": "Add anchors.", "proactive": True}},
            ]}


def test_migrations_are_idempotent(tmp_path):
    path = tmp_path / "db.sqlite3"
    db = Database(path)
    Database(path)
    assert db.schema_version() == MIGRATIONS[-1][0]
    with sqlite3.connect(path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM schema_migrations").fetchone()[0] == len(MIGRATIONS)
        indexes = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='index'")}
    assert {"idx_audits_created", "idx_audits_host_created", "idx_findings_audit", "idx_findings_fingerprint"} <= indexes


def test_store_and_reload_results(tmp_path):
    db = Database(tmp_path / "db.sqlite3")
    db.create_audit("a" * 32, "https://e.example/", "e.example", 2, "marketplace-1.4.0")
    report = sample_report()
    findings = prioritise([dict(f) for f in report["findings"]], 2)
    version = db.store_result("a" * 32, report, findings, {"status": "partial", "partial": 1, "readiness_score": 84.0})
    assert version == 1
    assert db.store_result("a" * 32, report, findings, {"status": "partial"}) == 2
    stored = db.get_findings("a" * 32)
    assert [f["finding_code"] for f in stored] == ["F-001", "F-002"]
    assert stored[0]["priority"]["rank"] == 1 and stored[1]["priority"] is None
    assert stored[0]["evidence"] == report["findings"][0]["evidence"]
    assert db.get_report("a" * 32)["readiness"]["score"] == 84.0
    audit = db.get_audit("a" * 32)
    assert audit["status"] == "partial" and audit["partial"] is True and audit["report_version"] == 2


def test_list_filters_and_like_escaping(tmp_path):
    db = Database(tmp_path / "db.sqlite3")
    db.create_audit("1" * 32, "https://a_b.example/", "a_b.example", 2, "v")
    db.create_audit("2" * 32, "https://axb.example/", "axb.example", 2, "v")
    items, total = db.list_audits(query="a_b")
    assert total == 1 and items[0]["host"] == "a_b.example"
    items, total = db.list_audits(status="queued", limit=1)
    assert total == 2 and len(items) == 1


def test_active_jobs_are_marked_interrupted_on_startup(tmp_path):
    settings = make_settings(tmp_path)
    db = Database(settings.db_path)
    db.create_audit("3" * 32, "https://e.example/", "e.example", 2, "v")
    db.update_audit("3" * 32, status="running")
    manager = JobManager(settings, db)
    try:
        audit = db.get_audit("3" * 32)
        assert audit["status"] == "interrupted" and audit["finished_at"]
    finally:
        manager.shutdown()


def test_engine_failure_exit_is_never_stored_as_completed(tmp_path):
    """Phase 6: the engine exits 3 when its final progress update cannot be persisted, even though a valid report
    exists. The runner must record a failed audit, not a completed one."""
    import json
    settings = make_settings(tmp_path)
    db = Database(settings.db_path)
    audit_id = "4" * 32
    db.create_audit(audit_id, "https://e.example/", "e.example", 2, "v")
    report_path = tmp_path / "report.json"
    report_path.write_text(json.dumps(sample_report()), encoding="utf-8")
    manager = JobManager(settings, db)
    try:
        manager._finish(audit_id, "exited", 3, report_path,
                        "ERROR: the final progress update could not be persisted; the audit is not reported as successful.")
        audit = db.get_audit(audit_id)
        assert audit["status"] == "failed" and audit["readiness_score"] is None
        assert "engine exited with code 3" in audit["error"] and "final progress update" in audit["error"]
        manager._finish(audit_id, "exited", 0, report_path, "")  # control: exit 0 with the same report is stored
        assert db.get_audit(audit_id)["status"] == "partial"
    finally:
        manager.shutdown()


def test_child_environment_does_not_inherit_secrets(tmp_path):
    os.environ["ANTHROPIC_API_KEY"] = "sk-test-secret"
    os.environ["DATABASE_PASSWORD"] = "hunter2"
    try:
        settings = make_settings(tmp_path)
        manager = JobManager(settings, Database(settings.db_path))
        env = manager._child_env()
        manager.shutdown()
    finally:
        os.environ.pop("ANTHROPIC_API_KEY")
        os.environ.pop("DATABASE_PASSWORD")
    assert "ANTHROPIC_API_KEY" not in env and "DATABASE_PASSWORD" not in env
    assert env["BRAND_AUDIT_DISABLE_RENDER"] == "1"
    assert env["BRAND_AUDIT_OFFLINE"] == "1"


def test_report_contract_validation():
    assert validate_report(sample_report()) == []
    assert validate_report([]) == ["report is not a JSON object"]
    broken = sample_report()
    broken["findings"][0]["severity"] = "low"
    del broken["summary"]
    problems = validate_report(broken)
    assert "missing or invalid 'summary'" in problems
    assert "finding 0 has invalid severity" in problems


def test_pdf_renders_unicode_and_markup_safely():
    report = sample_report()
    findings = prioritise([dict(f) for f in report["findings"]], 2)
    audit = {"id": "a" * 32, "url": "https://e.example/", "host": "e.example", "status": "partial", "engine_version": "marketplace-1.4.0"}
    pdf = render_pdf(audit, report, findings)
    assert pdf.startswith(b"%PDF") and len(pdf) > 2000


def test_pdf_contains_disclaimer_scope_and_ranked_factors():
    from io import BytesIO

    from pypdf import PdfReader

    report = sample_report()
    findings = prioritise([dict(f) for f in report["findings"]], 2)
    audit = {"id": "a" * 32, "url": "https://e.example/", "host": "e.example", "status": "partial", "engine_version": "v"}
    text = " ".join(page.extract_text() for page in PdfReader(BytesIO(render_pdf(audit, report, findings))).pages)
    assert "not an Adobe score" in text
    assert "Low Web Agreement / Fact Contradiction" in text
    assert "Pages that failed to load: https://e.example/b" in text
    assert "\N{REPLACEMENT CHARACTER}" not in text
    assert "readiness-v2 (itemised)" in text and "engine index v1: 84.0" in text
    assert "F-001 Low Web Agreement" in text  # the high-severity trust defect is itemised with its penalty
    assert "Proactive idea" not in text.split("Scope")[0]  # suggestions are not penalised
