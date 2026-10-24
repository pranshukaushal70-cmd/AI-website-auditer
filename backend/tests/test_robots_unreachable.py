"""Security phase 3 / D11 end to end: robots.txt answering 503 means a partial audit that fetched no page."""

from conftest import wait_for_terminal

FALSE_DEFECTS = {"HTTP requests blocked by anti-bot measures", "Robots.txt blocks all crawlers from root",
                 "Robots.txt blocks specific AI assistants", "No XML Sitemap declared in robots.txt"}


def test_robots_503_gives_a_partial_audit_with_no_page_fetches_and_no_false_defects(make_client, fixture_site):
    original = fixture_site.render

    def render(path):
        if path == "/robots.txt":
            return 503, "text/plain", "Service temporarily unavailable"
        return original(path)

    fixture_site.render = render
    client = make_client(local_fixture_port=fixture_site.port)
    audit = client.post("/api/audits", json={"url": fixture_site.base + "/", "max_pages": 4}).json()
    done = wait_for_terminal(client, audit["id"])

    assert done["status"] == "partial", done
    assert fixture_site.requests and set(fixture_site.requests) == {"/robots.txt"}, fixture_site.requests

    report = client.get(f"/api/audits/{audit['id']}/report").json()["report"]
    assert set(report["execution"]["unavailable_categories"]) == {"technical", "trust", "engagement"}
    unavailable = {(c["category"], c["check"]) for c in report["execution"]["unavailable_checks"]}
    assert ("technical", "crawler_block") in unavailable
    assert report["scope"]["sitemap_checked"] is False

    findings = client.get(f"/api/audits/{audit['id']}/findings").json()["items"]
    assert not FALSE_DEFECTS & {f["title"] for f in findings}
    assert not any(f["proactive"] for f in findings), "no 'clean' suggestions for categories that never ran"

    v2 = client.get(f"/api/audits/{audit['id']}/readiness").json()
    assert v2["score"] is None and v2["coverage"]["not_assessed"] == ["technical", "trust", "engagement"]
