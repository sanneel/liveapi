"""
The `cube_blocked_slot` table — operator-reserved EMPTY slots in a cube.

Normally the cube resolver auto-fills every slot: remove a match and the next
ranked one slides in. That fights an operator who wants to clear a slot and
then place a *specific* match. A blocked slot tells the resolver "leave this
slot blank — do not auto-fill it"; the operator fills it explicitly (which
clears the block), or restores it to automatic.

One row per (cube_slug, position). Independent of `cube_override` (which is
per-event); this is purely per-slot, so it survives a match finishing/leaving
the feed and can't be auto-cleared by the finished-pin sweep.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Column, DateTime, Integer, PrimaryKeyConstraint, String

from .base import Base


class CubeBlockedSlot(Base):
    __tablename__ = "cube_blocked_slot"

    cube_slug = Column(String, nullable=False)
    position = Column(Integer, nullable=False)
    created_by = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    __table_args__ = (
        PrimaryKeyConstraint("cube_slug", "position", name="pk_cube_blocked_slot"),
    )

    def __repr__(self) -> str:
        return f"<CubeBlockedSlot cube={self.cube_slug} position={self.position}>"
