"""Find the PREMATCH odds source.

The WS carries 0 prematch odds frames (live-only channel), so the price must
ride in an XHR. Prime suspect: the RESPONSE body of POST
/api/v1/reactive-outcomes/subscribe — the page subscribes and the call likely
returns the current price snapshot, with the WS only streaming later changes.

This loads the World Cup overlay, scrolls to trigger the Angular subscriptions,
and prints the body of every odds-ish response inline (method, status, length,
first ~1.1k chars) so we can read the exact JSON shape of prematch prices.

Run on the VPS:
    cd /home/admin/staging_html && .venv/bin/python scripts/probe_prematch_source.py
"""

from __future__ import annotations

from playwright.sync_api import TimeoutError as PWTimeout
from playwright.sync_api import sync_playwright

OVERLAY = (
    "https://jugabet.cl/football/all/1"
    "?tournaments=c19cb5ffb4404c31b869b53dd90161de"  # FIFA World Cup 2026
)
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)
TZ = "America/Santiago"

# url substrings worth inspecting for a price snapshot
INTEREST = ("reactive-outcome", "subscribe", "market", "outcome", "/odd", "filter", "price")


def main() -> None:
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        ctx = browser.new_context(user_agent=UA, locale="es-CL", timezone_id=TZ)
        page = ctx.new_page()

        hits: list = []

        def on_resp(resp):
            u = resp.url.lower()
            if not any(s in u for s in INTEREST):
                return
            try:
                body = resp.body() or b""
            except Exception:
                body = b""
            snippet = body[:1100].decode("utf-8", "ignore").replace("\n", " ")
            try:
                method = resp.request.method
            except Exception:
                method = "?"
            hits.append((method, resp.status, len(body), resp.url, snippet))

        page.on("response", on_resp)
        page.goto(OVERLAY, wait_until="domcontentloaded", timeout=60_000)
        try:
            page.wait_for_selector("div.event-card", timeout=30_000)
        except PWTimeout:
            print("PROBE: no event cards on overlay")
            browser.close()
            return

        # Scroll through the cards so Angular fires the per-card subscriptions.
        for _ in range(10):
            page.mouse.wheel(0, 700)
            page.wait_for_timeout(500)
        page.wait_for_timeout(5000)

        print(f"=== {len(hits)} odds-ish responses ===")
        for i, (method, status, length, url, snippet) in enumerate(hits):
            print(f"\n[{i}] {method} {status} len={length} {url}")
            if length:
                print("    " + snippet[:1000])
        browser.close()


if __name__ == "__main__":
    main()
