"""
HotBoost repository — CRUD on the `hot_override` table.

Current surface (positional model used by the new HotEngine):
  - positions_for(event_ids)   {event_id: slot_number}
  - suppressed_for(event_ids)  set of event_ids that should be hidden
  - set_position(event_id, position, by=...)
  - set_suppress(event_id, suppress, by=...)
  - clear_positions_for_events(event_ids)
  - clear(event_id)            remove the row entirely

Legacy surface (boolean pin + boost — kept for older clients):
  - as_dict()                  {event_id: (boost, pin)}
  - upsert(event_id, boost?, pin?, by=...)
  - delete(event_id)
"""

from __future__ import annotations

from datetime import datetime
from typing import Dict, Iterable, List, Optional, Set, Tuple

from sqlalchemy.orm import Session

from ..logging_config import get_logger
from ..models import HotBoost

logger = get_logger("app.repositories.hot_boost")


class HotBoostRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    # ─── positional model (new) ────────────────────────────────────────
    def positions_for(self, event_ids: Iterable[str]) -> Dict[str, int]:
        ids = [str(e) for e in event_ids if e]
        if not ids:
            return {}
        rows = (
            self.session.query(HotBoost.event_id, HotBoost.position)
            .filter(HotBoost.event_id.in_(ids))
            .filter(HotBoost.position.is_not(None))
            .all()
        )
        return {eid: int(pos) for eid, pos in rows}

    def suppressed_for(self, event_ids: Iterable[str]) -> Set[str]:
        ids = [str(e) for e in event_ids if e]
        if not ids:
            return set()
        rows = (
            self.session.query(HotBoost.event_id)
            .filter(HotBoost.event_id.in_(ids))
            .filter(HotBoost.suppress.is_(True))
            .all()
        )
        return {eid for (eid,) in rows}

    def set_position(
        self, event_id: str, position: Optional[int], *, by: Optional[str] = None
    ) -> HotBoost:
        return self._upsert_field(event_id, "position", position, by=by)

    def set_suppress(
        self, event_id: str, suppress: bool, *, by: Optional[str] = None
    ) -> HotBoost:
        return self._upsert_field(event_id, "suppress", bool(suppress), by=by)

    def clear_positions_for_events(self, event_ids: Iterable[str]) -> int:
        """Set position=NULL for every row in `event_ids`. Cheap idempotent reset."""
        ids = [str(e) for e in event_ids if e]
        if not ids:
            return 0
        rows = (
            self.session.query(HotBoost)
            .filter(HotBoost.event_id.in_(ids))
            .filter(HotBoost.position.is_not(None))
            .all()
        )
        for row in rows:
            row.position = None
            row.updated_at = datetime.utcnow()
        return len(rows)

    def clear(self, event_id: str) -> bool:
        """Remove the row entirely (all overrides reset for this event)."""
        row = self.get(event_id)
        if row is None:
            return False
        self.session.delete(row)
        logger.info(f"hot_override.clear event_id={event_id}")
        return True

    # ─── legacy boost/pin model (kept for older API consumers) ─────────
    def get(self, event_id: str) -> Optional[HotBoost]:
        if not event_id:
            return None
        return self.session.get(HotBoost, str(event_id))

    def list_all(self) -> List[HotBoost]:
        return self.session.query(HotBoost).all()

    def as_dict(self) -> Dict[str, Tuple[float, bool]]:
        rows = self.session.query(HotBoost.event_id, HotBoost.boost, HotBoost.pin).all()
        return {eid: (float(boost), bool(pin)) for eid, boost, pin in rows}

    def upsert(
        self,
        event_id: str,
        *,
        boost: Optional[float] = None,
        pin: Optional[bool] = None,
        by: Optional[str] = None,
    ) -> HotBoost:
        event_id = str(event_id).strip()
        if not event_id:
            raise ValueError("event_id required")
        row = self.session.get(HotBoost, event_id)
        if row is None:
            row = HotBoost(event_id=event_id, boost=0.0, pin=False, suppress=False)
            self.session.add(row)
        if boost is not None:
            row.boost = float(boost)
        if pin is not None:
            row.pin = bool(pin)
        row.updated_by = by
        row.updated_at = datetime.utcnow()
        logger.info(
            f"hot_override.upsert event_id={event_id} boost={row.boost} pin={row.pin} by={by}"
        )
        return row

    def delete(self, event_id: str) -> bool:
        return self.clear(event_id)

    # ─── internals ─────────────────────────────────────────────────────
    def _upsert_field(
        self, event_id: str, field: str, value, *, by: Optional[str]
    ) -> HotBoost:
        event_id = str(event_id).strip()
        if not event_id:
            raise ValueError("event_id required")
        row = self.session.get(HotBoost, event_id)
        if row is None:
            row = HotBoost(event_id=event_id, boost=0.0, pin=False, suppress=False)
            self.session.add(row)
        setattr(row, field, value)
        row.updated_by = by
        row.updated_at = datetime.utcnow()
        logger.info(f"hot_override.{field}.set event_id={event_id} value={value} by={by}")
        return row
