"""
Seed a synthetic club + upcoming match for local testing.

Useful when the parser can't reach jugabet.cl (geo restriction) and the
clubs table stays empty. Inserts:

  clubs:   'test-club' (Test Club)
  matches: a single prematch row with home_slug='test-club'

Idempotent — uses INSERT OR IGNORE on the club row, and creates the
match row only if no match with event_id='test-match-1' exists.

Run:
    venv_win\\Scripts\\python scripts\\seed_test_club.py
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta

DB_PATH = "data/jugabet.db"
CLUB_SLUG = "test-club"
CLUB_NAME = "Test Club"
EVENT_ID = "test-match-1"


def main() -> None:
    now = datetime.utcnow()
    now_iso = now.isoformat()
    kickoff = (now + timedelta(hours=3)).isoformat()

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    cur.execute(
        "INSERT OR IGNORE INTO clubs(slug, name, logo, created_at, updated_at) "
        "VALUES (?, ?, NULL, ?, ?)",
        (CLUB_SLUG, CLUB_NAME, now_iso, now_iso),
    )
    print(f"club rows touched: {cur.rowcount}")

    existing = cur.execute(
        "SELECT 1 FROM matches WHERE event_id = ?", (EVENT_ID,)
    ).fetchone()
    if existing:
        print(f"match {EVENT_ID} already exists, skipping insert")
    else:
        cur.execute(
            """
            INSERT INTO matches (
                event_id, sport, mode, status,
                home_name, away_name, home_slug, away_slug,
                home_logo, away_logo,
                tournament_name, href,
                start_time_utc, time_raw,
                home_score, away_score,
                market_type, market_name, odds_json,
                hot_score, is_active,
                first_seen_at, last_updated_at
            ) VALUES (
                ?, 'football', 'prematch', 'prematch',
                ?, 'Rival FC', ?, 'rival-fc',
                NULL, NULL,
                'Local Test League', NULL,
                ?, ?,
                NULL, NULL,
                '1x2', '1X2', NULL,
                NULL, 1,
                ?, ?
            )
            """,
            (EVENT_ID, CLUB_NAME, CLUB_SLUG, kickoff, "Today, 22:00", now_iso, now_iso),
        )
        print(f"inserted match {EVENT_ID}: {CLUB_NAME} vs Rival FC at {kickoff}")

    conn.commit()
    conn.close()
    print("done")


if __name__ == "__main__":
    main()
