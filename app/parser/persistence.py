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

# Virtual/esports inventory streams as "live" with no start_time, so it
# escapes both deactivate_stale (live-exempt) and deactivate_expired
# (start_time-based) and piles up forever. Reap any synthetic row not seen
# in a feed for this long; a virtual match runs only minutes, so this is
# safely above one full parser cycle.
_SYNTHETIC_REAP_MINUTES = 45

# Prematch deactivation is centralized here (NOT per-feed). A single feed's page
# is a partial view; using "missing from this page" as the signal reaped real
# World Cup / league / campaign fixtures (all mode='prematch', owned by sibling
# overlay feeds) on page-1 rotation or a one-cycle overlay stall. Keying off
# last_updated_at means a match kept alive by ANY feed survives. 90m ≈ 9 cycles
# of slack; deactivate_expired (12h after start) still backstops finished games.
_PREMATCH_NOT_SEEN_MINUTES = 90


def _maybe_run_expiry(session, settings) -> int:
    global _last_expiry_at
    now = time.monotonic()
    with _expiry_lock:
        if now - _last_expiry_at < _EXPIRY_INTERVAL_SECONDS:
            return 0
        _last_expiry_at = now
    repo = MatchRepository(session)
    # Heal first: a campaign/hot-pinned match wrongly deactivated earlier (e.g.
    # while its feed was failing) comes back before any reaper runs this cycle.
    n_healed = repo.reactivate_protected()
    if n_healed:
        print(f"[DB] Reactivated {n_healed} campaign/hot-pinned matches", flush=True)
    n_expired = repo.deactivate_expired(settings.match_deactivate_after_hours)
    n_stale = repo.deactivate_not_seen(_PREMATCH_NOT_SEEN_MINUTES, modes=("prematch",))
    n_reaped = repo.deactivate_synthetic_not_seen(_SYNTHETIC_REAP_MINUTES)
    if n_stale:
        print(
            f"[DB] Reaped {n_stale} prematch matches not seen in "
            f"{_PREMATCH_NOT_SEEN_MINUTES}m",
            flush=True,
        )
    if n_reaped:
        print(
            f"[DB] Reaped {n_reaped} stale synthetic matches "
            f"(not seen in {_SYNTHETIC_REAP_MINUTES}m)",
            flush=True,
        )
    return n_expired


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
    db_mode = "prematch" if mode.startswith("prematch") else ("live" if mode.startswith("live") else mode)
    try:
        with db_session() as session:
            repo = MatchRepository(session)
            n_upserted = repo.bulk_upsert(events, sport, db_mode)
            # Deactivation is NOT per-feed. A feed's page is only a partial,
            # rotating view; using "missing from this page" as the signal
            # flickered real matches — most damagingly the firehose
            # (mode='prematch') reaping World Cup / league / campaign fixtures
            # that are also mode='prematch' but owned by sibling overlay feeds.
            # Instead every feed just upserts (refreshing last_updated_at), and
            # the gated reapers in _maybe_run_expiry drop only matches not seen
            # by ANY feed for a generous window. A match kept alive by any feed
            # can never be dropped on rotation or a one-cycle overlay stall.
            n_deactivated = 0
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
        # so this stays O(1) effectively. Wipe the main face cache
        # (`cube:{slug}`), the odds face cache (`cube_odds:{slug}`) AND the
        # animated GIF cache (`cube_gif:{slug}:...`) so emails see fresh odds.
        if sport == "football":
            png_cache.invalidate_prefix("cube:")
            png_cache.invalidate_prefix("cube_odds:")
            png_cache.invalidate_prefix("cube_gif:")
            # Re-render the default email GIF in the background so the cache is
            # warm BEFORE the next inbox open — emails fetch the GIF once with a
            # short timeout and won't wait for a cold render (the "must refresh"
            # bug). Daemon thread so it never blocks the parse cycle.
            _schedule_cube_gif_prewarm()
    except Exception:
        logger.exception("post-parse hot/club cache invalidation failed")


def _schedule_cube_gif_prewarm() -> None:
    """Kick off cube GIF pre-warming off the parse-cycle critical path."""
    try:
        from ..routes.public_cube import prewarm_cube_gifs
        threading.Thread(
            target=prewarm_cube_gifs, name="cube-gif-prewarm", daemon=True
        ).start()
    except Exception:
        logger.exception("failed to schedule cube gif pre-warm")



