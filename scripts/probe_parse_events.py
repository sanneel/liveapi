"""Extract + parse the embedded events JSON from the raw HTML (no browser).

We proved the odds live as inline JSON in the SSR HTML:
  {... "marketKey":[1,2,0,...], "eventId":"15069103", "type":3, "price":8.55,
       "originalPrice":8.43 ...}
type 0=home, 1=draw, 3=away; marketKey[1]==2 & [2]==0 => the 1X2 result market.

This bracket-matches the events array, json.loads it, prints one full event's
shape (teams/time/markets), and prototypes the exact result-market extraction
(event -> home/draw/away price) that will move into the parser.

Run on the VPS:
    cd /home/admin/staging_html && .venv/bin/python scripts/probe_parse_events.py
"""

from __future__ import annotations

import html as _html
import json
import re
import urllib.request

OVERLAY = (
    "https://jugabet.cl/football/all/1"
    "?tournaments=c19cb5ffb4404c31b869b53dd90161de"
)
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)


def match_bracket(s: str, i: int):
    """Return s[i:j+1] where j closes the bracket opened at i, string-aware."""
    open_ch = s[i]
    close_ch = "]" if open_ch == "[" else "}"
    depth = 0
    in_str = False
    esc = False
    for j in range(i, len(s)):
        c = s[j]
        if in_str:
            if esc:
                esc = False
            elif c == "\\":
                esc = True
            elif c == '"':
                in_str = False
        else:
            if c == '"':
                in_str = True
            elif c == open_ch:
                depth += 1
            elif c == close_ch:
                depth -= 1
                if depth == 0:
                    return s[i : j + 1]
    return None


def find_events_array(html: str):
    """The events array is the [{...}] fragment carrying the most prices."""
    best = None
    for m in re.finditer(r'\[\{"', html):
        frag = match_bracket(html, m.start())
        if not frag or '"eventId"' not in frag:
            continue
        data = None
        for cand in (frag, _html.unescape(frag)):
            try:
                data = json.loads(cand)
                break
            except Exception:
                continue
        if not isinstance(data, list):
            continue
        n = frag.count('"price"')
        if best is None or n > best[0]:
            best = (n, data, len(frag))
    return best


def iter_outcomes(obj):
    """Yield every dict that has eventId + price (an outcome)."""
    if isinstance(obj, dict):
        if "eventId" in obj and "price" in obj:
            yield obj
        for v in obj.values():
            yield from iter_outcomes(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from iter_outcomes(v)


def main() -> None:
    req = urllib.request.Request(OVERLAY, headers={"User-Agent": UA, "Accept-Language": "es-CL"})
    with urllib.request.urlopen(req, timeout=30) as r:
        html = r.read().decode("utf-8", "ignore")
    print(f"raw bytes={len(html)}")

    best = find_events_array(html)
    if not best:
        print("could NOT bracket-match an events array")
        return
    n_prices, events, frag_len = best
    print(f"events array: {len(events)} events, frag_len={frag_len}, prices={n_prices}")

    # one full event's shape
    ev0 = events[0]
    if isinstance(ev0, dict):
        print(f"\nevent[0] top-level keys: {list(ev0.keys())}")
        for k in ("id", "eventId", "name", "slug", "startDate", "startTime", "date", "competitors", "teams", "tournament", "category"):
            if k in ev0:
                val = json.dumps(ev0[k], ensure_ascii=False)
                print(f"   {k}: {val[:160]}")

    # result-market extraction prototype
    by_event = {}
    for o in iter_outcomes(events):
        mk = o.get("marketKey")
        is_result = isinstance(mk, list) and len(mk) >= 3 and mk[1] == 2 and mk[2] == 0
        if not is_result:
            mii = str(o.get("marketItemId") or "")
            is_result = "_2_0_-_1_-_-" in mii
        if not is_result:
            continue
        eid = str(o.get("eventId"))
        t = o.get("type", 0)  # home often omits type -> 0
        by_event.setdefault(eid, {})[t] = (o.get("price"), o.get("originalPrice"))

    full = [e for e, d in by_event.items() if 0 in d and 3 in d]
    print(f"\nresult markets parsed: {len(by_event)} events; {len(full)} have home+away")
    for eid, d in list(by_event.items())[:6]:
        h = d.get(0)
        x = d.get(1)
        a = d.get(3)
        print(f"   event {eid}: home(0)={h} draw(1)={x} away(3)={a}")

    # show the distinct 'type' values present so we confirm home==0
    types = sorted({o.get("type", 0) for o in iter_outcomes(events)
                    if (isinstance(o.get('marketKey'), list) and o['marketKey'][1:3] == [2, 0])})
    print(f"\ntype values seen in result market: {types}")


if __name__ == "__main__":
    main()
