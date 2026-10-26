# Brand AI-Readiness Audit - Agent Skill Marketplace

This Agent Skill Marketplace is a modular package containing four specialized agent skills designed to audit unseen websites for AI discoverability, factual trust, answerability, and on-site user engagement. The v1.4 pipeline adds bounded multi-page crawling, redirect/indexability/canonical analysis, page-type-aware structured-data quality, visible↔JSON-LD fact parity, rendered mobile geometry, semantic CTA classification, AI answerability and quote-readiness, deep-link context retention, entity-confidence signals, potential orphan detection, prioritized actions, and adversarial regression coverage.

The package follows the `agentskills.io` skill structure and is designed around the Adobe Hackathon Round 3 rubric, with bounded, read-only checks for unseen websites. The readiness index is an internal diagnostic only and is not an Adobe score.

---

## Directory Layout

The original marketplace package is shown below. The final-year platform adds `backend/`, `frontend/`, `docs/`,
`evaluation/` and `.github/` alongside it; see the platform section at the end of this file.

```text
brand-ai-readiness-audit/
├── marketplace.json
├── README.md
├── RUBRIC_MAPPING.md
├── verify_marketplace.py
├── examples/
│   └── run_live_smoke_tests.ps1
├── tests/
│   ├── test_all_rubric_cases.py
│   ├── test_round3_polish.py
│   └── test_engine_fixes.py      # added by the platform extension (regression tests for D1–D13)
└── skills/
    ├── audit-orchestrator/
    │   ├── SKILL.md
    │   └── scripts/
    │       ├── compose_report.py
    │       └── run_audit.py
    ├── crawl-render-audit/
    │   ├── SKILL.md
    │   ├── references/
    │   │   └── discoverability_checklist.md
    │   └── scripts/
    │       └── check_technical.py
    ├── freshness-corroboration/
    │   ├── SKILL.md
    │   ├── references/
    │   │   └── freshness_corroboration_guide.md
    │   └── scripts/
    │       └── check_trust.py
    └── engagement-audit/
        ├── SKILL.md
        ├── references/
        │   └── engagement_principles.md
        └── scripts/
            └── check_engagement.py
```

---

## Skills Overview

### 1. Audit Orchestrator (`skills/audit-orchestrator`) [ENTRYPOINT]
* **Role**: Composes and coordinates the overall audit workflow.
* **Function**: 
  1. Runs the bounded technical crawl first and uses its representative URLs as the shared audit scope.
  2. Runs freshness/trust and engagement checks against those same representative deep links, preventing homepage-only blind spots.
  3. Runs `compose_report.py` to merge all findings into a standardized JSON report conforming to the required schema.
  4. **Rich Metadata & Scope**: Captures execution scope (`pages_checked`, `robots_checked`, `sitemap_checked`, `render_check`, `external_sources_checked`), finding categories, confidence ratings, affected page lists, and actionable `how_to_fix` instructions.
  5. **Proactive Improvements**: Adds category-level recommendations only when no critical/high defect is present. Proactive items are explicitly tagged and excluded from defect counts.
  6. Emits the final JSON report.

### 2. Crawl & Render Audit (`skills/crawl-render-audit`)
* **Role**: Technical crawlability, robots compliance, and AI discoverability auditor.
* **Function**:
  1. **Strict Robots.txt Compliance**: Uses `urllib.robotparser.RobotFileParser` to verify permission before fetching any URL. Disallowed targets abort fetching immediately to prevent policy violations. Scans for AI-specific crawler restrictions (`GPTBot`, `ClaudeBot`, `Google-Extended`, etc.).
  2. **XML Sitemap Parser & Index Follower**: Parses `sitemap.xml` and sitemap index files recursively via `xml.etree.ElementTree`, extracting URLs and `<lastmod>` timestamps.
  3. **Bounded Mini-Crawler**: Intelligently samples representative internal pages using URL, title/anchor semantics, schema hints, sitemap priority when available, same-domain rules, and a strict page budget.
  4. **Deep Schema.org Analysis**: Recursively extracts `@graph`, arrays, and nested schemas; validates property completeness (`Organization`, `Product`, `Article`, `FAQPage`, `BreadcrumbList`); identifies malformed vs. incomplete vs. valid schemas.
  5. **WCAG-Compliant Image Audit**: Distinguishes decorative images (`alt=""`, `role="presentation"`, spacer/icon files) from informative images, eliminating false positives on empty alt attributes.
  6. **Multi-Page Render Gap**: Renders the homepage plus up to three representative crawled pages and compares raw HTML facts with rendered DOM facts.
  7. **Indexability & Canonical Audit**: Checks meta/X-Robots noindex and canonical consistency, while recognizing that a missing canonical alone is not automatically a defect. Long/cross-host redirect chains are separately surfaced.
  8. **Visible ↔ Structured Fact Parity**: Detects conflicting prices, phones, emails, and other high-value machine facts between visible content and JSON-LD with formatting-aware normalization.
  9. **Mobile Geometry**: Uses a 390×844 viewport when Playwright is available to detect horizontal overflow and below-fold H1/CTA placement.
  10. **Mobile Viewport & Canvas Fallbacks**: Verifies responsive `<meta name="viewport">` tags and checks for machine-readable canvas fallbacks. Also records sampled internal-link graph/orphan signals.
* **Reference Guide**: [discoverability_checklist.md](skills/crawl-render-audit/references/discoverability_checklist.md)

### 3. Freshness & Corroboration (`skills/freshness-corroboration`)
* **Role**: Freshness, E-E-A-T credentials, and external web agreement auditor.
* **Function**:
  1. **Multi-Signal Freshness Model**: Synthesizes XML sitemap `<lastmod>`, Schema.org `dateModified`/`datePublished`, HTML `<meta>` timestamps, and in-page update notices alongside copyright footers. Avoids false positives on actively maintained sites that have not bumped copyright years.
  2. **Authoritative `sameAs` Entity Disambiguation**: Extracts verified external entity links from JSON-LD (Wikidata, Wikipedia, LinkedIn, Crunchbase) while strictly ignoring internal `@id` URIs. Flags entity ambiguity risks when naming collisions occur without disambiguation links.
  3. **Cross-Source Web Corroboration**: Queries the **Wikidata Entities Search API** and **Wikipedia Search API** to cross-verify headquarters locations, brand identity, and when available founding-year claims.
  4. **sameAs Sanity Validation**: Separates plausible knowledge/profile entity links from unsupported or suspicious sameAs targets before using them as disambiguation evidence. Accurately isolates regional codes (e.g. Canada as `CAN` vs California as `CA`) to prevent false contradictions.
  5. **Small Business Generalization Guard**: Recognizes that absence of Wikipedia/Wikidata entries is normal and expected for growing or niche brands, marking such cases as clean passes rather than defects.
  6. **E-E-A-T and Contact Transparency**: Audits author bylines, contact page links, corporate email, phone, and physical address disclosures.
* **Reference Guide**: [freshness_corroboration_guide.md](skills/freshness-corroboration/references/freshness_corroboration_guide.md)

### 4. Engagement Audit (`skills/engagement-audit`)
* **Role**: On-site user retention, readability, and navigation structure auditor.
* **Function**:
  1. **Heading Hierarchy & Value Hook**: Evaluates single `H1` placement and descriptive value propositions. Rendered geometry is used when Playwright is available.
  2. **Readability & Walls of Text**: Identifies unformatted paragraphs exceeding 100 words and detects excessive buzzwords or jargon.
  3. **Deep-Link Breadcrumb Auditing**: Verifies breadcrumb navigation structures (`nav[aria-label="breadcrumb"]`, `BreadcrumbList` schema) for visitors arriving via AI citations.
  4. **Intent-Classified CTAs**: Separates navigation links from conversion CTAs, then classifies purchase, demo, lead-generation, onboarding, pricing, download, learning, and navigation intents.
  5. **AI Answerability & Quote Readiness**: Scores identity, offer, audience, contact, and next-step clarity and separately estimates whether concise question→answer or definition content is easy to quote.
  6. **Deep-Link Context Retention**: Scores whether a visitor arriving directly on the page can retain brand context and continue through navigation, internal paths, breadcrumbs, and a meaningful CTA.
  7. **Dead-End Risk Detection**: Flags pages lacking primary header navigation, footers, or CTAs that strand users in dead ends.
  8. **Lightweight Performance & Clutter**: Calculates text-to-HTML ratios and monitors external script and stylesheet dependency bloat.
* **Reference Guide**: [engagement_principles.md](skills/engagement-audit/references/engagement_principles.md)

---

## How to Run an Audit

To perform a complete Brand AI-Readiness Audit against any live website:

```bash
# Recommended: deterministic end-to-end runner.
# It crawls first, shares the representative page set with trust + engagement,
# then emits one final report.
python skills/audit-orchestrator/scripts/run_audit.py https://example.com --max-pages 6 --output final_audit_report.json

# Optional: run the three skills individually when debugging.
python skills/crawl-render-audit/scripts/check_technical.py https://example.com --max-pages 6 --output tech.json
python skills/freshness-corroboration/scripts/check_trust.py https://example.com --technical tech.json --max-pages 6 --output trust.json
python skills/engagement-audit/scripts/check_engagement.py https://example.com --technical tech.json --max-pages 6 --output engage.json
python skills/audit-orchestrator/scripts/compose_report.py \
  --site "example.com" --technical tech.json --trust trust.json --engagement engage.json --output report.json
```

---

## Real-Website Smoke Testing

The marketplace is intended to run against unseen live websites, not only the offline fixtures used by the unit tests. Before submission, run the entrypoint against 2–3 real public URLs and inspect the generated JSON reports. A ready-to-use PowerShell smoke-test script is provided at `examples/run_live_smoke_tests.ps1`.

```powershell
# From the marketplace root
powershell -ExecutionPolicy Bypass -File examples/run_live_smoke_tests.ps1
```

The script clears stale JSON first, then writes fresh reports into `examples/reports/`. It also enforces a 60-second per-stage timeout and a 240-second whole-pipeline deadline. Network failures are recorded as `unavailable` rather than being misreported as anti-bot blocks. No pre-generated reports are shipped, because stale/canned site outputs are poor evidence of generalization.

## Runtime Bound

The entrypoint is deliberately bounded for the Round 3 `<5 minute` runtime guardrail.
`run_audit.py` enforces a hard 60-second timeout per audit stage and a hard 240-second
wall-clock deadline for the complete pipeline. The final report records
`runtime_seconds`, `runtime_limit_seconds`, `stage_timeout_seconds`, and any timed-out
categories under `execution`. A timeout or failed stage is marked as partial rather
than being presented as a clean audit.

The runtime cap is a safety bound, not a claim that every network target will finish
successfully. Actual runtime depends on network/server behavior; the included live
smoke-test script measures it on the machine where the submission is run.

## Verification and Automated Testing

The marketplace contains a dual-layer verification system directly runnable from the root:

```bash
# Runs the offline end-to-end audit server test AND the rubric/hardening suite plus the Round 3 polish/generalization suite
python verify_marketplace.py
```

### What `verify_marketplace.py` Tests:
1. **End-to-End Pipeline Execution**: Spins up an offline mock server serving test fixtures, executes all three sub-audits, runs the composer, and validates schema compliance.
2. **Signal Detection**: Verifies detection of AI crawler blocks, missing viewport tags, FAQ parity gaps, stale dates, E-E-A-T omissions, location contradictions, and navigation dead ends.
3. **Proactive Suggestions**: Confirms that clean runs generate appropriate proactive improvement suggestions.
4. **Core challenge-check suite (`tests/test_all_rubric_cases.py`)**: Executes 48 focused unit/regression checks across technical discoverability, trust/freshness, engagement, report composition, and hardening cases. The 34 historical core checks are not described as 34 Adobe rubric criteria; Adobe's supplied brief defines six evaluation criteria. (robots specificity, sitemap index recursion, malformed recoverable XML, WCAG decorative alt, multi-signal freshness weighting, Canada vs California disambiguation, page-type aware E-E-A-T, intent CTAs, breadcrumbs, and schema conformity).
5. **Round 3 Polish & Generalization Suite (`tests/test_round3_polish.py`)**: Executes 20 additional tests covering quote-readiness, deep-link scoring, semantic page selection, multi-page engagement isolation, schema/page mismatch, redirect-chain handling, formatting-aware fact parity, entity-confidence scoring, separate quote-readiness reporting, report priority actions, manifest integrity, and the internal diagnostic-score wording.

---

## Rubric Traceability

See `RUBRIC_MAPPING.md` for an auditable requirement-to-implementation-and-test map derived from the supplied Round 3 brief. It maps the brief's six evaluation criteria to concrete skills, scripts, and regression tests rather than relying on an unsupported “34/34 rubric criteria” claim.

## Portability & Engineering Hygiene

* **Core dependencies**: All core auditing scripts rely strictly on the Python 3 standard library. Playwright is an optional rendering enhancement. Install it only when you want verified rendered-vs-raw and mobile geometry checks: `pip install playwright` followed by `python -m playwright install chromium`. The marketplace does not bundle a virtual environment or `site-packages`.
* **Safety & Non-Invasiveness**: Read-only auditing. Strictly respects `robots.txt` disallow rules, enforces bounded crawl budgets, and applies generous 10-second network timeouts.
* **Package Hygiene**: Strictly conforms to the `<50MB` package limit, with clean Unix-style forward slashes and no `__pycache__` or operating system artifacts.

---

# Brand AI-Readiness Intelligence Platform (final-year project extension)

The skill marketplace above is unchanged in structure and remains the audit engine. A web platform now wraps it:
a FastAPI backend runs the engine as an isolated, bounded subprocess, stores results in SQLite, ranks findings with a
transparent deterministic model (`priority-v1`), computes an itemised readiness index (`readiness-v2`, every penalty
traced to a finding and its evidence), compares runs, and exports JSON/PDF reports; a React + TypeScript UI drives the
flow. An offline labelled dataset (`evaluation/`) measures per-detector precision, recall and F1.
The readiness indices are internal diagnostics, not Adobe scores.

Status, defects found in the original engine, and what is still planned: `docs/PROJECT_AUDIT.md`,
`docs/IMPLEMENTATION_ROADMAP.md`, `docs/CHANGE_LOG.md`. Security model: `docs/SECURITY.md`. API: `docs/API_REFERENCE.md`.
Tests, evaluation method, results and scoring models: `docs/TESTING_AND_EVALUATION.md`.

## Setup (Windows PowerShell; use `source .venv/bin/activate` and `/` paths on macOS/Linux)

Requirements: Python 3.12, Node 20+ (tested with 24.21). No API keys or paid services are needed.

```powershell
python -m venv .venv
.venv\Scripts\python -m pip install -r backend\requirements-dev.txt
cd frontend; npm ci; npm run build; cd ..
```

**After cloning, the frontend build is required.** `frontend/dist/` is generated output and is not stored in Git (nor are
`.venv/`, `frontend/node_modules/`, or the platform database under `backend/var/`). `npm ci` installs the exact versions in
`frontend/package-lock.json`, and `npm run build` type-checks the UI and writes `frontend/dist/`, which the API serves in
single-process mode. Without it the API still works, but `http://127.0.0.1:8000/` has no UI. Re-run `npm run build`
after changing anything under `frontend/src/`.

Ports: the API listens on 127.0.0.1:8000, and the Vite development server (optional, hot reload) on localhost:5173. No
other development port or editor setting is needed.

## Run

Single process (the API also serves the built UI):

```powershell
cd backend
..\.venv\Scripts\python -m brand_platform            # safe launcher: binds 127.0.0.1:8000, ignores proxy headers
# open http://127.0.0.1:8000   (--port N to change the port; non-loopback --host values are refused)
```

Running `uvicorn brand_platform.main:app` directly still works, and the in-app guard still refuses non-local clients,
but the launcher is preferred: plain uvicorn trusts `X-Forwarded-For` from 127.0.0.1 by default.

Development with hot reload: run the command above, then `cd frontend; npm run dev` and open http://localhost:5173
(Vite proxies `/api` to port 8000).

Configuration is through environment variables (all optional): `BRAND_PLATFORM_DATA_DIR` (default `backend/var`),
`BRAND_PLATFORM_MAX_CONCURRENT_JOBS` (2), `BRAND_PLATFORM_MAX_QUEUED_JOBS` (10), `BRAND_PLATFORM_DEFAULT_MAX_PAGES` (4),
`BRAND_PLATFORM_RUNTIME_LIMIT` (240 s), `BRAND_PLATFORM_STAGE_TIMEOUT` (60 s), `BRAND_PLATFORM_ALLOWED_PORTS` (80,443),
`BRAND_PLATFORM_CREATE_RATE_LIMIT` (12 per 10 min), `BRAND_PLATFORM_CORS_ORIGINS` (empty; only for a frontend calling
the API directly from another loopback origin, since the Vite proxy needs none),
`BRAND_PLATFORM_OFFLINE_CORROBORATION=1` (operator kill switch for Wikipedia/Wikidata lookups; overrides any opt-in),
`BRAND_PLATFORM_RETENTION_DAYS` (unset = keep audits indefinitely; see below).

Wikipedia/Wikidata corroboration is **off by default** in the platform. Each audit opts in with a checkbox on the New
Audit page, which explains that the detected brand name is sent to those public APIs. The choice is recorded per
audit and shown in history and in the JSON/PDF exports. The engine command line still corroborates by default; set
`BRAND_AUDIT_EXTERNAL_CORROBORATION=off` to opt out there.

### Audit retention (off by default)

Audits are kept **indefinitely** unless you set `BRAND_PLATFORM_RETENTION_DAYS` to a whole number of days from 1 to
3650. Any other value (`0`, `30d`, `-1`, `1.5`) stops the server with a clear error rather than guessing. With a period
set, a **finished** audit (completed, partial, failed, timed out, cancelled or interrupted) is deleted together with its
reports and findings once its `finished_at` is more than N days old; `created_at` is used only for a finished audit with
no `finished_at`. Queued and running audits are never deleted. An audit interrupted by a server restart counts as
finished at that restart. The server purges at startup and then every 24 hours, in a background thread that never
blocks startup and stops at shutdown. There is no HTTP endpoint that deletes audits.

Manual purge (run from `backend/`, against the database in `BRAND_PLATFORM_DATA_DIR`). **Preview is the default and
deletes nothing:**

```powershell
..\.venv\Scripts\python -m brand_platform.purge                          # preview using BRAND_PLATFORM_RETENTION_DAYS
..\.venv\Scripts\python -m brand_platform.purge --older-than-days 90     # preview with an explicit period
..\.venv\Scripts\python -m brand_platform.purge --older-than-days 90 --apply   # delete what the preview lists
```

Each applied purge is logged in the `retention_runs` table (date, trigger, period, cutoff and counts only; never the
deleted content). Deleted rows are overwritten in the database file (SQLite `secure_delete`) and the write-ahead log is
truncated. That is **not** a guarantee of forensic erasure: backups, copies of the file, previously downloaded JSON/PDF
exports, filesystem snapshots, SSD wear-levelling and OS caches are outside its reach (`docs/SECURITY.md`).

There is **no authentication**, so the platform is **local-only by design**. It refuses non-loopback clients, Host
headers other than `localhost`/`127.0.0.1`/`[::1]`, cross-site state-changing requests, browser requests from other
sites (`Sec-Fetch-Site`; links to UI pages still open), non-JSON bodies, and bodies over
64 KiB. `BRAND_PLATFORM_CORS_ORIGINS` may list loopback origins only. Public, LAN or reverse-proxied deployment is **not
supported** until proper authentication and deployment security are implemented, and no setting re-enables it
(`docs/SECURITY.md`).

## Demo walkthrough
1. Open **New audit**, enter a site you are permitted to test, and choose a page budget (1–6).
2. Watch the four stages (technical → trust → engagement → compose). You can cancel.
3. Review the readiness overview, severity counts, any partial-execution notice, and the ranked findings. Open a finding
   to see its evidence, affected pages, fix, and the factor breakdown of its priority score.
4. Export JSON or PDF. After fixing something, audit again and use **Compare with previous run**, or choose two runs in **History**.

## Tests

```powershell
python tests\test_all_rubric_cases.py      # 48 original checks
python tests\test_round3_polish.py         # 20 original checks
python tests\test_engine_fixes.py          # 24 regression tests for defects fixed in this extension
python verify_marketplace.py               # original end-to-end verifier (runs the three suites above)
python evaluation\test_evaluation.py       # 10 tests for the evaluation harness
python evaluation\run_evaluation.py --check  # re-runs the labelled detector evaluation; fails if metrics drift
cd backend; ..\.venv\Scripts\python -m pytest; ..\.venv\Scripts\python -m ruff check . ..\evaluation; cd ..
cd frontend; npm test; npm run typecheck; cd ..
```

The backend suite includes real end-to-end audits of a local fixture website (submit → run engine → persist → findings
→ readiness-v2 → JSON/PDF export → re-audit → compare), plus robots-disallow, cancellation, and hard-timeout cases. It
needs no internet. `.github/workflows/ci.yml` runs all of these; it has not yet run on GitHub because the folder is not
a Git repository.

## Detector evaluation

`python evaluation\run_evaluation.py` runs the engine on 59 labelled pages (103 labels, 13 detectors) and writes
`evaluation\results\v1\results.{json,md}` (`--name <stem>` writes a separately named file and never overwrites an existing
one). Before the D14 fix: micro F1 0.90 (typical 0.97, edge 0.62), seven errors. After fixing D14 (`X-Robots-Tag`
noindex was never detected on live sites): micro F1 0.92 (edge 0.71), six errors, with exactly one label changed. See
`docs/TESTING_AND_EVALUATION.md` §4. The dataset is small, synthetic and single-annotator, so these figures show agreement
with the documented criteria, not real-world accuracy.

## Troubleshooting
- `verify_marketplace.py` failed with `UnicodeDecodeError` on Windows before this extension; that is fixed. If you see it,
  check that `tests/test_round3_polish.py` is the updated version.
- An audit that ends **Partial** means some evidence could not be collected (see the notice on the audit page); those
  checks are not counted as passes.
- `dns_resolution_failed` or a failed fetch for every page usually means the machine has no outbound internet access.
- Packaging the original Adobe submission: zip only `marketplace.json`, `README.md`, `RUBRIC_MAPPING.md`,
  `verify_marketplace.py`, `skills/`, `tests/`, `examples/`, never `.venv/`, `frontend/node_modules/`, `backend/`,
  `frontend/`, `evaluation/` or `.github/`. These files now include the session-1 engine fixes (`docs/CHANGE_LOG.md`);
  the byte-for-byte original is the ZIP that was submitted.
