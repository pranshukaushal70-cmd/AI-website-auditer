"""Admission check for user-submitted audit URLs.

This is the first of two layers. The engine re-validates every request, every redirect hop,
and filters DNS answers at connect time (see skills/*/scripts/*.py `_validate_public_http_url`
and `_guarded_dns`). This layer rejects unsafe input early with a clear error and enforces
platform policy (ports, length, normalisation) that the engine does not.
"""

from __future__ import annotations

import ipaddress
import re
import socket
import urllib.parse
from dataclasses import dataclass

MAX_URL_LENGTH = 2048
BLOCKED_HOST_SUFFIXES = (".localhost", ".local", ".internal", ".lan", ".home.arpa", ".onion")
BLOCKED_HOSTS = {"localhost", "localhost.localdomain", "ip6-localhost", "ip6-loopback", "metadata.google.internal"}
_NAT64_PREFIX = ipaddress.ip_network("64:ff9b::/96")
_SCHEME_ONLY = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*:(?!\d)")


class UnsafeURLError(ValueError):
    """Raised when a URL is not acceptable as an audit target."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class ValidatedURL:
    url: str
    host: str
    resolved_addresses: tuple[str, ...]


def is_public_ip(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    """Same rule as the engine's `_is_public_ip` (parity is asserted in the tests)."""
    if ip.version == 6:
        if ip.ipv4_mapped is not None:
            return is_public_ip(ip.ipv4_mapped)
        if ip.teredo is not None:
            return False
        if ip.sixtofour is not None:
            return is_public_ip(ip.sixtofour)
        if ip in _NAT64_PREFIX:
            return is_public_ip(ipaddress.IPv4Address(int(ip) & 0xFFFFFFFF))
    return ip.is_global and not (ip.is_private or ip.is_loopback or ip.is_link_local or
                                 ip.is_unspecified or ip.is_multicast or ip.is_reserved)


def _resolve(host: str, port: int) -> list[str]:
    infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    return sorted({info[4][0].split("%")[0] for info in infos})


def validate_audit_url(raw: str, allowed_ports: tuple[int, ...] = (80, 443),
                       local_fixture_port: int | None = None, resolver=_resolve) -> ValidatedURL:
    """Normalise and validate a submitted URL; raise UnsafeURLError with a stable code."""
    if not isinstance(raw, str) or not raw.strip():
        raise UnsafeURLError("invalid_url", "A URL is required.")
    text = raw.strip()
    if len(text) > MAX_URL_LENGTH:
        raise UnsafeURLError("invalid_url", f"URL is longer than {MAX_URL_LENGTH} characters.")
    if any(ord(c) < 0x21 or c in "\\" for c in text):
        raise UnsafeURLError("invalid_url", "URL contains whitespace, control characters, or backslashes.")
    if "://" not in text:
        if _SCHEME_ONLY.match(text):  # e.g. "javascript:..." or "mailto:..." (but not "host:8080")
            raise UnsafeURLError("unsupported_scheme", "Only http and https URLs can be audited.")
        text = "https://" + text

    parts = urllib.parse.urlsplit(text)
    scheme = parts.scheme.lower()
    if scheme not in ("http", "https"):
        raise UnsafeURLError("unsupported_scheme", "Only http and https URLs can be audited.")
    if parts.username is not None or parts.password is not None:
        raise UnsafeURLError("credentials_in_url", "URLs with embedded credentials are not accepted.")
    if not parts.hostname:
        raise UnsafeURLError("invalid_url", "URL must include a hostname.")
    try:
        port = parts.port or (443 if scheme == "https" else 80)
    except ValueError as exc:
        raise UnsafeURLError("invalid_url", "URL port is not a valid number.") from exc

    host = parts.hostname.rstrip(".").lower()
    try:
        ascii_host = host.encode("idna").decode("ascii") if not _is_ip_literal(host) else host
    except UnicodeError as exc:
        raise UnsafeURLError("invalid_url", "Hostname is not a valid internationalised domain name.") from exc

    fixture = local_fixture_port is not None and ascii_host == "127.0.0.1" and port == local_fixture_port and scheme == "http"
    if not fixture:
        if port not in allowed_ports:
            raise UnsafeURLError("port_not_allowed", f"Port {port} is not allowed. Allowed ports: {', '.join(map(str, allowed_ports))}.")
        single_label = "." not in ascii_host and not _is_ip_literal(ascii_host)
        if ascii_host in BLOCKED_HOSTS or ascii_host.endswith(BLOCKED_HOST_SUFFIXES) or single_label:
            raise UnsafeURLError("non_public_host", f"Hostname '{ascii_host}' is not a public internet host.")

    if _is_ip_literal(ascii_host):
        addresses = [str(ipaddress.ip_address(ascii_host))]
    else:
        try:
            addresses = resolver(ascii_host, port)
        except (OSError, UnicodeError) as exc:
            raise UnsafeURLError("dns_resolution_failed", f"Hostname '{ascii_host}' could not be resolved.") from exc
        if not addresses:
            raise UnsafeURLError("dns_resolution_failed", f"Hostname '{ascii_host}' did not resolve to any address.")

    if not fixture:
        for addr in addresses:
            if not is_public_ip(ipaddress.ip_address(addr)):
                # Every answer must be public: a mixed answer set is a rebinding red flag.
                raise UnsafeURLError("non_public_address", f"Hostname '{ascii_host}' resolves to a non-public address ({addr}).")

    netloc = f"[{ascii_host}]" if ":" in ascii_host else ascii_host
    if parts.port is not None and not (scheme == "https" and port == 443 or scheme == "http" and port == 80):
        netloc += f":{port}"
    path = parts.path or "/"
    normalised = urllib.parse.urlunsplit((scheme, netloc, path, parts.query, ""))
    return ValidatedURL(url=normalised, host=ascii_host, resolved_addresses=tuple(addresses))


def _is_ip_literal(host: str) -> bool:
    try:
        ipaddress.ip_address(host)
        return True
    except ValueError:
        return False
