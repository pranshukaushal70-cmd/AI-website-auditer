import re
from pathlib import Path

import pytest

from brand_platform import prioritization as pr

COMPOSER = Path(__file__).resolve().parents[2] / "skills" / "audit-orchestrator" / "scripts" / "compose_report.py"


def finding(fid, title, severity="medium", confidence=0.9, pages=1, evidence="Found 3 pages.", category="technical", proactive=False):
    return {"id": fid, "title": title, "category": category, "severity": severity, "confidence": confidence,
            "affected_pages": [f"https://e.example/{i}" for i in range(pages)], "evidence": evidence,
            "suggested_action": {}, "proactive": proactive}


def test_score_is_the_product_of_documented_factors():
    f = finding("F-001", "Missing Mobile Viewport Metadata tag", "medium", 0.95, pages=2)
    f["fingerprint"] = pr.fingerprint("technical", f["title"])
    p = pr.score_finding(f, pages_checked=4)
    values = {x["name"]: x["value"] for x in p["factors"]}
    assert values == {"severity": 0.4, "confidence": 0.95, "reach": 0.75, "evidence": 1.0, "effort": 1.0}
    assert p["score"] == pytest.approx(100 * 0.4 * 0.95 * 0.75 * 1.0 * 1.0, abs=0.05)


def test_factor_bounds():
    assert pr.reach_factor(1, 6) == pytest.approx(0.5833, abs=1e-3)
    assert pr.reach_factor(6, 6) == 1.0
    assert pr.reach_factor(10, 6) == 1.0
    assert pr.reach_factor(0, 0) == 1.0
    assert pr.evidence_factor("Detected 2 broken blocks") == 1.0
    assert pr.evidence_factor("See https://e.example/a") == 1.0
    assert pr.evidence_factor("Navigation looks weak.") == 0.85
    assert pr.evidence_factor("") == 0.85


def test_unknown_rule_uses_default_effort_and_says_so():
    f = finding("F-001", "Some future rule")
    f["fingerprint"] = pr.fingerprint("technical", f["title"])
    effort = next(x for x in pr.score_finding(f, 1)["factors"] if x["name"] == "effort")
    assert effort["input"] == "medium"
    assert "default" in effort["explanation"]


def test_ranking_is_deterministic_and_skips_proactive():
    findings = [
        finding("F-001", "Missing Mobile Viewport Metadata tag", "medium", 0.95),
        finding("F-002", "Robots.txt blocks all crawlers from root", "critical", 0.95),
        finding("F-003", "Low Web Agreement / Fact Contradiction", "high", 0.95, category="trust"),
        finding("F-004", "Proactive idea", proactive=True),
    ]
    ranked = pr.prioritise([dict(f) for f in findings], pages_checked=1)
    order = sorted((f for f in ranked if not f.get("proactive")), key=lambda f: f["priority"]["rank"])
    assert [f["id"] for f in order] == ["F-002", "F-003", "F-001"]
    assert "priority" not in ranked[3]
    again = pr.prioritise([dict(f) for f in findings], pages_checked=1)
    assert [f.get("priority") for f in again] == [f.get("priority") for f in ranked]


def test_equal_scores_break_ties_by_id():
    a = finding("F-002", "Rule A")
    b = finding("F-001", "Rule B")
    ranked = pr.prioritise([a, b], pages_checked=1)
    assert {f["id"]: f["priority"]["rank"] for f in ranked} == {"F-001": 1, "F-002": 2}


def test_duplicate_titles_get_distinct_fingerprints():
    ranked = pr.prioritise([finding("F-001", "Same"), finding("F-002", "Same")], pages_checked=1)
    assert ranked[0]["fingerprint"] != ranked[1]["fingerprint"]


def test_effort_table_only_references_rules_the_engine_emits():
    """Guards against the effort table drifting from the composer's finding titles."""
    source = COMPOSER.read_text(encoding="utf-8")
    titles = set(re.findall(r'"title"\s*:\s*"([^"]+)"', source))
    titles |= set(re.findall(r'\("\w+","([^"]+)","', source))  # the tuple-driven technical rules
    emitted = {pr.fingerprint(cat, t) for t in titles for cat in ("technical", "trust", "engagement")}
    missing = [fp for fp in pr.EFFORT_BY_RULE if fp not in emitted]
    assert not missing, missing
