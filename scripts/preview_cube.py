"""Render UCL + WorldCup cubes with synthetic match data for preview."""

from datetime import datetime

from app.models import Match
from app.render.cube_render import render_cube_png
from app.services.cube_themes import get_theme


def main() -> None:
    ucl_match = Match(
        event_id="demo-1",
        sport="football",
        status="prematch",
        mode="prematch",
        home_name="Real Madrid",
        away_name="Manchester City",
        tournament_name="UEFA Champions League",
        tournament_slug="uefa-champions-league",
        time_raw="Hoy, 20:00",
        odds_json='{"p1": "2.10", "draw": "3.40", "p2": "3.05"}',
        is_active=True,
        last_updated_at=datetime.utcnow(),
    )
    png = render_cube_png(get_theme("ucl"), ucl_match)
    open("logs/cube_ucl_real.png", "wb").write(png)
    print(f"ucl with match bytes: {len(png)}")

    wc_match = Match(
        event_id="demo-2",
        sport="football",
        status="live",
        mode="live",
        home_name="Argentina",
        away_name="France",
        home_score=2,
        away_score=2,
        tournament_name="FIFA World Cup",
        tournament_slug="fifa-world-cup",
        time_raw="89'",
        odds_json='{"p1": "1.85", "draw": "3.50", "p2": "4.20"}',
        is_active=True,
        last_updated_at=datetime.utcnow(),
    )
    png2 = render_cube_png(get_theme("worldcup"), wc_match)
    open("logs/cube_wc_real.png", "wb").write(png2)
    print(f"wc with match bytes: {len(png2)}")


if __name__ == "__main__":
    main()
