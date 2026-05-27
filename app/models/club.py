"""
The `clubs` table — immutable team-entity rows.

A club is a *persistent projection* of a team identity; not a campaign,
not a scheduler, not a marketing object. It exists once an admin manually
creates the slug, with stable identity over time.

Insert policy (enforced at the repository layer):
  - Admin manually creates clubs; the parser does NOT auto-insert.
  - `INSERT OR IGNORE` on slug — never overwrite an existing row.
  - First-seen name is locked in; subsequent name changes from the admin
    are allowed but parser feed drift does not propagate here.
  - Logo is admin-controlled.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, String

from .base import Base


class Club(Base):
    __tablename__ = "clubs"

    slug = Column(String, primary_key=True)
    name = Column(String, nullable=False)
    logo = Column(String, nullable=True)
    # When True, the club's PNG drops the opposing team's logo before rendering.
    # Useful when the URL is used as fan-base creative for one club only.
    hide_opponent_logo = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )

    def __repr__(self) -> str:
        return f"<Club /{self.slug} {self.name}>"
