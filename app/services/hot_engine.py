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
    def __init__(self, session: Session, sport: str,
                 league: Optional[str] | list | tuple = None,
                 quotas: Optional[dict] = None) -> None:
        self.session = session
        self.sport = (sport or "").strip().lower() or "football"
        # A campaign may name several leagues, each optionally with its own match
        # quota. Accept one name, a list of them, or the raw column value, so
        # every existing caller keeps working.
        self.quotas: dict = dict(quotas or {})
        if league is None:
            self.leagues: list[str] = []
        elif isinstance(league, (list, tuple)):
            self.leagues = [str(x).strip() for x in league if str(x).strip()]
        else:
            from ..models.campaign import parse_league_entries
            entries = parse_league_entries(str(league))
            self.leagues = [e["name"] for e in entries]
            if not self.quotas:
                self.quotas = {e["name"]: e["limit"] for e in entries
                               if e["limit"] is not None}
        # Kept for callers and logs that read a single name.
        self.league = self.leagues[0] if len(self.leagues) == 1 else None
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

        if self.leagues:
            from ..utils.slugify import slugify_league
            wanted = {slugify_league(name) for name in self.leagues}
            all_matches = [m for m in all_matches if m.tournament_slug in wanted]

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
        # When a league filter is active the caller has already chosen which
        # tournaments are in scope — tell the scorer to skip its cross-tournament
        # diversity caps so `?limit=N` actually returns N matches. That holds for
        # two named leagues as much as for one: the cap (2-3 per tournament)
        # would silently return 4-6 for a campaign asking for 10.
        # With quotas, ask for the whole pool: the cap discards from the head of
        # the scored list, so a league that dominates the top would otherwise eat
        # the headroom and leave the campaign short of its own total.
        want = len(events) if self.quotas else limit + CANDIDATE_HEADROOM
        scored = run_scoring(
            events,
            self.sport,
            want,
            tz,
            single_league=bool(self.leagues),
        )
        auto_ordered = [
            by_id[e["event_id"]]
            for e in scored
            if e.get("event_id") in by_id
        ]
        # Per-league quotas ("2 from X, 3 from Y"). Applied to the scored order
        # rather than by scoring each league separately, so the campaign still
        # shows its hottest matches — a quota caps a league, it does not reorder
        # anything. A league with fewer hot matches than its quota contributes
        # what it has; nothing is invented to reach the number.
        if self.quotas:
            taken: Dict[str, int] = {}
            capped = []
            for m in auto_ordered:
                cap = self.quotas.get(m.tournament_name)
                if cap is not None:
                    if taken.get(m.tournament_name, 0) >= cap:
                        continue
                    taken[m.tournament_name] = taken.get(m.tournament_name, 0) + 1
                capped.append(m)
            auto_ordered = capped
        # Fallback: if the scorer rejected every candidate (e.g. UFC fights
        # scheduled past the horizon, or a sport without 1×2 odds), we still
        # have an unscored pool of real active matches. Returning [] here
        # makes /hot/{sport}.png render a blank 1×1 while the admin
        # leaderboard happily lists those matches via its own fallback.
        # Use the candidate set in upcoming-time order so the public surface
        # behaves like a "next N upcoming" view rather than a hard 404.
        if not auto_ordered:
            from datetime import datetime
            def _key(m: Match) -> tuple:
                # Earliest upcoming first; matches with no start_time sort last.
                start = m.start_time_utc or datetime.max
                return (start, m.event_id)
            auto_ordered = sorted(candidates, key=_key)
            logger.info(
                f"hot_engine fallback for sport={self.sport}: "
                f"scorer rejected all {len(candidates)} candidates, "
                f"returning time-ordered raw matches"
            )

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
