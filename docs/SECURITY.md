# Security Model

Scope: the web platform (`backend/`, `frontend/`) and the audit engine it runs (`skills/`). This describes what is
**implemented and tested**. Items marked *not implemented* are known gaps.

## Threat model

| Actor / input | Risk | Primary controls |
|---|---|---|
| Platform user submitting a URL | SSRF into private networks or cloud metadata; port scanning; abusive load | Two-layer URL validation, port allow-list, rate and concurrency limits |
| Audited website (untrusted content) | Redirects or DNS answers pointing at internal addresses; oversized or slow responses; malformed HTML/JSON-LD; text crafted to manipulate an AI model | Per-request and per-redirect revalidation, DNS filtering at connect time, size/time caps, tolerant parsers, no LLM in the core path |
| Browser viewing results | Script injection through crawled text or URLs | React escaping, http(s)-only links, strict CSP |
| Operator environment | Secrets leaking into child processes or logs | Minimal child environment, no secrets in logs or the database |

## Controls

### URL admission (API layer, `backend/brand_platform/urlsafety.py`)
- Only `http`/`https`; scheme-only strings such as `javascript:` are rejected. No embedded credentials. No whitespace,
  control characters or backslashes. Length ≤ 2048.
- Ports limited to `BRAND_PLATFORM_ALLOWED_PORTS` (default 80, 443).
- `localhost`, `*.localhost`, `*.local`, `*.internal`, `*.lan`, `*.home.arpa`, `*.onion`, cloud metadata hostnames and
  single-label hosts (which also covers decimal/hex IPv4 spellings) are refused.
- The hostname is resolved, and **every** answer must be globally routable (`is_global` and not private, loopback,
  link-local, multicast, reserved or unspecified). IPv4-mapped, 6to4 and NAT64 addresses are judged by the embedded IPv4
  address; Teredo is refused. A mixed public/private answer set is rejected as a rebinding pattern.
- Tests: `backend/tests/test_urlsafety.py` (50 cases, including a parity check against the engine's rule).

### Per-request enforcement (engine, all three skill scripts)
- Every fetch, every redirect hop and the final URL are revalidated (`_validate_public_http_url`).
- `_guarded_dns()` filters `getaddrinfo` answers at connect time, which narrows the DNS-rebinding window between
  validation and connection.
- Responses are read up to 2 MB; 10 s socket timeouts; at least 0.5 s between requests to a host, or longer if
  robots.txt declares a `Crawl-delay`.
- robots.txt is checked before every page fetch. **D13** (the trust stage ignored disallow rules) was fixed in session 1
  and is covered by `tests/test_engine_fixes.py::TestTrustRobotsGate` and the backend end-to-end test
  `test_robots_disallowed_site_is_partial_not_clean`, which asserts that only `/robots.txt` was requested.
- **robots.txt failures fail closed** (D11 fixed, security phase 3, 2026-10-25). All three stages follow RFC 9309:

  | robots.txt result | Decision |
  |---|---|
  | 2xx | Parse the rules (an empty file has none) |
  | 4xx except 429 | Unavailable: no restrictions |
  | 429, 5xx, no response (network error, timeout, DNS failure, or a redirect refused by URL validation), or a cross-host redirect (not followed) | **Unreachable: fetch nothing** |

  An unreachable robots.txt is reported as unavailable evidence. The technical `crawler_block` is `unavailable`, the
  composer marks the audit **partial**, and there is no "anti-bot", "blocks all crawlers" or sitemap finding, nor a
  proactive "clean" suggestion. Skipped pages state the reason.
- The trust and engagement stages fetch robots.txt through a redirect-validating opener: every hop is checked with
  `_validate_public_http_url`, cross-host hops are not followed, DNS answers are filtered at connect time, the body is
  capped at 64 KiB, and the timeout is 5 s. The technical stage uses `fetch_url`, which already worked this way.
- The engagement multi-page path checks robots.txt for every page, as the trust stage does. Pages passed with `--pages`
  were previously fetched without a per-page robots.txt check (the platform passes only `--technical`, whose URLs were
  already filtered).
- Tests: `tests/test_engine_fixes.py::TestRobotsFailureHandling` (11 tests on real sockets: 200 allow and disallow,
  same-host redirect, 403/404/410, 429, 500/503, closed port, a real timeout, a cross-host redirect, a redirect to
  10.0.0.1, an end-to-end compose, and the classifier table) and `backend/tests/test_robots_unreachable.py` (a 503
  robots.txt through the whole platform).
- Headless rendering is **disabled** in the platform (`BRAND_AUDIT_DISABLE_RENDER=1`) because a browser's own network
  stack bypasses these checks.

### Process isolation and limits (`runner.py`)
- Each audit runs `run_audit.py` in its own process group with a **minimal environment**: only PATH, temp and locale
  variables, proxy and CA settings, and the engine switches. API keys and passwords in the server environment are not
  inherited (tested).
- Hard kill of the whole process tree at runtime limit + grace; cancellation kills the tree too (both tested).
- `BRAND_PLATFORM_MAX_CONCURRENT_JOBS` (default 2), queue cap (default 10), one active audit per host, and a creation
  rate limit per client address (default 12 per 10 minutes, in memory, single node).

### Local-only exposure (`backend/brand_platform/exposure.py`, `__main__.py`; security-hardening phase 1, 2026-10-25)
Every HTTP request passes `ExposureGuard` before reaching CORS or any route. Rejections use the normal error envelope
with `X-Request-ID` and the security headers.

| Rule | Rejection |
|---|---|
| Client address and listening interface must both be loopback (`127.0.0.0/8`, `::1`, IPv4-mapped loopback). A server started with `--host 0.0.0.0` still refuses LAN clients; an unknown peer is refused. | 403 `remote_client_forbidden` |
| `Host` must be `localhost`, `127.0.0.1` or `[::1]` (any port). This defeats DNS rebinding, where a website re-points its own domain at 127.0.0.1. | 400 `invalid_host` |
| Methods other than GET/HEAD/OPTIONS with an `Origin` that is not a loopback origin (including `null`) are refused (CSRF). | 403 `cross_origin_forbidden` |
| A request body must be `application/json`. A body with no Content-Type is a CORS "simple request" that browsers send cross-site without a preflight. Bodiless POSTs (cancel) are unaffected. | 415 `unsupported_media_type` |
| Bodies are capped at 64 KiB, checked from `Content-Length` and by counting a streamed body (buffered up to the cap, then replayed). | 413 `payload_too_large` / 400 `invalid_content_length` |

- None of these rules has an environment-variable override. There is deliberately no "trusted proxy" or "allow remote"
  switch, because the platform has no authentication.
- `create_app` refuses to start if `BRAND_PLATFORM_CORS_ORIGINS` contains a non-loopback origin.
- `python -m brand_platform` binds 127.0.0.1 by default, exits with code 2 for any non-loopback `--host`, and runs uvicorn
  with `proxy_headers=False` (so `X-Forwarded-For` cannot change the address the rate limiter sees) and no `Server`
  header.
- Fixed in the same phase: the request-logging middleware read `request.url`, which parses the Host header, so a malformed
  Host such as `[::1` caused a 500. It now reads the raw ASGI path.
- Tests: `backend/tests/test_exposure.py` (51). The test suite's client presents a genuine loopback identity through a
  test-only ASGI shim (`tests/conftest.py::LoopbackPeer`); production code contains no test bypass.

### API and browser
- Consistent error envelope `{error: {code, message, request_id}}`. Internal exceptions return a generic 500 message;
  stack traces are not sent to clients.
- Request IDs: a client value is accepted only if it matches `^[A-Za-z0-9-]{8,64}$`; otherwise a new one is generated.
- Headers: `Content-Security-Policy` (`default-src 'self'`, no inline script **or** style; bars are drawn as SVG so
  `unsafe-inline` is not needed), `X-Frame-Options: DENY`, `X-Content-Type-Options: nosniff`, `Referrer-Policy: no-referrer`.
  `/api/docs` (Swagger UI) is exempt from the CSP because it loads assets from a CDN.
- CORS allows only the configured dev origins and the methods GET and POST.
- The UI renders crawled text as text (React escaping, no `dangerouslySetInnerHTML`), and links only `http:`/`https:`
  URLs with `rel="noopener noreferrer nofollow"`.
- SQL uses bound parameters; column names in dynamic UPDATEs come from a fixed allow-list.

### Data handling
- Stored: audit metadata, the composed report (findings and evidence snippets), and prioritisation. Not stored: raw
  page HTML, sub-audit working files (each job's work directory is deleted), or request headers.
- Logs are structured JSON with request id, path, status and duration. No request bodies and no secrets are logged.

## Known gaps (not implemented)
- **No authentication or authorisation.** Every local process and local user on the machine can start audits and read
  every stored audit. Since phase 1 nothing else can reach the API. **Public, LAN and reverse-proxied deployment are not
  supported** until proper authentication and deployment security are implemented.
- The rate limiter is in memory and keyed on the client IP, which is always a loopback address now. It still throttles
  runaway local clients, but it resets on restart and cannot tell local users apart.
- `_guarded_dns()` monkey-patches `socket.getaddrinfo` process-wide. That is safe only because each audit runs in its own process.
- No automatic data-retention purge.
- **Third-party disclosure (O5; resolved for the platform in security phase 4, 2026-10-25).** External corroboration is
  **off by default** and opt-in per audit:
  - The New Audit page has an unchecked checkbox. Its disclosure says that the brand name detected on the site is sent to
    the public Wikipedia and Wikidata search APIs, and that no page content, address or contact detail is sent.
  - `POST /api/audits` accepts `external_corroboration` only as a strict JSON boolean (`"yes"`, `1` and `null` are
    rejected), and it defaults to `false`.
  - For every audit that did not opt in, the runner sets `BRAND_AUDIT_EXTERNAL_CORROBORATION=off` in the engine's
    environment. The trust stage then sends nothing to either service, on any page, and records the check as
    `skipped`. The report shows `scope.external_corroboration = "skipped_by_user"`, `external_sources_checked = 0`, and
    the check under `execution.skipped_checks`, not under `unavailable_checks`.
  - `BRAND_PLATFORM_OFFLINE_CORROBORATION=1` remains an operator kill switch that also overrides an opt-in (the check
    is then reported unavailable), and `/api/config` exposes `external_corroboration_available` so the UI disables the
    option.
  - The choice is stored per audit (migration 2, a nullable column; legacy audits show "Not recorded (predates
    consent)") and shown in history, the audit page, the JSON export and the PDF.
  - If both services fail or return an unusable response, the check is reported as **unavailable**, never as a pass.
    Each response is capped at 256 KiB, and an oversized response counts as a failed lookup.
  - The engine **CLI** default is unchanged (the original submission corroborates). Set
    `BRAND_AUDIT_EXTERNAL_CORROBORATION=off` to opt out on the command line.
- **Test-only local-target overrides (O9; phase 2, 2026-10-25)**:
  - Platform: `BRAND_PLATFORM_LOCAL_FIXTURE_PORT` was **removed**. `Settings.local_fixture_port` can be set only in code
    (the backend tests do this), so no environment or deployment configuration can enable local targets. Audit child
    processes get an allow-listed environment, so a `BRAND_AUDIT_LOCAL_FIXTURE` in the server's environment is never
    inherited. `backend/tests/test_fixture_override.py` proves both. One test hands the runner a loopback URL directly
    (bypassing API validation) with both variables set in the server environment, and the real engine child makes
    zero requests. With the code-level setting it makes 13, which shows the test can detect a leak.
  - Engine and original verifier: `BRAND_AUDIT_LOCAL_FIXTURE` is kept because `verify_marketplace.py` depends on it. Its
    scope is unchanged (`localhost`/`127.0.0.1` on exactly that port, http or https). Each engine script now prints a
    prominent stderr warning the first time it sees the variable, and the verifier prints a banner when it sets it.
    `tests/test_engine_fixes.py::TestLegacyLocalFixtureOverride` checks the warning, that it appears once per process,
    and that other ports, private IPs, `[::1]` and other local names stay refused.
  - Residual: anyone who sets `BRAND_AUDIT_LOCAL_FIXTURE` while running the engine **CLI** directly can still let it
    fetch that one local port. That is now loud, never silent, and the web platform cannot be made to do it.
- D14 (X-Robots-Tag `noindex` never checked on live responses) and D15 (redirect chains never analysed on live
  responses) were fixed on 2026-10-25. Both were correctness defects, not safety ones. The redirect *safety* controls
  in `fetch_url` were not modified, and `TestRedirectChainLiveFetch` now guards them with real sockets: cross-host hops
  are recorded but not followed, a redirect to a private address is refused before any connection, and redirect runs
  are capped. The D15 fix also stops a site from overriding the reported final URL or chain by sending its own
  `_final_url:` / `_redirect_chain:` headers.
- Optional LLM remediation (planned, M3) will need its own prompt-injection controls. Crawled text must be passed as quoted
  data, with no tool access, strict output validation, and a deterministic fallback.
