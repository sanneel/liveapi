"""
Match content-quality classifier.

Sports books advertise huge "live" inventories that are actually synthetic:
simulated football, replays of past matches, esports replays, etc.
These look fine in raw feeds but should NOT show up in a real campaign
picker / hot leaderboard by default — they're operator footguns that
let an admin accidentally promote a fake fixture as a public PNG.

Single source of truth: `is_synthetic_tournament(name) -> bool`.
Used at:
  * parser write time (sets `Match.is_synthetic`)
  * search/list paths (filters by default unless caller opts in)
"""

from __future__ import annotations

import re
import unicodedata
from typing import Iterable, Optional, Tuple


# Keywords that mark a tournament as synthetic / replay / non-real-event.
# Match is done after lowercasing + diacritic stripping, on token boundaries
# OR substring (some feed names are concatenated). New keywords go here.
SYNTHETIC_KEYWORDS: Tuple[str, ...] = (
    "virtual",          # "Fútbol virtual", "Virtual League"
    "replay",           # "FIFA Replays"
    "ereplay",          # "eReplay football"
    "esportsbattle",    # "ESportsBattle"
    "esports-battle",
    "ehighlight",       # "eHighlights"
    "epenalt",          # "ePenalties"
    "ebattle",          # "eBattle"
    "simulat",          # "simulator", "simulated"
    "fifa 23",          # FIFA series video-game leagues
    "fifa 24",
    "fifa 25",
    "fc 24",
    "fc 25",
    "efootball",        # Konami eFootball video-game leagues
    "vff",              # Virtual Football Friendlies in some feeds
    # Speculative / placeholder fight cards that the operator should never
    # promote as a real fixture. "Mundo. Posibles peleas" is a UFC/MMA
    # bucket of rumoured matchups; the participants/odds are not real.
    "posibles",         # "Mundo. Posibles peleas"
    "posible",          # singular variant
    "por confirmar",    # generic Spanish "TBD"
    "tbd",              # "TBD vs TBD"
    "to be determined",
    "speculative",
)


# Pre-computed normalized keyword set so we don't normalize on every check.
_NORMALIZED_KEYWORDS: Tuple[str, ...] = tuple(
    "".join(
        ch for ch in unicodedata.normalize("NFKD", k.lower())
        if not unicodedata.combining(ch)
    )
    for k in SYNTHETIC_KEYWORDS
)

_WS = re.compile(r"\s+")


def _normalize(text: Optional[str]) -> str:
    if not text:
        return ""
    t = text.lower()
    t = unicodedata.normalize("NFKD", t)
    t = "".join(ch for ch in t if not unicodedata.combining(ch))
    t = _WS.sub(" ", t).strip()
    return t


def is_synthetic_tournament(name: Optional[str]) -> bool:
    """True if the tournament name looks like virtual/replay/esports inventory.

    Substring match after lowercase + diacritic strip. We intentionally use
    substring (not word boundary) because feed names concatenate things
    like "FutbolVirtual" and "ESportsBattle3v3".
    """
    if not name:
        return False
    n = _normalize(name)
    if not n:
        return False
    for kw in _NORMALIZED_KEYWORDS:
        if kw in n:
            return True
    return False


def filter_synthetic(names: Iterable[str]) -> list[str]:
    """Filter helper for tournament name lists used in admin dropdowns."""
    return [n for n in names if not is_synthetic_tournament(n)]
