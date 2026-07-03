"""Regression tests for parser-link live odds handling.

Run locally or on the VPS:
    python scripts/test_parser_link_live_odds.py
Exits 0 / prints OK on success; raises AssertionError otherwise.
"""

from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models.match import Match
from app.parser.priority_odds import _tournament_ids_from_url
from app.repositories.match_repo import MatchRepository


def _event(status: str) -> dict:
    return {
        "event_id": "wc_playoff_live",
        "status": status,
        "time": {"raw": "Hoy, 20:00", "utc": (datetime.utcnow() + timedelta(hours=1)).isoformat()},
        "tournament": {
            "id": "playoff-tid",
            "name": "FIFA World Cup. Play-Off",
        },
        "competitors": {
            "home": {"name": "Chile", "slug": "chile"},
            "away": {"name": "Peru", "slug": "peru"},
        },
        "score": {"home": 0 if status == "live" else None, "away": 0 if status == "live" else None},
        "market": {
            "name": "1X2",
            "type": "1x2",
            "odds": {"p1": "1.80", "draw": "3.40", "p2": "4.70"},
        },
    }


def test_overlay_live_event_promotes_mode() -> None:
    engine = create_engine("sqlite:///:memory:")
    Match.__table__.create(bind=engine)
    session = sessionmaker(bind=engine)()
    repo = MatchRepository(session)

    repo.upsert_event(_event("live"), "football", "prematch")
    session.commit()
    match = session.get(Match, "wc_playoff_live")
    assert match.mode == "live", f"expected live mode from overlay status, got {match.mode!r}"
    assert match.status == "live", f"expected live status, got {match.status!r}"

    repo.upsert_event(_event("prematch"), "football", "prematch")
    session.commit()
    match = session.get(Match, "wc_playoff_live")
    assert match.mode == "live", "prematch refresh clobbered live mode"
    assert match.status == "live", "prematch refresh clobbered live status"


def test_parser_link_tournament_ids() -> None:
    assert _tournament_ids_from_url(
        "https://jugabet.cl/football/all/1?Tournaments=abc-123,def456"
    ) == {"abc-123", "def456"}
    assert _tournament_ids_from_url(
        "https://jugabet.cl/#/football/all/1?tournaments[]=playoff-tid"
    ) == {"playoff-tid"}
    assert _tournament_ids_from_url(
        "https://jugabet.cl/football/all/1?tournament=single"
    ) == {"single"}


def main() -> None:
    test_overlay_live_event_promotes_mode()
    test_parser_link_tournament_ids()
    print("OK: parser-link live odds regression tests passed")


if __name__ == "__main__":
    main()
