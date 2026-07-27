#!/usr/bin/env python3
"""Mine real game IDs → library/games.json.

The planner must never GUESS a lobbyGameId (real ones are provider-prefixed
and opaque: pragmatic-sweet-bonanza-super-scatter, walletGameId vs20swbonsup).
This registry is the only sanctioned source; a game not in it is flagged
⛔ RESOLVE_AT_BUILD_TIME by the planner, never invented.

Two sources, richest first:
  1. The backoffice GAMES CATALOG API — how the UI itself finds ids:
     GET .../journey-activities/free-spins-bonus-deposit/data/games
         ?freeSpinTypes=...&gameProvider=...&productType=slots&size=100
     Response objects use `lobbyId`/`walletId`/`translationKey`. A single
     capture yields the whole provider catalogue (100s of games), not just
     the ones a journey happened to use. Refresh live with
     fetch_games_catalog_console.js.
  2. freespin configs embedded in journey POST bodies (`lobbyGameId` dicts) —
     a fallback that only sees games actually used in a campaign.

Usage:
    python build_games_registry.py <file.har|journey.json> [more...]
    python build_games_registry.py ~/Downloads/*.har

Merges into the existing games.json (hand-tuned aliases preserved) and rewrites.
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


def _from_catalog(g: dict) -> dict | None:
    """Normalize a GAMES CATALOG API object (lobbyId/walletId/translationKey)
    into the registry schema. Returns None if it isn't a catalog game."""
    lid = g.get("lobbyId")
    if not lid or "walletId" not in g:
        return None
    pts = g.get("productTypes") or []
    return {
        "provider": g.get("gameProvider"),
        "lobbyGameId": lid,
        "walletGameId": g.get("walletId"),
        "externalGameId": g.get("externalGameId"),
        "productType": pts[0] if pts else None,
        "subcategory": None,
        "gameTranslationKey": g.get("translationKey"),
        "providerTranslationKey": None,
        "contributionFactor": g.get("contributionFactor"),
        "freeSpinsAvailable": g.get("freeSpinsAvailable"),
        "status": g.get("status"),
    }


def _walk(obj, found: dict):
    if isinstance(obj, dict):
        # 1) games catalog API object (lobbyId/walletId/translationKey)
        cat = _from_catalog(obj)
        if cat:
            found[cat["lobbyGameId"]] = {k: v for k, v in cat.items() if v is not None}
        # 2) freespin config embedded in a journey (lobbyGameId dict)
        lid = obj.get("lobbyGameId")
        if lid and ("provider" in obj or "walletGameId" in obj):
            found.setdefault(lid, {})  # catalog wins if already present
            if not found[lid]:
                found[lid] = {k: obj.get(k) for k in FIELDS if obj.get(k) is not None}
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
            # request bodies (journey POSTs → embedded freespin configs)
            if req.get("method") == "POST" and "postData" in req:
                try:
                    _walk(json.loads(req["postData"]["text"]), found)
                except Exception:  # noqa: BLE001
                    pass
            # response bodies (the games catalog API — the rich source)
            txt = (e.get("response", {}).get("content", {}) or {}).get("text")
            if txt and "lobbyId" in txt:
                try:
                    _walk(json.loads(txt), found)
                except Exception:  # noqa: BLE001
                    pass
    else:
        _walk(data, found)


def _auto_alias(g: dict) -> list[str]:
    name = (g.get("gameTranslationKey") or "").strip().lower()
    return [name] if name else []


INDEX = HERE / "library" / "games_index.md"


def write_compact_index(games: dict) -> None:
    """Write a terse name→ids table for the planner PROMPT. The full games.json
    (with metadata) is authoritative; this compact view is what gets injected so
    the system prompt stays small (~1 line/game vs ~11). Format per line:
      Name | provider | lobbyGameId | walletGameId | externalGameId
    """
    lines = [
        "# Games registry (compact) — resolve a brief's game NAME to these ids.",
        "# Never guess an id; if a game isn't listed, flag ⛔ RESOLVE_AT_BUILD_TIME.",
        "# Name | provider | lobbyGameId | walletGameId | externalGameId",
    ]
    for g in sorted(games.values(), key=lambda x: (x.get("gameTranslationKey") or "").lower()):
        name = g.get("gameTranslationKey") or g.get("lobbyGameId")
        lines.append(" | ".join([
            str(name), str(g.get("provider") or ""),
            str(g.get("lobbyGameId") or ""), str(g.get("walletGameId") or ""),
            str(g.get("externalGameId") or ""),
        ]))
    INDEX.write_text("\n".join(lines) + "\n", encoding="utf-8")


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
    write_compact_index(reg["games"])
    print(f"\n{added} added, {updated} updated → {REGISTRY} ({len(games)} games total)")
    print(f"compact prompt index → {INDEX}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
