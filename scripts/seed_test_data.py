#!/usr/bin/env python3
"""
Seed realistic test matches into the DB so the admin UI has something to show
before the parser can reach jugabet.cl.

Run: python scripts/seed_test_data.py

Idempotent — re-running just updates existing seeded matches.
Test matches all have event_ids starting with "seed_".
You can remove them later with:
  DELETE FROM matches WHERE event_id LIKE 'seed_%';
"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from app.database import db_session  # noqa: E402
from app.repositories.match_repo import MatchRepository  # noqa: E402
from app.logging_config import get_logger  # noqa: E402

logger = get_logger("seed")


def _event(eid, home, away, league, sport, mode, status, hours_from_now,
           odds, score=None, home_slug=None, away_slug=None):
    now = datetime.now(timezone.utc)
    start = now + timedelta(hours=hours_from_now)
    return {
        "event_id": f"seed_{eid}",
        "href": f"https://jugabet.cl/events/{eid}",
        "status": status,
        "time": {
            "raw": start.strftime("%d %b, %H:%M"),
            "utc": start.isoformat(),
        },
        "tournament": {"name": league},
        "competitors": {
            "home": {
                "name": home,
                "logo": f"https://jugabet.cl/static/iolite/icons/{home_slug}.webp" if home_slug else None,
            },
            "away": {
                "name": away,
                "logo": f"https://jugabet.cl/static/iolite/icons/{away_slug}.webp" if away_slug else None,
            },
        },
        "score": {"home": score[0] if score else None, "away": score[1] if score else None},
        "market": {
            "name": "Resultado del partido (tiempo reglamentario)",
            "type": "1x2" if len(odds) == 3 else "winner",
            "odds": (
                {"p1": odds[0], "draw": odds[1], "p2": odds[2], "more_odds": False}
                if len(odds) == 3 else
                {"p1": odds[0], "p2": odds[1], "more_odds": False}
            ),
        },
    }


SEED = [
    # ─── Football ─────────────────────────────────────────────────────
    ("ft1", "Colo-Colo", "Universidad de Chile",
     "Chile. Primera División", "football", "prematch", "prematch",
     6, ("1.85", "3.40", "4.20"), None, "colo-colo", "universidad-de-chile"),

    ("ft2", "Real Madrid", "Barcelona",
     "España. La Liga", "football", "prematch", "prematch",
     30, ("2.10", "3.60", "3.20"), None, None, None),

    ("ft3", "River Plate", "Boca Juniors",
     "Argentina. Liga Profesional", "football", "live", "live",
     -1, ("2.30", "3.10", "3.00"), (1, 0), None, None),

    ("ft4", "Manchester City", "Arsenal",
     "Inglaterra. Premier League", "football", "prematch", "prematch",
     54, ("1.55", "4.20", "5.80"), None, None, None),

    ("ft5", "Audax Italiano", "Barracas Central",
     "América del Sur. Copa Sudamericana", "football", "prematch", "prematch",
     20, ("2.46", "3.20", "2.98"), None, None, None),

    # ─── Basketball ───────────────────────────────────────────────────
    ("bk1", "Los Angeles Lakers", "Golden State Warriors",
     "NBA", "basketball", "prematch", "prematch",
     8, ("1.72", "2.10"), None, None, None),

    ("bk2", "Boston Celtics", "Miami Heat",
     "NBA", "basketball", "live", "live",
     -1, ("1.45", "2.80"), (87, 91), None, None),

    # ─── Tennis ───────────────────────────────────────────────────────
    ("tn1", "Carlos Alcaraz", "Novak Djokovic",
     "Roland Garros", "tennis", "prematch", "prematch",
     12, ("1.90", "1.95"), None, None, None),

    ("tn2", "Jannik Sinner", "Alexander Zverev",
     "Roland Garros", "tennis", "prematch", "prematch",
     36, ("1.60", "2.35"), None, None, None),

    # ─── Cybersport ───────────────────────────────────────────────────
    ("cy1", "NAVI", "G2 Esports",
     "CS2 · ESL Pro League", "cybersport", "prematch", "prematch",
     4, ("1.75", "2.05"), None, None, None),

    ("cy2", "T1", "Cloud9",
     "LoL · Worlds 2025", "cybersport", "prematch", "prematch",
     22, ("1.40", "2.90"), None, None, None),

    # ─── Fights ───────────────────────────────────────────────────────
    ("fg1", "Israel Adesanya", "Sean Strickland",
     "UFC 310 · Middleweight", "ufc", "prematch", "prematch",
     48, ("1.85", "2.00"), None, None, None),

    ("fg2", "Canelo Álvarez", "David Benavidez",
     "Boxing · Super Middleweight", "boxing", "prematch", "prematch",
     96, ("1.55", "2.50"), None, None, None),
]


def main() -> int:
    logger.info(f"Seeding {len(SEED)} test matches into DB...")
    with db_session() as session:
        repo = MatchRepository(session)
        for args in SEED:
            event = _event(*args)
            sport = args[4]
            mode = args[5]
            repo.upsert_event(event, sport, mode)
    logger.info(f"✓ Seeded {len(SEED)} matches.")
    logger.info("Now run the server and open http://127.0.0.1:8000/admin")
    return 0


if __name__ == "__main__":
    sys.exit(main())
