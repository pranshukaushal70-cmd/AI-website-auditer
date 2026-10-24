"""Safe launcher: ``python -m brand_platform [--host 127.0.0.1] [--port 8000]``.

Binds to loopback only and refuses any other interface: the platform has no authentication, so
public or LAN deployment is unsupported. Proxy headers are ignored, so a client cannot choose the
address the rate limiter sees by sending X-Forwarded-For. The in-app ExposureGuard enforces the
same local-only rule even if the server is started some other way.
"""

from __future__ import annotations

import argparse
import sys

from .exposure import is_loopback_host

UVICORN_OPTIONS = {"proxy_headers": False, "server_header": False, "forwarded_allow_ips": ""}


def parse_args(argv=None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="python -m brand_platform", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--host", default="127.0.0.1", help="loopback address to bind (default 127.0.0.1)")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args(argv)
    if not is_loopback_host(args.host):
        parser.error(f"refusing to bind {args.host!r}: only loopback addresses are supported because the platform "
                     "has no authentication (see docs/SECURITY.md)")
    if not 1 <= args.port <= 65535:
        parser.error("--port must be between 1 and 65535")
    return args


def main(argv=None, run=None) -> int:
    args = parse_args(argv)
    if run is None:
        import uvicorn
        run = uvicorn.run
    from .main import app
    run(app, host=args.host, port=args.port, **UVICORN_OPTIONS)
    return 0


if __name__ == "__main__":
    sys.exit(main())
