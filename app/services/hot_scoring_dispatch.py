"""
Hot scoring dispatch — sport-to-scorer routing.

This is the *only* place the legacy `hot_scoring*.py` modules are imported.
Both `HotResolver` and (formerly) `public_render._resolve_matches` go through
this helper, so the per-sport scorer choice exists in one place.

The behaviour matches the original inline `_run_scoring` in `public_render.py`
verbatim — same import paths, same defaults, same payload extraction.
"""

from __future__ import annotations

from typing import Any, Dict, List

from ..logging_config import get_logger

logger = get_logger("app.services.hot_scoring_dispatch")


def run_scoring(
    events: List[Dict[str, Any]],
    sport: str,
    limit: int,
    timezone: str,
    with_scores: bool = False,
    single_league: bool = False,
) -> List[Dict[str, Any]]:
    """Return the top-N scored event dicts using the per-sport scorer.

    Falls back to the football scorer for unknown sports to preserve the
    legacy behaviour rather than raising — public render path must not 500
    on a missing scorer.

    When `with_scores=True`, the scorer is called with `debug=True` so each
    returned event carries `_hot_score` (and `_hot_reasons` where supported).
    Default `with_scores=False` keeps the legacy behaviour byte-identical
    for Phase 3's `HotResolver._resolve_auto`.

    When `single_league=True`, the caller has already narrowed candidates to
    one tournament. Every scorer disables its `max_per_tournament` cap (and
    where applicable, `require_min_prematch`) so a league-filtered auto
    campaign asking for `?limit=10` actually returns up to 10 matches from
    that single league instead of capping at 2-3.
    """
    # Per-sport scorer + per-sport kwarg overrides. Combat sports announce
    # fixtures 1–3 months ahead (UFC/boxing), so the football-style 4-day
    # horizon rejects every candidate and leaves /hot/{ufc|mma}.png blank.
    # Tune horizon by sport here, not inside the scorer, so the constant
    # stays semantic ("ufc looks at the next 60 days").
    extra: dict[str, object] = {}
    if sport == "football":
        from scoring.hot_scoring import pick_hot
    elif sport == "tennis":
        from scoring.hot_scoring_tennis import pick_hot
    elif sport == "basketball":
        from scoring.hot_scoring_basketball import pick_hot
    elif sport == "cybersport":
        from scoring.hot_scoring_cybersport import pick_hot
    elif sport in ("fights", "ufc", "mma", "boxing"):
        from scoring.hot_scoring_fights import pick_hot
        extra["horizon_days"] = 60
        # When the caller asks for one canonical combat sport (not the
        # 'fights' union), every candidate is already in that sport, so
        # the cross-sport diversity cap (MAX_PER_SPORT=3) would silently
        # truncate /hot/ufc.png to 3 even with limit=10. Disable it here
        # — the union view ('fights') still gets the cap so ufc/mma/boxing
        # remain balanced there.
        if sport in ("ufc", "mma", "boxing"):
            extra["single_sport"] = True
    else:
        logger.warning(f"unknown sport {sport}, using football scorer")
        from scoring.hot_scoring import pick_hot

    payload = pick_hot(
        events=events,
        limit=limit,
        timezone=timezone,
        debug=with_scores,
        single_league=single_league,
        **extra,
    )
    # Pure move of legacy `_run_scoring` return: returns payload["events"]
    # when payload is a dict (even if that value is None), [] otherwise.
    return payload.get("events") if isinstance(payload, dict) else []
