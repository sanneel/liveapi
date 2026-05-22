"""
Records every public render of a campaign URL.

IP is hashed (SHA-256) for privacy — we can count unique opens without
storing PII. user_agent is kept truncated.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Column, DateTime, Integer, String

from .base import Base


class CampaignHit(Base):
    __tablename__ = "campaign_hits"

    id = Column(Integer, primary_key=True, autoincrement=True)
    campaign_slug = Column(String, nullable=False, index=True)
    ts = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    ip_hash = Column(String, nullable=True)
    user_agent = Column(String, nullable=True)

    def __repr__(self) -> str:
        return f"<CampaignHit {self.campaign_slug} @ {self.ts.isoformat()}>"
