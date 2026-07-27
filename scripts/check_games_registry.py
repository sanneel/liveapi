#!/usr/bin/env python3
"""Sanity-check journey-cloner/library/games.json after pasting a fresh capture.

The realistic failure is a TRUNCATED paste: a few hundred KB of JSON through a
clipboard or a terminal can lose its tail, and the result is invalid JSON that
would otherwise only blow up later, during --reindex. Run this first.

    python scripts/check_games_registry.py
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
REGISTRY = REPO / "journey-cloner" / "library" / "games.json"
INDEX = REPO / "journey-cloner" / "library" / "games_index.md"
# What shipped before the re-capture. A smaller number means the paste lost data.
KNOWN_GOOD = 106


def main() -> int:
    if not REGISTRY.exists():
        print(f"MISSING: {REGISTRY}")
        return 1

    raw = REGISTRY.read_text(encoding="utf-8")
    try:
        data = json.loads(raw)
    except ValueError as exc:
        print(f"INVALID JSON ({len(raw):,} bytes read) — {exc}")
        print("  Almost certainly a truncated paste. Use the downloaded")
        print("  games.json file instead of the clipboard, or restore the backup:")
        print("    cp journey-cloner/library/games.json.bak journey-cloner/library/games.json")
        return 1

    games = data.get("games") or {}
    if not isinstance(games, dict) or not games:
        print("PARSED, but there is no non-empty 'games' object — wrong file?")
        return 1

    providers = Counter(g.get("provider") or "?" for g in games.values())
    missing_ids = [k for k, g in games.items() if not g.get("lobbyGameId")]

    print(f"OK: {len(games):,} games, {len(raw):,} bytes")
    print(f"    providers: {dict(providers)}")
    if missing_ids:
        print(f"    WARNING: {len(missing_ids)} entries have no lobbyGameId")
    if len(games) < KNOWN_GOOD:
        print(f"    WARNING: fewer than the {KNOWN_GOOD} games that shipped before —")
        print("             the capture may have been partial. Check the console log.")

    if INDEX.exists():
        index_rows = sum(1 for line in INDEX.read_text(encoding="utf-8").splitlines()
                         if line.strip() and not line.startswith("#"))
        if index_rows != len(games):
            print(f"    NEXT: index has {index_rows} rows vs {len(games)} games — rebuild it:")
            print("            python journey-cloner/build_games_registry.py --reindex")
        else:
            print(f"    index is in sync ({index_rows} rows)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
