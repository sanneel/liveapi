"""Standalone probe: does a single World Cup MATCH DETAIL page yield prematch odds?

Run on the VPS:
    cd /home/admin/staging_html && .venv/bin/python scripts/probe_event_odds.py

Why: live matches get odds (~49%) but prematch World Cup matches almost never
(~6%). Hypothesis: prematch prices are pushed ONCE at subscribe-time over the
Centrifugo WS, and on a crowded list page we lose that race. A single match's
own /events/ detail page forces a fresh, complete subscription with our
collector listening from the first frame.

This probe:
  1. Loads the World Cup overlay, measures odds collected passively, grabs the
     first /events/ detail link.
  2. Opens THAT detail page with the WS collector attached from frame one,
     waits for the one-shot push, and reports what arrived.

If detail >> overlay, the per-event priority lane is the fix. If the detail
page also yields nothing, prematch odds are not WS-pushed on load and we need a
different path (and this probe says so explicitly).
"""

from __future__ import annotations

import json as _json

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


def make_collector():
    """Returns (collected, stats, on_ws). Same WS shape the parser uses:
    push.pub.data.data.customizedOutcome -> {eventId, outcomeType, price}.
    outcomeType 0=home, 1=draw, 3=away (result market)."""
    collected: dict = {}
    stats = {"sockets": 0, "frames": 0, "co_frames": 0}

    def on_ws(ws):
        stats["sockets"] += 1

        def on_frame(payload):
            stats["frames"] += 1
            try:
                text = payload if isinstance(payload, str) else payload.decode("utf-8", "ignore")
            except Exception:
                return
            if "customizedOutcome" not in text:
                return
            stats["co_frames"] += 1
            for line in text.split("\n"):
                line = line.strip()
                if not line or '"push"' not in line:
                    continue
                try:
                    co = _json.loads(line)["push"]["pub"]["data"]["data"]["customizedOutcome"]
                except Exception:
                    continue
                if not isinstance(co, dict):
                    continue
                ot = co.get("outcomeType")
                if ot not in (0, 1, 3):
                    continue
                eid = str(co.get("eventId") or "").strip()
                price = co.get("price")
                if not eid or price is None:
                    continue
                collected.setdefault(eid, {})[ot] = price

        try:
            ws.on("framereceived", on_frame)
        except Exception:
            pass

    return collected, stats, on_ws


def _wait_for_odds(page, collected, max_steps: int, grace_ms: int = 1500) -> None:
    for _ in range(max_steps):
        if collected:
            page.wait_for_timeout(grace_ms)  # let the rest of the burst land
            return
        page.wait_for_timeout(500)


def main() -> None:
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        ctx = browser.new_context(user_agent=UA, locale="es-CL", timezone_id=TZ)

        # ── 1) overlay: passive odds + first detail href ──────────────────
        ov_collected, ov_stats, ov_on_ws = make_collector()
        ov = ctx.new_page()
        ov.on("websocket", ov_on_ws)
        ov.goto(OVERLAY, wait_until="domcontentloaded", timeout=60_000)
        try:
            ov.wait_for_selector("div.event-card", timeout=30_000)
        except PWTimeout:
            print("PROBE: overlay has NO event cards — World Cup not listed yet")
            browser.close()
            return
        _wait_for_odds(ov, ov_collected, max_steps=20)  # ~10s passive
        cards = len(ov.query_selector_all("div.event-card"))
        a = ov.query_selector('a[data-id="event-card"]') or ov.query_selector('a[href*="/events/"]')
        href = a.get_attribute("href") if a else None
        sample = ov.query_selector("div.event-card")
        title = sample.inner_text().split("\n")[0] if sample else "?"
        print(f"PROBE overlay : cards={cards} odds_events={len(ov_collected)} "
              f"sockets={ov_stats['sockets']} frames={ov_stats['frames']} "
              f"co_frames={ov_stats['co_frames']}")
        print(f"PROBE overlay : first_card='{title}' first_href={href}")
        ov.close()

        if not href:
            print("PROBE: no /events/ detail link found — cannot test detail page")
            browser.close()
            return
        if href.startswith("/"):
            href = "https://jugabet.cl" + href

        # ── 2) detail page: WS collector attached from frame one ──────────
        d_collected, d_stats, d_on_ws = make_collector()
        det = ctx.new_page()
        det.on("websocket", d_on_ws)
        det.goto(href, wait_until="domcontentloaded", timeout=60_000)
        _wait_for_odds(det, d_collected, max_steps=60)  # up to ~30s
        print(f"PROBE detail  : url={href}")
        print(f"PROBE detail  : odds_events={len(d_collected)} "
              f"sockets={d_stats['sockets']} frames={d_stats['frames']} "
              f"co_frames={d_stats['co_frames']}")
        for eid, outs in list(d_collected.items())[:5]:
            print(f"   event {eid}: home={outs.get(0)} draw={outs.get(1)} away={outs.get(3)}")

        # ── verdict ───────────────────────────────────────────────────────
        if d_collected and not ov_collected:
            print("VERDICT: detail page WORKS, overlay doesn't -> build the per-event priority lane")
        elif d_collected:
            print("VERDICT: detail page yields odds -> per-event lane viable")
        else:
            print("VERDICT: detail page also EMPTY -> prematch odds not WS-pushed on load; need another path")

        browser.close()


if __name__ == "__main__":
    main()
