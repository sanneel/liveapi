"""Capture the EXACT request jugabet's page makes to the old odds API.

For the CTO: dumps method + URL + request headers + request body + response
body for the odds-related calls, so the breakage is reproducible verbatim.

Targets:
  POST /api/v2/markets/by-market-filter   (old odds API — now returns {})
  POST /api/v1/reactive-outcomes/subscribe (live WS subscribe — returns ack only)

Run on the VPS:
    cd /home/admin/staging_html && .venv/bin/python scripts/probe_capture_request.py
"""

from __future__ import annotations

from playwright.sync_api import TimeoutError as PWTimeout
from playwright.sync_api import sync_playwright

URL = "https://jugabet.cl/football/prematch/1"
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)
TZ = "America/Santiago"
TARGETS = ("by-market-filter", "reactive-outcomes/subscribe", "by-sport-filter")

INTERESTING_HEADERS = (
    "content-type", "accept", "x-app-version", "x-platform", "authorization",
    "x-request-id", "origin", "referer", "x-language", "x-brand",
)


def main() -> None:
    captured = []

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        ctx = browser.new_context(user_agent=UA, locale="es-CL", timezone_id=TZ)
        page = ctx.new_page()

        def on_response(resp):
            url = resp.url
            if not any(t in url for t in TARGETS):
                return
            req = resp.request
            try:
                body = (resp.body() or b"")[:600].decode("utf-8", "ignore")
            except Exception:
                body = "<unreadable>"
            hdrs = {}
            try:
                for k, v in (req.headers or {}).items():
                    if k.lower() in INTERESTING_HEADERS:
                        hdrs[k] = v
            except Exception:
                pass
            captured.append({
                "method": req.method,
                "url": url,
                "status": resp.status,
                "req_headers": hdrs,
                "req_body": (req.post_data or "")[:1200],
                "resp_body": body,
            })

        page.on("response", on_response)
        page.goto(URL, wait_until="domcontentloaded", timeout=60_000)
        try:
            page.wait_for_selector("div.event-card", timeout=30_000)
        except PWTimeout:
            pass
        # scroll so the app fires its odds/subscribe calls
        for _ in range(8):
            page.mouse.wheel(0, 700)
            page.wait_for_timeout(500)
        page.wait_for_timeout(4000)
        browser.close()

    print(f"==== captured {len(captured)} odds-related requests ====")
    for i, c in enumerate(captured):
        print(f"\n[{i}] {c['method']} {c['url']}")
        print(f"     status        : {c['status']}")
        print(f"     req headers   : {c['req_headers']}")
        print(f"     REQUEST BODY  : {c['req_body'] or '<empty>'}")
        print(f"     RESPONSE BODY : {c['resp_body'] or '<empty>'}")


if __name__ == "__main__":
    main()
