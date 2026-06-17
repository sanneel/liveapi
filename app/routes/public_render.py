"""
Public dynamic campaign rendering.

  GET /r/{slug}.png[?limit=N]

This is the URL embedded in emails. On every email open:
  1. Look up campaign by slug
  2. If disabled or expired → 404
  3. Resolve matches:
       mode='manual' → editor's pick, in saved order
       mode='auto'   → top hottest for `sport`, optionally filtered by
                       `tournament_slug == slugify(campaign.league)`
                       Count comes from `?limit=` (default 5, max 20).
  4. Render PNG using the shared `render_for_sport` template
  5. Record an anonymized hit
  6. Return the PNG (no client-side cache → always fresh odds)

PNG is cached in-memory for `PUBLIC_CACHE_SECONDS` keyed by `{slug}:{limit}`.
The parser invalidates this cache for the affected sport after every
successful feed cycle, so admins and email recipients see fresh data within
one parse interval rather than waiting for TTL.
"""

from __future__ import annotations

import hashlib
import re
import threading
import time
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

from fastapi import APIRouter, Request, Response

from ..config import get_settings
from ..database import db_session
from ..logging_config import get_logger
from ..middleware import limiter
from ..models import Campaign, CampaignHit, Match
from ..render import render_for_sport
from ..repositories.campaign_repo import CampaignRepository
from ..services.hot_engine import HotEngine
from ..utils.slugify import slugify_league

DEFAULT_AUTO_LIMIT = 5
MAX_AUTO_LIMIT = 20

logger = get_logger("app.routes.public_render")

router = APIRouter()

settings = get_settings()
PUBLIC_CACHE_SECONDS = settings.public_cache_seconds
PUBLIC_CACHE_MAX_ENTRIES = settings.public_cache_max_entries
HIT_FLUSH_INTERVAL = 30            # batch-write hits at most every N seconds
SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{1,49}$")

# 1×1 transparent PNG for empty / disabled / expired campaigns
TRANSPARENT_PNG_1X1 = (
    b"\x89PNG\r\n\x1a\n"
    b"\x00\x00\x00\rIHDR"
    b"\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89"
    b"\x00\x00\x00\nIDATx\x9cc`\x00\x00\x00\x02\x00\x01"
    b"\xe2!\xbc3"
    b"\x00\x00\x00\x00IEND\xaeB`\x82"
)

# ── PNG cache ───────────────────────────────────────────────────────────
_png_cache_lock = threading.Lock()
_png_cache: Dict[str, Tuple[float, bytes]] = {}  # slug -> (ts, bytes)


def _cache_get(slug: str) -> Optional[bytes]:
    with _png_cache_lock:
        entry = _png_cache.get(slug)
        if entry and (time.time() - entry[0]) < PUBLIC_CACHE_SECONDS:
            return entry[1]
    return None


def _cache_put(slug: str, png: bytes) -> None:
    with _png_cache_lock:
        if len(_png_cache) >= PUBLIC_CACHE_MAX_ENTRIES:
            oldest_key = min(_png_cache, key=lambda k: _png_cache[k][0])
            _png_cache.pop(oldest_key, None)
        _png_cache[slug] = (time.time(), png)


# ── Cache invalidation (called by admin mutations for real-time updates) ──
def _slug_from_key(key: str) -> str:
    """Cache keys are 'slug:limit'; recover the slug."""
    return key.split(":", 1)[0]


def _cache_invalidate(slug: str) -> None:
    """Drop every cached entry for this campaign slug (all `?limit=` variants)."""
    with _png_cache_lock:
        for k in [k for k in _png_cache if _slug_from_key(k) == slug]:
            _png_cache.pop(k, None)


def _cache_invalidate_sport(sport: str) -> None:
    """Drop every cached PNG whose campaign is in `sport`."""
    with _png_cache_lock:
        slugs = {_slug_from_key(k) for k in _png_cache}
    if not slugs:
        return
    try:
        with db_session() as session:
            affected = (
                session.query(Campaign.slug)
                .filter(Campaign.slug.in_(slugs))
                .filter(Campaign.sport == sport)
                .all()
            )
        affected_slugs = {row[0] for row in affected}
    except Exception:
        logger.exception("cache invalidate_sport: DB lookup failed; clearing entire cache")
        _cache_invalidate_all()
        return
    if not affected_slugs:
        return
    with _png_cache_lock:
        for k in [k for k in _png_cache if _slug_from_key(k) in affected_slugs]:
            _png_cache.pop(k, None)


def _cache_invalidate_all() -> None:
    """Drop every cached PNG. Used by the admin 'Purge cache' button."""
    with _png_cache_lock:
        _png_cache.clear()


# ── Hit buffer (batched writes to avoid DB pressure during spikes) ─────
_hit_buffer_lock = threading.Lock()
_hit_buffer: List[Dict[str, Any]] = []
_last_flush_ts = 0.0


def _hash_ip(ip: Optional[str]) -> Optional[str]:
    if not ip:
        return None
    return hashlib.sha256(ip.encode("utf-8")).hexdigest()[:32]


def _client_ip(request: Request) -> str:
    xff = request.headers.get("x-forwarded-for")
    if xff:
        return xff.split(",")[0].strip()
    return request.client.host if request.client else ""


def _record_hit(slug: str, request: Request) -> None:
    """Buffer a hit, flush to DB periodically."""
    global _last_flush_ts
    ua = (request.headers.get("user-agent") or "")[:200]
    entry = {
        "campaign_slug": slug,
        "ts": datetime.utcnow(),
        "ip_hash": _hash_ip(_client_ip(request)),
        "user_agent": ua,
    }
    with _hit_buffer_lock:
        _hit_buffer.append(entry)
        now = time.time()
        if (now - _last_flush_ts) < HIT_FLUSH_INTERVAL and len(_hit_buffer) < 100:
            return
        batch = list(_hit_buffer)
        _hit_buffer.clear()
        _last_flush_ts = now

    try:
        with db_session() as session:
            session.bulk_insert_mappings(CampaignHit, batch)
    except Exception:
        logger.exception("failed to flush hit buffer")


def flush_hit_buffer() -> None:
    """Flush buffered analytics hits during graceful shutdown."""
    with _hit_buffer_lock:
        if not _hit_buffer:
            return
        batch = list(_hit_buffer)
        _hit_buffer.clear()

    try:
        with db_session() as session:
            session.bulk_insert_mappings(CampaignHit, batch)
    except Exception:
        logger.exception("failed to flush hit buffer on shutdown")


# ── Match resolution per campaign mode ─────────────────────────────────
def _clamp_limit(limit: Optional[int]) -> int:
    try:
        n = int(limit) if limit is not None else DEFAULT_AUTO_LIMIT
    except (TypeError, ValueError):
        n = DEFAULT_AUTO_LIMIT
    return max(1, min(n, MAX_AUTO_LIMIT))


def is_past_kickoff_cutoff(match: Match, now: datetime, hours: int) -> bool:
    """True once a match is `hours` past its kickoff — old enough to be
    treated as finished and hidden from a rendered campaign. Matches with no
    known start time are never hidden by this rule (we can't judge them)."""
    if not match.start_time_utc:
        return False
    return match.start_time_utc + timedelta(hours=hours) < now


def _resolve_matches(session, campaign: Campaign, auto_limit: int) -> List[Match]:
    """Return the matches that this campaign should render right now.

    Both modes drop matches more than `campaign_hide_after_start_hours` past
    kickoff (finished games disappear from the PNG without being deleted).

    Manual-mode additionally drops:
      * `is_active=False` rows (the parser stopped seeing the match)
      * `is_synthetic=True` rows (virtual / replay / esports — never public)

    The admin-side counterparts (campaign list + edit) call
    `manual_render_stats()` to surface WHY a campaign's render is empty,
    so a synthetic-only or all-stale selection doesn't ship a silent 1×1.
    """
    now = datetime.utcnow()
    hide_hours = get_settings().campaign_hide_after_start_hours

    if campaign.mode == "auto":
        engine = HotEngine(session, campaign.sport, league=campaign.league)
        # Over-fetch then drop past-kickoff matches and trim, so a finished
        # game in the top slots is backfilled by the next fresh match rather
        # than leaving the PNG short.
        pool = engine.resolve(MAX_AUTO_LIMIT)
        fresh = [m for m in pool if not is_past_kickoff_cutoff(m, now, hide_hours)]
        candidates = fresh[:auto_limit]
        if not candidates and campaign.league:
            # Surface silent breakage: campaign pinned to a league the feed
            # no longer emits (renamed/dropped) shows zero matches.
            league_slug = slugify_league(campaign.league)
            logger.warning(
                f"auto campaign /r/{campaign.slug}.png: 0 matches after "
                f"league filter (sport={campaign.sport} league={campaign.league!r} "
                f"slug={league_slug!r})"
            )
        return candidates

    # mode == "manual" — editor's selection in order
    repo = CampaignRepository(session)
    matches = repo.get_matches(campaign.slug)
    return [
        m for m in matches
        if m.is_active and not m.is_synthetic
        and not is_past_kickoff_cutoff(m, now, hide_hours)
    ]


def manual_render_stats(matches: List[Match]) -> Dict[str, Any]:
    """Bucket a manual campaign's selected matches by why each one would
    or wouldn't render in the public PNG. Used by the campaign list +
    edit page to warn the operator BEFORE they ship.

    Returns:
      total                  Selected matches (regardless of state)
      renderable             Active + not synthetic — go to the PNG
      inactive               is_active=False — parser dropped from feed
      synthetic              is_synthetic=True — hidden as virtual/replay
      will_render_blank      True if total > 0 but renderable == 0
    """
    total = len(matches)
    renderable = sum(1 for m in matches if m.is_active and not m.is_synthetic)
    inactive = sum(1 for m in matches if not m.is_active)
    synthetic = sum(1 for m in matches if m.is_active and m.is_synthetic)
    return {
        "total": total,
        "renderable": renderable,
        "inactive": inactive,
        "synthetic": synthetic,
        "will_render_blank": total > 0 and renderable == 0,
    }



# ── Endpoint ───────────────────────────────────────────────────────────
# 600 req/min/IP is generous enough for legitimate email-open spikes from
# corporate networks (often many users behind one NAT) but stops scrapers.
@router.get("/r/{slug}.png")
@limiter.limit("600/minute")
def render_campaign_png(
    slug: str, request: Request, limit: Optional[int] = None
) -> Response:
    slug = slug.strip().lower()
    if not SLUG_RE.match(slug):
        return _png_response(TRANSPARENT_PNG_1X1, cache_status="BAD_SLUG", status_code=404)

    # Key the cache on the *requested* limit (None → "def"); the effective
    # count for "def" comes from the campaign's stored hot_limit, resolved
    # after the DB lookup below.
    cache_key = f"{slug}:{limit if limit is not None else 'def'}"

    cached = _cache_get(cache_key)
    if cached is not None:
        _record_hit(slug, request)
        return _png_response(cached, cache_status="HIT")

    with db_session() as session:
        campaign = CampaignRepository(session).find_by_slug(slug)

        if campaign is None or not campaign.enabled:
            logger.info(f"campaign /r/{slug}.png missing/disabled → 1x1")
            return _png_response(TRANSPARENT_PNG_1X1, cache_status="MISS", status_code=404)

        if campaign.expires_at and campaign.expires_at < datetime.utcnow():
            logger.info(f"campaign /r/{slug}.png expired → 1x1")
            return _png_response(TRANSPARENT_PNG_1X1, cache_status="EXPIRED", status_code=410)

        # No explicit ?limit= → fall back to the campaign's saved default.
        auto_limit = _clamp_limit(limit if limit is not None else campaign.hot_limit)
        matches = _resolve_matches(session, campaign, auto_limit)
        events = [m.to_event_dict() for m in matches]
        sport = campaign.sport
        theme = "vip" if campaign.vip else "default"

    if not events:
        # No CTA, no redirect, no HTML — empty campaigns return a 1×1.
        return _png_response(TRANSPARENT_PNG_1X1, cache_status="EMPTY")

    try:
        png = render_for_sport(sport, events, theme=theme)
    except Exception:
        logger.exception(f"render failed for slug={slug}")
        return _png_response(TRANSPARENT_PNG_1X1, cache_status="ERROR", status_code=500)

    _cache_put(cache_key, png)
    _record_hit(slug, request)
    logger.info(f"rendered /r/{slug}.png mode={campaign.mode} matches={len(events)} sport={sport}")
    return _png_response(png, cache_status="MISS")


def _png_response(png: bytes, cache_status: str, status_code: int = 200) -> Response:
    """Build a Response with PNG bytes + no-cache headers (email clients re-fetch every open).

    `X-Deprecated` / `X-Migrate-To`: signals to monitoring + future
    middleware that this endpoint is being retired. Phase C will delete
    the campaigns surface entirely once the 90-day deprecation window
    has elapsed and traffic on /r/* has drained.
    """
    return Response(
        content=png,
        media_type="image/png",
        status_code=status_code,
        headers={
            "Cache-Control": "no-cache, no-store, must-revalidate",
            "Pragma": "no-cache",
            "Expires": "0",
            "X-Cache": cache_status,
            "X-Deprecated": "true",
            "X-Migrate-To": "/club/{slug}.png",
        },
    )
