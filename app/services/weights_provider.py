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

Seeding vs. scoring are two different concerns:
  * Every sport in `_SEED_SOURCES` is seeded so the admin can *see and edit*
    its weights.
  * Only sports in `_MANAGED_SPORTS` have a live scorer that reads back from
    here, i.e. where edits actually change scoring. The UI flags the rest as
    display-only.
"""

from __future__ import annotations

import importlib
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Dict, List, Optional, Tuple

from sqlalchemy.exc import IntegrityError

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


# ── Static seed sources ──────────────────────────────────────────────────
# Each static `weights_<sport>.py` exposes its patterns in a slightly
# different shape. A `_SeedSpec` says how to pull (pattern, points) rows of
# one kind from a single module attribute, so the same seeding code handles
# all of them.

_KIND_LEAGUE = "league"
_KIND_TEAM = "team"
_KIND_WORD = "word"


@dataclass(frozen=True)
class _SeedSpec:
    attr: str                          # module attribute to read
    kind: str                          # league | team | word
    shape: str                         # "pairs" | "flat" | "mapping"
    points_attr: Optional[str] = None  # for "flat": module const holding the bonus
    default_points: int = 0            # used if points_attr is missing


# Football / basketball / tennis all expose (pattern, points) tuple lists.
_PAIR_SPECS: Tuple[_SeedSpec, ...] = (
    _SeedSpec("LEAGUE_BOOST_PATTERNS", _KIND_LEAGUE, "pairs"),
    _SeedSpec("TEAM_BOOST_PATTERNS", _KIND_TEAM, "pairs"),
)

# Cybersport stores plain string lists with one shared bonus constant per list.
_CYBER_SPECS: Tuple[_SeedSpec, ...] = (
    _SeedSpec("TIER1_TOURNAMENT_PATTERNS", _KIND_LEAGUE, "flat", "TOURNAMENT_TIER1_BONUS"),
    _SeedSpec("TIER2_TOURNAMENT_PATTERNS", _KIND_LEAGUE, "flat", "TOURNAMENT_TIER2_BONUS"),
    _SeedSpec("TIER3_TOURNAMENT_PATTERNS", _KIND_LEAGUE, "flat", "TOURNAMENT_TIER3_PENALTY"),
    _SeedSpec("POPULAR_TEAMS", _KIND_TEAM, "flat", "POPULAR_TEAM_BONUS"),
    _SeedSpec("LATAM_TEAMS", _KIND_TEAM, "flat", "LATAM_TEAM_BONUS"),
    _SeedSpec("GAME_WEIGHTS", _KIND_WORD, "mapping"),
)

# Fight sports (ufc / mma / boxing) all read the one combat weights file.
_FIGHT_SPECS: Tuple[_SeedSpec, ...] = (
    _SeedSpec("TIER1_TOURNAMENT_PATTERNS", _KIND_LEAGUE, "flat", "TOURNAMENT_TIER1_BONUS"),
    _SeedSpec("TIER2_TOURNAMENT_PATTERNS", _KIND_LEAGUE, "flat", "TOURNAMENT_TIER2_BONUS"),
    _SeedSpec("FEATURED_TOURNAMENT_PATTERNS", _KIND_LEAGUE, "flat", "FEATURED_TOURNAMENT_BONUS"),
    _SeedSpec("CHILE_FIGHTERS", _KIND_TEAM, "flat", "CHILE_FIGHTER_BONUS"),
    _SeedSpec("LATAM_FIGHTERS", _KIND_TEAM, "flat", "LATAM_FIGHTER_BONUS"),
    _SeedSpec("GLOBAL_FIGHT_STARS", _KIND_TEAM, "flat", "GLOBAL_FIGHT_STAR_BONUS"),
    _SeedSpec("SPORT_BASE_WEIGHTS", _KIND_WORD, "mapping"),
)

# sport -> (static module name, seed specs). Every sport here is seedable for
# display/editing on the admin page.
_SEED_SOURCES: Dict[str, Tuple[str, Tuple[_SeedSpec, ...]]] = {
    "football": ("scoring.weights_chile_first", _PAIR_SPECS),
    "basketball": ("scoring.weights_basketball_chile_first", _PAIR_SPECS),
    "tennis": ("scoring.weights_tennis_chile_first", _PAIR_SPECS),
    "cybersport": ("scoring.weights_cybersport_chile", _CYBER_SPECS),
    "ufc": ("scoring.weights_fights_chile_first", _FIGHT_SPECS),
    "mma": ("scoring.weights_fights_chile_first", _FIGHT_SPECS),
    "boxing": ("scoring.weights_fights_chile_first", _FIGHT_SPECS),
}

# Sports whose live scorer actually reads its weights back from this provider,
# i.e. where an admin edit changes scoring within one cache TTL. Sports that
# are seeded but NOT here are editable for visibility only — their scorer still
# uses the static file — and the UI surfaces that distinction.
#
# Every exposed sport now reads its weights back through get_weights(), so admin
# edits change scoring within one cache TTL. Cybersport and the fight sports keep
# a few non-editable structural bonuses in code (combo/crossover, UFC promotion),
# but every tournament/team/fighter/game weight is table-driven.
_MANAGED_SPORTS = frozenset(
    {"football", "basketball", "tennis", "cybersport", "ufc", "mma", "boxing"}
)

# Mapping keys that are catch-all sentinels in the static files, not real
# patterns worth showing as editable rows.
_SKIP_MAPPING_KEYS = frozenset({"other"})

_cache: Dict[str, _CacheEntry] = {}
_lock = threading.Lock()


def _coerce_int(value) -> Optional[int]:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _rows_from_spec(mod, spec: _SeedSpec) -> List[dict]:
    """Extract seed-row dicts for one spec from an imported static module."""
    raw = getattr(mod, spec.attr, None)
    if raw is None:
        return []
    rows: List[dict] = []

    if spec.shape == "pairs":
        for item in raw:
            try:
                pattern, points = item
            except (TypeError, ValueError):
                continue
            pattern = str(pattern).strip()
            pts = _coerce_int(points)
            if pattern and pts is not None:
                rows.append({"kind": spec.kind, "pattern": pattern, "points": pts})

    elif spec.shape == "flat":
        pts = spec.default_points
        if spec.points_attr:
            resolved = _coerce_int(getattr(mod, spec.points_attr, None))
            if resolved is not None:
                pts = resolved
        for item in raw:
            pattern = str(item).strip()
            if pattern:
                rows.append({"kind": spec.kind, "pattern": pattern, "points": pts})

    elif spec.shape == "mapping":
        if isinstance(raw, dict):
            for key, points in raw.items():
                pattern = str(key).strip()
                pts = _coerce_int(points)
                if (
                    pattern
                    and pts is not None
                    and pattern.lower() not in _SKIP_MAPPING_KEYS
                ):
                    rows.append({"kind": spec.kind, "pattern": pattern, "points": pts})

    return rows


def seed_rows_from_static(sport: str) -> List[dict]:
    """Build seed rows (dicts) from the static weights module for `sport`.

    Returns [] when the sport has no known static source — the scorer keeps
    using its own static import in that case. De-duplicates on (kind, pattern)
    so repeated entries in a static file (or overlap between specs) don't trip
    the unique constraint.
    """
    src = _SEED_SOURCES.get(sport)
    if not src:
        return []
    module_name, specs = src
    try:
        mod = importlib.import_module(module_name)
    except Exception:
        logger.exception(f"weights_provider: cannot import seed module {module_name}")
        return []

    rows: List[dict] = []
    seen: set = set()
    for spec in specs:
        for row in _rows_from_spec(mod, spec):
            key = (row["kind"], row["pattern"].lower())
            if key in seen:
                continue
            seen.add(key)
            rows.append(row)
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
    try:
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
    except IntegrityError:
        # Another thread/worker seeded this sport at the same moment (first
        # access after deploy races the first scoring cycle). The rows exist
        # now, so this is a harmless no-op rather than a 500.
        logger.info(f"weights_provider: {sport} seeded concurrently — skipping")
        return 0


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
    """True when this sport's live scorer reads its weights from the DB
    provider, i.e. admin edits actually change scoring. Seedable-but-not-
    managed sports return False so the UI can flag edits as display-only."""
    return sport in _MANAGED_SPORTS
