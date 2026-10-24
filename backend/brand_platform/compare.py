"""Run-to-run comparison of two stored audits.

A finding is identified by its rule fingerprint (category + normalised title). Classification:

- persistent: present in both runs.
- new: present only in the target run, and its category produced evidence in the base run.
- resolved: present only in the base run, and its category produced evidence in the target run.
- inconclusive: present in only one run, but its category was missing or unavailable in the
  other run, so absence is not evidence of a fix (or of a regression).

Proactive suggestions are excluded: they are not defects.
"""

from __future__ import annotations


def _unusable_categories(report: dict | None) -> set[str]:
    execution = (report or {}).get("execution", {}) or {}
    return set(execution.get("missing_categories", []) or []) | set(execution.get("unavailable_categories", []) or [])


def _defects(findings: list[dict]) -> dict[str, dict]:
    return {f["fingerprint"]: f for f in findings if not f.get("proactive")}


def _brief(f: dict) -> dict:
    return {"fingerprint": f["fingerprint"], "title": f["title"], "category": f["category"], "severity": f["severity"],
            "confidence": f["confidence"], "affected_pages": f["affected_pages"],
            "priority_score": (f.get("priority") or {}).get("score")}


def compare_runs(base_audit: dict, base_findings: list[dict], base_report: dict | None,
                 target_audit: dict, target_findings: list[dict], target_report: dict | None) -> dict:
    base, target = _defects(base_findings), _defects(target_findings)
    base_gaps, target_gaps = _unusable_categories(base_report), _unusable_categories(target_report)
    result: dict[str, list] = {"persistent": [], "new": [], "resolved": [], "inconclusive": []}

    for fp in sorted(set(base) | set(target)):
        if fp in base and fp in target:
            item = _brief(target[fp])
            item["previous_severity"] = base[fp]["severity"]
            item["severity_changed"] = base[fp]["severity"] != target[fp]["severity"]
            result["persistent"].append(item)
        elif fp in target:
            item = _brief(target[fp])
            if item["category"] in base_gaps:
                item["reason"] = f"Category '{item['category']}' could not be evaluated in the base run."
                result["inconclusive"].append(dict(item, side="target"))
            else:
                result["new"].append(item)
        else:
            item = _brief(base[fp])
            if item["category"] in target_gaps:
                item["reason"] = f"Category '{item['category']}' could not be evaluated in the target run."
                result["inconclusive"].append(dict(item, side="base"))
            else:
                result["resolved"].append(item)

    caveats = []
    if base_audit["host"] != target_audit["host"]:
        caveats.append("The two audits target different hosts; the comparison is not like-for-like.")
    if base_audit["max_pages"] != target_audit["max_pages"]:
        caveats.append(f"Page budgets differ ({base_audit['max_pages']} vs {target_audit['max_pages']}); "
                       "differences may reflect sampling rather than site changes.")
    base_pages = set(((base_report or {}).get("scope") or {}).get("audited_urls", []) or [])
    target_pages = set(((target_report or {}).get("scope") or {}).get("audited_urls", []) or [])
    if base_pages and target_pages and base_pages != target_pages:
        caveats.append("The representative page samples differ between runs.")
    if base_gaps or target_gaps:
        caveats.append("At least one run has missing or unavailable categories; affected findings are marked inconclusive.")

    def score(a: dict):
        return a.get("readiness_score")

    delta = None if score(base_audit) is None or score(target_audit) is None else round(score(target_audit) - score(base_audit), 1)
    return {
        "base": {k: base_audit[k] for k in ("id", "url", "status", "created_at", "readiness_score")},
        "target": {k: target_audit[k] for k in ("id", "url", "status", "created_at", "readiness_score")},
        "readiness_delta": delta,
        "counts": {k: len(v) for k, v in result.items()},
        "caveats": caveats,
        **result,
    }
