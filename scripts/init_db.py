#!/usr/bin/env python3
"""
One-time database initialization.

Creates the SQLite file (if needed) and runs all Alembic migrations.

Usage:
    python scripts/init_db.py
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

# Make `app.*` importable when this is run from anywhere
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from app.config import get_settings  # noqa: E402
from app.logging_config import get_logger  # noqa: E402

logger = get_logger("init_db")


def main() -> int:
    settings = get_settings()
    logger.info(f"Database URL: {settings.database_url}")

    # Ensure data dir exists
    if settings.database_url.startswith("sqlite:///"):
        db_path = Path(settings.database_url.replace("sqlite:///", "", 1))
        db_path.parent.mkdir(parents=True, exist_ok=True)
        logger.info(f"Data directory ready: {db_path.parent}")

    # Run Alembic upgrade head
    logger.info("Running migrations: alembic upgrade head")
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=str(PROJECT_ROOT),
    )
    if result.returncode != 0:
        logger.error("Alembic migration failed.")
        return result.returncode

    # Print summary
    from sqlalchemy import inspect

    from app.database import engine

    inspector = inspect(engine)
    tables = inspector.get_table_names()
    logger.info(f"Tables created ({len(tables)}):")
    for t in sorted(tables):
        logger.info(f"  - {t}")

    logger.info("[success] Database initialized successfully.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
