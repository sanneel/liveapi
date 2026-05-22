"""
Jugabet Odds CRM — production application package.

Layout:
  app/config.py            — settings loaded from .env
  app/database.py          — SQLAlchemy engine + session factory
  app/logging_config.py    — structured logging (rotating file + console)
  app/models/              — ORM models, one table per file
  app/repositories/        — DB access layer (queries, upserts)
  app/parser/              — auto-fetch + persistence
"""
