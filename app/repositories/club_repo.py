"""
Club repository — CRUD on the `clubs` table.

Insert-only by design: `ensure(slug, ...)` does INSERT OR IGNORE.
Admin can update mutable fields (name, logo, hide_opponent_logo) via
`update(slug, **fields)`.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import List, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..logging_config import get_logger
from ..models import Club

logger = get_logger("app.repositories.club")

SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{1,49}$")


class ClubRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    @staticmethod
    def _normalize_slug(slug: str) -> Optional[str]:
        if not slug:
            return None
        slug = slug.strip().lower()
        if not SLUG_RE.match(slug):
            return None
        return slug

    def find_by_slug(self, slug: str) -> Optional[Club]:
        s = self._normalize_slug(slug)
        if s is None:
            return None
        return self.session.get(Club, s)

    def list_all(self, limit: int = 500, offset: int = 0) -> List[Club]:
        return (
            self.session.query(Club)
            .order_by(Club.name.asc())
            .limit(limit)
            .offset(offset)
            .all()
        )

    def ensure(
        self,
        slug: str,
        name: str,
        logo: Optional[str] = None,
    ) -> Optional[Club]:
        """Insert a club row only if it doesn't already exist.

        Never overwrites — first observation wins for both `name` and `logo`.
        Returns the existing or newly-created Club, or None on bad slug.
        """
        s = self._normalize_slug(slug)
        if s is None:
            return None
        existing = self.session.get(Club, s)
        if existing is not None:
            return existing
        if not name:
            return None
        c = Club(slug=s, name=name.strip(), logo=(logo or None))
        self.session.add(c)
        logger.info(f"club.ensure created slug={s} name={name}")
        return c

    def update(self, slug: str, **fields) -> Optional[Club]:
        """Admin-driven mutation. Touches only the fields explicitly passed."""
        c = self.find_by_slug(slug)
        if c is None:
            return None
        allowed = {"name", "logo", "hide_opponent_logo"}
        for k, v in fields.items():
            if k in allowed and v is not None:
                setattr(c, k, v)
        c.updated_at = datetime.utcnow()
        return c

    def delete(self, slug: str) -> bool:
        c = self.find_by_slug(slug)
        if c is None:
            return False
        self.session.delete(c)
        logger.info(f"club.delete slug={slug}")
        return True
