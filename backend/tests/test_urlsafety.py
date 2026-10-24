import ipaddress
import sys
from pathlib import Path

import pytest

from brand_platform.urlsafety import UnsafeURLError, is_public_ip, validate_audit_url

ROOT = Path(__file__).resolve().parents[2]


def resolver_for(*addresses):
    return lambda host, port: list(addresses)


def fails(url, code, **kw):
    kw.setdefault("resolver", resolver_for("93.184.216.34"))
    with pytest.raises(UnsafeURLError) as info:
        validate_audit_url(url, **kw)
    assert info.value.code == code, info.value.message
    return info.value


@pytest.mark.parametrize("url,code", [
    ("", "invalid_url"),
    ("   ", "invalid_url"),
    ("ftp://example.com/", "unsupported_scheme"),
    ("file:///etc/passwd", "unsupported_scheme"),
    ("javascript:alert(1)", "unsupported_scheme"),
    ("gopher://example.com/", "unsupported_scheme"),
    ("http://user:pass@example.com/", "credentials_in_url"),
    ("http://user@example.com/", "credentials_in_url"),
    ("http://example.com:22/", "port_not_allowed"),
    ("http://example.com:6379/", "port_not_allowed"),
    ("http://example.com:99999/", "invalid_url"),
    ("http://localhost/", "non_public_host"),
    ("http://LOCALHOST./", "non_public_host"),
    ("http://api.localhost/", "non_public_host"),
    ("http://printer.local/", "non_public_host"),
    ("http://metadata.google.internal/", "non_public_host"),
    ("http://intranet/", "non_public_host"),
    ("http://2130706433/", "non_public_host"),
    ("http://0x7f000001/", "non_public_host"),
    ("http://exa mple.com/", "invalid_url"),
    ("http://example.com\\@evil.com/", "invalid_url"),
    ("http://example.com/" + "a" * 2100, "invalid_url"),
])
def test_rejects_malformed_and_disallowed_urls(url, code):
    fails(url, code)


@pytest.mark.parametrize("literal", [
    "127.0.0.1", "10.1.2.3", "172.16.0.1", "192.168.0.10", "169.254.169.254", "100.64.0.1", "0.0.0.0",
    "198.18.0.1", "224.0.0.1", "240.0.0.1", "255.255.255.255", "[::1]", "[::ffff:127.0.0.1]", "[fe80::1]",
    "[fc00::1]", "[2002:7f00:1::]", "[2001:0:4136:e378:8000:63bf:3fff:fdd2]", "[64:ff9b::a00:1]",
])
def test_rejects_non_public_ip_literals(literal):
    fails(f"http://{literal}/", "non_public_address")


@pytest.mark.parametrize("answers", [("10.0.0.5",), ("93.184.216.34", "127.0.0.1"), ("::1",), ("169.254.169.254",)])
def test_rejects_hostnames_resolving_to_any_non_public_address(answers):
    """A mixed public/private answer set is refused: it is a DNS-rebinding pattern."""
    fails("https://rebind.example/", "non_public_address", resolver=resolver_for(*answers))


def test_dns_failure_is_reported():
    def broken(host, port):
        raise OSError("no such host")
    fails("https://does-not-exist.example/", "dns_resolution_failed", resolver=broken)


def test_accepts_and_normalises_public_urls():
    v = validate_audit_url("Example.COM", resolver=resolver_for("93.184.216.34"))
    assert v.url == "https://example.com/"
    assert v.host == "example.com"
    v = validate_audit_url("http://example.com:80/path?q=1#frag", resolver=resolver_for("93.184.216.34"))
    assert v.url == "http://example.com/path?q=1"
    v = validate_audit_url("https://8.8.8.8/", resolver=resolver_for())
    assert v.host == "8.8.8.8"


def test_internationalised_domain_is_punycode_encoded():
    v = validate_audit_url("https://bücher.example/", resolver=resolver_for("93.184.216.34"))
    assert v.host == "xn--bcher-kva.example"


def test_custom_allowed_ports():
    v = validate_audit_url("https://example.com:8443/", allowed_ports=(443, 8443), resolver=resolver_for("93.184.216.34"))
    assert v.url == "https://example.com:8443/"


def test_local_fixture_opt_in_is_narrow():
    assert validate_audit_url("http://127.0.0.1:8123/", local_fixture_port=8123).url == "http://127.0.0.1:8123/"
    fails("http://127.0.0.1:8124/", "port_not_allowed", local_fixture_port=8123)
    fails("https://127.0.0.1:8123/", "port_not_allowed", local_fixture_port=8123)
    fails("http://localhost:8123/", "port_not_allowed", local_fixture_port=8123)
    fails("http://localhost/", "non_public_host", local_fixture_port=8123)
    fails("http://127.0.0.1/", "non_public_address", local_fixture_port=8123)


def test_public_ip_rule_matches_engine_rule():
    """The API admission rule and the engine's per-request rule must agree."""
    sys.path.insert(0, str(ROOT / "skills" / "crawl-render-audit" / "scripts"))
    import check_technical

    samples = ["8.8.8.8", "1.1.1.1", "93.184.216.34", "127.0.0.1", "10.0.0.1", "100.64.0.1", "169.254.1.1", "192.0.2.1",
               "203.0.113.5", "::1", "2606:4700:4700::1111", "::ffff:8.8.8.8", "::ffff:10.0.0.1", "2002:808:808::",
               "2002:a00:1::", "64:ff9b::808:808", "64:ff9b::a00:1", "2001:0:4136:e378:8000:63bf:3fff:fdd2", "fe80::1", "ff02::1"]
    for s in samples:
        ip = ipaddress.ip_address(s)
        assert is_public_ip(ip) == check_technical._is_public_ip(ip), s
