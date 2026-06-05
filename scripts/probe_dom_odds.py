"""Decisive test: are prematch odds in the HTML/DOM (parseable) or not?

Two competing claims:
  - report says odds are in the server-rendered HTML snapshot (parse with BS4)
  - our WS probe says prematch odds never hit the WebSocket

This checks BOTH sources for the World Cup overlay:
  A) RAW HTTP GET (urllib, no JS) — does the response BODY already contain
     event cards and decimal odds? (tests the "requests+BeautifulSoup" claim)
  B) RENDERED DOM (Playwright, after Angular hydration) — for the first few
     cards, dump visible text, any odds-ish elements, and every X.XX number.

If (B) shows odds, the fix is to parse them from the DOM (works for prematch).
If neither shows odds, the price rides in an XHR and we go capture that next.

Run on the VPS:
    cd /home/admin/staging_html && .venv/bin/python scripts/probe_dom_odds.py
"""

from __future__ import annotations

import re
import urllib.request

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

ODDS_RE = re.compile(r"\b\d+\.\d{2}\b")


def raw_http_test() -> None:
    print("=== A) RAW HTTP (urllib, no JS) ===")
    req = urllib.request.Request(OVERLAY, headers={"User-Agent": UA, "Accept-Language": "es-CL"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            html = r.read().decode("utf-8", "ignore")
    except Exception as e:  # noqa: BLE001
        print(f"   raw GET failed: {e!r}")
        return
    print(f"   bytes={len(html)}")
    print(f"   contains 'event-card'      : {'event-card' in html}")
    print(f"   contains 'app-sport-events': {'app-sport-events' in html}")
    print(f"   contains 'cuota'           : {'cuota' in html.lower()}")
    nums = ODDS_RE.findall(html)
    print(f"   X.XX numbers in raw body   : {len(nums)}  sample={nums[:10]}")


def rendered_dom_test() -> None:
    print("\n=== B) RENDERED DOM (Playwright, post-hydration) ===")
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        ctx = browser.new_context(user_agent=UA, locale="es-CL", timezone_id=TZ)
        page = ctx.new_page()
        page.goto(OVERLAY, wait_until="domcontentloaded", timeout=60_000)
        try:
            page.wait_for_selector("div.event-card", timeout=30_000)
        except PWTimeout:
            print("   no event cards rendered")
            browser.close()
            return
        # Give odds a few seconds to paint after cards appear.
        page.wait_for_timeout(6000)

        data = page.evaluate(
            r"""() => {
                const cards = [...document.querySelectorAll('div.event-card')].slice(0, 3);
                return cards.map(c => {
                    const text = (c.innerText || '').replace(/\s+/g, ' ').trim();
                    const oddEls = [...c.querySelectorAll('[class]')]
                        .filter(e => /odd|price|cuota|outcome|selection|market/i.test(e.getAttribute('class') || ''))
                        .slice(0, 15)
                        .map(e => (e.getAttribute('class') || '') + ' => "' + (e.innerText || '').replace(/\s+/g, ' ').trim().slice(0, 30) + '"');
                    const nums = text.match(/\b\d+\.\d{2}\b/g) || [];
                    return { text: text.slice(0, 280), oddEls, nums };
                });
            }"""
        )
        for i, card in enumerate(data):
            print(f"\n   --- card {i} ---")
            print(f"   TEXT: {card['text']}")
            print(f"   X.XX numbers: {card['nums']}")
            print(f"   odds-ish elements ({len(card['oddEls'])}):")
            for line in card["oddEls"]:
                print(f"      {line}")
        browser.close()


def main() -> None:
    raw_http_test()
    rendered_dom_test()


if __name__ == "__main__":
    main()
