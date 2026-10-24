#!/usr/bin/env python3
"""Reproduction for D15 (fixed 2026-10-25; kept as a standalone check). Not collected by the test suites.

Before the fix, analyze_redirect_chain() read `_redirect_chain` and `_final_url` only
`if isinstance(response_headers, dict)`. fetch_url() returns response.info(), an http.client.HTTPMessage,
so on live sites the redirect chain was never analysed: a 3-hop chain was reported as 0 hops / pass.
Same defect class as D14. Regression tests: tests/test_engine_fixes.py::TestRedirectChainHeaders and
::TestRedirectChainLiveFetch.

    python tests/repro_d15_redirect_chain.py      # exit 1 if D15 is present, exit 0 when fixed
"""

import email
import http.client
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "skills" / "crawl-render-audit" / "scripts"))
import check_technical  # noqa: E402

REQUESTED = "https://example.com/start"
CHAIN = [{"from": f"https://example.com/{i}", "to": f"https://example.com/{i + 1}", "status": 301} for i in range(3)]


def production_headers():
    """Built exactly as fetch_url builds them."""
    message = email.message_from_string("Content-Type: text/html\n\n", _class=http.client.HTTPMessage)
    message["_final_url"] = "https://example.com/3"
    message["_redirect_chain"] = CHAIN
    return message


def main() -> int:
    as_dict = check_technical.analyze_redirect_chain(REQUESTED, {"_final_url": "https://example.com/3", "_redirect_chain": CHAIN})
    as_live = check_technical.analyze_redirect_chain(REQUESTED, production_headers())
    print(f"dict headers (test-mock shape): status={as_dict['status']} hops={as_dict['hops']} final={as_dict['final_url']}")
    print(f"HTTPMessage (production shape): status={as_live['status']} hops={as_live['hops']} final={as_live['final_url']}")
    if (as_live["status"], as_live["hops"], as_live["final_url"]) != (as_dict["status"], as_dict["hops"], as_dict["final_url"]):
        print("D15 PRESENT: production-shaped headers lose the redirect chain.")
        return 1
    print("D15 not reproduced: both header shapes give the same result.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
