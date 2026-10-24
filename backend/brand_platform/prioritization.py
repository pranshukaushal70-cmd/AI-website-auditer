"""Transparent, deterministic finding prioritisation.

    priority = 100 × severity × confidence × reach × evidence × effort

Every factor is in (0, 1], so the score is in (0, 100] and each factor's effect can be read
directly: halving a factor halves the score. The factor values are design choices documented
here and in docs/TESTING_AND_EVALUATION.md; they are **not** learned from data and have not
been validated against remediation outcomes. Proactive suggestions are not defects and are
never ranked.

Inputs come only from the engine's rule outputs (severity, confidence, affected pages,
evidence text) plus a fixed, expert-estimated effort table. No LLM is involved.
"""

from __future__ import annotations

import re

MODEL_VERSION = "priority-v1"

SEVERITY_WEIGHT = {"critical": 1.0, "high": 0.7, "medium": 0.4}

EFFORT_MULTIPLIER = {"low": 1.0, "medium": 0.85, "high": 0.7}

# Estimated remediation effort per engine rule, keyed by finding fingerprint.
# low = configuration or template one-liner; medium = content/markup work across pages;
# high = architectural or cross-team change. Unknown rules default to medium.
EFFORT_BY_RULE = {
    "technical:robots-txt-blocks-all-crawlers-from-root": "low",
    "technical:robots-txt-blocks-specific-ai-assistants": "low",
    "technical:no-xml-sitemap-declared-in-robots-txt": "low",
    "technical:http-requests-blocked-by-anti-bot-measures": "medium",
    "technical:client-side-js-rendering-gap-detected": "high",
    "technical:missing-or-invalid-schema-org-structured-data": "medium",
    "technical:content-locked-in-non-text-format-or-missing-alt-text": "medium",
    "technical:missing-mobile-viewport-metadata-tag": "low",
    "technical:questions-detected-in-text-but-missing-faqpage-structured-data": "low",
    "technical:page-is-marked-noindex": "low",
    "technical:canonical-url-is-missing-or-inconsistent": "low",
    "technical:visible-content-conflicts-with-structured-data": "medium",
    "technical:mobile-rendering-has-layout-issues": "high",
    "technical:long-or-cross-host-redirect-chain": "medium",
    "technical:potentially-orphaned-high-value-pages": "medium",
    "trust:stale-copyright-year-in-footer-notice": "low",
    "trust:stale-activity-signals-in-page-text": "medium",
    "trust:missing-e-e-a-t-expertise-or-contact-transparency-signals": "medium",
    "trust:low-web-agreement-fact-contradiction": "high",
    "trust:entity-ambiguity-mistaken-identity-risk": "medium",
    "trust:low-entity-confidence-identity-ambiguity": "medium",
    "engagement:incorrect-or-missing-page-heading-h1-hierarchy": "low",
    "engagement:poor-text-readability-layout-walls-of-text": "medium",
    "engagement:inaccessible-navigation-flow-or-missing-ctas": "medium",
    "engagement:low-text-to-code-ratio-cluttered-page-layout": "high",
    "engagement:above-the-fold-or-mobile-layout-issue": "medium",
    "engagement:low-answerability-of-the-primary-landing-page": "medium",
    "engagement:low-ai-quote-readiness": "medium",
    "engagement:weak-deep-link-context-retention": "medium",
}

_CONCRETE_EVIDENCE = re.compile(r"\d|https?://")


def fingerprint(category: str, title: str) -> str:
    """Stable rule identity used for effort lookup and run-to-run comparison."""
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    return f"{category}:{slug}"


def reach_factor(affected: int, pages_checked: int) -> float:
    """0.5 for a single page of a large sample, rising linearly to 1.0 when every page is affected."""
    share = min(1.0, max(affected, 1) / max(pages_checked, 1))
    return round(0.5 + 0.5 * share, 4)


def evidence_factor(evidence: str) -> float:
    """1.0 when evidence cites a measurement or URL; 0.85 when it is descriptive only."""
    return 1.0 if _CONCRETE_EVIDENCE.search(evidence or "") else 0.85


def score_finding(finding: dict, pages_checked: int) -> dict:
    fp = finding["fingerprint"]
    severity = SEVERITY_WEIGHT.get(finding["severity"], SEVERITY_WEIGHT["medium"])
    confidence = max(0.0, min(1.0, float(finding.get("confidence", 0.85))))
    affected = len(finding.get("affected_pages") or [])
    reach = reach_factor(affected, pages_checked)
    evidence = evidence_factor(finding.get("evidence", ""))
    effort_level = EFFORT_BY_RULE.get(fp, "medium")
    effort = EFFORT_MULTIPLIER[effort_level]
    score = round(100 * severity * confidence * reach * evidence * effort, 1)
    return {
        "model": MODEL_VERSION,
        "score": score,
        "factors": [
            {"name": "severity", "value": severity, "input": finding["severity"],
             "explanation": f"Rule severity '{finding['severity']}' (critical 1.0, high 0.7, medium 0.4)."},
            {"name": "confidence", "value": round(confidence, 2), "input": confidence,
             "explanation": "Engine confidence that the finding is real, as reported by the rule."},
            {"name": "reach", "value": reach, "input": f"{affected}/{max(pages_checked, 1)} pages",
             "explanation": "Share of sampled pages affected: 0.5 for one page of many, 1.0 when all are affected."},
            {"name": "evidence", "value": evidence, "input": "concrete" if evidence == 1.0 else "descriptive",
             "explanation": "1.0 when evidence cites a measurement or URL, 0.85 when it is descriptive only."},
            {"name": "effort", "value": effort, "input": effort_level,
             "explanation": f"Estimated remediation effort '{effort_level}' (low 1.0, medium 0.85, high 0.7); "
                            + ("rule-specific estimate." if fp in EFFORT_BY_RULE else "rule not in the effort table, default used.")},
        ],
    }


def prioritise(findings: list[dict], pages_checked: int) -> list[dict]:
    """Attach `fingerprint` and (for defects) `priority` to each finding; rank defects by score.

    Ties are broken by severity weight, then confidence, then finding id, so ranking is fully
    deterministic for a given report.
    """
    seen: dict[str, int] = {}
    for f in findings:
        fp = fingerprint(f["category"], f["title"])
        seen[fp] = seen.get(fp, 0) + 1
        f["fingerprint"] = fp if seen[fp] == 1 else f"{fp}#{seen[fp]}"
        if not f.get("proactive"):
            f["priority"] = score_finding(f, pages_checked)
    defects = [f for f in findings if not f.get("proactive")]
    defects.sort(key=lambda f: (-f["priority"]["score"], -SEVERITY_WEIGHT.get(f["severity"], 0),
                                -float(f.get("confidence", 0)), f["id"]))
    for rank, f in enumerate(defects, 1):
        f["priority"]["rank"] = rank
    return findings
