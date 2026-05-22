"""One-shot: rows misfiled as sport='mundo' actually came from a football
overlay feed (see server.py FEEDS for /football/all/?tournaments=...). Remap
them back to 'football' so they appear under the football endpoints.
"""

from sqlalchemy import text

from app.database import db_session


def main() -> None:
    with db_session() as s:
        n = s.execute(
            text("UPDATE matches SET sport='football' WHERE sport='mundo'")
        ).rowcount
        print(f"remapped sport='mundo' -> 'football': {n} rows")


if __name__ == "__main__":
    main()
