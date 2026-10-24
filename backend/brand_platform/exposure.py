"""Local-only exposure guard (security-hardening phase 1).

The platform has no authentication, so it is only safe when nothing but the local machine can
reach it. This ASGI middleware enforces that for every HTTP request, independently of how the
server was started:

- the client and the listening interface must both be loopback addresses (a server started with
  ``--host 0.0.0.0`` still refuses LAN clients);
- the Host header must name a loopback host, which defeats DNS-rebinding pages whose own domain
  has been re-pointed at 127.0.0.1;
- requests that can change state must not come from a foreign Origin (cross-site request forgery);
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


def _headers(scope) -> dict[str, str]:
    out: dict[str, str] = {}
    for raw_name, raw_value in scope.get("headers") or []:
        out.setdefault(raw_name.decode("latin-1").lower(), raw_value.decode("latin-1"))
    return out


class ExposureGuard:
    def __init__(self, app, max_body_bytes: int = DEFAULT_MAX_BODY_BYTES):
        self.app = app
        self.max_body_bytes = max_body_bytes

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
        origin = headers.get("origin")
        if method not in SAFE_METHODS and origin is not None and not is_loopback_origin(origin):
            await _reject(send, 403, "cross_origin_forbidden", "Requests from other websites are not accepted.")
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
