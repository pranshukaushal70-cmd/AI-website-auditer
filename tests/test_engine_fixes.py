#!/usr/bin/env python3
"""Regression tests for the engine defects recorded in docs/PROJECT_AUDIT.md (D1-D8).

Each test names the defect it guards. They use offline fixtures and mocks only, so they
are deterministic and do not touch the network.
"""

import http.client
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]
for p in [
    ROOT / "skills" / "crawl-render-audit" / "scripts",
    ROOT / "skills" / "engagement-audit" / "scripts",
    ROOT / "skills" / "freshness-corroboration" / "scripts",
    ROOT / "skills" / "audit-orchestrator" / "scripts",
]:
    sys.path.insert(0, str(p))

import check_engagement
import check_technical
import check_trust
import compose_report
import run_audit

COMPOSER = ROOT / "skills" / "audit-orchestrator" / "scripts" / "compose_report.py"


def compose(tech=None, trust=None, engagement=None, site="https://example.com"):
    """Run the real composer CLI on in-memory sub-audit dicts and return the report."""
    with tempfile.TemporaryDirectory() as d:
        d = Path(d)
        cmd = [sys.executable, str(COMPOSER), "--site", site, "--output", str(d / "out.json")]
        for name, data in (("technical", tech), ("trust", trust), ("engagement", engagement)):
            if data is not None:
                (d / f"{name}.json").write_text(json.dumps(data), encoding="utf-8")
                cmd += [f"--{name}", str(d / f"{name}.json")]
        subprocess.run(cmd, check=True, capture_output=True, text=True)
        return json.loads((d / "out.json").read_text(encoding="utf-8"))


CLEAN_TECH = {"robots_txt": {"status": "found", "sitemaps": ["https://example.com/sitemap.xml"]},
              "crawler_block": {"status": "pass", "evidence": "ok"},
              "viewport_check": {"status": "pass", "evidence": "ok"},
              "structured_data": {"status": "pass", "evidence": "ok"},
              "crawl_scope": {"pages_successfully_crawled": 2}}
CLEAN_TRUST = {"copyright": {"status": "pass", "evidence": "ok"},
               "multi_signal_freshness": {"status": "pass", "evidence": "ok"},
               "eeat_check": {"status": "pass", "evidence": "ok"}}
CLEAN_ENG = {"h1_audit": {"status": "pass", "evidence": "ok"},
             "readability": {"status": "pass", "evidence": "ok"},
             "navigation_cta": {"status": "pass", "evidence": "ok"}}
UNAVAILABLE = {"status": "unavailable", "evidence": "Page fetch failed."}


class TestReadinessIndex(unittest.TestCase):
    def test_d1_proactive_suggestions_do_not_reduce_readiness(self):
        """D1: a report containing only proactive suggestions scores 100 in every dimension."""
        report = compose(CLEAN_TECH, CLEAN_TRUST, CLEAN_ENG)
        self.assertEqual(report["summary"]["total_findings"], 0)
        self.assertEqual(report["summary"]["proactive_suggestions_count"], 3)
        self.assertEqual(report["readiness"]["dimensions"], {"technical": 100.0, "trust": 100.0, "engagement": 100.0})
        self.assertEqual(report["readiness"]["score"], 100.0)

    def test_d1_defects_still_reduce_readiness(self):
        tech = dict(CLEAN_TECH, viewport_check={"status": "warning", "evidence": "no viewport", "confidence": 1.0})
        report = compose(tech, CLEAN_TRUST, CLEAN_ENG)
        self.assertEqual(report["readiness"]["dimensions"]["technical"], 93.0)


class TestAffectedPages(unittest.TestCase):
    def test_d2_engagement_findings_keep_page_level_affected_urls(self):
        eng = dict(CLEAN_ENG, readability={"status": "warning", "evidence": "wall of text",
                                           "affected_pages": ["https://example.com/article"]})
        report = compose(CLEAN_TECH, CLEAN_TRUST, eng)
        f = next(x for x in report["findings"] if x["title"].startswith("Poor text readability"))
        self.assertEqual(f["affected_pages"], ["https://example.com/article"])

    def test_d2_trust_findings_keep_page_level_affected_urls(self):
        trust = dict(CLEAN_TRUST, eeat_check={"status": "warning", "evidence": "no author",
                                              "affected_pages": ["https://example.com/blog/post"]})
        report = compose(CLEAN_TECH, trust, CLEAN_ENG)
        f = next(x for x in report["findings"] if "E-E-A-T" in x["title"])
        self.assertEqual(f["affected_pages"], ["https://example.com/blog/post"])

    def test_d2_falls_back_to_site_url_when_no_pages_reported(self):
        eng = dict(CLEAN_ENG, h1_audit={"status": "fail", "severity": "high", "evidence": "no h1"})
        report = compose(CLEAN_TECH, CLEAN_TRUST, eng)
        f = next(x for x in report["findings"] if "H1" in x["title"])
        self.assertEqual(f["affected_pages"], ["https://example.com"])


class TestUnavailableChecks(unittest.TestCase):
    def test_d3_unfetchable_engagement_is_not_reported_clean(self):
        eng = {k: dict(UNAVAILABLE) for k in ("h1_audit", "readability", "navigation_cta", "answerability",
                                              "deep_link_context", "clutter")}
        report = compose(CLEAN_TECH, CLEAN_TRUST, eng)
        self.assertTrue(report["execution"]["partial"])
        self.assertIn("engagement", report["execution"]["unavailable_categories"])
        self.assertFalse(any(f["category"] == "engagement" and f.get("proactive") for f in report["findings"]))
        self.assertTrue(any(c["category"] == "engagement" and c["check"] == "h1_audit"
                            for c in report["execution"]["unavailable_checks"]))

    def test_d3_unfetchable_trust_is_not_reported_clean(self):
        trust = {"copyright": dict(UNAVAILABLE), "multi_signal_freshness": dict(UNAVAILABLE),
                 "eeat_check": dict(UNAVAILABLE)}
        report = compose(CLEAN_TECH, trust, CLEAN_ENG)
        self.assertIn("trust", report["execution"]["unavailable_categories"])
        self.assertFalse(any(f["category"] == "trust" and f.get("proactive") for f in report["findings"]))

    def test_d3_network_failure_is_not_reported_clean_technical(self):
        tech = {"robots_txt": {"status": "not_found"},
                "crawler_block": {"status": "unavailable", "evidence": "no response"},
                "structured_data": dict(UNAVAILABLE), "viewport_check": dict(UNAVAILABLE),
                "faq_schema_check": dict(UNAVAILABLE), "locked_content": dict(UNAVAILABLE)}
        report = compose(tech, CLEAN_TRUST, CLEAN_ENG)
        self.assertIn("technical", report["execution"]["unavailable_categories"])
        self.assertFalse(any(f["category"] == "technical" and f.get("proactive") for f in report["findings"]))

    def test_d3_single_unavailable_check_does_not_mark_partial(self):
        """Render being unavailable is listed but does not make the whole report partial."""
        tech = dict(CLEAN_TECH, js_render_gap={"status": "unavailable", "evidence": "no browser"})
        report = compose(tech, CLEAN_TRUST, CLEAN_ENG)
        self.assertFalse(report["execution"]["partial"])
        self.assertEqual(report["execution"]["unavailable_categories"], [])
        self.assertTrue(any(c["check"] == "js_render_gap" for c in report["execution"]["unavailable_checks"]))

    def test_d3_failed_pages_are_listed(self):
        eng = dict(CLEAN_ENG, page_reports=[{"url": "https://example.com/", "status": "pass"},
                                            {"url": "https://example.com/broken", "status": "unavailable"}])
        tech = dict(CLEAN_TECH, crawl_scope={"pages_successfully_crawled": 1, "pages_failed": 1,
                                             "failed_urls": ["https://example.com/gone"]})
        report = compose(tech, CLEAN_TRUST, eng)
        self.assertIn("https://example.com/broken", report["execution"]["failed_pages"])
        self.assertIn("https://example.com/gone", report["execution"]["failed_pages"])

    def test_d3_multi_page_trust_keeps_execution_errors(self):
        def failing_fetch(url):
            msg = check_trust._record_execution_error(f"Page fetch blocked/failed for {url}", OSError("boom"))
            return f"Error: {msg}", None
        with patch.object(check_trust, "fetch_page_with_headers", side_effect=failing_fetch), \
                patch.object(check_trust, "robots_allows", return_value=(True, "")):
            out = check_trust.analyze_trust_pages(["https://example.com/", "https://example.com/a"],
                                                  current_year=2026, primary_external=lambda _b: [])
        self.assertTrue(out["execution"]["partial"])
        self.assertEqual(len(out["execution"]["errors"]), 2)


class TestScopeMetadata(unittest.TestCase):
    def _robots_disallow_fetch(self, url, **kwargs):
        if url.endswith("/robots.txt"):
            return 200, "User-agent: *\nDisallow: /\n", {}
        raise AssertionError(f"Fetched {url} although robots.txt disallows it")

    def test_d4_sitemap_not_checked_when_robots_aborts_crawl(self):
        tech = check_technical.analyze_technical("https://example.com/", fetch_fn=self._robots_disallow_fetch)
        self.assertFalse(tech["sitemap"]["checked"])
        report = compose(tech, CLEAN_TRUST, CLEAN_ENG)
        self.assertFalse(report["scope"]["sitemap_checked"])
        self.assertFalse(report["scope"]["sitemap_found"])

    def test_d4_legacy_technical_json_keeps_old_behaviour(self):
        report = compose(CLEAN_TECH, CLEAN_TRUST, CLEAN_ENG)
        self.assertTrue(report["scope"]["sitemap_checked"])


def _fake_site_fetch(url, **kwargs):
    if url.endswith("/robots.txt"):
        return 404, "", {}
    if url.rstrip("/") in ("https://example.com", "https://example.com/about"):
        html = ("<html><head><title>Example Co</title><meta name='viewport' content='width=device-width'></head>"
                "<body><h1>Example Co builds tools</h1><a href='/about'>About us</a></body></html>")
        return 200, html, {"_final_url": url, "_redirect_chain": []}
    return 404, "", {}


class TestRendering(unittest.TestCase):
    def _install_fake_playwright(self, goto_side_effect):
        fake = MagicMock()
        page = fake.sync_playwright.return_value.__enter__.return_value.chromium.launch.return_value \
            .new_context.return_value.new_page.return_value
        page.goto.side_effect = goto_side_effect
        sys.modules["playwright"] = fake
        sys.modules["playwright.sync_api"] = fake
        return fake

    def tearDown(self):
        sys.modules.pop("playwright", None)
        sys.modules.pop("playwright.sync_api", None)
        os.environ.pop("BRAND_AUDIT_DISABLE_RENDER", None)

    def test_d5_one_render_failure_does_not_abort_rendering(self):
        os.environ.pop("BRAND_AUDIT_DISABLE_RENDER", None)
        self._install_fake_playwright(RuntimeError("navigation boom"))
        tech = check_technical.analyze_technical("https://example.com/", max_crawl_pages=2, fetch_fn=_fake_site_fetch)
        ev = tech["js_render_gap"]["evidence"]
        self.assertIn("Render failed for https://example.com/", ev)
        self.assertNotIn("js_ev", ev)

    def test_d6_render_can_be_disabled_by_environment(self):
        os.environ["BRAND_AUDIT_DISABLE_RENDER"] = "1"
        fake = self._install_fake_playwright(None)
        tech = check_technical.analyze_technical("https://example.com/", max_crawl_pages=2, fetch_fn=_fake_site_fetch)
        self.assertEqual(tech["js_render_gap"]["status"], "unavailable")
        self.assertIn("disabled", tech["js_render_gap"]["evidence"].lower())
        fake.sync_playwright.assert_not_called()
        _, _, err = check_engagement.render_engagement_metrics("https://example.com/")
        self.assertIn("disabled", err.lower())


class TestPublicAddressRule(unittest.TestCase):
    BLOCKED = ["http://100.64.0.1/", "http://[2002:7f00:1::]/", "http://[2002:a00:1::]/",
               "http://[2001:0:4136:e378:8000:63bf:3fff:fdd2]/", "http://[64:ff9b::a00:1]/",
               "http://127.0.0.1/", "http://169.254.169.254/", "http://[::ffff:10.0.0.1]/",
               "http://192.168.1.1:8080/", "http://[fe80::1]/", "http://240.0.0.1/"]
    ALLOWED = ["http://8.8.8.8/", "http://[2606:4700:4700::1111]/", "http://[64:ff9b::808:808]/"]

    def test_d7_validators_block_non_public_addresses_in_every_skill(self):
        os.environ.pop("BRAND_AUDIT_LOCAL_FIXTURE", None)
        for module in (check_technical, check_trust, check_engagement):
            for url in self.BLOCKED:
                with self.subTest(module=module.__name__, url=url):
                    with self.assertRaises(ValueError):
                        module._validate_public_http_url(url)
            for url in self.ALLOWED:
                with self.subTest(module=module.__name__, url=url):
                    self.assertTrue(module._validate_public_http_url(url))


def _offline_public_dns():
    """Deterministic, offline DNS for example.com: a fixed public address (93.184.215.14), so URL validation still
    applies its real public-address rule without a network lookup. Anything else is refused as unresolvable."""
    import socket

    def fake(host, port, family=0, type=0, proto=0, flags=0):
        if str(host).lower() == "example.com":
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.215.14", port or 0))]
        raise socket.gaierror(f"offline test DNS: {host} is not resolvable")
    return patch("socket.getaddrinfo", side_effect=fake)


def _http_error(code):
    return urllib.error.HTTPError("https://example.com/x", code, "err", {}, None)


class TestErrorLabelling(unittest.TestCase):
    def setUp(self):
        check_trust.EXECUTION_ERRORS.clear()
        check_engagement.EXECUTION_ERRORS.clear()

    def test_d8_missing_sitemap_is_not_an_execution_error(self):
        # Patch target changed (security phase 6, approved option A) from urllib.request.urlopen: the sitemap is now
        # fetched through the redirect-validating opener; OpenerDirector.open intercepts it offline.
        with _offline_public_dns(), patch("urllib.request.OpenerDirector.open", side_effect=_http_error(404)):
            self.assertIsNone(check_trust.fetch_sitemap_lastmod("https://example.com"))
        self.assertEqual(check_trust.EXECUTION_ERRORS, [])

    def test_d8_sitemap_failure_is_not_labelled_as_corroboration(self):
        with _offline_public_dns(), patch("urllib.request.OpenerDirector.open", side_effect=_http_error(500)):  # option A, see above
            check_trust.fetch_sitemap_lastmod("https://example.com")
        self.assertTrue(check_trust.EXECUTION_ERRORS)
        self.assertNotIn("Wikipedia", check_trust.EXECUTION_ERRORS[0])
        self.assertIn("sitemap", check_trust.EXECUTION_ERRORS[0].lower())

    def test_missing_robots_txt_is_allowed_without_error(self):
        # Patch target changed (security phase 3, approved option A) from urllib.request.urlopen: robots.txt is now
        # fetched through a redirect-validating opener, and OpenerDirector.open intercepts both paths offline.
        # _offline_public_dns (phase 6): URL validation resolves DNS before connecting; without it this test made a
        # real lookup of example.com (a hidden network dependency since phase 3).
        with _offline_public_dns(), patch("urllib.request.OpenerDirector.open", side_effect=_http_error(404)):
            allowed, _ = check_trust.robots_allows("https://example.com/")
            self.assertTrue(allowed)
            self.assertTrue(check_engagement.robots_allows("https://example.com/"))
        self.assertEqual(check_trust.EXECUTION_ERRORS, [])
        self.assertEqual(check_engagement.EXECUTION_ERRORS, [])


class TestExternalCorroboration(unittest.TestCase):
    PAGES = {u: f"<html><head><title>Acme</title></head><body><p>Page {i}</p><a href='/contact'>Contact</a></body></html>"
             for i, u in enumerate(["https://acme.example/", "https://acme.example/a", "https://acme.example/b"])}

    def tearDown(self):
        os.environ.pop("BRAND_AUDIT_OFFLINE", None)

    def test_d12_external_apis_are_queried_once_for_multi_page_trust(self):
        with patch.object(check_trust, "fetch_page_with_headers", side_effect=lambda u: (self.PAGES[u], None)), \
                patch.object(check_trust, "robots_allows", return_value=(True, "")), \
                patch.object(check_trust, "fetch_sitemap_lastmod", return_value=None), \
                patch.object(check_trust, "check_external_apis", return_value=[]) as external:
            out = check_trust.analyze_trust_pages(list(self.PAGES), current_year=2026)
        self.assertEqual(out["pages_checked"], 3)
        self.assertEqual(external.call_count, 1)

    def test_offline_mode_marks_corroboration_unavailable_not_pass(self):
        os.environ["BRAND_AUDIT_OFFLINE"] = "1"
        with patch.object(check_trust, "fetch_sitemap_lastmod", return_value=None), \
                patch("urllib.request.urlopen", side_effect=AssertionError("network used in offline mode")):
            r = check_trust.analyze_trust(self.PAGES["https://acme.example/"], "https://acme.example/", current_year=2026)
        self.assertEqual(r["corroboration_check"]["status"], "unavailable")
        self.assertIn("offline", r["corroboration_check"]["evidence"].lower())
        report = compose(CLEAN_TECH, r, CLEAN_ENG)
        self.assertEqual(report["scope"]["external_sources_checked"], 0)
        self.assertTrue(any(c["check"] == "corroboration_check" for c in report["execution"]["unavailable_checks"]))


class TestTrustRobotsGate(unittest.TestCase):
    def test_d13_multi_page_trust_respects_robots_disallow(self):
        """robots_allows returns a (allowed, url) tuple; a truthiness check let every page through."""
        with patch.object(check_trust, "robots_allows", return_value=(False, "https://example.com/robots.txt")), \
                patch.object(check_trust, "fetch_page_with_headers",
                             side_effect=AssertionError("fetched a robots-disallowed page")) as fetch:
            out = check_trust.analyze_trust_pages(["https://example.com/", "https://example.com/a"], current_year=2026)
        fetch.assert_not_called()
        self.assertTrue(all(r["status"] == "unavailable" for r in out["page_reports"]))
        self.assertIn("robots.txt", out["page_reports"][0]["multi_signal_freshness"]["evidence"])


class TestPortedDeadTests(unittest.TestCase):
    """Working versions of the two functions in test_round3_polish.py that were never collected."""

    def test_composer_marks_missing_subaudit_as_partial(self):
        with tempfile.TemporaryDirectory() as td:
            tech = Path(td) / "technical.json"
            tech.write_text(json.dumps({"robots_txt": {}, "crawl_scope": {"pages_successfully_crawled": 1},
                                        "js_render_gap": {"status": "unavailable"}}), encoding="utf-8")
            result = subprocess.run([sys.executable, str(COMPOSER), "--site", "https://example.com",
                                     "--technical", str(tech), "--trust", str(Path(td) / "missing-trust.json"),
                                     "--output", str(Path(td) / "report.json")], text=True, capture_output=True)
            self.assertEqual(result.returncode, 0)
            report = json.loads((Path(td) / "report.json").read_text(encoding="utf-8"))
            self.assertTrue(report["execution"]["partial"])
            self.assertIn("trust", report["execution"]["missing_categories"])
            self.assertFalse(any(f.get("category") == "trust" and f.get("proactive") for f in report["findings"]))

    def test_network_failure_is_unavailable_not_antibot(self):
        def no_response(url, **kwargs):
            return 0, "temporary dns failure", {"_error": "Temporary failure in name resolution"}
        result = check_technical.analyze_technical("https://example.com", fetch_fn=no_response)
        self.assertEqual(result["crawler_block"]["status"], "unavailable")
        self.assertNotIn("anti-bot", result["crawler_block"]["evidence"].lower())


def _http_message(header_lines, url):
    """Headers exactly as check_technical.fetch_url returns them: response.info() plus two private keys."""
    import email
    import http.client
    message = email.message_from_string("".join(f"{line}\n" for line in header_lines) + "\n", _class=http.client.HTTPMessage)
    message["_final_url"] = url
    message["_redirect_chain"] = []
    return message


class TestXRobotsTagHeader(unittest.TestCase):
    """D14: X-Robots-Tag was read only from dict headers, so live HTTPMessage headers were never checked."""

    URL = "https://example.com/"
    PAGE = ("<html><head><title>Example Co</title><meta name='viewport' content='width=device-width'></head>"
            "<body><h1>Example Co builds forecasting tools</h1></body></html>")

    def setUp(self):
        self._render = os.environ.get("BRAND_AUDIT_DISABLE_RENDER")
        os.environ["BRAND_AUDIT_DISABLE_RENDER"] = "1"

    def tearDown(self):
        if self._render is None:
            os.environ.pop("BRAND_AUDIT_DISABLE_RENDER", None)
        else:
            os.environ["BRAND_AUDIT_DISABLE_RENDER"] = self._render

    def _indexability(self, headers):
        def fetch(url, **kwargs):
            if url.endswith("/robots.txt"):
                return 404, "", {}
            if url.rstrip("/") == self.URL.rstrip("/"):
                return 200, self.PAGE, headers
            return 404, "", {}
        return check_technical.analyze_technical(self.URL, max_crawl_pages=1, fetch_fn=fetch)["indexability_check"]

    def test_header_noindex_is_detected_with_production_headers(self):
        check = self._indexability(_http_message(["X-Robots-Tag: noindex"], self.URL))
        self.assertEqual(check["status"], "fail")
        self.assertEqual(check["affected_pages"], [self.URL])
        self.assertIn("X-Robots-Tag contains noindex", check["evidence"])

    def test_index_follow_passes(self):
        self.assertEqual(self._indexability(_http_message(["X-Robots-Tag: index, follow"], self.URL))["status"], "pass")

    def test_lowercase_header_name_is_detected(self):
        self.assertEqual(self._indexability(_http_message(["x-robots-tag: noindex"], self.URL))["status"], "fail")
        self.assertEqual(self._indexability({"x-robots-tag": "noindex", "_final_url": self.URL, "_redirect_chain": []})["status"], "fail")

    def test_noindex_in_second_repeated_header_is_detected(self):
        check = self._indexability(_http_message(["X-Robots-Tag: otherbot: noarchive", "X-Robots-Tag: noindex"], self.URL))
        self.assertEqual(check["status"], "fail")
        self.assertIn("noarchive", check["evidence"])  # both values are reported, in order
        self.assertIn("noindex", check["evidence"])

    def test_existing_dict_header_behaviour_is_unchanged(self):
        self.assertEqual(self._indexability({"X-Robots-Tag": "noindex", "_final_url": self.URL, "_redirect_chain": []})["status"], "fail")
        self.assertEqual(self._indexability({"X-Robots-Tag": "index", "_final_url": self.URL, "_redirect_chain": []})["status"], "pass")
        self.assertEqual(self._indexability({"_final_url": self.URL, "_redirect_chain": []})["status"], "pass")

    def test_response_without_the_header_passes(self):
        self.assertEqual(self._indexability(_http_message(["Content-Type: text/html"], self.URL))["status"], "pass")

    def test_header_values_helper_edge_cases(self):
        message = _http_message(["X-Robots-Tag: a", "x-robots-tag: b"], self.URL)
        self.assertEqual(check_technical.header_values(message, "X-ROBOTS-TAG"), ["a", "b"])
        self.assertEqual(check_technical.header_values({"X-Robots-Tag": ["a", "noindex"]}, "x-robots-tag"), ["a", "noindex"])
        self.assertEqual(check_technical.header_values({"X-Robots-Tag": None}, "X-Robots-Tag"), [])
        self.assertEqual(check_technical.header_values(None, "X-Robots-Tag"), [])
        self.assertEqual(check_technical.header_values("not headers", "X-Robots-Tag"), [])


def _hop(src, dst, status=301):
    return {"from": src, "to": dst, "status": status}


class TestRedirectChainHeaders(unittest.TestCase):
    """D15: analyze_redirect_chain read the chain only from dict headers, so live HTTPMessage chains were lost."""

    START = "https://example.com/start"

    def _message(self, final_url, chain, server_lines=()):
        message = _http_message(list(server_lines), self.START)  # appends _final_url=START, _redirect_chain=[]
        del message["_final_url"]
        del message["_redirect_chain"]
        message["_final_url"] = final_url
        message["_redirect_chain"] = chain
        return message

    def _both(self, final_url, chain):
        live = check_technical.analyze_redirect_chain(self.START, self._message(final_url, chain))
        mock = check_technical.analyze_redirect_chain(self.START, {"_final_url": final_url, "_redirect_chain": chain})
        self.assertEqual(live, mock, "production and dict headers must give the same analysis")
        return live

    def test_zero_hops(self):
        r = self._both(self.START, [])
        self.assertEqual((r["status"], r["hops"], r["final_url"], r["cross_domain"]), ("pass", 0, self.START, False))

    def test_one_same_host_hop_passes(self):
        r = self._both("https://example.com/home", [_hop(self.START, "https://example.com/home")])
        self.assertEqual((r["status"], r["hops"], r["final_url"]), ("pass", 1, "https://example.com/home"))

    def test_three_hops_warn(self):
        chain = [_hop(self.START, "https://example.com/a"), _hop("https://example.com/a", "https://example.com/b", 302),
                 _hop("https://example.com/b", "https://example.com/c")]
        r = self._both("https://example.com/c", chain)
        self.assertEqual((r["status"], r["hops"]), ("warning", 3))
        self.assertIn("longer than two hops", r["evidence"])

    def test_cross_host_hop_warns(self):
        r = self._both(self.START, [_hop(self.START, "https://other.example/landing", 302)])
        self.assertEqual((r["status"], r["hops"]), ("warning", 1))
        self.assertIn("crosses to a different host", r["evidence"])

    def test_server_sent_private_headers_cannot_override_engine_values(self):
        spoofed = self._message("https://example.com/c", [_hop(self.START, "https://example.com/c")],
                                server_lines=["_final_url: https://spoof.example/", "_redirect_chain: not-a-list"])
        r = check_technical.analyze_redirect_chain(self.START, spoofed)
        self.assertEqual((r["final_url"], r["hops"]), ("https://example.com/c", 1))

    def test_missing_or_unusable_headers_mean_no_chain(self):
        for headers in (None, "not headers", {}, _http_message([], self.START)):
            r = check_technical.analyze_redirect_chain(self.START, headers)
            self.assertEqual((r["status"], r["hops"], r["final_url"]), ("pass", 0, self.START))


class TestRedirectChainLiveFetch(unittest.TestCase):
    """D15 end to end: real sockets, real fetch_url redirect handling, real HTTPMessage headers.

    Also guards the redirect safety controls the fix must not weaken: cross-host redirects are recorded
    but not followed, private targets are refused before any connection, and redirect runs are capped.
    """

    def setUp(self):
        import threading
        from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
        self.requested = []
        routes = {"/zero": None, "/one": "/zero", "/three-a": "/three-b", "/three-b": "/three-c", "/three-c": "/zero"}
        test = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):  # noqa: N802
                test.requested.append(self.path)
                port = self.server.server_address[1]
                target = routes.get(self.path, "missing")
                if self.path == "/cross":
                    target = f"http://localhost:{port}/zero"
                elif self.path == "/private":
                    target = "http://10.0.0.1/admin"
                elif self.path.startswith("/run-"):
                    target = f"/run-{int(self.path[5:]) + 1}"
                if target == "missing":
                    self.send_response(404)
                    self.end_headers()
                    return
                if target is None:
                    body = b"<html><body><h1>Landing page for redirect tests</h1></body></html>"
                    self.send_response(200)
                    self.send_header("Content-Type", "text/html; charset=utf-8")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                    return
                self.send_response(302 if self.path in ("/three-b", "/cross", "/private") else 301)
                self.send_header("Location", target)
                self.send_header("Content-Length", "0")
                self.end_headers()

            def log_message(self, *args):
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.port = self.server.server_address[1]
        self.base = f"http://127.0.0.1:{self.port}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self._fixture = os.environ.get("BRAND_AUDIT_LOCAL_FIXTURE")
        os.environ["BRAND_AUDIT_LOCAL_FIXTURE"] = str(self.port)  # the engine's existing test-only localhost allowance

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        if self._fixture is None:
            os.environ.pop("BRAND_AUDIT_LOCAL_FIXTURE", None)
        else:
            os.environ["BRAND_AUDIT_LOCAL_FIXTURE"] = self._fixture

    def _fetch_and_analyse(self, path):
        url = self.base + path
        status, _, headers = check_technical.fetch_url(url)
        return status, headers, check_technical.analyze_redirect_chain(url, headers)

    def test_live_zero_one_and_three_hops(self):
        status, headers, r = self._fetch_and_analyse("/zero")
        self.assertIsInstance(headers, http.client.HTTPMessage)
        self.assertEqual((status, r["status"], r["hops"]), (200, "pass", 0))
        status, _, r = self._fetch_and_analyse("/one")
        self.assertEqual((status, r["status"], r["hops"], r["final_url"]), (200, "pass", 1, self.base + "/zero"))
        status, _, r = self._fetch_and_analyse("/three-a")
        self.assertEqual((status, r["status"], r["hops"], r["final_url"]), (200, "warning", 3, self.base + "/zero"))
        self.assertEqual([h["status"] for h in r["chain"]], [301, 302, 301])

    def test_live_cross_host_redirect_is_reported_and_not_followed(self):
        self.requested.clear()
        status, _, r = self._fetch_and_analyse("/cross")
        self.assertEqual(status, 302)  # the handler refuses to follow a cross-host hop
        self.assertEqual(self.requested, ["/cross"])  # nothing was fetched from the other host
        self.assertEqual((r["status"], r["hops"]), ("warning", 1))
        self.assertIn("crosses to a different host", r["evidence"])

    def test_live_redirect_to_private_address_is_refused(self):
        self.requested.clear()
        status, body, headers = check_technical.fetch_url(self.base + "/private")
        self.assertEqual(status, 0)
        self.assertIn("10.0.0.1", body)  # the validation error names the blocked target
        self.assertEqual(self.requested, ["/private"])

    def test_live_redirect_runs_are_capped(self):
        status, _, _ = check_technical.fetch_url(self.base + "/run-0")
        self.assertNotEqual(status, 200)
        self.assertLessEqual(len(self.requested), 12)  # urllib's HTTPRedirectHandler.max_redirections (10) still applies


class TestRobotsFailureHandling(unittest.TestCase):
    """Security phase 3 / D11: robots.txt failures never become permission to crawl, in all three stages.

    Real sockets, the real fetchers (fetch_url for technical, the new validated opener for trust/engagement),
    and the engine's existing test-only localhost allowance for the fixture port.
    """

    def setUp(self):
        import contextlib
        import io
        import socket
        import threading
        from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
        self.requests = []
        self.robots = (200, {}, "User-agent: *\nAllow: /\n", 0.0)  # (status, headers, body, delay seconds)
        test = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):  # noqa: N802
                test.requests.append((self.headers.get("Host"), self.path))
                if self.path == "/robots.txt":
                    status, headers, body, delay = test.robots
                    if delay:
                        time.sleep(delay)
                elif self.path == "/real-robots.txt":
                    status, headers, body = 200, {}, "User-agent: *\nDisallow: /private/\n"
                else:
                    status, headers, body = 200, {"Content-Type": "text/html"}, "<html><body><h1>Fixture page for robots tests</h1></body></html>"
                data = body.encode()
                try:
                    self.send_response(status)
                    for k, v in headers.items():
                        self.send_header(k, v)
                    self.send_header("Content-Length", str(len(data)))
                    self.end_headers()
                    self.wfile.write(data)
                except OSError:
                    pass  # the client gave up (timeout scenario)

            def log_message(self, *args):
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.port = self.server.server_address[1]
        self.base = f"http://127.0.0.1:{self.port}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        with socket.socket() as s:  # a port with nothing listening, for the network-failure case
            s.bind(("127.0.0.1", 0))
            self.closed_port = s.getsockname()[1]
        self._saved = os.environ.get("BRAND_AUDIT_LOCAL_FIXTURE")
        os.environ["BRAND_AUDIT_LOCAL_FIXTURE"] = str(self.port)
        os.environ["BRAND_AUDIT_DISABLE_RENDER"] = "1"
        for m in (check_technical, check_trust, check_engagement):
            m._LOCAL_FIXTURE_WARNED = True  # keep test output readable; the warning is covered elsewhere
        for m in (check_trust, check_engagement):
            m.ROBOTS_UNREACHABLE.clear()
            m.EXECUTION_ERRORS.clear()
        self._quiet = contextlib.redirect_stderr(io.StringIO())
        self._quiet.__enter__()

    def tearDown(self):
        self._quiet.__exit__(None, None, None)
        self.server.shutdown()
        self.server.server_close()
        os.environ.pop("BRAND_AUDIT_DISABLE_RENDER", None)
        if self._saved is None:
            os.environ.pop("BRAND_AUDIT_LOCAL_FIXTURE", None)
        else:
            os.environ["BRAND_AUDIT_LOCAL_FIXTURE"] = self._saved
        for m in (check_technical, check_trust, check_engagement):
            m._LOCAL_FIXTURE_WARNED = False

    def decisions(self, base=None, technical_fetch=None):
        """Robots verdict from each stage for base/ : technical (status, allowed), trust allowed, engagement allowed."""
        base = base or self.base
        tech = check_technical.evaluate_robots_txt(base, base + "/", fetch_fn=technical_fetch)
        trust_allowed, _ = check_trust.robots_allows(base + "/")
        return (tech["status"], tech["audit_crawler_allowed"]), trust_allowed, check_engagement.robots_allows(base + "/")

    def page_requests(self):
        return [p for _, p in self.requests if p not in ("/robots.txt", "/real-robots.txt")]

    def assert_unreachable(self, base=None, technical_fetch=None, reason_fragment=""):
        tech, trust_ok, eng_ok = self.decisions(base, technical_fetch)
        self.assertEqual(tech, ("unreachable", False))
        self.assertFalse(trust_ok)
        self.assertFalse(eng_ok)
        for m in (check_trust, check_engagement):
            reason = " ".join(m.ROBOTS_UNREACHABLE.values())
            self.assertIn(reason_fragment, reason, m.__name__)
        self.assertEqual(self.page_requests(), [])

    def test_200_rules_are_parsed(self):
        self.assertEqual(self.decisions(), (("found", True), True, True))
        self.robots = (200, {}, "User-agent: *\nDisallow: /\n", 0.0)
        self.assertEqual(self.decisions(), (("found", False), False, False))
        self.assertEqual(check_trust.ROBOTS_UNREACHABLE, {})  # disallowed is not the same as unreachable

    def test_same_host_redirect_is_followed_and_parsed(self):
        self.robots = (301, {"Location": "/real-robots.txt"}, "", 0.0)
        self.assertEqual(self.decisions(), (("found", True), True, True))
        self.assertIn("/real-robots.txt", [p for _, p in self.requests])

    def test_ordinary_4xx_means_no_restrictions(self):
        for code in (404, 403, 410):
            self.robots = (code, {}, "missing", 0.0)
            self.assertEqual(self.decisions(), (("not_found", True), True, True), code)
        self.assertEqual(check_trust.EXECUTION_ERRORS + check_engagement.EXECUTION_ERRORS, [])

    def test_429_is_unreachable(self):
        self.robots = (429, {"Retry-After": "60"}, "slow down", 0.0)
        self.assert_unreachable(reason_fragment="HTTP 429")

    def test_5xx_is_unreachable(self):
        for code in (500, 503):
            for m in (check_trust, check_engagement):
                m.ROBOTS_UNREACHABLE.clear()
            self.robots = (code, {}, "down", 0.0)
            self.assert_unreachable(reason_fragment=f"HTTP {code}")
        self.assertTrue(any("robots.txt unreachable" in e for e in check_trust.EXECUTION_ERRORS))

    def test_network_failure_is_unreachable(self):
        os.environ["BRAND_AUDIT_LOCAL_FIXTURE"] = str(self.closed_port)
        self.assert_unreachable(base=f"http://127.0.0.1:{self.closed_port}", reason_fragment="no HTTP response")

    def test_timeout_is_unreachable(self):
        self.robots = (200, {}, "User-agent: *\nAllow: /\n", 6.0)  # longer than the 5 s robots timeout in trust/engagement
        quick = lambda u: check_technical.fetch_url(u, timeout=1)  # noqa: E731 - real fetch_url, shorter timeout
        started = time.monotonic()
        self.assert_unreachable(technical_fetch=quick, reason_fragment="no HTTP response")
        # 1 s (technical) + 5 s (trust) + 5 s (engagement): proves the clients really waited and timed out,
        # rather than the server dropping the connection.
        self.assertGreaterEqual(time.monotonic() - started, 10.5)
        self.assertTrue(any("timed out" in e.lower() for e in check_trust.EXECUTION_ERRORS), check_trust.EXECUTION_ERRORS)

    def test_cross_host_redirect_is_unreachable_and_not_followed(self):
        self.robots = (302, {"Location": f"http://localhost:{self.port}/robots.txt"}, "", 0.0)
        self.assert_unreachable(reason_fragment="HTTP 302 redirect that was not followed")
        self.assertTrue(all(host.startswith("127.0.0.1") for host, _ in self.requests), self.requests)

    def test_unsafe_redirect_target_is_refused_and_unreachable(self):
        self.robots = (302, {"Location": "http://10.0.0.1/robots.txt"}, "", 0.0)
        self.assert_unreachable(reason_fragment="no HTTP response")
        self.assertTrue(any("10.0.0.1" in e for e in check_trust.EXECUTION_ERRORS + check_engagement.EXECUTION_ERRORS))

    def test_unreachable_robots_fetches_no_pages_and_composes_a_partial_report(self):
        self.robots = (503, {}, "down", 0.0)
        url = self.base + "/"
        tech = check_technical.analyze_technical(url, max_crawl_pages=3)
        trust = check_trust.analyze_trust_pages([url, self.base + "/about"], current_year=2026)
        engagement = check_engagement.analyze_engagement_pages([url, self.base + "/about"])
        self.assertEqual(self.page_requests(), [], "no page may be fetched when robots.txt is unreachable")
        self.assertEqual((tech["robots_txt"]["status"], tech["crawler_block"]["status"]), ("unreachable", "unavailable"))
        self.assertIn("RFC 9309", tech["crawler_block"]["evidence"])
        for r in trust["page_reports"] + engagement["page_reports"]:
            self.assertEqual(r["status"], "unavailable")
        self.assertIn("could not be retrieved (HTTP 503)", trust["page_reports"][0]["eeat_check"]["evidence"])
        self.assertIn("could not be retrieved (HTTP 503)", engagement["page_reports"][0]["h1_audit"]["evidence"])
        report = compose(tech, trust, engagement, site=url)
        titles = {f["title"] for f in report["findings"]}
        self.assertTrue(report["execution"]["partial"])
        self.assertIn("technical", report["execution"]["unavailable_categories"])
        self.assertNotIn("HTTP requests blocked by anti-bot measures", titles)  # not a false crawler-blocking defect
        self.assertNotIn("Robots.txt blocks all crawlers from root", titles)
        self.assertNotIn("No XML Sitemap declared in robots.txt", titles)
        self.assertFalse(any(f.get("proactive") for f in report["findings"] if f.get("category") == "technical"))

    def test_classifier_table(self):
        expected = {200: "parse", 204: "parse", 404: "unavailable", 401: "unavailable", 403: "unavailable", 451: "unavailable",
                    429: "unreachable", 500: "unreachable", 503: "unreachable", 0: "unreachable", 301: "unreachable", 302: "unreachable"}
        for code, decision in expected.items():
            self.assertEqual(check_technical.classify_robots_status(code), decision, code)
            self.assertEqual(check_trust._classify_robots_status(code), decision, code)
            self.assertEqual(check_engagement._classify_robots_status(code), decision, code)


class TestExternalCorroborationConsent(unittest.TestCase):
    """Security phase 4: opt-out sends nothing; outages are unavailable (never pass); responses are size-capped."""

    HTML = ("<html><head><title>Acme Analytics | Forecasting</title></head><body><h1>Acme Analytics</h1>"
            "<p>We are based in Austin, TX.</p><a href='/contact'>Contact</a></body></html>")
    URL = "https://acme.example/"

    def setUp(self):
        self._env = {k: os.environ.pop(k, None) for k in ("BRAND_AUDIT_EXTERNAL_CORROBORATION", "BRAND_AUDIT_OFFLINE")}
        check_trust.EXECUTION_ERRORS.clear()

    def tearDown(self):
        for k, v in self._env.items():
            os.environ.pop(k, None)
            if v is not None:
                os.environ[k] = v

    def _no_network(self):
        boom = AssertionError("an external request was made")
        return patch("urllib.request.urlopen", side_effect=boom), patch.object(check_trust, "check_external_apis", side_effect=boom)

    @staticmethod
    def _response(body: bytes):
        resp = MagicMock()
        resp.read.side_effect = lambda n=-1: body if n is None or n < 0 else body[:n]
        cm = MagicMock()
        cm.__enter__.return_value = resp
        cm.__exit__.return_value = False
        return cm

    def test_opt_out_makes_no_external_request_and_is_recorded_as_skipped(self):
        os.environ["BRAND_AUDIT_EXTERNAL_CORROBORATION"] = "off"
        urlopen, apis = self._no_network()
        injected = MagicMock(side_effect=AssertionError("injected lookup used"))
        with urlopen, apis:
            r = check_trust.analyze_trust(self.HTML, self.URL, current_year=2026, fetch_sitemap_fn=lambda b: None)
            r2 = check_trust.analyze_trust(self.HTML, self.URL, current_year=2026, fetch_sitemap_fn=lambda b: None,
                                           external_apis_fn=injected)
        injected.assert_not_called()
        for result in (r, r2):
            self.assertEqual(result["corroboration_check"]["status"], "skipped")
            self.assertIn("did not opt in", result["corroboration_check"]["evidence"])

    def test_opt_out_applies_to_every_page_of_a_multi_page_audit(self):
        os.environ["BRAND_AUDIT_EXTERNAL_CORROBORATION"] = "off"
        pages = {self.URL: self.HTML, self.URL + "about": self.HTML}
        with patch.object(check_trust, "fetch_page_with_headers", side_effect=lambda u: (pages[u], None)), \
                patch.object(check_trust, "robots_allows", return_value=(True, "")), \
                patch.object(check_trust, "fetch_sitemap_lastmod", return_value=None), \
                patch.object(check_trust, "check_external_apis") as apis, \
                patch("urllib.request.urlopen", side_effect=AssertionError("an external request was made")):
            out = check_trust.analyze_trust_pages(list(pages), current_year=2026)
        apis.assert_not_called()
        self.assertEqual(out["corroboration_check"]["status"], "skipped")
        self.assertTrue(all(p["corroboration_check"]["status"] == "skipped" for p in out["page_reports"]))

    def test_opt_out_takes_effect_even_with_the_offline_switch(self):
        os.environ.update(BRAND_AUDIT_EXTERNAL_CORROBORATION="off", BRAND_AUDIT_OFFLINE="1")
        urlopen, apis = self._no_network()
        with urlopen, apis:
            r = check_trust.analyze_trust(self.HTML, self.URL, current_year=2026, fetch_sitemap_fn=lambda b: None)
        self.assertEqual(r["corroboration_check"]["status"], "skipped")

    def test_offline_kill_switch_still_overrides_an_opt_in(self):
        os.environ["BRAND_AUDIT_OFFLINE"] = "1"  # opted in (no "off"), but the operator disabled external calls
        urlopen, apis = self._no_network()
        with urlopen, apis:
            r = check_trust.analyze_trust(self.HTML, self.URL, current_year=2026, fetch_sitemap_fn=lambda b: None)
        self.assertEqual(r["corroboration_check"]["status"], "unavailable")
        self.assertIn("offline", r["corroboration_check"]["evidence"].lower())

    def test_cli_default_is_unchanged_and_still_corroborates(self):
        with patch.object(check_trust, "check_external_apis", return_value=[]) as apis:
            r = check_trust.analyze_trust(self.HTML, self.URL, current_year=2026, fetch_sitemap_fn=lambda b: None)
        apis.assert_called_once()
        self.assertEqual(r["corroboration_check"]["status"], "pass")

    def test_external_outage_is_unavailable_not_pass(self):
        with patch("urllib.request.urlopen", side_effect=urllib.error.URLError("network is unreachable")):
            r = check_trust.analyze_trust(self.HTML, self.URL, current_year=2026, fetch_sitemap_fn=lambda b: None)
        self.assertEqual(check_trust.EXTERNAL_QUERY_STATUS, {"attempted": 2, "failed": 2})
        self.assertEqual(r["corroboration_check"]["status"], "unavailable")
        self.assertIn("could not be reached", r["corroboration_check"]["evidence"])
        self.assertNotIn("No external search results found", r["corroboration_check"]["evidence"])

    def test_one_source_down_still_uses_the_other(self):
        wikidata = json.dumps({"search": [{"label": "Acme Analytics", "description": "software company in Austin, Texas",
                                           "concepturi": "https://www.wikidata.org/wiki/Q1"}]}).encode()
        def fake(req, timeout=None):
            if "wikipedia" in req.full_url:
                raise urllib.error.URLError("down")
            return self._response(wikidata)
        with patch("urllib.request.urlopen", side_effect=fake):
            r = check_trust.analyze_trust(self.HTML, self.URL, current_year=2026, fetch_sitemap_fn=lambda b: None)
        self.assertEqual(check_trust.EXTERNAL_QUERY_STATUS, {"attempted": 2, "failed": 1})
        self.assertNotEqual(r["corroboration_check"]["status"], "unavailable")
        self.assertIn("1 external source", r["corroboration_check"]["evidence"])

    def test_oversized_external_responses_are_refused(self):
        limit = check_trust.EXTERNAL_RESPONSE_MAX_BYTES
        self.assertEqual(limit, 256 * 1024)
        huge = b'{"query": {"search": []}, "pad": "' + b"x" * limit + b'"}'
        reads = []
        def fake(req, timeout=None):
            cm = self._response(huge)
            original = cm.__enter__.return_value.read.side_effect
            cm.__enter__.return_value.read.side_effect = lambda n=-1: reads.append(n) or original(n)
            return cm
        with patch("urllib.request.urlopen", side_effect=fake):
            r = check_trust.analyze_trust(self.HTML, self.URL, current_year=2026, fetch_sitemap_fn=lambda b: None)
        self.assertEqual(reads, [limit + 1, limit + 1])  # never reads more than limit + 1 bytes
        self.assertEqual(r["corroboration_check"]["status"], "unavailable")
        self.assertTrue(any("byte limit" in e for e in check_trust.EXECUTION_ERRORS))
        exactly = b'{"search": []' + b" " * (limit - 14) + b"}"
        self.assertEqual(len(exactly), limit)
        self.assertEqual(check_trust._read_capped_json(self._response(exactly).__enter__()), {"search": []})

    def test_composer_reports_skipped_and_unavailable_distinctly(self):
        os.environ["BRAND_AUDIT_EXTERNAL_CORROBORATION"] = "off"
        with patch("urllib.request.urlopen", side_effect=AssertionError("network")):
            skipped = check_trust.analyze_trust(self.HTML, self.URL, current_year=2026, fetch_sitemap_fn=lambda b: None)
        os.environ.pop("BRAND_AUDIT_EXTERNAL_CORROBORATION")
        with patch("urllib.request.urlopen", side_effect=urllib.error.URLError("down")):
            outage = check_trust.analyze_trust(self.HTML, self.URL, current_year=2026, fetch_sitemap_fn=lambda b: None)
        a, b = compose(CLEAN_TECH, skipped, CLEAN_ENG), compose(CLEAN_TECH, outage, CLEAN_ENG)
        self.assertEqual((a["scope"]["external_sources_checked"], a["scope"]["external_corroboration"]), (0, "skipped_by_user"))
        self.assertEqual([c["check"] for c in a["execution"]["skipped_checks"]], ["corroboration_check"])
        self.assertFalse(any(c["check"] == "corroboration_check" for c in a["execution"]["unavailable_checks"]))
        self.assertEqual((b["scope"]["external_sources_checked"], b["scope"]["external_corroboration"]), (0, "unavailable"))
        self.assertTrue(any(c["check"] == "corroboration_check" for c in b["execution"]["unavailable_checks"]))
        self.assertEqual(b["execution"]["skipped_checks"], [])


class TestSitemapFetchSafety(unittest.TestCase):
    """Security phase 6, step 1: the trust stage's sitemap fetch (formerly a bare urlopen) validates the URL and
    every redirect hop before connecting, follows same-host redirects only, and is bounded in size and time."""

    def setUp(self):
        import contextlib
        import io
        import threading
        from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
        self.requests, self.route = [], ("200", "<urlset><url><lastmod>2026-05-01</lastmod></url></urlset>")
        test = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):  # noqa: N802
                test.requests.append((self.headers.get("Host"), self.path))
                kind, value = test.route if self.path == "/sitemap.xml" else ("200", "<urlset><url><lastmod>2025-02-02</lastmod></url></urlset>")
                try:
                    if kind == "redirect":
                        self.send_response(302)
                        self.send_header("Location", value)
                        self.send_header("Content-Length", "0")
                        self.end_headers()
                        return
                    if kind == "slow":
                        time.sleep(value)
                        kind, value = "200", "<urlset><url><lastmod>2026-01-01</lastmod></url></urlset>"
                    body = value.encode()
                    self.send_response(int(kind))
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                except OSError:
                    pass  # the client gave up (timeout case)

            def log_message(self, *args):
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.port = self.server.server_address[1]
        self.base = f"http://127.0.0.1:{self.port}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self._saved = os.environ.get("BRAND_AUDIT_LOCAL_FIXTURE")
        os.environ["BRAND_AUDIT_LOCAL_FIXTURE"] = str(self.port)  # the engine's narrow test-only allowance
        check_trust._LOCAL_FIXTURE_WARNED = True
        check_trust.EXECUTION_ERRORS.clear()
        self._quiet = contextlib.redirect_stderr(io.StringIO())
        self._quiet.__enter__()

    def tearDown(self):
        self._quiet.__exit__(None, None, None)
        self.server.shutdown()
        self.server.server_close()
        os.environ.pop("BRAND_AUDIT_LOCAL_FIXTURE", None)
        if self._saved is not None:
            os.environ["BRAND_AUDIT_LOCAL_FIXTURE"] = self._saved
        check_trust._LOCAL_FIXTURE_WARNED = False

    def fetch(self):
        return check_trust.fetch_sitemap_lastmod(self.base)

    def errors(self):
        return " ".join(check_trust.EXECUTION_ERRORS)

    def test_sitemap_lastmod_is_parsed(self):
        self.assertEqual(self.fetch(), 2026)
        self.assertEqual(check_trust.EXECUTION_ERRORS, [])

    def test_same_host_redirect_is_followed(self):
        self.route = ("redirect", "/real-sitemap.xml")
        self.assertEqual(self.fetch(), 2025)
        self.assertEqual([p for _, p in self.requests], ["/sitemap.xml", "/real-sitemap.xml"])

    def test_cross_host_redirect_is_not_followed(self):
        self.route = ("redirect", f"http://localhost:{self.port}/sitemap.xml")  # allowed host, but a different one
        self.assertIsNone(self.fetch())
        self.assertEqual(self.requests, [(f"127.0.0.1:{self.port}", "/sitemap.xml")])
        self.assertIn("redirect to another host not followed", self.errors())

    def test_redirects_to_prohibited_destinations_are_refused_before_connecting(self):
        for target in ("http://10.0.0.1/sitemap.xml", "http://192.168.1.1/sitemap.xml", "http://169.254.169.254/latest/meta-data/",
                       f"http://127.0.0.1:{self.port + 1}/sitemap.xml", "http://[::1]/sitemap.xml",
                       "ftp://127.0.0.1/sitemap.xml", "file:///etc/passwd"):
            with self.subTest(target=target):
                self.requests.clear()
                check_trust.EXECUTION_ERRORS.clear()
                self.route = ("redirect", target)
                self.assertIsNone(self.fetch())
                self.assertEqual([p for _, p in self.requests], ["/sitemap.xml"])  # nothing fetched after the redirect
                self.assertIn("Sitemap lastmod fetch failed", self.errors())

    def test_per_hop_validation_refuses_even_without_the_dns_guard(self):
        """Defence in depth: with the connect-time DNS filter disabled, redirect validation alone must stop the hop
        before any connection to the prohibited address is attempted."""
        import contextlib
        import socket
        attempts = []
        real_create = socket.create_connection

        def watch(address, *args, **kwargs):
            attempts.append(address[0])
            if address[0] != "127.0.0.1":
                raise AssertionError(f"connection attempted to {address}")
            return real_create(address, *args, **kwargs)

        for target in ("http://10.0.0.1/sitemap.xml", "http://169.254.169.254/latest/meta-data/", "http://[::1]/x"):
            with self.subTest(target=target):
                attempts.clear()
                self.route = ("redirect", target)
                with patch.object(check_trust, "_guarded_dns", contextlib.nullcontext), \
                        patch("socket.create_connection", side_effect=watch):
                    self.assertIsNone(self.fetch())
                self.assertEqual(set(attempts), {"127.0.0.1"})  # only the audited site itself was contacted
                self.assertIn("Blocked", self.errors())

    def test_unsafe_starting_url_is_refused_without_any_request(self):
        self.assertIsNone(check_trust.fetch_sitemap_lastmod("http://10.0.0.1"))
        self.assertIsNone(check_trust.fetch_sitemap_lastmod(f"http://127.0.0.1:{self.port + 1}"))
        self.assertEqual(self.requests, [])
        self.assertIn("Blocked", self.errors())

    def test_dns_failure_is_handled(self):
        with _offline_public_dns():
            self.assertIsNone(check_trust.fetch_sitemap_lastmod("https://unresolvable.invalid"))
        self.assertIn("resolution failed", self.errors())

    def test_oversized_sitemap_is_never_read_past_64_kib(self):
        early = "<urlset><url><lastmod>2020-01-01</lastmod></url>"
        late = "<url><lastmod>2026-01-01</lastmod></url></urlset>"
        self.route = ("200", early + " " * (70 * 1024) + late)  # the 2026 entry lies beyond the 64 KiB cap
        self.assertEqual(self.fetch(), 2020)

    def test_timeout_is_handled(self):
        self.route = ("slow", 4.5)  # longer than the 3 s sitemap timeout
        started = time.monotonic()
        self.assertIsNone(self.fetch())
        self.assertGreaterEqual(time.monotonic() - started, 2.9)
        self.assertIn("timed out", self.errors().lower())

    def test_missing_sitemap_is_not_an_error(self):
        for code in ("404", "410"):
            self.route = (code, "missing")
            self.assertIsNone(self.fetch())
        self.assertEqual(check_trust.EXECUTION_ERRORS, [])
        self.route = ("503", "down")
        self.assertIsNone(self.fetch())
        self.assertIn("HTTP 503", self.errors())


class TestOffsiteSitemaps(unittest.TestCase):
    """Security phase 6, step 2: sitemaps declared in robots.txt on another host (CDN subdomains included) are
    skipped and reported, never fetched; www.<site> is the same site, as for every crawl request."""

    SITE = "https://example.com"
    ROBOTS = ("User-agent: *\nAllow: /\n"
              "Sitemap: https://cdn.example.com/sitemap.xml\n"
              "Sitemap: https://other.example/sitemap.xml\n"
              "Sitemap: http://10.0.0.1/sitemap.xml\n"
              "Sitemap: https://www.example.com/sitemap-main.xml\n")
    PAGE = ("<html><head><title>Example Co</title><meta name='viewport' content='width=device-width'></head>"
            "<body><h1>Example Co builds forecasting tools</h1></body></html>")

    def setUp(self):
        os.environ["BRAND_AUDIT_DISABLE_RENDER"] = "1"
        self.fetched = []

    def tearDown(self):
        os.environ.pop("BRAND_AUDIT_DISABLE_RENDER", None)

    def fake_fetch(self, url, **kwargs):
        self.fetched.append(url)
        headers = {"_final_url": url, "_redirect_chain": []}
        if url == self.SITE + "/robots.txt":
            return 200, self.ROBOTS, headers
        if url == "https://www.example.com/sitemap-main.xml":
            return 200, ('<urlset><url><loc>https://example.com/pricing</loc><lastmod>2026-09-01</lastmod></url></urlset>'), headers
        if url.rstrip("/") in (self.SITE, self.SITE + "/pricing"):
            return 200, self.PAGE, headers
        return 404, "", headers

    def test_offsite_declared_sitemaps_are_never_fetched_and_are_reported(self):
        tech = check_technical.analyze_technical(self.SITE + "/", max_crawl_pages=2, fetch_fn=self.fake_fetch)
        for offsite in ("https://cdn.example.com/sitemap.xml", "https://other.example/sitemap.xml", "http://10.0.0.1/sitemap.xml"):
            self.assertNotIn(offsite, self.fetched)
            self.assertIn(offsite, tech["sitemap"]["skipped_offsite"])
        self.assertIn("https://www.example.com/sitemap-main.xml", self.fetched)  # www.<site> is the same site
        self.assertTrue(tech["sitemap"]["found"])
        self.assertIn("Skipped 3 sitemap(s) declared in robots.txt on another host", tech["sitemap"]["evidence"])
        self.assertTrue(all(check_technical.is_same_domain(u, self.SITE) for u in self.fetched))
        self.assertEqual(len(tech["robots_txt"]["sitemaps"]), 4)  # the declarations themselves are still recorded

    def test_composed_report_lists_skipped_sitemaps_without_a_false_defect(self):
        tech = check_technical.analyze_technical(self.SITE + "/", max_crawl_pages=2, fetch_fn=self.fake_fetch)
        report = compose(tech, None, None, site=self.SITE)
        self.assertEqual(set(report["scope"]["sitemaps_skipped_offsite"]),
                         {"https://cdn.example.com/sitemap.xml", "https://other.example/sitemap.xml", "http://10.0.0.1/sitemap.xml"})
        self.assertNotIn("No XML Sitemap declared in robots.txt", {f["title"] for f in report["findings"]})

    def test_parse_xml_sitemap_refuses_an_offsite_starting_sitemap(self):
        res = check_technical.parse_xml_sitemap("https://cdn.example.com/sitemap.xml", self.SITE, fetch_fn=self.fake_fetch)
        self.assertEqual(self.fetched, [])
        self.assertTrue(res["skipped_offsite"])
        self.assertFalse(res["found"])

    def test_sitemap_index_children_on_other_hosts_are_not_queued(self):
        index = ('<sitemapindex><sitemap><loc>https://cdn.example.com/a.xml</loc></sitemap>'
                 '<sitemap><loc>https://example.com/b.xml</loc></sitemap></sitemapindex>')

        def fetch(url, **kwargs):
            self.fetched.append(url)
            if url.endswith("/sitemap.xml"):
                return 200, index, {}
            return 200, '<urlset><url><loc>https://example.com/b</loc></url></urlset>', {}
        check_technical.parse_xml_sitemap(self.SITE + "/sitemap.xml", self.SITE, fetch_fn=fetch)
        self.assertEqual(self.fetched, [self.SITE + "/sitemap.xml", "https://example.com/b.xml"])

    def test_entity_expansion_sitemap_fails_safely_and_quickly(self):
        import pyexpat
        bomb = ('<?xml version="1.0"?><!DOCTYPE lolz [<!ENTITY lol "lol">'
                + "".join(f'<!ENTITY lol{i} "' + f"&lol{i - 1};" * 10 + '">' for i in range(1, 10)).replace("&lol0;", "&lol;")
                + ']><urlset><url><loc>&lol9;</loc></url></urlset>')
        started = time.monotonic()
        res = check_technical.parse_xml_sitemap(self.SITE + "/sitemap.xml", self.SITE, fetch_fn=lambda u, **k: (200, bomb, {}))
        self.assertLess(time.monotonic() - started, 5.0)
        self.assertLess(sum(len(u) for u in res["urls"]), 10_000)  # nothing like the 10^9-character expansion
        self.assertGreaterEqual(tuple(int(x) for x in pyexpat.EXPAT_VERSION.split("_")[1].split(".")), (2, 4, 1))


class TestTruncatedPagesAreReported(unittest.TestCase):
    """Security phase 6, step 3: a response over the 2 MB cap is still read only up to the cap, and the truncation
    is now recorded (it was silent). Informational: it does not make the audit partial."""

    BIG = 2_500_000

    def setUp(self):
        import contextlib
        import io
        import threading
        from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
        big = ("<html><head><title>Big Co</title></head><body><h1>Big Co</h1><p>"
               + "x" * self.BIG + "</p><p>TAIL-MARKER</p></body></html>").encode()
        small = b"<html><head><title>Small</title></head><body><h1>Small</h1></body></html>"
        self.sent = []

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):  # noqa: N802
                body = big if self.path == "/" else small if self.path == "/small" else b""
                self.send_response(200 if body else 404)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                try:
                    self.wfile.write(body)
                except OSError:
                    pass  # the client stopped reading at its cap

            def log_message(self, *args):
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        port = self.server.server_address[1]
        self.base = f"http://127.0.0.1:{port}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self._saved = {k: os.environ.get(k) for k in ("BRAND_AUDIT_LOCAL_FIXTURE", "BRAND_AUDIT_DISABLE_RENDER")}
        os.environ["BRAND_AUDIT_LOCAL_FIXTURE"] = str(port)
        os.environ["BRAND_AUDIT_DISABLE_RENDER"] = "1"
        for module in (check_technical, check_trust, check_engagement):
            module.TRUNCATED_URLS.clear()
            if hasattr(module, "_LOCAL_FIXTURE_WARNED"):
                module._LOCAL_FIXTURE_WARNED = True
        self._quiet = contextlib.redirect_stderr(io.StringIO())
        self._quiet.__enter__()

    def tearDown(self):
        self._quiet.__exit__(None, None, None)
        self.server.shutdown()
        self.server.server_close()
        for k, v in self._saved.items():
            os.environ.pop(k, None)
            if v is not None:
                os.environ[k] = v

    def test_each_fetcher_caps_at_2_mb_and_records_the_truncation(self):
        cap = 2 * 1024 * 1024
        _, text, _ = check_technical.fetch_url(self.base + "/")
        self.assertEqual(len(text.encode()), cap)
        self.assertNotIn("TAIL-MARKER", text)
        html, _ = check_trust.fetch_page_with_headers(self.base + "/")
        self.assertEqual(len(html.encode()), cap)
        raw_len, html = check_engagement.fetch_page(self.base + "/")
        self.assertEqual(raw_len, cap)
        for module in (check_technical, check_trust, check_engagement):
            self.assertEqual(module.TRUNCATED_URLS, [self.base + "/"], module.__name__)

    def test_small_pages_are_not_reported(self):
        check_technical.fetch_url(self.base + "/small")
        check_trust.fetch_page_with_headers(self.base + "/small")
        check_engagement.fetch_page(self.base + "/small")
        for module in (check_technical, check_trust, check_engagement):
            self.assertEqual(module.TRUNCATED_URLS, [], module.__name__)

    def test_technical_audit_reports_truncation_without_marking_it_partial(self):
        tech = check_technical.analyze_technical(self.base + "/", max_crawl_pages=1)
        self.assertEqual(tech["crawl_scope"]["truncated_urls"], [self.base + "/"])
        self.assertEqual(tech["execution"]["truncated_pages"], [self.base + "/"])
        report = compose(tech, None, None, site=self.base)
        self.assertEqual(report["execution"]["truncated_pages"], [self.base + "/"])
        self.assertFalse(any("truncat" in e.lower() for e in report["execution"]["errors"]))

    def test_composer_merges_truncation_from_all_stages_and_stays_informational(self):
        tech = {"execution": {"partial": False, "errors": [], "truncated_pages": ["https://example.com/"]}}
        trust = {"execution": {"partial": False, "errors": [], "truncated_pages": ["https://example.com/", "https://example.com/a"]}}
        clean = compose({"execution": {"partial": False, "errors": []}}, {"execution": {"partial": False, "errors": []}}, None)
        report = compose(tech, trust, None)
        self.assertEqual(report["execution"]["truncated_pages"], ["https://example.com/", "https://example.com/a"])
        self.assertEqual(report["execution"]["partial"], clean["execution"]["partial"])
        self.assertEqual(report["readiness"], clean["readiness"])
        self.assertEqual(clean["execution"]["truncated_pages"], [])


class TestProgressWriteReliability(unittest.TestCase):
    """Phase 6 reliability fix: on Windows, replacing the progress file fails with PermissionError while the web
    API has it open. Writes are retried with a bounded backoff; an exhausted retry is surfaced, never ignored."""

    def setUp(self):
        import contextlib
        import io
        self.dir = tempfile.TemporaryDirectory()
        self.path = Path(self.dir.name) / "progress.json"
        self.sleeps = []
        self.progress = run_audit.Progress(str(self.path), sleep=self.sleeps.append)  # no real sleeping
        self.stderr = io.StringIO()
        self._quiet = contextlib.redirect_stderr(self.stderr)
        self._quiet.__enter__()

    def tearDown(self):
        self._quiet.__exit__(None, None, None)
        self.dir.cleanup()

    def stored(self):
        return json.loads(self.path.read_text(encoding="utf-8"))["stages"]

    def test_transient_replace_failures_are_retried_until_the_write_succeeds(self):
        real_replace = Path.replace
        outcomes = [PermissionError(13, "Access is denied")] * 3

        def flaky(self_path, target):
            if outcomes:
                raise outcomes.pop(0)
            return real_replace(self_path, target)
        with patch.object(Path, "replace", flaky):
            self.assertTrue(self.progress.update("compose", "completed"))
        self.assertEqual(self.stored()["compose"], "completed")
        self.assertEqual(self.sleeps, list(run_audit.Progress.RETRY_DELAYS[:3]))
        self.assertEqual(self.progress.failures, [])
        self.assertNotIn("ERROR", self.stderr.getvalue())

    def test_exhausted_retries_are_reported_not_swallowed(self):
        self.assertTrue(self.progress.update("compose", "running"))
        with patch.object(Path, "replace", side_effect=PermissionError(13, "Access is denied")) as replace:
            self.assertFalse(self.progress.update("compose", "completed"))
        self.assertEqual(replace.call_count, len(run_audit.Progress.RETRY_DELAYS) + 1)  # bounded
        self.assertEqual(self.sleeps, list(run_audit.Progress.RETRY_DELAYS))
        self.assertLess(sum(run_audit.Progress.RETRY_DELAYS), 1.0)
        self.assertEqual(len(self.progress.failures), 1)
        self.assertIn("could not persist progress compose=completed after 7 attempts", self.stderr.getvalue())
        self.assertIn("PermissionError", self.progress.failures[0])
        self.assertEqual(self.stored()["compose"], "running")  # the stale file is left as it was, not corrupted

    def test_a_later_write_repairs_an_earlier_lost_one(self):
        with patch.object(Path, "replace", side_effect=PermissionError(13, "Access is denied")):
            self.assertFalse(self.progress.update("technical", "completed"))
        self.assertTrue(self.progress.update("trust", "completed"))
        self.assertEqual(self.stored()["technical"], "completed")  # every write carries the full stage table

    def test_disabled_progress_never_fails(self):
        self.assertTrue(run_audit.Progress(None).update("compose", "completed"))

    def test_audit_is_not_reported_successful_when_the_final_progress_write_fails(self):
        """main() with stubbed stages: every stage succeeds, but the final progress write cannot be persisted."""
        out = Path(self.dir.name) / "report.json"

        def fake_run(cmd, timeout):
            target = Path(cmd[cmd.index("--output") + 1])
            target.write_text(json.dumps({"execution": {"partial": False, "errors": [], "missing_categories": []}}), encoding="utf-8")
            return subprocess.CompletedProcess(cmd, 0, "", ""), None

        def update(self_progress, stage_name, state):
            return not (stage_name == "compose" and state == "completed")
        argv = ["run_audit.py", "https://example.com", "--output", str(out), "--progress-file", str(self.path)]
        with patch.object(run_audit, "run", fake_run), patch.object(run_audit.Progress, "update", update),                 patch.object(sys, "argv", argv):
            self.assertEqual(run_audit.main(), 3)
        self.assertIn("final progress update could not be persisted", self.stderr.getvalue())
        with patch.object(run_audit, "run", fake_run), patch.object(sys, "argv", argv):
            self.assertEqual(run_audit.main(), 0)  # control: the same run succeeds when the write succeeds
        self.assertEqual(self.stored()["compose"], "completed")


class TestEmailDetectionIsLinear(unittest.TestCase):
    """Security phase 6: the three stages' email regexes were quadratic on long word-character runs (100,000
    characters took about 130 s). find_emails must return exactly what each original regex returned, and finish
    quickly on 2 MB hostile page text."""

    ORIGINAL = {  # module: (original pattern, flags) exactly as it was used
        "check_technical": (r'[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}', 0),
        "check_trust": (r'[\w.+-]+@[\w.-]+\.[a-zA-Z]{2,}', 0),
        "check_engagement": (r'[\w.+-]+@[\w.-]+\.[a-z]{2,}', re.I),
    }
    CURATED = [
        "", "@", "@@", "a@", "@b.com", "a@b", "a@b.c", "a@b.co", "A@B.COM", "a.b+c-d_e@sub.example.co.uk",
        "Mail sales@example.com or j.doe+x@mail.co.uk today.", "<a href='mailto:info@brand.io'>info@brand.io</a>",
        '"john doe"@example.com', '"john@doe"@example.com', "o'brien@example.ie", "user%tag@example.com",
        "a@[192.168.0.1]", "a@localhost", "a@b..com", "a@.com", ".a@b.com", "a@b.com.", "a@b.c0m", "a@b.com9",
        "a@b.co9x@c.de", "a@b.comc@d.ef", "a@b.com@c.de", "a@@b.com", "a@b.com,c@d.org;e@f.net",
        "jöhn@exämple.de", "用户@例子.广告", "用户@例子.com", "δοκιμή@παράδειγμα.δοκιμή", "x@y.Kb", "x@y.ſx",
        "x@y.İx", "x@y.ıx", "a​@b.com", "a b@c.com", "1@2.34", "1@2.ab", "____@____.__",
        "a" * 300 + "@" + "b" * 300 + ".com", "x" * 3000 + " a@b.com", "a@b.com " + "@" * 3000, ("a@" + "b" * 50) * 60,
    ]
    HOSTILE = {
        "word-run": "x" * (2 * 1024 * 1024),
        "digit-run": "7" * (2 * 1024 * 1024),
        "at-runs": ("a@" + "b" * 1000) * 2093,
        "dots": "a." * (1024 * 1024),
        "alternating": "a@" * (1024 * 1024),
    }

    def modules(self):
        return {"check_technical": check_technical, "check_trust": check_trust, "check_engagement": check_engagement}

    def test_matches_the_original_regex_exactly(self):
        import random
        rnd = random.Random(20261025)
        alphabet = list("abcxyzABCXYZ019_.+-@ \t\n,;:<>\"'()[]%") + list("éüßøç用户δοκKſİı​ ")
        weights = [6 if c.isalnum() else 3 if c in ".@-+_" else 1 for c in alphabet]
        fuzz = ["".join(rnd.choices(alphabet, weights, k=rnd.randint(1, rnd.choice((20, 80, 400))))) for _ in range(20000)]
        for name, module in self.modules().items():
            pattern, flags = self.ORIGINAL[name]
            original = re.compile(pattern, flags)
            for text in self.CURATED + fuzz:
                self.assertEqual(module.find_emails(text), original.findall(text), (name, text[:80]))
                self.assertEqual(bool(module.find_emails(text)), bool(original.search(text)), (name, text[:80]))

    def test_the_three_copies_differ_only_in_their_original_domain_pattern(self):
        import inspect
        sources = {name: inspect.getsource(m.find_emails) for name, m in self.modules().items()}
        normalised = {re.sub(r"r'\[\\w\.\+-\]\+@[^']*', text(, re\.I)?", "PATTERN", s) for s in sources.values()}
        self.assertEqual(len(normalised), 1, "find_emails copies have drifted apart")
        for name, module in self.modules().items():
            pattern, flags = self.ORIGINAL[name]
            self.assertEqual(module._EMAIL_LOCAL_CHAR.pattern, r'[\w.+-]')
            self.assertEqual("[\\w.+-]+@" + module._EMAIL_DOMAIN.pattern, pattern)
            self.assertEqual(module._EMAIL_DOMAIN.flags & re.I, flags & re.I)

    def test_two_megabyte_hostile_text_takes_linear_work(self):
        """Deterministic: count the scanner's pattern calls instead of timing them (wall-clock limits are flaky on
        loaded machines). Local-part character checks are at most len(text) and domain matches at most one per
        '@'; domain runs end at the next '@', so they never overlap and the domain regex's work is also linear."""

        class Counting:
            def __init__(self, pattern):
                self.pattern, self.calls = pattern, 0

            def match(self, *args):
                self.calls += 1
                return self.pattern.match(*args)

        for label, text in self.HOSTILE.items():
            for name, module in self.modules().items():
                local, domain = Counting(module._EMAIL_LOCAL_CHAR), Counting(module._EMAIL_DOMAIN)
                started = time.monotonic()
                with patch.object(module, "_EMAIL_LOCAL_CHAR", local), patch.object(module, "_EMAIL_DOMAIN", domain):
                    module.find_emails(text)
                self.assertLessEqual(local.calls, len(text), (label, name))
                self.assertLessEqual(domain.calls, text.count("@"), (label, name))
                if "@" in text:  # the scanner must really be the code doing the work (not a bare regex call)
                    self.assertGreater(domain.calls, 0, (label, name))
                # Hang guard only. Measured 0-2.5 s here; the original regex needs hours at this size.
                self.assertLess(time.monotonic() - started, 120.0, (label, name))


class TestPageTextScansStayLinear(unittest.TestCase):
    r"""Security phase 6: the FAQ question regex r'([^.!?]+\?)' was quadratic on long runs without . ! or ? (2 MB of
    plain prose stalled the technical stage). QUESTION_SENTENCE must find exactly the same questions, quickly; and no
    stage may hang on a 2 MB hostile page."""

    def test_question_sentence_matches_the_original_regex_exactly(self):
        import random
        original = re.compile(r'([^.!?]+\?)')
        rnd = random.Random(1025)
        alphabet = list("abc xyz ABC 019?.!,;:\n\t\"'()-") + list("éü用户¿¡？。")
        weights = [6 if c.isalnum() or c == " " else 3 if c in "?.!" else 1 for c in alphabet]
        cases = ["", "?", "??", "a?", "What is it?", "Hi. How are you? Fine! Why? ...?", "a?b?c", "no question here.",
                 "x" * 5000 + "?", "x" * 5000, "¿Qué? 用户？", "line one\nwhat now?", ". ? ! ?"]
        cases += ["".join(rnd.choices(alphabet, weights, k=rnd.randint(1, rnd.choice((20, 100, 500))))) for _ in range(30000)]
        for text in cases:
            self.assertEqual(check_technical.QUESTION_SENTENCE.findall(text), original.findall(text), text[:80])

    def test_question_sentence_only_starts_matches_at_run_starts(self):
        """Why it is linear, checked structurally: the lookbehind lets a match begin only after . ! ? or at the
        start, so each run is scanned once. Wall-clock is a hang guard only (the original needs hours at 2 MB)."""
        self.assertTrue(check_technical.QUESTION_SENTENCE.pattern.startswith("(?<![^.!?])"))
        for text in ("x" * (2 * 1024 * 1024), "word " * 400_000, ("a" * 1000 + "?") * 2000):
            started = time.monotonic()
            found = check_technical.QUESTION_SENTENCE.findall(text)
            self.assertLess(time.monotonic() - started, 120.0)
            self.assertEqual(len(found), text.count("?"))

    def test_each_stage_analyses_a_two_megabyte_hostile_page_without_hanging(self):
        """End to end, in a child process with a hard timeout so a regression fails instead of hanging the suite."""
        script = r'''
import os, sys, time
root = sys.argv[1]
for sub in ("crawl-render-audit", "engagement-audit", "freshness-corroboration"):
    sys.path.insert(0, os.path.join(root, "skills", sub, "scripts"))
os.environ["BRAND_AUDIT_DISABLE_RENDER"] = "1"
os.environ["BRAND_AUDIT_EXTERNAL_CORROBORATION"] = "off"
import check_technical, check_trust, check_engagement
url = "https://example.com/"
for label, payload in (("word-run", "x" * 2000000), ("prose", "word " * 400000), ("at-runs", ("a@" + "b" * 1000) * 1990)):
    html = "<html><head><title>Hostile</title></head><body><h1>Hostile</h1><p>" + payload + "</p></body></html>"
    for stage in ("technical", "trust", "engagement"):
        started = time.monotonic()
        if stage == "technical":
            check_technical.analyze_technical(url, max_crawl_pages=1, fetch_fn=lambda u, **k: (
                (200, html, {"_final_url": u, "_redirect_chain": []}) if u == url else (404, "", {"_final_url": u, "_redirect_chain": []})))
        elif stage == "trust":
            check_trust.analyze_trust(html, url, current_year=2026, fetch_sitemap_fn=lambda base: None,
                                      external_apis_fn=lambda *a, **k: None)
        else:
            check_engagement.analyze_engagement(len(html), html)
        print(f"{label} {stage} {time.monotonic() - started:.2f}", flush=True)
'''
        result = subprocess.run([sys.executable, "-c", script, str(ROOT)], capture_output=True, text=True, timeout=900)
        self.assertEqual(result.returncode, 0, result.stderr[-2000:])
        timings = [line.split() for line in result.stdout.splitlines()]
        self.assertEqual(len(timings), 9, result.stdout)
        for label, stage, seconds in timings:
            # Hang guard: before the fix, technical exceeded 30 s on three of these payloads (and needs hours at
            # 2 MB); after it, each stage measured 0.8-3.2 s here. Loaded CI machines can be many times slower.
            self.assertLess(float(seconds), 120.0, f"{stage} on {label} took {seconds}s")


class TestPageRedirectScope(unittest.TestCase):
    """Security phase 7, H2: the trust and engagement page fetchers follow only same-site redirects (the technical
    stage's rule: each hop on the previous hop's host, ignoring "www."). A redirect to another host, CDN subdomains
    included, is not followed and the page is reported as failed with the reason. Every hop is still validated."""

    REASON = "redirected to another host (not followed)"

    def setUp(self):
        import contextlib
        import io
        import threading
        from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
        self.requests = []
        test = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):  # noqa: N802
                host = self.headers.get("Host", "")
                test.requests.append((host, self.path))
                port = test.port
                routes = {
                    "/same": ("302", "/landing"),
                    "/cross": ("302", f"http://localhost:{port}/elsewhere"),
                    "/same-then-cross": ("301", "/hop"),
                    "/hop": ("302", f"http://localhost:{port}/elsewhere"),
                    "/private": ("302", "http://10.0.0.1/admin"),
                    "/metadata": ("307", "http://169.254.169.254/latest/meta-data/"),
                    "/ftp": ("302", f"ftp://127.0.0.1:{port}/x"),
                    "/loop": ("302", "/loop"),
                    "/no-location": ("302", None),
                }
                kind, target = routes.get(self.path, ("200", None))
                if self.path == "/robots.txt":
                    kind = "404"
                if kind in ("301", "302", "307"):
                    self.send_response(int(kind))
                    if target:
                        self.send_header("Location", target)
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
                body = (f"<html><head><title>Page {self.path}</title></head><body><h1>Served by {host}{self.path}</h1>"
                        "<p>Example Co makes forecasting software for retail teams.</p></body></html>").encode()
                self.send_response(int(kind))
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args):
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.port = self.server.server_address[1]
        self.base = f"http://127.0.0.1:{self.port}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self._saved = os.environ.get("BRAND_AUDIT_LOCAL_FIXTURE")
        os.environ["BRAND_AUDIT_LOCAL_FIXTURE"] = str(self.port)
        for module in (check_trust, check_engagement):
            module._LOCAL_FIXTURE_WARNED = True
            module.EXECUTION_ERRORS.clear()
        self._quiet = contextlib.redirect_stderr(io.StringIO())
        self._quiet.__enter__()

    def tearDown(self):
        self._quiet.__exit__(None, None, None)
        self.server.shutdown()
        self.server.server_close()
        os.environ.pop("BRAND_AUDIT_LOCAL_FIXTURE", None)
        if self._saved is not None:
            os.environ["BRAND_AUDIT_LOCAL_FIXTURE"] = self._saved
        for module in (check_trust, check_engagement):
            module._LOCAL_FIXTURE_WARNED = False

    def fetchers(self):
        """(name, module, fetch returning (text, ok))"""
        def trust(url):
            html, _ = check_trust.fetch_page_with_headers(url)
            return html, not html.startswith("Error:")

        def engagement(url):
            raw_len, html = check_engagement.fetch_page(url)
            return html, bool(raw_len)
        return (("trust", check_trust, trust), ("engagement", check_engagement, engagement))

    def run_case(self, path):
        for name, module, fetch in self.fetchers():
            self.requests.clear()
            module.EXECUTION_ERRORS.clear()
            text, ok = fetch(self.base + path)
            yield name, module, text, ok, list(self.requests)

    def test_same_host_redirect_is_followed(self):
        for name, _, text, ok, requests in self.run_case("/same"):
            with self.subTest(stage=name):
                self.assertTrue(ok, text)
                self.assertIn(f"Served by 127.0.0.1:{self.port}/landing", text)
                self.assertEqual([p for _, p in requests], ["/same", "/landing"])

    def test_cross_host_redirect_is_not_followed_and_is_reported(self):
        for case in ("/cross", "/same-then-cross"):
            for name, module, text, ok, requests in self.run_case(case):
                with self.subTest(stage=name, case=case):
                    self.assertFalse(ok)
                    self.assertNotIn("Served by", text)
                    self.assertTrue(all(h.startswith("127.0.0.1:") for h, _ in requests), requests)  # localhost never contacted
                    self.assertIn(self.REASON, text)
                    self.assertIn(f"http://localhost:{self.port}/elsewhere", " ".join(module.EXECUTION_ERRORS))

    def test_redirects_to_prohibited_destinations_are_refused_before_connecting(self):
        for case in ("/private", "/metadata", "/ftp"):
            for name, module, text, ok, requests in self.run_case(case):
                with self.subTest(stage=name, case=case):
                    self.assertFalse(ok)
                    self.assertEqual([p for _, p in requests], [case])  # nothing requested after the redirect
                    self.assertIn("Page fetch blocked/failed", " ".join(module.EXECUTION_ERRORS))

    def test_redirect_loop_and_missing_location_fail_cleanly(self):
        for case, max_requests in (("/loop", 11), ("/no-location", 1)):
            for name, module, text, ok, requests in self.run_case(case):
                with self.subTest(stage=name, case=case):
                    self.assertFalse(ok)
                    self.assertLessEqual(len(requests), max_requests)
                    self.assertTrue(module.EXECUTION_ERRORS)

    def test_failed_page_carries_the_reason_into_the_composed_report(self):
        urls = [self.base + "/same", self.base + "/cross"]
        trust = check_trust.analyze_trust_pages(urls, current_year=2026, primary_external=lambda _b: [])
        engagement = check_engagement.analyze_engagement_pages(urls)
        for name, report, key in (("trust", trust, "eeat_check"), ("engagement", engagement, "h1_audit")):
            with self.subTest(stage=name):
                pages = {r["url"]: r for r in report["page_reports"]}
                self.assertNotEqual(pages[self.base + "/same"].get("status"), "unavailable")
                failed = pages[self.base + "/cross"]
                self.assertEqual(failed["status"], "unavailable")
                self.assertIn(self.REASON, failed[key]["evidence"])
        composed = compose(None, trust, engagement, site=self.base)
        self.assertIn(self.base + "/cross", composed["execution"]["failed_pages"])
        self.assertNotIn(self.base + "/same", composed["execution"]["failed_pages"])

    def test_host_pair_rule_matches_the_technical_stage(self):
        """Exercises each fetcher's redirect handler directly (hostnames that cannot be served locally). The per-hop
        validator is stubbed here only; the real-socket tests above cover it."""
        import io
        import urllib.parse
        import urllib.request
        cases = [
            ("http://example.com/", "https://example.com/", True),          # http -> https
            ("https://example.com/", "https://www.example.com/", True),     # apex -> www
            ("https://www.example.com/a", "https://example.com/b", True),   # www -> apex
            ("https://EXAMPLE.com/", "https://www.example.COM/x", True),    # case-insensitive
            ("https://example.com/", "https://cdn.example.com/", False),    # CDN subdomain
            ("https://example.com/", "https://example.org/", False),        # other domain
            ("https://example.com/", "https://example.com:8443/", False),   # other port (as fetch_url)
            ("https://www.example.com/", "https://www2.example.com/", False),
        ]
        for name, module, _ in self.fetchers():
            captured = []

            def capture(*handlers):
                captured.extend(handlers)
                raise RuntimeError("stop after building the opener")
            fetch = check_trust.fetch_page_with_headers if module is check_trust else check_engagement.fetch_page
            with patch("urllib.request.build_opener", side_effect=capture):
                fetch(self.base + "/")
            handler = captured[0]
            for src, dst, follow in cases:
                with self.subTest(stage=name, src=src, dst=dst), patch.object(module, "_validate_public_http_url"):
                    req = urllib.request.Request(src)
                    if follow:
                        self.assertIsNotNone(handler.redirect_request(req, io.BytesIO(), 301, "Moved", {}, dst))
                    else:
                        with self.assertRaises(module.CrossHostRedirectRefused) as raised:
                            handler.redirect_request(req, io.BytesIO(), 301, "Moved", {}, dst)
                        self.assertIn(self.REASON, str(raised.exception))

        def technical_rule(src, dst):  # fetch_url's TrackingRedirectHandler comparison
            return urllib.parse.urlparse(src).netloc.lower().removeprefix("www.") == urllib.parse.urlparse(dst).netloc.lower().removeprefix("www.")
        self.assertEqual([technical_rule(s, d) for s, d, _ in cases], [f for _, _, f in cases])


class TestVerifierLoopbackBinding(unittest.TestCase):
    """Security phase 5: the original verifier's mock site listens on loopback only (it used all interfaces)."""

    def test_run_server_binds_127_0_0_1(self):
        sys.path.insert(0, str(ROOT))
        import verify_marketplace as vm
        bound = []

        class FakeServer:
            def __init__(self, address, handler):
                bound.append(address)

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

            def serve_forever(self):
                return None

        with patch.object(vm.socketserver, "TCPServer", FakeServer):
            vm.run_server()
        self.assertEqual(bound, [("127.0.0.1", vm.PORT)])
        self.assertEqual(vm.MOCK_HOST, "127.0.0.1")

    def test_localhost_target_still_reaches_an_ipv4_loopback_server(self):
        """'localhost' may resolve to ::1 first (it does on Windows); the IPv4 fallback must still connect."""
        import socketserver
        import threading
        import urllib.request
        from http.server import BaseHTTPRequestHandler

        class Ok(BaseHTTPRequestHandler):
            def do_GET(self):  # noqa: N802
                self.send_response(200)
                self.send_header("Content-Length", "2")
                self.end_headers()
                self.wfile.write(b"ok")

            def log_message(self, *args):
                pass

        server = socketserver.TCPServer(("127.0.0.1", 0), Ok)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        try:
            self.assertEqual(server.socket.getsockname()[0], "127.0.0.1")
            with urllib.request.urlopen(f"http://localhost:{server.server_address[1]}/", timeout=10) as r:
                self.assertEqual(r.read(), b"ok")
        finally:
            server.shutdown()
            server.server_close()


class TestLegacyLocalFixtureOverride(unittest.TestCase):
    """Security-hardening phase 2: BRAND_AUDIT_LOCAL_FIXTURE stays narrow and is never silent."""

    MODULES = (check_technical, check_trust, check_engagement)

    def setUp(self):
        self._saved = os.environ.pop("BRAND_AUDIT_LOCAL_FIXTURE", None)
        for module in self.MODULES:
            module._LOCAL_FIXTURE_WARNED = False

    def tearDown(self):
        os.environ.pop("BRAND_AUDIT_LOCAL_FIXTURE", None)
        if self._saved is not None:
            os.environ["BRAND_AUDIT_LOCAL_FIXTURE"] = self._saved
        for module in self.MODULES:
            module._LOCAL_FIXTURE_WARNED = False

    def _validate(self, module, url):
        import contextlib
        import io
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            try:
                module._validate_public_http_url(url)
                allowed = True
            except ValueError:
                allowed = False
        return allowed, err.getvalue()

    def test_without_the_override_loopback_is_refused_and_nothing_is_printed(self):
        for module in self.MODULES:
            allowed, printed = self._validate(module, "http://127.0.0.1:8123/")
            self.assertFalse(allowed, module.__name__)
            self.assertEqual(printed, "", module.__name__)

    def test_override_warns_prominently_exactly_once_per_process(self):
        os.environ["BRAND_AUDIT_LOCAL_FIXTURE"] = "8123"
        for module in self.MODULES:
            allowed, first = self._validate(module, "http://127.0.0.1:8123/")
            self.assertTrue(allowed, module.__name__)
            self.assertIn("TEST-ONLY override BRAND_AUDIT_LOCAL_FIXTURE=8123", first)
            self.assertIn("!" * 78, first)
            self.assertIn(os.path.basename(module.__file__), first)
            _, second = self._validate(module, "http://localhost:8123/")
            self.assertEqual(second, "", "the warning must not repeat within a process")

    def test_override_does_not_widen_what_is_allowed(self):
        os.environ["BRAND_AUDIT_LOCAL_FIXTURE"] = "8123"
        for module in self.MODULES:
            for url in ("http://127.0.0.1:8124/", "http://10.0.0.1:8123/", "http://[::1]:8123/", "http://localhost/",
                        "http://169.254.169.254:8123/", "http://localhost.localdomain:8123/"):
                allowed, _ = self._validate(module, url)
                self.assertFalse(allowed, f"{module.__name__} allowed {url}")

    def test_dns_guard_honours_the_override_only_for_the_named_port(self):
        import socket
        os.environ["BRAND_AUDIT_LOCAL_FIXTURE"] = "8123"
        import contextlib
        import io
        with contextlib.redirect_stderr(io.StringIO()), check_technical._guarded_dns():
            self.assertTrue(socket.getaddrinfo("127.0.0.1", 8123))
            with self.assertRaises(socket.gaierror):
                socket.getaddrinfo("127.0.0.1", 8124)


if __name__ == "__main__":
    unittest.main(verbosity=2)
