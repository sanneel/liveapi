"""
Stable league/tournament slug derivation.

The feed sometimes varies the casing/accents/punctuation of the same
tournament name across cycles (e.g. "Chile Primera División" vs.
"CHILE PRIMERA DIVISION"). Auto campaigns filter on the slug, not the
raw name, so the same logical league survives those variations.

The function is deliberately conservative — pure ASCII output, no
external dependency on python-slugify.
"""

from __future__ import annotations

import re
import unicodedata

_NON_ALNUM = re.compile(r"[^a-z0-9]+")


def slugify_league(name: str | None) -> str | None:
    if name is None:
        return None
    s = unicodedata.normalize("NFKD", name)
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = s.casefold().strip()
    s = _NON_ALNUM.sub("-", s).strip("-")
    return s or None
