import pytest

from brand_platform import readiness


def finding(code, category, severity, confidence=1.0, pages=("https://e.example/",), proactive=False):
    return {"finding_code": code, "fingerprint": f"{category}:{code.lower()}", "title": f"Finding {code}", "category": category,
            "severity": severity, "confidence": confidence, "affected_pages": list(pages), "evidence": f"Evidence for {code}.",
            "proactive": proactive}


def report(pages_checked=2, missing=(), unavailable=(), checks=(), v1=None):
    return {"scope": {"pages_checked": pages_checked},
            "execution": {"partial": bool(missing or unavailable), "missing_categories": list(missing),
                          "unavailable_categories": list(unavailable), "unavailable_checks": list(checks)},
            "readiness": v1 or {}}


def test_penalty_arithmetic_is_base_times_confidence_times_reach():
    two_pages = ("https://e.example/", "https://e.example/a")
    out = readiness.compute([finding("F-1", "technical", "high", 0.9, two_pages),   # 18 × 0.9 × 1.0  = 16.2
                             finding("F-2", "technical", "medium", 1.0)],           # 7 × 1.0 × 0.75 = 5.25
                            report(pages_checked=2))
    tech = out["dimensions"]["technical"]
    assert [p["penalty"] for p in tech["penalties"]] == [16.2, 5.25]
    assert tech["total_penalty"] == 21.45 and tech["score"] == 78.5  # round(100 − 21.45, 1); 78.55 is stored as 78.549…
    assert out["score"] == round((78.5 + 100 + 100) / 3, 1)
    assert out["band"] == "excellent"


def test_every_penalty_cites_its_finding_and_evidence():
    out = readiness.compute([finding("F-1", "trust", "critical")], report())
    p = out["dimensions"]["trust"]["penalties"][0]
    assert p["finding_code"] == "F-1" and p["fingerprint"] == "trust:f-1" and p["evidence_excerpt"] == "Evidence for F-1."
    assert p["affected_pages"] == ["https://e.example/"] and p["reach_input"] == "1/2 pages"
    assert {"base_penalty", "confidence", "reach", "penalty", "severity", "dimension"} <= set(p)


def test_proactive_suggestions_carry_no_penalty():
    out = readiness.compute([finding("S-1", "engagement", "medium", proactive=True)], report())
    assert out["dimensions"]["engagement"]["penalties"] == [] and out["score"] == 100.0


def test_unassessed_dimension_is_excluded_not_scored_perfect():
    findings = [finding("F-1", "technical", "critical")]
    out = readiness.compute(findings, report(unavailable=["trust"], v1={"score": 81.0, "band": "strong"}))
    assert out["dimensions"]["trust"]["assessed"] is False and out["dimensions"]["trust"]["score"] is None
    assert out["coverage"] == {"assessed": ["technical", "engagement"], "not_assessed": ["trust"], "pages_checked": 2,
                               "partial_execution": True}
    tech = 100 - 30 * 0.75
    assert out["score"] == round((tech + 100) / 2, 1)
    assert out["engine_v1"] == {"score": 81.0, "band": "strong"}  # v1 is reported alongside, never overwritten


def test_no_assessed_dimension_gives_no_score():
    out = readiness.compute([], report(missing=["technical", "trust", "engagement"]))
    assert out["score"] is None and out["band"] is None


def test_dimension_score_floors_at_zero_and_unavailable_checks_are_listed():
    many = [finding(f"F-{i}", "engagement", "critical", pages=("a", "b")) for i in range(5)]
    checks = [{"category": "engagement", "check": "rendered_experience"}, {"category": "technical", "check": "js_render_gap"}]
    out = readiness.compute(many, report(checks=checks))
    assert out["dimensions"]["engagement"]["score"] == 0.0
    assert out["dimensions"]["engagement"]["unavailable_checks"] == ["rendered_experience"]


@pytest.mark.parametrize("score,band", [(90.0, "excellent"), (89.9, "strong"), (75.0, "strong"), (55.0, "needs_attention"),
                                        (54.9, "at_risk"), (0.0, "at_risk"), (None, None)])
def test_bands(score, band):
    assert readiness.band(score) == band


def test_result_is_deterministic_regardless_of_input_order():
    fs = [finding("F-1", "technical", "high"), finding("F-2", "technical", "medium"), finding("F-3", "trust", "high")]
    assert readiness.compute(fs, report()) == readiness.compute(list(reversed(fs)), report())
