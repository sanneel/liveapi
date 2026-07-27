#!/usr/bin/env python3
"""
Run this to see what HTML Playwright actually gets from jugabet.cl.
Usage: python debug_html.py
"""
from playwright.sync_api import sync_playwright

URL = "https://jugabet.cl/football/prematch/1"

with sync_playwright() as p:
    # Connect to Brave running with --remote-debugging-port=9222
    browser = p.chromium.connect_over_cdp("http://127.0.0.1:9222")
    context = browser.new_context(timezone_id="America/Santiago")
    page = context.new_page()

    print(f"Loading {URL} ...")
    page.goto(URL, wait_until="domcontentloaded", timeout=30000)

    # Try waiting for event cards
    try:
        page.wait_for_selector("div.event-card", timeout=15000)
        print("Found div.event-card elements!")
    except Exception:
        print("TIMEOUT: div.event-card not found after 15 seconds")

    page.wait_for_timeout(2000)
    html = page.content()

    # Count event cards
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, "html.parser")
    cards = soup.select("div.event-card")
    print(f"\nEvent cards found: {len(cards)}")

    # Show first 300 chars of body text to see what the page actually shows
    body = soup.find("body")
    body_text = body.get_text(" ", strip=True)[:500] if body else ""
    print(f"\nPage text preview:\n{body_text}")

    # Show page title
    title = soup.find("title")
    print(f"\nPage title: {title.get_text() if title else 'none'}")

    # Check for any divs that might be event containers
    print(f"\nDivs with 'event' in class: {len(soup.select('[class*=event]'))}")
    print(f"Divs with 'card' in class: {len(soup.select('[class*=card]'))}")

    # Save full HTML for inspection
    with open("debug_output.html", "w", encoding="utf-8") as f:
        f.write(html)
    print("\nFull HTML saved to debug_output.html")

    context.close()
    browser.close()
