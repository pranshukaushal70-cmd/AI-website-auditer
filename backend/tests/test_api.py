"""API tests. The end-to-end cases run the real engine against a local fixture site."""

import time

import pytest
from conftest import FixtureSite, wait_for_terminal


def test_health_config_and_security_headers(make_client):
    client = make_client()
    r = client.get("/api/health")
    assert r.status_code == 200 and r.json()["status"] == "ok" and r.json()["schema_version"] >= 1
    assert r.headers["X-Content-Type-Options"] == "nosniff"
    assert "frame-ancestors 'none'" in r.headers["Content-Security-Policy"]
    cfg = client.get("/api/config").json()
    assert cfg["max_pages_cap"] == 6 and cfg["rendering_enabled"] is False and cfg["priority_model"] == "priority-v1"


def test_request_id_is_echoed_or_generated(make_client):
    client = make_client()
    assert client.get("/api/health", headers={"X-Request-ID": "demo-req-12345"}).headers["X-Request-ID"] == "demo-req-12345"
    generated = client.get("/api/health", headers={"X-Request-ID": "bad id!"}).headers["X-Request-ID"]
    assert len(generated) == 32 and generated != "bad id!"


@pytest.mark.parametrize("url,code", [
    ("http://127.0.0.1/", "non_public_address"),
    ("http://169.254.169.254/latest/meta-data/", "non_public_address"),
    ("http://[::1]/", "non_public_address"),
    ("http://localhost:8000/", "port_not_allowed"),
    ("http://localhost/", "non_public_host"),
    ("file:///etc/passwd", "unsupported_scheme"),
    ("http://user:pw@example.com/", "credentials_in_url"),
])
def test_unsafe_urls_are_rejected_with_structured_errors(make_client, url, code):
    r = make_client().post("/api/audits", json={"url": url})
    assert r.status_code == 422
    err = r.json()["error"]
    assert err["code"] == code and err["message"] and err["request_id"]


def test_request_validation_errors(make_client):
    client = make_client()
    r = client.post("/api/audits", json={"url": "https://example.com", "max_pages": 50})
    assert r.status_code == 422 and r.json()["error"]["code"] == "validation_error"
    assert r.json()["error"]["details"][0]["field"] == "max_pages"
    r = client.post("/api/audits", json={"url": "https://example.com", "unexpected": 1})
    assert r.status_code == 422


def test_unknown_ids_and_routes(make_client):
    client = make_client()
    for path in ("/api/audits/" + "0" * 32, "/api/audits/not-an-id", "/api/audits/" + "0" * 32 + "/report.pdf"):
        r = client.get(path)
        assert r.status_code == 404 and r.json()["error"]["code"] == "audit_not_found"
    assert client.get("/api/nope").json()["error"]["code"] == "not_found"


def test_creation_rate_limit(make_client):
    client = make_client(creation_rate_limit=2)
    codes = [client.post("/api/audits", json={"url": "http://127.0.0.1/"}).status_code for _ in range(3)]
    assert codes == [422, 422, 429]


def test_end_to_end_audit_persist_export_and_compare(make_client, fixture_site):
    # Opts in to external corroboration (off by default since security phase 4, option A); assertions unchanged.
    client = make_client(local_fixture_port=fixture_site.port)
    r = client.post("/api/audits", json={"url": fixture_site.base + "/", "max_pages": 5, "external_corroboration": True})
    assert r.status_code == 202, r.text
    first = r.json()
    assert first["status"] in ("queued", "running") and first["host"] == "127.0.0.1"

    busy = client.post("/api/audits", json={"url": fixture_site.base + "/"})
    assert busy.status_code == 409 and busy.json()["error"]["code"] == "host_busy"

    done = wait_for_terminal(client, first["id"])
    assert done["status"] in ("completed", "partial"), done
    assert done["progress"]["stages"] == {s: "completed" for s in ("technical", "trust", "engagement", "compose")}
    assert done["report_version"] == 1 and done["pages_checked"] >= 3 and done["readiness_score"] is not None

    findings = client.get(f"/api/audits/{first['id']}/findings").json()["items"]
    titles = {f["title"] for f in findings}
    assert "Missing Mobile Viewport Metadata tag" in titles
    assert "Visible content conflicts with structured data" in titles
    assert "Poor text readability layout (Walls of Text)" in titles
    viewport = next(f for f in findings if f["title"] == "Missing Mobile Viewport Metadata tag")
    assert viewport["affected_pages"] == [fixture_site.base + "/pricing"]
    walls = next(f for f in findings if f["title"].startswith("Poor text readability"))
    assert walls["affected_pages"] == [fixture_site.base + "/blog/launch"]
    defects = [f for f in findings if not f["proactive"]]
    assert sorted(f["priority"]["rank"] for f in defects) == list(range(1, len(defects) + 1))
    assert all(f["priority"] is None for f in findings if f["proactive"])

    filtered = client.get(f"/api/audits/{first['id']}/findings", params={"category": "technical", "include_proactive": False}).json()
    assert filtered["items"] and all(f["category"] == "technical" and not f["proactive"] for f in filtered["items"])
    assert client.get(f"/api/audits/{first['id']}/findings", params={"q": "viewport"}).json()["total"] >= 1

    report = client.get(f"/api/audits/{first['id']}/report").json()["report"]
    assert report["execution"]["unavailable_categories"] == []
    assert report["execution"]["failed_pages"] == [fixture_site.base + "/contact"]  # deliberate 404 in the fixture
    assert any(c["check"] == "corroboration_check" for c in report["execution"]["unavailable_checks"])
    assert report["scope"]["external_sources_checked"] == 0

    exported = client.get(f"/api/audits/{first['id']}/report.json")
    assert exported.status_code == 200 and "attachment" in exported.headers["Content-Disposition"]
    assert exported.json()["export_format"] == "brand-ai-readiness/1"
    v2 = client.get(f"/api/audits/{first['id']}/readiness").json()
    assert v2["model"] == "readiness-v2" and v2["coverage"]["not_assessed"] == []
    penalised = {p["finding_code"] for d in v2["dimensions"].values() for p in d["penalties"]}
    assert penalised == {f["finding_code"] for f in defects}  # every defect, and only defects, carry a penalty
    assert all(p["evidence_excerpt"] and p["affected_pages"] for d in v2["dimensions"].values() for p in d["penalties"])
    assert exported.json()["readiness_v2"] == v2
    pdf = client.get(f"/api/audits/{first['id']}/report.pdf")
    assert pdf.status_code == 200 and pdf.headers["content-type"] == "application/pdf" and pdf.content.startswith(b"%PDF")

    fixture_site.fixed = True  # simulate remediation, then re-audit
    second = client.post("/api/audits", json={"url": fixture_site.base + "/", "max_pages": 5, "external_corroboration": True}).json()
    assert wait_for_terminal(client, second["id"])["status"] in ("completed", "partial")
    diff = client.get("/api/compare", params={"base": first["id"], "target": second["id"]}).json()
    resolved = {x["title"] for x in diff["resolved"]}
    assert "Missing Mobile Viewport Metadata tag" in resolved
    assert "Visible content conflicts with structured data" in resolved
    assert diff["counts"]["new"] == 0
    assert diff["readiness_delta"] is not None and diff["readiness_delta"] > 0

    history = client.get("/api/audits", params={"q": "127.0.0.1"}).json()
    assert history["total"] == 2 and [a["id"] for a in history["items"]] == [second["id"], first["id"]]
    assert client.get("/api/compare", params={"base": first["id"], "target": first["id"]}).status_code == 422


def test_robots_disallowed_site_is_partial_not_clean(make_client, fixture_site):
    original = fixture_site.render

    def render(path):
        if path == "/robots.txt":
            return 200, "text/plain", "User-agent: *\nDisallow: /\n"
        return original(path)

    fixture_site.render = render
    client = make_client(local_fixture_port=fixture_site.port)
    audit = client.post("/api/audits", json={"url": fixture_site.base + "/", "max_pages": 2}).json()
    done = wait_for_terminal(client, audit["id"])
    assert done["status"] == "partial"
    assert [p for p in fixture_site.requests if p not in ("/robots.txt",)] == []  # nothing but robots.txt was fetched
    findings = client.get(f"/api/audits/{audit['id']}/findings").json()["items"]
    assert not any(f["proactive"] for f in findings), "no 'clean' suggestions for categories that never ran"


def test_cancel_running_audit(make_client):
    with FixtureSite(delay=1.5) as slow:
        client = make_client(local_fixture_port=slow.port)
        audit = client.post("/api/audits", json={"url": slow.base + "/", "max_pages": 4}).json()
        deadline = time.monotonic() + 20
        while client.get(f"/api/audits/{audit['id']}").json()["status"] != "running" and time.monotonic() < deadline:
            time.sleep(0.2)
        r = client.post(f"/api/audits/{audit['id']}/cancel")
        assert r.status_code == 200
        done = wait_for_terminal(client, audit["id"], timeout=60)
        assert done["status"] == "cancelled"
        assert client.get(f"/api/audits/{audit['id']}/report.json").json()["error"]["code"] == "report_not_ready"
        assert client.post(f"/api/audits/{audit['id']}/cancel").status_code == 409


def test_hard_runtime_limit_kills_the_engine(make_client):
    with FixtureSite(delay=3.0) as slow:
        client = make_client(local_fixture_port=slow.port, runtime_limit_seconds=30.0, kill_grace_seconds=-25.0)
        audit = client.post("/api/audits", json={"url": slow.base + "/", "max_pages": 4}).json()
        started = time.monotonic()
        done = wait_for_terminal(client, audit["id"], timeout=60)
        assert done["status"] == "timed_out"
        assert time.monotonic() - started < 30
