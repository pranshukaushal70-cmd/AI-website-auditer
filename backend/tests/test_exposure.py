"""Security-hardening phase 1: local-only exposure, Host validation, CSRF, body limits, launcher."""

import json

import pytest
from conftest import local_test_client, make_settings
from fastapi.testclient import TestClient

from brand_platform import __main__ as launcher
from brand_platform.config import Settings
from brand_platform.exposure import host_header_name, is_loopback_host, is_loopback_origin, is_ui_page_path, origin_key
from brand_platform.main import create_app

PRIVATE_TARGET = json.dumps({"url": "http://10.0.0.1/"})  # refused by URL safety, so a 422 proves the guard let it through
JSON = {"Content-Type": "application/json"}


@pytest.fixture()
def app(tmp_path):
    return create_app(make_settings(tmp_path))


def client_for(app, **kwargs):
    client = local_test_client(app, **kwargs)
    client.__enter__()
    return client


def error_code(response):
    return response.json()["error"]["code"]


# --- clients and listening interface -------------------------------------------------------------

@pytest.mark.parametrize("peer", [("192.168.1.20", 5000), ("10.1.2.3", 5000), ("8.8.8.8", 5000), ("2001:db8::1", 5000)])
def test_remote_clients_are_refused_before_reaching_the_api(app, peer):
    remote = client_for(app, client=peer)
    r = remote.post("/api/audits", content=json.dumps({"url": "https://example.com/"}), headers=JSON)
    assert r.status_code == 403 and error_code(r) == "remote_client_forbidden"
    assert r.headers["X-Request-ID"] and r.headers["X-Frame-Options"] == "DENY"  # rejections keep the standard envelope
    local = client_for(app)
    assert local.get("/api/audits").json()["total"] == 0  # nothing was created
    assert remote.get("/api/health").status_code == 403  # reads are refused too


def test_unknown_client_identity_is_refused(app):
    with TestClient(app) as raw:  # Starlette's default peer is the non-address 'testclient'
        assert raw.get("/api/health").status_code == 403


@pytest.mark.parametrize("peer", [("127.0.0.1", 1), ("127.0.0.5", 1), ("::1", 1), ("::ffff:127.0.0.1", 1)])
def test_loopback_clients_are_accepted(app, peer):
    assert client_for(app, client=peer).get("/api/health").status_code == 200


def test_server_listening_on_a_non_loopback_interface_refuses_requests(app):
    lan = client_for(app, base_url="http://192.168.1.5")  # as if started with --host 0.0.0.0 and reached via the LAN IP
    assert error_code(lan.get("/api/health")) == "remote_client_forbidden"
    assert error_code(lan.get("/api/health", headers={"Host": "localhost"})) == "remote_client_forbidden"


# --- Host header (DNS rebinding) ------------------------------------------------------------------

@pytest.mark.parametrize("host", ["attacker.example", "127.0.0.1.attacker.example", "localhost.attacker.example",
                                  "192.168.1.5", "127.0.0.2", "[::1", "localhost:80x", ""])
def test_unexpected_host_headers_are_rejected(app, host):
    r = client_for(app).get("/api/health", headers={"Host": host})
    assert r.status_code == 400 and error_code(r) == "invalid_host"


@pytest.mark.parametrize("host", ["localhost", "localhost:8000", "LOCALHOST:5173", "127.0.0.1:8000", "[::1]:8000", "[::1]"])
def test_loopback_host_headers_are_accepted(app, host):
    assert client_for(app).get("/api/health", headers={"Host": host}).status_code == 200


# --- cross-site requests ---------------------------------------------------------------------------

@pytest.mark.parametrize("origin", ["https://attacker.example", "null", "http://localhost.attacker.example", "file://"])
def test_state_changing_requests_from_foreign_origins_are_refused(app, origin):
    c = client_for(app)
    r = c.post("/api/audits", content=PRIVATE_TARGET, headers={**JSON, "Origin": origin})
    assert r.status_code == 403 and error_code(r) == "cross_origin_forbidden"
    r = c.post("/api/audits/" + "a" * 32 + "/cancel", headers={"Origin": origin})
    assert error_code(r) == "cross_origin_forbidden"


@pytest.mark.parametrize("host, origin", [("127.0.0.1:8000", "http://127.0.0.1:8000"), ("[::1]:8000", "http://[::1]:8000"),
                                          ("localhost:5173", "http://localhost:5173"), ("LOCALHOST:5174", "http://localhost:5174"),
                                          ("127.0.0.1", "http://127.0.0.1:80"), ("localhost:8000", "http://LOCALHOST:8000/")])
def test_the_servers_own_origin_passes_the_guard(app, host, origin):
    # Through the Vite proxy the Host header is the dev server's (localhost:5173, or the next free port), as is Origin.
    r = client_for(app).post("/api/audits", content=PRIVATE_TARGET, headers={**JSON, "Host": host, "Origin": origin})
    assert r.status_code == 422 and error_code(r) == "non_public_address"


@pytest.mark.parametrize("origin", ["http://localhost:5173", "http://127.0.0.1:5173", "http://localhost:3000",
                                    "http://127.0.0.1:8001", "https://127.0.0.1:8000", "http://localhost:8000"])
def test_other_local_origins_need_explicit_configuration(tmp_path, origin):
    """Security phase 7 (M2): before, any loopback origin could start or cancel audits. A port is not an app (another
    project's dev server can hold 127.0.0.1:5173), so only the server's own origin or a configured one passes."""
    headers = {**JSON, "Host": "127.0.0.1:8000", "Origin": origin}
    default = client_for(create_app(make_settings(tmp_path)))
    r = default.post("/api/audits", content=PRIVATE_TARGET, headers=headers)
    assert r.status_code == 403 and error_code(r) == "cross_origin_forbidden"
    assert error_code(default.post("/api/audits/" + "a" * 32 + "/cancel", headers=headers)) == "cross_origin_forbidden"
    configured = client_for(create_app(make_settings(tmp_path, cors_origins=[origin])))
    assert error_code(configured.post("/api/audits", content=PRIVATE_TARGET, headers=headers)) == "non_public_address"


def test_reads_with_a_foreign_origin_get_no_cors_grant(app):
    r = client_for(app).get("/api/audits", headers={"Origin": "https://attacker.example"})
    assert r.status_code == 200 and "access-control-allow-origin" not in r.headers


def test_cors_allowlist_is_empty_by_default(monkeypatch):
    monkeypatch.delenv("BRAND_PLATFORM_CORS_ORIGINS", raising=False)
    assert Settings().cors_origins == []
    monkeypatch.setenv("BRAND_PLATFORM_CORS_ORIGINS", "http://localhost:5173, http://127.0.0.1:5173")
    assert Settings().cors_origins == ["http://localhost:5173", "http://127.0.0.1:5173"]  # explicit configuration kept


# --- Fetch Metadata (Sec-Fetch-Site; security phase 7, M2) ------------------------------------------

OWN = "http://127.0.0.1:8000"
AUDIT = "/api/audits/" + "a" * 32
API_READS = ["/api/health", "/api/config", "/api/audits", AUDIT, AUDIT + "/findings", AUDIT + "/report",
             AUDIT + "/readiness", AUDIT + "/report.json", AUDIT + "/report.pdf", "/api/compare?base=a&target=b",
             "/api/docs", "/api/openapi.json"]
CROSS = ["cross-site", "same-site"]  # same-site: another port on the same loopback host name


def fetch_meta(site, mode="cors", dest="empty", origin=None, **extra):
    headers = {"Host": "127.0.0.1:8000", "Sec-Fetch-Site": site, "Sec-Fetch-Mode": mode, "Sec-Fetch-Dest": dest, **extra}
    if origin:
        headers["Origin"] = origin
    return headers


def navigation(site):
    return fetch_meta(site, mode="navigate", dest="document", **{"Sec-Fetch-User": "?1"})


def refused(r, code="cross_site_forbidden"):
    return r.status_code == 403 and error_code(r) == code


@pytest.fixture()
def built(tmp_path):
    """The API serving a built UI, as in single-process mode."""
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<!doctype html><title>UI</title>", encoding="utf-8")
    (dist / "assets" / "index-B-vUFE-P.js").write_text("console.log('app');", encoding="utf-8")
    (dist / "assets" / "index-Dt2g.css").write_text("body{}", encoding="utf-8")
    (dist / "favicon.svg").write_text("<svg/>", encoding="utf-8")
    return client_for(create_app(make_settings(tmp_path, frontend_dist=dist)))


UI_PAGES = ["/", "/dashboard", "/audits/new", "/audits/" + "0123456789abcdef" * 2, "/history", "/compare?base=a&target=b"]
STATIC = ["/assets/index-B-vUFE-P.js", "/assets/index-Dt2g.css", "/favicon.svg", "/index.html"]


def test_same_origin_browser_requests_pass(app):
    c = client_for(app)
    for path in API_READS:
        assert c.get(path, headers=fetch_meta("same-origin")).status_code != 403, path
    assert c.get("/api/audits", headers=fetch_meta("same-origin")).json()["total"] == 0
    assert c.head("/api/health", headers=fetch_meta("same-origin")).status_code != 403
    r = c.post("/api/audits", content=PRIVATE_TARGET, headers={**JSON, **fetch_meta("same-origin", origin=OWN)})
    assert error_code(r) == "non_public_address"
    assert error_code(c.post(AUDIT + "/cancel", headers=fetch_meta("same-origin", origin=OWN))) == "audit_not_found"
    # The export buttons are same-origin <a download> links: a navigation to an API route.
    assert error_code(c.get(AUDIT + "/report.pdf", headers=navigation("same-origin"))) == "audit_not_found"


def test_same_origin_assets_and_pages_load(built):
    for path in STATIC:
        assert built.get(path, headers=fetch_meta("same-origin", mode="no-cors", dest="script")).status_code == 200, path
    for path in UI_PAGES:
        assert built.get(path, headers=navigation("same-origin")).status_code == 200, path


@pytest.mark.parametrize("site", ["same-origin", "none"])
def test_browser_state_changes_without_an_origin_are_refused(app, site):
    """A browser always sends Origin on POST, so a POST marked by Fetch Metadata without one is not trusted."""
    c = client_for(app)
    assert refused(c.post("/api/audits", content=PRIVATE_TARGET, headers={**JSON, **fetch_meta(site)}))
    assert refused(c.post(AUDIT + "/cancel", headers=fetch_meta(site)))


def test_direct_navigation_reads_pass_but_cannot_change_state(built):
    """Sec-Fetch-Site: none is a URL typed into the address bar or a bookmark."""
    for path in UI_PAGES + STATIC:
        assert built.get(path, headers=navigation("none")).status_code == 200, path
    assert built.head("/", headers=navigation("none")).status_code != 403
    assert error_code(built.get(AUDIT + "/report.pdf", headers=navigation("none"))) == "audit_not_found"
    assert built.get("/api/docs", headers=navigation("none")).status_code == 200
    assert refused(built.post(AUDIT + "/cancel", headers={**navigation("none"), "Origin": OWN}))


@pytest.mark.parametrize("site", CROSS)
def test_cross_site_links_open_ui_pages(built, site):
    for path in UI_PAGES:
        r = built.get(path, headers=navigation(site))
        assert r.status_code == 200 and r.headers["X-Frame-Options"] == "DENY", path
    assert built.head("/dashboard", headers=navigation(site)).status_code != 403


@pytest.mark.parametrize("site", CROSS)
def test_cross_site_api_reads_are_refused_whatever_the_request_type(app, site):
    c = client_for(app)
    for path in API_READS:
        assert refused(c.get(path, headers=fetch_meta(site, origin="https://attacker.example"))), path  # fetch()
        assert refused(c.get(path, headers=fetch_meta(site, origin="http://localhost:3000"))), path
        for dest in ("image", "script", "style", "empty", "object", "embed"):  # <img>, <script>, ... (no Origin)
            assert refused(c.get(path, headers=fetch_meta(site, mode="no-cors", dest=dest))), (path, dest)
        assert refused(c.get(path, headers=navigation(site))), path  # a link to the API, e.g. an export download
        assert refused(c.get(path, headers=fetch_meta(site, mode="navigate", dest="iframe"))), path
    assert c.head("/api/health", headers=fetch_meta(site, mode="no-cors", dest="image")).status_code == 403  # no body


@pytest.mark.parametrize("site", CROSS)
def test_cross_site_static_resources_and_framed_pages_are_refused(built, site):
    for path in STATIC:
        for dest in ("script", "style", "image", "empty"):
            assert refused(built.get(path, headers=fetch_meta(site, mode="no-cors", dest=dest))), (path, dest)
        assert refused(built.get(path, headers=navigation(site))), path  # only UI pages may be opened from a link
    for path in UI_PAGES:
        assert refused(built.get(path, headers=fetch_meta(site, mode="navigate", dest="iframe"))), path
        assert refused(built.get(path, headers=fetch_meta(site, mode="cors", origin="https://attacker.example"))), path


@pytest.mark.parametrize("site", CROSS)
def test_cross_site_state_changes_and_preflights_are_refused(app, site):
    c = client_for(app)
    for origin in ("https://attacker.example", "http://localhost:3000", "null"):
        r = c.post("/api/audits", content=PRIVATE_TARGET, headers={**JSON, **fetch_meta(site, origin=origin)})
        assert refused(r, "cross_origin_forbidden"), origin
        # A cross-site <form method=post> is a navigation; it is refused as well.
        form = {**navigation(site), "Origin": origin, "Content-Type": "application/x-www-form-urlencoded"}
        assert refused(c.post(AUDIT + "/cancel", headers=form), "cross_origin_forbidden"), origin
        preflight = {**fetch_meta(site, origin=origin), "Access-Control-Request-Method": "POST",
                     "Access-Control-Request-Headers": "content-type"}
        r = c.options("/api/audits", headers=preflight)
        assert refused(r) and "access-control-allow-origin" not in r.headers, origin
    assert refused(c.post(AUDIT + "/cancel", headers=fetch_meta(site)))  # no Origin at all
    assert c.get("/api/audits").json()["total"] == 0  # nothing was created


@pytest.mark.parametrize("site, origin", [("same-site", "http://localhost:5173"), ("cross-site", "http://127.0.0.1:5173")])
def test_a_configured_dev_origin_keeps_cors_access(tmp_path, site, origin):
    """A frontend that calls the API directly from another loopback origin works once that origin is configured."""
    c = client_for(create_app(make_settings(tmp_path, cors_origins=[origin])))
    host = {"Host": "localhost:8000"}
    r = c.get("/api/audits", headers={**fetch_meta(site, origin=origin), **host})
    assert r.status_code == 200 and r.headers["access-control-allow-origin"] == origin
    preflight = {**fetch_meta(site, origin=origin), **host, "Access-Control-Request-Method": "POST",
                 "Access-Control-Request-Headers": "content-type"}
    r = c.options("/api/audits", headers=preflight)
    assert r.status_code == 200 and r.headers["access-control-allow-origin"] == origin
    r = c.post("/api/audits", content=PRIVATE_TARGET, headers={**JSON, **fetch_meta(site, origin=origin), **host})
    assert error_code(r) == "non_public_address"
    # Only that exact origin: the other dev host name, another port or an image request without Origin are refused.
    other = "http://127.0.0.1:5173" if origin == "http://localhost:5173" else "http://localhost:5173"
    assert refused(c.get("/api/audits", headers={**fetch_meta(site, origin=other), **host}))
    assert refused(c.get("/api/audits", headers={**fetch_meta(site, origin=origin.replace("5173", "5174")), **host}))
    assert refused(c.get("/api/audits", headers={**fetch_meta(site, mode="no-cors", dest="image"), **host}))


@pytest.mark.parametrize("host", ["localhost:5173", "[::1]:5173", "localhost:5174", "127.0.0.1:5173"])
def test_vite_dev_proxy_requests_pass_with_the_default_configuration(app, host):
    """What the Vite proxy forwards (verified against the real proxy): the browser's Host, Origin and Sec-Fetch-*
    headers unchanged, from a 127.0.0.1 peer. So the dev UI is same-origin on whatever port Vite chose."""
    c = client_for(app)
    origin = f"http://{host}"
    meta = {**fetch_meta("same-origin"), "Host": host}
    assert c.get("/api/audits", headers=meta).status_code == 200
    assert c.get("/api/config", headers=meta).status_code == 200
    r = c.post("/api/audits", content=PRIVATE_TARGET, headers={**JSON, **meta, "Origin": origin})
    assert error_code(r) == "non_public_address"
    assert error_code(c.post(AUDIT + "/cancel", headers={**meta, "Origin": origin})) == "audit_not_found"
    assert error_code(c.get(AUDIT + "/report.json", headers={**navigation("same-origin"), "Host": host})) == "audit_not_found"


def test_requests_without_fetch_metadata_keep_the_documented_curl_contract(built):
    """curl and scripts send neither Origin nor Sec-Fetch-Site (docs/API_REFERENCE.md). The missing header is not taken
    as proof of safety: such requests still pass the Origin, JSON-body and CORS rules, and a browser origin is checked."""
    assert built.get("/api/audits").status_code == 200
    assert error_code(built.get(AUDIT + "/report.pdf")) == "audit_not_found"
    assert built.get("/assets/index-B-vUFE-P.js").status_code == 200
    assert error_code(built.post("/api/audits", content=PRIVATE_TARGET, headers=JSON)) == "non_public_address"
    assert error_code(built.post(AUDIT + "/cancel")) == "audit_not_found"
    assert built.post("/api/audits", content=PRIVATE_TARGET).status_code == 415  # still a JSON-only API
    for origin in ("https://attacker.example", "http://localhost:3000", "null"):
        assert refused(built.post(AUDIT + "/cancel", headers={"Origin": origin}), "cross_origin_forbidden")


@pytest.mark.parametrize("value", ["", "cross-origin", "same-origin, cross-site", "same-originx", "*"])
def test_unknown_fetch_site_values_are_refused(built, value):
    assert refused(built.get("/api/audits", headers={"Sec-Fetch-Site": value}))
    assert refused(built.get("/", headers={**navigation("none"), "Sec-Fetch-Site": value}))


def test_fetch_site_values_are_case_and_space_insensitive(built):
    assert built.get("/api/audits", headers={"Sec-Fetch-Site": " Same-Origin "}).status_code == 200
    assert refused(built.get("/api/audits", headers={"Sec-Fetch-Site": "Cross-Site"}))


def test_cross_site_rejections_keep_the_standard_envelope(app):
    r = client_for(app).get("/api/audits", headers=fetch_meta("cross-site", mode="no-cors", dest="image"))
    assert refused(r) and r.headers["X-Request-ID"] and r.headers["X-Frame-Options"] == "DENY"
    assert r.json()["error"]["message"] == "Requests from other websites are not accepted."


# --- request bodies --------------------------------------------------------------------------------

@pytest.mark.parametrize("content_type", [None, "text/plain", "application/x-www-form-urlencoded", "multipart/form-data",
                                          "application/jsonx"])
def test_bodies_must_be_json(app, content_type):
    headers = {"Content-Type": content_type} if content_type else {}
    r = client_for(app).post("/api/audits", content=PRIVATE_TARGET, headers=headers)
    assert r.status_code == 415 and error_code(r) == "unsupported_media_type"


def test_json_with_charset_and_bodiless_posts_are_accepted(app):
    c = client_for(app)
    r = c.post("/api/audits", content=PRIVATE_TARGET, headers={"Content-Type": "application/json; charset=utf-8"})
    assert error_code(r) == "non_public_address"
    assert error_code(c.post("/api/audits/" + "a" * 32 + "/cancel")) == "audit_not_found"  # cancel has no body


def test_oversized_bodies_are_refused_by_content_length(app):
    c = client_for(app)
    limit = make_settings_limit()
    at_limit = json.dumps({"url": "http://10.0.0.1/", "pad": ""})
    at_limit = at_limit[:-2] + "x" * (limit - len(at_limit)) + '"}'
    assert len(at_limit) == limit
    assert c.post("/api/audits", content=at_limit, headers=JSON).status_code == 422  # reaches validation (extra field)
    r = c.post("/api/audits", content=at_limit + " ", headers=JSON)
    assert r.status_code == 413 and error_code(r) == "payload_too_large"


def test_oversized_streamed_bodies_are_refused_while_reading(app):
    def chunks():
        for _ in range(100):
            yield b"x" * 4096  # 400 KiB with no Content-Length (chunked transfer)
    r = client_for(app).post("/api/audits", content=chunks(), headers=JSON)
    assert r.status_code == 413 and error_code(r) == "payload_too_large"


def test_non_numeric_content_length_is_rejected(app):
    r = client_for(app).post("/api/audits", content=PRIVATE_TARGET, headers={**JSON, "Content-Length": "12abc"})
    assert r.status_code == 400 and error_code(r) == "invalid_content_length"


def make_settings_limit():
    from brand_platform.config import Settings
    return Settings.__dataclass_fields__["max_request_bytes"].default


# --- configuration and launcher ---------------------------------------------------------------------

@pytest.mark.parametrize("origins", [["https://attacker.example"], ["http://localhost:5173", "http://192.168.1.5:5173"], ["*"]])
def test_non_loopback_cors_origins_refuse_to_start(tmp_path, origins):
    with pytest.raises(ValueError, match="loopback origins"):
        create_app(make_settings(tmp_path, cors_origins=origins))


@pytest.mark.parametrize("host", ["0.0.0.0", "::", "192.168.1.5", "example.com", "10.0.0.1"])
def test_launcher_refuses_non_loopback_hosts(host, capsys):
    with pytest.raises(SystemExit) as exc:
        launcher.parse_args(["--host", host])
    assert exc.value.code == 2 and "only loopback addresses" in capsys.readouterr().err


def test_launcher_binds_loopback_and_ignores_proxy_headers():
    calls = []
    assert launcher.main(["--port", "8123"], run=lambda app, **kw: calls.append(kw)) == 0
    assert calls == [{"host": "127.0.0.1", "port": 8123, "proxy_headers": False, "server_header": False, "forwarded_allow_ips": ""}]
    for host in ("localhost", "::1", "127.0.0.1"):
        assert launcher.parse_args(["--host", host]).host == host


def test_launcher_prints_the_local_only_no_auth_warning_before_serving():
    import io
    events, out = [], io.StringIO()
    launcher.main(["--port", "8123"], run=lambda app, **kw: events.append(out.getvalue()), out=out)
    banner = events[0]  # already printed when the server starts
    assert banner.startswith("Brand AI-Readiness platform: http://127.0.0.1:8123/")
    assert "LOCAL-ONLY" in banner and "refuses requests from other computers" in banner
    assert "NO AUTHENTICATION" in banner and "can start audits and read every stored audit" in banner
    assert "reverse proxy, tunnel or port forwarding" in banner
    assert launcher.startup_banner("::1", 8000).startswith("Brand AI-Readiness platform: http://[::1]:8000/")


def test_launcher_prints_no_banner_when_it_refuses_to_start(capsys):
    with pytest.raises(SystemExit):
        launcher.main(["--host", "0.0.0.0"], run=lambda app, **kw: None)
    assert "Brand AI-Readiness platform:" not in capsys.readouterr().err


# --- helpers ---------------------------------------------------------------------------------------

def test_helper_parsing():
    assert host_header_name("[::1]:8000") == "::1" and host_header_name("Localhost:5173") == "localhost"
    assert host_header_name("[::1]x") is None and host_header_name("a:b") is None
    assert is_loopback_host("::ffff:127.0.0.1") and is_loopback_host("[::1]") and not is_loopback_host("testclient")
    assert not is_loopback_host("") and not is_loopback_host("0.0.0.0")
    assert is_loopback_origin("http://localhost:5173") and not is_loopback_origin("http://localhost:5173/path")
    assert origin_key("http://LocalHost:5173/") == ("http", "localhost", 5173) and origin_key("http://[::1]") == ("http", "::1", 80)
    assert origin_key("https://127.0.0.1") == ("https", "127.0.0.1", 443)
    for bad in ("null", "file://", "http://localhost:99999", "http://localhost:5173/x", "http://u@localhost", "ws://localhost", ""):
        assert origin_key(bad) is None, bad
    assert all(is_ui_page_path(p) for p in ("/", "/dashboard", "/audits/new", "/audits/" + "a" * 32))
    assert not any(is_ui_page_path(p) for p in ("/api", "/api/", "/api/audits", "/index.html", "/assets/x.js", "/favicon.svg", ""))
