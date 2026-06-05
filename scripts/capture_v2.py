#!/usr/bin/env python3
"""
One-off diagnostic: capture jugabet's Angular-v2 odds data flow.

jugabet moved to an Angular v2 frontend that streams odds over Server-Sent
Events (EventSource) instead of the old `by-market-filter` XHRs + DOM attrs.
This script loads a page that HAS matches, shims EventSource + fetch, and dumps
everything needed to rewrite the parser:

  * every data/API/stream response (url + status + content-type)
  * SSE (EventSource) connection URLs and a sample of their messages
  * any `Failed to fetch` errors (Cloudflare / anti-bot blocking)
  * one match-card's outerHTML (so we can find the new selectors)

Run on the VPS (Chilean IP, against a page that has fixtures):
    ./.venv/bin/python scripts/capture_v2.py "https://jugabet.cl/football/prematch/1"

It changes nothing and writes nothing — paste its stdout back.
"""
from __future__ import annotations

import json
import sys

from playwright.sync_api import sync_playwright

URL = sys.argv[1] if len(sys.argv) > 1 else "https://jugabet.cl/football/prematch/1"

# Injected at document-start so it wraps EventSource/fetch before Angular uses them.
SHIM = r"""
(() => {
  window.__cap = { sse: [], errors: [] };
  const OrigES = window.EventSource;
  if (OrigES) {
    const Wrapped = function(url, cfg) {
      try { window.__cap.sse.push({type:'open', url:String(url)}); } catch(e){}
      const es = new OrigES(url, cfg);
      try {
        es.addEventListener('message', (e) => {
          try { if (window.__cap.sse.length < 60)
            window.__cap.sse.push({type:'msg', url:String(url), data:String(e.data).slice(0,1500)});
          } catch(_){}
        });
        es.addEventListener('error', () => {
          try { window.__cap.sse.push({type:'error', url:String(url)}); } catch(_){}
        });
      } catch(e){}
      return es;
    };
    Wrapped.prototype = OrigES.prototype;
    try { Object.defineProperty(window, 'EventSource', {value:Wrapped, writable:true, configurable:true}); }
    catch(e) { window.EventSource = Wrapped; }
  }
  const of = window.fetch;
  if (of) {
    window.fetch = function() {
      const a = arguments;
      const u = (typeof a[0]==='string') ? a[0] : ((a[0] && a[0].url) || '');
      return of.apply(this, a).catch((err) => {
        try { window.__cap.errors.push({url:String(u), err:String(err)}); } catch(_){}
        throw err;
      });
    };
  }
})();
"""

API_HINTS = ("/api", "filter", "odds", "market", "event", "sport",
             "stream", "sse", "graphql", "lineup", "prematch", "live")

# Endpoints whose BODY we dump — this is the v2 odds/market data we must map
# into the parser.
KEY_BODY_HINTS = ("by-market-filter", "by-sport-filter", "/markets",
                  "/sport/layout", "reactive-outcomes", "/outcomes", "/events/")


def main() -> None:
    responses = []
    bodies = []
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
        page.add_init_script(SHIM)

        def on_resp(r):
            try:
                ct = (r.headers or {}).get("content-type", "")
                u = r.url
                if "event-stream" in ct or "json" in ct or any(h in u.lower() for h in API_HINTS):
                    if not any(u.endswith(ext) for ext in (".js", ".css", ".woff", ".woff2", ".png", ".jpg", ".svg")):
                        responses.append({"status": r.status, "ct": ct[:38], "url": u})
                # Dump the BODY of the odds/market/layout endpoints — that's the
                # v2 data we need to map into the parser.
                if any(k in u.lower() for k in KEY_BODY_HINTS):
                    try:
                        _txt = r.text()
                    except Exception as _e:
                        _txt = f"(body unavailable: {_e})"
                    bodies.append({"status": r.status, "url": u, "body": (_txt or "")[:6000]})
            except Exception:
                pass

        page.on("response", on_resp)

        # v2 streams live odds over a "reactive-outcomes" push channel — capture
        # the WebSocket frames (that's where the odds values are).
        def on_ws(ws):
            try:
                ws_frames.append({"ev": "open", "url": ws.url})
                def on_recv(payload):
                    try:
                        if sum(1 for x in ws_frames if x.get("ev") == "recv") < 25:
                            ws_frames.append({"ev": "recv", "url": ws.url, "data": str(payload)[:1200]})
                    except Exception:
                        pass
                ws.on("framereceived", on_recv)
            except Exception:
                pass

        page.on("websocket", on_ws)
        try:
            page.goto(URL, wait_until="domcontentloaded", timeout=45000)
        except Exception as e:
            print(f"goto error: {e}")
        for _ in range(6):
            try:
                page.mouse.wheel(0, 4000)
            except Exception:
                pass
            page.wait_for_timeout(1500)
        page.wait_for_timeout(5000)

        cap = page.evaluate("window.__cap || {sse:[],errors:[]}")
        n_cards = page.evaluate(
            "() => { let m=0; for (const s of ['app-event-card','[data-lineup-id]','[class*=event-card]','[class*=eventCard]'])"
            " { try { m=Math.max(m, document.querySelectorAll(s).length); } catch(e){} } return m; }"
        )
        card = page.evaluate(
            """() => {
                const odd = document.querySelector('p.outcome__odd');
                if (odd) {
                  let el = odd;
                  for (let i = 0; i < 7 && el.parentElement; i++) el = el.parentElement;
                  return 'ODDS_IN_DOM count=' + document.querySelectorAll('p.outcome__odd').length
                         + '\\n' + el.outerHTML.slice(0, 3500);
                }
                const sels = ['app-event-card','[class*=event-card]','[class*=eventCard]',
                              '[class*=event-row]','[class*=eventRow]','[class*=sportsEvent]'];
                for (const s of sels) {
                  for (const c of document.querySelectorAll(s)) {
                    const cls = (typeof c.className === 'string') ? c.className : '';
                    if (cls.includes('chip') || cls.includes('filter')) continue;
                    if ((c.innerText || '').trim().length > 8)
                      return 'NO_ODDS_IN_DOM sel=' + s + '\\n' + c.outerHTML.slice(0, 3500);
                  }
                }
                return 'NO_ODDS_IN_DOM and no match-card matched';
            }"""
        )
        browser.close()

    print(f"URL: {URL}")
    print(f"match-ish cards on page: {n_cards}")
    print("\n=== NETWORK (api / data / stream responses) ===")
    for r in responses[:70]:
        print(f"{r['status']}  {r['ct']:20}  {r['url']}")
    print("\n=== SSE (EventSource) ===")
    print(json.dumps(cap.get("sse", []), indent=2, ensure_ascii=False)[:3500])
    print("\n=== fetch errors (Failed to fetch / Cloudflare) ===")
    print(json.dumps(cap.get("errors", []), indent=2, ensure_ascii=False)[:2000])
    print("\n=== WEBSOCKET frames (reactive-outcomes odds?) ===")
    print(json.dumps(ws_frames[:30], indent=2, ensure_ascii=False)[:4500])

    print("\n=== KEY ENDPOINT BODIES (odds / markets / layout) ===")
    for b in bodies[:8]:
        print(f"\n--- {b['status']}  {b['url']}")
        print(b["body"])

    print("\n=== sample match-card HTML ===")
    print(card)


if __name__ == "__main__":
    main()
