#!/usr/bin/env python3
"""
Path A diagnostic: does jugabet v2 actually render odds into the DOM (headless),
and under what selector?

Loads a page, scrolls to pull every card into view (v2 subscribes to a card's
odds over the Centrifugo WebSocket when it enters the viewport), polls candidate
odds selectors every 4s for ~32s, logs the WebSocket frames (sent = the
per-event subscriptions, recv = the odds pushes), and dumps a real match-card's
HTML so we can pin the exact odds selector.

Run on the VPS:
    ./.venv/bin/python scripts/capture_odds_dom.py "https://jugabet.cl/football/prematch/1"
"""
from __future__ import annotations

import json
import sys

from playwright.sync_api import sync_playwright

URL = sys.argv[1] if len(sys.argv) > 1 else "https://jugabet.cl/football/prematch/1"

# Candidate selectors for a rendered odds value — the poll reports which (if
# any) actually match, so we learn the real one.
ODDS_SELS = [
    "p.outcome__odd", "[class*=outcome__odd]", "[class*=outcomeOdd]",
    "button[class*=outcome]", "[class*=selection__odd]", "[class*=Selection]",
    "[data-clickstream-action*=ODD]", "[class*=odd]",
]


def main() -> None:
    ws_frames = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(
            locale="es-CL",
            timezone_id="America/Santiago",
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
            ),
        )
        page = ctx.new_page()

        def on_ws(ws):
            try:
                ws_frames.append({"ev": "open", "url": ws.url})

                def rec(pl):
                    if sum(1 for x in ws_frames if x.get("ev") == "recv") < 30:
                        try:
                            ws_frames.append({"ev": "recv", "data": str(pl)[:1400]})
                        except Exception:
                            pass

                def snt(pl):
                    if sum(1 for x in ws_frames if x.get("ev") == "sent") < 30:
                        try:
                            ws_frames.append({"ev": "sent", "data": str(pl)[:1400]})
                        except Exception:
                            pass

                ws.on("framereceived", rec)
                ws.on("framesent", snt)
            except Exception:
                pass

        page.on("websocket", on_ws)

        try:
            page.goto(URL, wait_until="domcontentloaded", timeout=45000)
        except Exception as e:
            print("goto error:", e)

        def probe():
            try:
                return page.evaluate(
                    "(sels)=>{const o={};for(const s of sels){try{o[s]=document.querySelectorAll(s).length;}"
                    "catch(e){o[s]=-1;}}return o;}",
                    ODDS_SELS,
                )
            except Exception as e:
                return {"err": str(e)}

        timeline = []
        for i in range(8):  # ~32s, scrolling each cycle
            try:
                page.mouse.wheel(0, 6000)
            except Exception:
                pass
            page.wait_for_timeout(4000)
            timeline.append({"sec": (i + 1) * 4, "odds": probe()})

        card = page.evaluate(
            """(sels)=>{
                let odd=null;
                for(const s of sels){const el=document.querySelector(s); if(el){odd=el;break;}}
                if(odd){
                  let el=odd;
                  for(let i=0;i<9&&el.parentElement;i++){
                    el=el.parentElement;
                    if(el.querySelectorAll(sels.join(',')).length>=2 && (el.innerText||'').length>20) break;
                  }
                  return 'ODDS_CARD ::\\n'+el.outerHTML.slice(0,4500);
                }
                const cs=document.querySelectorAll('app-event-card,[class*=event-card],[class*=eventCard],[class*=event-row],[class*=eventRow]');
                for(const c of cs){
                  const cl=(typeof c.className==='string')?c.className:'';
                  if(cl.includes('chip')||cl.includes('filter'))continue;
                  if((c.innerText||'').trim().length>10) return 'NO_ODDS_CARD ::\\n'+c.outerHTML.slice(0,4500);
                }
                return 'no card matched';
            }""",
            ODDS_SELS,
        )
        browser.close()

    print("URL:", URL)
    print("\n=== odds-selector counts over time (which selector renders, and when) ===")
    for t in timeline:
        nz = {k: v for k, v in t["odds"].items() if isinstance(v, int) and v > 0}
        print(f"  +{t['sec']:>2}s : {nz if nz else '(none)'}")
    print("\n=== WebSocket frames (sent = subscriptions, recv = pushes) ===")
    print(json.dumps(ws_frames[:40], indent=2, ensure_ascii=False)[:5000])
    print("\n=== match-card HTML ===")
    print(card)


if __name__ == "__main__":
    main()
