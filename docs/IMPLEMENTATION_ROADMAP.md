# Implementation Roadmap — Brand AI-Readiness Intelligence Platform

Status legend: ✅ done and tested · 🟡 in progress / partial · ⬜ planned (not started).
This file is updated at the end of every work session. "Done" means implemented **and** covered by a passing test.

## Target architecture (chosen for simplicity, not for appearance)

```
 React + TypeScript + Vite SPA  ──HTTP/JSON──▶  FastAPI (Python 3.12)
        (frontend/)                                (backend/brand_platform/)
                                                    │  URL safety pre-check (DNS, public IPs, ports)
                                                    │  Bounded job runner (thread pool, N concurrent, queue cap)
                                                    │      └─ subprocess: skills/audit-orchestrator/scripts/run_audit.py
                                                    │             (unchanged CLI contract; process isolation)
                                                    │  Deterministic prioritisation (explainable factors)
                                                    │  SQLite (stdlib sqlite3, versioned migrations)
                                                    └─ JSON + PDF (reportlab) export
```

Decisions and why:
- **Subprocess, not import**: the engine monkey-patches `socket.getaddrinfo` process-wide (audit D10). Running it in a
  child process keeps that safe and gives real hard-kill cancellation and timeouts.
- **SQLite via stdlib `sqlite3`**: one file, no server, no ORM dependency. Schema is plain SQL with a
  `schema_migrations` table, so a PostgreSQL port is a mechanical translation if ever needed.
- **No Redis/Celery**: audits are ≤ 6 pages and ≤ 240 s; a bounded in-process thread pool with a queue cap is
  sufficient for a single-node demo. Jobs that were running when the server stopped are marked `interrupted` at startup.
- **Rendering disabled in server mode**: Playwright bypasses the SSRF guard (audit D6), so the API runs the engine
  with `BRAND_AUDIT_DISABLE_RENDER=1`. Rendering stays available to the CLI.

## Milestones

### M0 — Baseline & audit ✅
- Snapshot, test baseline, defect list → `docs/PROJECT_AUDIT.md`.
- Session 2: re-verified (`PROJECT_AUDIT.md` §8). The session-1 snapshot is no longer reachable (O1), so the owner must
  keep the originally submitted ZIP separately; it was deliberately not restored over the working tree.

### M1 — Engine correctness fixes (targeted patches, each with a regression test) ✅
Acceptance: original suites pass (48 + 20 tests), verifier exits 0 on Windows **without** `PYTHONUTF8`, and new
regression tests in `tests/test_engine_fixes.py` pass.
- D1 proactive items excluded from the readiness index.
- D2 per-check `affected_pages` propagated for trust/engagement.
- D3 unavailable checks surfaced (`execution.unavailable_checks`) and no proactive "clean" suggestion for a category
  whose checks were all unavailable; multi-page trust keeps `execution.errors`.
- D4 `sitemap_checked` reflects whether a sitemap was found.
- D5 `js_ev` NameError.
- D6 `BRAND_AUDIT_DISABLE_RENDER` switch.
- D7 public-IP rule uses `is_global` plus 6to4/Teredo/NAT64 embedded-address checks.
- D8 error label. Test-runner placement and encoding fixes. Smoke-script `$host` fix.
- D12 duplicate external queries; D13 trust stage ignored robots.txt disallow (found by the M2 end-to-end test).

### M2 — Vertical slice: submit → audit → persist → view → export ✅ (session 1)
Acceptance criteria:
1. `POST /api/audits` rejects unsafe URLs (scheme, credentials, private/reserved IPs, non-standard ports) with a
   structured 422 error; accepts public URLs and returns a job id.
2. The job runs the real engine in a subprocess, records stage progress, enforces a hard timeout, supports cancel.
3. Results (metadata, findings, evidence, prioritisation, report version) persist in SQLite and survive restart.
4. `GET /api/audits/{id}/report.json` and `/report.pdf` export the stored report.
5. History list, filtering, and run-to-run comparison (`resolved / new / persistent / inconclusive`).
6. The React UI performs the flow end-to-end against the real API; no hard-coded results.
7. Backend pytest suite + frontend unit tests pass; original regression suites still pass.

### M3a — Explainable readiness index 🟡 (backend done and tested in session 2; UI not started)
- ✅ `readiness-v2` (`backend/brand_platform/readiness.py`): itemised penalties with evidence, reach factor, unassessed
  dimensions excluded rather than scored 100. Engine v1 index unchanged and reported alongside.
- ✅ `GET /api/audits/{id}/readiness`, `readiness_v2` in the JSON export, itemised table in the PDF;
  `backend/tests/test_readiness.py` plus end-to-end assertions.
- ⬜ Show the penalty breakdown in the React audit page (it currently shows the engine v1 index).

### M3b — Optional AI ⬜
- Optional LLM provider abstraction (env-configured, off by default) for remediation *explanations* only; strict
  input limits, timeouts, output schema validation, deterministic fallback text, page text passed as quoted untrusted
  data, never tools. Stored separately from rule outputs and labelled as generated.
- Unit tests with a fake provider for timeout, malformed output, and injection-laden page text.

### M4 — Research evaluation framework 🟡 (dataset v1 and harness done and tested in session 2)
- ✅ `evaluation/fixtures/v1/`: 59 page-level cases, 103 labels, 13 detectors, typical / edge / adversarial, a rationale
  per label, and a SHA-256 dataset digest.
- ✅ Offline harness calling the unmodified engine with production-shaped headers; per-detector, micro, macro and
  per-kind precision/recall/F1/FPR; `--check` reproducibility guard (verified across hash seeds); one ablation
  (`--ablation-mock-headers`). Results: `evaluation/results/v1/results.md`, method: `docs/TESTING_AND_EVALUATION.md`.
- ⬜ Independent second annotator plus Cohen's κ; more cases per detector (currently 2–4 positives each).
- ⬜ Multi-page cases (crawl selection, affected-page attribution) and the detectors not yet covered (canonical,
  redirects, sitemap, answerability, quote-readiness, orphans).
- ⬜ Content ablations (multi-signal freshness vs copyright-only; formatting-aware vs naive fact parity).

### M5 — Hardening, CI, docs 🟡
- 🟡 `.github/workflows/ci.yml` written: engine suites, verifier, evaluation check (Ubuntu and Windows), backend
  pytest + ruff, frontend typecheck + tests + build. YAML validated locally; **not yet run on GitHub** (no repository).
- ✅ Docs: `SECURITY.md`, `API_REFERENCE.md`, `CHANGE_LOG.md`, `TESTING_AND_EVALUATION.md`.
- ⬜ Remaining docs: `SYSTEM_ARCHITECTURE.md`, `LIMITATIONS.md`, `FINAL_YEAR_REPORT_OUTLINE.md`, `VIVA_PREPARATION.md`.
- ⬜ Clean-install test from the documented steps; low-cost deployment notes (single VM / container, no paid services).

### M6 — Security hardening 🟡 (approved 5-phase plan, 2026-10-25)
- ✅ Phase 1: local-only API exposure (`exposure.py`, launcher, 51 tests).
- ✅ Phase 2: `BRAND_PLATFORM_LOCAL_FIXTURE_PORT` removed (code-level setting only); the engine's
  `BRAND_AUDIT_LOCAL_FIXTURE` is kept for the verifier, unchanged in scope and loudly warned about; 9 tests.
- ✅ Phase 3: D11 fixed. Conservative robots.txt handling in all three stages (429, 5xx, no response, timeout, or an
  unsafe or cross-host redirect → fetch nothing; partial report); per-hop-validated robots.txt fetches in
  trust/engagement; a per-page robots gate added to the engagement multi-page path; 12 tests.
- ✅ Phase 4: external corroboration off by default in the platform, per-audit opt-in with a UI disclosure, DB migration
  2 (nullable; legacy audits "not recorded"), shown in history and exports, outages reported as unavailable, 256 KiB
  response cap, engine CLI default unchanged; 26 tests (9 engine, 11 backend, 6 frontend).
- ✅ Phase 5: retention disabled by default (`BRAND_PLATFORM_RETENTION_DAYS`, strict 1–3650), startup and daily purge
  when configured, `python -m brand_platform.purge` (preview default, `--apply`), migration 3, secure_delete, the
  verifier's mock server on 127.0.0.1; 45 tests (43 backend, 2 engine).

## Next session (recommended order)
1. Owner: `git init` and make a first commit so CI can run and later changes are reviewable as diffs; keep the original
   submission ZIP outside the working tree (O1).
2. Engine fixes, each closing an evaluation error and keeping every existing test green. ✅ D14 (session 3: noindex
   recall 0.75 → 1.00, micro F1 0.90 → 0.92, one label changed). ✅ D15 (session 4: redirect chains analysed on live headers; 10 regression tests;
   no metric change because dataset v1 has no redirect detector). Next: fixed-width viewport, walls of text outside `<p>`, and nav-link-as-CTA.
   Re-run the evaluation and report before/after metrics on the same frozen dataset v1 each time.
   Practice established in session 3: before a fix, save a named baseline (`--name baseline-pre-<fix>`); after it,
   a named post-fix run; then, with the owner's approval, regenerate the canonical `results.json` (done for D14 on
   2026-10-25).
3. Show `readiness-v2` and its penalty breakdown in the React audit page.
4. Evaluation v2: second annotator, κ, more and multi-page cases.
5. M3b optional LLM explanations; remaining docs.

## Known limitations carried forward
- Live audits are not reproducible over time (sites change; Wikipedia/Wikidata availability varies).
- The readiness index is an internal heuristic, not a validated measure and not an Adobe score.
- Single-node job runner: no horizontal scaling; in-flight jobs do not survive a restart (they are marked interrupted).
- D11 fixed (security phase 3). D9 (a robots.txt self-disallow is titled "anti-bot") is still open.
- D14 fixed (session 3); D15 fixed (session 4).
- Evaluation metrics come from a small, single-annotator, synthetic dataset; they show agreement with the documented
  criteria, not real-world accuracy (`TESTING_AND_EVALUATION.md` §5).
