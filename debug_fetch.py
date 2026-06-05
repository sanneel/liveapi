"""
Quick debug: fetch one Jugabet page with Playwright and print:
  - page title
  - all unique CSS class names found in the DOM
  - first 3000 chars of page HTML
  - first 3000 chars of any XHR/API responses that fire

Run on VPS:
  python3 debug_fetch.py [url]
  python3 debug_fetch.py  # defaults to football/live/1
"""

import sys
import json
import re
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

URL = sys.argv[1] if len(sys.argv) > 1 else "https://jugabet.cl/football/prematch/1"
TIMEOUT = 30_000

print(f"[DEBUG] Fetching: {URL}", flush=True)

xhr_hits = []

with sync_playwright() as pw:
    browser = pw.chromium.launch(headless=True)
    context = browser.new_context(
        user_agent=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        locale="es-CL",
        timezone_id="America/Santiago",
    )
    page = context.new_page()

    def on_response(resp):
        try:
            ct = (resp.headers or {}).get("content-type", "")
            url_l = resp.url.lower()
            if "json" in ct or any(s in url_l for s in ("api", "filter", "market", "odds", "graphql", "event")):
                try:
                    body = resp.body()
                    blen = len(body)
                except Exception:
                    body = b""
                    blen = -1
                snippet = body[:300].decode("utf-8", errors="replace") if body else ""
                xhr_hits.append({
                    "status": resp.status,
                    "url": resp.url,
                    "len": blen,
                    "snippet": snippet,
                })
                print(f"  [XHR] {resp.status} len={blen} {resp.url}", flush=True)
        except Exception as e:
            pass

    page.on("response", on_response)

    try:
        page.goto(URL, wait_until="domcontentloaded", timeout=TIMEOUT)
    except PWTimeout:
        print("[DEBUG] page.goto timed out; reading whatever loaded", flush=True)

    # Wait a bit for JS to render
    page.wait_for_timeout(5000)

    html = page.content()
    title = page.title()

    # Collect all unique class tokens
    all_classes = set()
    for m in re.finditer(r'class=["\']([^"\']+)["\']', html):
        for cls in m.group(1).split():
            all_classes.add(cls)

    # Find all tag names used in the body
    tags = set(re.findall(r'<([a-z][a-z0-9-]*)', html))

    # Look for event-like classes
    event_classes = sorted(c for c in all_classes if any(
        kw in c for kw in ("event", "card", "match", "sport", "odds", "market", "outcome", "competitor")
    ))

    print(f"\n{'='*60}")
    print(f"PAGE TITLE: {title}")
    print(f"HTML LENGTH: {len(html)}")
    print(f"\nEVENT/CARD/ODDS RELATED CLASSES ({len(event_classes)}):")
    for c in event_classes[:60]:
        print(f"  .{c}")

    print(f"\nALL UNIQUE CLASS TOKENS (first 80):")
    for c in sorted(all_classes)[:80]:
        print(f"  .{c}")

    print(f"\nTAGS FOUND: {', '.join(sorted(tags)[:40])}")

    print(f"\nXHR API HITS ({len(xhr_hits)}):")
    for x in xhr_hits:
        print(f"  [{x['status']}] {x['url'][:120]}")
        if x["snippet"]:
            print(f"       BODY: {x['snippet'][:200]}")

    print(f"\nFIRST 4000 CHARS OF HTML:")
    print(html[:4000])

    context.close()
    browser.close()

print("\n[DEBUG] done.")
