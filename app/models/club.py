"""
The `clubs` table — immutable team-entity rows.

A club is a *persistent projection* of a team identity; not a campaign,
not a scheduler, not a marketing object. It exists forever once the
parser has seen its slug, with stable identity over time.

Insert policy (enforced at the repository layer):
  - `INSERT OR IGNORE` on slug — never overwrite an existing row.
  - First-seen name from parser is locked in; subsequent name drift
    in feeds does not propagate here.
  - Logo is set once on first observation; never overwritten.
  - `fallback_text` is admin-only.
  - `cta_url` defaults to `https://jugabet.cl/football/leagues/1`.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, String

from .base import Base

DEFAULT_CTA_URL = "https://jugabet.cl/football/leagues/1"


class Club(Base):
    __tablename__ = "clubs"

    slug = Column(String, primary_key=True)
    name = Column(String, nullable=False)
    logo = Column(String, nullable=True)
    fallback_text = Column(String, nullable=True)
    cta_url = Column(String, nullable=True, default=DEFAULT_CTA_URL)
    # When True, the club's PNG drops the opposing team's logo before rendering.
    # Useful when the URL is used as fan-base creative for one club only.
    hide_opponent_logo = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )

    def __repr__(self) -> str:
        return f"<Club /{self.slug} {self.name}>"
