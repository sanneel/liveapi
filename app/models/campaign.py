"""
The `campaigns` table.

A campaign represents a dynamic URL like `xxxx.com/r/random1`.

  mode = 'manual'  -> renders the editor-picked matches (see CampaignMatch)
  mode = 'auto'    -> top-N hottest matches for `sport`, optionally
                      restricted to one league (tournament_name) via the
                      `league` column. Count is supplied by `?limit=` at
                      request time; the row stores no count.
"""

from __future__ import annotations

from sqlalchemy import Boolean, Column, DateTime, Integer, String

from .base import Base, TimestampMixin


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

    def __repr__(self) -> str:
        return f"<Campaign /{self.slug} sport={self.sport} mode={self.mode}>"
