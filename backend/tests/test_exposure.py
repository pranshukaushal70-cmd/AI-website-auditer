"""Security-hardening phase 1: local-only exposure, Host validation, CSRF, body limits, launcher."""

import json

import pytest
from conftest import local_test_client, make_settings
from fastapi.testclient import TestClient

from brand_platform import __main__ as launcher
from brand_platform.exposure import host_header_name, is_loopback_host, is_loopback_origin
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


@pytest.mark.parametrize("origin", ["http://localhost:5173", "http://127.0.0.1:8000", "http://[::1]:8000"])
def test_local_origins_pass_the_guard(app, origin):
    r = client_for(app).post("/api/audits", content=PRIVATE_TARGET, headers={**JSON, "Origin": origin})
    assert r.status_code == 422 and error_code(r) == "non_public_address"


def test_reads_with_a_foreign_origin_get_no_cors_grant(app):
    r = client_for(app).get("/api/audits", headers={"Origin": "https://attacker.example"})
    assert r.status_code == 200 and "access-control-allow-origin" not in r.headers


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
