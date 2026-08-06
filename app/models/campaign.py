"""
The `campaigns` table.

A campaign represents a dynamic URL like `xxxx.com/r/random1`.

  mode = 'manual'  -> renders the editor-picked matches (see CampaignMatch)
  mode = 'auto'    -> top-N hottest matches for `sport`, optionally
                      restricted to one or more leagues (tournament_name) via
                      the `league` column. Count is supplied by `?limit=` at
                      request time; the row stores no count.

The `league` column holds either a single tournament name or, for a campaign
covering several, a JSON array of them. One column rather than two because the
alternative — a legacy `league` beside a new `leagues` — is two copies of one
fact that can disagree, and every row written before this change is already a
valid single-league value under this scheme. Read it through
`Campaign.league_names`; never parse the raw column at a call site.
"""

from __future__ import annotations

import json
from typing import List, Optional

from sqlalchemy import Boolean, Column, DateTime, Integer, String

from .base import Base, TimestampMixin


def parse_leagues(value: Optional[str]) -> List[str]:
    """The column's tournament names, in order. Empty when unfiltered.

    A plain string is one league (every pre-existing row). A JSON array is
    several. A name that happens to start with '[' is not a real risk — real
    tournament names do not — but a failed decode falls back to the literal
    value rather than dropping the filter, because losing a filter silently
    would widen a campaign to its whole sport.
    """
    raw = (value or "").strip()
    if not raw:
        return []
    if raw.startswith("["):
        try:
            decoded = json.loads(raw)
        except ValueError:
            return [raw]
        if isinstance(decoded, list):
            return [str(x).strip() for x in decoded if str(x).strip()]
        return [raw]
    return [raw]


def format_leagues(names: List[str]) -> Optional[str]:
    """Inverse of parse_leagues. One name stays a plain string so a
    single-league campaign's column looks exactly as it always did."""
    clean: List[str] = []
    for n in names or []:
        n = (n or "").strip()
        if n and n not in clean:      # a league twice would double its weight
            clean.append(n)
    if not clean:
        return None
    if len(clean) == 1:
        return clean[0]
    return json.dumps(clean, ensure_ascii=False)


class Campaign(Base, TimestampMixin):
    __tablename__ = "campaigns"

    slug = Column(String, primary_key=True)
    title = Column(String, nullable=False)
    sport = Column(String, nullable=False, index=True)
    mode = Column(String, nullable=False, default="manual")
    league = Column(String, nullable=True)
    # Default render count for auto campaigns: used when the URL carries no
    # explicit `?limit=`, and as the limit baked into the edit-page Copy URL.
    # Manual campaigns ignore it (they render their selected match list).
    hot_limit = Column(Integer, nullable=False, default=5)
    # VIP toggle: when True the public PNG renders with the "vip" color theme
    # (purple/violet); when False it uses the original "default" navy theme.
    vip = Column(Boolean, nullable=False, default=False)
    enabled = Column(Boolean, nullable=False, default=True, index=True)
    expires_at = Column(DateTime, nullable=True, index=True)
    created_by = Column(String, nullable=True)

    @property
    def league_names(self) -> List[str]:
        """The tournaments this campaign is restricted to ([] = all in sport)."""
        return parse_leagues(self.league)

    @property
    def league_label(self) -> str:
        """For the admin and the monitor: 'A', 'A + B', 'A + 2 more'."""
        names = self.league_names
        if not names:
            return ""
        if len(names) == 1:
            return names[0]
        if len(names) == 2:
            return f"{names[0]} + {names[1]}"
        return f"{names[0]} + {len(names) - 1} more"

    def __repr__(self) -> str:
        return f"<Campaign /{self.slug} sport={self.sport} mode={self.mode}>"
