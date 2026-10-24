"""Shared fixtures: an offline fixture website and an API client wired to temporary storage."""

from __future__ import annotations

import json
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient  # noqa: E402

from brand_platform.config import Settings  # noqa: E402
from brand_platform.main import create_app  # noqa: E402


class FixtureSite:
    """A small multi-page site whose defects can be switched off to simulate remediation."""

    def __init__(self, delay: float = 0.0):
        self.fixed = False
        self.delay = delay
        self.requests: list[str] = []
        site = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):  # noqa: N802
                site.requests.append(self.path)
                if site.delay:
                    time.sleep(site.delay)
                status, ctype, body = site.render(self.path.split("?")[0])
                payload = body.encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

            def log_message(self, *args):
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.port = self.server.server_address[1]
        self.base = f"http://127.0.0.1:{self.port}"
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    def render(self, path: str):
        base = self.base
        viewport = '<meta name="viewport" content="width=device-width, initial-scale=1">'
        nav = '<header><nav><a href="/">Home</a><a href="/pricing">Pricing</a><a href="/about">About us</a><a href="/blog/launch">Blog</a></nav></header>'
        footer = '<footer><a href="/contact">Contact</a> &copy; 2026 Acme Analytics</footer>'
        if path == "/robots.txt":
            return 200, "text/plain", f"User-agent: *\nDisallow: /private/\nSitemap: {base}/sitemap.xml\n"
        if path == "/sitemap.xml":
            urls = "".join(f"<url><loc>{base}{p}</loc><lastmod>2026-09-01</lastmod></url>" for p in ("/", "/pricing", "/about", "/blog/launch"))
            return 200, "application/xml", f'<?xml version="1.0"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{urls}</urlset>'
        if path == "/":
            org = json.dumps({"@context": "https://schema.org", "@type": "Organization", "name": "Acme Analytics", "url": f"{base}/"})
            return 200, "text/html", (f"<html><head><title>Acme Analytics | Demand forecasting software</title>{viewport}"
                                      f'<script type="application/ld+json">{org}</script></head><body>{nav}'
                                      "<h1>Demand forecasting software for retail teams</h1>"
                                      "<p>Acme Analytics is a software platform that helps retail teams forecast demand.</p>"
                                      '<a href="/signup">Get Started</a>' + footer + "</body></html>")
        if path == "/pricing":
            head = viewport if self.fixed else ""
            ld_price = "49" if self.fixed else "39"
            offer = json.dumps({"@context": "https://schema.org", "@type": "Product", "name": "Acme Pro", "description": "Forecasting",
                                "offers": {"@type": "Offer", "price": ld_price, "priceCurrency": "USD"}})
            return 200, "text/html", (f"<html><head><title>Pricing - Acme Analytics</title>{head}"
                                      f'<script type="application/ld+json">{offer}</script></head><body>{nav}'
                                      "<h1>Simple pricing for growing retail teams</h1><p>Acme Pro costs $49 per month.</p>"
                                      '<a href="/signup">Start free trial</a>' + footer + "</body></html>")
        if path == "/about":
            return 200, "text/html", (f"<html><head><title>About us - Acme Analytics</title>{viewport}</head><body>{nav}"
                                      "<h1>About the Acme Analytics team</h1><p>We are based in Austin, TX. Email hello@acme.example.</p>"
                                      '<a href="/contact">Contact us</a>' + footer + "</body></html>")
        if path == "/blog/launch":
            wall = "" if self.fixed else "<p>" + " ".join(["Forecasting accuracy matters for every retail planner."] * 25) + "</p>"
            return 200, "text/html", (f"<html><head><title>Launch notes - Acme Analytics</title>{viewport}</head><body>{nav}"
                                      f"<h1>Launch notes for the spring forecasting release</h1>{wall}<p>Short summary.</p>"
                                      '<a href="/signup">Get Started</a>' + footer + "</body></html>")
        return 404, "text/plain", "not found"

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *exc):
        self.server.shutdown()
        self.server.server_close()


@pytest.fixture()
def fixture_site():
    with FixtureSite() as site:
        yield site


def make_settings(tmp_path: Path, **overrides) -> Settings:
    values = dict(data_dir=tmp_path / "var", offline_corroboration=True, creation_rate_limit=1000,
                  stage_timeout_seconds=60.0, runtime_limit_seconds=180.0, frontend_dist=tmp_path / "no-dist")
    values.update(overrides)
    return Settings(**values)


class LoopbackPeer:
    """Test-only ASGI shim: Starlette's TestClient always reports client 'testclient', which the
    ExposureGuard correctly rejects. This presents the identity of a real local browser instead."""

    def __init__(self, app, client=("127.0.0.1", 50000)):
        self.app, self.client = app, client

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            scope = dict(scope, client=self.client)
        await self.app(scope, receive, send)


def local_test_client(app, base_url="http://127.0.0.1", **peer) -> TestClient:
    return TestClient(LoopbackPeer(app, **peer), base_url=base_url)


@pytest.fixture()
def make_client(tmp_path):
    clients = []

    def _make(**overrides):
        app = create_app(make_settings(tmp_path, **overrides))
        client = local_test_client(app)
        client.__enter__()
        clients.append(client)
        return client

    yield _make
    for c in clients:
        c.__exit__(None, None, None)


def wait_for_terminal(client, audit_id: str, timeout: float = 150.0) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        audit = client.get(f"/api/audits/{audit_id}").json()
        if audit["status"] not in ("queued", "running"):
            return audit
        time.sleep(0.5)
    raise AssertionError(f"audit {audit_id} did not finish within {timeout}s: {audit}")
