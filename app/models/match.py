"""
The `matches` table.

Stores every event the parser has ever seen, plus its latest known odds.
`is_active=False` when the match is no longer in the feed (finished / pulled).

This table is the single source of truth used by:
  - the admin "Matches" page (searchable list)
  - campaign rendering (matches are referenced by event_id)
  - hot-score ranking
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Dict, Optional

from sqlalchemy import Boolean, Column, DateTime, Float, Index, Integer, String, Text

from .base import Base


class Match(Base):
    __tablename__ = "matches"

    # ── identity ──
    event_id = Column(String, primary_key=True)
    sport = Column(String, nullable=False, index=True)        # football, basketball, ...
    mode = Column(String, nullable=False, index=True)         # live | prematch
    status = Column(String, nullable=False, index=True)       # live | prematch

    # ── teams ──
    home_name = Column(String, nullable=False)
    away_name = Column(String, nullable=False)
    home_logo = Column(String, nullable=True)
    away_logo = Column(String, nullable=True)
    home_slug = Column(String, nullable=True, index=True)
    away_slug = Column(String, nullable=True, index=True)

    # ── meta ──
    tournament_name = Column(String, nullable=True, index=True)
    # Normalized form of tournament_name. Auto campaigns filter on this so
    # feed casing/accent variation doesn't silently break league pinning.
    tournament_slug = Column(String, nullable=True, index=True)
    href = Column(String, nullable=True)

    # ── time ──
    start_time_utc = Column(DateTime, nullable=True, index=True)
    time_raw = Column(String, nullable=True)                  # display string "Hoy, 20:00"

    # ── score (live) ──
    home_score = Column(Integer, nullable=True)
    away_score = Column(Integer, nullable=True)

    # ── market ──
    market_type = Column(String, nullable=True)               # 1x2 | winner | total
    market_name = Column(String, nullable=True)
    odds_json = Column(Text, nullable=True)                   # JSON-encoded odds dict

    # ── ranking / state ──
    hot_score = Column(Float, nullable=True, index=True)
    is_active = Column(Boolean, default=True, nullable=False, index=True)
    # Synthetic content marker — virtual football, FIFA replays, esports
    # replays, etc. Populated at parser-write time from
    # `app.utils.quality.is_synthetic_tournament`. Read paths (campaign
    # picker, HotEngine) filter this out by default so admins don't
    # accidentally render a fake fixture as a public PNG.
    is_synthetic = Column(Boolean, default=False, nullable=False, index=True)

    # ── timestamps ──
    first_seen_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    last_updated_at = Column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )

    __table_args__ = (
        Index("ix_matches_sport_status_active", "sport", "status", "is_active"),
        Index("ix_matches_active_hot", "is_active", "hot_score"),
        Index("ix_matches_sport_active", "sport", "is_active"),
    )

    # ─────────────────────────────────────────────────────────────────
    def odds(self) -> Dict[str, Any]:
        """Decode odds_json into a dict (never raises)."""
        if not self.odds_json:
            return {}
        try:
            return json.loads(self.odds_json)
        except Exception:
            return {}

    def to_event_dict(self) -> Dict[str, Any]:
        """
        Convert to the same dict shape `parse_html` produces, so this Match
        can be fed directly to scoring / render code without changes.

        `is_active` and `is_synthetic` are passed through so the admin UI
        can surface INACTIVE / SYN badges on JS-rendered match rows; the
        scoring / render code already ignores extra keys.
        """
        return {
            "event_id": self.event_id,
            "href": self.href,
            "status": self.status,
            "sport": self.sport,
            "time": {
                "raw": self.time_raw,
                "utc": self.start_time_utc.isoformat() if self.start_time_utc else None,
            },
            "tournament": {"name": self.tournament_name},
            "competitors": {
                "home": {"name": self.home_name, "logo": self.home_logo, "slug": self.home_slug},
                "away": {"name": self.away_name, "logo": self.away_logo, "slug": self.away_slug},
            },
            "score": {"home": self.home_score, "away": self.away_score},
            "market": {
                "name": self.market_name,
                "type": self.market_type,
                "odds": self.odds(),
            },
            "is_active": bool(self.is_active),
            "is_synthetic": bool(self.is_synthetic),
        }

    def __repr__(self) -> str:
        return f"<Match {self.event_id} {self.home_name} vs {self.away_name}>"
