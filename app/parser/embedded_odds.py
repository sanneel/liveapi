"""Parse 1X2 result-market odds embedded as JSON in jugabet's SSR HTML.

Jugabet (GR8 Tech ULTIM8 / Angular) ships the full events payload — teams,
kickoff and result-market odds — as an inline JSON array in the server-rendered
HTML, then hydrates client-side. The Centrifugo WebSocket only streams *live*
price updates, so prematch odds never arrive over it (World Cup / campaign
matches measured ~6% coverage). A plain HTTP GET of the same feed URL yields
~100% of the result-market odds with no browser and no WS race.

Each outcome object in the blob:
    {"marketKey":[1,2,0,"null","null"], "eventId":"15069103", "type":3,
     "price":8.55, "originalPrice":8.43, ...}
type 0=home, 1=draw, 3=away; marketKey[1:3]==[2,0] marks the 1X2 result market.
We read `price` (the value jugabet displays, including its "Mega cuota" boost).
"""

from __future__ import annotations

import html as _html
import json
import re
import urllib.request
from typing import Dict, List, Optional

from ..logging_config import get_logger

logger = get_logger(__name__)

_ARRAY_OF_OBJECTS_RE = re.compile(r'\[\{"')
_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)
_GET_TIMEOUT_S = 15
_MIN_VALID_ODD = 1.0


def _match_bracket(s: str, i: int) -> Optional[str]:
    """Return s[i:j+1] where j closes the bracket opened at i (JSON-string aware)."""
    open_ch = s[i]
    close_ch = "]" if open_ch == "[" else "}"
    depth = 0
    in_str = False
    esc = False
    for j in range(i, len(s)):
        c = s[j]
        if in_str:
            if esc:
                esc = False
            elif c == "\\":
                esc = True
            elif c == '"':
                in_str = False
        elif c == '"':
            in_str = True
        elif c == open_ch:
            depth += 1
        elif c == close_ch:
            depth -= 1
            if depth == 0:
                return s[i : j + 1]
    return None


def find_events_array(html: str) -> List[dict]:
    """Return the embedded events array: the ``[{...}]`` fragment with the most
    prices. Nested arrays are skipped (we advance past a matched fragment), so
    this scans only top-level arrays and stays well under a few ms even on the
    ~260KB pages jugabet serves."""
    best_count = -1
    best: List[dict] = []
    pos = 0
    for m in _ARRAY_OF_OBJECTS_RE.finditer(html):
        start = m.start()
        if start < pos:
            continue  # inside an already-matched fragment
        frag = _match_bracket(html, start)
        if not frag:
            continue
        pos = start + len(frag)  # skip nested arrays within this one
        if '"eventId"' not in frag or '"price"' not in frag:
            continue
        data = None
        for cand in (frag, _html.unescape(frag)):
            try:
                data = json.loads(cand)
                break
            except Exception:
                continue
        if not isinstance(data, list):
            continue
        n = frag.count('"price"')
        if n > best_count:
            best_count = n
            best = data
    return best


def _iter_outcomes(obj):
    """Yield every dict carrying both eventId and price (i.e. an outcome)."""
    if isinstance(obj, dict):
        if "eventId" in obj and "price" in obj:
            yield obj
        for v in obj.values():
            yield from _iter_outcomes(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _iter_outcomes(v)


def _is_result_outcome(o: dict) -> bool:
    """True for outcomes of the 1X2 result market (marketKey[1:3]==[2,0])."""
    mk = o.get("marketKey")
    if isinstance(mk, list) and len(mk) >= 3 and mk[1] == 2 and mk[2] == 0:
        return True
    return "_2_0_-_1_-_-" in str(o.get("marketItemId") or "")


def extract_result_outcomes(html: str) -> Dict[str, Dict[int, float]]:
    """``{eventId: {0: home, 1: draw, 3: away}}`` for the 1X2 result market.

    Best-effort: returns ``{}`` if the blob is absent or unparseable so callers
    can treat it as optional enrichment over the existing WS path.
    """
    out: Dict[str, Dict[int, float]] = {}
    try:
        events = find_events_array(html)
    except Exception:
        logger.warning("embedded_odds: events array scan failed", exc_info=True)
        return out
    for o in _iter_outcomes(events):
        if not _is_result_outcome(o):
            continue
        eid = str(o.get("eventId") or "").strip()
        if not eid:
            continue
        t = o.get("type", 0)  # the home outcome omits `type` -> 0
        if t not in (0, 1, 3):
            continue
        try:
            price = float(o.get("price"))
        except (TypeError, ValueError):
            continue
        if price <= _MIN_VALID_ODD:
            continue
        out.setdefault(eid, {})[t] = price
    return out


def fetch_embedded_odds(url: str) -> Dict[str, Dict[int, float]]:
    """HTTP GET ``url`` and extract result-market odds from its SSR HTML.

    Best-effort: returns ``{}`` on any network/parse error so the caller can
    treat it as optional enrichment over the existing WS path.
    """
    try:
        req = urllib.request.Request(
            url, headers={"User-Agent": _UA, "Accept-Language": "es-CL"}
        )
        with urllib.request.urlopen(req, timeout=_GET_TIMEOUT_S) as r:
            html = r.read().decode("utf-8", "ignore")
    except Exception:
        logger.warning("embedded_odds: GET failed for %s", url, exc_info=True)
        return {}
    return extract_result_outcomes(html)
