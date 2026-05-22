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
) -> List[Dict[str, Any]]:
    """Return the top-N scored event dicts using the per-sport scorer.

    Falls back to the football scorer for unknown sports to preserve the
    legacy behaviour rather than raising — public render path must not 500
    on a missing scorer.

    When `with_scores=True`, the scorer is called with `debug=True` so each
    returned event carries `_hot_score` (and `_hot_reasons` where supported).
    Default `with_scores=False` keeps the legacy behaviour byte-identical
    for Phase 3's `HotResolver._resolve_auto`.
    """
    if sport == "football":
        from hot_scoring import pick_hot
    elif sport == "tennis":
        from hot_scoring_tennis import pick_hot
    elif sport == "basketball":
        from hot_scoring_basketball import pick_hot
    elif sport == "cybersport":
        from hot_scoring_cybersport import pick_hot
    elif sport in ("fights", "ufc", "mma", "boxing"):
        from hot_scoring_fights import pick_hot
    else:
        logger.warning(f"unknown sport {sport}, using football scorer")
        from hot_scoring import pick_hot

    payload = pick_hot(
        events=events, limit=limit, timezone=timezone, debug=with_scores
    )
    # Pure move of legacy `_run_scoring` return: returns payload["events"]
    # when payload is a dict (even if that value is None), [] otherwise.
    return payload.get("events") if isinstance(payload, dict) else []
