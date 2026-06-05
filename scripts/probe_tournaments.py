"""Discover football tournament UUIDs (for the priority live lane).

We need the jugabet tournament UUIDs for the leagues to parse live:
Chilean Primera (Liga de Primera), Copa Sudamericana, Copa Libertadores, plus
World Cup. Overlay feeds key on these UUIDs: /football/all/1?tournaments=<uuid>.

This GETs several football pages, reads tournament.id / tournament.name /
category.name from the embedded events JSON, and prints every distinct
tournament with its match count — flagging the ones matching the target leagues.

Run on the VPS:
    cd /home/admin/staging_html && .venv/bin/python scripts/probe_tournaments.py
"""

from __future__ import annotations

import os
import sys
import urllib.request
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.parser.embedded_odds import find_events_array

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)
URLS = [
    "https://jugabet.cl/football/all/1",
    "https://jugabet.cl/football/prematch/1",
    "https://jugabet.cl/football/live/1",
]
TARGET_KEYWORDS = (
    "chile", "primera", "libertadores", "sudamericana", "conmebol", "sudam",
)


def _get(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Language": "es-CL"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode("utf-8", "ignore")


def main() -> None:
    # uuid -> {"name", "cat", "n"}
    tours: dict = {}
    for url in URLS:
        try:
            html = _get(url)
        except Exception as e:  # noqa: BLE001
            print(f"GET failed {url}: {e!r}")
            continue
        events = find_events_array(html)
        for ev in events:
            if not isinstance(ev, dict):
                continue
            t = ev.get("tournament") or {}
            cat = ev.get("category") or {}
            tid = t.get("id")
            if not tid:
                continue
            rec = tours.setdefault(tid, {"name": t.get("name"), "cat": cat.get("name"), "n": 0})
            rec["n"] += 1

    print(f"==== {len(tours)} distinct tournaments seen ====")
    for tid, rec in sorted(tours.items(), key=lambda kv: -kv[1]["n"]):
        print(f"  {rec['n']:4}  {tid}  | {rec['cat']} / {rec['name']}")

    print("\n==== TARGET-LEAGUE MATCHES (chile / conmebol / libertadores / sudamericana) ====")
    found = False
    for tid, rec in tours.items():
        hay = f"{rec.get('cat','')} {rec.get('name','')}".lower()
        if any(k in hay for k in TARGET_KEYWORDS):
            found = True
            print(f"  uuid={tid}  | {rec['cat']} / {rec['name']}  ({rec['n']} matches)")
    if not found:
        print("  (none currently on the fetched pages — likely off page 1.")
        print("   Open the league on jugabet.cl and copy its")
        print("   /football/all/1?tournaments=<uuid> URL instead.)")


if __name__ == "__main__":
    main()
