from brand_platform.compare import compare_runs


def audit(aid, score, host="e.example", max_pages=4):
    return {"id": aid, "url": f"https://{host}/", "host": host, "status": "completed", "created_at": "2026-10-01T00:00:00Z",
            "readiness_score": score, "max_pages": max_pages}


def f(fp, category="technical", severity="medium", proactive=False):
    return {"fingerprint": fp, "title": fp, "category": category, "severity": severity, "confidence": 0.9,
            "affected_pages": [], "proactive": proactive, "priority": {"score": 10}}


def report(unavailable=(), missing=(), urls=()):
    return {"execution": {"unavailable_categories": list(unavailable), "missing_categories": list(missing)},
            "scope": {"audited_urls": list(urls)}}


def test_classifies_persistent_new_and_resolved():
    base = [f("a"), f("b"), f("p", proactive=True)]
    target = [f("b", severity="high"), f("c")]
    out = compare_runs(audit("1", 60.0), base, report(), audit("2", 72.5), target, report())
    assert [x["fingerprint"] for x in out["resolved"]] == ["a"]
    assert [x["fingerprint"] for x in out["new"]] == ["c"]
    assert [x["fingerprint"] for x in out["persistent"]] == ["b"]
    assert out["persistent"][0]["severity_changed"] is True
    assert out["persistent"][0]["previous_severity"] == "medium"
    assert out["counts"] == {"persistent": 1, "new": 1, "resolved": 1, "inconclusive": 0}
    assert out["readiness_delta"] == 12.5
    assert out["caveats"] == []


def test_absence_in_an_unavailable_category_is_inconclusive_not_resolved():
    base = [f("t1", category="trust"), f("x")]
    target = [f("e1", category="engagement")]
    out = compare_runs(audit("1", 50.0), base, report(unavailable=["engagement"]),
                       audit("2", None), target, report(missing=["trust"]))
    inconclusive = {x["fingerprint"]: x["side"] for x in out["inconclusive"]}
    assert inconclusive == {"t1": "base", "e1": "target"}
    assert [x["fingerprint"] for x in out["resolved"]] == ["x"]
    assert out["readiness_delta"] is None
    assert any("inconclusive" in c for c in out["caveats"])


def test_caveats_for_scope_differences():
    out = compare_runs(audit("1", 1.0, max_pages=2), [], report(urls=["https://e.example/"]),
                       audit("2", 1.0, host="other.example", max_pages=4), [], report(urls=["https://other.example/"]))
    assert len(out["caveats"]) == 3
