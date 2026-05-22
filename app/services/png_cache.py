"""
Tiny in-process PNG cache for the new public endpoints (/hot, /club).

Mirrors the cache contract of `public_render._png_cache` but keyed by
arbitrary strings ('hot:football', 'club:csd-colo-colo') so different
namespaces don't collide.

Process-local only. No Redis, no IPC. Single-worker assumption holds
through the deprecation window — see deploy/jugabet.service.
"""

from __future__ import annotations

import threading
import time
from typing import Dict, Optional, Tuple

from ..config import get_settings

_lock = threading.Lock()
_cache: Dict[str, Tuple[float, bytes]] = {}

_settings = get_settings()
TTL_SECONDS = _settings.public_cache_seconds
MAX_ENTRIES = _settings.public_cache_max_entries


def get(key: str) -> Optional[bytes]:
    with _lock:
        entry = _cache.get(key)
        if entry and (time.time() - entry[0]) < TTL_SECONDS:
            return entry[1]
    return None


def put(key: str, png: bytes) -> None:
    with _lock:
        if len(_cache) >= MAX_ENTRIES:
            oldest = min(_cache, key=lambda k: _cache[k][0])
            _cache.pop(oldest, None)
        _cache[key] = (time.time(), png)


def invalidate(key: str) -> None:
    with _lock:
        _cache.pop(key, None)


def invalidate_prefix(prefix: str) -> None:
    """Drop all entries whose key begins with `prefix` — useful for
    sport-scoped invalidation on hot_override mutations."""
    with _lock:
        for k in [k for k in _cache if k.startswith(prefix)]:
            _cache.pop(k, None)


def invalidate_all() -> None:
    with _lock:
        _cache.clear()
