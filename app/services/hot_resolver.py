"""
HotResolver — resolves a sport+scope into the ordered list of matches
that a `mode='hot'` campaign should render.

Three override branches, chosen by `hot_override_config.override_mode`:

  auto    Today's behaviour: pool active matches for the sport (optionally
          filtered by parser mode), run the legacy per-sport scorer, return
          top N as Match rows.

  manual  Use the admin-curated override list verbatim, in admin order.
          Drop matches no longer active. Cap at `limit`.

  hybrid  Take pinned overrides first (in admin order), then fill the
          remainder with the auto scorer, skipping event_ids already pinned.

When no `hot_override_config` row exists for (sport, scope), `override_mode`
defaults to 'auto' — byte-identical output to pre-Phase-3 behaviour.
"""

from __future__ import annotations

from typing import Dict, List

from sqlalchemy.orm import Session

from ..config import get_settings
from ..logging_config import get_logger
from ..models import Match
from ..repositories.hot_override_repo import HotOverrideRepository
from ..repositories.match_repo import MatchRepository
from .hot_scoring_dispatch import run_scoring

logger = get_logger("app.services.hot_resolver")


VALID_SCOPES = ("prematch", "live", "all")


class HotResolver:
    """Resolves (sport, scope) → ordered List[Match].

    `scope` here is the value of `Campaign.hot_mode`: 'all' | 'prematch' | 'live'.
    """

    def __init__(self, session: Session, sport: str, scope: str) -> None:
        self.session = session
        self.sport = sport
        self.scope = scope if scope in VALID_SCOPES else "all"
        self.override_repo = HotOverrideRepository(session)
        self.match_repo = MatchRepository(session)

    # ─── public ───────────────────────────────────────────────────────
    def resolve(self, limit: int) -> List[Match]:
        limit = max(1, int(limit or 1))
        override_mode = self.override_repo.get_override_mode(self.sport, self.scope)

        if override_mode == "manual":
            return self._resolve_manual(limit)
        if override_mode == "hybrid":
            return self._resolve_hybrid(limit)
        return self._resolve_auto(limit)

    # ─── internals ────────────────────────────────────────────────────
    def _candidate_matches(self) -> List[Match]:
        """Active matches in scope for this resolver.

        Legacy behaviour: a `sport='fights'` campaign pools boxing+mma+ufc
        rows since there is no `Match.sport='fights'`. Preserved here.
        """
        if self.sport == "fights":
            sports_in_scope = ("boxing", "mma", "ufc")
        else:
            sports_in_scope = (self.sport,)

        all_matches: List[Match] = []
        for s in sports_in_scope:
            all_matches.extend(self.match_repo.find_active_by_sport(s))

        if self.scope == "prematch":
            return [m for m in all_matches if m.mode == "prematch"]
        if self.scope == "live":
            return [m for m in all_matches if m.mode == "live"]
        return all_matches  # scope == "all"

    def _resolve_auto(self, limit: int) -> List[Match]:
        candidates = self._candidate_matches()
        if not candidates:
            return []

        events = []
        for m in candidates:
            d = m.to_event_dict()
            # `fights` scorer expects each event tagged with its concrete sport
            d["sport"] = m.sport
            events.append(d)

        tz = get_settings().forced_timezone
        scored = run_scoring(events, self.sport, limit, tz)

        by_id: Dict[str, Match] = {m.event_id: m for m in candidates}
        ordered = [by_id.get(e.get("event_id")) for e in scored if e.get("event_id") in by_id]
        return [m for m in ordered if m is not None]

    def _resolve_manual(self, limit: int) -> List[Match]:
        event_ids = self.override_repo.list_event_ids(self.sport, self.scope)
        if not event_ids:
            return []
        # Load matches and preserve admin order. Drop inactive.
        matches = self.match_repo.find_by_event_ids(event_ids)
        by_id: Dict[str, Match] = {m.event_id: m for m in matches if m.is_active}
        ordered = [by_id[eid] for eid in event_ids if eid in by_id]
        return ordered[:limit]

    def _resolve_hybrid(self, limit: int) -> List[Match]:
        pinned_ids = self.override_repo.list_event_ids(self.sport, self.scope)
        pinned_set = set(pinned_ids)

        # Pinned first, in admin order, dropping inactive.
        pinned_matches: List[Match] = []
        if pinned_ids:
            loaded = self.match_repo.find_by_event_ids(pinned_ids)
            by_id: Dict[str, Match] = {m.event_id: m for m in loaded if m.is_active}
            pinned_matches = [by_id[eid] for eid in pinned_ids if eid in by_id]
            pinned_matches = pinned_matches[:limit]

        remaining = limit - len(pinned_matches)
        if remaining <= 0:
            return pinned_matches

        # Fill with auto, skipping anything already pinned.
        candidates = [m for m in self._candidate_matches() if m.event_id not in pinned_set]
        if not candidates:
            return pinned_matches

        events = []
        for m in candidates:
            d = m.to_event_dict()
            d["sport"] = m.sport
            events.append(d)

        tz = get_settings().forced_timezone
        # Ask the scorer for `remaining` results — it caps internally too.
        scored = run_scoring(events, self.sport, remaining, tz)
        by_id = {m.event_id: m for m in candidates}
        auto_picked = [by_id.get(e.get("event_id")) for e in scored if e.get("event_id") in by_id]
        auto_picked = [m for m in auto_picked if m is not None][:remaining]

        return pinned_matches + auto_picked
