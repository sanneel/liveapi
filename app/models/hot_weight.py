"""
The `hot_weight` table — admin-editable scoring weights per sport.

Replaces the static lists in `weights_<sport>.py` as the runtime source of
truth. Those files are still used once, to *seed* this table the first time a
sport has no rows; after that every weight can be created / edited / disabled
from the admin "Weights" page and the scorer picks the change up on its next
cycle (no restart).

One row = one weight rule:
  kind     'league' | 'team' | 'word'
             league → matched against the tournament name
             team   → matched against the home OR away team name
             word   → matched against tournament + both team names (catch-all)
  pattern  human-readable substring; matching is accent/case-insensitive and
           uses the same `normalize()` rules as the scorer.
  points   integer added to a match's score while this rule is active
           (negative demotes — e.g. Junior: -200).
  enabled  soft on/off without deleting the row.
  starts_at / ends_at  optional active window (Chile time). NULL = unbounded.
           This is how a temporary boost reverts itself: past `ends_at` the
           rule simply stops counting, no edit needed.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Integer,
    String,
    UniqueConstraint,
    Index,
)

from .base import Base

WEIGHT_KINDS = ("league", "team", "word")


class HotWeight(Base):
    __tablename__ = "hot_weight"

    id = Column(Integer, primary_key=True, autoincrement=True)
    sport = Column(String, nullable=False, index=True)
    kind = Column(String, nullable=False)  # league | team | word
    pattern = Column(String, nullable=False)
    points = Column(Integer, nullable=False, default=0)
    enabled = Column(Boolean, nullable=False, default=True)
    note = Column(String, nullable=True)

    # Optional active window (Chile time). NULL on either side = unbounded.
    starts_at = Column(DateTime, nullable=True)
    ends_at = Column(DateTime, nullable=True)

    created_by = Column(String, nullable=True)
    updated_by = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )

    __table_args__ = (
        UniqueConstraint("sport", "kind", "pattern", name="uq_hot_weight_skp"),
        Index("ix_hot_weight_sport_enabled", "sport", "enabled"),
    )

    def __repr__(self) -> str:
        return f"<HotWeight {self.sport}/{self.kind} {self.pattern!r} {self.points:+d}>"
