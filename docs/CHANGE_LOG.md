# Change Log

The directory is not under Git, so every change is recorded here. A byte-for-byte snapshot of the 22 original files
was taken before any edit (session scratchpad `original_snapshot/`); initialising Git is recommended so future
changes are reviewable as diffs.

## Session 1 — 2026-10-23

### Changes to original files (targeted patches; CLI flags and JSON output contract preserved)

| File | Change | Reason (see `docs/PROJECT_AUDIT.md`) |
|---|---|---|
| `skills/audit-orchestrator/scripts/compose_report.py` | Proactive suggestions excluded from the readiness index. | D1 |
| same | Trust/engagement findings use the check's own `affected_pages` (fallback: site URL). | D2 |
| same | New `collect_unavailable()`: `execution.unavailable_categories`, `execution.unavailable_checks`, `execution.failed_pages`; no proactive "clean" suggestion for a category with no usable evidence; such a category marks the report partial. | D3 |
| same | `scope.sitemap_checked` uses the technical stage's new `sitemap.checked` flag (legacy JSON keeps old behaviour); new `scope.sitemap_found` and `scope.audited_urls`. | D4 |
| same | `scope.external_sources_checked` is 0 when corroboration did not run. | Offline mode |
| `skills/crawl-render-audit/scripts/check_technical.py` | `js_ev` defined before the render block; stray re-initialisation removed. | D5 |
| same | `BRAND_AUDIT_DISABLE_RENDER=1` skips Playwright with an explicit "disabled" note. | D6 |
| same | `_is_public_ip` uses `is_global` and checks IPv4-mapped / 6to4 / NAT64 embedded addresses; Teredo refused. Validator uses it. | D7 |
| same | `sitemap.checked` flag; `crawl_scope.failed_urls` list. | D3, D4 |
| `skills/freshness-corroboration/scripts/check_trust.py` | Same public-IP rule. | D7 |
| same | 4xx robots.txt treated as "no restrictions" without logging an error (RFC 9309); sitemap 404/410 not an error; sitemap failures labelled correctly. | D8 |
| same | Multi-page output carries `execution.errors`; fetch exceptions are recorded. | D3 |
| same | Pages after the primary page no longer re-query Wikipedia/Wikidata. | D12 |
| same | `BRAND_AUDIT_OFFLINE=1` skips corroboration and reports it **unavailable** (never a pass). | Reproducible tests/evaluation |
| same | **robots.txt gate fixed**: `robots_allows()` returns a tuple, which was tested for truthiness, so disallowed pages were fetched in both the multi-page and single-page paths. | D13 |
| `skills/engagement-audit/scripts/check_engagement.py` | Public-IP rule; 4xx robots.txt handling; render-disable switch. | D6, D7, D8 |
| `skills/audit-orchestrator/scripts/run_audit.py` | Optional `--progress-file` writes per-stage state atomically. Without the flag behaviour is unchanged. | Platform progress |
| `verify_marketplace.py` | Hygiene walk skips `.venv`, `node_modules`, `.git` and tool caches; also runs `tests/test_engine_fixes.py`. | Local environments are not part of the package |
| `tests/test_all_rubric_cases.py` | `if __name__ == "__main__": unittest.main()` moved to the end of the file so all 48 tests run (43 ran before). No assertion changed. | Audit §3 |
| `tests/test_round3_polish.py` | `read_text()` → `read_text(encoding="utf-8")` (5 calls) so the suite passes on Windows. | Audit §3 |
| same | The mock of `check_trust.robots_allows` returned `True`; the real function returns `(allowed, robots_url)`. Mock corrected to the real return type; assertions unchanged. The invalid mock is what hid D13. | D13 |
| `examples/run_live_smoke_tests.ps1` | `$host` (read-only automatic variable) renamed `$siteHost`. | Script could not run |

Not changed: `marketplace.json`, every `SKILL.md`, every reference guide, `RUBRIC_MAPPING.md`.
The two dead functions at the end of `tests/test_round3_polish.py` were left as they are; working equivalents are in
`tests/test_engine_fixes.py::TestPortedDeadTests`.

### New files
- `tests/test_engine_fixes.py` — 24 regression tests for D1–D8, D12, D13.
- `backend/` — FastAPI platform (`brand_platform/`), 84 pytest tests, pinned requirements.
- `frontend/` — React + TypeScript + Vite UI, 18 Vitest tests.
- `docs/PROJECT_AUDIT.md`, `docs/IMPLEMENTATION_ROADMAP.md`, `docs/API_REFERENCE.md`, `docs/SECURITY.md`, this file.
- `.gitignore`.

### Test results at the end of the session (all run on Windows 10, Python 3.12.3, Node 24.21.0)
| Suite | Result |
|---|---|
| `python tests/test_all_rubric_cases.py` | 48 passed |
| `python tests/test_round3_polish.py` | 20 passed |
| `python tests/test_engine_fixes.py` | 24 passed |
| `python verify_marketplace.py` | exit 0 (no `PYTHONUTF8` needed) |
| `backend: pytest` | 84 passed (includes real end-to-end audits of a local fixture site) |
| `backend: ruff check .` | clean |
| `frontend: npm test` / `npm run build` | 18 passed / build OK; `tsc --noEmit` clean |
| Browser walkthrough (Playwright, local fixture) | Submit → progress → results → finding detail → re-audit → compare → history → dashboard; 390 px viewport has no horizontal overflow; the only console error is the deliberate 422 for a private IP. |

## Session 2 — 2026-10-24

The session-1 `original_snapshot/` lived in that session's temporary scratchpad and is no longer reachable (PROJECT_AUDIT
O1). Nothing was restored from a ZIP. No engine file (`skills/`), original test, `verify_marketplace.py`,
`marketplace.json`, `RUBRIC_MAPPING.md` or frontend file was changed in this session.

### Changed files
| File | Change |
|---|---|
| `README.md` | Directory layout lists `tests/test_engine_fixes.py`, `examples/` and the platform folders; platform intro mentions readiness-v2 and the evaluation; test commands include the evaluation; new "Detector evaluation" section; packaging note updated. Original skill descriptions untouched. |
| `docs/PROJECT_AUDIT.md` | §6 gains a "Now" column; new §8 re-verification with test results, observations O1–O11, and defect D14. |
| `docs/IMPLEMENTATION_ROADMAP.md` | Milestone statuses (M3a readiness-v2, M4 evaluation, M5 CI) and a re-prioritised next-session list. |
| `docs/SECURITY.md` | Known gaps: third-party disclosure to Wikipedia/Wikidata (O5), test-only localhost escape hatches (O9), D14 note. |
| `docs/API_REFERENCE.md` | `GET /audits/{id}/readiness`; `readiness_v2` key in the JSON export; PDF contents. |
| `backend/brand_platform/main.py` | New `/readiness` endpoint; JSON export adds `readiness_v2` (existing keys unchanged). |
| `backend/brand_platform/pdf_report.py` | Itemised readiness-v2 section. |
| `backend/tests/test_api.py` | End-to-end test gains readiness-v2 assertions. No existing assertion changed or removed. |
| `backend/tests/test_db_runner_pdf.py` | PDF test gains readiness-v2 assertions. No existing assertion changed or removed. |

### New files
- `backend/brand_platform/readiness.py` (readiness-v2) and `backend/tests/test_readiness.py` (14 tests).
- `evaluation/harness.py`, `evaluation/run_evaluation.py`, `evaluation/test_evaluation.py` (10 tests).
- `evaluation/fixtures/v1/cases.json` and 51 pages under `evaluation/fixtures/v1/pages/` (59 cases, 103 labels;
  dataset sha256 `01d1d7e79ec5ee3ff6961b724885c0eb63d591f04db327334c70f18d473199a1`, unchanged since the labels were frozen
  before the first run).
- `evaluation/results/v1/results.json` and `results.md` (generated).
- `docs/TESTING_AND_EVALUATION.md`, `.github/workflows/ci.yml`.

### Findings
- **D14** (medium): `X-Robots-Tag` noindex is never detected on live sites, because the check requires dict headers but the
  real fetcher returns an `HTTPMessage`. Reproduced directly and by evaluation case `noindex-header`. Not fixed.
- **O11** (low): some evidence strings depend on the hash seed (set ordering). Verdicts are unaffected.

### Test results at the end of the session (Windows 10, Python 3.12.3, Node 24.21.0)
| Suite | Result |
|---|---|
| `python tests/test_all_rubric_cases.py` | 48 passed |
| `python tests/test_round3_polish.py` | 20 passed |
| `python tests/test_engine_fixes.py` | 24 passed |
| `python verify_marketplace.py` (from a scratch directory) | exit 0 |
| `python evaluation/test_evaluation.py` | 10 passed |
| `python evaluation/run_evaluation.py --check` | reproducible (also with `PYTHONHASHSEED` 1, 2, 3, 7) |
| Evaluation v1 | micro P 0.94 / R 0.87 / F1 0.90; macro F1 0.89; 7 errors; 0 abstentions |
| `backend: pytest` | 98 passed (84 existing + 14 new) |
| `ruff check` (backend, evaluation) | clean |
| `frontend: vitest` / `tsc --noEmit` | 18 passed / clean |
| `.github/workflows/ci.yml` | YAML parses (PyYAML); **not run on GitHub** (no repository) |

## Session 3 — 2026-10-25 (D14 fix, approved)

Nothing was restored from or written to the original submitted ZIP. Only the working copy changed.

### Changed files
| File | Change |
|---|---|
| `skills/crawl-render-audit/scripts/check_technical.py` | **D14 fix only.** New `header_values(response_headers, name)` helper: every value of a header, case-insensitive, from an `http.client.HTTPMessage` or a dict, with list values and `None` handled. The `x_robots=` line uses it. 19 lines added, 1 line replaced; nothing else changed. `analyze_redirect_chain` (D15) is untouched. sha256 before `d08b98f1…`, after `626f8749…`. |
| `tests/test_engine_fixes.py` | New `TestXRobotsTagHeader` (7 tests): header noindex, `index, follow`, lowercase header name (HTTPMessage and dict), noindex in the second repeated header, unchanged dict behaviour, no header, and helper edge cases. Against the pre-fix engine 4 of them fail, as expected, and the 3 behaviour-preservation guards pass. No existing test changed. |
| `evaluation/run_evaluation.py` | `--name <stem>` writes `evaluation/results/<dataset>/<stem>.{json,md}` and refuses to overwrite an existing named file. The default (`results`) is unchanged. |
| `docs/PROJECT_AUDIT.md`, `docs/TESTING_AND_EVALUATION.md`, `docs/IMPLEMENTATION_ROADMAP.md`, `docs/SECURITY.md`, `README.md` | D14 marked fixed with measured before/after; D15 documented; test-results table updated. |

### New files
- `evaluation/results/v1/baseline-pre-d14-fix.{json,md}`: frozen dataset run immediately before the fix.
- `evaluation/results/v1/post-d14-fix.{json,md}`: the same dataset after the fix.
- `tests/repro_d15_redirect_chain.py`: standalone D15 reproduction (exit 1 while present). Not collected by any suite.

`evaluation/results/v1/results.{json,md}` were **not** modified (checked by sha256).

### Measured effect (frozen dataset v1, sha256 `01d1d7e7…`)
One label changed (`noindex-header`, FN → TP). `technical.noindex` recall 0.75 → 1.00 and F1 0.86 → 1.00. Micro F1
0.90 → 0.92, macro F1 0.89 → 0.90, errors 7 → 6. The other 12 detectors are identical in every count, and no new false
positive appeared.

### Test results after the fix
| Suite | Result |
|---|---|
| `tests/test_all_rubric_cases.py` / `test_round3_polish.py` / `test_engine_fixes.py` | 48 / 20 / 31 passed |
| `verify_marketplace.py` (from a scratch directory) | exit 0 |
| `backend: pytest` | 98 passed (run three times; one run printed an unexplained "Exception occurred during processing of request" line from a local fixture-server thread after the summary, with no failing test; the other two runs did not) |
| `ruff check` backend, evaluation, D15 repro | clean. The engine file has 5 pre-existing pyflakes findings, identical before and after the fix; not touched. |
| `frontend: vitest` / `tsc --noEmit` | 18 passed / clean |
| `evaluation/test_evaluation.py` | 9 passed, **1 failing by design** (`test_two_runs_are_identical_and_match_committed_results`): the committed `results.json` holds pre-fix numbers and was not overwritten. `run_evaluation.py --check` fails for the same reason. Both will pass once `results.json` is regenerated, if the owner approves; the CI evaluation step fails until then. |
| `tests/repro_d15_redirect_chain.py` | exit 1 (D15 present) |

## Session 3b — 2026-10-25 (canonical evaluation results refreshed, approved)

Command: `python evaluation/run_evaluation.py` (default `--name results`, frozen dataset v1, reference year 2026, header
fidelity as documented). Only `evaluation/results/v1/results.json` and `results.md` were rewritten.
`baseline-pre-d14-fix.*` and `post-d14-fix.*` are byte-identical to before (sha256-checked), and no source, test, fixture
or configuration file changed.

- The refreshed `results.json` equals `post-d14-fix.json` in its deterministic content. Against the pre-fix baseline,
  exactly one label differs (`noindex-header`, FN → TP). Micro F1 is 0.92, with 6 errors.
- `run_evaluation.py --check` passes (`PYTHONHASHSEED` 0, 1, 2, 3, 7, 42). `evaluation/test_evaluation.py`: 10 passed,
  so the session-3 "failing by design" test now passes without any test change.
- CI-equivalent checks: engine suites 48 / 20 / 31 passed; `verify_marketplace.py` exit 0; backend pytest 98 passed;
  `ruff check backend evaluation` clean; frontend `typecheck` clean and `npm test` 18 passed. `npm run build` was **not**
  run locally because it would overwrite the existing `frontend/dist/` and no frontend file changed; CI still runs it.
- `tests/repro_d15_redirect_chain.py` still exits 1: D15 is open, as intended.
- Docs updated: `TESTING_AND_EVALUATION.md` (§1 results, §4 file roles) and `IMPLEMENTATION_ROADMAP.md` (results-refresh
  practice).

## Session 4 — 2026-10-25 (D15 fix, approved)

The original submitted ZIP was not touched. Only the working copy changed.

### Changed files
| File | Change |
|---|---|
| `skills/crawl-render-audit/scripts/check_technical.py` | **D15 fix only.** New `_internal_header(headers, key)` helper returns the value `fetch_url` stored. On an `HTTPMessage` that is the *last* value, so server-sent `_final_url:` / `_redirect_chain:` headers cannot override it; dicts behave as before. `analyze_redirect_chain` uses it for its two reads and accepts the chain only as a list or tuple. `fetch_url` and its redirect handler are unchanged. sha256 before `626f8749…`, after `92e46e7e…`. |
| `tests/test_engine_fixes.py` | `import http.client`; new `TestRedirectChainHeaders` (6 tests: 0, 1 and 3 hops, cross-host, spoofed private headers, missing headers) and `TestRedirectChainLiveFetch` (4 tests on real sockets with the real `fetch_url`: 0/1/3 hops, cross-host reported and not followed, private redirect target refused, redirect run capped). Against the pre-fix engine 6 fail; the 4 that pass on both include the two safety guards. No existing test changed. |
| `tests/repro_d15_redirect_chain.py` | Docstring only: marked fixed. |
| `docs/PROJECT_AUDIT.md`, `docs/TESTING_AND_EVALUATION.md` (§1, new §4.2), `docs/SECURITY.md`, `docs/IMPLEMENTATION_ROADMAP.md` | D15 marked fixed; evaluation note. |

### New files
- `evaluation/results/v1/baseline-pre-d15-fix.{json,md}` and `post-d15-fix.{json,md}`. They are identical in every verdict
  and metric because dataset v1 has no redirect detector. The canonical `results.{json,md}` and all earlier result files
  are unchanged (sha256-checked).

### Test results after the fix
| Suite | Result |
|---|---|
| `tests/test_all_rubric_cases.py` / `test_round3_polish.py` / `test_engine_fixes.py` | 48 / 20 / 41 passed |
| `tests/repro_d15_redirect_chain.py` | exit 0 (was 1) |
| `verify_marketplace.py` (from a scratch directory) | exit 0 |
| `backend: pytest` | 98 passed |
| `ruff check backend evaluation` + the repro script | clean. Engine file: the same 5 pre-existing pyflakes findings before and after. |
| `evaluation/test_evaluation.py` / `run_evaluation.py --check` | 10 passed / reproducible (`PYTHONHASHSEED` 1, 42) |
| `frontend: typecheck` / `npm test` | clean / 18 passed (`npm run build` not run locally; it would overwrite `frontend/dist/`) |

## Session 5 — 2026-10-25 (security hardening, phase 1 of 5: API exposure; approved)

The original submitted ZIP was not touched. No engine script, `verify_marketplace.py`, frontend file, `.env` file or
secret was changed (engine `check_technical.py` sha256 still `92e46e7e…`).

### Changed files
| File | Change |
|---|---|
| `backend/brand_platform/exposure.py` (new) | `ExposureGuard` ASGI middleware: loopback-only client and listening interface (403 `remote_client_forbidden`), Host allow-list `localhost`/`127.0.0.1`/`[::1]` (400 `invalid_host`), foreign-Origin refusal for non-GET methods (403 `cross_origin_forbidden`), JSON-only request bodies (415 `unsupported_media_type`), a 64 KiB body cap from Content-Length and a streamed-body count (413 `payload_too_large`, 400 `invalid_content_length`). No environment overrides. |
| `backend/brand_platform/__main__.py` (new) | `python -m brand_platform` launcher: 127.0.0.1 by default, exit 2 for non-loopback `--host`, uvicorn with `proxy_headers=False`, `forwarded_allow_ips=""`, `server_header=False`. |
| `backend/brand_platform/main.py` | Registers the guard (outside CORS, inside the request-context middleware). Refuses to start with non-loopback CORS origins. The request-context middleware reads the raw ASGI path instead of `request.url`: a malformed Host header (e.g. `[::1`) used to raise there and return 500, a pre-existing bug found by the new tests. |
| `backend/brand_platform/config.py` | `max_request_bytes = 64 KiB` (a constant, not read from the environment). |
| `backend/tests/conftest.py` | Test-only `LoopbackPeer` ASGI shim and `local_test_client()`. Starlette 0.41's TestClient always reports peer `testclient` and Host `testserver`, which the guard correctly refuses, so the fixture now presents a real loopback identity. No existing test or assertion changed. |
| `backend/tests/test_exposure.py` (new) | 51 tests: remote, unknown and loopback peers; non-loopback listener; 8 bad and 6 good Host values; 4 foreign and 3 local Origins; cross-origin reads get no CORS grant; 5 non-JSON content types; JSON with charset; bodiless cancel; exact-limit and limit+1 bodies; a 400 KiB chunked body; non-numeric Content-Length; 3 unsafe CORS configurations; 5 refused launcher hosts; the launcher's uvicorn options. |
| `README.md`, `docs/SECURITY.md`, `docs/API_REFERENCE.md` | Launcher instructions; local-only policy; public, LAN and proxied deployment documented as unsupported; new error codes. |

### New files
- `evaluation/results/v1/post-security-phase1.{json,md}`: identical in every verdict and metric to the canonical
  `results.json` (micro F1 0.92). All 10 earlier result files are unchanged (sha256-checked).

### Verification
| Check | Result |
|---|---|
| `backend/tests/test_exposure.py` | 51 passed (first run: 50 passed, 1 failed, which exposed the malformed-Host 500; fixed in `main.py`, not in the test) |
| `backend: pytest` (full) | 149 passed (98 existing + 51 new) |
| Engine `test_all_rubric_cases` / `test_round3_polish` / `test_engine_fixes` | 48 / 20 / 41 passed |
| `verify_marketplace.py` (from a scratch directory) | exit 0 |
| `ruff check backend evaluation` | clean |
| `evaluation/test_evaluation.py` / `run_evaluation.py --check` | 10 passed / reproducible |
| Frontend typecheck / `npm test` | clean / 18 passed |
| Live launcher smoke test (127.0.0.1:8765, throwaway data directory, stopped afterwards) | health 200; `Host: attacker.example` 400; body with no Content-Type 415; foreign Origin 403; `X-Forwarded-For: 8.8.8.8` not trusted (200); no `Server` header; `--host 0.0.0.0`, `192.168.1.5` and `::` exit 2 |

## Session 6 — 2026-10-25 (security hardening, phase 2 of 5: test-only target overrides; approved)

The original submitted ZIP was not touched. No `.env` file, secret, frontend file or URL/DNS/SSRF/redirect/crawl-limit
logic was changed.

### Changed files
| File | Change |
|---|---|
| `backend/brand_platform/config.py` | `local_fixture_port` is now a plain `None` default, settable only in code. `BRAND_PLATFORM_LOCAL_FIXTURE_PORT` is no longer read and has no effect. |
| `skills/crawl-render-audit/scripts/check_technical.py` | Both reads of `BRAND_AUDIT_LOCAL_FIXTURE` (`_validate_public_http_url`, `_guarded_dns`) go through the new `_legacy_local_fixture_port()`. It returns exactly what `os.environ.get` returned, so the allowance is unchanged, and prints a prominent stderr warning once per process. 2 lines replaced, 23 added. sha256 `92e46e7e…` → `5d1717e8…`. |
| `skills/freshness-corroboration/scripts/check_trust.py` | The same change. sha256 `f26861f1…` → `51c45276…`. |
| `skills/engagement-audit/scripts/check_engagement.py` | The same change. sha256 `062a1672…` → `e411b160…`. |
| `verify_marketplace.py` | Prints a five-line warning banner when it sets `BRAND_AUDIT_LOCAL_FIXTURE`. Behaviour otherwise unchanged. sha256 before `5bd88156…`. |
| `backend/tests/test_fixture_override.py` (new) | 5 tests: the environment variable is ignored; the API refuses a local target with both variables set in the server environment, and the fixture receives 0 requests; the child environment never inherits either variable; only the code-level setting reaches the child; a real engine child given a loopback URL past admission, with the unsafe server environment, fetches nothing (sensitivity checked: with the code-level setting the same scenario made 13 requests). |
| `tests/test_engine_fixes.py` | New `TestLegacyLocalFixtureOverride` (4 tests across all three engine modules): refusal and silence when unset; warning content, exactly once per process; no widening (other port, private IP, `[::1]`, `localhost` without the port, metadata IP, `localhost.localdomain`); DNS guard limited to the named port. No existing test changed. |
| `docs/SECURITY.md`, `docs/PROJECT_AUDIT.md` (O9), `docs/IMPLEMENTATION_ROADMAP.md` | Phase-2 status and the remaining CLI-only residual. |

### Incident during the session (no lasting effect)
The first scripted engine patch turned `\n` escapes into literal newlines and left all three engine scripts with a syntax
error. It was found immediately by parsing the files. All three were restored from the backups taken just before
(byte-identical, `check_technical.py` back to `92e46e7e…`), and nothing ran against the broken files. The second attempt
used a patch script that parses each result and rolls back on any failure. It rolled back once, on a wrong assertion
count in the script itself, before succeeding.

### New files
- `evaluation/results/v1/post-security-phase2.{json,md}`: identical in every verdict and metric to the canonical
  `results.json`. All 12 earlier result files are unchanged (sha256-checked).

### Verification
| Check | Result |
|---|---|
| `backend/tests/test_fixture_override.py` / `TestLegacyLocalFixtureOverride` | 5 passed / 4 passed |
| `backend: pytest` (full) | 154 passed (149 + 5) |
| Engine `test_all_rubric_cases` / `test_round3_polish` / `test_engine_fixes` | 48 / 20 / 45 passed |
| `tests/repro_d15_redirect_chain.py` | exit 0 |
| `verify_marketplace.py` (from a scratch directory) | exit 0. The log shows the verifier banner and the in-process warnings from `check_technical.py` and `check_trust.py`; stage subprocess warnings are captured by the verifier and shown only on failure, as before. |
| `ruff check backend evaluation` | clean |
| `evaluation/test_evaluation.py` / `run_evaluation.py --check` | 10 passed / reproducible |
| Frontend typecheck / `npm test` | clean / 18 passed |

## Session 7 — 2026-10-25 (security hardening, phase 3 of 5: robots.txt failures fail closed — D11; approved, incl. option A)

The original submitted ZIP was not touched. No `.env` file, secret, frontend file, or URL/DNS/SSRF/redirect-limit/
timeout/size-limit protection was weakened. Phase 1 and 2 protections are unchanged.

### Changed files
| File | Change |
|---|---|
| `skills/crawl-render-audit/scripts/check_technical.py` | New `classify_robots_status()` and `robots_unreachable_reason()`. `evaluate_robots_txt`: 2xx parse; 4xx except 429 no restrictions; anything else gives status `unreachable` and `audit_crawler_allowed=False` (it was "Defaulting to permissive crawl" for every non-200). `analyze_technical`: an unreachable robots.txt returns before sitemap discovery and any page fetch, with `crawler_block` and the page-dependent checks `unavailable`. sha256 `5d1717e8…` → `40276637…` (trust `51c45276…` → `75a50aa1…`, engagement `e411b160…` → `5139eaaa…`). |
| `skills/freshness-corroboration/scripts/check_trust.py` | `robots_allows` keeps its `(allowed, robots_url)` contract but fails closed. It fetches through the new `_fetch_robots_txt` (per-hop `_validate_public_http_url`, no cross-host follow, DNS guard, 64 KiB cap, 5 s timeout) instead of bare `urlopen`. A target that fails validation is now "not allowed" (was allowed). `ROBOTS_UNREACHABLE` records the reason, used in page-level evidence and in the single-page `robots_gate` (`status` stays `blocked`, the value the composer recognises; a new `cause` field). |
| `skills/engagement-audit/scripts/check_engagement.py` | The same `robots_allows` change (returns a bool, as before). `analyze_engagement_pages` now checks robots.txt for each page on the real-fetch path (pages from `--pages` previously bypassed it); runs with an injected `fetch_fn` are unchanged. |
| `tests/test_engine_fixes.py` | `import time`; new `TestRobotsFailureHandling` (11 tests). **Option A:** in `TestErrorLabelling.test_missing_robots_txt_is_allowed_without_error` only the patch target changed, from `urllib.request.urlopen` to `urllib.request.OpenerDirector.open`, so it stays offline with the validated opener; its assertions are unchanged. |
| `backend/tests/test_robots_unreachable.py` (new) | A 503 robots.txt through the whole platform: partial audit, only `/robots.txt` requested, all three categories unavailable, `sitemap_checked` false, no false defects or proactive suggestions, readiness-v2 not assessed. |
| `docs/SECURITY.md`, `docs/PROJECT_AUDIT.md`, `docs/IMPLEMENTATION_ROADMAP.md`, `docs/TESTING_AND_EVALUATION.md` | D11 marked fixed; robots.txt policy table; test counts. |

`compose_report.py` needed no change. The existing gate handling already produced the correct partial report; the
end-to-end compose test and the backend integration test confirm it.

### Found and corrected while writing the tests
The first version of the timeout test passed for the wrong reason. `time` was not imported in the test file, so the
fixture handler's `time.sleep` raised `NameError` and dropped the connection instead of delaying. Fixed by importing
`time` and asserting that the clients really waited (≥ 10.5 s) and that a "timed out" error was recorded.

### Evidence that the tests detect the old behaviour
The pre-phase-3 engine was rebuilt in the scratchpad from the pre-phase-2 backups plus the phase-2 patch script
(sha256s `5d1717e8…`/`51c45276…`/`e411b160…` match the session-6 values). With robots.txt answering 503, all three
stages returned *allowed*, and the technical stage fetched `/sitemap.xml` and `/`. The new behaviour fetches nothing.

### New files (evaluation)
- `evaluation/results/v1/post-security-phase3.{json,md}`: identical in every verdict and metric to the canonical
  `results.json` and to `post-security-phase2` (micro P 0.94 / R 0.89 / F1 0.92, macro F1 0.90, 6 errors, 0
  abstentions). Every fixture serves robots.txt with status 200. All 14 earlier result files are unchanged
  (sha256-checked).

### Verification
| Check | Result |
|---|---|
| `TestRobotsFailureHandling` / `test_robots_unreachable.py` | 11 passed / 1 passed |
| `backend: pytest` (full) | 155 passed (154 + 1) |
| Engine `test_all_rubric_cases` / `test_round3_polish` / `test_engine_fixes` | 48 / 20 / 56 passed |
| `tests/repro_d15_redirect_chain.py` | exit 0 |
| `verify_marketplace.py` (from a scratch directory) | exit 0 |
| `ruff check backend evaluation` | clean. Engine pyflakes: 4 in `check_technical.py` and 1 in `check_trust.py`, all present in the originals. The earlier "`sys` imported but unused" disappeared because the phase-2 helper uses `sys`. |
| `evaluation/test_evaluation.py` / `run_evaluation.py --check` | 10 passed / reproducible |
| Frontend typecheck / `npm test` | clean / 18 passed |

## Session 8 — 2026-10-25 (security hardening, phase 4 of 5: consent for external corroboration; approved, incl. option A)

The original submitted ZIP was not touched. No `.env` file, secret, SSRF/DNS/redirect protection or Phase 1–3 control
was changed. Nothing was committed or deployed.

### Migration 2
`ALTER TABLE audits ADD COLUMN external_corroboration INTEGER`. The column is nullable on purpose: existing audits keep
every column and their stored reports unchanged, and their consent stays NULL (shown as "Not recorded (predates
consent)"). Nothing is backfilled or inferred. New audits always store 0 or 1. Tested on a disposable database created
with migration 1 only; it upgrades to schema 2 with the legacy row and report intact, and re-running is a no-op. No real
platform database exists in this workspace (`backend/var/` is absent), so no live data was migrated.

### Changed files
| File | Change |
|---|---|
| `skills/freshness-corroboration/scripts/check_trust.py` | `BRAND_AUDIT_EXTERNAL_CORROBORATION=off`: no Wikipedia/Wikidata request on any page (even with an injected lookup), check `skipped`. If both lookups fail, the check is `unavailable`, never pass (`EXTERNAL_QUERY_STATUS`; the `check_external_apis` signature is unchanged). Responses are read with a 256 KiB cap (`_read_capped_json`), and an oversized response is a failed lookup. The offline switch still overrides an opt-in. The CLI default is unchanged, and mock data (the verifier) is unaffected. sha256 `75a50aa1…` → `d4044c2c…`. |
| `skills/audit-orchestrator/scripts/compose_report.py` | `SKIPPED_STATUSES`; `scope.external_sources_checked` is 0 when skipped (it would otherwise have claimed 2); new `scope.external_corroboration` (`skipped_by_user`, `unavailable`, `performed`, `not_run`) and `execution.skipped_checks`. sha256 `c7d2ee9e…` → `6bde2bce…`. |
| `backend/brand_platform/db.py` | Migration 2; `create_audit(..., external_corroboration=False)`; the row maps to `True`/`False`/`None`. |
| `backend/brand_platform/schemas.py` | `CreateAuditRequest.external_corroboration` (strict bool, default false); `Audit.external_corroboration: bool \| None`; `PublicConfig.external_corroboration_available`. |
| `backend/brand_platform/runner.py` | The flag is threaded through `submit` → `_run_safely` → `_run` → `_child_env`. Every audit without opt-in gets `BRAND_AUDIT_EXTERNAL_CORROBORATION=off`; the offline kill switch still sets `BRAND_AUDIT_OFFLINE=1` (also for opted-in audits). |
| `backend/brand_platform/main.py` | Passes the choice to the runner; `/api/config` reports availability. |
| `backend/brand_platform/pdf_report.py` | Header line with the recorded choice, the outcome, and the number of external sources checked; `consent_label()`. |
| `frontend/src/api.ts`, `lib/format.ts`, `pages/NewAudit.tsx`, `pages/History.tsx`, `pages/AuditDetail.tsx`, `styles.css` | An unchecked opt-in checkbox with the disclosure (linked by `aria-describedby`; disabled when the server is offline); `createAudit` sends an explicit boolean; an "External lookups" column in history; a label on the audit page; scoped CSS so the label wraps on narrow screens. `Audit.external_corroboration` is optional in the type, so the existing test fixture needed no change. |
| `backend/tests/test_api.py` | **Option A:** the end-to-end test's two requests add `"external_corroboration": True` (plus a comment). No assertion changed. Its assertion that `corroboration_check` is unavailable failed under the new default before this change, as predicted, and passes after it. |
| `backend/tests/test_corroboration_consent.py` (new) | 11 tests: migration 1 → 2 with a legacy row and report; explicit storage for new audits; child environment (off switch for every non-opted-in audit, kill-switch precedence, no leak of a server-environment value); strict boolean validation (5 bad values); config availability; end-to-end opt-out (report scope, `skipped_checks`, history, JSON, PDF) and opt-in; a legacy audit in history and the PDF. |
| `tests/test_engine_fixes.py` | New `TestExternalCorroborationConsent` (9 tests): no request on opt-out (single page, injected lookup, multi-page); opt-out with the offline switch; kill switch over opt-in; CLI default still corroborates; total outage gives unavailable; one source down still uses the other; the 256 KiB cap (reads at most limit + 1 bytes; exactly-at-limit parses); composer `skipped_by_user` vs `unavailable`. |
| `frontend/src/app.test.tsx` | 6 tests: default false is sent; true only when ticked; the disclosure text is the checkbox's accessible description; disabled when the server is offline; consent labels including legacy; `api.createAudit` default. |
| `README.md`, `docs/SECURITY.md`, `docs/PROJECT_AUDIT.md` (O5), `docs/API_REFERENCE.md`, `docs/IMPLEMENTATION_ROADMAP.md`, `docs/TESTING_AND_EVALUATION.md` | Consent model, API fields, statuses, test counts. |

### Incidents during the session (no lasting effect)
- The engine patch script rolled back once: two target strings depended on trailing whitespace that was lost when the
  script was written. Both files were confirmed unchanged by `cmp`; the edit was re-targeted and applied cleanly.

### Not done (decision needed)
- `frontend/dist/` (the build the backend serves in single-process mode) was **not** rebuilt, so it predates this phase's
  UI. The production build was verified to compile by building into the scratchpad (`vite build`, exit 0; the bundle
  contains the consent checkbox). Until `npm run build` is run, the single-process UI has no checkbox and always sends
  the default (off). That is the safe direction, but the history column is missing too.

### New files (evaluation)
- `evaluation/results/v1/post-security-phase4.{json,md}`: identical in every verdict and metric to the canonical
  `results.json` and to `post-security-phase3` (micro P 0.94 / R 0.89 / F1 0.92, macro F1 0.90, 6 errors). The harness
  calls `analyze_trust` with an injected empty lookup and no opt-out variable, so this phase does not affect it. All
  16 earlier result files are unchanged (sha256-checked).

### Verification
| Check | Result |
|---|---|
| New engine / backend / frontend tests | 9 / 11 / 6 passed |
| `backend: pytest` (full) | 166 passed (155 + 11) |
| Engine `test_all_rubric_cases` / `test_round3_polish` / `test_engine_fixes` | 48 / 20 / 65 passed |
| `tests/repro_d15_redirect_chain.py` | exit 0 |
| `verify_marketplace.py` (from a scratch directory) | exit 0 |
| `ruff check backend evaluation` | clean. Engine pyflakes unchanged (4 / 1 / 0, `compose_report.py` 0). |
| `evaluation/test_evaluation.py` / `run_evaluation.py --check` | 10 passed / reproducible (`PYTHONHASHSEED` 1, 42) |
| Frontend `tsc --noEmit` / `vitest` / `vite build` (to the scratchpad) | clean / 24 passed / exit 0 |

## Session 8b — 2026-10-25 (frontend rebuild and Phase 4 verification, approved)

### Frontend build
- Before building: no Git repository and no ZIP in the workspace. `frontend/dist/` contained only the four artifacts of the
  2026-10-23 build (`index.html`, `assets/index-CKXl5QOs.js`, `assets/index-CQXMUTIv.css`, `favicon.svg`, a copy of
  `public/favicon.svg`). It was copied to the scratchpad (`dist_before_phase4_build/`) before building.
- `npm run build` (`tsc --noEmit && vite build`): exit 0. `dist/` now holds `index.html`, `assets/index-M24TtfWX.js`,
  `assets/index-BNgDKekl.css` and `favicon.svg`; the old hashed assets were removed by Vite, and nothing else changed.
  The bundle contains the consent checkbox, its disclosure, the "External lookups" column and the legacy label.

### Real-browser smoke test (headless Chromium via the already-installed system Playwright 1.63; nothing installed)
A throwaway data directory in the scratchpad (deleted afterwards). A **migration-1-only** database with one pre-consent
audit and report was upgraded to schema 2 by the real launcher (`python -m brand_platform`, 127.0.0.1) at startup. One
opted-out and one opted-in audit were then seeded. **20 of 20 checks passed** at 1280 px and 390 px:
- the checkbox is unchecked by default and enabled; the disclosure (including what is *not* sent) is visible
- the bodies the browser actually POSTed were `external_corroboration: false`, then `true` after ticking (the target
  was a private IP, refused with a field error, so no audit was created)
- history shows "Opted in", "Not requested" and "Not recorded (predates consent)"
- the legacy audit page shows its consent label and its report
- the legacy report is served unchanged (JSON-equal to what was stored before the migration)
- no page-level horizontal overflow

The only console errors were the two deliberate 422 responses. The screenshots were also inspected by eye.

### Visual issue found (pre-existing, not fixed)
At 390 px the history table scrolls horizontally inside its container, and the site column is about 49 px wide, so URLs
wrap almost letter by letter. Serving the pre-phase-4 build against the same data showed the same 49 px column and an
already-overflowing table (460 px in a 316 px container). The new column adds about 85 px of horizontal scroll and does
not narrow the site column. A responsive history layout is a separate frontend change.

### Verification after the rebuild
backend 166 passed; engine 48 / 20 / 65 passed; `verify_marketplace.py` exit 0; ruff clean; evaluation tests 10 passed;
`--check` reproducible (`PYTHONHASHSEED` 0, 1, 42); frontend typecheck clean and 24 tests passed; D15 repro exit 0. All 16
result files that existed before phase 4 are unchanged (sha256-checked); the directory holds 18 (plus
`post-security-phase4.{json,md}`). Nothing was committed, pushed or deployed.

## Session 9 — 2026-10-25 (mobile layout of the audit history; approved)

Frontend only. No backend, API, authentication, configuration, evaluation dataset, `.env` file or original ZIP was
changed. Nothing was committed or deployed.

### Problem (pre-existing, confirmed against the pre-phase-4 build in session 8b)
Below about 760 px the history table scrolled sideways inside its container, so some cells were off-screen and site
links were squeezed to about 27 px wide. A 134-character URL broke into 40 lines of about 3 characters.

### Change
| File | Change |
|---|---|
| `frontend/src/pages/History.tsx` | The table gets `className="history-table"`. Each data cell gets a `data-label` matching its column, and the checkbox and site cells get `select-cell` / `site-cell` classes. Explicit ARIA roles (`table`, `rowgroup`, `row`, `columnheader`, `cell`) keep the table semantics when the mobile layout changes `display`. No column, value, link, checkbox or behaviour changed. |
| `frontend/src/styles.css` | One block inside the existing `@media (max-width: 760px)` breakpoint, scoped to `.history-table`. Each row becomes a card: the checkbox and full-width URL as the heading, then labelled lines using the existing header typography and design tokens. The header row is visually hidden but available to screen readers. Nothing outside the media query changed, and the dashboard table is unaffected. |
| `frontend/src/app.test.tsx` | 1 test: the table class and roles, 8 column headers, 8 cells per row, each data cell's `data-label` equal to its header, a disabled checkbox for a report-less audit, and the legacy consent label. |
| `frontend/dist/` | Rebuilt (`npm run build`, exit 0): `assets/index-BYewt8IE.js`, `assets/index-B-vUFE-P.css`, `index.html`, `favicon.svg`. The previous build is in the scratchpad (`dist_before_history_fix/`). |

### Browser verification (headless Chromium, system Playwright 1.63; real launcher on loopback, throwaway data)
Five seeded audits (legacy pre-consent, opted out, opted in, a 134-character URL with findings, and a failed audit with no report).

| Width | Sideways scroll (before → after) | All cells visible | Long URL (before → after) |
|---|---|---|---|
| 320 px | yes → **no** | no → **yes** | 40 lines × ~3 chars → **7 lines × ~19 chars** |
| 375 px | yes → **no** | no → **yes** | 40 × ~3 → **5 × ~27** |
| 390 px | yes → **no** | no → **yes** | 40 × ~3 → **5 × ~27** |
| 768 px | no → no | yes → yes | unchanged; screenshot **pixel-identical** before and after |
| 1280 px | no → no | yes → yes | unchanged; screenshot **pixel-identical** before and after |

At every width: no page overflow, 8 cells per row, 5 checkboxes (1 disabled), the same consent labels and column headers
as before, and no console errors. At 390 px, selecting two audits enabled "Compare selected (2/2)", and the site link
opened the audit page. The 320 px and 390 px screenshots were inspected by eye. The phase-4 browser smoke test (consent
checkbox, disclosure, request bodies, history labels, legacy page) was re-run against the new build and passed, with only
the two deliberate 422 console errors.

### Verification
frontend `tsc --noEmit` clean; `vitest` 25 passed (24 + 1); `npm run build` exit 0.
Backend suite re-run for regression confirmation (no backend file changed): 166 passed.

## Session 10 — 2026-10-25 (version control: local Git baseline; approved)

Until this session the project was **not** under Git. Sessions 1–9 above (the platform, D1–D15, evaluation v1,
readiness-v2, security phases 1–4, and the mobile history layout) were all made in one uncommitted working tree. They
are recorded here, in this change log, and **not** as separate historical commits, which would misrepresent what was
built and tested together. The first commit is one honest baseline of the working tree as verified on 2026-10-25:
backend 166 passed; engine 48 / 20 / 65; evaluation tests 10 passed and `--check` reproducible; `verify_marketplace.py`
exit 0; ruff clean; frontend typecheck clean and 25 tests passed. The unmodified original submission is not in this
history (see PROJECT_AUDIT O1); the submitted ZIP is kept outside the repository.

### Files changed for the baseline
| File | Change |
|---|---|
| `.gitignore` | Adds `.vscode/` (it only held a Live Server port, which the project does not use). Existing entries are kept: `.venv/`, `__pycache__/`, `*.pyc`, `.pytest_cache/`, `.ruff_cache/`, `backend/var/` (the platform database), `frontend/node_modules/`, `frontend/dist/`, `examples/reports/*.json`. |
| `.gitattributes` (new) | `* text=auto eol=lf`, plus binary types. This machine has `core.autocrlf=true` system-wide, which would give CRLF checkouts; the Python sources are LF-normalised. |
| `README.md` | Clone/setup instructions: `npm ci` + `npm run build` are required after cloning, because `frontend/dist/` is not in Git; ports documented. |

Excluded from the repository: `.venv/`, `frontend/node_modules/`, `frontend/dist/`, caches, any database, `.vscode/`,
scratch files (they live outside the project), and the original submission ZIP (not in the workspace). A secret scan of
the tracked files found no credentials, keys or `.env` files.

### Findings during baseline staging
- **Line endings.** The 18 evaluation result files (and `backend/requirements-dev.txt`) are CRLF in the working tree,
  because `run_evaluation.py` writes in text mode, which emits CRLF on Windows. With `eol=lf` Git would have stored the
  results as LF, so a clone would not reproduce their recorded SHA-256s. `.gitattributes` therefore marks
  `evaluation/results/** -text`, and the results are stored byte-for-byte: all 18 stored blobs were verified to have the
  same SHA-256 as the working files. `requirements-dev.txt` is normalised to LF in the repository. Making
  `run_evaluation.py` write `\n` explicitly is a possible later change; it was not made here.
- **Trailing whitespace.** `git diff --cached --check` reports trailing whitespace only in original-submission code
  (`README.md:58` in the original skills section, the four engine scripts, `tests/test_all_rubric_cases.py`,
  `verify_marketplace.py`) and, because of their CRLF endings, in the byte-exact result files. Every file added or
  changed by the platform work passes the check. The original code was not reformatted, to avoid unrelated changes.

## Session 11 — 2026-10-25 (security hardening, phase 5 of 5: audit retention; approved)

Built on the local baseline commit `327c83b`. The original submitted ZIP was not touched. No `.env` file, secret,
SSRF/DNS/redirect protection, API exposure rule or Phase 1–4 behaviour was changed. Every destructive operation ran
only against pytest temporary databases or throwaway scratchpad databases. No real platform database exists in this
workspace.

### Design (as approved)
- `BRAND_PLATFORM_RETENTION_DAYS`: unset (the default) keeps audits indefinitely. A set value must be a whole number
  from 1 to 3650, or the server refuses to start; it is never clamped (unlike the other numeric settings).
  `/api/config.retention_days` is `null` when retention is disabled.
- Expired: a finished audit whose `finished_at` (fallback `created_at` if it never finished) is **strictly** older than
  now − N days. Queued and running audits are never candidates, and status is re-checked inside the delete
  transaction. Unreadable timestamps are never deleted (counted as "undated"). Note: at startup the job manager marks
  leftover queued and running audits as `interrupted` with `finished_at` = now, so they become eligible only N days
  after that restart.
- `Database.purge_audits`: one transaction (audits, with reports and findings via `ON DELETE CASCADE`, plus the
  `retention_runs` row); `PRAGMA secure_delete = ON`; `wal_checkpoint(TRUNCATE)` afterwards.
- Scheduler: when a policy is set, `RetentionScheduler` (a daemon thread) purges at startup and every 24 h. Errors are
  logged and retried, startup is never blocked, it stops in the lifespan shutdown before the job runner, and its wait
  is interruptible.
- `python -m brand_platform.purge [--older-than-days N] [--apply]`: preview by default, `--apply` to delete, the same
  strict 1–3650 validation, a no-op when retention is disabled and no override is given, and it never creates a
  database.
- No HTTP delete endpoint was added.

### Changed files
| File | Change |
|---|---|
| `backend/brand_platform/config.py` | `parse_retention_days()` (strict), `Settings.retention_days` (env; default `None`), `__post_init__` validation. |
| `backend/brand_platform/db.py` | Migration 3 (index `idx_audits_finished`, table `retention_runs`; additive); `retention_candidates()`, `purge_audits()`, `_record_retention_run()`, `retention_runs()`. Migrations 1–2 unchanged. |
| `backend/brand_platform/retention.py` (new) | `plan()` (read-only), `apply()`, `RetentionScheduler`, timestamp parsing. |
| `backend/brand_platform/purge.py` (new) | The manual CLI. |
| `backend/brand_platform/main.py` | Starts and stops the scheduler only when a policy is set; `retention_days` in `/api/config`. Imports sorted by ruff (`I001`). |
| `backend/brand_platform/schemas.py` | `PublicConfig.retention_days`. |
| `backend/brand_platform/logging_setup.py` | The purge count fields are allowed in structured logs. |
| `verify_marketplace.py` | `MOCK_HOST = "127.0.0.1"`; the mock site binds loopback instead of all interfaces (O8). The target stays `http://localhost:8999/`. |
| `backend/tests/test_retention.py` (new) | 43 tests: config parsing (7 valid, 10 invalid), the default-off and env startup error, the config API, exact cutoff boundaries (1 s past is expired; exactly N days is kept, at N=30 and N=1), queued/running never, `created_at` fallback, `finished_at` precedence, undated kept, preview deletes nothing, apply deletes exactly the expired audits with reports and findings while legacy NULL consent stays NULL, in-transaction status re-check, rollback on failure, a purge log without content, deleted content absent from the database files, every API view 404 after purge, migration 3 from schema 1 and 2, the CLI (no-op, never creates a DB, preview, apply, env policy, invalid input), and the scheduler (startup purge, clean stop, failure never blocks startup, prompt stop). |
| `tests/test_engine_fixes.py` | `TestVerifierLoopbackBinding` (2 tests): `run_server()` binds `("127.0.0.1", 8999)` (the baseline commit's verifier binds `("", 8999)`, so the test detects the old behaviour), and `http://localhost` still reaches an IPv4 loopback server. |
| `backend/tests/test_corroboration_consent.py` | **Existing assertion updated:** the phase-4 migration test asserted `schema_version() == 2`, which became false by design with migration 3. It now asserts `MIGRATIONS[-1][0]`, the pattern already used in `test_db_runner_pdf.py`. Its legacy-preservation checks are unchanged and now also run through migration 3. |
| `README.md`, `docs/SECURITY.md`, `docs/API_REFERENCE.md`, `docs/PROJECT_AUDIT.md` (O8), `docs/IMPLEMENTATION_ROADMAP.md`, `docs/TESTING_AND_EVALUATION.md` | Retention configuration, commands, erasure limits, API behaviour, test counts. |

### Corrected during the session (mistakes in the new tests, not in the code)
- The first run of `test_retention.py` had two failures; both were wrong expectations or setups in the new tests:
  1. With N=1, audit C finished exactly one day earlier, which is exactly at the cutoff, so it is kept under the
     documented strict rule. The expectation was corrected, and the case now asserts that boundary.
  2. The test helper generated ids such as `"RRRR…"`, which the API rejects (`^[0-9a-f]{32}$`) with a 404 regardless of
     retention, so the API-after-purge test had **passed for the wrong reason**. Ids are now lowercase hex, and the test
     first asserts 200 before purging, so a later 404 can only come from the purge.
- Sensitivity checks: with `secure_delete` OFF, the deleted audit's URL, report and finding text remained in the file
  after deletion and checkpoint; with it ON, none did. So the file-level test detects the protection.

### Verifier timing (measured; not caused by this phase)
`localhost` resolves to `::1` first on this machine. The mock server is IPv4-only, both before (`""`) and now
(`127.0.0.1`), so every request pays a ~2 s IPv6 fallback either way (direct measurement: 2.0–3.1 s per request in both
cases). The verifier from the baseline commit (via a temporary `git worktree`) took 94 s, and the phase-5 verifier 96 s,
run back to back. The growth from ~60 s (session 2) happened before the baseline, most plausibly from the per-page
robots.txt checks added in security phase 3 (each pays the fallback); this was not measured further. Binding `::1` as
well would remove the fallback but was not requested.

### New files (evaluation)
- `evaluation/results/v1/post-security-phase5.{json,md}`: identical in every verdict and metric to the canonical
  `results.json` (micro F1 0.92, 6 errors). All 18 committed result files are byte-identical to the baseline commit
  (SHA-256 against `git show HEAD:`), and the 16 historically recorded checksums still match.

### Verification
| Check | Result |
|---|---|
| `backend/tests/test_retention.py` / `TestVerifierLoopbackBinding` | 43 passed / 2 passed |
| `backend: pytest` (full) | 209 passed (166 + 43) |
| Engine `test_all_rubric_cases` / `test_round3_polish` / `test_engine_fixes` | 48 / 20 / 67 passed |
| `tests/repro_d15_redirect_chain.py` | exit 0 |
| `verify_marketplace.py` (from a scratch directory) | exit 0 |
| `ruff check backend evaluation` | clean |
| `evaluation/test_evaluation.py` / `run_evaluation.py --check` | 10 passed / reproducible (`PYTHONHASHSEED` 0, 1, 42) |
| Frontend typecheck / `vitest` / `npm run build` | clean / 25 passed / exit 0 (asset hashes unchanged) |
| Live server on a migration-1 database (scratchpad) | upgraded to schema 3; `/api/config.retention_days` null |
| History layout re-check on the current build | 320/375/390 px: no overflow, all 8 cells visible; 768/1280 px pixel-identical to the session-9 screenshots |

## Session 12 — 2026-10-25 (pre-push review: `.gitignore` hardening)

A pre-push review found that `.gitignore` covered `backend/var/` but not stray secrets or databases elsewhere. Added:
`.env` / `.env.*` (except `.env.example`), key and certificate files (`*.pem`, `*.key`, `*.p12`, `*.pfx`, `id_rsa*`,
`id_ed25519*`), `credentials.json`, SQLite/DB files anywhere (`*.sqlite`, `*.sqlite3`, `*.sqlite3-*`, `*.db`,
`*.db-journal`), `*.zip` (the original submission ZIP stays outside the repository), the temporary JSON files
`verify_marketplace.py` writes to its working directory, logs, `*.tmp`/`*.bak`, `scratch/`, coverage output, `venv/`,
`node_modules/` and `.DS_Store`. Verified with `git check-ignore` (every example path is ignored) and
`git ls-files -ci --exclude-standard` (no tracked file becomes ignored). No source or test file changed.

Re-verified on the current code before committing: backend 209 passed; engine 48 / 20 / 67 passed; evaluation tests
10 passed and `--check` reproducible (`PYTHONHASHSEED` 0, 42); `verify_marketplace.py` exit 0; ruff clean; frontend
typecheck clean, 25 tests passed, build exit 0. All 18 result files from the baseline commit are byte-identical
(SHA-256 against `git show 327c83b:`).

Note: the session scratchpad (outside the repository) was removed externally between runs, including earlier build
backups, screenshots and a saved checksum list. Nothing in the repository was affected; Git now holds the reference
copies.

## Session 13 — 2026-10-25/26 (security phase 6: security and production-readiness audit; approved step by step)

Built on `3c64bbe` (`origin/main` at the start). The original submitted ZIP was not touched. No `.env` file, secret,
credential or real database was read or changed, and no existing SSRF, DNS, redirect, size or robots.txt protection was
weakened. Engine scripts (original submission working copies) were changed only to correct the security and reliability
issues below, as approved. One commit per logical change; all were verified before committing.

### Commits
| Commit | Change |
|---|---|
| `37832fc` | Step 1: the trust stage's `sitemap.xml` lastmod fetch moved from a bare `urlopen` (redirects followed to any host and scheme) to `_fetch_validated_text`, extracted from the robots.txt fetcher: validated start URL and every hop, same host only, DNS filtered at connect time, 64 KiB, 3 s. |
| `6d7cd5c` | Step 2: robots.txt `Sitemap:` lines on another host (CDN subdomains included) are skipped, never fetched, and reported. |
| `469c81e` | Reliability: bounded retry for progress-file writes; a final progress update that cannot be written fails the audit (exit 3). |
| `66be993` | Linear email detection (`find_emails`) in all three stages. |
| `371cc45` | Linear FAQ question scan (`QUESTION_SENTENCE`) in the technical stage, plus an end-to-end hostile-page test. |
| `b3efd43` | Step 3a: pages truncated at the 2 MB cap are recorded (informational). |
| `daf5076` | Step 3b: truncated pages and skipped off-site sitemaps are shown in the UI and PDF. |
| `25ecca9` | Step 4: local-only / no-authentication warning in the launcher and the UI footer. |
| `2568893` | Step 5: GitHub Actions moved to their Node 24 releases (`checkout@v5`, `setup-python@v6`, `setup-node@v5`). |
| (this commit) | Documentation. |

### Approved changes to existing tests
- Option A: the two D8 sitemap tests patch `urllib.request.OpenerDirector.open` instead of `urllib.request.urlopen`
  (assertions unchanged). They and the phase-3 test `test_missing_robots_txt_is_allowed_without_error` now use an
  offline DNS stub for `example.com`: URL validation resolves DNS before connecting, and the robots test had made a
  real DNS lookup since phase 3.

### Problems found during the phase, and how each was handled
1. **Committed before reading a result (process error).** `6d7cd5c` was committed in the same command that printed the
   backend result, which was 1 failed, 208 passed. It was local only. Work stopped, and the failure was investigated
   and reported. The commit was kept unchanged as approved; it was not the cause.
2. **Silent progress loss (pre-existing, Windows).** `test_end_to_end_audit_persist_export_and_compare` failed
   intermittently because `Progress.update` swallowed every `OSError`, and on Windows the atomic replace fails while
   the API reads the file. Measured with a reader polling continuously: 2049 of 3000 updates lost silently. After the
   fix (7 attempts, about 0.6 s of backoff): 0 of 1000 lost silently (77 exhausted and reported) under the same
   worst case, and 0 exhausted with a 0.05 s poll. Verified with the e2e test 10/10 and the full backend suite 3/3 runs
   while the engine suites ran in parallel.
3. **Quadratic regexes over page text (pre-existing since the original submission; denial of service).** The new
   2.5 MB truncation test hung. The email regex `[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}` (same shape in all three stages)
   took 14.6 s / 48.2 s / 133 s on 25k / 50k / 100k characters of `x`. Profiling every stage on six hostile 2 MB
   shapes after fixing it exposed a second one, the FAQ regex `([^.!?]+\?)`, which still took over 30 s on four shapes,
   including 2 MB of plain words. The FAQ fix was outside the approval (email only) but required by the approved
   requirement that all stages handle 2 MB hostile input; it was committed separately so it can be reviewed on its
   own.
   - `find_emails` emulates `re.findall` exactly in linear time; `QUESTION_SENTENCE` adds `(?<![^.!?])`, which skips
     no match the original found because a match always starts at the start of a run.
   - **Behaviour differences: none.** 0 differences over 300,183 inputs for the email scanner (three variants, with
     each stage's flags; valid, invalid, quoted and unusual local parts, IP-literal domains, Unicode including
     case-folding edge characters such as U+212A and U+0130, multiple and adjacent addresses, long and adversarial
     strings; both the `findall` and boolean call styles) and over 30,013 inputs for the FAQ scan. An earlier candidate
     pattern with length limits (`{1,64}` local part) was faster but differed on 31 of 20,004 fuzzed inputs, so it was
     not used.
   - Timing: on hostile 2 MB inputs each stage took 0.3–5.3 s in most runs, and at most 13.1 s in one run while the
     machine was loaded. That payload, re-measured, scaled linearly (1.6 s technical, 2.4 s trust at 2 MB, wall ≈ CPU).
     The commit message of `371cc45` gives "0.3-5.3 s" and omits the 13.1 s reading; this entry is the correct record.
   - Wall-clock assertions were unreliable on this machine (a dual-core i5-7200U at 33–53 % background CPU). A 15 s
     limit failed twice with 21–25 s readings, during runs in which the whole process was several times slower; wall
     time equalled CPU time when re-measured. The linearity tests therefore count the scanner's pattern calls
     (deterministic) and keep only a 120 s hang guard, against hours for the original regex at 2 MB.
   - Each fix was tested in an isolated `git worktree` at the exact commit state before committing (engine suites,
     evaluation, verifier, backend), and the committed tree was confirmed identical to the tested tree. The worktree was
     removed afterwards.
4. **A test-tooling slip, caught.** The first version of the email helper had `\w` in a non-raw docstring, which Python
   reports as a `SyntaxWarning`; patches were then applied with warnings treated as errors, and the helper's docstring
   is raw.

### Remaining limitations (documented in `docs/SECURITY.md`)
- Sitemaps hosted on another host (for example a CDN) are not used, by decision.
- Page-text regexes were profiled on six hostile shapes, not formally proven linear.
- The build itself still uses Node 20 and Python 3.12 (unchanged by decision; only the action runtimes moved to Node 24).
- No authentication; local-only use only (unchanged; now stated at startup and in the UI).

### Verification (final, on `2568893` before the documentation commit)
| Check | Result |
|---|---|
| Engine `test_all_rubric_cases` / `test_round3_polish` / `test_engine_fixes` | 48 / 20 / 97 passed |
| `tests/repro_d15_redirect_chain.py` | exit 0 |
| `verify_marketplace.py` (from a scratch directory) | exit 0 |
| `evaluation/test_evaluation.py` / `run_evaluation.py --check` | 10 passed / reproducible (`PYTHONHASHSEED` 0, 42; micro F1 0.92) |
| Backend `pytest` (full) | 213 passed, two runs (209 before the phase + 4) |
| `ruff check backend evaluation` | clean; no new pyflakes findings in the engine scripts (counts equal to `3c64bbe`) |
| Frontend typecheck / `vitest` / build | clean / 30 passed / exit 0 |
| Browser check (Chromium, built app) | footer note visible at 390 px and 1280 px, no horizontal scroll |
| Evaluation result files | all 20 byte-identical (SHA-256: `3c64bbe` = `HEAD` = working tree); no evaluation file changed |
| Secret scan of `3c64bbe..HEAD`; tracked `.env`, database, ZIP, key or scratch files | none |

## Session 14 — 2026-10-26 (security phase 7, step H1: built-UI file route; approved)

Built on `3a4f7b7`. The phase 6 CI run (`40222500018` on `3a4f7b7`) passed all four jobs; only the
`ubuntu-latest` → Ubuntu 26 migration notice remained. No engine, evaluation, frontend or configuration file changed in
this step; no `.env`, secret or real database was touched.

### Vulnerability (found in the phase 7 audit, reproduced before fixing)
`backend/brand_platform/main.py`, the fallback route that serves `frontend/dist`, ran `(dist / path).resolve()` and
`is_file()` before its `is_relative_to(dist)` check. On Windows, `GET /%5C%5Cattacker.example%5Cshare%5Cx.png` or
`/%2F%2Fattacker.example/share/x` (and a browser's `///attacker.example/...`) became the UNC path
`\attacker.example\share\...`, and an interception probe showed both calls receiving it. On a real system those calls
make Windows try to reach the host over SMB/WebDAV, which can leak the user's NTLM hash. The request is a GET with a
loopback `Host`, so the local-only guard admits it and any web page could trigger it with an `<img>`. The old route also
answered a path containing NUL with an unhandled 500. Nothing tested the route (the test settings never mount it).

### Fix
`ui_file(dist, path)` decides from the path string before any filesystem call: allow-listed segments only
(`[A-Za-z0-9_-]`, `.` not first or last), no Windows device names, at most 1024 characters; anything else is a 404. An
allowed path is resolved under `dist` and its containment re-checked (symlinks out of `dist` are refused). Missing files
and client-side routes still return `index.html`, as before; `/api/*` is unchanged. Every file of the real build is
still served byte-for-byte.

### Tests
`backend/tests/test_ui_files.py` (new, 46 tests; 45 pass and the symlink test is skipped on this Windows account, which
cannot create symlinks). Against the previous route 35 of them fail, including all four that intercept `pathlib` and
assert no UNC path reaches it.

Corrected while writing the tests (test mistakes, not code defects): the HTTP test client rewrites `//host/...` into a
different URL, so those cases are sent byte-for-byte with an explicit raw path; and the fixture now enters the
`TestClient` context so `/api/health` has its startup state.

Disclosure: when running the new tests and a probe against the *previous* route, the UNC cases were sent to it without
interception, so Windows attempted a name lookup for `attacker.example`. That domain is reserved (RFC 2606) and never
resolves, so no connection could be made.

### Verification
| Check | Result |
|---|---|
| `backend/tests/test_ui_files.py` | 45 passed, 1 skipped |
| Backend `pytest` (full), two runs | 258 passed, 1 skipped (213 + 45) |
| Real launcher + uvicorn, raw paths with `curl --path-as-is` | `/`, asset, client route and `/api/health` 200; `///attacker.example/...`, `%5C%5C`, `%2F%2F`, encoded traversal, `C:\`, NUL all 404 |
| Engine `test_all_rubric_cases` / `test_round3_polish` / `test_engine_fixes` | 48 / 20 / 97 passed |
| `verify_marketplace.py`; `evaluation/test_evaluation.py`; `run_evaluation.py --check` | exit 0; 10 passed; reproducible (micro F1 0.92) |
| `ruff check backend evaluation` | clean |
| Frontend typecheck / `vitest` / build | clean / 30 passed / exit 0 |
| Evaluation result files | all 20 byte-identical to `3a4f7b7` |
