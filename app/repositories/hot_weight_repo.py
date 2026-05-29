"""
HotWeight repository — CRUD on the `hot_weight` table.

The admin "Weights" page and the scoring weights provider both go through
here. Kept deliberately small: list / create / update / delete / bulk-seed.
"""

from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from sqlalchemy.orm import Session

from ..logging_config import get_logger
from ..models import HotWeight
from ..models.hot_weight import WEIGHT_KINDS

logger = get_logger("app.repositories.hot_weight")


class HotWeightRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    # ─── reads ─────────────────────────────────────────────────────────
    def list_for_sport(self, sport: str, *, enabled_only: bool = False) -> List[HotWeight]:
        q = self.session.query(HotWeight).filter(HotWeight.sport == sport)
        if enabled_only:
            q = q.filter(HotWeight.enabled.is_(True))
        return q.order_by(
            HotWeight.kind.asc(),
            HotWeight.points.desc(),
            HotWeight.pattern.asc(),
        ).all()

    def get(self, weight_id: int) -> Optional[HotWeight]:
        return self.session.get(HotWeight, int(weight_id))

    def count_for_sport(self, sport: str) -> int:
        return self.session.query(HotWeight).filter(HotWeight.sport == sport).count()

    # ─── writes ────────────────────────────────────────────────────────
    def create(
        self,
        *,
        sport: str,
        kind: str,
        pattern: str,
        points: int,
        note: Optional[str] = None,
        starts_at: Optional[datetime] = None,
        ends_at: Optional[datetime] = None,
        enabled: bool = True,
        by: Optional[str] = None,
    ) -> HotWeight:
        kind = (kind or "").strip().lower()
        if kind not in WEIGHT_KINDS:
            raise ValueError(f"kind must be one of {WEIGHT_KINDS}")
        pattern = (pattern or "").strip()
        if not pattern:
            raise ValueError("pattern required")
        row = HotWeight(
            sport=sport,
            kind=kind,
            pattern=pattern,
            points=int(points),
            note=(note or None),
            starts_at=starts_at,
            ends_at=ends_at,
            enabled=bool(enabled),
            created_by=by,
            updated_by=by,
        )
        self.session.add(row)
        self.session.flush()
        logger.info(
            f"hot_weight.create sport={sport} kind={kind} pattern={pattern!r} "
            f"points={points} by={by}"
        )
        return row

    def update(self, weight_id: int, *, by: Optional[str] = None, **fields) -> Optional[HotWeight]:
        row = self.get(weight_id)
        if row is None:
            return None
        # note/starts_at/ends_at are nullable — an explicit None clears them.
        # The others are only applied when present in `fields`.
        for key in ("kind", "pattern", "points", "note", "enabled", "starts_at", "ends_at"):
            if key not in fields:
                continue
            value = fields[key]
            if key == "kind":
                value = (value or "").strip().lower()
                if value not in WEIGHT_KINDS:
                    raise ValueError(f"kind must be one of {WEIGHT_KINDS}")
            elif key == "pattern":
                value = (value or "").strip()
                if not value:
                    raise ValueError("pattern required")
            elif key == "points":
                value = int(value)
            elif key == "enabled":
                value = bool(value)
            setattr(row, key, value)
        row.updated_by = by
        row.updated_at = datetime.utcnow()
        logger.info(f"hot_weight.update id={weight_id} by={by}")
        return row

    def delete(self, weight_id: int) -> bool:
        row = self.get(weight_id)
        if row is None:
            return False
        self.session.delete(row)
        logger.info(f"hot_weight.delete id={weight_id}")
        return True

    def bulk_seed(self, sport: str, rows: List[dict], *, by: str = "seed") -> int:
        """Insert many rows for a sport. Skips (sport, kind, pattern) collisions
        so re-running is safe. Returns count inserted."""
        existing = {
            (w.kind, w.pattern.strip().lower())
            for w in self.list_for_sport(sport)
        }
        inserted = 0
        for r in rows:
            kind = (r.get("kind") or "").strip().lower()
            pattern = (r.get("pattern") or "").strip()
            if not pattern or kind not in WEIGHT_KINDS:
                continue
            if (kind, pattern.lower()) in existing:
                continue
            self.session.add(
                HotWeight(
                    sport=sport,
                    kind=kind,
                    pattern=pattern,
                    points=int(r.get("points") or 0),
                    note=r.get("note"),
                    enabled=True,
                    created_by=by,
                    updated_by=by,
                )
            )
            existing.add((kind, pattern.lower()))
            inserted += 1
        if inserted:
            self.session.flush()
        logger.info(f"hot_weight.bulk_seed sport={sport} inserted={inserted}")
        return inserted
