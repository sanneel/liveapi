"""
Cube match resolver.

A themed cube needs the top-N matches that match a competition theme.
HotEngine already handles per-sport candidate selection, scoring,
suppression, and positional pins — but its `league` filter accepts a
single exact slug. Themes have multiple acceptable patterns, so this
module wraps HotEngine with the theme filter and tightens the candidate
list before scoring.

We also fall back to "raw active rows for the sport, filtered to the
theme, sorted by last_updated_at desc" when scoring drops everything —
the same admin-Browse fallback added in admin_hot.py. A cube endpoint
with zero in-scope matches will return a 1×1 transparent PNG (see
public_cube.py), not crash.

Override layer (Phase D): the cube_override table can pin a specific
match to a specific slot of a specific cube, or suppress it from that
cube entirely. Pins win over the auto-rank for their slot; suppressed
matches are dropped from the candidate pool before scoring.
"""

from __future__ import annotations

from datetime import datetime
import unicodedata
from typing import List, Optional

from sqlalchemy.orm import Session

from ..logging_config import get_logger
from ..models import Match
from ..repositories.cube_override_repo import CubeOverrideRepository
from ..repositories.match_repo import MatchRepository
from .cube_themes import CubeTheme, match_in_theme
from .hot_engine import HotEngine

logger = get_logger("app.services.cube_resolver")


_WORLDCUP_PRIORITY_COUNTRY_ALIASES = (
    ("chile",),
    ("germany", "alemania"),
    ("brazil", "brasil"),
    ("france", "francia"),
    ("portugal",),
    ("argentina",),
    ("spain", "espana"),
)


def _has_required_teams(match: Match, required: tuple) -> bool:
    """All required strings must appear somewhere in home+away name combined."""
    names = (
        (match.home_name or "").lower()
        + " "
        + (match.away_name or "").lower()
    )
    return all(t.lower() in names for t in required)


def _is_live(match: Match) -> bool:
    return (match.status or "").strip().lower() == "live" or (match.mode or "").strip().lower() == "live"


def _sort_live_first(matches: List[Match]) -> List[Match]:
    """Stable sort that promotes live matches to the front while keeping the
    underlying hot-score ordering intact within each bucket."""
    return sorted(matches, key=lambda m: 0 if _is_live(m) else 1)


def _norm_text(value: str) -> str:
    value = unicodedata.normalize("NFKD", value or "")
    value = "".join(ch for ch in value if not unicodedata.combining(ch))
    return value.lower()


def _worldcup_auto_score(match: Match, now: datetime) -> tuple:
    """World Cup automation: closest fixtures and priority countries rise,
    but neither signal is strong enough to erase the existing hot score."""
    score = float(match.hot_score or 0.0)

    if _is_live(match):
        score += 120.0

    if match.start_time_utc:
        hours = (match.start_time_utc - now).total_seconds() / 3600.0
        if hours >= 0:
            score += max(0.0, 48.0 - min(hours, 96.0) * 0.5)
        else:
            score += max(0.0, 12.0 + hours)

    names = _norm_text(f"{match.home_name} {match.away_name}")
    country_hits = sum(
        1
        for aliases in _WORLDCUP_PRIORITY_COUNTRY_ALIASES
        if any(alias in names for alias in aliases)
    )
    score += country_hits * 28.0

    start = match.start_time_utc or datetime.max
    return (-score, start, match.event_id)


def _sort_for_theme(matches: List[Match], theme: CubeTheme) -> List[Match]:
    if theme.slug == "worldcup":
        now = datetime.utcnow()
        return sorted(matches, key=lambda m: _worldcup_auto_score(m, now))
    if theme.prefer_live:
        return _sort_live_first(matches)
    return matches


def resolve_for_theme(
    session: Session,
    theme: CubeTheme,
    limit: int = 1,
) -> List[Optional[Match]]:
    """Return a POSITIONAL list of up to `limit` slots that satisfy `theme`,
    ranked by the sport's hot scorer, with cube override pins / suppressions /
    blocked (blank) slots applied. Entry `i` is the Match for slot `i`, or
    `None` when that slot is intentionally blank (operator-blocked) or no match
    is available. Callers index by slot and treat `None` as an empty slot.

    Behavior:
      1. Load cube_override rows for this theme (pins + suppressions).
      2. Run HotEngine over the theme's sport.
      3. Drop anything whose tournament_slug doesn't match the theme.
      4. Drop anything explicitly suppressed in the cube_override table.
      5. If theme.prefer_live=True, stable-sort the survivor list so live
         matches come first (their hot-score ordering is preserved within
         the live bucket and within the prematch bucket).
      6. Fill the output slots: active pinned events take their slot first;
         the auto-ranked list fills the rest. If a pinned event has finished
         and is no longer active, the pin is cleared and the slot returns to
         the automated leaderboard.
      7. Fall back to raw active rows in the theme if everything came back
         empty so the cube doesn't go silent.
    """
    limit = max(1, int(limit or 1))
    override_repo = CubeOverrideRepository(session)
    match_repo = MatchRepository(session)

    pinned = override_repo.all_pinned(theme.slug)        # {slot: event_id}
    suppressed = override_repo.all_suppressed(theme.slug)  # {event_id, ...}
    blocked = override_repo.blocked_slots(theme.slug)     # {slot, ...} kept blank

    engine = HotEngine(session, theme.sport)
    # Oversample so the theme filter has something to work with even when
    # only a handful of in-scope matches exist in a sea of other fixtures.
    ranked = engine.resolve(limit * 20)
    filtered = [m for m in ranked if match_in_theme(m.tournament_slug, theme)]
    if theme.required_teams:
        filtered = [m for m in filtered if _has_required_teams(m, theme.required_teams)]
    # Apply cube-level suppression (independent of HotEngine's own suppress
    # which operates at the sport level — operators may want a match hidden
    # from the cube but still visible on /hot/football.png).
    if suppressed:
        filtered = [m for m in filtered if m.event_id not in suppressed]
    filtered = _sort_for_theme(filtered, theme)

    # Assemble the final slot list: pinned slots first, then fill gaps
    # from HotEngine's pre-scored shortlist, then from the raw active
    # in-theme pool if that still wasn't enough.
    auto_iter = iter(filtered)
    slots: List[Match | None] = [None for _ in range(limit)]
    used_ids: set = set()
    for slot in range(limit):
        if slot in blocked:
            # Operator reserved this slot as blank — never auto-fill it.
            continue
        if slot in pinned:
            eid = pinned[slot]
            if eid in suppressed:
                # Defensive: pinned AND suppressed is contradictory. Treat
                # suppress as the winner (operator's most recent intent
                # was almost certainly suppress).
                continue
            m = match_repo.find_by_event_id(eid)
            if m is not None and m.is_active:
                slots[slot] = m
                used_ids.add(m.event_id)
                continue
            # Pin points at a match that's currently inactive or gone. Rendering
            # is READ-ONLY — we never mutate override rows here (this runs on the
            # request path and in background GIF pre-warm threads; a write here
            # races the parser's writes and risks SQLite "database is locked").
            # We simply don't render the pin this cycle and let the slot fall
            # through to auto-rank. Genuinely-finished pins are cleared by
            # `release_finished_pins()` in the parser's post-cycle hook, which
            # owns DB writes. A flaky feed that briefly deactivates an *upcoming*
            # fixture therefore can't cost the operator their pin.
        # No pin for this slot — pull the next auto-ranked candidate that
        # we haven't already used and isn't suppressed.
        for m in auto_iter:
            if m.event_id in used_ids:
                continue
            if m.event_id in suppressed:
                continue
            slots[slot] = m
            used_ids.add(m.event_id)
            break

    # Fallback expansion: if HotEngine + theme filter didn't yield enough
    # candidates to fill every slot, pull from the FULL active-football
    # pool. Without this, themes with a small candidate count (e.g. the
    # WC group-stage when only ~5 fixtures are scheduled today) leave
    # slots 2/3 permanently empty after slot 1 is pinned.
    if any(m is None for i, m in enumerate(slots) if i not in blocked):
        extras = match_repo.find_active_by_sport(theme.sport)
        extras = [m for m in extras if match_in_theme(m.tournament_slug, theme)]
        if theme.required_teams:
            extras = [m for m in extras if _has_required_teams(m, theme.required_teams)]
        extras = [m for m in extras if m.event_id not in used_ids]
        extras = [m for m in extras if m.event_id not in suppressed]
        extras = _sort_for_theme(extras, theme)
        if theme.slug != "worldcup" and not theme.prefer_live:
            extras.sort(key=lambda m: m.last_updated_at or datetime.min, reverse=True)
        extra_iter = iter(extras)
        for i, current in enumerate(slots):
            if current is not None or i in blocked:
                continue
            for m in extra_iter:
                if m.event_id in used_ids:
                    continue
                slots[i] = m
                used_ids.add(m.event_id)
                break

    # Return the POSITIONAL slot list (None = blank/blocked/unavailable) so
    # callers that index by slot (cube faces, web odds, admin) see a reserved
    # blank in its place instead of the list silently compacting. Only when the
    # operator has done NOTHING and auto produced nothing do we drop to the raw
    # fallback below (which has no internal gaps anyway).
    if blocked or any(m is not None for m in slots):
        return slots

    # Fallback: raw active in the theme, freshest first. Mirrors the admin
    # Browse fallback pattern so a cube doesn't go silent the moment the
    # scorer filters everything out (missing odds, wrong market type, etc).
    raw = match_repo.find_active_by_sport(theme.sport)
    raw = [m for m in raw if match_in_theme(m.tournament_slug, theme)]
    if theme.required_teams:
        raw = [m for m in raw if _has_required_teams(m, theme.required_teams)]
    if suppressed:
        raw = [m for m in raw if m.event_id not in suppressed]
    raw = _sort_for_theme(raw, theme)
    if theme.slug != "worldcup" and not theme.prefer_live:
        raw.sort(key=lambda m: m.last_updated_at or datetime.min, reverse=True)
    if not raw:
        logger.info(
            "cube theme=%s sport=%s: no matches with tournament_slug "
            "starting with any of %s",
            theme.slug, theme.sport, theme.league_patterns,
        )
    return raw[:limit]


def candidates_for_theme(
    session: Session,
    theme: CubeTheme,
    limit: int = 50,
) -> List[Match]:
    """Return EVERY active in-theme match (independent of overrides), for the
    admin candidate list. Mirrors admin_hot.py's "leaderboard candidates"
    semantic — operators need to see suppressed AND unsuppressed matches
    so they can toggle either way.

    Sorted: live first (if prefer_live), then by hot_score desc, then by
    last_updated_at desc, capped at `limit`.
    """
    match_repo = MatchRepository(session)
    raw = match_repo.find_active_by_sport(theme.sport)
    raw = [m for m in raw if match_in_theme(m.tournament_slug, theme)]
    if theme.required_teams:
        raw = [m for m in raw if _has_required_teams(m, theme.required_teams)]
    if theme.slug == "worldcup":
        raw = _sort_for_theme(raw, theme)
    else:
        raw.sort(
            key=lambda m: (
                -(m.hot_score if m.hot_score is not None else -1e9),
                -(m.last_updated_at.timestamp() if m.last_updated_at else 0),
            )
        )
        if theme.prefer_live:
            raw = _sort_live_first(raw)
    return raw[: max(1, int(limit or 50))]
