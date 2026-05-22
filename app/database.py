"""
Database engine + session factory.

Usage:
    from app.database import db_session
    with db_session() as session:
        session.query(Match)...

The context manager auto-commits on success and auto-rolls-back on exception.
"""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker
from fastapi import HTTPException

from .config import get_settings
from .logging_config import get_logger

logger = get_logger("app.database")

_settings = get_settings()

# Ensure the data directory exists (SQLite needs a writable parent)
if _settings.database_url.startswith("sqlite:///"):
    db_path = _settings.database_url.replace("sqlite:///", "", 1)
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)

engine: Engine = create_engine(
    _settings.database_url,
    connect_args={"check_same_thread": False} if "sqlite" in _settings.database_url else {},
    pool_pre_ping=True,
    echo=False,
)


# Enable SQLite WAL mode for better read concurrency under load
@event.listens_for(engine, "connect")
def _enable_sqlite_pragmas(dbapi_connection, _connection_record):  # noqa: ANN001
    if "sqlite" not in _settings.database_url:
        return
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA synchronous=NORMAL")
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.execute("PRAGMA busy_timeout=5000")
    cursor.close()


SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine, expire_on_commit=False)


@contextmanager
def db_session() -> Iterator[Session]:
    """Context manager for DB sessions with auto-commit/rollback."""
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except HTTPException:
        session.rollback()
        raise
    except Exception:
        session.rollback()
        logger.exception("DB session rolled back due to exception")
        raise
    finally:
        session.close()


def get_db() -> Iterator[Session]:
    """FastAPI dependency."""
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
