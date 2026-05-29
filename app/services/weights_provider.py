"""
Runtime scoring-weights provider.

The per-sport football/tennis/... scorers used to import their weight lists
directly from the static `weights_<sport>.py` modules at import time. This
module makes those weights DB-backed and editable from the admin "Weights"
page, while staying cheap enough to call from the hot scoring path.

Flow:
  1. First time a sport is requested and its `hot_weight` table slice is empty,
     seed it once from the static module (so the admin page shows the existing
     weights immediately).
  2. Return an in-memory snapshot of the *active* weights (enabled + inside
     their optional starts_at/ends_at window), cached for a few seconds.
  3. Admin mutations call `invalidate(sport)` so edits show up on the next
     scoring cycle without a restart.

The snapshot is intentionally a plain dataclass of `(pattern, points)` tuples
so the scorers can keep using their existing `sum_matching_weights` /
`first_matching_weight` helpers unchanged.
"""

from __future__ import annotations

import importlib
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional, Tuple

from ..database import db_session
from ..logging_config import get_logger
from ..repositories.hot_weight_repo import HotWeightRepository

logger = get_logger("app.services.weights_provider")

# How long a loaded snapshot is reused before re-reading the DB. Short enough
# that an admin edit is visible "within a few seconds"; long enough that we are
# not hitting SQLite once per scored match.
_CACHE_TTL_SEC = 15.0


@dataclass(frozen=True)
class WeightSet:
    """Active weights for one sport at load time."""

    league: Tuple[Tuple[str, int], ...] = ()
    team: Tuple[Tuple[str, int], ...] = ()
    word: Tuple[Tuple[str, int], ...] = ()


@dataclass
class _CacheEntry:
    loaded_at: float
    snapshot: WeightSet


# sport -> static seed source: (module_name, league_attr, team_attr)
# Only sports listed here can be auto-seeded. Football is wired now; the rest
# fall back to their own static imports inside the scorer until added.
_SEED_SOURCES: Dict[str, Tuple[str, Optional[str], Optional[str]]] = {
    "football": ("weights_chile_first", "LEAGUE_BOOST_PATTERNS", "TEAM_BOOST_PATTERNS"),
}

_cache: Dict[str, _CacheEntry] = {}
_lock = threading.Lock()


def seed_rows_from_static(sport: str) -> List[dict]:
    """Build seed rows (dicts) from the static weights module for `sport`.

    Returns [] when the sport has no known static source — the scorer keeps
    using its own static import in that case.
    """
    src = _SEED_SOURCES.get(sport)
    if not src:
        return []
    module_name, league_attr, team_attr = src
    try:
        mod = importlib.import_module(module_name)
    except Exception:
        logger.exception(f"weights_provider: cannot import seed module {module_name}")
        return []

    rows: List[dict] = []
    if league_attr:
        for pat, pts in getattr(mod, league_attr, []) or []:
            rows.append({"kind": "league", "pattern": str(pat), "points": int(pts)})
    if team_attr:
        for pat, pts in getattr(mod, team_attr, []) or []:
            rows.append({"kind": "team", "pattern": str(pat), "points": int(pts)})
    return rows


def ensure_seeded(sport: str) -> int:
    """Seed the sport's weights from static once, if its slice is empty.

    Idempotent — does nothing if the sport already has rows or has no static
    seed source. Returns the number of rows inserted. Safe to call from the
    admin list endpoint so simply opening the Weights page populates the
    table the first time, without waiting for a scoring cycle.
    """
    if sport not in _SEED_SOURCES:
        return 0
    with db_session() as session:
        repo = HotWeightRepository(session)
        if repo.count_for_sport(sport) > 0:
            return 0
        rows = seed_rows_from_static(sport)
        if not rows:
            return 0
        inserted = repo.bulk_seed(sport, rows, by="seed:static")
        logger.info(f"weights_provider: seeded {inserted} weights for {sport}")
        return inserted


def _ensure_seeded(sport: str) -> None:
    """Backwards-compatible internal alias used by the scoring load path."""
    ensure_seeded(sport)


def _is_active(row, now: datetime) -> bool:
    if not row.enabled:
        return False
    if row.starts_at is not None and now < row.starts_at:
        return False
    if row.ends_at is not None and now > row.ends_at:
        return False
    return True


def _load_snapshot(sport: str) -> WeightSet:
    _ensure_seeded(sport)
    now = datetime.utcnow()
    league: List[Tuple[str, int]] = []
    team: List[Tuple[str, int]] = []
    word: List[Tuple[str, int]] = []
    with db_session() as session:
        rows = HotWeightRepository(session).list_for_sport(sport, enabled_only=True)
        for r in rows:
            if not _is_active(r, now):
                continue
            item = (r.pattern, int(r.points))
            if r.kind == "league":
                league.append(item)
            elif r.kind == "team":
                team.append(item)
            elif r.kind == "word":
                word.append(item)
    # League matching is order-sensitive in the scorer (more specific first);
    # preserve the repo's points-desc ordering which puts specific high-value
    # tiers ahead of broad low-value ones.
    return WeightSet(league=tuple(league), team=tuple(team), word=tuple(word))


def get_weights(sport: str) -> WeightSet:
    """Return the active WeightSet for a sport (cached, ~15s TTL)."""
    now = time.monotonic()
    entry = _cache.get(sport)
    if entry is not None and (now - entry.loaded_at) < _CACHE_TTL_SEC:
        return entry.snapshot
    with _lock:
        # Re-check after acquiring the lock to avoid a thundering reload.
        entry = _cache.get(sport)
        if entry is not None and (time.monotonic() - entry.loaded_at) < _CACHE_TTL_SEC:
            return entry.snapshot
        snapshot = _load_snapshot(sport)
        _cache[sport] = _CacheEntry(loaded_at=time.monotonic(), snapshot=snapshot)
        return snapshot


def invalidate(sport: Optional[str] = None) -> None:
    """Drop cached weights so the next scoring cycle re-reads the DB."""
    with _lock:
        if sport is None:
            _cache.clear()
        else:
            _cache.pop(sport, None)


def has_db_weights(sport: str) -> bool:
    """True when this sport is managed by the DB provider (seedable)."""
    return sport in _SEED_SOURCES
