"""
Parser → DB bridge.

The existing `server.py` parser calls `persist_feed_results(events, sport, mode)`
after each fetch cycle. This is best-effort: if persistence fails, the legacy
in-memory pipeline keeps working unchanged.

Logs every run:
  - n_upserted: matches inserted or updated
  - n_deactivated: matches no longer in the feed (marked inactive)
  - duration_ms
"""

from __future__ import annotations

import threading
import time
from typing import Any, Dict, Iterable, List, Set, Tuple

from ..database import db_session
from ..logging_config import get_logger
from ..repositories.club_repo import ClubRepository
from ..repositories.match_repo import MatchRepository
from ..services import png_cache
from ..config import get_settings

logger = get_logger("app.parser.persistence")

# C1: deactivate_expired used to run on every feed cycle (14x). It is a
# global UPDATE across the whole matches table; serialize it to at most
# once per EXPIRY_INTERVAL_SECONDS regardless of which feed fired it.
_EXPIRY_INTERVAL_SECONDS = 300.0
_expiry_lock = threading.Lock()
_last_expiry_at: float = 0.0


def _maybe_run_expiry(session, settings) -> int:
    global _last_expiry_at
    now = time.monotonic()
    with _expiry_lock:
        if now - _last_expiry_at < _EXPIRY_INTERVAL_SECONDS:
            return 0
        _last_expiry_at = now
    repo = MatchRepository(session)
    return repo.deactivate_expired(settings.match_deactivate_after_hours)


def _slugs_in_events(events: Iterable[Dict[str, Any]]) -> Set[str]:
    slugs: Set[str] = set()
    for e in events:
        comps = e.get("competitors") or {}
        for side in ("home", "away"):
            slug = (comps.get(side) or {}).get("slug")
            if slug:
                slugs.add(str(slug))
    return slugs


def persist_feed_results(
    events: List[Dict[str, Any]],
    sport: str,
    mode: str,
) -> Tuple[int, int]:
    """
    Persist a feed's parsed events to the DB.

    Returns (n_upserted, n_deactivated). Never raises — failures are logged.
    """
    started = time.monotonic()
    n_expired = 0
    # Bug 3: overlay feeds (e.g. football world-cup/Chile filter URLs) re-scrape
    # events already covered by the canonical (sport,prematch|live) feeds. Skip
    # the DB write to avoid 3-way upsert races on the same event_id; the
    # in-memory _state still holds the parsed events for legacy endpoints.
    if mode not in ("live", "prematch"):
        elapsed_ms = int((time.monotonic() - started) * 1000)
        logger.info(
            f"persisted {sport}/{mode}: skipped DB upsert (overlay feed) "
            f"events={len(events)} duration_ms={elapsed_ms}"
        )
        _invalidate_post_parse(sport, _slugs_in_events(events))
        return 0, 0
    try:
        with db_session() as session:
            repo = MatchRepository(session)
            n_upserted = repo.bulk_upsert(events, sport, mode)
            active_ids = [str(e.get("event_id")) for e in events if e.get("event_id")]
            n_deactivated = repo.deactivate_stale(sport, mode, active_ids)
            n_expired = _maybe_run_expiry(session, get_settings())
            n_clubs = _auto_attach_clubs(session, events)

        elapsed_ms = int((time.monotonic() - started) * 1000)
        logger.info(
            f"persisted {sport}/{mode}: upserted={n_upserted} "
            f"deactivated={n_deactivated} expired={n_expired} "
            f"clubs_new={n_clubs} duration_ms={elapsed_ms}"
        )

        # Drop any rendered PNG that could now be stale. Cheap — the caches
        # are bounded and process-local. Without this, admins and email
        # recipients see old matches for up to PUBLIC_CACHE_SECONDS after
        # every parse cycle.
        _invalidate_post_parse(sport, _slugs_in_events(events))

        return n_upserted, n_deactivated

    except Exception:
        logger.exception(f"persist_feed_results failed for {sport}/{mode}")
        return 0, 0


def _invalidate_post_parse(sport: str, touched_slugs: Set[str]) -> None:
    """Clear every cache layer touched by a fresh parse cycle for `sport`.

    Imported lazily so this module doesn't pull in the route layer at
    import time (avoids a circular import via app.routes.public_render).
    """
    try:
        from ..routes.public_render import _cache_invalidate_sport
        _cache_invalidate_sport(sport)
    except Exception:
        logger.exception("post-parse campaign cache invalidation failed")
    try:
        png_cache.invalidate_prefix(f"hot:{sport}")
        # H3: only invalidate club PNG entries whose underlying match data
        # actually changed in this cycle. Wiping the whole `club:` prefix on
        # every feed (14x/cycle) defeated the cache entirely.
        for slug in touched_slugs:
            png_cache.invalidate(f"club:{slug}")
        # Themed cubes are sport-scoped (all current themes filter football).
        # Cheapest correct behavior: wipe the whole cube namespace whenever
        # the cube's sport refreshed. Theme registry is small (<10 entries)
        # so this stays O(1) effectively.
        if sport == "football":
            png_cache.invalidate_prefix("cube:")
    except Exception:
        logger.exception("post-parse hot/club cache invalidation failed")


def _auto_attach_clubs(session, events) -> int:
    """Insert-only club rows for every (home_slug, home_name) and
    (away_slug, away_name) pair observed in this feed cycle.

    First observation wins (`ClubRepository.ensure` is INSERT OR IGNORE).
    Wrapped so any failure here cannot break the parser's primary write
    path — failures are logged and counted as zero.

    NOTE: Auto-creation is disabled as clubs must be created manually.
    """
    return 0

