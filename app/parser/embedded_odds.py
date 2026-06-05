"""Parse match-result odds (1X2 / 2-way winner) embedded as JSON in jugabet's SSR HTML.

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


def _market_outcomes(market: dict) -> Dict[int, float]:
    """Match-result outcomes (``{0: home, 1: draw, 3: away}``) of one market.

    Restricted to the match-result selection ids 0/1/3; totals (4/5),
    handicaps, etc. are ignored. The home outcome may omit ``type`` -> 0.
    """
    outs: Dict[int, float] = {}
    if not isinstance(market, dict):
        return outs
    for o in market.get("outcomes") or []:
        if not isinstance(o, dict):
            continue
        t = o.get("type", 0)
        if t not in (0, 1, 3):
            continue
        try:
            price = float(o.get("price"))
        except (TypeError, ValueError):
            continue
        if price <= _MIN_VALID_ODD:
            continue
        outs[t] = price
    return outs


def extract_result_outcomes(html: str) -> Dict[str, Dict[int, float]]:
    """``{eventId: {0: home, 1: draw, 3: away}}`` for each event's primary
    match-result market — works for every sport.

    football is 1X2 (types 0/1/3); all other sports are 2-way winner/moneyline
    (types 0/3, no draw). For each event we take the primary market carrying
    both home(0) and away(3), preferring a 3-way (with a draw) over a 2-way when
    both exist. Best-effort: returns ``{}`` if the blob is absent/unparseable.
    """
    out: Dict[str, Dict[int, float]] = {}
    try:
        events = find_events_array(html)
    except Exception:
        logger.warning("embedded_odds: events array scan failed", exc_info=True)
        return out
    for ev in events:
        if not isinstance(ev, dict):
            continue
        eid = str(ev.get("id") or ev.get("eventId") or "").strip()
        markets = ev.get("markets")
        if not eid or not isinstance(markets, list):
            continue
        candidates = []
        for m in markets:
            outs = _market_outcomes(m)
            if 0 in outs and 3 in outs:  # needs both home and away
                candidates.append(outs)
        if not candidates:
            continue
        # prefer a 3-way (1X2) market over a 2-way when both are present
        out[eid] = next((c for c in candidates if 1 in c), candidates[0])
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
