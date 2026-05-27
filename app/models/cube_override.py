"""
The `cube_override` table — per-cube admin overlay on top of the cube resolver.

A cube theme (e.g. `worldcup`, `ucl`) normally auto-picks the top in-scope
match via HotEngine + theme tournament filter. The override layer lets an
operator pin a specific match to a specific slot of a specific cube, or
suppress a match from that cube entirely. Operating on `(cube_slug, event_id)`
keeps cubes independent — pinning a match into the World Cup cube doesn't
disturb the UCL cube even when both reference the same fixture.

Mirrors `hot_override` semantically but the composite key changes:
  hot_override:  PK = event_id              (one row per match, global)
  cube_override: PK = (cube_slug, event_id) (one row per (cube, match))

Slot semantics:
  position  (int|null) Lock this event to slot N of the cube theme's match
                       face list (0-indexed to match CubeTheme.faces[i].match_index).
                       NULL = no positional pin; auto-rank may use this match.
  suppress  (bool)     Hide this event from THIS cube entirely.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    PrimaryKeyConstraint,
    String,
)

from .base import Base


class CubeOverride(Base):
    __tablename__ = "cube_override"

    cube_slug = Column(String, nullable=False)
    event_id = Column(
        String,
        ForeignKey("matches.event_id", ondelete="CASCADE"),
        nullable=False,
    )
    position = Column(Integer, nullable=True, index=True)
    suppress = Column(Boolean, nullable=False, default=False, index=True)
    updated_by = Column(String, nullable=True)
    updated_at = Column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )

    __table_args__ = (
        PrimaryKeyConstraint("cube_slug", "event_id", name="pk_cube_override"),
    )

    def __repr__(self) -> str:
        return (
            f"<CubeOverride cube={self.cube_slug} event={self.event_id} "
            f"position={self.position} suppress={self.suppress}>"
        )
