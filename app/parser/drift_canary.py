"""Parser drift canary — proactive detection of jugabet format changes.

The fixture tests prove our extractor still parses our *saved sample*. They
cannot tell us when jugabet changes their live embedded-JSON shape — today we
only learn that when odds quietly go stale and campaigns render blank.

This canary closes that gap. It GETs one known listing URL and asks: does the
live page's embedded blob still yield at least one event with valid
match-result odds? The outcome is classified so a real format change is
distinguishable from a transient network blip or a quiet off-hours page:

  * "ok"          — >=1 event with valid odds extracted. Healthy.
  * "drifted"     — the page still advertises events ('"eventId"' and '"price"'
                    are in the HTML) but the extractor got 0. jugabet most
                    likely changed their embedded JSON shape. THIS is the alert.
  * "unreachable" — the GET itself failed (network / geo-block / site down).
  * "no_events"   — page fetched but carries no event markers at all (off-hours
                    or wrong URL). Inconclusive; never treated as drift.
  * "unknown"     — the canary has not run yet this process.

The result is cached in-process. `/health` reads the cache only (it never
fetches inline, so the health endpoint stays fast), and the campaign monitor
runs the check on its interval and alerts on ok<->drifted transitions.
"""

from __future__ import annotations

import threading
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from ..config import get_settings
from ..logging_config import get_logger
from .embedded_odds import _get_html, parse_events

logger = get_logger("app.parser.canary")

_lock = threading.Lock()
_last: Optional[Dict[str, Any]] = None


def _classify(html: Optional[str]) -> tuple[str, int]:
    """Map raw page HTML to (status, events_with_valid_odds)."""
    if html is None:
        return "unreachable", 0
    # parse_events only keeps events that carry both home(0) and away(3), so
    # every returned entry is already a valid match-result extraction.
    odds, _tids = parse_events(html)
    n = len(odds)
    if n > 0:
        return "ok", n
    has_event_markers = '"eventId"' in html and '"price"' in html
    if has_event_markers:
        # The data is on the page but our extractor produced nothing -> drift.
        return "drifted", 0
    return "no_events", 0


def run_canary_once() -> Dict[str, Any]:
    """Fetch the configured canary URL, classify, cache, and return the result.

    Best-effort: any failure is captured as a status, never raised, so the
    caller's loop can't die on it.
    """
    settings = get_settings()
    url = settings.parser_canary_url
    try:
        html = _get_html(url)
    except Exception:  # noqa: BLE001 — canary must never raise into the loop
        logger.warning("parser canary: fetch raised for %s", url, exc_info=True)
        html = None

    status, events = _classify(html)
    result: Dict[str, Any] = {
        "status": status,
        "events_with_odds": events,
        "url": url,
        "checked_utc": datetime.now(timezone.utc).isoformat(),
    }
    with _lock:
        global _last
        _last = result

    if status == "drifted":
        logger.warning(
            "parser canary: DRIFTED — %s advertises events but the extractor "
            "returned 0. jugabet may have changed their embedded JSON shape.",
            url,
        )
    elif status == "unreachable":
        logger.warning("parser canary: unreachable — %s", url)
    return result


def get_last_result() -> Dict[str, Any]:
    """Return the cached canary result (never fetches). Safe for /health."""
    with _lock:
        if _last is None:
            return {
                "status": "unknown",
                "events_with_odds": None,
                "url": None,
                "checked_utc": None,
            }
        return dict(_last)
