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


def parse_league_entries(value: Optional[str]) -> List[dict]:
    """The column as [{"name": str, "limit": int|None}, ...], in order.

    Three shapes, oldest first, because each was a valid way to write this column
    and rows in all three exist:
      "Premier League"                          one league (every row predating
                                                 multi-league support)
      ["A", "B"]                                several, no per-league quota
      [{"name": "A", "limit": 2}, {"name": "B"}] several, some with a quota

    A failed decode falls back to the literal value rather than dropping the
    filter: losing it silently would widen a campaign to its whole sport.
    """
    raw = (value or "").strip()
    if not raw:
        return []
    if not raw.startswith("["):
        return [{"name": raw, "limit": None}]
    try:
        decoded = json.loads(raw)
    except ValueError:
        return [{"name": raw, "limit": None}]
    if not isinstance(decoded, list):
        return [{"name": raw, "limit": None}]
    out: List[dict] = []
    for item in decoded:
        if isinstance(item, dict):
            name = str(item.get("name") or "").strip()
            cap = item.get("limit")
            try:
                cap = int(cap) if cap not in (None, "") else None
            except (TypeError, ValueError):
                cap = None
            if cap is not None and cap < 1:
                cap = None       # "0 matches from this league" means don't name it
        else:
            name, cap = str(item).strip(), None
        if name:
            out.append({"name": name, "limit": cap})
    return out


def parse_leagues(value: Optional[str]) -> List[str]:
    """Just the tournament names, in order. Empty when unfiltered."""
    return [e["name"] for e in parse_league_entries(value)]


def format_leagues(entries) -> Optional[str]:
    """Inverse of parse_league_entries.

    Accepts plain names or {"name","limit"} dicts / (name, limit) pairs. The
    narrowest shape that can carry the data is used, so a single league with no
    quota still stores as the bare string it always did and nothing downstream
    sees a new format it did not need.
    """
    clean: List[dict] = []
    seen: set = set()
    for item in entries or []:
        if isinstance(item, dict):
            name, cap = str(item.get("name") or "").strip(), item.get("limit")
        elif isinstance(item, (list, tuple)) and len(item) == 2:
            name, cap = str(item[0] or "").strip(), item[1]
        else:
            name, cap = str(item or "").strip(), None
        if not name or name in seen:   # a league twice would double its weight
            continue
        try:
            cap = int(cap) if cap not in (None, "") else None
        except (TypeError, ValueError):
            cap = None
        if cap is not None and cap < 1:
            cap = None
        seen.add(name)
        clean.append({"name": name, "limit": cap})
    if not clean:
        return None
    if not any(e["limit"] for e in clean):
        if len(clean) == 1:
            return clean[0]["name"]
        return json.dumps([e["name"] for e in clean], ensure_ascii=False)
    return json.dumps([{k: v for k, v in e.items() if v is not None or k == "name"}
                       for e in clean], ensure_ascii=False)


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
    def league_entries(self) -> List[dict]:
        """[{"name","limit"}, ...] — limit is None for "no quota of its own"."""
        return parse_league_entries(self.league)

    @property
    def league_names(self) -> List[str]:
        """The tournaments this campaign is restricted to ([] = all in sport)."""
        return parse_leagues(self.league)

    @property
    def league_quotas(self) -> dict:
        """{league name: max matches} for the leagues that set one."""
        return {e["name"]: e["limit"] for e in self.league_entries
                if e["limit"] is not None}

    @property
    def league_label(self) -> str:
        """For the admin and the monitor: 'A ×2 + B ×3', 'A + 2 more'."""
        entries = self.league_entries
        if not entries:
            return ""

        def one(e: dict) -> str:
            return e["name"] + (f" ×{e['limit']}" if e["limit"] else "")

        if len(entries) == 1:
            return one(entries[0])
        if len(entries) == 2:
            return f"{one(entries[0])} + {one(entries[1])}"
        return f"{one(entries[0])} + {len(entries) - 1} more"

    def __repr__(self) -> str:
        return f"<Campaign /{self.slug} sport={self.sport} mode={self.mode}>"
