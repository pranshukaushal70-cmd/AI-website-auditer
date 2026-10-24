"""Offline evaluation harness for the audit engine's page-level detectors.

Each labelled case is one HTML page (plus an optional robots.txt, response headers and a
sitemap lastmod year). The harness runs the *unmodified* engine functions on it through
their existing injection points, so nothing touches the network:

- technical  -> check_technical.analyze_technical(url, max_crawl_pages=1, fetch_fn=<fixture server>)
- trust      -> check_trust.analyze_trust(html, url, current_year=..., fetch_sitemap_fn=..., external_apis_fn=...)
- engagement -> check_engagement.analyze_engagement(len(html), html)

A detector's output is mapped to a binary prediction: status "fail" or "warning" means
"defect detected" (1), "pass" means "no defect" (0), and anything else ("unavailable",
"not_checked") is an abstention. Abstentions are counted and reported, never scored as
correct or incorrect. Labels are the annotator's judgement of the documented criterion
(see docs/TESTING_AND_EVALUATION.md); they are not derived from detector output.
"""

from __future__ import annotations

import contextlib
import email
import hashlib
import http.client
import io
import json
import os
import platform
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATASET_DIR = Path(__file__).resolve().parent / "fixtures"
for _p in ("crawl-render-audit", "freshness-corroboration", "engagement-audit"):
    sys.path.insert(0, str(ROOT / "skills" / _p / "scripts"))

HARNESS_VERSION = "eval-harness/1"
DEFAULT_ROBOTS = "User-agent: *\nAllow: /\n"


def _status_prediction(check: dict | None) -> int | None:
    status = (check or {}).get("status")
    if status in ("fail", "warning"):
        return 1
    if status == "pass":
        return 0
    return None


def _ai_crawler_prediction(tech: dict) -> int | None:
    robots = tech.get("robots_txt") or {}
    if robots.get("status") != "found":
        return None
    return 1 if robots.get("blocked_bots") else 0


# detector id -> (stage, extractor(stage_output) -> 1 | 0 | None, engine check key for evidence)
DETECTORS = {
    "technical.ai_crawler_block": ("technical", _ai_crawler_prediction, "robots_txt"),
    "technical.viewport": ("technical", lambda o: _status_prediction(o.get("viewport_check")), "viewport_check"),
    "technical.structured_data": ("technical", lambda o: _status_prediction(o.get("structured_data")), "structured_data"),
    "technical.faq_schema": ("technical", lambda o: _status_prediction(o.get("faq_schema_check")), "faq_schema_check"),
    "technical.noindex": ("technical", lambda o: _status_prediction(o.get("indexability_check")), "indexability_check"),
    "technical.fact_parity": ("technical", lambda o: _status_prediction(o.get("fact_parity")), "fact_parity"),
    "technical.image_alt": ("technical", lambda o: _status_prediction(o.get("locked_content")), "locked_content"),
    "trust.stale_content": ("trust", lambda o: _status_prediction(o.get("multi_signal_freshness")), "multi_signal_freshness"),
    "trust.eeat": ("trust", lambda o: _status_prediction(o.get("eeat_check")), "eeat_check"),
    "engagement.h1": ("engagement", lambda o: _status_prediction(o.get("h1_audit")), "h1_audit"),
    "engagement.readability": ("engagement", lambda o: _status_prediction(o.get("readability")), "readability"),
    "engagement.navigation_cta": ("engagement", lambda o: _status_prediction(o.get("navigation_cta")), "navigation_cta"),
    "engagement.clutter": ("engagement", lambda o: _status_prediction(o.get("clutter")), "clutter"),
}


@dataclass
class Case:
    id: str
    url: str
    html: str
    labels: dict[str, bool]
    rationale: dict[str, str]
    kind: str = "typical"
    robots: str | None = None
    headers: dict[str, str] = field(default_factory=dict)
    sitemap_lastmod_year: int | None = None


def load_dataset(version: str = "v1") -> tuple[dict, list[Case]]:
    base = DATASET_DIR / version
    manifest_path = base / "cases.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    cases = []
    for raw in manifest["cases"]:
        unknown = set(raw["labels"]) - set(DETECTORS)
        if unknown:
            raise ValueError(f"case {raw['id']}: unknown detector(s) {sorted(unknown)}")
        missing = set(raw["labels"]) - set(raw.get("rationale", {}))
        if missing:
            raise ValueError(f"case {raw['id']}: label(s) without rationale {sorted(missing)}")
        cases.append(Case(
            id=raw["id"], url=raw["url"], kind=raw.get("kind", "typical"),
            html=(base / "pages" / raw["page"]).read_text(encoding="utf-8"),
            labels=raw["labels"], rationale=raw["rationale"], robots=raw.get("robots"),
            headers=raw.get("headers", {}), sitemap_lastmod_year=raw.get("sitemap_lastmod_year"),
        ))
    ids = [c.id for c in cases]
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate case ids")
    return manifest, cases


def dataset_digest(version: str = "v1") -> str:
    """SHA-256 over the manifest and every page, so results are tied to an exact dataset."""
    base = DATASET_DIR / version
    h = hashlib.sha256()
    for path in sorted([base / "cases.json", *(base / "pages").glob("*.html")]):
        h.update(path.relative_to(base).as_posix().encode())
        h.update(path.read_bytes().replace(b"\r\n", b"\n"))
    return h.hexdigest()


def _http_headers(url: str, extra: dict[str, str]) -> http.client.HTTPMessage:
    """Headers in the same type the engine's real fetch_url returns (response.info()).

    Using a plain dict here would exercise code paths that never run in production
    (see D14 in docs/PROJECT_AUDIT.md), so the fixture server mirrors fetch_url exactly.
    """
    message = email.message_from_string("".join(f"{k}: {v}\n" for k, v in extra.items()) + "\n",
                                        _class=http.client.HTTPMessage)
    message["_final_url"] = url
    message["_redirect_chain"] = []
    return message


def _fixture_fetch(case: Case):
    page_key = case.url.rstrip("/")

    def fetch(url, **_kwargs):
        if url.endswith("/robots.txt"):
            return 200, case.robots if case.robots is not None else DEFAULT_ROBOTS, _http_headers(url, {"Content-Type": "text/plain"})
        if url.rstrip("/") == page_key:
            return 200, case.html, _http_headers(url, {"Content-Type": "text/html; charset=utf-8", **case.headers})
        return 404, "", _http_headers(url, {})

    return fetch


def run_stages(case: Case, current_year: int) -> dict[str, dict]:
    """Run the three engine stages on one case. Engine stdout chatter is suppressed."""
    import check_engagement
    import check_technical
    import check_trust

    out: dict[str, dict] = {}
    needed = {DETECTORS[d][0] for d in case.labels}
    with contextlib.redirect_stdout(io.StringIO()):
        if "technical" in needed:
            out["technical"] = check_technical.analyze_technical(case.url, max_crawl_pages=1, fetch_fn=_fixture_fetch(case))
        if "trust" in needed:
            out["trust"] = check_trust.analyze_trust(
                case.html, case.url, current_year=current_year,
                http_last_modified=case.headers.get("Last-Modified"),
                fetch_sitemap_fn=lambda _base: case.sitemap_lastmod_year,
                external_apis_fn=lambda _brand: [])
        if "engagement" in needed:
            out["engagement"] = check_engagement.analyze_engagement(len(case.html), case.html)
    return out


def _ratio(num: int, den: int) -> float | None:
    return round(num / den, 4) if den else None


def metrics(tp: int, fp: int, fn: int, tn: int) -> dict:
    precision = _ratio(tp, tp + fp)
    recall = _ratio(tp, tp + fn)
    f1 = None
    if precision is not None and recall is not None and (precision + recall) > 0:
        f1 = round(2 * precision * recall / (precision + recall), 4)
    elif precision is not None and recall is not None:
        f1 = 0.0
    return {"tp": tp, "fp": fp, "fn": fn, "tn": tn, "precision": precision, "recall": recall, "f1": f1,
            "false_positive_rate": _ratio(fp, fp + tn), "accuracy": _ratio(tp + tn, tp + fp + fn + tn)}


def evaluate(version: str = "v1") -> dict:
    manifest, cases = load_dataset(version)
    current_year = int(manifest["current_year"])
    previous_render = os.environ.get("BRAND_AUDIT_DISABLE_RENDER")
    os.environ["BRAND_AUDIT_DISABLE_RENDER"] = "1"  # rendering is out of scope and must not launch a browser
    try:
        rows, timings = [], []
        for case in cases:
            started = time.perf_counter()
            stages = run_stages(case, current_year)
            timings.append(time.perf_counter() - started)
            for detector, expected in sorted(case.labels.items()):
                stage, extract, check_key = DETECTORS[detector]
                predicted = extract(stages[stage])
                evidence = str(((stages[stage].get(check_key) or {}).get("evidence")) or "")
                rows.append({"case": case.id, "kind": case.kind, "detector": detector, "expected": int(bool(expected)),
                             "predicted": predicted, "outcome": _outcome(int(bool(expected)), predicted),
                             "engine_evidence": evidence[:300], "rationale": case.rationale[detector]})
    finally:
        if previous_render is None:
            os.environ.pop("BRAND_AUDIT_DISABLE_RENDER", None)
        else:
            os.environ["BRAND_AUDIT_DISABLE_RENDER"] = previous_render

    per_detector = {}
    for detector in DETECTORS:
        mine = [r for r in rows if r["detector"] == detector]
        if not mine:
            continue
        counts = {k: sum(1 for r in mine if r["outcome"] == k) for k in ("tp", "fp", "fn", "tn")}
        per_detector[detector] = {
            "labelled": len(mine),
            "positives": sum(r["expected"] for r in mine),
            "negatives": sum(1 - r["expected"] for r in mine),
            "abstained": sum(1 for r in mine if r["outcome"] == "abstain"),
            **metrics(**counts),
        }
    per_kind = {}
    for kind in sorted({r["kind"] for r in rows}):
        mine = [r for r in rows if r["kind"] == kind]
        per_kind[kind] = {"labelled": len(mine), **metrics(**{k: sum(1 for r in mine if r["outcome"] == k) for k in ("tp", "fp", "fn", "tn")})}
    totals = {k: sum(d[k] for d in per_detector.values()) for k in ("tp", "fp", "fn", "tn")}
    scored = [d for d in per_detector.values() if d["f1"] is not None]
    timings_sorted = sorted(timings)
    return {
        "harness": HARNESS_VERSION,
        "dataset": {"version": version, "sha256": dataset_digest(version), "cases": len(cases),
                    "labels": len(rows), "current_year": current_year},
        "engine_manifest_version": json.loads((ROOT / "marketplace.json").read_text(encoding="utf-8")).get("version"),
        "per_detector": per_detector,
        "per_kind": per_kind,
        "micro": metrics(**totals),
        "macro_f1": round(sum(d["f1"] for d in scored) / len(scored), 4) if scored else None,
        "abstentions": sum(d["abstained"] for d in per_detector.values()),
        "errors": [r for r in rows if r["outcome"] in ("fp", "fn")],
        "rows": rows,
        # Timing is environment-dependent and excluded from the reproducibility check.
        "runtime": {"python": platform.python_version(), "platform": platform.system(),
                    "per_case_seconds_median": round(timings_sorted[len(timings_sorted) // 2], 4) if timings else None,
                    "per_case_seconds_max": round(timings_sorted[-1], 4) if timings else None},
    }


def _outcome(expected: int, predicted: int | None) -> str:
    if predicted is None:
        return "abstain"
    return {(1, 1): "tp", (0, 1): "fp", (1, 0): "fn", (0, 0): "tn"}[(expected, predicted)]


def deterministic_view(result: dict) -> dict:
    """The part of a result that must be identical across runs and machines.

    Excluded: timing, and the engine's free-text evidence. Some evidence strings list items
    from a Python set (e.g. schema types), so their order follows the per-process hash seed;
    verdicts, counts and metrics do not depend on it.
    """
    def strip(rows):
        return [{k: v for k, v in r.items() if k != "engine_evidence"} for r in rows]

    view = {k: v for k, v in result.items() if k != "runtime"}
    view["rows"], view["errors"] = strip(result["rows"]), strip(result["errors"])
    return view
