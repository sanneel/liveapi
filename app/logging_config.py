"""
Structured logging configuration.

Three files (rotating, 10 MB × 10):
  logs/app.log      — everything INFO+
  logs/parser.log   — only "app.parser.*" loggers
  logs/errors.log   — only ERROR+ from the whole app
"""

from __future__ import annotations

import logging
import logging.handlers
import sys
from pathlib import Path

from .config import get_settings


_configured = False

_FORMAT = "%(asctime)s | %(levelname)-7s | %(name)-30s | %(message)s"
_DATEFMT = "%Y-%m-%d %H:%M:%S"


def _make_rotating_handler(path: Path, level: int) -> logging.Handler:
    settings = get_settings()
    h = logging.handlers.RotatingFileHandler(
        path,
        maxBytes=settings.log_max_bytes,
        backupCount=settings.log_backup_count,
        encoding="utf-8",
    )
    h.setLevel(level)
    h.setFormatter(logging.Formatter(_FORMAT, _DATEFMT))
    return h


def setup_logging() -> None:
    global _configured
    if _configured:
        return

    settings = get_settings()
    log_dir = Path(settings.log_dir)
    log_dir.mkdir(parents=True, exist_ok=True)

    root = logging.getLogger()
    root.setLevel(getattr(logging, settings.log_level.upper(), logging.INFO))

    # Remove default handlers (uvicorn / pytest may have added some)
    root.handlers.clear()

    # ── Console ──
    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(logging.Formatter(_FORMAT, _DATEFMT))
    root.addHandler(console)

    # ── app.log: everything ──
    root.addHandler(_make_rotating_handler(log_dir / "app.log", logging.DEBUG))

    # ── errors.log: only ERROR+ ──
    root.addHandler(_make_rotating_handler(log_dir / "errors.log", logging.ERROR))

    # ── parser.log: dedicated channel ──
    parser_logger = logging.getLogger("app.parser")
    parser_logger.addHandler(_make_rotating_handler(log_dir / "parser.log", logging.DEBUG))
    parser_logger.propagate = True  # also bubble up to root/console

    # Silence very chatty libraries
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("PIL").setLevel(logging.WARNING)

    _configured = True


def get_logger(name: str) -> logging.Logger:
    setup_logging()
    return logging.getLogger(name)
