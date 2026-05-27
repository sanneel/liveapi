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
    is_overlay = mode not in ("live", "prematch")
    db_mode = "prematch" if mode.startswith("prematch") else ("live" if mode.startswith("live") else mode)
    try:
        with db_session() as session:
            repo = MatchRepository(session)
            n_upserted = repo.bulk_upsert(events, sport, db_mode)
            # Feed-based deactivation policy:
            #   * overlays never deactivate (they're partial views)
            #   * LIVE feeds never deactivate either — Jugabet's
            #     /<sport>/live/1 only shows a paginated subset and which
            #     matches appear rotates constantly. Using "missing from
            #     feed" as a deactivation signal here flickers real live
            #     matches in and out. `deactivate_expired` (12h after
            #     start_time_utc) is the safety net that cleans up
            #     genuinely-finished live matches.
            #   * PREMATCH feeds run deactivate_stale with the 30-min
            #     grace window from MatchRepository; that catches
            #     legitimately-cancelled fixtures while staying robust
            #     against page-1 rotation.
            if is_overlay or db_mode == "live":
                n_deactivated = 0
            else:
                active_ids = [str(e.get("event_id")) for e in events if e.get("event_id")]
                n_deactivated = repo.deactivate_stale(sport, db_mode, active_ids)
            n_expired = _maybe_run_expiry(session, get_settings())

        elapsed_ms = int((time.monotonic() - started) * 1000)
        print(
            f"[DB] Persisted {sport}/{mode}: upserted={n_upserted} "
            f"deactivated={n_deactivated} expired={n_expired} "
            f"duration_ms={elapsed_ms}",
            flush=True
        )
        logger.info(
            f"persisted {sport}/{mode}: upserted={n_upserted} "
            f"deactivated={n_deactivated} expired={n_expired} "
            f"duration_ms={elapsed_ms}"
        )

        # Drop any rendered PNG that could now be stale. Cheap — the caches
        # are bounded and process-local. Without this, admins and email
        # recipients see old matches for up to PUBLIC_CACHE_SECONDS after
        # every parse cycle.
        _invalidate_post_parse(sport, _slugs_in_events(events))

        return n_upserted, n_deactivated

    except Exception as e:
        print(f"[DB] [ERROR] persist_feed_results failed for {sport}/{mode}: {e}", flush=True)
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
        # so this stays O(1) effectively. Wipe both the main face cache
        # (`cube:{slug}`) AND the odds face cache (`cube_odds:{slug}`).
        if sport == "football":
            png_cache.invalidate_prefix("cube:")
            png_cache.invalidate_prefix("cube_odds:")
    except Exception:
        logger.exception("post-parse hot/club cache invalidation failed")



