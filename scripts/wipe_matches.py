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
    with db_session() as s:
        m_before = s.execute(text("SELECT COUNT(*) FROM matches")).scalar()
        cm_before = s.execute(text("SELECT COUNT(*) FROM campaign_matches")).scalar()
        s.execute(text("DELETE FROM campaign_matches"))
        s.execute(text("DELETE FROM matches"))
        m_after = s.execute(text("SELECT COUNT(*) FROM matches")).scalar()
        cm_after = s.execute(text("SELECT COUNT(*) FROM campaign_matches")).scalar()
        print(f"matches:          {m_before} -> {m_after}  (deleted {m_before - m_after})")
        print(f"campaign_matches: {cm_before} -> {cm_after}  (deleted {cm_before - cm_after})")


if __name__ == "__main__":
    main()
