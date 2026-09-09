#!/usr/bin/env python3
"""Point a house label — "game of the week" — at a real game in the registry.

A brief does not always name a title. It says "Game of the Week", and the
composer refused the whole journey because that is not a game: `resolve_game`
will not guess, and keeping the reference template's game would award spins on
the wrong title. The label is the missing third option — an operator states, once
per rotation, which registered game the label means, and every brief that uses
the phrase resolves by itself from then on.

A label is stored as an ALIAS on its target game, so nothing new resolves it:
`journey_composer._game_index` already indexes every alias, and so does
`compose._games_by_name`. The refusal stays exactly as strict — a label can only
ever point at a game already in library/games.json, and this script refuses if it
does not resolve.

Exactly one game owns a label at a time. `_game_index` builds with setdefault, so
two owners would silently resolve to whichever was read first; moving a label
therefore strips it from every other entry before adding it.

Usage:
    python set_game_label.py --list
    python set_game_label.py "game of the week" "Big Bass Bonanza 1000"
    python set_game_label.py "game of the week" pragmatic-big-bass-bonanza-1000
    python set_game_label.py --clear "game of the week"
    python set_game_label.py "juego de la semana" "Gates of Olympus" --dry-run

The target may be a title, a lobbyGameId, or any existing alias. Rebuilds
library/games_index.md afterwards so the planner's prompt lists the live labels.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
REGISTRY = SCRIPT_DIR / "library" / "games.json"

sys.path.insert(0, str(SCRIPT_DIR))
from journey_composer import _norm  # noqa: E402  the composer's own normaliser

# Labels the house uses. Free-form is allowed, but these are the ones the
# planner prompt advertises, so keep the list and the prompt in step.
KNOWN_LABELS = ("game of the week", "juego de la semana", "gow")


def _load() -> dict:
    return json.loads(REGISTRY.read_text(encoding="utf-8"))


def _save(doc: dict) -> None:
    REGISTRY.write_text(
        json.dumps(doc, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _own_names(entry: dict) -> set[str]:
    """The names a game owns by being itself — never removable as a label."""
    return {_norm(entry.get("gameTranslationKey") or ""),
            _norm(entry.get("lobbyGameId") or ""),
            _norm(entry.get("walletGameId") or "")} - {""}


def _find(games: dict, target: str) -> tuple[str, dict]:
    """Registry key + entry for a title / lobbyGameId / alias. Refuse if absent."""
    want = _norm(target)
    for key, entry in games.items():
        if want in _own_names(entry) or want in {_norm(a) for a in entry.get("aliases") or []}:
            return key, entry
    import difflib
    names = {_norm(e.get("gameTranslationKey") or ""): e.get("gameTranslationKey")
             for e in games.values()}
    near = [names[n] for n in difflib.get_close_matches(want, list(names), n=3, cutoff=0.6)]
    raise SystemExit(
        f"{target!r} is not in {REGISTRY.name} ({len(games)} games)."
        + (f" Did you mean: {near}?" if near else "")
        + "\nA label may only point at a game that is already registered. If the"
          "\ngame is real but missing, capture it first — paste"
          "\nfetch_games_catalog_console.js in a logged-in backoffice tab, then"
          "\n  python build_games_registry.py --reindex")


def labels_in(games: dict) -> dict[str, str]:
    """label -> game display name, for every alias that is not a game's own name."""
    out: dict[str, str] = {}
    for entry in games.values():
        own = _own_names(entry)
        for alias in entry.get("aliases") or []:
            if _norm(alias) not in own:
                out[alias] = entry.get("gameTranslationKey") or entry.get("lobbyGameId") or "?"
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("label", nargs="?", help='e.g. "game of the week"')
    ap.add_argument("game", nargs="?", help="title, lobbyGameId or existing alias")
    ap.add_argument("--list", action="store_true", help="show the live labels")
    ap.add_argument("--clear", action="store_true", help="remove the label entirely")
    ap.add_argument("--dry-run", action="store_true", help="say what would change, write nothing")
    args = ap.parse_args()

    doc = _load()
    games = doc.get("games") or {}

    if args.list:
        live = labels_in(games)
        if not live:
            print("no labels set. Known ones to set: " + ", ".join(KNOWN_LABELS))
            return 0
        for label, game in sorted(live.items()):
            print(f"  {label!r} -> {game}")
        return 0

    if not args.label:
        ap.print_help()
        return 2

    want = _norm(args.label)
    if not want:
        raise SystemExit("label is empty after normalising")

    # A label must never shadow a real game's own name, or that game becomes
    # unreachable by the name every brief calls it.
    for key, entry in games.items():
        if want in _own_names(entry):
            raise SystemExit(
                f"{args.label!r} IS the name of a registered game "
                f"({entry.get('gameTranslationKey')}). Pick a label that is not a "
                f"game name, or just use the game's own name in the brief.")

    # And it must not merely LOOK like a title. "Gates of Olympus" matches no
    # entry exactly here — the registry has "Gates of Olympus Super Scatter" —
    # so the exact check above waves it through and the phrase every brief uses
    # for one game silently becomes an alias for another. That is the near-match
    # swap this repo refuses, arriving through the back door of a label. A label
    # names a rotation ("game of the week"); a title names a game, and a title
    # that is missing gets captured, never aliased.
    if len(want) >= 4:
        titles = sorted({e.get("gameTranslationKey") for e in games.values()
                         if want in _norm(e.get("gameTranslationKey") or "")})
        if titles:
            raise SystemExit(
                f"{args.label!r} reads as a game title, not a house label — it is "
                f"part of {titles[:5]}. A label is for a rotation the brief names "
                f"instead of a game (\"game of the week\"). If the brief means one "
                f"of those games, write its full title; if it means a game that is "
                f"missing, capture it with fetch_games_catalog_console.js.")

    # Strip the label from wherever it currently lives, so there is one owner.
    previous = []
    for key, entry in games.items():
        aliases = entry.get("aliases") or []
        kept = [a for a in aliases if _norm(a) != want]
        if len(kept) != len(aliases):
            previous.append(entry.get("gameTranslationKey") or key)
            entry["aliases"] = kept

    if args.clear:
        if not previous:
            print(f"{args.label!r} was not set on any game")
            return 0
        print(f"cleared {args.label!r} (was: {', '.join(previous)})")
        if not args.dry_run:
            _save(doc)
            _reindex(games)
        return 0

    if not args.game:
        raise SystemExit("a game is required unless --list or --clear is given")

    key, entry = _find(games, args.game)
    entry.setdefault("aliases", []).append(args.label)

    name = entry.get("gameTranslationKey")
    moved = f" (moved from {', '.join(previous)})" if previous else ""
    print(f"{args.label!r} -> {name}  [{entry.get('lobbyGameId')}]{moved}")

    if args.dry_run:
        print("--dry-run: nothing written")
        return 0

    _save(doc)
    _reindex(games)

    # Prove the composer resolves it, rather than trusting the write.
    import importlib
    import journey_composer as J
    importlib.reload(J)
    hit = J.resolve_game(args.label)
    print(f"resolved by the composer: {hit.get('gameName') or hit.get('game_name') or name} "
          f"-> {hit.get('lobbyGameId')}")
    return 0


def _reindex(games: dict) -> None:
    from build_games_registry import write_compact_index
    write_compact_index(games)
    print("rebuilt library/games_index.md")


if __name__ == "__main__":
    raise SystemExit(main())
