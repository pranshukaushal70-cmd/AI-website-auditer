# Testing and Evaluation

This document covers three things: how the software is tested, how the detectors are evaluated against labelled data,
and how the two scoring models (`priority-v1` and `readiness-v2`) are defined. Every number below was produced by a
command listed in §7 and was run on 2026-10-24 (Windows 10, Python 3.12.3, Node 24.21.0). Where a result lives in a
generated file, that file is the authority, and this document points to it.

## 1. Test suites

| Suite | What it covers | Command | Result (2026-10-25, after the D14 fix) |
|---|---|---|---|
| `tests/test_all_rubric_cases.py` | Original 48 engine checks | `python tests/test_all_rubric_cases.py` | 48 passed |
| `tests/test_round3_polish.py` | Original 20 Round-3 checks | `python tests/test_round3_polish.py` | 20 passed |
| `tests/test_engine_fixes.py` | Regression tests for D1–D8, D11–D15 and security phases 2–3 (the D15 and robots.txt tests use real sockets and the real fetchers) | `python tests/test_engine_fixes.py` | 65 passed (after security phase 4) |
| `verify_marketplace.py` | Original offline end-to-end verifier (runs the three suites above) | `python verify_marketplace.py` | exit 0 |
| `evaluation/test_evaluation.py` | Metric arithmetic, dataset integrity, fixture fidelity, reproducibility | `python evaluation/test_evaluation.py` | 10 passed (after the approved refresh of `results.json`, 2026-10-25) |
| `evaluation/run_evaluation.py --check` | Re-runs the detector evaluation; fails if results differ from the committed ones | see §7 | reproducible against the refreshed `results.json` (`PYTHONHASHSEED` 0, 1, 2, 3, 7, 42) |
| `tests/repro_d15_redirect_chain.py` | Standalone D15 reproduction (not part of any suite) | `python tests/repro_d15_redirect_chain.py` | exit 0 after the fix (exit 1 before) |
| `backend/tests` | API, URL safety, DB, runner, PDF, prioritisation, comparison, readiness-v2; real offline end-to-end audits of a local fixture site | `cd backend && python -m pytest` | 166 passed (after security phase 4) |
| `frontend/src/app.test.tsx` | URL pre-check, formatting, findings filter/explorer, progress stepper, API client errors | `cd frontend && npm test` | 24 passed (after security phase 4) |
| Static checks | `ruff check` (backend, evaluation); `tsc --noEmit` (frontend) | see §7 | clean |

`.github/workflows/ci.yml` runs all of the above on every push and pull request (engine and evaluation on Ubuntu and
Windows). **The workflow has not yet run on GitHub**: the directory is not a Git repository. It was checked only for
valid YAML locally.

## 2. Detector evaluation: labelling criteria

Dataset `evaluation/fixtures/v1/` has 59 cases and 103 labels for 13 detectors. Each case is a single HTML page served to
the engine with an optional robots.txt, response headers, or sitemap `lastmod` year. A label answers one question: *does
this page have the defect, according to the criterion below?* The criteria restate the detector's documented purpose
(README, `SKILL.md`, reference guides) in testable form. The reference year is pinned to 2026.

| Detector id | Engine check | Defect present (label = true) when… |
|---|---|---|
| `technical.ai_crawler_block` | `robots_txt.blocked_bots` | robots.txt disallows the site root for at least one named AI crawler. Partial-path disallows and commented-out rules do not count. |
| `technical.viewport` | `viewport_check` | The page has no **responsive** viewport meta tag (missing, or a fixed width). |
| `technical.structured_data` | `structured_data` | JSON-LD is absent or invalid, or the type expected for the page (Organization/WebSite on the homepage, Product, Article) is missing or lacks required properties. |
| `technical.faq_schema` | `faq_schema_check` | The page presents an FAQ (an FAQ section, accordions, or two or more question/answer pairs) without FAQPage JSON-LD. |
| `technical.noindex` | `indexability_check` | A noindex directive is present in meta robots, meta googlebot, or the `X-Robots-Tag` header. |
| `technical.fact_parity` | `fact_parity` | A price, phone number or email in JSON-LD contradicts the visible one after formatting is normalised. |
| `technical.image_alt` | `locked_content` | Two or more content images lack alt text, or a canvas carries information with no text alternative. Decorative images with empty alt are correct. |
| `trust.stale_content` | `multi_signal_freshness` | A strong date signal (schema dates, meta modified date, sitemap lastmod, HTTP Last-Modified) predates 2025, another signal agrees, and nothing shows 2025–2026 activity. A copyright year alone never makes a page stale. |
| `trust.eeat` | `eeat_check` | Article pages: no author byline. Pricing/product pages: no contact link and no email/phone. Legal pages: never. Other pages: no contact/about link, no author, **and** no direct channel (email, phone, address). |
| `engagement.h1` | `h1_audit` | Not exactly one H1 element, or the H1 has fewer than three words. |
| `engagement.readability` | `readability` | A single text block exceeds ~100 words, or the copy is dominated by buzzwords. |
| `engagement.navigation_cta` | `navigation_cta` | No site navigation, or the page ends without a call to action or next step beyond navigation links. |
| `engagement.clutter` | `clutter` | Visible text is under ~5% of the HTML, or the page carries script bloat (e.g. 30+ external scripts). |

Cases are tagged **typical** (a clear instance of the criterion), **edge** (a realistic variation where a heuristic and a
human reader might disagree), or **adversarial** (content written to mislead an automated auditor). Every label has a
one-line rationale in `cases.json`.

## 3. Method

`evaluation/harness.py` calls the unmodified engine through its existing injection points. Nothing touches the network:
`analyze_technical(url, max_crawl_pages=1, fetch_fn=…)`, `analyze_trust(html, url, current_year=2026,
fetch_sitemap_fn=…, external_apis_fn=…)` and `analyze_engagement(len(html), html)`. Browser rendering is disabled.

- **Prediction mapping**: status `fail` or `warning` → 1 (defect), `pass` → 0, anything else (`unavailable`,
  `not_checked`) → abstention. Abstentions are reported, never scored. There were 0 abstentions in v1.
- **Fixture fidelity**: the fixture fetcher returns headers as an `http.client.HTTPMessage`, the same type the real
  `fetch_url` returns. A plain dict, as unit-test mocks use, would exercise a code path that never runs in production
  (this is how D14 was found; see §5).
- **Metrics**: per detector TP/FP/FN/TN, precision TP/(TP+FP), recall TP/(TP+FN), F1, false-positive rate FP/(FP+TN).
  Undefined ratios are reported as n/a, never as 0 or 1. Also micro totals over all labels, macro F1 over detectors, and a
  breakdown by case kind.
- **Reproducibility**: `results.json` records the dataset version and a SHA-256 over the manifest and pages. `--check`
  re-runs the evaluation and compares everything except timing and the engine's free-text evidence. Some evidence strings
  list items from a Python `set`, so their order follows the hash seed. Verdicts do not depend on it (observation O11).

## 4. Results (dataset v1, sha256 `01d1d7e7…`)

This section is the **pre-fix baseline** (engine as of 2026-10-24), preserved in `baseline-pre-d14-fix.{json,md}`. The
results after the D14 fix are in §4.1. Since 2026-10-25 the canonical `results.{json,md}`, which `--check` and CI
compare against, hold the post-fix results; their content is identical to `post-d14-fix.{json,md}`. Summary:

| Scope | Labels | TP | FP | FN | TN | Precision | Recall | F1 |
|---|---|---|---|---|---|---|---|---|
| All labels (micro) | 103 | 33 | 2 | 5 | 63 | 0.94 | 0.87 | 0.90 |
| Typical cases | 80 | 28 | 0 | 2 | 50 | 1.00 | 0.93 | 0.97 |
| Edge cases | 21 | 4 | 2 | 3 | 12 | 0.67 | 0.57 | 0.62 |
| Adversarial cases | 2 | 1 | 0 | 0 | 1 | 1.00 | 1.00 | 1.00 |

Macro-averaged F1 over the 13 detectors is 0.89. Seven detectors scored F1 1.00 on this dataset. The other six are
`technical.viewport` 0.67, `technical.noindex` 0.86, `trust.eeat` 0.75 (the only detector with false positives),
`engagement.h1` 0.86, `engagement.readability` 0.80 and `engagement.navigation_cta` 0.67. Five of the seven errors are on
edge cases; `two-h1` and `nav-no-cta` are typical cases.

### Error analysis (all 7 errors)

| Case | Detector | Error | Root cause in the engine |
|---|---|---|---|
| `noindex-header` | noindex | FN | **D14**: the `X-Robots-Tag` check runs only `if isinstance(response_headers, dict)`; the real fetcher returns an `HTTPMessage`, so header-level noindex is never detected on live sites. |
| `viewport-fixed-width` | viewport | FN | Only the presence of a viewport tag is checked, not whether it is responsive (`width=1024` passes). |
| `two-h1` | h1 | FN | An H1 that contains only an image (logo) is not counted, so two H1 elements are reported as one. |
| `wall-div` | readability | FN | Only `<p>` elements are measured; a 180-word block in a `<div>` is invisible to the check. |
| `nav-no-cta` | navigation_cta | FN | A navigation link is classified as a "navigation" CTA, which satisfies the CTA requirement, so a dead-end page passes. |
| `blog-by-name` | eeat | FP | A byline counts only as "written by", "author:", "by: " (with a colon) or an author link; "By Priya Shah" is missed. |
| `home-email-only` | eeat | FP | For general pages the rule requires a contact link or author. Direct channels (email/phone/address) are recorded in the evidence but do not satisfy it. This is a disagreement between the engine's rule and the criterion in §2, not a crash. |

D14 was fixed on 2026-10-25 (§4.1). The other six are unchanged. Each is a candidate engine change with a ready-made
regression case.

### Ablation: what the harness's header fidelity changes

`python evaluation/run_evaluation.py --ablation-mock-headers` re-runs the whole dataset with response headers as a plain
dict (the shape unit-test mocks use) instead of the production `HTTPMessage`. Measured on 2026-10-24, exactly one label
changes: `noindex-header` goes from FN to TP. `technical.noindex` recall rises from 0.75 to 1.00, and micro F1 from 0.90
to 0.92. Mock-shaped fixtures would have hidden D14 and overstated production accuracy. After the D14 fix the same
command reports 0.92 for both header shapes, with no label changing.

### 4.1 D14 fix: measured before and after (2026-10-25)

Same frozen dataset (sha256 `01d1d7e7…`, 103 labels) and the same harness. The only code change between the runs is the
D14 fix in `check_technical.py`. Files: `evaluation/results/v1/baseline-pre-d14-fix.{json,md}` (before) and
`post-d14-fix.{json,md}` (after). Neither overwrote the other or `results.{json,md}`.

| Scope | Before: TP / FP / FN / TN | After: TP / FP / FN / TN | Precision | Recall | F1 |
|---|---|---|---|---|---|
| `technical.noindex` | 3 / 0 / 1 / 3 | 4 / 0 / 0 / 3 | 1.00 → 1.00 | 0.75 → 1.00 | 0.86 → 1.00 |
| All labels (micro) | 33 / 2 / 5 / 63 | 34 / 2 / 4 / 63 | 0.94 → 0.94 | 0.87 → 0.89 | 0.90 → 0.92 |
| Edge cases | 4 / 2 / 3 / 12 | 5 / 2 / 2 / 12 | 0.67 → 0.71 | 0.57 → 0.71 | 0.62 → 0.71 |

Macro F1 0.89 → 0.90; errors 7 → 6. **Exactly one label changed** (`noindex-header`, FN → TP). The other 12 detectors
are identical in every count. The three noindex negatives stayed negative, so no false positive was introduced. Typical
(0.97) and adversarial (1.00) F1 are unchanged. These are measured values. The prediction made before the fix (noindex
recall 1.00, micro F1 ≈ 0.92) matched them.

### 4.2 D15 fix: the evaluation cannot measure it (2026-10-25)

`baseline-pre-d15-fix.{json,md}` and `post-d15-fix.{json,md}` are **identical** in every verdict and metric (micro F1 0.92,
6 errors). This was expected: dataset v1 has no redirect detector (§5), so D15's effect is shown only by the regression
tests (`TestRedirectChainHeaders`, `TestRedirectChainLiveFetch`), not by these metrics. The canonical `results.json`
was therefore left unchanged. A redirect detector in the dataset would need multi-response fixtures and a new dataset
version (v2).

## 5. Threats to validity and limitations

- **Annotator bias**: one annotator (the AI assistant that wrote the harness) labelled every case, and had read several
  detector thresholds (e.g. ">100 words", ">40% and ≥2 images", the schema required-property table) before labelling.
  Typical cases near documented thresholds therefore tend to agree with the engine by construction. The typical-case
  scores show that the implementation matches its documented criterion, **not** that it is accurate on real websites.
  Independent double annotation with an agreement measure (Cohen's κ) is needed before these numbers support stronger
  claims.
- **Small samples**: each detector has 2–4 positive cases. One extra error moves a detector's F1 substantially. Read
  per-detector metrics as counts, not as stable rates.
- **Synthetic pages**: the fixtures are small, clean, single-page documents. Real sites add scripts, templates, consent
  banners, localisation and malformed markup. Multi-page behaviour (crawl selection, aggregation across pages,
  affected-page attribution) is covered by the backend end-to-end tests, not by this dataset.
- **Out of scope**: rendering (disabled), external corroboration (stubbed to "no records"), redirect chains, canonical
  checks, sitemap parsing, answerability and quote-readiness scores, and orphan detection.
- **Labels were frozen** before the first harness run (the dataset digest is unchanged since). No label or fixture was
  edited after results were seen.

## 6. Scoring models

### priority-v1 (`backend/brand_platform/prioritization.py`)
`priority = 100 × severity × confidence × reach × evidence × effort`, with every factor in (0, 1]:
severity critical 1.0 / high 0.7 / medium 0.4; confidence from the rule; reach `0.5 + 0.5 × affected/pages_checked`;
evidence 1.0 if it cites a number or URL, otherwise 0.85; effort low 1.0 / medium 0.85 / high 0.7 from a per-rule expert
table. The factor values are design choices. They were not learned from data and have not been validated against
remediation outcomes. Each finding returns its factors with explanations.

### readiness-v2 (`backend/brand_platform/readiness.py`)
- Per dimension (technical, trust, engagement): `score = max(0, 100 − Σ penalty)`, where
  `penalty = base(severity) × confidence × reach`, base critical 30 / high 18 / medium 7, and reach as above.
- Overall: the equal-weight mean of **assessed** dimensions. A dimension listed in `execution.missing_categories` or
  `unavailable_categories` is marked not assessed and excluded. If none is assessed, the score is null.
- Bands: ≥90 excellent, ≥75 strong, ≥55 needs attention, otherwise at risk.
- Every penalty is returned as a record with finding code, fingerprint, title, base, confidence, reach input, penalty,
  affected pages and an evidence excerpt. Proactive suggestions carry no penalty.
- It differs from the engine's own index (here **v1**, `compose_report.py`) in exactly three ways: itemised penalties, the
  reach factor, and exclusion of unassessed dimensions (v1 scores them 100, which inflates the index when evidence is
  missing). v1 is reported alongside v2 and never overwritten.
- Exposed at `GET /api/audits/{id}/readiness`, in the JSON export (`readiness_v2`) and in the PDF. Tests are in
  `backend/tests/test_readiness.py`, and the end-to-end test asserts that every defect, and only defects, carry a
  penalty. Not yet shown in the web UI.
- Like v1, it is an internal heuristic. It is not an Adobe score and not validated against search or AI-assistant
  outcomes.

## 7. Reproducing everything

From the package root, with the existing environment (no network needed except for installing dependencies):

```powershell
python tests\test_all_rubric_cases.py
python tests\test_round3_polish.py
python tests\test_engine_fixes.py
python verify_marketplace.py                      # writes and deletes temporary JSON in the current directory
python evaluation\test_evaluation.py
python evaluation\run_evaluation.py --check       # reproduce the committed metrics
python evaluation\run_evaluation.py               # regenerate evaluation\results\v1\results.{json,md}
cd backend;  ..\.venv\Scripts\python -m pytest -p no:cacheprovider;  ..\.venv\Scripts\python -m ruff check . ..\evaluation;  cd ..
cd frontend; npm test; npm run typecheck; cd ..
```

Set `PYTHONDONTWRITEBYTECODE=1` to avoid leaving `__pycache__` folders in the package (the verifier deletes them anyway).
To add a case: add a page under `evaluation/fixtures/v1/pages/` and an entry in `cases.json` with a rationale for every
label, then regenerate. Changing labels or pages changes the dataset digest. A changed dataset should be given a new
version (`v2`) rather than edited in place once results are reported.
