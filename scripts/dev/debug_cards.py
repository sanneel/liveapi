"""
debug_cards.py — dumps first 5 div.event-card elements after proper Angular hydration.

Run on VPS:
  python3 debug_cards.py [url]
"""

import sys
import re
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

URL = sys.argv[1] if len(sys.argv) > 1 else "https://jugabet.cl/football/prematch/1"

print(f"[DEBUG] Fetching: {URL}", flush=True)

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
    page.goto(URL, wait_until="domcontentloaded", timeout=45000)

    # Phase 1: wait for Angular shell
    try:
        page.wait_for_selector("app-sport-events-widget", timeout=8000)
        print("[DEBUG] Phase 1 OK: app-sport-events-widget found", flush=True)
    except PWTimeout:
        print("[DEBUG] Phase 1: no app-sport-events-widget", flush=True)

    # Phase 2: wait for actual cards
    try:
        page.wait_for_selector("div.event-card", timeout=25000)
        print("[DEBUG] Phase 2 OK: div.event-card found", flush=True)
    except PWTimeout:
        print("[DEBUG] Phase 2: no div.event-card after 25s", flush=True)

    # Scroll to load more
    for i in range(5):
        page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        page.wait_for_timeout(1200)

    page.wait_for_timeout(2000)

    count = page.locator("div.event-card").count()
    print(f"\n[DEBUG] Total div.event-card found: {count}", flush=True)

    print("\n[DEBUG] ===== FIRST 3 EVENT CARD HTML =====")
    cards = page.locator("div.event-card").all()
    for i, card in enumerate(cards[:3]):
        try:
            html = card.inner_html()
            print(f"\n--- CARD {i+1} ---")
            print(html[:3000])
        except Exception as e:
            print(f"  ERROR: {e}")

    context.close()
    browser.close()

print("\n[DEBUG] done.")
