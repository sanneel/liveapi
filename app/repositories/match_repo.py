"""
Match repository — all queries against the `matches` table.

Public surface:
  - upsert_event(event_dict, sport, mode)        single match upsert
  - bulk_upsert(events, sport, mode)             many matches at once
  - deactivate_stale(sport, mode, active_ids)    mark dropped matches inactive
  - deactivate_expired(hours)                    mark old matches inactive
  - find_by_event_id / find_by_event_ids
  - find_active_by_sport(sport, mode=None)
  - search(query, sport, status, limit, offset)
  - count_active()
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from typing import Any, Dict, Iterable, List, Optional

from sqlalchemy import update
from sqlalchemy.orm import Session

from ..logging_config import get_logger
from ..models import Campaign, HotBoost, Match
from ..models.campaign_match import CampaignMatch
from ..utils.quality import is_synthetic_tournament
from ..utils.slugify import slugify_league

logger = get_logger("app.repositories.match")


class MatchRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    # ─── parse helpers ────────────────────────────────────────────────
    @staticmethod
    def _parse_utc(value: Optional[str]) -> Optional[datetime]:
        if not value:
            return None
        try:
            # accept "2026-05-19T22:00:00+00:00" or "...Z"
            v = value.replace("Z", "+00:00")
            return datetime.fromisoformat(v).replace(tzinfo=None)
        except Exception:
            return None

    @staticmethod
    def _odds_to_json(odds: Any) -> Optional[str]:
        if not isinstance(odds, dict) or not odds:
            return None
        # Treat "no real odds" (e.g. {"odds": []} or all dashes) as None, so an
        # empty pass from one feed doesn't wipe the odds another feed already
        # set — matches aggregate odds across feeds (broad prematch list vs the
        # league overlays, which cover the same fixtures with better odds).
        def _val(v: Any) -> bool:
            return v not in (None, "", "-")
        has_real = (
            _val(odds.get("p1")) or _val(odds.get("p2")) or _val(odds.get("draw"))
            or _val(odds.get("over")) or _val(odds.get("under"))
            or any(_val(x) for x in (odds.get("odds") or []))
        )
        if not has_real:
            return None
        try:
            return json.dumps(odds, ensure_ascii=False)
        except Exception:
            return None

    # ─── upsert ───────────────────────────────────────────────────────
    def upsert_event(
        self,
        event: Dict[str, Any],
        sport: str,
        mode: str,
        prefetched: Optional[Dict[str, Match]] = None,
    ) -> Optional[Match]:
        """Insert or update one event. Returns the Match instance, or None on failure.

        If `prefetched` is provided, look the existing row up in that dict instead
        of issuing a per-event SELECT (see `bulk_upsert`).
        """
        event_id = str(event.get("event_id") or "").strip()
        if not event_id:
            logger.warning("upsert_event: missing event_id, skipping")
            return None

        comps = event.get("competitors") or {}
        home = comps.get("home") or {}
        away = comps.get("away") or {}
        score = event.get("score") or {}
        market = event.get("market") or {}
        time_info = event.get("time") or {}
        tournament = event.get("tournament") or {}

        home_name = (home.get("name") or "").strip()
        away_name = (away.get("name") or "").strip()
        if not home_name or not away_name:
            logger.debug(f"upsert_event: {event_id} missing team names, skipping")
            return None

        if prefetched is not None:
            match = prefetched.get(event_id)
        else:
            match = self.session.get(Match, event_id)
        now = datetime.utcnow()
        is_new = match is None

        if is_new:
            match = Match(
                event_id=event_id,
                first_seen_at=now,
            )
            self.session.add(match)
            if prefetched is not None:
                prefetched[event_id] = match

        # Update all fields. Use existing value as fallback to avoid wiping
        # data on a partial refresh.
        match.sport = sport
        # H4: don't let a prematch cycle clobber a row that's been promoted
        # to live by the live feed. The match disappearing from /hot during
        # the next prematch parse was the most common "missing match" cause.
        incoming_status = (event.get("status") or "").strip().lower()
        if mode == "live" or incoming_status == "live" or match.mode != "live":
            match.mode = mode
        match.status = event.get("status") or match.status or "prematch"
        match.home_name = home_name
        match.away_name = away_name
        match.home_logo = home.get("logo") or match.home_logo
        match.away_logo = away.get("logo") or match.away_logo
        # Slugs come from data-event-competitors JSON; fall back to existing
        # value so a feed cycle that lost the JSON doesn't wipe them.
        match.home_slug = (home.get("slug") or "").strip() or match.home_slug
        match.away_slug = (away.get("slug") or "").strip() or match.away_slug
        match.tournament_id = tournament.get("id") or match.tournament_id
        new_tournament_name = tournament.get("name") or match.tournament_name
        if new_tournament_name != match.tournament_name:
            match.tournament_name = new_tournament_name
            match.tournament_slug = slugify_league(new_tournament_name)
            match.is_synthetic = is_synthetic_tournament(new_tournament_name)
        elif match.tournament_slug is None and match.tournament_name:
            match.tournament_slug = slugify_league(match.tournament_name)
        # Re-classify on every upsert so a previously-mis-tagged row gets
        # corrected when its tournament name stays stable but the keyword
        # list grows. Cheap (string match).
        if match.tournament_name is not None:
            match.is_synthetic = is_synthetic_tournament(match.tournament_name)
        match.href = event.get("href") or match.href
        match.time_raw = time_info.get("raw") or match.time_raw

        utc = self._parse_utc(time_info.get("utc"))
        if utc is not None:
            match.start_time_utc = utc

        match.home_score = score.get("home") if score.get("home") is not None else match.home_score
        match.away_score = score.get("away") if score.get("away") is not None else match.away_score
        # Only update the market (type/name/odds) when this feed actually
        # carries odds for the match, so an empty pass doesn't wipe — or
        # mislabel as "unknown" — the market another feed already set.
        new_odds = self._odds_to_json(market.get("odds"))
        if new_odds is not None:
            match.market_type = market.get("type") or match.market_type
            match.market_name = market.get("name") or match.market_name
            match.odds_json = new_odds

        match.is_active = True
        match.last_updated_at = now

        if is_new:
            logger.info(
                f"NEW match {event_id}: {home_name} vs {away_name} [{sport}/{mode}]"
            )
        return match

    def bulk_upsert(self, events: Iterable[Dict[str, Any]], sport: str, mode: str) -> int:
        # C2: pre-load all existing rows in one query so upsert_event doesn't
        # issue a SELECT per event. Cuts cycle DB round-trips from O(N) to O(1).
        events_list = list(events)
        ids = [
            str(e.get("event_id")).strip()
            for e in events_list
            if e.get("event_id")
        ]
        prefetched: Dict[str, Match] = {}
        if ids:
            for m in self.session.query(Match).filter(Match.event_id.in_(ids)).all():
                prefetched[m.event_id] = m
        n = 0
        for event in events_list:
            try:
                if self.upsert_event(event, sport, mode, prefetched=prefetched) is not None:
                    n += 1
            except Exception:
                logger.exception(f"bulk_upsert: failed for event {event.get('event_id')}")
        return n

    # ─── lifecycle ────────────────────────────────────────────────────
    # Grace window for deactivate_stale.
    #
    # A match must be MISSING from EVERY feed that could cover it for this
    # many seconds before it gets marked inactive. Why so generous:
    #
    #   * Jugabet `/<sport>/prematch/1` is **page 1 only**. Popular leagues
    #     (Champions League, etc.) get pushed off page 1 whenever lower
    #     leagues kick off — they're still real prematch matches, they're
    #     just not on page 1 right now. Sibling overlay feeds
    #     (prematch_leagues_*) touch them every ~240s; primary prematch
    #     runs every ~120s. The grace MUST be larger than (overlay
    #     cadence + slowest-ever overlay cycle + a margin), or any slow
    #     overlay run causes the primary to wipe the match.
    #   * Live feeds rotate which matches appear on page 1 as games end /
    #     new ones kick off. A real live match can vanish from page 1 for
    #     5-10 minutes mid-game and reappear later.
    #   * `deactivate_expired` (6h after start_time_utc) is the real
    #     "this match is over" safety net; deactivate_stale is only a
    #     belt-and-braces cleanup for matches that left the feed AND
    #     also passed their start time without being scraped.
    #
    # 1800s (30 min) gives ~7× the overlay cycle as slack, which is the
    # difference between "ghost reactivation flicker every cycle" and
    # "match stays present until the 6-hour expiry kicks in normally".
    DEACTIVATE_GRACE_SECONDS = 1800

    def deactivate_stale(
        self,
        sport: str,
        mode: str,
        active_event_ids: Iterable[str],
        grace_seconds: Optional[int] = None,
    ) -> int:
        """Mark matches in this (sport, mode) feed that are NOT in active_event_ids as inactive.

        Only deactivates rows whose `last_updated_at` is older than the grace
        window. A match still being upserted by a sibling feed (overlay,
        live↔prematch swap) stays active.
        """
        ids = [str(eid) for eid in active_event_ids if eid]
        grace = self.DEACTIVATE_GRACE_SECONDS if grace_seconds is None else int(grace_seconds)
        grace_cutoff = datetime.utcnow() - timedelta(seconds=grace)

        # Diagnostic visibility: log which rows are about to be deactivated.
        # Without this, "my match disappeared" bug reports are unrecoverable
        # after the fact because the row's status just silently flips.
        candidates_q = (
            self.session.query(Match)
            .filter(Match.sport == sport)
            .filter(Match.mode == mode)
            .filter(Match.is_active.is_(True))
            .filter(Match.last_updated_at < grace_cutoff)
        )
        if ids:
            candidates_q = candidates_q.filter(~Match.event_id.in_(ids))
        candidates = candidates_q.all()
        if candidates:
            sample = [
                f"{m.event_id}({m.home_name} vs {m.away_name}, "
                f"tournament={m.tournament_name}, last_seen={m.last_updated_at})"
                for m in candidates[:5]
            ]
            logger.warning(
                "deactivate_stale: marking %d inactive in %s/%s (grace=%ds). "
                "Sample: %s",
                len(candidates), sport, mode, grace, " | ".join(sample),
            )

        if not ids:
            # Bug 8: live feeds have no start_time_utc-based fallback, so an
            # empty live cycle MUST authoritatively deactivate; otherwise
            # finished live matches stay is_active=True forever ("ghost
            # live"). Prematch feeds still no-op on empty to avoid wiping
            # the future schedule on a transient outage — deactivate_expired
            # cleans those up.
            if mode != "live":
                return 0
            stmt = (
                update(Match)
                .where(Match.sport == sport)
                .where(Match.mode == mode)
                .where(Match.is_active.is_(True))
                .where(Match.last_updated_at < grace_cutoff)
                .values(is_active=False, last_updated_at=datetime.utcnow())
            )
            return int(self.session.execute(stmt).rowcount or 0)
        stmt = (
            update(Match)
            .where(Match.sport == sport)
            .where(Match.mode == mode)
            .where(Match.is_active.is_(True))
            .where(~Match.event_id.in_(ids))
            .where(Match.last_updated_at < grace_cutoff)
            .values(is_active=False, last_updated_at=datetime.utcnow())
        )
        result = self.session.execute(stmt)
        return int(result.rowcount or 0)

    def protected_event_ids(self) -> List[str]:
        """event_ids that must NEVER be auto-deactivated: a match pinned to an
        enabled campaign or pinned into the hot list. Losing one of these breaks
        a live campaign/hot slot, so the reapers always skip them."""
        try:
            ids = {
                r[0]
                for r in (
                    self.session.query(CampaignMatch.event_id)
                    .join(Campaign, Campaign.slug == CampaignMatch.campaign_slug)
                    .filter(Campaign.enabled.is_(True))
                    .all()
                )
            }
            ids |= {
                r[0]
                for r in self.session.query(HotBoost.event_id)
                .filter(HotBoost.position.is_not(None))
                .all()
            }
            return [i for i in ids if i]
        except Exception:
            logger.warning("protected_event_ids query failed", exc_info=True)
            return []

    def reactivate_protected(self) -> int:
        """Re-activate any campaign/hot-pinned match that was deactivated.
        Heals rows the reaper removed before the exemption existed."""
        prot = self.protected_event_ids()
        if not prot:
            return 0
        stmt = (
            update(Match)
            .where(Match.is_active.is_(False))
            .where(Match.event_id.in_(prot))
            .values(is_active=True, last_updated_at=datetime.utcnow())
        )
        return int(self.session.execute(stmt).rowcount or 0)

    def deactivate_expired(self, hours: int = 6) -> int:
        """Mark matches whose scheduled start was more than `hours` ago as inactive."""
        cutoff = datetime.utcnow() - timedelta(hours=hours)
        stmt = (
            update(Match)
            .where(Match.is_active.is_(True))
            .where(Match.start_time_utc.is_not(None))
            .where(Match.start_time_utc < cutoff)
        )
        prot = self.protected_event_ids()
        if prot:
            stmt = stmt.where(Match.event_id.not_in(prot))
        stmt = stmt.values(is_active=False, last_updated_at=datetime.utcnow())
        result = self.session.execute(stmt)
        return int(result.rowcount or 0)

    def deactivate_synthetic_not_seen(self, minutes: int = 45) -> int:
        """Reap active *synthetic* (virtual/esports/replay) matches not seen
        in any feed within `minutes`.

        Virtual inventory is streamed as "live" with no start_time_utc, so it
        falls through both existing reapers: deactivate_stale exempts live
        feeds, and deactivate_expired needs a start_time. Left alone it grows
        without bound (observed: 15k+ active synthetic football rows drowning
        the scoring pool). A virtual match runs only minutes, so anything not
        re-seen for `minutes` has certainly ended. Scoped to is_synthetic so a
        transient real-feed outage can never drop a genuine fixture.
        """
        cutoff = datetime.utcnow() - timedelta(minutes=minutes)
        stmt = (
            update(Match)
            .where(Match.is_active.is_(True))
            .where(Match.is_synthetic.is_(True))
            .where(Match.last_updated_at < cutoff)
            .values(is_active=False, last_updated_at=datetime.utcnow())
        )
        result = self.session.execute(stmt)
        return int(result.rowcount or 0)

    def deactivate_not_seen(
        self, minutes: int, modes: Optional[Iterable[str]] = None
    ) -> int:
        """Deactivate active matches not upserted by ANY feed within `minutes`.

        This is the safe replacement for the per-feed ``deactivate_stale``.
        ``deactivate_stale`` keyed off one feed's page membership, so the
        firehose (``/football/prematch/1``) could reap World Cup / league /
        campaign fixtures — they share ``mode='prematch'`` but live in sibling
        overlay feeds — whenever an overlay stalled or a match rotated off
        page 1. Keying purely off ``last_updated_at`` means a match kept alive
        by *any* feed survives; only fixtures genuinely gone from every feed for
        ``minutes`` are dropped. ``deactivate_expired`` (start_time-based) is
        still the backstop for finished games.
        """
        cutoff = datetime.utcnow() - timedelta(minutes=minutes)
        stmt = (
            update(Match)
            .where(Match.is_active.is_(True))
            .where(Match.is_synthetic.is_(False))
            .where(Match.last_updated_at < cutoff)
        )
        if modes:
            stmt = stmt.where(Match.mode.in_(list(modes)))
        prot = self.protected_event_ids()
        if prot:
            stmt = stmt.where(Match.event_id.not_in(prot))
        stmt = stmt.values(is_active=False, last_updated_at=datetime.utcnow())
        result = self.session.execute(stmt)
        return int(result.rowcount or 0)

    def update_result_odds(self, event_id: str, outcomes: Dict[int, float]) -> bool:
        """Refresh ONLY the result-market odds of an existing match.

        Used by the priority odds parser (browserless HTTP). Maps
        {0:home, 1:draw, 3:away} -> the same {p1, draw, p2} JSON the normal
        upsert writes, via _odds_to_json for identical validation/format. Does
        NOT create matches and never touches teams/time/score. Returns True if a
        row existed and was updated.
        """
        match = self.session.get(Match, str(event_id))
        if match is None:
            return False
        p1, draw, p2 = outcomes.get(0), outcomes.get(1), outcomes.get(3)

        def _fmt(v):
            try:
                return f"{float(v):.2f}"
            except (TypeError, ValueError):
                return None

        if draw is not None:
            odds = {"p1": _fmt(p1), "draw": _fmt(draw), "p2": _fmt(p2), "more_odds": False}
            market_type = "1x2"
        else:
            odds = {"p1": _fmt(p1), "p2": _fmt(p2), "more_odds": False}
            market_type = "winner"

        new_json = self._odds_to_json(odds)
        if new_json is None:
            return False
        match.market_type = market_type
        match.odds_json = new_json
        match.last_updated_at = datetime.utcnow()
        return True

    # ─── reads ────────────────────────────────────────────────────────
    def find_by_event_id(self, event_id: str) -> Optional[Match]:
        return self.session.get(Match, event_id)

    def find_by_event_ids(self, event_ids: Iterable[str]) -> List[Match]:
        ids = [str(e) for e in event_ids if e]
        if not ids:
            return []
        return self.session.query(Match).filter(Match.event_id.in_(ids)).all()

    def find_active_by_sport(
        self,
        sport: str,
        mode: Optional[str] = None,
        since: Optional[datetime] = None,
        include_synthetic: bool = False,
    ) -> List[Match]:
        q = self.session.query(Match).filter(Match.sport == sport, Match.is_active.is_(True))
        if not include_synthetic:
            q = q.filter(Match.is_synthetic.is_(False))
        if mode:
            q = q.filter(Match.mode == mode)
        if since is not None:
            q = q.filter(Match.last_updated_at >= since)
        return q.all()

    def count_active(self) -> int:
        return self.session.query(Match).filter(Match.is_active.is_(True)).count()

    @staticmethod
    def _escape_like(s: str) -> str:
        """Escape % and _ so user-supplied terms can't wildcard-DoS the search."""
        return s.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")

    def search(
        self,
        query: Optional[str] = None,
        sport: Optional[str] = None,
        status: Optional[str] = None,
        tournament: Optional[str] = None,
        team: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
        include_synthetic: bool = False,
        include_inactive: bool = False,
    ) -> List[Match]:
        # Default search hides inactive AND synthetic rows (campaign picker
        # behaviour). The hot-override admin opts in with include_inactive=True
        # so operators can pin/suppress a match that has temporarily left the
        # feed (e.g. half-time gap, transient parse failure).
        q = self.session.query(Match)
        if not include_inactive:
            q = q.filter(Match.is_active.is_(True))
        if not include_synthetic:
            # Synthetic (virtual/replay/esports) inventory is hidden from
            # all read paths by default so an admin can't accidentally
            # promote a fake fixture into a public PNG. The campaign
            # picker exposes a toggle that flips this to True.
            q = q.filter(Match.is_synthetic.is_(False))
        if sport:
            q = q.filter(Match.sport == sport)
        if status:
            q = q.filter(Match.status == status)
        if tournament:
            q = q.filter(Match.tournament_name == tournament)
        if team:
            t = team.strip().lower()
            name_like = f"%{self._escape_like(t)}%"
            q = q.filter(
                (Match.home_slug == t)
                | (Match.away_slug == t)
                | (Match.home_name.ilike(name_like, escape="\\"))
                | (Match.away_name.ilike(name_like, escape="\\"))
            )
        if query:
            like = f"%{self._escape_like(query)}%"
            q = q.filter(
                (Match.home_name.ilike(like, escape="\\"))
                | (Match.away_name.ilike(like, escape="\\"))
                | (Match.tournament_name.ilike(like, escape="\\"))
            )
        # `event_id` ASC tail tie-breaker makes the ordering total —
        # without it, ties on `hot_score` / `last_updated_at` (and the
        # latter is rewritten by every parser cycle) caused page 2 of the
        # admin matches list to repeat rows from page 1 when the parser
        # touched rows between the two requests.
        return (
            q.order_by(
                Match.hot_score.desc().nullslast(),
                Match.last_updated_at.desc(),
                Match.event_id.asc(),
            )
            .limit(limit)
            .offset(offset)
            .all()
        )

    def list_tournaments(
        self,
        sport: Optional[str] = None,
        include_synthetic: bool = False,
    ) -> List[str]:
        """Distinct tournament names of active matches, ordered alphabetically.
        Used to populate league-filter dropdowns in the admin picker.

        Default excludes synthetic (virtual/replay/esports) inventory so
        admins don't even see it in the league dropdown. Caller can opt
        in for the "show synthetic" toggle.
        """
        q = (
            self.session.query(Match.tournament_name)
            .filter(Match.is_active.is_(True))
            .filter(Match.tournament_name.is_not(None))
        )
        if not include_synthetic:
            q = q.filter(Match.is_synthetic.is_(False))
        if sport:
            q = q.filter(Match.sport == sport)
        rows = q.distinct().order_by(Match.tournament_name.asc()).all()
        return [r[0] for r in rows if r[0]]
