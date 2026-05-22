"""
Sport → render-function dispatcher.

Re-exports the existing PIL render functions from the legacy render_*.py
files so we don't have to duplicate any drawing code. The legacy files
remain runnable as standalone servers; we just call their drawing function
directly when serving /r/{slug}.png.

This module loads renderers lazily on first use to keep cold-start fast.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Callable, Dict, List
from urllib.parse import urlsplit

from ..config import get_settings
from ..logging_config import get_logger

logger = get_logger("app.render")

# sport (lowercase) → callable(events: list) → bytes
_CACHE: Dict[str, Callable[[List[Dict[str, Any]]], bytes]] = {}


def _load(sport: str) -> Callable[[List[Dict[str, Any]]], bytes]:
    if sport in _CACHE:
        return _CACHE[sport]

    # Import the legacy renderers on first use.
    if sport == "football":
        from render_server import render_hot_png as fn
    elif sport == "basketball":
        from basketball_render_server import render_hot_png as fn
    elif sport == "tennis":
        from tennis_render_server import render_hot_png as fn
    elif sport == "cybersport":
        from cybersport_render_server import render_hot_png as fn
    elif sport in ("fights", "ufc", "mma", "boxing"):
        from fights_render_server import render_hot_png as fn
    else:
        logger.warning(f"unknown sport={sport}, falling back to football renderer")
        from render_server import render_hot_png as fn

    _CACHE[sport] = fn
    return fn


def render_for_sport(sport: str, events: List[Dict[str, Any]]) -> bytes:
    """Render an event list to PNG bytes using the renderer for that sport."""
    fn = _load((sport or "football").lower().strip())
    return fn(_sanitize_events(events))


def _safe_logo_url(url: Any) -> str | None:
    if not isinstance(url, str):
        return None
    url = url.strip()
    if not url:
        return None
    parsed = urlsplit(url)
    if parsed.scheme != "https" or not parsed.netloc:
        return None
    host = parsed.hostname.lower() if parsed.hostname else ""
    if host not in get_settings().allowed_logo_host_list():
        return None
    return url


def _sanitize_events(events: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    cleaned = deepcopy(events)
    for event in cleaned:
        competitors = event.get("competitors") if isinstance(event, dict) else None
        if not isinstance(competitors, dict):
            continue
        for side in ("home", "away"):
            team = competitors.get(side)
            if isinstance(team, dict):
                team["logo"] = _safe_logo_url(team.get("logo"))
    return cleaned
