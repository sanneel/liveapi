"""
Cross-cutting middleware (rate limiting, etc.).

The slowapi limiter is configured here and attached to the FastAPI app
in server.py. Limits are per-IP via the X-Forwarded-For header (so they
work correctly behind Cloudflare / Caddy).
"""

from __future__ import annotations

from slowapi import Limiter
from slowapi.util import get_remote_address

from ..logging_config import get_logger

logger = get_logger("app.middleware.ratelimit")


def _key(request) -> str:
    """Per-IP key. Honours X-Forwarded-For (set by Caddy / Cloudflare)."""
    xff = request.headers.get("x-forwarded-for")
    if xff:
        return xff.split(",")[0].strip()
    return get_remote_address(request)


limiter = Limiter(
    key_func=_key,
    default_limits=["200/minute"],   # safe fallback for any route without explicit limit
    storage_uri="memory://",         # in-process — fine for a single-VPS setup
)
