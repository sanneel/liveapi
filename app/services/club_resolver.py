"""
ClubResolver — resolves a club slug into its next upcoming match.

Independent of campaigns. Reads only `matches` (and the resolver caller
reads `clubs` for the page chrome).

Criteria (DB-driven, no fuzzy name matching):
  - is_active = True
  - status = 'prematch'
  - start_time_utc IS NOT NULL AND start_time_utc > UTCNOW()
  - (home_slug == slug) OR (away_slug == slug)
Ordered by start_time_utc ASC, capped at `limit` (default 1).

Sport scope: searches ALL sports unless `sport` is provided. A club like
'csd-colo-colo' could in principle play football and a friendly in
another sport; admin can pin sport-scope at the route layer if needed.
"""

from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from sqlalchemy.orm import Session

from ..logging_config import get_logger
from ..models import Match

logger = get_logger("app.services.club_resolver")


class ClubResolver:
    def __init__(
        self, session: Session, slug: str, sport: Optional[str] = None
    ) -> None:
        self.session = session
        self.slug = (slug or "").strip().lower()
        self.sport = (sport or "").strip().lower() or None

    def resolve(self, limit: int = 1) -> List[Match]:
        if not self.slug:
            return []
        limit = max(1, int(limit or 1))
        now = datetime.utcnow()

        q = (
            self.session.query(Match)
            .filter(Match.is_active.is_(True))
            .filter(Match.status == "prematch")
            .filter(Match.start_time_utc.is_not(None))
            .filter(Match.start_time_utc > now)
            .filter(
                (Match.home_slug == self.slug) | (Match.away_slug == self.slug)
            )
            .order_by(Match.start_time_utc.asc())
        )
        if self.sport:
            q = q.filter(Match.sport == self.sport)
        return q.limit(limit).all()
