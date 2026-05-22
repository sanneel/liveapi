"""
HotEngine — admin overlay on top of the legacy auto-scoring layer.

Public surface: `HotEngine(session, sport).resolve(limit)` -> List[Match].

Algorithm:
  1. Pull active candidate matches for the sport (or boxing/mma/ufc when
     sport == 'fights', matching legacy behavior).
  2. Run the existing per-sport scorer over all candidates — this is the
     unchanged "auto rank" output. Order is preserved across the rest of
     the algorithm.
  3. Drop any event marked `suppress=True` in `hot_override`.
  4. Read positional pins (`hot_override.position`) for the candidates.
     For each slot in 1..limit:
       - if a pinned event claims that slot AND is still active, use it.
       - otherwise consume the next un-used auto-ranked candidate.
  5. Cap at `limit`. With no overrides, output is byte-identical to the
     legacy scorer (engine is a no-op).

The scoring formulas themselves are NEVER touched here — only the overlay.
"""

from __future__ import annotations

from typing import Dict, List, Optional

from sqlalchemy.orm import Session

from ..config import get_settings
from ..logging_config import get_logger
from ..models import Match
from ..repositories.hot_boost_repo import HotBoostRepository
from ..repositories.match_repo import MatchRepository
from .hot_scoring_dispatch import run_scoring

logger = get_logger("app.services.hot_engine")

# Oversample so positional pinning doesn't starve the slot-fill phase.
CANDIDATE_HEADROOM = 40


class HotEngine:
    def __init__(self, session: Session, sport: str, league: Optional[str] = None) -> None:
        self.session = session
        self.sport = (sport or "").strip().lower() or "football"
        self.league = league
        self.match_repo = MatchRepository(session)
        self.boost_repo = HotBoostRepository(session)

    # ─── candidates ────────────────────────────────────────────────────
    def _candidate_matches(self) -> List[Match]:
        """Active matches in scope. `fights` pools boxing/mma/ufc the same
        way the legacy hot endpoint did."""
        if self.sport == "fights":
            sports_in_scope = ("boxing", "mma", "ufc")
        else:
            sports_in_scope = (self.sport,)

        all_matches: List[Match] = []
        for s in sports_in_scope:
            all_matches.extend(self.match_repo.find_active_by_sport(s))

        if self.league:
            from ..utils.slugify import slugify_league
            league_slug = slugify_league(self.league)
            all_matches = [m for m in all_matches if m.tournament_slug == league_slug]

        return all_matches


    # ─── public ────────────────────────────────────────────────────────
    def resolve(self, limit: int) -> List[Match]:
        limit = max(1, int(limit or 1))
        candidates = self._candidate_matches()
        if not candidates:
            return []

        by_id: Dict[str, Match] = {m.event_id: m for m in candidates}

        # Drop suppressed events before scoring — the scorer never sees them.
        suppressed = self.boost_repo.suppressed_for(by_id.keys())
        if suppressed:
            candidates = [m for m in candidates if m.event_id not in suppressed]
            by_id = {m.event_id: m for m in candidates}
            if not candidates:
                return []

        events = []
        for m in candidates:
            d = m.to_event_dict()
            d["sport"] = m.sport
            events.append(d)

        tz = get_settings().forced_timezone
        scored = run_scoring(events, self.sport, limit + CANDIDATE_HEADROOM, tz)
        auto_ordered = [
            by_id[e["event_id"]]
            for e in scored
            if e.get("event_id") in by_id
        ]

        # Build slot map from positional pins. Drop pins that point outside
        # [1, limit] or to events the candidate set doesn't have.
        positions = self.boost_repo.positions_for(by_id.keys())
        slot_map: Dict[int, str] = {}
        for eid, pos in positions.items():
            if 1 <= pos <= limit and eid in by_id:
                slot_map[pos] = eid

        used = set(slot_map.values())
        auto_queue = [m for m in auto_ordered if m.event_id not in used]

        result: List[Match] = []
        for slot in range(1, limit + 1):
            eid = slot_map.get(slot)
            if eid is not None:
                result.append(by_id[eid])
            elif auto_queue:
                result.append(auto_queue.pop(0))
            # else: gap — happens only when there aren't enough candidates,
            # in which case `result` is just shorter than `limit`.

        return result
