"""Map the embedded-JSON market shape for every sport.

football odds now parse from the SSR blob via marketKey[1:3]==[2,0] (1X2,
types 0/1/3). Other sports are mostly 2-way (winner). Before generalizing the
extractor, this prints, per sport: how many events, the first events' markets,
and the distinct primary-market keys + outcome type-sets — so we learn whether
the main market is markets[0], what its marketKey is, and which `type` values a
2-way winner uses (expected 0=home/p1, 3=away/p2, no draw).

Run on the VPS:
    cd /home/admin/staging_html && .venv/bin/python scripts/probe_all_sports.py
"""

from __future__ import annotations

import os
import sys
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.parser.embedded_odds import find_events_array

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)
SPORTS = {
    "football": "https://jugabet.cl/football/prematch/1",
    "basketball": "https://jugabet.cl/basketball/prematch/1",
    "tennis": "https://jugabet.cl/tennis/prematch/1",
    "cybersport": "https://jugabet.cl/cybersport/prematch/1",
    "boxing": "https://jugabet.cl/boxing/prematch/1",
    "mma": "https://jugabet.cl/mma/prematch/1",
    "ufc": "https://jugabet.cl/ufc/prematch/1",
}


def _get(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Language": "es-CL"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode("utf-8", "ignore")


def _names(ev: dict) -> str:
    comps = ev.get("competitors") or []
    return " v ".join(str((c or {}).get("name", "?")) for c in comps)


def main() -> None:
    for sport, url in SPORTS.items():
        print(f"\n################## {sport} ##################")
        try:
            html = _get(url)
        except Exception as e:  # noqa: BLE001
            print(f"  GET failed: {e!r}")
            continue
        events = find_events_array(html)
        print(f"  events: {len(events)}")
        if not events:
            continue

        # first 2 events: show up to 2 markets each
        for ev in events[:2]:
            if not isinstance(ev, dict):
                continue
            markets = ev.get("markets") or []
            print(f"  - {ev.get('id')} | {_names(ev)} | markets={len(markets)}")
            for mi, mk in enumerate(markets[:2]):
                outs = mk.get("outcomes") or []
                summ = [(o.get("type"), o.get("price")) for o in outs[:6]]
                print(f"      market[{mi}] name={mk.get('name')!r} "
                      f"key={mk.get('marketKey')} outs={summ}")

        # distinct primary-market (markets[0]) keys + type-sets across all events
        keys = set()
        typesets = set()
        for ev in events:
            if not isinstance(ev, dict):
                continue
            ms = ev.get("markets") or []
            if not ms:
                continue
            m0 = ms[0] or {}
            mk = m0.get("marketKey")
            keys.add(tuple(mk[:3]) if isinstance(mk, list) else None)
            ts = tuple(sorted(
                o.get("type") for o in (m0.get("outcomes") or []) if o.get("type") is not None
            ))
            typesets.add(ts)
        print(f"  markets[0] key[:3] variants : {sorted(map(str, keys))}")
        print(f"  markets[0] type-sets        : {sorted(map(str, typesets))}")


if __name__ == "__main__":
    main()
