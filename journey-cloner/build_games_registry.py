#!/usr/bin/env python3
"""Mine real game IDs from captured journeys → library/games.json.

The planner must never GUESS a lobbyGameId (real ones are provider-prefixed
and opaque: pragmatic-sweet-bonanza-super-scatter, walletGameId vs20swbonsup).
This registry is the only sanctioned source; a game not in it is flagged
⛔ RESOLVE_AT_BUILD_TIME by the planner, never invented.

Usage:
    python build_games_registry.py <file.har|journey.json> [more...]
    python build_games_registry.py ~/Downloads/*.har

Scans every POST body (HAR) or journey object (JSON) for freespin game configs
(any dict carrying lobbyGameId), merges them with the existing games.json
(existing hand-tuned aliases are preserved), and rewrites the file.
"""
from __future__ import annotations

import glob
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REGISTRY = HERE / "library" / "games.json"

FIELDS = ("provider", "lobbyGameId", "walletGameId", "externalGameId",
          "productType", "subcategory", "gameTranslationKey",
          "providerTranslationKey")


def _walk(obj, found: dict):
    if isinstance(obj, dict):
        lid = obj.get("lobbyGameId")
        if lid and ("provider" in obj or "walletGameId" in obj):
            found[lid] = {k: obj.get(k) for k in FIELDS}
        for v in obj.values():
            _walk(v, found)
    elif isinstance(obj, list):
        for v in obj:
            _walk(v, found)


def _mine_file(path: str, found: dict):
    try:
        data = json.load(open(path, encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        print(f"  skip {path}: {exc}")
        return
    if isinstance(data, dict) and "log" in data and "entries" in data["log"]:
        for e in data["log"]["entries"]:
            req = e.get("request", {})
            if req.get("method") == "POST" and "postData" in req:
                try:
                    _walk(json.loads(req["postData"]["text"]), found)
                except Exception:  # noqa: BLE001
                    pass
    else:
        _walk(data, found)


def _auto_alias(g: dict) -> list[str]:
    name = (g.get("gameTranslationKey") or "").strip().lower()
    return [name] if name else []


def main() -> int:
    args = sys.argv[1:]
    if not args:
        print(__doc__)
        return 2

    paths: list[str] = []
    for a in args:
        paths += glob.glob(a) or [a]

    found: dict = {}
    for p in paths:
        print(f"mining {p}")
        _mine_file(p, found)

    reg = json.load(open(REGISTRY, encoding="utf-8")) if REGISTRY.exists() else {"games": {}}
    games = reg.setdefault("games", {})

    added, updated = 0, 0
    for lid, g in found.items():
        if lid in games:
            # keep hand-tuned aliases; refresh the id fields from the capture
            existing_aliases = games[lid].get("aliases", [])
            games[lid].update({k: v for k, v in g.items() if v is not None})
            games[lid]["aliases"] = existing_aliases or _auto_alias(g)
            updated += 1
        else:
            g["aliases"] = _auto_alias(g)
            games[lid] = g
            added += 1

    reg["games"] = dict(sorted(games.items()))
    REGISTRY.write_text(json.dumps(reg, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"\n{added} added, {updated} updated → {REGISTRY} ({len(games)} games total)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
