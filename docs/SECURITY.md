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
  robots.txt declares a `Crawl-delay`. Since security phase 6 a page cut off at 2 MB is recorded
  (`crawl_scope.truncated_urls`, `execution.truncated_pages`) and shown in the UI and PDF as an informational note; it
  does not make the audit partial or change any score.
- **Page text is scanned in linear time** (security phase 6, 2026-10-26). The email regex used by all three stages
  (`[\w.+-]+@…`) and the technical stage's FAQ question regex (`[^.!?]+\?`) were quadratic on long runs without the
  character they look for: 100,000 characters took about 130 s, so a hostile or merely large page could stall a stage
  until its 60 s timeout and leave the audit partial. They were replaced by `find_emails()` (a linear scanner, defined
  identically in each standalone script) and `QUESTION_SENTENCE` (the same regex with the lookbehind `(?<![^.!?])`).
  Both return exactly what the original regexes returned (0 differences over 300,183 and 30,013 curated and fuzzed
  inputs). On hostile 2 MB inputs every stage now finished in 0.3–5.3 s in most runs on the development laptop (a dual-core
  laptop CPU with other applications running), and in at most 13.1 s in one run while the machine was loaded; re-measured,
  that payload scaled linearly (2.4 s at 2 MB). Each stage's own timeout is 60 s.
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
- **The trust stage's `sitemap.xml` lastmod check** (security phase 6) uses the same fetcher (`_fetch_validated_text`),
  with a 64 KiB cap and a 3 s timeout. It previously used a bare `urlopen` that followed redirects to any host and
  scheme, with only the connect-time DNS filter as protection. The starting URL is now validated too, and a refused or
  cross-host redirect is recorded as an execution error; 404/410 is not an error. Tests:
  `TestSitemapFetchSafety` (10, real sockets), including a redirect to 10.0.0.1, 169.254.169.254, `[::1]`, `ftp:` and
  `file:`, and a check that no connection is attempted even when the DNS filter is disabled.
- **Page fetches stay on the audited site** (security phase 7, H2, 2026-10-26). All three stages now apply one redirect
  rule: each hop must stay on the previous hop's host, ignoring a leading `www.`. So http→https and apex↔www are
  followed (each hop still validated first), while a redirect to any other host, CDN subdomains and other ports
  included, is not. The technical stage (`fetch_url`) already worked this way; the trust and engagement page fetchers
  followed redirects to any public host and analysed that host's page as the audited site, without its robots.txt.
  They now raise `CrossHostRedirectRefused`, the page is reported as failed (`status: unavailable`, listed in
  `execution.failed_pages`) with the evidence "redirected to another host (not followed): <url>", and it is never
  counted as a pass. Loops and over-long chains end with urllib's limits (10 redirects) as a recorded failure.
  Tests: `TestPageRedirectScope` (6, real sockets): same-host followed, cross-host refused (also after a same-host
  hop) without contacting the other host, private/metadata/`ftp:` targets refused before connecting, loops and a
  missing `Location`, the reason carried into the composed report, and the host-pair rule checked against the
  technical stage's.
- **Only same-site sitemaps are fetched** (security phase 6). robots.txt `Sitemap:` lines on another host, including a
  CDN subdomain of the audited site, are skipped and never requested; `www.<site>` counts as the same site, as for every
  crawl request. Skipped URLs are listed in the technical evidence, `scope.sitemaps_skipped_offsite`, the UI and the
  PDF. **Limitation:** a site whose only sitemap is on a CDN host is reported as having no sitemap found on the site,
  and its sitemap URLs and lastmod dates are not used. Sitemap-index children were already restricted to the site.
  Malicious XML is handled by the bundled expat (2.6.0 here), which refuses entity-expansion ("billion laughs")
  documents; `TestOffsiteSitemaps` covers both.
- The engagement multi-page path checks robots.txt for every page, as the trust stage does. Pages passed with `--pages`
  were previously fetched without a per-page robots.txt check (the platform passes only `--technical`, whose URLs were
  already filtered).
- Tests: `tests/test_engine_fixes.py::TestRobotsFailureHandling` (11 tests on real sockets: 200 allow and disallow,
  same-host redirect, 403/404/410, 429, 500/503, closed port, a real timeout, a cross-host redirect, a redirect to
  10.0.0.1, an end-to-end compose, and the classifier table) and `backend/tests/test_robots_unreachable.py` (a 503
  robots.txt through the whole platform).
- Headless rendering is **disabled** in the platform (`BRAND_AUDIT_DISABLE_RENDER=1`) because a browser's own network
  stack bypasses these checks.
- **Engine CLI rendering is not covered by the SSRF guard** (security phase 7, M3A). When the engine scripts are run
  directly (`run_audit.py`, `check_technical.py`, `check_engagement.py`) and Playwright is installed, the technical
  stage renders the homepage and up to three crawled pages in headless Chromium **automatically**; the engagement stage
  renders with `--render` (`run_audit.py --render-engagement`). Chromium does its own DNS resolution, follows its own
  redirects and loads every sub-resource and script the page asks for, with none of `_validate_public_http_url`,
  `_guarded_dns`, the 2 MB cap or the same-host redirect rule applied. A hostile audited page can therefore make
  the auditing machine send requests to private, loopback or cloud-metadata addresses (blind SSRF). Only the URLs
  passed to `page.goto` were validated by the normal crawl first. When auditing a site you do not trust from the CLI,
  set `BRAND_AUDIT_DISABLE_RENDER=1` or do not install Playwright; rendered checks then report `unavailable`.
- **Proxies** (security phase 7, M3A; behaviour unchanged, verified). The engine's urllib openers use the proxy from
  `HTTP_PROXY`/`HTTPS_PROXY` (forwarded by the runner) and, on Windows, the system proxy setting even when no variable
  is set. Through a proxy, `_guarded_dns()` filters the **proxy's** address, not the target's: with a loopback or
  private proxy every fetch fails (verified: `DNS resolution for 127.0.0.1 returned no public IP addresses`), and with
  a public proxy the target hostname is resolved by the proxy, outside the connect-time filter. Per-hop validation
  still runs locally, but the DNS-rebinding window that `_guarded_dns()` narrows is open again, and the proxy may
  reach networks of its own. Running audits through a proxy is therefore unsupported.
- **The engine has no port allow-list** (CLI only). The platform admits only `BRAND_PLATFORM_ALLOWED_PORTS` (default
  80, 443) and crawling stays on the audited host *and port*, so this matters only when the engine CLI is given a URL
  with another port. Every address is still checked as public.

### Process isolation and limits (`runner.py`)
- Each audit runs `run_audit.py` in its own process group with a **minimal environment**: only PATH, temp and locale
  variables, proxy and CA settings, and the engine switches. API keys and passwords in the server environment are not
  inherited (tested). Forwarding the proxy variables does not make proxies supported; see the proxy bullet above.
- Hard kill of the whole process tree at runtime limit + grace; cancellation kills the tree too (both tested).
- Progress-file integrity (phase 6): the engine retries a failed progress write up to 7 times (about 0.6 s; on Windows
  the replace fails while the API is reading the file). An exhausted retry is printed as an error, and if the final
  update cannot be written the engine exits 3 and the audit is stored as **failed**, never as completed.
- `BRAND_PLATFORM_MAX_CONCURRENT_JOBS` (default 2), queue cap (default 10), one active audit per host, and a creation
  rate limit per client address (default 12 per 10 minutes, in memory, single node).

### Local-only exposure (`backend/brand_platform/exposure.py`, `__main__.py`; security-hardening phase 1, 2026-10-25)
Every HTTP request passes `ExposureGuard` before reaching CORS or any route. Rejections use the normal error envelope
with `X-Request-ID` and the security headers.

| Rule | Rejection |
|---|---|
| Client address and listening interface must both be loopback (`127.0.0.0/8`, `::1`, IPv4-mapped loopback). A server started with `--host 0.0.0.0` still refuses LAN clients; an unknown peer is refused. | 403 `remote_client_forbidden` |
| `Host` must be `localhost`, `127.0.0.1` or `[::1]` (any port). This defeats DNS rebinding, where a website re-points its own domain at 127.0.0.1. | 400 `invalid_host` |
| Methods other than GET/HEAD/OPTIONS that carry an `Origin` are refused (CSRF) unless that origin is the server's own (scheme plus the validated `Host`, so the Vite proxy's forwarded `localhost:5173` matches) or is listed in `BRAND_PLATFORM_CORS_ORIGINS`. Before M2 any loopback origin passed, on any port. `null` and malformed origins are refused. | 403 `cross_origin_forbidden` |
| `Sec-Fetch-Site` (Fetch Metadata, security phase 7, M2), see below: browser requests from other sites are refused, including GETs, sub-resources and preflights. | 403 `cross_site_forbidden` |
| A request body must be `application/json`. A body with no Content-Type is a CORS "simple request" that browsers send cross-site without a preflight. Bodiless POSTs (cancel) are unaffected. | 415 `unsupported_media_type` |
| Bodies are capped at 64 KiB, checked from `Content-Length` and by counting a streamed body (buffered up to the cap, then replayed). | 413 `payload_too_large` / 400 `invalid_content_length` |

- **Cross-site request protection** (`ExposureGuard.cross_site_refusal`; security phase 7, M2, 2026-10-26). Browsers mark
  every request with `Sec-Fetch-Site`, which page scripts cannot set:

  | `Sec-Fetch-Site` | Decision |
  |---|---|
  | `same-origin` | Allowed: the UI, its assets and the export links, served by the API or through the Vite proxy (which forwards the browser's `Host`, `Origin` and `Sec-Fetch-*` unchanged; verified against the real proxy). A POST must also carry a trusted `Origin` (browsers always send one). |
  | `none` (address bar, bookmark) | GET/HEAD only, to any path. A POST is refused. |
  | `same-site` / `cross-site` | Refused, with two exceptions: (1) an `Origin` explicitly listed in `BRAND_PLATFORM_CORS_ORIGINS`; (2) a GET/HEAD top-level navigation (`Sec-Fetch-Mode: navigate`, `Sec-Fetch-Dest: document`) to a UI page (not `/api`, and no `.` in the last path segment), so a link from another app can open `/audits/<id>`. API routes, exports, `/api/docs`, assets, `index.html`, images, scripts, frames, `fetch()` and preflights from other sites are refused, GET or not. |
  | any other value (empty, a list, unknown) | Refused. |
  | missing | Not treated as safe, and not as proof of anything. The request falls back to the rules that applied before M2: the `Origin` rule above, the JSON-only body rule and CORS. This keeps the documented `curl` contract (`docs/API_REFERENCE.md`): a client that sends neither `Origin` nor `Sec-Fetch-Site` is allowed. |

  `same-site` matters because sites ignore ports: a page on `http://localhost:3000` is same-site with
  `http://localhost:8000`. `BRAND_PLATFORM_CORS_ORIGINS` is **empty by default** since M2 (it was
  `http://localhost:5173,http://127.0.0.1:5173`). The UI and the Vite proxy are same-origin and need no entry. A listed
  port trusts whatever app runs on it: during M2 an unrelated project's dev server was found holding
  `127.0.0.1:5173`, while this project's Vite took `[::1]:5173`. Set the variable only for a frontend that calls the API
  directly from another loopback origin.

  These checks are not authentication. They stop a *browser* from acting for another website. Any program running on
  this computer can send any headers and can use the API fully; that follows from the local-only, unauthenticated
  design. Browsers without Fetch Metadata (before about 2020, Safari before 16.4) get only the `Origin`, JSON and CORS
  rules, so their cross-site GETs still reach the server, although the page cannot read the response.
  Tests: `test_exposure.py` (Fetch Metadata section).
- None of these rules has an environment-variable override. There is deliberately no "trusted proxy" or "allow remote"
  switch, because the platform has no authentication.
- `create_app` refuses to start if `BRAND_PLATFORM_CORS_ORIGINS` contains a non-loopback origin.
- `python -m brand_platform` binds 127.0.0.1 by default, exits with code 2 for any non-loopback `--host`, and runs uvicorn
  with `proxy_headers=False` (so `X-Forwarded-For` cannot change the address the rate limiter sees) and no `Server`
  header.
- Since security phase 6, `python -m brand_platform` prints a warning before serving: local-only (loopback binding,
  requests from other computers refused), no authentication (any user or program on this computer can start audits and
  read every stored audit), and do not expose it through a reverse proxy, tunnel or port forwarding. The UI footer
  states the same. Tests: `test_exposure.py` (banner before serving, none when the launcher refuses) and the frontend
  footer test.
- Fixed in the same phase: the request-logging middleware read `request.url`, which parses the Host header, so a malformed
  Host such as `[::1` caused a 500. It now reads the raw ASGI path.
- Tests: `backend/tests/test_exposure.py` (53). The test suite's client presents a genuine loopback identity through a
  test-only ASGI shim (`tests/conftest.py::LoopbackPeer`); production code contains no test bypass.

### API and browser
- Consistent error envelope `{error: {code, message, request_id}}`. Internal exceptions return a generic 500 message;
  stack traces are not sent to clients.
- Request IDs: a client value is accepted only if it matches `^[A-Za-z0-9-]{8,64}$`; otherwise a new one is generated.
- Headers: `Content-Security-Policy` (`default-src 'self'`, no inline script **or** style; bars are drawn as SVG so
  `unsafe-inline` is not needed), `X-Frame-Options: DENY`, `X-Content-Type-Options: nosniff`, `Referrer-Policy: no-referrer`.
  Responses produced through the application's middleware carry these headers and `X-Request-ID`: 404s and guard
  rejections are covered by tests, and a 422 validation error was checked on the real launcher. Some responses do
  **not** (verified on the real launcher or the in-process app, 2026-10-27): an **unhandled
  exception's 500** (Starlette's top-level error handler runs outside the middleware that adds them; the body is still
  the generic error envelope, but its `request_id` field is the placeholder `"-"`, so it cannot be used to correlate
  the response with server logs, and there is no `X-Request-ID` header, CSP, `nosniff`, framing or referrer header),
  and errors uvicorn sends itself before the application runs, such as a 400 for a malformed request
  line or an oversized header. See "Known gaps". There is no path exemption since
  security phase 7, M3A: the interactive Swagger UI at `/api/docs`, which was exempt because FastAPI's page loads
  `swagger-ui-dist@5` (a floating version, no integrity check) from cdn.jsdelivr.net onto the API's own origin, is
  disabled. `/api/docs` returns 404. The OpenAPI schema remains at `/api/openapi.json`.
- CORS allows only the explicitly configured loopback origins (none by default since M2) and the methods GET and POST.
- The UI renders crawled text as text (React escaping, no `dangerouslySetInnerHTML`), and links only `http:`/`https:`
  URLs with `rel="noopener noreferrer nofollow"`.
- SQL uses bound parameters; column names in dynamic UPDATEs come from a fixed allow-list.
- **Built-UI file route** (`main.py::ui_file`; security phase 7, H1, 2026-10-26). The fallback route that serves
  `frontend/dist` used to resolve and stat `dist / <request path>` before checking containment. On Windows a request
  such as `/%5C%5Chost%5Cshare%5Cx` or `/%2F%2Fhost/share/x` became the UNC path `\\host\share\x`, so the server's
  filesystem calls would make Windows try to reach that host over SMB (an NTLM-hash leak). Because it is a plain GET
  with a valid loopback `Host`, any web page could trigger it with an `<img>`. Now the path is checked as a string
  first: every segment must match `[A-Za-z0-9_-]`, with `.` allowed except at the start or end, and Windows device
  names, paths over 1024 characters, empty segments, `..`, backslashes, `:` and NUL are refused with 404 before any
  filesystem call. An allowed path is joined under `dist`, resolved, and its containment re-checked (a symlink leading
  out of `dist` is refused). Missing files and client-side routes still load `index.html`; `/api/*` is unchanged.
  Tests: `backend/tests/test_ui_files.py` (46: traversal, absolute, UNC, Windows-style and encoded paths, device names,
  NUL, hidden files, a filesystem-call interception proving UNC paths never reach `pathlib`, symlink and junction
  escapes, valid assets, missing assets, fallback, API routes; 47 since the session-15 follow-up). 35 of the original
  46 fail against the previous route.

### Data handling
- Stored: audit metadata, the composed report (findings and evidence snippets), and prioritisation. Not stored: raw
  page HTML, sub-audit working files (each job's work directory is deleted), or request headers.
- Logs are structured JSON with request id, path, status and duration. No request bodies and no secrets are logged.
- **Retention (security phase 5, 2026-10-25).** Off by default: with `BRAND_PLATFORM_RETENTION_DAYS` unset, nothing is
  ever deleted.
  - A set value must be a whole number from 1 to 3650, or the server refuses to start (no clamping, no guessing).
  - Expired means a finished audit whose `finished_at` (or `created_at` if it never finished) is strictly older than
    now − N days. Queued and running audits are excluded, and each audit's status is re-checked inside the delete
    transaction. Audits with unreadable timestamps are never deleted.
  - Deletion is one transaction per run: audits, reports and findings together (`ON DELETE CASCADE`), plus a
    `retention_runs` row holding only date, trigger, period, cutoff and counts.
  - The server purges at startup and every 24 hours in a daemon thread (errors are logged and retried, startup is never
    blocked, the thread stops at shutdown). `python -m brand_platform.purge` previews by default and deletes only with
    `--apply`. No network-accessible delete endpoint exists.
  - **Erasure limits:** the purge connection enables SQLite `secure_delete`, so freed pages are overwritten, and the WAL
    is checkpointed with `TRUNCATE` (if a reader holds the WAL, the checkpoint reports busy and old frames remain until
    a later checkpoint). This does not reach backups or copies of the database, exported JSON/PDF files, filesystem
    snapshots or journaling, SSD wear-levelling or remapped blocks, or OS page caches. Treat it as best-effort
    in-database overwriting, not forensic erasure.
  - Logs from a purge contain counts only (no ids, hosts or URLs).
  - Tests: `backend/tests/test_retention.py` (43), including a file-level check that deleted URLs, hosts, report and
    finding text no longer appear in the database files (and that the same check fails with `secure_delete` off).

## Dependency status (checked 2026-10-27; no versions changed)
Checked with `npm audit` against `frontend/package-lock.json` and the OSV database for every package installed in the
backend virtual environment. Applicability was assessed against how this project uses each package.

| Package (pinned) | Advisories | Applies here? |
|---|---|---|
| `starlette` 0.41.3 (via `fastapi` 0.115.6), runtime | GHSA-7f5h-v6xp-fcq8: quadratic CPU when merging many `Range` values in `FileResponse` | **Yes, low.** The built-UI route uses `FileResponse`. Measured on the real launcher (uvicorn 0.32.1, h11 0.16, development laptop, 2026-10-27): the largest accepted header is about 63 KiB (a 64 KiB header gets 400), room for about 5,000 ranges. Client-measured response times for one request: 2,000 ranges (20.8 KB header) 3.3 s, 3,000 (32.8 KB) 4.6 s, 4,000 (44.8 KB) 7.1 s, 5,000 (56.8 KB) 9.1 s. The work runs on a worker thread: `/api/health` answered in 0.25 s while a 5,000-range request was in progress, so one request does not stall the server; many concurrent ones would compete for CPU and worker threads. Only a local program can send it: browsers need a CORS preflight for such a header, and cross-site requests are refused (M2). Fixed in Starlette 0.49.1, which needs a FastAPI upgrade (not done). |
| `starlette` 0.41.3, runtime | Six others (multipart and form limits, `Host` poisoning of `request.url`, `StaticFiles` UNC paths, `HTTPEndpoint` methods) | No. No form or multipart parsing (JSON bodies only, 64 KiB), `Host` is validated before routing and `request.url` is not used for decisions, no `StaticFiles` (the built-UI route is custom, phase 7 H1), no `HTTPEndpoint`. |
| `react-router-dom` 6.28.0, shipped in the UI | Open redirects via untrusted paths, SSR hydration | No. Every navigation target is a fixed path or a server-generated hex audit id; there is no server-side rendering. Fixed in 6.30.x (not upgraded). |
| `vite` 5.4.11, development server only | **GHSA-v6wh-96g9-6wx3**: `/__open-in-editor?file=` passes the value to `fs.existsSync`; on Windows a `\\host\share` path makes the machine open an SMB connection to that host and send the developer's NTLMv2 hash. Also GHSA-vg6x-rcgg-rjx6 (CORS `*` lets any website read dev-server responses) and Windows `server.fs.deny` bypasses. | **Yes, while `npm run dev` runs** (confirmed by reading the installed code; not exploited). Any website visited at the same time can trigger the SMB connection with an `<img>`. The production build and the API are not affected, and API data stays protected through the proxy (M2 refuses cross-site requests; verified). The hash-leak fix exists only in Vite 6.4.3 and later; 5.4.21 fixes the CORS and `fs.deny` issues. **Workaround until upgraded:** run the dev server only while developing, stop it afterwards, and do not browse untrusted websites while it runs. Otherwise use the single-process mode (`npm run build`, then `python -m brand_platform`), which does not start Vite. |
| `vitest` 2.1.8, `tinypool`, `esbuild` (dev only) | RCE when the Vitest API/UI server listens; prototype-pollution gadget; esbuild serve CORS | No. Tests run with `vitest run`, which starts no server; `tinypool` options are not attacker-controlled; esbuild's own server is not used. |
| `pypdf` 5.1.0, `pytest` 8.3.4, `pip` 24.0 (test and tooling only) | Various | No runtime exposure. `pypdf` only parses the PDFs this project generates, in tests. |
| `uvicorn`, `pydantic`, `reportlab`, `h11`, `httpx` and the rest | None reported | — |

Upgrades are deliberately left to a separate, tested change.

## Known gaps (not implemented)
- **Unhandled-error 500s lack the security headers and the `X-Request-ID` header** (found in the M3A pre-commit
  review, 2026-10-27). The generic `internal_error` body is returned, so no stack trace leaks, but the response is
  built by Starlette's outermost error handler, outside the middleware that adds the headers. Low impact (a fixed JSON
  body with no page content). These responses lack the CSP, `nosniff`, framing and referrer headers. They also cannot
  be matched to server logs: the `X-Request-ID` header is missing, the body's `request_id` is the placeholder `-` (the
  handler runs after the request context has been reset, so even a client-supplied id is lost), and the error log line
  records `request_id: "-"` too (verified in-process, 2026-10-27). A fix
  (for example adding the headers in that handler, or a pure ASGI wrapper outside it) is a code change for a later
  phase. Errors uvicorn sends before the application runs (malformed request line, oversized header) cannot carry
  them either.
- **No authentication or authorisation.** Every local process and local user on the machine can start audits and read
  every stored audit. Since phase 1 nothing else can reach the API. **Public, LAN and reverse-proxied deployment are not
  supported** until proper authentication and deployment security are implemented.
- The rate limiter is in memory and keyed on the client IP, which is always a loopback address now. It still throttles
  runaway local clients, but it resets on restart and cannot tell local users apart.
- `_guarded_dns()` monkey-patches `socket.getaddrinfo` process-wide. That is safe only because each audit runs in its own process.
- Page-text regexes were profiled on six hostile 2 MB input shapes (security phase 6) and the two quadratic ones were
  fixed. The remaining patterns are not formally proven linear; a new pattern over page text should be checked the
  same way (`TestPageTextScansStayLinear` runs every stage on hostile pages).
- Sitemaps hosted on another host (for example a CDN) are not fetched, by decision; see the sitemap bullet above.
- Cross-site GET requests are refused since M2 when the browser sends `Sec-Fetch-Site` (all current browsers do).
  From a browser that does not send it, a cross-site GET still reaches the server. Such a page cannot read the
  response, and the built-UI route no longer touches other hosts (phase 7, H1). Cross-site links to UI pages are
  allowed on purpose; framing is denied.
- Link-escape tests for the built-UI route: the directory case runs everywhere (a symlink on POSIX, a junction on
  Windows, which needs no privilege). The file-symlink case may skip only on Windows accounts without the symlink
  privilege; on any other OS a failure to create the link fails the test, so a green Linux CI run means it ran.
- Retention is off by default (by decision). An operator who wants deletion must set `BRAND_PLATFORM_RETENTION_DAYS`.
- The original verifier's mock server now binds `127.0.0.1` (O8, resolved in phase 5). It still uses a fixed port,
  8999, and its `localhost` target pays a measured ~2 s per connection on this machine because `localhost` resolves to
  `::1` first. That cost was already present with the old all-interfaces IPv4 binding.
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
