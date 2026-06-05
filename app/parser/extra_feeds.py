"""Admin-managed parser feed links."""

from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any, Dict, List, Tuple
from urllib.parse import urlparse

from ..config import BASE_DIR


EXTRA_FEEDS_FILE = BASE_DIR / "data" / "parser_extra_feeds.json"
VALID_SPORTS = {"football", "basketball", "tennis", "cybersport", "boxing", "mma", "ufc"}
VALID_MODES = {"prematch", "live"}

_NON_SLUG = re.compile(r"[^a-z0-9]+")


def _slugify(value: str) -> str:
    value = (value or "").casefold().strip()
    value = _NON_SLUG.sub("-", value).strip("-")
    return value[:48].strip("-") or "custom"


def _validate_url(url: str) -> str:
    url = (url or "").strip()
    parsed = urlparse(url)
    if parsed.scheme != "https":
        raise ValueError("URL must start with https://")
    if (parsed.hostname or "").lower() not in {"jugabet.cl", "www.jugabet.cl"}:
        raise ValueError("URL must be on jugabet.cl")
    return url


def load_extra_feeds() -> List[Dict[str, Any]]:
    try:
        raw = json.loads(EXTRA_FEEDS_FILE.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return []
    except Exception:
        return []
    if not isinstance(raw, list):
        return []
    feeds: List[Dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        try:
            feed = normalize_feed(item)
        except ValueError:
            continue
        feeds.append(feed)
    return feeds


def save_extra_feeds(feeds: List[Dict[str, Any]]) -> None:
    EXTRA_FEEDS_FILE.parent.mkdir(parents=True, exist_ok=True)
    cleaned = [normalize_feed(feed) for feed in feeds]
    EXTRA_FEEDS_FILE.write_text(
        json.dumps(cleaned, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def normalize_feed(feed: Dict[str, Any]) -> Dict[str, Any]:
    label = str(feed.get("label") or "").strip()
    url = _validate_url(str(feed.get("url") or ""))
    sport = str(feed.get("sport") or "").strip().lower()
    mode = str(feed.get("mode") or "").strip().lower()
    if sport not in VALID_SPORTS:
        raise ValueError("Unsupported sport")
    if mode not in VALID_MODES:
        raise ValueError("Unsupported mode")
    feed_id = _slugify(str(feed.get("id") or label or url))
    return {
        "id": feed_id,
        "label": label or feed_id.replace("-", " ").title(),
        "sport": sport,
        "mode": mode,
        "url": url,
        "enabled": bool(feed.get("enabled", True)),
        "created_at": int(feed.get("created_at") or time.time()),
    }


def add_extra_feed(label: str, sport: str, mode: str, url: str) -> Dict[str, Any]:
    feeds = load_extra_feeds()
    new_feed = normalize_feed(
        {
            "label": label,
            "sport": sport,
            "mode": mode,
            "url": url,
            "created_at": int(time.time()),
        }
    )
    existing_ids = {feed["id"] for feed in feeds}
    base_id = new_feed["id"]
    suffix = 2
    while new_feed["id"] in existing_ids:
        new_feed["id"] = f"{base_id}-{suffix}"
        suffix += 1
    feeds.append(new_feed)
    save_extra_feeds(feeds)
    return new_feed


def delete_extra_feed(feed_id: str) -> bool:
    feed_id = _slugify(feed_id)
    feeds = load_extra_feeds()
    kept = [feed for feed in feeds if feed["id"] != feed_id]
    if len(kept) == len(feeds):
        return False
    save_extra_feeds(kept)
    return True


def feed_key(feed: Dict[str, Any]) -> Tuple[str, str]:
    return str(feed["sport"]), f"{feed['mode']}_extra_{feed['id']}"


def build_extra_feed_map() -> Dict[Tuple[str, str], str]:
    return {
        feed_key(feed): str(feed["url"])
        for feed in load_extra_feeds()
        if feed.get("enabled", True)
    }
