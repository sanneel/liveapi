"""
Sport → render-function dispatcher.

Re-exports the existing PIL render functions from the legacy render_*.py
files so we don't have to duplicate any drawing code. The legacy files
remain runnable as standalone servers; we just call their drawing function
directly when serving /r/{slug}.png.

This module loads renderers lazily on first use to keep cold-start fast.
"""

from __future__ import annotations

import inspect
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
        from render_servers.render_server import render_hot_png as fn
    elif sport == "basketball":
        from render_servers.basketball_render_server import render_hot_png as fn
    elif sport == "tennis":
        from render_servers.tennis_render_server import render_hot_png as fn
    elif sport == "cybersport":
        from render_servers.cybersport_render_server import render_hot_png as fn
    elif sport in ("fights", "ufc", "mma", "boxing"):
        from render_servers.fights_render_server import render_hot_png as fn
    else:
        logger.warning(f"unknown sport={sport}, falling back to football renderer")
        from render_servers.render_server import render_hot_png as fn

    _CACHE[sport] = fn
    return fn


def render_for_sport(
    sport: str, events: List[Dict[str, Any]], theme: str = "default"
) -> bytes:
    """Render an event list to PNG bytes using the renderer for that sport.

    `theme` selects a color palette (e.g. "default" or "vip"). It is only
    forwarded to renderers whose signature accepts a `theme` argument, so
    sport renderers that don't support theming yet are unaffected.
    """
    fn = _load((sport or "football").lower().strip())
    sanitized = _sanitize_events(events)
    if "theme" in inspect.signature(fn).parameters:
        return fn(sanitized, theme=theme)
    return fn(sanitized)


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
