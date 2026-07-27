"""
debug_fetch.py v2 — wait for Angular to hydrate, then dump the real event structure.

Run on VPS:
  python3 debug_fetch.py [url]
  python3 debug_fetch.py  # defaults to football/prematch/1
"""

import sys
import json
import re
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

URL = sys.argv[1] if len(sys.argv) > 1 else "https://jugabet.cl/football/prematch/1"
TIMEOUT = 45_000

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
            if "json" in ct or any(s in url_l for s in ("api/v", "filter", "market", "odds", "graphql", "event", "sport")):
                try:
                    body = resp.body()
                    blen = len(body)
                except Exception:
                    body = b""
                    blen = -1
                snippet = body[:400].decode("utf-8", errors="replace") if body else ""
                xhr_hits.append({
                    "status": resp.status,
                    "url": resp.url,
                    "len": blen,
                    "snippet": snippet,
                })
                print(f"  [XHR] {resp.status} len={blen} {resp.url}", flush=True)
        except Exception:
            pass

    page.on("response", on_response)

    try:
        page.goto(URL, wait_until="domcontentloaded", timeout=TIMEOUT)
    except PWTimeout:
        print("[DEBUG] page.goto timed out; reading whatever loaded", flush=True)

    # Try to wait for any known sport event container selector
    possible_selectors = [
        "div.event-card",
        "app-prematch-game-events",
        "app-sport-events-widget",
        "div[class*='event-card']",
        "div[class*='prematch']",
        "div[class*='sport-event']",
        "div[data-event-card-id]",
        "a[data-id='event-card']",
        "div[data-id='event-card']",
        "[data-event-card-id]",
        "[data-event-stage]",
        "div.event-list",
        "div.events-list",
        "div.event-item",
        "div.match-card",
        "div.match-item",
        "app-game-event",
        "app-event-card",
    ]

    found_selector = None
    for sel in possible_selectors:
        try:
            page.wait_for_selector(sel, timeout=2000)
            found_selector = sel
            print(f"[DEBUG] Found selector: {sel}", flush=True)
            break
        except PWTimeout:
            pass

    if not found_selector:
        print("[DEBUG] None of the candidate selectors matched after 2s each; waiting 15s for Angular...", flush=True)
        page.wait_for_timeout(15000)
    else:
        page.wait_for_timeout(3000)

    # Try to wait for networkidle briefly
    try:
        page.wait_for_load_state("networkidle", timeout=10000)
    except PWTimeout:
        pass

    # Scroll to trigger lazy loading
    try:
        for _ in range(5):
            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            page.wait_for_timeout(1500)
    except Exception:
        pass

    page.wait_for_timeout(3000)

    html = page.content()

    # Check counts of candidates
    print("\n[DEBUG] SELECTOR COUNTS IN FINAL HTML:")
    check_selectors = [
        "div.event-card",
        "[data-event-card-id]",
        "[data-event-stage]",
        "a[data-id='event-card']",
        "app-sport-events-widget",
        "app-prematch-game-events",
        "app-game-event",
        "div[class*='event']",
        "div[class*='match']",
    ]
    for sel in check_selectors:
        try:
            count = page.locator(sel).count()
            print(f"  {sel!r}: {count}")
        except Exception as e:
            print(f"  {sel!r}: ERROR {e}")

    # Dump innerHTML of sport events widget
    print("\n[DEBUG] innerHTML of app-sport-events-widget (first 3000 chars):")
    try:
        inner = page.locator("app-sport-events-widget").first.inner_html()
        print(inner[:3000])
    except Exception as e:
        print(f"  ERROR: {e}")

    # Dump first 500 chars of first app-game-event if it exists
    print("\n[DEBUG] First app-game-event innerHTML:")
    try:
        inner2 = page.locator("app-game-event").first.inner_html()
        print(inner2[:2000])
    except Exception as e:
        print(f"  ERROR: {e}")

    # Find ALL unique class names, tags from final HTML
    all_classes = set()
    for m in re.finditer(r'class=["\']([^"\']+)["\']', html):
        for cls in m.group(1).split():
            all_classes.add(cls)

    tags = set(re.findall(r'<([a-zA-Z][a-zA-Z0-9-]*)', html))
    custom_tags = sorted(t for t in tags if "-" in t)

    event_classes = sorted(c for c in all_classes if any(
        kw in c.lower() for kw in ("event", "card", "match", "sport", "odds", "market", "outcome", "competitor", "game-event")
    ))

    print(f"\n[DEBUG] FINAL HTML LENGTH: {len(html)}")
    print(f"\n[DEBUG] CUSTOM/ANGULAR TAGS ({len(custom_tags)}):")
    for t in custom_tags:
        print(f"  <{t}>")

    print(f"\n[DEBUG] EVENT/MATCH/ODDS CLASSES ({len(event_classes)}):")
    for c in event_classes[:80]:
        print(f"  .{c}")

    print(f"\n[DEBUG] ALL UNIQUE CLASSES (first 120):")
    for c in sorted(all_classes)[:120]:
        print(f"  .{c}")

    # All XHR hits with non-empty JSON bodies > 10 bytes
    print(f"\n[DEBUG] XHR HITS WITH BODY > 10 bytes:")
    for x in xhr_hits:
        if x["len"] > 10:
            print(f"  [{x['status']}] len={x['len']} {x['url'][:120]}")
            if x["snippet"] and x["len"] < 5000:
                print(f"    BODY: {x['snippet'][:300]}")

    # Find any data attributes on first real elements that might be event data
    print(f"\n[DEBUG] Elements with data-event* attributes:")
    for m in re.finditer(r'<[^>]+(data-event[^>]*?)>', html[:50000]):
        print(f"  {m.group(0)[:200]}")
        if len(list(re.finditer(r'<[^>]+data-event', html[:50000]))) > 20:
            break

    context.close()
    browser.close()

print("\n[DEBUG] done.")
