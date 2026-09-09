#!/usr/bin/env python3
"""Serve the repo root so the extension's browser tests can fetch their inputs.

The tests are HTML pages rather than Python because what they check is JS
behaviour: that content.js and run_code.js find the admin's script cards, that
seeding a token leaves every generated script parseable, and that a %c-styled
console line comes back out readable. There is no JS runtime on the deploy box, so they run in a
browser.

    python3 extension/tests/serve.py

Then open the three URLs it prints. Every line on each page must read OK.
The invariant the *generators* have to keep is checked in Python instead, by
scripts/test_script_runner.py.
"""
import http.server
import os
import socketserver
from pathlib import Path

PORT = int(os.environ.get("PORT", "8765"))
ROOT = Path(__file__).resolve().parents[2]

PAGES = [
    "content.test.html",
    "seed.test.html",
    "format.test.html",
    "generator.test.html",
    # Not extension code, but the same feature: the CRM-side button that mints
    # a run code so the operator never carries 650 KB through the clipboard.
    "run_code.test.html",
]


class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=str(ROOT), **kw)

    def log_message(self, *a):  # quiet: the page output is the signal
        pass


def main() -> int:
    socketserver.TCPServer.allow_reuse_address = True
    with socketserver.TCPServer(("127.0.0.1", PORT), Handler) as httpd:
        print(f"Serving {ROOT} at http://127.0.0.1:{PORT}\n")
        for page in PAGES:
            print(f"  http://127.0.0.1:{PORT}/extension/tests/{page}")
        print("\nEvery line on every page must read OK. Ctrl-C to stop.")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
