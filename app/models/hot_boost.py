"""
The `hot_override` table — per-event admin overlay on top of the HOT engine.

Semantics (current — positional model):
  position  (int|null) Lock this event to slot N (1-indexed) of the hot
                       list for its sport. The engine fills empty slots
                       with auto-ranked events.
  suppress  (bool)     Hide this event from hot output entirely.

Legacy fields kept for backward-compatibility with the older boost/pin API,
but the new HotEngine no longer reads them:

  boost (float)        Additive on top of the scorer's `_hot_score`.
  pin   (bool)         Old "always before non-pinned" flag.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, Float, ForeignKey, Integer, String

from .base import Base


class HotBoost(Base):
    __tablename__ = "hot_override"

    event_id = Column(
        String,
        ForeignKey("matches.event_id", ondelete="NO ACTION"),
        primary_key=True,
    )
    # Active surface
    position = Column(Integer, nullable=True, index=True)
    suppress = Column(Boolean, nullable=False, default=False, index=True)
    # Legacy
    boost = Column(Float, nullable=False, default=0.0)
    pin = Column(Boolean, nullable=False, default=False, index=True)
    updated_by = Column(String, nullable=True)
    updated_at = Column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )

    def __repr__(self) -> str:
        return (
            f"<HotBoost {self.event_id} position={self.position} "
            f"suppress={self.suppress}>"
        )
