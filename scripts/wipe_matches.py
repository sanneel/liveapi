"""Destructive one-shot: wipe every row from the `matches` table so the
parser can repopulate from scratch.

Also clears `campaign_matches` (FK into matches.event_id) since matches-only
deletion fails the FK constraint. User-created campaigns survive; they just
lose their selected-match list and need to be re-picked once the parser
repopulates matches.

Preserves: campaigns, clubs, users, admin_logs, hot_override*, campaign_hits.

Safe by default: running without --yes only previews the row counts and makes
no changes. Pass --yes to actually delete.

    python scripts/wipe_matches.py            # preview only
    python scripts/wipe_matches.py --yes      # actually wipe
"""

from __future__ import annotations

import argparse


def _counts(cursor) -> tuple[int, int]:
    cursor.execute("SELECT COUNT(*) FROM matches")
    matches = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM campaign_matches")
    campaign_matches = cursor.fetchone()[0]
    return matches, campaign_matches


def main(confirmed: bool) -> None:
    from app.database import engine

    dbapi_conn = engine.raw_connection()
    try:
        cursor = dbapi_conn.cursor()
        m_before, cm_before = _counts(cursor)

        if not confirmed:
            print("DRY RUN - nothing deleted. Re-run with --yes to wipe.")
            print(f"  matches:          {m_before} rows would be deleted")
            print(f"  campaign_matches: {cm_before} rows would be deleted")
            return

        cursor.execute("PRAGMA foreign_keys = OFF")
        cursor.execute("BEGIN TRANSACTION")
        cursor.execute("DELETE FROM campaign_matches")
        cursor.execute("DELETE FROM matches")
        dbapi_conn.commit()

        m_after, cm_after = _counts(cursor)
        print(f"matches:          {m_before} -> {m_after}  (deleted {m_before - m_after})")
        print(f"campaign_matches: {cm_before} -> {cm_after}  (deleted {cm_before - cm_after})")
    except Exception:
        dbapi_conn.rollback()
        raise
    finally:
        dbapi_conn.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--yes",
        action="store_true",
        help="Actually delete. Without this flag the script only previews counts.",
    )
    args = parser.parse_args()
    main(confirmed=args.yes)
