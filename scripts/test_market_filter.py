#!/usr/bin/env python3
"""
Test whether POST /api/v2/markets/by-market-filter returns the prematch odds
snapshot when given the page's real eventIds (the app sends it empty -> {}).
If it returns odds, that's the clean, complete, fast prematch odds source.

Run on the VPS:
    ./.venv/bin/python scripts/test_market_filter.py "https://jugabet.cl/football/prematch/1"
"""
from __future__ import annotations
import json
import sys
from playwright.sync_api import sync_playwright

URL = sys.argv[1] if len(sys.argv) > 1 else "https://jugabet.cl/football/prematch/1"

with sync_playwright() as p:
    b = p.chromium.launch(headless=True)
    ctx = b.new_context(locale="es-CL", timezone_id="America/Santiago",
                        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                                   "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")
    page = ctx.new_page()
    page.goto(URL, wait_until="domcontentloaded", timeout=45000)
    try:
        page.wait_for_selector("div.event-card", timeout=25000)
    except Exception:
        pass
    page.wait_for_timeout(3000)

    event_ids = page.evaluate(
        "() => Array.from(document.querySelectorAll('div.event-card[data-event-card-id]'))"
        ".map(c => c.getAttribute('data-event-card-id')).filter(Boolean)"
    )
    print(f"event ids on page: {len(event_ids)} -> {event_ids[:6]}")

    # Try the by-market-filter POST with real eventIds, a couple of body shapes.
    for body in (
        {"eventIds": event_ids, "sportId": "", "stage": 1},
        {"eventIds": event_ids[:20], "sportId": "", "stage": 1},
        {"eventIds": event_ids[:20], "stage": 1},
    ):
        res = page.evaluate(
            """async (body) => {
                try {
                    const r = await fetch('/api/v2/markets/by-market-filter', {
                        method:'POST', headers:{'Content-Type':'application/json'},
                        credentials:'include', body: JSON.stringify(body)
                    });
                    const t = await r.text();
                    return {status:r.status, len:t.length, body:t.slice(0, 2500)};
                } catch(e){ return {error:String(e)}; }
            }""",
            body,
        )
        print(f"\n--- POST by-market-filter  eventIds={len(body.get('eventIds', []))} keys={list(body.keys())}")
        print(json.dumps(res, ensure_ascii=False)[:2800])

    b.close()
