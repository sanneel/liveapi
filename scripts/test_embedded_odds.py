"""Standalone test for app/parser/embedded_odds.py extraction logic.

Run locally or on the VPS:
    python scripts/test_embedded_odds.py
Exits 0 and prints OK on success; raises AssertionError otherwise.

Mirrors the real jugabet SSR shape observed in probing: the home outcome omits
`type` (-> 0), draw is type 1, away is type 3, and the 1X2 market is marked by
marketKey[1:3]==[2,0]. Includes noise (an earlier unrelated array, a non-result
market, HTML around the blob) to prove the bracket-matcher and filters hold.
"""

from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.parser.embedded_odds import extract_result_outcomes, find_events_array, parse_events


def _outcome(eid, type_, price, original, market_key=(1, 2, 0, "null", "null"), with_type=True):
    o = {
        "id": f"{eid}_2_0_-_1_-_-",
        "marketItemId": f"{eid}_2_0_-_1_-_-",
        "marketKey": list(market_key),
        "eventId": eid,
        "status": 1,
        "price": price,
        "originalPrice": original,
    }
    if with_type:
        o["type"] = type_
    return o


def _build_html() -> str:
    # An earlier, unrelated small array of objects (noise the scanner must skip
    # over without mistaking it for the events array).
    noise = json.dumps([{"id": "x", "label": "menu"}, {"id": "y", "label": "promo"}])

    mexico = {
        "id": "15069103",
        "startsAt": "2026-06-12T19:00:00Z",
        "competitors": [
            {"id": "14516", "name": "México", "slug": "mexico"},
            {"id": "19736", "name": "Sudáfrica", "slug": "south-africa"},
        ],
        "tournament": {"id": "c19cb5ffb4404", "name": "Etapa de grupos"},
        "markets": [
            {
                "name": "1X2",
                "outcomes": [
                    _outcome("15069103", 0, 1.43, 1.41, with_type=False),  # home omits type
                    _outcome("15069103", 1, 4.46, 4.4),
                    _outcome("15069103", 3, 8.55, 8.43),
                ],
            },
            {
                # a non-result market (over/under) that must be ignored
                "name": "Total",
                "outcomes": [
                    {"eventId": "15069103", "type": 0, "price": 1.90,
                     "marketKey": [1, 18, 0, "null", "null"], "marketItemId": "15069103_18_0_-_1_-_-"},
                ],
            },
        ],
    }
    canada = {
        "id": "16226843",
        "competitors": [
            {"id": "1", "name": "Canada"},
            {"id": "2", "name": "Bosnia"},
        ],
        "markets": [
            {
                "name": "1X2",
                "outcomes": [
                    _outcome("16226843", 0, 1.80, 1.78, with_type=False),
                    _outcome("16226843", 1, 3.74, 3.70),
                    _outcome("16226843", 3, 4.57, 4.52),
                ],
            }
        ],
    }
    # 2-way winner (tennis/basketball/fights): types 0 and 3, no draw.
    tennis = {
        "id": "17004991",
        "competitors": [
            {"id": "1", "name": "Arnaldi"},
            {"id": "2", "name": "Cobolli"},
        ],
        "markets": [
            {
                "name": "Winner",
                "outcomes": [
                    _outcome("17004991", 0, 3.05, 3.00, market_key=(1, 1, 0, "null", "null"), with_type=False),
                    _outcome("17004991", 3, 1.44, 1.43, market_key=(1, 1, 0, "null", "null")),
                ],
            }
        ],
    }
    events = json.dumps([mexico, canada, tennis], ensure_ascii=False)
    return (
        "<!doctype html><html><head><script>window.menu="
        + noise
        + ";</script></head><body><main class='loading'>"
        + "<sport-events data-events='"
        + events
        + "'></sport-events></main></body></html>"
    )


def main() -> None:
    html = _build_html()

    events = find_events_array(html)
    assert isinstance(events, list) and len(events) == 3, f"expected 3 events, got {events!r}"

    odds = extract_result_outcomes(html)
    assert set(odds) == {"15069103", "16226843", "17004991"}, f"event ids wrong: {set(odds)}"

    mex = odds["15069103"]
    assert mex == {0: 1.43, 1: 4.46, 3: 8.55}, f"mexico odds wrong: {mex}"

    can = odds["16226843"]
    assert can == {0: 1.80, 1: 3.74, 3: 4.57}, f"canada odds wrong: {can}"

    # 2-way winner: only home(0) + away(3), no draw key
    ten = odds["17004991"]
    assert ten == {0: 3.05, 3: 1.44}, f"tennis 2-way odds wrong: {ten}"
    assert 1 not in ten, "2-way market must not invent a draw"

    # the over/under (non-result) market must NOT leak a 1.90 into home
    assert mex[0] == 1.43, "result-market filter failed (total market leaked)"

    # parse_events returns the same odds plus tournament UUIDs in one pass
    odds2, tids = parse_events(html)
    assert odds2 == odds, "parse_events odds disagree with extract_result_outcomes"
    assert tids.get("15069103") == "c19cb5ffb4404", f"mexico tournament id wrong: {tids}"

    # empty / garbage inputs are safe
    assert extract_result_outcomes("") == {}
    assert extract_result_outcomes("<html>no json here</html>") == {}
    assert extract_result_outcomes("[{\"broken\": ") == {}

    print("OK: embedded_odds extraction passed all assertions")


if __name__ == "__main__":
    main()
