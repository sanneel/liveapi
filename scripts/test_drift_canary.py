"""Standalone test for app/parser/drift_canary classification logic.

Run locally or on the VPS:
    python scripts/test_drift_canary.py
Exits 0 and prints OK on success; raises AssertionError otherwise.

No network: feeds synthetic HTML straight into _classify to prove the four
outcomes (ok / drifted / no_events / unreachable) are distinguished correctly,
including the key case — events present on the page but extractor yields none.
"""

from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.parser.drift_canary import _classify, get_last_result


def _page(events: list) -> str:
    """Wrap an events array in page-like HTML (with noise around the blob)."""
    return (
        "<html><head><title>jugabet</title></head><body>"
        "<script>window.__STATE__=" + json.dumps(events) + ";</script>"
        "</body></html>"
    )


def _valid_event() -> dict:
    # A normal 1X2 event: home(0)/draw(1)/away(3) with usable prices.
    return {
        "id": "E1",
        "tournament": {"id": "T1"},
        "markets": [
            {
                "name": "1X2",
                "outcomes": [
                    {"eventId": "E1", "type": 0, "price": 1.50, "marketKey": [1, 2, 0, "null", "null"]},
                    {"eventId": "E1", "type": 1, "price": 3.20, "marketKey": [1, 2, 0, "null", "null"]},
                    {"eventId": "E1", "type": 3, "price": 4.00, "marketKey": [1, 2, 0, "null", "null"]},
                ],
            }
        ],
    }


def _renumbered_event() -> dict:
    # Drift: jugabet still ships eventId/price, but the result-market selection
    # ids changed (10/12 instead of 0/3), so the extractor matches nothing.
    return {
        "id": "E1",
        "markets": [
            {
                "name": "1X2",
                "outcomes": [
                    {"eventId": "E1", "type": 10, "price": 1.50},
                    {"eventId": "E1", "type": 12, "price": 4.00},
                ],
            }
        ],
    }


def main() -> None:
    # ok: a valid event yields one extracted match-result.
    status, n = _classify(_page([_valid_event()]))
    assert status == "ok" and n == 1, f"expected ok/1, got {status}/{n}"

    # drifted: markers present, extractor returns zero (renumbered selections).
    status, n = _classify(_page([_renumbered_event()]))
    assert status == "drifted" and n == 0, f"expected drifted/0, got {status}/{n}"

    # no_events: a normal page with no event markers at all.
    status, n = _classify("<html><body>No hay partidos.</body></html>")
    assert status == "no_events" and n == 0, f"expected no_events/0, got {status}/{n}"

    # unreachable: the GET failed (None HTML).
    status, n = _classify(None)
    assert status == "unreachable" and n == 0, f"expected unreachable/0, got {status}/{n}"

    # Cache starts empty -> "unknown", never raises.
    assert get_last_result()["status"] == "unknown"

    print("OK: drift_canary classification (ok/drifted/no_events/unreachable) passed")


if __name__ == "__main__":
    main()
