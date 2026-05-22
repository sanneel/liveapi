"""
Hot override system tables.

`hot_override_config` — one row per (sport, scope); chooses how the hot list is built.
`hot_override_match`  — ordered list of admin-selected matches for that (sport, scope).

Override scope (`mode` column) is independent of the parser FEEDS dimension.
Valid values: 'prematch' | 'live' | 'all'. A campaign with `hot_mode='all'`
reads overrides at `(sport, 'all')`, etc.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
)

from .base import Base


class HotOverrideConfig(Base):
    __tablename__ = "hot_override_config"

    sport = Column(String, primary_key=True)
    mode = Column(String, primary_key=True)  # scope: prematch | live | all
    override_mode = Column(String, nullable=False, default="auto")  # auto | manual | hybrid
    updated_by = Column(String, nullable=True)
    updated_at = Column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )

    def __repr__(self) -> str:
        return f"<HotOverrideConfig {self.sport}/{self.mode}={self.override_mode}>"


class HotOverrideMatch(Base):
    __tablename__ = "hot_override_match"

    id = Column(Integer, primary_key=True, autoincrement=True)
    sport = Column(String, nullable=False)
    mode = Column(String, nullable=False)  # scope: prematch | live | all
    event_id = Column(
        String,
        ForeignKey("matches.event_id", ondelete="NO ACTION"),
        nullable=False,
    )
    position = Column(Integer, nullable=False, default=0)
    pinned = Column(Boolean, nullable=False, default=True)
    created_by = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    __table_args__ = (
        UniqueConstraint("sport", "mode", "event_id", name="uq_hot_override_match_smv"),
        Index(
            "ix_hot_override_match_sport_mode_position",
            "sport",
            "mode",
            "position",
        ),
        Index("ix_hot_override_match_event_id", "event_id"),
    )

    def __repr__(self) -> str:
        return f"<HotOverrideMatch {self.sport}/{self.mode} pos={self.position} {self.event_id}>"
