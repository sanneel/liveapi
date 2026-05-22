"""
Hot override repository — CRUD on `hot_override_config` and `hot_override_match`.

Both tables are keyed on (sport, scope). Scope is the column named `mode` and
takes one of: 'prematch' | 'live' | 'all'.
"""

from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from sqlalchemy import delete
from sqlalchemy.orm import Session

from ..logging_config import get_logger
from ..models import HotOverrideConfig, HotOverrideMatch

logger = get_logger("app.repositories.hot_override")


VALID_SCOPES = ("prematch", "live", "all")
VALID_OVERRIDE_MODES = ("auto", "manual", "hybrid")


class HotOverrideRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    # ─── config ───────────────────────────────────────────────────────
    def get_config(self, sport: str, scope: str) -> Optional[HotOverrideConfig]:
        return (
            self.session.query(HotOverrideConfig)
            .filter(HotOverrideConfig.sport == sport)
            .filter(HotOverrideConfig.mode == scope)
            .one_or_none()
        )

    def get_override_mode(self, sport: str, scope: str) -> str:
        """Returns the override_mode for (sport, scope), defaulting to 'auto'
        when no config row exists. Cheap — single PK lookup."""
        cfg = self.get_config(sport, scope)
        return cfg.override_mode if cfg else "auto"

    def set_mode(
        self,
        sport: str,
        scope: str,
        override_mode: str,
        *,
        by: Optional[str] = None,
    ) -> HotOverrideConfig:
        if override_mode not in VALID_OVERRIDE_MODES:
            raise ValueError(f"invalid override_mode: {override_mode}")
        cfg = self.get_config(sport, scope)
        if cfg is None:
            cfg = HotOverrideConfig(sport=sport, mode=scope)
            self.session.add(cfg)
        cfg.override_mode = override_mode
        cfg.updated_by = by
        cfg.updated_at = datetime.utcnow()
        logger.info(
            f"hot_override.set_mode sport={sport} scope={scope} mode={override_mode} by={by}"
        )
        return cfg

    # ─── matches ──────────────────────────────────────────────────────
    def list_matches(self, sport: str, scope: str) -> List[HotOverrideMatch]:
        return (
            self.session.query(HotOverrideMatch)
            .filter(HotOverrideMatch.sport == sport)
            .filter(HotOverrideMatch.mode == scope)
            .order_by(HotOverrideMatch.position.asc())
            .all()
        )

    def list_event_ids(self, sport: str, scope: str) -> List[str]:
        rows = (
            self.session.query(HotOverrideMatch.event_id)
            .filter(HotOverrideMatch.sport == sport)
            .filter(HotOverrideMatch.mode == scope)
            .order_by(HotOverrideMatch.position.asc())
            .all()
        )
        return [r[0] for r in rows]

    def add_match(
        self,
        sport: str,
        scope: str,
        event_id: str,
        *,
        pinned: bool = True,
        by: Optional[str] = None,
    ) -> bool:
        """Add to the end of the list. No-op if already present (returns False)."""
        existing = (
            self.session.query(HotOverrideMatch)
            .filter_by(sport=sport, mode=scope, event_id=str(event_id))
            .one_or_none()
        )
        if existing is not None:
            return False
        max_pos = (
            self.session.query(HotOverrideMatch)
            .filter(HotOverrideMatch.sport == sport)
            .filter(HotOverrideMatch.mode == scope)
            .count()
        )
        self.session.add(
            HotOverrideMatch(
                sport=sport,
                mode=scope,
                event_id=str(event_id),
                position=max_pos,
                pinned=pinned,
                created_by=by,
            )
        )
        logger.info(
            f"hot_override.add_match sport={sport} scope={scope} event_id={event_id} by={by}"
        )
        return True

    def remove_match(self, sport: str, scope: str, event_id: str) -> bool:
        result = self.session.execute(
            delete(HotOverrideMatch)
            .where(HotOverrideMatch.sport == sport)
            .where(HotOverrideMatch.mode == scope)
            .where(HotOverrideMatch.event_id == str(event_id))
        )
        return (result.rowcount or 0) > 0

    def reorder(self, sport: str, scope: str, event_ids: List[str]) -> int:
        """Reassign position by the order of `event_ids`. Unlisted rows are unchanged.
        Returns the number of rows whose position was updated."""
        ids = [str(e) for e in event_ids if e]
        if not ids:
            return 0
        rows = (
            self.session.query(HotOverrideMatch)
            .filter(HotOverrideMatch.sport == sport)
            .filter(HotOverrideMatch.mode == scope)
            .filter(HotOverrideMatch.event_id.in_(ids))
            .all()
        )
        by_id = {r.event_id: r for r in rows}
        n = 0
        for pos, eid in enumerate(ids):
            r = by_id.get(eid)
            if r is None:
                continue
            r.position = pos
            n += 1
        return n

    def replace_all(
        self,
        sport: str,
        scope: str,
        event_ids: List[str],
        *,
        by: Optional[str] = None,
    ) -> int:
        """Wholesale replace: drop everything in (sport, scope), insert event_ids in order."""
        self.session.execute(
            delete(HotOverrideMatch)
            .where(HotOverrideMatch.sport == sport)
            .where(HotOverrideMatch.mode == scope)
        )
        n = 0
        for pos, eid in enumerate(event_ids):
            eid = str(eid).strip()
            if not eid:
                continue
            self.session.add(
                HotOverrideMatch(
                    sport=sport,
                    mode=scope,
                    event_id=eid,
                    position=pos,
                    pinned=True,
                    created_by=by,
                )
            )
            n += 1
        logger.info(
            f"hot_override.replace_all sport={sport} scope={scope} n={n} by={by}"
        )
        return n
