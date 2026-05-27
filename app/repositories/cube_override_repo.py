"""
CubeOverrideRepository — CRUD on the `cube_override` table.

Per-cube admin overlay. Each (cube_slug, event_id) pair is one row:
  * position:  int|None — slot index (0-based) to pin this event in the cube
  * suppress:  bool     — drop this event from the cube entirely

Mirrors HotBoostRepository's positional API so the admin route layer can
re-use the same JSON shape and the same drag-to-slot UX.
"""

from __future__ import annotations

from datetime import datetime
from typing import Dict, Iterable, List, Optional, Set

from sqlalchemy.orm import Session

from ..logging_config import get_logger
from ..models import CubeOverride

logger = get_logger("app.repositories.cube_override")


class CubeOverrideRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    # ─── reads ─────────────────────────────────────────────────────────
    def get(self, cube_slug: str, event_id: str) -> Optional[CubeOverride]:
        if not cube_slug or not event_id:
            return None
        return (
            self.session.query(CubeOverride)
            .filter(CubeOverride.cube_slug == cube_slug)
            .filter(CubeOverride.event_id == event_id)
            .first()
        )

    def list_for_cube(self, cube_slug: str) -> List[CubeOverride]:
        if not cube_slug:
            return []
        return (
            self.session.query(CubeOverride)
            .filter(CubeOverride.cube_slug == cube_slug)
            .all()
        )

    def positions_for(self, cube_slug: str, event_ids: Iterable[str]) -> Dict[str, int]:
        """Return {event_id: slot} for any pinned rows in `cube_slug`."""
        ids = [str(e) for e in event_ids if e]
        if not cube_slug or not ids:
            return {}
        rows = (
            self.session.query(CubeOverride.event_id, CubeOverride.position)
            .filter(CubeOverride.cube_slug == cube_slug)
            .filter(CubeOverride.event_id.in_(ids))
            .filter(CubeOverride.position.is_not(None))
            .all()
        )
        return {eid: int(pos) for eid, pos in rows}

    def suppressed_for(self, cube_slug: str, event_ids: Iterable[str]) -> Set[str]:
        ids = [str(e) for e in event_ids if e]
        if not cube_slug or not ids:
            return set()
        rows = (
            self.session.query(CubeOverride.event_id)
            .filter(CubeOverride.cube_slug == cube_slug)
            .filter(CubeOverride.event_id.in_(ids))
            .filter(CubeOverride.suppress.is_(True))
            .all()
        )
        return {eid for (eid,) in rows}

    def all_pinned(self, cube_slug: str) -> Dict[int, str]:
        """Return {slot: event_id} for every pinned row in this cube — no
        candidate-id filter. Used by the resolver to honor pins even when
        the pinned event isn't currently surfaced by HotEngine."""
        if not cube_slug:
            return {}
        rows = (
            self.session.query(CubeOverride.position, CubeOverride.event_id)
            .filter(CubeOverride.cube_slug == cube_slug)
            .filter(CubeOverride.position.is_not(None))
            .all()
        )
        return {int(pos): eid for pos, eid in rows}

    def all_suppressed(self, cube_slug: str) -> Set[str]:
        """Return every event_id suppressed in this cube — no candidate
        filter. Used by the resolver to drop suppressed events from the
        auto-rank pool."""
        if not cube_slug:
            return set()
        rows = (
            self.session.query(CubeOverride.event_id)
            .filter(CubeOverride.cube_slug == cube_slug)
            .filter(CubeOverride.suppress.is_(True))
            .all()
        )
        return {eid for (eid,) in rows}

    def event_at_position(
        self, cube_slug: str, position: int
    ) -> Optional[str]:
        """If some event currently holds `position` in `cube_slug`, return
        its event_id. Used to detect + displace existing pins when the
        admin drags a different match into the slot."""
        if not cube_slug:
            return None
        row = (
            self.session.query(CubeOverride.event_id)
            .filter(CubeOverride.cube_slug == cube_slug)
            .filter(CubeOverride.position == int(position))
            .first()
        )
        return row[0] if row else None

    # ─── writes ────────────────────────────────────────────────────────
    def set_position(
        self,
        cube_slug: str,
        event_id: str,
        position: Optional[int],
        *,
        by: Optional[str] = None,
    ) -> CubeOverride:
        return self._upsert_field(cube_slug, event_id, "position", position, by=by)

    def set_suppress(
        self,
        cube_slug: str,
        event_id: str,
        suppress: bool,
        *,
        by: Optional[str] = None,
    ) -> CubeOverride:
        return self._upsert_field(cube_slug, event_id, "suppress", bool(suppress), by=by)

    def clear_positions(self, cube_slug: str) -> int:
        """Set position=NULL for every pinned row in this cube."""
        if not cube_slug:
            return 0
        rows = (
            self.session.query(CubeOverride)
            .filter(CubeOverride.cube_slug == cube_slug)
            .filter(CubeOverride.position.is_not(None))
            .all()
        )
        for row in rows:
            row.position = None
            row.updated_at = datetime.utcnow()
        return len(rows)

    def clear_position_at_slot(
        self, cube_slug: str, position: int, *, except_event_id: Optional[str] = None
    ) -> int:
        """Clear position on EVERY row in this cube currently at `position`,
        optionally excluding `except_event_id`.

        Why this exists: `event_at_position` returns at most one row, but
        rapid drag-drop races OR a previous bug can leave two rows holding
        the same position. The resolver's `all_pinned()` then silently drops
        one (dict key collision) and the cube renders only one of them while
        the other stays "pinned to slot N" forever. Clearing all duplicates
        before assigning a fresh pin keeps the (cube_slug, position) → event
        mapping single-valued.
        """
        if not cube_slug:
            return 0
        q = (
            self.session.query(CubeOverride)
            .filter(CubeOverride.cube_slug == cube_slug)
            .filter(CubeOverride.position == int(position))
        )
        if except_event_id is not None:
            q = q.filter(CubeOverride.event_id != str(except_event_id).strip())
        rows = q.all()
        for row in rows:
            row.position = None
            row.updated_at = datetime.utcnow()
        return len(rows)

    def clear_all_for_cube(self, cube_slug: str) -> int:
        """Delete every override row for this cube. Returns the number of
        rows removed. Used by the admin "Reset all overrides" button."""
        if not cube_slug:
            return 0
        rows = (
            self.session.query(CubeOverride)
            .filter(CubeOverride.cube_slug == cube_slug)
            .all()
        )
        n = len(rows)
        for row in rows:
            self.session.delete(row)
        if n:
            logger.info(
                "cube_override.clear_all_for_cube cube=%s removed=%d",
                cube_slug, n,
            )
        return n

    def clear(self, cube_slug: str, event_id: str) -> bool:
        """Remove the row entirely (both pin and suppress reset for this cube/event)."""
        row = self.get(cube_slug, event_id)
        if row is None:
            return False
        self.session.delete(row)
        logger.info(
            "cube_override.clear cube=%s event_id=%s", cube_slug, event_id
        )
        return True

    # ─── internals ─────────────────────────────────────────────────────
    def _upsert_field(
        self,
        cube_slug: str,
        event_id: str,
        field: str,
        value,
        *,
        by: Optional[str],
    ) -> CubeOverride:
        cube_slug = (cube_slug or "").strip()
        event_id = str(event_id or "").strip()
        if not cube_slug:
            raise ValueError("cube_slug required")
        if not event_id:
            raise ValueError("event_id required")
        # Mirrors HotBoostRepository._upsert_field: session.get() doesn't see
        # pending inserts in the identity map, so two calls in one
        # transaction would otherwise queue two INSERTs for the same
        # composite key.
        row = (
            self.session.query(CubeOverride)
            .filter(CubeOverride.cube_slug == cube_slug)
            .filter(CubeOverride.event_id == event_id)
            .first()
        )
        if row is None:
            row = self.session.identity_map.get(
                (CubeOverride, (cube_slug, event_id), None)
            )
        if row is None:
            row = CubeOverride(
                cube_slug=cube_slug,
                event_id=event_id,
                position=None,
                suppress=False,
            )
            self.session.add(row)
            self.session.flush()
        setattr(row, field, value)
        row.updated_by = by
        row.updated_at = datetime.utcnow()
        logger.info(
            "cube_override.%s.set cube=%s event_id=%s value=%s by=%s",
            field, cube_slug, event_id, value, by,
        )
        return row
