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
"""

from __future__ import annotations

from datetime import datetime
from typing import List

from sqlalchemy.orm import Session

from ..logging_config import get_logger
from ..models import Match
from ..repositories.match_repo import MatchRepository
from .cube_themes import CubeTheme, match_in_theme
from .hot_engine import HotEngine

logger = get_logger("app.services.cube_resolver")


def resolve_for_theme(
    session: Session,
    theme: CubeTheme,
    limit: int = 1,
) -> List[Match]:
    """Return up to `limit` matches that satisfy `theme`, ranked by the
    sport's hot scorer.

    Behavior:
      1. Run HotEngine over the theme's sport (this gives us the same
         ranking + override semantics as /hot/{sport}.png).
      2. Drop anything whose tournament_slug doesn't match the theme.
      3. If scoring + filter leaves nothing, fall back to raw active rows
         in the theme so the cube still renders the most-recently-updated
         in-scope match.
    """
    limit = max(1, int(limit or 1))
    engine = HotEngine(session, theme.sport)
    # Oversample so the theme filter has something to work with even when
    # only a handful of in-scope matches exist in a sea of other fixtures.
    ranked = engine.resolve(limit * 20)
    filtered = [m for m in ranked if match_in_theme(m.tournament_slug, theme)]
    if filtered:
        return filtered[:limit]

    # Fallback: raw active in the theme, freshest first. Mirrors the admin
    # Browse fallback pattern so a cube doesn't go silent the moment the
    # scorer filters everything out (missing odds, wrong market type, etc).
    match_repo = MatchRepository(session)
    raw = match_repo.find_active_by_sport(theme.sport)
    raw = [m for m in raw if match_in_theme(m.tournament_slug, theme)]
    raw.sort(key=lambda m: m.last_updated_at or datetime.min, reverse=True)
    if not raw:
        logger.info(
            f"cube theme={theme.slug} sport={theme.sport}: no matches "
            f"with tournament_slug starting with any of {theme.league_patterns}"
        )
    return raw[:limit]
