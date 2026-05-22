#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Run this script ONCE to discover the real jugabet.cl API URLs.
It opens each feed page in a headless browser, captures every API call,
and saves the results to api_urls_discovered.json.

Usage:
    python discover_api_urls.py

Output:
    api_urls_discovered.json  — URLs + one sample response body per URL pattern

Once you have the URLs, paste them into server_v2.py.
"""

import json
import time
from pathlib import Path
from playwright.sync_api import sync_playwright

SITE_BASE = "https://jugabet.cl"
TIMEOUT_MS = 30_000
JS_SETTLE_MS = 2000

FEEDS_TO_PROBE = [
    f"{SITE_BASE}/football/prematch/1",
    f"{SITE_BASE}/football/live/1",
    f"{SITE_BASE}/basketball/prematch/1",
    f"{SITE_BASE}/tennis/prematch/1",
]

OUTPUT_FILE = Path(__file__).parent / "api_urls_discovered.json"

# URL substrings that indicate an odds/events API call
INTERESTING_PATTERNS = [
    "by-market-filter",
    "by-sport-filter",
    "events",
    "markets",
    "odds",
    "sport",
    "/api/",
    "sportsbook",
]


def is_interesting(url: str) -> bool:
    u = url.lower()
    return any(p in u for p in INTERESTING_PATTERNS) and "cdn" not in u and "static" not in u


def probe_page(page, url: str) -> dict:
    captured = {}

    def on_response(response):
        try:
            ru = response.url
            if not is_interesting(ru):
                return
            ct = response.headers.get("content-type", "")
            if "json" not in ct:
                return
            try:
                body = response.json()
            except Exception:
                return
            if ru not in captured:
                print(f"  [CAPTURED] {ru}")
                captured[ru] = body
        except Exception:
            pass

    page.on("response", on_response)

    print(f"\nProbing: {url}")
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=TIMEOUT_MS)
        page.wait_for_timeout(JS_SETTLE_MS)
    except Exception as e:
        print(f"  [WARN] page load error: {e}")

    page.remove_listener("response", on_response)
    return captured


def main():
    all_captured: dict = {}

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            timezone_id="America/Santiago",
            ignore_https_errors=False,
        )
        page = context.new_page()

        for feed_url in FEEDS_TO_PROBE:
            result = probe_page(page, feed_url)
            all_captured.update(result)
            time.sleep(1)

        context.close()
        browser.close()

    print(f"\n\nTotal unique API URLs captured: {len(all_captured)}")

    # Summarize: just URLs + first 200 chars of response for readability
    summary = {}
    for url, body in all_captured.items():
        body_str = json.dumps(body)
        summary[url] = {
            "response_preview": body_str[:500] + ("..." if len(body_str) > 500 else ""),
            "response_type": type(body).__name__,
            "response_keys": list(body.keys())[:10] if isinstance(body, dict) else None,
        }

    OUTPUT_FILE.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Saved to: {OUTPUT_FILE}")
    print("\nURL list:")
    for url in all_captured:
        print(f"  {url}")


if __name__ == "__main__":
    main()
