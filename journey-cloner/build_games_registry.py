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


DEFAULT_PROVIDER = "pragmatic"


def write_compact_index(games: dict) -> None:
    """Write a terse name→ids table for the planner PROMPT. The full games.json
    (with metadata) is authoritative; this compact view is what gets injected so
    the system prompt stays small.

    Two redundancies are factored out of every row, because this table is re-sent
    on every single call:
      * externalGameId is identical to walletGameId for 106/106 captured games,
        so it is stated once in the header instead of 106 times.
      * the provider is `pragmatic` for 102/106, so only the exceptions carry a
        `@provider` suffix.
    Format per line:  Name | lobbyGameId | walletGameId[ @provider]
    """
    # The live catalog is ~4,900 games across ~48 providers. Listing them would
    # be roughly 300 KB in every single prompt — 15x the whole rest of it — so
    # the index is now a SUMMARY, and the composer resolves names itself
    # (compose._games_by_name / journey_composer.resolve_game index the full
    # games.json by id, display name and alias). The planner writes the game the
    # way the brief says it; an unresolvable name is refused with near matches.
    by_provider: dict[str, int] = {}
    for g in games.values():
        by_provider[str(g.get("provider") or "?")] = by_provider.get(str(g.get("provider") or "?"), 0) + 1
    lines = [
        f"# Games registry — {len(games)} games across {len(by_provider)} providers.",
        "#",
        "# The full table is NOT inlined here: it is ~300KB. Write the game the way",
        "# the brief names it — \"Big Bass Bonanza 1000\", \"Wanted Dead or a Wild\" —",
        "# in the game field. The composer resolves the name to the real",
        "# lobby/wallet/external/provider tuple against library/games.json, and",
        "# REFUSES with near matches if it cannot. Do NOT invent an id, and do NOT",
        "# flag ⛔ merely because you cannot see the game listed here — you cannot",
        "# see any of them. Flag ⛔ only if the brief names no game at all.",
        "#",
        "# Games per provider:",
    ]
    for prov, count in sorted(by_provider.items(), key=lambda kv: (-kv[1], kv[0])):
        lines.append(f"#   {prov} ({count})")
    INDEX.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    args = sys.argv[1:]
    if not args:
        print(__doc__)
        return 2

    # After pasting a fresh games.json from fetch_games_catalog_console.js the
    # compact index is stale, and there was no way to rebuild it without also
    # re-mining a HAR. The prompt reads the index, so a stale one silently means
    # the planner cannot see the games you just captured.
    if args[0] == "--reindex":
        if not REGISTRY.exists():
            print(f"no registry at {REGISTRY}")
            return 2
        games = json.load(open(REGISTRY, encoding="utf-8")).get("games") or {}
        write_compact_index(games)
        print(f"reindexed {len(games)} games -> {INDEX} ({INDEX.stat().st_size:,} bytes)")
        return 0

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
