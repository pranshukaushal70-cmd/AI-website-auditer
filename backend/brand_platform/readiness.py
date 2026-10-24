"""Versioned, itemised readiness index (readiness-v2), computed from stored findings.

    dimension score = max(0, 100 − Σ penalty)    for technical, trust, engagement
    penalty         = base(severity) × confidence × reach
    reach           = 0.5 + 0.5 × (affected pages / pages checked)       (same rule as priority-v1)
    overall         = Σ weight × dimension score / Σ weight, over *assessed* dimensions only

Differences from the engine's own index (compose_report.py, here called readiness-v1):
- every penalty is returned as a record that cites the finding, its evidence and affected pages;
- reach is a factor, so a defect on every sampled page costs more than one on a single page;
- a dimension with no usable evidence (execution.missing_categories / unavailable_categories)
  is reported as not assessed and excluded from the overall score, instead of counting as 100.

Base penalties keep v1's values (critical 30, high 18, medium 7) so the two versions differ
only in the three rules above. All constants are design choices, not fitted to outcome data,
and the index has not been validated against search or AI-assistant behaviour. It is an
internal diagnostic, not an Adobe score. Proactive suggestions never carry a penalty.
"""

from __future__ import annotations

MODEL_VERSION = "readiness-v2"
DIMENSIONS = ("technical", "trust", "engagement")
DIMENSION_WEIGHTS = {"technical": 1.0, "trust": 1.0, "engagement": 1.0}
BASE_PENALTY = {"critical": 30.0, "high": 18.0, "medium": 7.0}
BANDS = ((90.0, "excellent"), (75.0, "strong"), (55.0, "needs_attention"), (0.0, "at_risk"))
EVIDENCE_EXCERPT_CHARS = 280


def band(score: float | None) -> str | None:
    if score is None:
        return None
    return next(name for floor, name in BANDS if score >= floor)


def _reach(affected: int, pages_checked: int) -> float:
    share = min(1.0, max(affected, 1) / max(pages_checked, 1))
    return round(0.5 + 0.5 * share, 4)


def penalty_record(finding: dict, pages_checked: int) -> dict:
    severity = finding["severity"]
    base = BASE_PENALTY.get(severity, BASE_PENALTY["medium"])
    confidence = max(0.0, min(1.0, float(finding.get("confidence", 0.85))))
    affected = finding.get("affected_pages") or []
    reach = _reach(len(affected), pages_checked)
    evidence = str(finding.get("evidence") or "")
    return {
        "finding_code": finding.get("finding_code") or finding.get("id"),
        "fingerprint": finding.get("fingerprint"),
        "title": finding["title"],
        "dimension": finding["category"],
        "severity": severity,
        "base_penalty": base,
        "confidence": round(confidence, 2),
        "reach": reach,
        "reach_input": f"{len(affected)}/{max(pages_checked, 1)} pages",
        "penalty": round(base * confidence * reach, 2),
        "affected_pages": list(affected),
        "evidence_excerpt": evidence[:EVIDENCE_EXCERPT_CHARS] + ("…" if len(evidence) > EVIDENCE_EXCERPT_CHARS else ""),
    }


def compute(findings: list[dict], report: dict) -> dict:
    """Readiness-v2 for one stored audit. `findings` use the platform's stored shape."""
    scope = report.get("scope") or {}
    execution = report.get("execution") or {}
    pages_checked = int(scope.get("pages_checked") or 1)
    not_assessed = set(execution.get("missing_categories") or []) | set(execution.get("unavailable_categories") or [])
    unavailable_checks = execution.get("unavailable_checks") or []

    dimensions = {}
    for dim in DIMENSIONS:
        records = sorted((penalty_record(f, pages_checked) for f in findings
                          if f.get("category") == dim and not f.get("proactive")),
                         key=lambda r: (-r["penalty"], r["finding_code"] or ""))
        total = round(sum(r["penalty"] for r in records), 2)
        assessed = dim not in not_assessed
        dimensions[dim] = {
            "assessed": assessed,
            "score": round(max(0.0, 100.0 - total), 1) if assessed else None,
            "total_penalty": total,
            "penalties": records,
            "unavailable_checks": sorted(c.get("check", "") for c in unavailable_checks if c.get("category") == dim),
            "weight": DIMENSION_WEIGHTS[dim],
        }

    assessed = [d for d in DIMENSIONS if dimensions[d]["assessed"]]
    weight_sum = sum(DIMENSION_WEIGHTS[d] for d in assessed)
    score = round(sum(DIMENSION_WEIGHTS[d] * dimensions[d]["score"] for d in assessed) / weight_sum, 1) if weight_sum else None
    v1 = report.get("readiness") or {}
    return {
        "model": MODEL_VERSION,
        "score": score,
        "band": band(score),
        "dimensions": dimensions,
        "coverage": {"assessed": assessed, "not_assessed": [d for d in DIMENSIONS if d not in assessed],
                     "pages_checked": pages_checked, "partial_execution": bool(execution.get("partial"))},
        "parameters": {"base_penalty": BASE_PENALTY, "dimension_weights": DIMENSION_WEIGHTS,
                       "reach": "0.5 + 0.5 × affected/pages_checked", "bands": {name: floor for floor, name in BANDS}},
        "engine_v1": {"score": v1.get("score"), "band": v1.get("band")},
        "method": ("Each dimension starts at 100 and loses base(severity) × confidence × reach per detected defect; the overall "
                   "score is the weighted mean of assessed dimensions. Dimensions without usable evidence are not assessed rather "
                   "than scored as perfect. Internal heuristic: not an Adobe score and not validated against outcomes."),
    }
