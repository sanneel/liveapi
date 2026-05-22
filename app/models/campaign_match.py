"""
The `campaign_matches` junction table.

Links a campaign (mode='manual') to the specific matches the editor picked.
position controls render order. pinned forces the match to render even when
its hot_score is low.
"""

from __future__ import annotations

from sqlalchemy import Boolean, Column, ForeignKey, Integer, PrimaryKeyConstraint, String

from .base import Base


class CampaignMatch(Base):
    __tablename__ = "campaign_matches"

    campaign_slug = Column(
        String,
        ForeignKey("campaigns.slug", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    event_id = Column(
        String,
        ForeignKey("matches.event_id"),
        nullable=False,
        index=True,
    )
    position = Column(Integer, nullable=False, default=0)
    pinned = Column(Boolean, nullable=False, default=False)

    __table_args__ = (PrimaryKeyConstraint("campaign_slug", "event_id"),)

    def __repr__(self) -> str:
        return f"<CampaignMatch {self.campaign_slug} → {self.event_id} pos={self.position}>"
