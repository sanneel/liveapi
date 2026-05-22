"""Insert a synthetic UCL match so the cube widget has something to render
when the parser is off (Windows dev). Idempotent — re-running just refreshes
the row. Delete with: DELETE FROM matches WHERE event_id='cube-demo-ucl'.
"""

from datetime import datetime

from app.database import db_session
from app.models import Match


def main() -> None:
    with db_session() as s:
        existing = s.get(Match, "cube-demo-ucl")
        now = datetime.utcnow()
        if existing is None:
            s.add(Match(
                event_id="cube-demo-ucl",
                sport="football",
                mode="prematch",
                status="prematch",
                home_name="Real Madrid",
                away_name="Manchester City",
                tournament_name="UEFA Champions League",
                tournament_slug="uefa-champions-league",
                time_raw="Hoy, 21:00",
                market_type="1x2",
                market_name="Resultado del partido",
                odds_json='{"p1": "2.10", "draw": "3.40", "p2": "3.05"}',
                is_active=True,
                first_seen_at=now,
                last_updated_at=now,
            ))
            print("inserted cube-demo-ucl")
        else:
            existing.is_active = True
            existing.last_updated_at = now
            existing.odds_json = '{"p1": "2.10", "draw": "3.40", "p2": "3.05"}'
            print("refreshed cube-demo-ucl")


if __name__ == "__main__":
    main()
