"""Local-only exposure guard (security-hardening phase 1).

The platform has no authentication, so it is only safe when nothing but the local machine can
reach it. This ASGI middleware enforces that for every HTTP request, independently of how the
server was started:

- the client and the listening interface must both be loopback addresses (a server started with
  ``--host 0.0.0.0`` still refuses LAN clients);
- the Host header must name a loopback host, which defeats DNS-rebinding pages whose own domain
  has been re-pointed at 127.0.0.1;
- requests that can change state must not come from a foreign Origin (cross-site request forgery);
- browser requests marked cross-site or same-site by Sec-Fetch-Site are refused unless they come from an explicitly
  configured origin or are a top-level navigation to a UI page (security phase 7, M2);
- a request body must be ``application/json`` (a body without a Content-Type is a CORS "simple
  request" that browsers send cross-site without a preflight);
- a request body may not exceed ``max_body_bytes``, checked from Content-Length and while reading.

Nothing here reads environment variables: there is deliberately no switch that re-enables remote
access, because remote deployment is unsupported until real authentication exists.
"""

from __future__ import annotations

import ipaddress
import json
import urllib.parse

from .logging_setup import request_id_var

LOOPBACK_HOSTNAMES = frozenset({"localhost", "127.0.0.1", "::1"})
SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
DEFAULT_MAX_BODY_BYTES = 64 * 1024


def is_loopback_host(host: str | None) -> bool:
    """True for 'localhost' or a loopback IP literal (any of 127.0.0.0/8, ::1, IPv4-mapped loopback)."""
    if not host:
        return False
    host = host.strip().lower()
    if host.startswith("[") and host.endswith("]"):
        host = host[1:-1]
    if host == "localhost":
        return True
    try:
        ip = ipaddress.ip_address(host.split("%")[0])
    except ValueError:
        return False
    if ip.version == 6 and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    return ip.is_loopback


def host_header_name(value: str) -> str | None:
    """Hostname part of a Host header ('[::1]:8000' -> '::1', 'localhost:5173' -> 'localhost')."""
    value = value.strip().lower()
    if not value:
        return None
    if value.startswith("["):
        end = value.find("]")
        if end == -1 or (len(value) > end + 1 and value[end + 1] != ":"):
            return None
        return value[1:end]
    name, _, port = value.partition(":")
    if port and not port.isdigit():
        return None
    return name or None


def is_loopback_origin(origin: str) -> bool:
    parts = urllib.parse.urlsplit(origin.strip())
    return parts.scheme in ("http", "https") and parts.hostname in LOOPBACK_HOSTNAMES and not parts.path.strip("/")


def origin_key(origin: str) -> tuple[str, str, int] | None:
    """(scheme, host, port) of a serialized origin such as 'http://localhost:5173', with the default port filled in;
    None for 'null', a path, credentials or anything that is not an http(s) origin."""
    parts = urllib.parse.urlsplit(origin.strip())
    try:
        port = parts.port
    except ValueError:
        return None
    if parts.scheme not in ("http", "https") or not parts.hostname or parts.path.strip("/") or parts.query \
            or parts.fragment or parts.username is not None or parts.password is not None:
        return None
    return parts.scheme, parts.hostname, port or (443 if parts.scheme == "https" else 80)


def is_ui_page_path(path: str) -> bool:
    """A client-side UI route such as /, /dashboard or /audits/<id>: not the API and not a file (no '.' in the last
    segment), so a cross-site link may open it as a page but never fetch an asset, export or API response."""
    return path.startswith("/") and not (path == "/api" or path.startswith("/api/")) and "." not in path.rsplit("/", 1)[-1]


def _headers(scope) -> dict[str, str]:
    out: dict[str, str] = {}
    for raw_name, raw_value in scope.get("headers") or []:
        out.setdefault(raw_name.decode("latin-1").lower(), raw_value.decode("latin-1"))
    return out


class ExposureGuard:
    def __init__(self, app, max_body_bytes: int = DEFAULT_MAX_BODY_BYTES, allowed_origins=()):
        self.app = app
        self.max_body_bytes = max_body_bytes
        # Explicitly configured loopback origins (BRAND_PLATFORM_CORS_ORIGINS, empty by default).
        self.allowed_origins = {k for k in map(origin_key, allowed_origins) if k is not None}

    def cross_site_refusal(self, scope, headers: dict[str, str], method: str) -> tuple[str, str] | None:
        """Security phase 7 (M2). Returns (code, message) to refuse the request, or None to let it through.

        These checks only stop *browsers* from acting for other websites; they do not authenticate anything, and any
        local program can send whatever headers it likes (the platform is local-only and unauthenticated by design)."""
        origin = headers.get("origin")
        if method not in SAFE_METHODS and origin is not None:
            # The server's own origin comes from the Host header, already validated as loopback. Through the Vite
            # proxy that is the dev server's origin (it forwards Host unchanged), so the proxied UI matches too.
            key = origin_key(origin)
            own = origin_key(f"{scope.get('scheme', 'http')}://{headers.get('host', '')}")
            if key is None or (key != own and key not in self.allowed_origins):
                return "cross_origin_forbidden", "Requests from other websites are not accepted."
        site = headers.get("sec-fetch-site")
        if site is None:
            # No Fetch Metadata: curl, scripts and older browsers. This proves nothing about safety; the request is
            # left to the Origin rule above, the JSON-body rule and CORS, as before M2 (the documented curl contract).
            return None
        site = site.strip().lower()
        if site in ("same-origin", "none") and method not in SAFE_METHODS and origin is None:
            return "cross_site_forbidden", "Requests from other websites are not accepted."  # browsers always send it
        if site == "same-origin":
            return None
        if site == "none":  # typed into the address bar, a bookmark: reads only
            if method in ("GET", "HEAD"):
                return None
        elif site in ("same-site", "cross-site"):
            if origin is not None and origin_key(origin) in self.allowed_origins:
                return None
            if (method in ("GET", "HEAD") and headers.get("sec-fetch-mode", "").strip().lower() == "navigate"
                    and headers.get("sec-fetch-dest", "").strip().lower() == "document"
                    and is_ui_page_path(scope.get("path", ""))):
                return None  # a link from another app to a UI page; framing is still denied by the security headers
        return "cross_site_forbidden", "Requests from other websites are not accepted."

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        headers = _headers(scope)
        method = scope.get("method", "GET").upper()

        client = scope.get("client")
        server = scope.get("server")
        if not client or not is_loopback_host(client[0]) or (server and not is_loopback_host(str(server[0]))):
            await _reject(send, 403, "remote_client_forbidden",
                          "This service accepts connections from the local machine only.")
            return
        if host_header_name(headers.get("host", "")) not in LOOPBACK_HOSTNAMES:
            await _reject(send, 400, "invalid_host", "The Host header must name localhost, 127.0.0.1 or [::1].")
            return
        refusal = self.cross_site_refusal(scope, headers, method)
        if refusal:
            await _reject(send, 403, *refusal)
            return

        declared = headers.get("content-length")
        if declared is not None:
            if not declared.strip().isdigit():
                await _reject(send, 400, "invalid_content_length", "Content-Length is not a valid number.")
                return
            if int(declared) > self.max_body_bytes:
                await _reject(send, 413, "payload_too_large", f"Request bodies are limited to {self.max_body_bytes} bytes.")
                return

        body, too_large = await _read_body(receive, self.max_body_bytes)
        if too_large:
            await _reject(send, 413, "payload_too_large", f"Request bodies are limited to {self.max_body_bytes} bytes.")
            return
        if body:
            media_type = headers.get("content-type", "").split(";", 1)[0].strip().lower()
            if media_type != "application/json":
                await _reject(send, 415, "unsupported_media_type", "Request bodies must be sent as application/json.")
                return

        await self.app(scope, _replay(body, receive), send)


async def _read_body(receive, limit: int) -> tuple[bytes, bool]:
    chunks, size = [], 0
    while True:
        message = await receive()
        if message["type"] == "http.disconnect":
            break
        chunk = message.get("body", b"")
        size += len(chunk)
        if size > limit:
            return b"", True
        chunks.append(chunk)
        if not message.get("more_body", False):
            break
    return b"".join(chunks), False


def _replay(body: bytes, receive):
    sent = False

    async def replayed():
        nonlocal sent
        if not sent:
            sent = True
            return {"type": "http.request", "body": body, "more_body": False}
        return await receive()

    return replayed


async def _reject(send, status: int, code: str, message: str) -> None:
    payload = json.dumps({"error": {"code": code, "message": message, "request_id": request_id_var.get()}}).encode()
    await send({"type": "http.response.start", "status": status,
                "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(payload)).encode())]})
    await send({"type": "http.response.body", "body": payload})
