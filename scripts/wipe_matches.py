"""Destructive one-shot: wipe every row from the `matches` table so the
parser can repopulate from scratch.

Also clears `campaign_matches` (FK into matches.event_id) since matches-only
deletion fails the FK constraint. User-created campaigns survive; they just
lose their selected-match list and need to be re-picked once the parser
repopulates matches.

Preserves: campaigns, clubs, users, admin_logs, hot_override*, campaign_hits.
"""

from sqlalchemy import text

from app.database import db_session


def main() -> None:
    from app.database import engine
    dbapi_conn = engine.raw_connection()
    try:
        cursor = dbapi_conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM matches")
        m_before = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM campaign_matches")
        cm_before = cursor.fetchone()[0]

        cursor.execute("PRAGMA foreign_keys = OFF")
        cursor.execute("BEGIN TRANSACTION")
        cursor.execute("DELETE FROM campaign_matches")
        cursor.execute("DELETE FROM matches")
        dbapi_conn.commit()

        cursor.execute("SELECT COUNT(*) FROM matches")
        m_after = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM campaign_matches")
        cm_after = cursor.fetchone()[0]

        print(f"matches:          {m_before} -> {m_after}  (deleted {m_before - m_after})")
        print(f"campaign_matches: {cm_before} -> {cm_after}  (deleted {cm_before - cm_after})")
    except Exception as e:
        dbapi_conn.rollback()
        raise e
    finally:
        dbapi_conn.close()


if __name__ == "__main__":
    main()
