"""Check whether jugabet's old odds API works again after the CTO disabled the
feature flag that was making it return {}.

The Angular page POSTs empty params (eventIds:[], sportId:""), so it always gets
{} — that tells us nothing. This pulls REAL sportId + eventIds from the page's
embedded SSR JSON and POSTs them to /api/v2/markets/by-market-filter directly,
so we see whether the endpoint returns odds when given proper input.

Run on the VPS:
    cd /home/admin/staging_html && .venv/bin/python scripts/probe_check_api.py
"""

from __future__ import annotations

import json
import os
import sys
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.parser.embedded_odds import find_events_array

PAGE = "https://jugabet.cl/football/prematch/1"
API = "https://jugabet.cl/api/v2/markets/by-market-filter"
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)


def _get(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Language": "es-CL"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode("utf-8", "ignore")


def main() -> None:
    html = _get(PAGE)
    events = find_events_array(html)
    sport_id = ""
    ids = []
    for ev in events:
        if not isinstance(ev, dict):
            continue
        if not sport_id and ev.get("sportId"):
            sport_id = str(ev["sportId"])
        eid = ev.get("id")
        if eid:
            ids.append(str(eid))
        if len(ids) >= 5:
            break

    print(f"extracted sportId={sport_id!r}  eventIds={ids}")
    if not sport_id or not ids:
        print("could not extract sportId/eventIds from SSR — aborting")
        return

    body = json.dumps({"eventIds": ids, "sportId": sport_id, "stage": 1}).encode("utf-8")
    req = urllib.request.Request(
        API,
        data=body,
        method="POST",
        headers={
            "User-Agent": UA,
            "Content-Type": "application/json; charset=UTF-8",
            "x-language": "es-JBCL",
            "Accept": "application/json, text/plain, */*",
            "Referer": PAGE,
            "Origin": "https://jugabet.cl",
        },
    )
    print(f"\nPOST {API}")
    print(f"  body: {body.decode()}")
    try:
        with urllib.request.urlopen(req, timeout=25) as r:
            status = r.status
            resp = r.read().decode("utf-8", "ignore")
    except Exception as e:  # noqa: BLE001
        print(f"  POST failed: {e!r}")
        return

    print(f"  status: {status}")
    print(f"  response length: {len(resp)}")
    has_price = '"price"' in resp or '"odds"' in resp or '"coefficient"' in resp
    print(f"  contains odds-like fields: {has_price}")
    print(f"  response head:\n    {resp[:1200]}")

    if resp.strip() in ("{}", "[]", ""):
        print("\nVERDICT: still EMPTY — the API is not returning odds yet (flag may not be fully off, or it needs other params).")
    elif has_price:
        print("\nVERDICT: API is BACK — returns odds for real params. The old XHR path is usable again.")
    else:
        print("\nVERDICT: non-empty but no obvious odds — inspect the response head above.")


if __name__ == "__main__":
    main()
