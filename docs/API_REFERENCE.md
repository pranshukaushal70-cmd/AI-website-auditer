# API Reference

Base path `/api`. JSON in and out. Interactive OpenAPI docs: `/api/docs`; schema: `/api/openapi.json`.
Timestamps are UTC ISO-8601 (`2026-10-23T10:25:11Z`). Every response carries `X-Request-ID`.
The API is local-only: loopback clients and `Host: localhost | 127.0.0.1 | [::1]` only; request bodies must be
`application/json` and at most 64 KiB; state-changing requests from a foreign `Origin` are refused (`docs/SECURITY.md`).

## Errors

```json
{ "error": { "code": "non_public_address", "message": "Hostname 'x' resolves to a non-public address (10.0.0.5).", "request_id": "…" } }
```

| HTTP | Codes |
|---|---|
| 400 | `invalid_host`, `invalid_content_length` |
| 403 | `remote_client_forbidden`, `cross_origin_forbidden` |
| 413 | `payload_too_large` (bodies over 64 KiB) |
| 415 | `unsupported_media_type` (request bodies must be `application/json`) |
| 404 | `audit_not_found`, `not_found` |
| 409 | `host_busy`, `not_cancellable`, `report_not_ready` |
| 422 | `validation_error` (with `details: [{field, message}]`), `invalid_url`, `unsupported_scheme`, `credentials_in_url`, `port_not_allowed`, `non_public_host`, `non_public_address`, `dns_resolution_failed`, `same_audit` |
| 429 | `rate_limited`, `queue_full` |
| 500 | `internal_error` |

## Endpoints

| Method & path | Purpose |
|---|---|
| `GET /health` | `{status, version, schema_version}` |
| `GET /config` | Public limits: `max_pages_cap`, `default_max_pages`, `allowed_ports`, `max_concurrent_jobs`, `max_queued_jobs`, `runtime_limit_seconds`, `rendering_enabled`, `priority_model`, `engine_version`, `external_corroboration_available` (false when the operator has switched external lookups off) |
| `POST /audits` | Body `{url, max_pages?, external_corroboration?}`. `max_pages` is 1–6. `external_corroboration` is a strict JSON boolean, default `false`: `true` opts in to sending the detected brand name to the Wikipedia/Wikidata search APIs. Returns **202** with an `Audit` in status `queued`. |
| `GET /audits` | Query `status`, `q` (URL/host substring), `host`, `limit` (≤100), `offset`. Returns `{items, total, limit, offset}`, newest first. |
| `GET /audits/{id}` | One `Audit`, including live `progress.stages` while it runs. |
| `POST /audits/{id}/cancel` | Cancels a queued or running audit (409 otherwise). |
| `GET /audits/{id}/findings` | Query `category`, `severity`, `q`, `include_proactive`. Returns findings ordered by priority rank; suggestions last. |
| `GET /audits/{id}/report` | `{audit, report}`, where `report` is the engine's composed JSON report (contract in `skills/audit-orchestrator/SKILL.md`, plus the additive `execution` and `scope` fields listed in `docs/CHANGE_LOG.md`). |
| `GET /audits/{id}/readiness` | `readiness-v2` for the stored audit: `{model, score, band, dimensions{technical,trust,engagement: {assessed, score, total_penalty, penalties[], unavailable_checks, weight}}, coverage, parameters, engine_v1, method}`. Each penalty: `{finding_code, fingerprint, title, dimension, severity, base_penalty, confidence, reach, reach_input, penalty, affected_pages, evidence_excerpt}`. 409 `report_not_ready` without a report. Definition: `docs/TESTING_AND_EVALUATION.md` §6. |
| `GET /audits/{id}/report.json` | Download: `{export_format: "brand-ai-readiness/1", audit, report, prioritised_findings, readiness_v2}` (`readiness_v2` added in session 2; existing keys unchanged) |
| `GET /audits/{id}/report.pdf` | Download: a PDF report covering summary, the itemised readiness-v2 penalty table, scope, methodology, severity chart, ranked recommendations with factors, finding details, and limitations. |
| `GET /compare?base=&target=` | Run diff: `persistent`, `new`, `resolved`, `inconclusive`, `counts`, `readiness_delta`, `caveats`. |

### Recorded consent
Every `Audit` (list, detail and the `audit` object in `report.json`) carries `external_corroboration`: `true`, `false`, or
`null` for audits created before consent was recorded ("Not recorded (predates consent)"). The composed report's
`scope.external_corroboration` says what actually happened (`skipped_by_user`, `unavailable`, `performed`, `not_run`), and
`execution.skipped_checks` lists checks skipped at the user's request, separately from `unavailable_checks`. The PDF
header shows both.

### Audit statuses
`queued` → `running` → one of `completed`, `partial` (the report exists but `execution.partial` is true), `failed`
(no valid report), `timed_out` (hard kill), `cancelled`, `interrupted` (the server stopped mid-run).

### Finding
`{id, audit_id, finding_code, fingerprint, title, category, severity, confidence, proactive, affected_pages, evidence,
suggested_action{summary, priority, how_to_fix}, priority{model, score, rank, factors[{name, value, input, explanation}]} | null}`.
`priority` is null for proactive suggestions. `fingerprint` (`category:slugified-title`) identifies the rule across runs.

## Example

```bash
curl -s -X POST localhost:8000/api/audits -H 'Content-Type: application/json' -d '{"url":"example.com","max_pages":3}'
curl -s localhost:8000/api/audits/<id>
curl -s localhost:8000/api/audits/<id>/findings
curl -s -o report.pdf localhost:8000/api/audits/<id>/report.pdf
```
