#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import faulthandler as _faulthandler
import json as _json
import os
import re
import sys as _sys
import threading
import time

# Dump a Python traceback for every thread on segfault/abort/timeout.
# Without this, a Playwright Node-subprocess death silently kills uvicorn
# with no diagnostic. Writes to stderr.
_faulthandler.enable(_sys.stderr)

# Catch uncaught exceptions in background threads. Without this, an EPIPE
# bubbling out of Playwright's internal IPC thread is logged via Python's
# default `sys.excepthook`, which writes to a stderr that may already be
# closed by then — so it disappears silently and looks like a clean
# process exit. Print to plain stdout with flush so the diagnostic
# survives even when the process is moments from death.
def _thread_excepthook(args) -> None:
    import traceback as _tb
    msg = "".join(_tb.format_exception(args.exc_type, args.exc_value, args.exc_traceback))
    try:
        print(
            f"[THREAD-CRASH] thread={args.thread.name if args.thread else '?'}\n{msg}",
            flush=True,
        )
    except Exception:
        pass


threading.excepthook = _thread_excepthook

try:
    _sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")
    _sys.stderr.reconfigure(encoding="utf-8", errors="backslashreplace")
except Exception:
    pass

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import quote as _url_quote, unquote as _url_unquote
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup
from fastapi import Depends, FastAPI, HTTPException, Query, Response, Body
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

from weights_chile_first import FORCED_TIMEZONE
from hot_scoring import pick_hot as pick_hot_football
from hot_scoring_tennis import pick_hot as pick_hot_tennis
from hot_scoring_basketball import pick_hot as pick_hot_basketball
from hot_scoring_cybersport import pick_hot as pick_hot_cybersport
from hot_scoring_fights import pick_hot as pick_hot_fights
import manual_store

# New v2 admin (Phase 2+)
from app.routes.admin_views import router as admin_views_router
from app.routes.admin_api import router as admin_api_router
from app.routes.admin_campaigns import router as admin_campaigns_router
from app.routes.admin_clubs import router as admin_clubs_router
from app.routes.admin_cube import router as admin_cube_router
from app.routes.admin_hot import router as admin_hot_router
from app.routes.admin_hot_override import router as admin_hot_override_router
from app.routes.admin_logs import router as admin_logs_router
from app.routes.admin_weights import router as admin_weights_router
from app.routes.public_club import router as public_club_router
from app.routes.public_cube import router as public_cube_router
from app.routes.public_hot import router as public_hot_router
from app.routes.public_render import router as public_render_router
from app.auth.routes import router as auth_router
from app.auth.dependencies import require_login, require_role
from app.config import get_settings
from app.logging_config import get_logger
from app.middleware.security import SameOriginUnsafeMethodMiddleware, SecurityHeadersMiddleware
from app.routes.public_render import flush_hit_buffer
from app.parser.extra_feeds import build_extra_feed_map

logger = get_logger("server")
parser_logger = get_logger("app.parser.server")

# Rate-limiting (slowapi)
from slowapi.errors import RateLimitExceeded
from slowapi import _rate_limit_exceeded_handler
from app.middleware import limiter


# ====== CONFIG ======
SETTINGS = get_settings()
REFRESH_SECONDS = SETTINGS.parser_refresh_seconds
TIMEOUT_MS = SETTINGS.parser_timeout_ms
WAIT_SELECTOR = "div.event-card"
JS_SETTLE_MS = SETTINGS.parser_js_settle_ms

# Shorter ceilings for the two waits INSIDE a page fetch that block the
# pw-worker queue when a page legitimately has no events (off-hours live
# pages, empty sport markets). The PARSER_TIMEOUT_MS=30000 default makes
# every empty page eat 60s+ of queue time, behind which 13 other feeds
# wait. These caps keep an empty page to ~12s instead of ~60s so the
# single worker actually drains 16 URLs per cycle on a high-latency
# (VPN) link. `page.goto` still uses the full TIMEOUT_MS — only the
# in-page event/odds waits are capped.
SELECTOR_WAIT_MS = min(TIMEOUT_MS, 8000)
ODDS_WAIT_MS = min(TIMEOUT_MS, 5000)

# Base domain for relative URLs (/static/... and /events/...)
SITE_BASE = "https://jugabet.cl"

# Logo URL pattern — slug comes from data-event-competitors JSON attribute
LOGO_URL = "https://jugabet.cl/static/iolite/icons/{slug}.webp"

_CHILE_TZ = ZoneInfo(FORCED_TIMEZONE)
_MONTHS_ES = ["ene","feb","mar","abr","may","jun","jul","ago","sep","oct","nov","dic"]
# ====================

app = FastAPI(
    title="Jugabet Events JSON",
    version="2.0",
    docs_url=None if SETTINGS.is_production() else "/docs",
    redoc_url=None if SETTINGS.is_production() else "/redoc",
    openapi_url=None if SETTINGS.is_production() else "/openapi.json",
)

# Validate production security settings
if SETTINGS.is_production():
    SETTINGS.validate_production()


allowed_hosts = SETTINGS.allowed_host_list()
if allowed_hosts and "*" not in allowed_hosts:
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=allowed_hosts)
app.add_middleware(SameOriginUnsafeMethodMiddleware)
app.add_middleware(SecurityHeadersMiddleware)

# ─── Rate limiting (Phase 5) ──────────────────────────────────────────
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)


# ─── BUG-01 part 3: global exception handler ────────────────────────
# Any unhandled exception in a route returns 500 with a generic body
# instead of bubbling out and (in dev) crashing the process. FastAPI
# already does this for sync routes, but explicit registration also
# covers cases where a custom middleware would otherwise surface the
# raw stack trace.
from fastapi.requests import Request as _FRequest  # noqa: E402
from fastapi.responses import JSONResponse as _FJSONResponse  # noqa: E402


@app.exception_handler(Exception)
async def _global_exception_handler(request: _FRequest, exc: Exception):
    # Skip HTTPException — Starlette already maps it to a proper response.
    if isinstance(exc, HTTPException):
        raise exc
    logger.error(
        f"unhandled exception on {request.method} {request.url.path}: {exc}",
        exc_info=True,
    )
    return _FJSONResponse(status_code=500, content={"detail": "Internal server error"})

# ─── Mount the new admin (Phase 2+) ───────────────────────────────────
# Order matters: include these BEFORE legacy /admin so they take precedence.
# Auth routes (login/logout/2fa) MUST be registered before admin_views_router
# so /admin/login isn't caught by the protected admin layer.
app.include_router(auth_router)
app.include_router(admin_hot_override_router)  # /api/hot/override/* (Phase A JSON API)
app.include_router(admin_clubs_router)       # /api/admin/clubs/*  (Phase A JSON API)
app.include_router(admin_logs_router)
app.include_router(admin_campaigns_router)   # /admin/campaigns/* + campaign builder APIs
app.include_router(admin_hot_router)         # /admin/hot + legacy hot override UI APIs
app.include_router(admin_weights_router)     # /admin/weights + weights CRUD + leaderboard APIs
app.include_router(admin_cube_router)        # /admin/cube + /api/admin/cube/* override APIs
app.include_router(admin_views_router)       # /admin (dashboard), /admin/matches
app.include_router(admin_api_router)
app.include_router(public_hot_router)        # /hot, /hot/{sport}, /hot/{sport}.png
app.include_router(public_club_router)       # /club/{slug}.png only — no HTML route
app.include_router(public_cube_router)       # /cube, /cube/{theme}, /cube/{theme}.png
app.include_router(public_render_router)     # /r/{slug}.png (deprecated, 90-day window)

# Static files for the new admin (Tailwind config, custom CSS/JS)
from pathlib import Path as _P
_STATIC_DIR = _P(__file__).resolve().parent / "app" / "static"
if _STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")


@app.get("/robots.txt", include_in_schema=False)
def robots_txt() -> Response:
    """Keep crawlers out of the admin panel and JSON APIs. The stronger
    guarantee is the `X-Robots-Tag: noindex` header set on /admin responses
    (see SecurityHeadersMiddleware); this just stops polite crawlers up front."""
    body = "User-agent: *\nDisallow: /admin/\nDisallow: /api/\n"
    return Response(content=body, media_type="text/plain")


FEEDS: Dict[Tuple[str, str], str] = {
    ("football", "prematch"): "https://jugabet.cl/football/prematch/1",
    ("football", "live"): "https://jugabet.cl/football/live/1",

    ("cybersport", "prematch"): "https://jugabet.cl/cybersport/prematch/1",
    ("cybersport", "live"): "https://jugabet.cl/cybersport/live/1",

    ("tennis", "prematch"): "https://jugabet.cl/tennis/prematch/1",
    ("tennis", "live"): "https://jugabet.cl/tennis/live/1",

    ("basketball", "prematch"): "https://jugabet.cl/basketball/prematch/1",
    ("basketball", "live"): "https://jugabet.cl/basketball/live/1",

    ("boxing", "prematch"): "https://jugabet.cl/boxing/prematch/1",
    ("boxing", "live"): "https://jugabet.cl/boxing/live/1",

    ("mma", "prematch"): "https://jugabet.cl/mma/prematch/1",
    ("mma", "live"): "https://jugabet.cl/mma/live/1",

    ("ufc", "prematch"): "https://jugabet.cl/ufc/prematch/1",
    ("ufc", "live"): "https://jugabet.cl/ufc/live/1",

    # Football overlays: same /football/all/ endpoint, filtered by tournament
    # UUID. These re-scrape events already covered by ("football","prematch").
    # The first element of every FEEDS key is written verbatim to Match.sport,
    # so it MUST be a real sport name — `"mundo"` previously produced a
    # bogus sport='mundo' bucket in the DB. The second element is the mode;
    # downstream filters look for `mode IN ('live','prematch')`, so overlay
    # modes get the `prematch_` prefix and DB writes are skipped for them
    # (see persistence.persist_feed_results).
    ("football", "prematch_leagues_1"): "https://jugabet.cl/football/all/1?tournaments=fc7f16ba2ec24f528179d20490404fb5,013358a438324b18975b19aeef58684f,ddccbf1be9ef4c8195ae4645d793899f",
    ("football", "prematch_leagues_2"): "https://jugabet.cl/football/all/1?tournaments=607f74ae5f454fd9ab623c4dea0b6efe,28327faaa572400890d37048f3c93471,5216b26a50e947948e547c75254e6ac0",
    ("football", "prematch_leagues_3"): "https://jugabet.cl/football/all/1?tournaments=254e4ecf1eb84a73b37b9cedffac646d,0f7c91bcf24e4d62a76e7d9d3fee8177,966112317e2c4ee28d5a36df840662d6",
    ("football", "prematch_leagues_4"): "https://jugabet.cl/football/all/1?tournaments=3a963f83fe5440d58aac9a36dbe6ac2e,4230df881fd14f319c5499c86a7e647d,c19cb5ffb4404c31b869b53dd90161de",
    # Dedicated single-tournament feed for the FIFA World Cup 2026
    # tournament filter. The combined `prematch_leagues_4` feed only
    # surfaced ~5 matches from this filter when bundled with two other
    # tournament UUIDs (Jugabet caps the rendered list). A dedicated
    # feed against the same UUID alone returns the tournament's full
    # match list, which keeps the WC cube's auto-rank pool deep enough
    # to fill all 3 slots even after pins are applied.
    ("football", "prematch_worldcup_2026"): "https://jugabet.cl/football/all/1?tournaments=c19cb5ffb4404c31b869b53dd90161de",
}
FEEDS.update(build_extra_feed_map())


@dataclass
class FeedState:
    data: List[Dict[str, Any]]
    meta: Dict[str, Any]


_state_lock = threading.Lock()
_state: Dict[Tuple[str, str], FeedState] = {
    key: FeedState(
        data=[],
        meta={
            "ok": False,
            "error": "not loaded yet",
            "last_updated_epoch": None,
            "last_success_epoch": None,
            "source_url": url,
            "count": 0,
            "sport": key[0],
            "mode": key[1],
            "timezone": FORCED_TIMEZONE,
        },
    )
    for key, url in FEEDS.items()
}

_parser_sem = threading.BoundedSemaphore(max(1, SETTINGS.parser_max_concurrency))


def _norm_status(text: Optional[str]) -> str:
    if not text:
        return ""
    return " ".join(text.strip().lower().split())


def detect_status(
    event_stage_raw: Optional[str],
    time_status_classes: List[str],
    home_score: Optional[int],
    away_score: Optional[int],
) -> str:
    # 1) Primary source: explicit event stage from HTML
    stage = _norm_status(event_stage_raw)
    if stage in {"live", "prematch"}:
        return stage

    # 2) Secondary source: time-status classes
    classes = {_norm_status(c) for c in time_status_classes if c}
    if "time-status--live" in classes:
        return "live"
    if "time-status--prematch" in classes:
        return "prematch"

    # 3) Fallback: score presence
    return "live" if (home_score is not None and away_score is not None) else "prematch"


def to_int_or_none(text: Optional[str]) -> Optional[int]:
    if not text:
        return None
    s = text.strip()
    return int(s) if s.isdigit() else None


def make_abs_url(href_or_src: Optional[str]) -> Optional[str]:
    if not href_or_src:
        return None
    s = href_or_src.strip()
    if not s:
        return None
    if s.startswith("//"):
        return "https:" + s
    if s.startswith("/"):
        return SITE_BASE + s
    return s


def _title_from_slug(slug: Optional[str]) -> Optional[str]:
    if not slug:
        return None
    text = _url_unquote(str(slug)).replace("-", " ").replace("_", " ")
    return " ".join(part.capitalize() for part in text.split()) or None


def _event_parts_from_href(href: Optional[str]) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    """Return (event_id, home_slug, away_slug) from /events/home_away_123."""
    if not href:
        return None, None, None
    path = _url_unquote(str(href).split("?", 1)[0].rstrip("/"))
    m = re.search(r"/events/([^/_]+(?:-[^/_]+)*)_([^/_]+(?:-[^/_]+)*)_(\d+)$", path)
    if not m:
        return None, None, None
    home_slug, away_slug, event_id = m.group(1), m.group(2), m.group(3)
    return event_id, home_slug, away_slug


def clone_events_with_sport(events: List[Dict[str, Any]], sport: str) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for ev in events:
        item = dict(ev)
        item["sport"] = sport
        out.append(item)
    return out


# ---------------------------
# Market parsing helpers
# ---------------------------

_num_re = re.compile(r"(\d+(?:[.,]\d+)?)")
_manual_slot_re = re.compile(r"^[a-z0-9][a-z0-9_-]{1,63}$")


def _validate_manual_slot(slot: str) -> str:
    slot = (slot or "").strip().lower()
    if not _manual_slot_re.match(slot):
        raise HTTPException(400, "slot must be 2-64 lowercase letters, numbers, underscores, or hyphens")
    return slot


def _norm(text: Optional[str]) -> str:
    if not text:
        return ""
    t = text.strip().lower()
    t = " ".join(t.split())
    return t


def _extract_first_number(text: Optional[str]) -> Optional[str]:
    if not text:
        return None
    m = _num_re.search(text)
    if not m:
        return None
    n = m.group(1).strip()
    # normalize decimal comma -> dot for consistency
    n = n.replace(",", ".")
    return n or None


def _detect_market_type(market_name_raw: Optional[str]) -> str:
    name = _norm(market_name_raw)

    # 1X2 / Match result
    if name in {
        "resultado del partido (tiempo reglamentario)",
        "resultado del partido",
        "match result",
        "1x2",
    }:
        return "1x2"

    # Total (over/under)
    if name in {"total", "totales", "más/menos", "mas/menos", "over/under"}:
        return "total"

    # Winner (2-way)
    if "ganador" in name or "winner" in name:
        return "winner"

    return "unknown"


def _market_has_more_odds_link(market_container) -> bool:
    if not market_container:
        return False
    return market_container.select_one("a.outcome__more-odds") is not None


def _detect_total_side(outcome_name_raw: Optional[str]) -> str:
    n = _norm(outcome_name_raw)
    if "más de" in n or "mas de" in n or n == "over" or " over" in f" {n} ":
        return "over"
    if "menos de" in n or n == "under" or " under" in f" {n} ":
        return "under"
    return "unknown"


def _is_draw_name(name_raw: Optional[str]) -> bool:
    n = _norm(name_raw)
    if not n:
        return False
    # common draw labels
    if "empate" in n:
        return True
    if n in {"draw", "x"}:
        return True
    return False


def _names_match(a: Optional[str], b: Optional[str]) -> bool:
    if not a or not b:
        return False
    return _norm(a) == _norm(b)


def _parse_1x2(market_container, home_name: Optional[str], away_name: Optional[str]) -> Dict[str, Optional[str]]:
    if not market_container or _market_has_more_odds_link(market_container):
        return {
            "p1": None,
            "draw": None,
            "p2": None,
            "more_odds": bool(market_container and _market_has_more_odds_link(market_container)),
        }

    outcomes = market_container.select("div.outcome")
    triples: List[Tuple[Optional[str], Optional[str]]] = []  # (name, odd)

    for o in outcomes:
        # ignore title outcomes if any (usually for total)
        classes = o.get("class") or []
        if "outcome--title" in classes:
            continue

        odd_el = o.select_one("p.outcome__odd")
        if not odd_el:
            continue
        odd = odd_el.get_text(" ", strip=True).replace("\xa0", " ")
        if not odd:
            continue

        name_el = o.select_one("p.outcome__name")
        name = name_el.get_text(" ", strip=True) if name_el else None
        triples.append((name, odd))

    p1 = None
    draw = None
    p2 = None

    # prefer mapping by labels/names when possible
    for name, odd in triples:
        if _is_draw_name(name):
            draw = odd

    for name, odd in triples:
        if draw is not None and _is_draw_name(name):
            continue
        if p1 is None and _names_match(name, home_name):
            p1 = odd
        elif p2 is None and _names_match(name, away_name):
            p2 = odd

    # fallback: fill remaining by order (excluding draw)
    non_draw_odds: List[str] = []
    for name, odd in triples:
        if _is_draw_name(name):
            continue
        non_draw_odds.append(odd)

    if p1 is None and len(non_draw_odds) >= 1:
        p1 = non_draw_odds[0]
    if p2 is None:
        if len(non_draw_odds) >= 2:
            p2 = non_draw_odds[1]
        elif len(non_draw_odds) == 1 and p1 is None:
            p2 = non_draw_odds[0]

    # draw fallback (if 3 outcomes but label not recognized)
    if draw is None and len(triples) >= 3:
        # take the middle odd as draw (typical order) if p1/p2 set by order already
        draw = triples[1][1]

    return {"p1": p1, "draw": draw, "p2": p2, "more_odds": False}


def _parse_winner(market_container, home_name: Optional[str], away_name: Optional[str]) -> Dict[str, Optional[str]]:
    if not market_container:
        return {"p1": None, "p2": None, "more_odds": False}

    if _market_has_more_odds_link(market_container):
        return {"p1": None, "p2": None, "more_odds": True}

    outcomes = market_container.select("div.outcome")
    pairs: List[Tuple[Optional[str], str]] = []  # (name, odd)

    for o in outcomes:
        odd_el = o.select_one("p.outcome__odd")
        if not odd_el:
            continue
        odd = odd_el.get_text(" ", strip=True).replace("\xa0", " ")
        if not odd:
            continue
        name_el = o.select_one("p.outcome__name")
        name = name_el.get_text(" ", strip=True) if name_el else None
        pairs.append((name, odd))

    if len(pairs) == 0:
        return {"p1": None, "p2": None, "more_odds": False}
    if len(pairs) == 1:
        return {"p1": pairs[0][1], "p2": None, "more_odds": False}

    p1 = None
    p2 = None

    # prefer mapping to home/away by names
    for name, odd in pairs:
        if p1 is None and _names_match(name, home_name):
            p1 = odd
        elif p2 is None and _names_match(name, away_name):
            p2 = odd

    # fallback to order / fill gaps
    if p1 is None and p2 is None:
        p1 = pairs[0][1]
        p2 = pairs[1][1]
    else:
        if p1 is None:
            # choose first odd that isn't away
            for name, odd in pairs:
                if not _names_match(name, away_name):
                    p1 = odd
                    break
        if p2 is None:
            # choose first odd that isn't home
            for name, odd in pairs:
                if not _names_match(name, home_name):
                    p2 = odd
                    break

        # final fallback if still missing
        if p1 is None:
            p1 = pairs[0][1]
        if p2 is None:
            p2 = pairs[1][1]

    return {"p1": p1, "p2": p2, "more_odds": False}


def _score_total_candidate(c: Dict[str, Optional[str]]) -> int:
    score = 0
    if c.get("over") is not None:
        score += 2
    if c.get("under") is not None:
        score += 2
    if c.get("line") is not None:
        score += 1
    return score


def _parse_total(market_container) -> Dict[str, Optional[str]]:
    if not market_container:
        return {"line": None, "over": None, "under": None, "more_odds": False}

    if _market_has_more_odds_link(market_container):
        return {"line": None, "over": None, "under": None, "more_odds": True}

    rows = market_container.select("div.market__list-row-new")
    if not rows:
        rows = [market_container]

    candidates: List[Dict[str, Optional[str]]] = []

    for row in rows:
        line: Optional[str] = None
        over: Optional[str] = None
        under: Optional[str] = None

        title_el = row.select_one("div.outcome--title p.outcome__odd")
        if title_el:
            line = title_el.get_text(" ", strip=True).replace("\xa0", " ")
            if line:
                line = line.strip()

        outcomes = row.select("div.outcome")
        for o in outcomes:
            classes = o.get("class") or []
            if "outcome--title" in classes:
                continue

            odd_el = o.select_one("p.outcome__odd")
            if not odd_el:
                continue
            odd = odd_el.get_text(" ", strip=True).replace("\xa0", " ")
            if not odd:
                continue

            name_el = o.select_one("p.outcome__name")
            name = name_el.get_text(" ", strip=True) if name_el else ""

            if line is None:
                maybe_line = _extract_first_number(name)
                if maybe_line is not None:
                    line = maybe_line

            side = _detect_total_side(name)
            if side == "over":
                over = odd
            elif side == "under":
                under = odd

        candidates.append({"line": line, "over": over, "under": under})

    best: Optional[Dict[str, Optional[str]]] = None
    for c in candidates:
        if best is None:
            best = c
            continue
        if _score_total_candidate(c) > _score_total_candidate(best):
            best = c

    if best is None:
        return {"line": None, "over": None, "under": None, "more_odds": False}

    return {"line": best.get("line"), "over": best.get("over"), "under": best.get("under"), "more_odds": False}


def _fmt_odd(value: Any) -> Optional[str]:
    """Format a numeric odds price (e.g. 1.31) as a 2-decimal string for the
    renderers; pass clean strings through; None for missing."""
    if value is None:
        return None
    try:
        return f"{float(value):.2f}"
    except (TypeError, ValueError):
        s = str(value).strip()
        return s or None


def _parse_odds_from_json(
    event_id: str,
    market_type: str,
    api_data: Dict[str, Any],
    home_name: Optional[str],
    away_name: Optional[str]
) -> Optional[Dict[str, Any]]:
    event_odds = api_data.get(event_id)
    if not event_odds:
        return None
        
    items = event_odds.get("items") or []
    if not items:
        return None
        
    rows = items[0].get("rows") or []
    if not rows:
        return None
        
    cells = rows[0].get("cells") or []
    if not cells:
        return None

    if market_type == "1x2":
        p1 = None
        draw = None
        p2 = None
        for cell in cells:
            price = cell.get("price")
            trans = cell.get("translation") or ""
            outcome = cell.get("outcomeType")
            
            if outcome == 0:
                p1 = price
            elif outcome == 1:
                draw = price
            elif outcome == 2:
                p2 = price
            else:
                if _is_draw_name(trans):
                    draw = price
                elif _names_match(trans, home_name):
                    p1 = price
                elif _names_match(trans, away_name):
                    p2 = price
                    
        if p1 is None and len(cells) >= 1:
            p1 = cells[0].get("price")
        # Bug 7: only fall back to positional draw if the middle cell's name
        # actually looks like a draw. Some 1x2 variants emit cells in
        # [home, away, draw] order, in which case cells[1] is away — assigning
        # it to draw blindly leaks the wrong odds into the 'draw' slot.
        if draw is None and len(cells) >= 3:
            mid_trans = cells[1].get("translation") or ""
            if _is_draw_name(mid_trans):
                draw = cells[1].get("price")
        if p2 is None and len(cells) >= 2:
            p2 = cells[-1].get("price")
            
        return {"p1": p1, "draw": draw, "p2": p2, "more_odds": False}

    elif market_type == "winner":
        p1 = None
        p2 = None
        for cell in cells:
            price = cell.get("price")
            trans = cell.get("translation") or ""
            outcome = cell.get("outcomeType")
            
            if outcome == 0:
                p1 = price
            elif outcome == 3 or outcome == 2:
                p2 = price
            else:
                if _names_match(trans, home_name):
                    p1 = price
                elif _names_match(trans, away_name):
                    p2 = price
                    
        if p1 is None and len(cells) >= 1:
            p1 = cells[0].get("price")
        if p2 is None and len(cells) >= 2:
            p2 = cells[1].get("price")
            
        return {"p1": p1, "p2": p2, "more_odds": False}

    elif market_type == "total":
        over = None
        under = None
        line = None
        for cell in cells:
            price = cell.get("price")
            trans = cell.get("translation") or ""
            
            maybe_line = _extract_first_number(trans)
            if maybe_line is not None:
                line = maybe_line
                
            side = _detect_total_side(trans)
            if side == "over":
                over = price
            elif side == "under":
                under = price
                
        if over is None and len(cells) >= 1:
            over = cells[0].get("price")
        if under is None and len(cells) >= 2:
            under = cells[1].get("price")
            
        return {"line": line, "over": over, "under": under, "more_odds": False}
        
    return None


# Empirical correction for Jugabet's `data-time` HTML attribute.
#
# Jugabet emits times like "05/30/2026 16:00:00 +00:00". The "+00:00" label
# claims UTC, but the value is actually rendered in a UTC-5 timezone
# (likely the bookmaker's backend server, NOT the Chilean public site's
# UI). Result: every parsed match time was 5 hours behind reality —
# e.g. UCL Final "30 may, 17:00 Chile" stored as 16:00 UTC (=> displayed
# 12:00 Chile). Confirmed by the operator against the live site on
# 2026-05-28.
#
# We can't trust the offset label, so we accept the wall-clock part of
# the string and add this many hours to get true UTC.
#
# Set via env var JUGABET_DATA_TIME_OFFSET_HOURS if Jugabet ever fixes
# this or changes their backend timezone (e.g., +6 in northern winter
# if their server crosses a DST boundary we haven't modeled).
JUGABET_DATA_TIME_OFFSET_HOURS = int(
    os.environ.get("JUGABET_DATA_TIME_OFFSET_HOURS", "5")
)


def _parse_data_time(data_time: Optional[str]) -> Tuple[Optional[str], Optional[str]]:
    """
    Convert the HTML data-time attribute to (display_string, utc_iso).

    Input format: "05/19/2026 22:00:00 +00:00"
    display_string examples: "Hoy, 18:00" / "Mañana, 18:00" / "19 may, 18:00"
    utc_iso example: "2026-05-19T22:00:00+00:00"
    """
    if not data_time:
        return None, None
    try:
        dt_parsed = datetime.strptime(data_time.strip(), "%m/%d/%Y %H:%M:%S %z")
        # See JUGABET_DATA_TIME_OFFSET_HOURS docstring above.
        dt_utc = dt_parsed + timedelta(hours=JUGABET_DATA_TIME_OFFSET_HOURS)
        dt_cl = dt_utc.astimezone(_CHILE_TZ)
        now_cl = datetime.now(_CHILE_TZ)
        if dt_cl.date() == now_cl.date():
            display = f"Hoy, {dt_cl.strftime('%H:%M')}"
        elif dt_cl.date() == (now_cl + timedelta(days=1)).date():
            display = f"Mañana, {dt_cl.strftime('%H:%M')}"
        else:
            # Bug 11: append year when crossing the year boundary so a Jan 2
            # fixture viewed on Dec 30 doesn't display ambiguously as "2 ene".
            if dt_cl.year != now_cl.year:
                display = (
                    f"{dt_cl.day} {_MONTHS_ES[dt_cl.month - 1]} {dt_cl.year}, "
                    f"{dt_cl.strftime('%H:%M')}"
                )
            else:
                display = (
                    f"{dt_cl.day} {_MONTHS_ES[dt_cl.month - 1]}, "
                    f"{dt_cl.strftime('%H:%M')}"
                )
        return display, dt_utc.isoformat()
    except Exception:
        # Bug 5: don't leak the unparsed string as a display label. Returning
        # the raw data-time string silently lost start_time_utc (breaking
        # deactivate_expired) and surfaced ugly raw values in the UI.
        logger.warning(
            f"parser: failed to parse data-time {data_time!r}", exc_info=True
        )
        return None, None


def _parse_epoch_time(epoch_raw: Optional[str]) -> Tuple[Optional[str], Optional[str]]:
    if not epoch_raw:
        return None, None
    try:
        dt_utc = datetime.fromtimestamp(int(str(epoch_raw).strip()), tz=ZoneInfo("UTC"))
        dt_cl = dt_utc.astimezone(_CHILE_TZ)
        now_cl = datetime.now(_CHILE_TZ)
        if dt_cl.date() == now_cl.date():
            display = f"Hoy, {dt_cl.strftime('%H:%M')}"
        elif dt_cl.date() == (now_cl + timedelta(days=1)).date():
            display = f"MaÃ±ana, {dt_cl.strftime('%H:%M')}"
        elif dt_cl.year != now_cl.year:
            display = (
                f"{dt_cl.day} {_MONTHS_ES[dt_cl.month - 1]} {dt_cl.year}, "
                f"{dt_cl.strftime('%H:%M')}"
            )
        else:
            display = f"{dt_cl.day} {_MONTHS_ES[dt_cl.month - 1]}, {dt_cl.strftime('%H:%M')}"
        return display, dt_utc.isoformat()
    except Exception:
        logger.warning("parser: failed to parse epoch time %r", epoch_raw, exc_info=True)
        return None, None


# BUG-01/DEVOPS-02 root cause: the previous thread-local Playwright design
# spawned one Node-driver subprocess per parser thread. When 14+ threads
# raced to call `sync_playwright().start()` near-simultaneously, the Node
# driver IPC pipe broke with EPIPE in a background thread, taking the
# whole uvicorn process down (ERR_CONNECTION_REFUSED on every subsequent
# request). The Python-side asyncio loop cannot trap a foreign-thread
# EPIPE bubbling out of the Node pipe transport.
#
# Fix: one Playwright instance, one Browser, one dedicated worker thread
# that owns both. Every fetch goes through a queue + future; the parser
# threads never touch Playwright directly. Eliminates the multi-process
# race AND keeps the browser-reuse perf win from C4.
import queue as _queue
from concurrent.futures import Future as _Future, TimeoutError as _FutureTimeout

_pw_jobs: "_queue.Queue[Tuple[str, _Future]]" = _queue.Queue()
_pw_worker_started = False
_pw_worker_lock = threading.Lock()
_pw_worker_thread: Optional[threading.Thread] = None
# Watchdog uses this to detect a wedged worker: if the queue depth is
# non-zero AND nothing has dequeued for longer than PW_WORKER_STALL_SECONDS,
# the worker is presumed dead and a new one is started in its place.
#
# MUST be > per-fetch deadline. A single slow prematch fetch (full
# adaptive scroll + odds XHR + JS settle) can legitimately run for 60-90s,
# and `fetch_rendered_html` waits up to 600s on the Future. If the
# threshold is shorter, a slow-but-alive worker gets respawned while it's
# still running — two pw-worker threads then race `sync_playwright().start()`
# and EPIPE the Node driver, reproducing the original BUG-01 crash.
_pw_last_dequeue_at: float = 0.0
_pw_worker_stall_seconds = 900.0
_pw_fetches_since_browser_recycle = 0
_pw_browser_recycle_after_fetches = 50
_pw_active_job_url: Optional[str] = None
_pw_active_job_started_at: float = 0.0
_pw_jobs_enqueued = 0
_pw_jobs_completed = 0
_pw_jobs_failed = 0

# When Jugabet soft-blocks this host, feeds fetch quickly but parse zero usable
# matches. Back off per feed so the parser does not burn CPU/RAM hammering the
# same blocked pages while still preserving last-known DB data.
_soft_block_backoff_seconds = 15 * 60
_feed_backoff_until: Dict[Tuple[str, str], float] = {}
_feed_backoff_lock = threading.Lock()


def _pw_worker_loop() -> None:
    """Dedicated thread: owns Playwright + Browser for the process lifetime.

    Pops (url, future) jobs off the queue, runs the fetch, sets the result
    (or exception) on the future. Restarts Playwright in-place if the
    Node driver dies between jobs.

    Robustness goal: even a Chromium / Node-driver crash MUST stay
    contained in this loop. Without that, a foreign-thread EPIPE inside
    Playwright's IPC layer bubbles out of the Python interpreter and
    kills uvicorn (the original BUG-01 footprint). We catch BaseException
    around every Playwright touchpoint and force a full pw + browser tear
    down on any failure so the next job starts from a clean slate.
    """
    import traceback as _traceback

    global _pw_fetches_since_browser_recycle
    global _pw_active_job_url, _pw_active_job_started_at
    global _pw_jobs_completed, _pw_jobs_failed

    pw = None
    browser = None

    def _shutdown_pw() -> None:
        """Force-tear-down both browser AND pw. A broken Node driver requires
        restarting Playwright, not just the browser context."""
        nonlocal pw, browser
        try:
            if browser is not None:
                browser.close()
        except BaseException:
            pass
        browser = None
        try:
            if pw is not None:
                pw.stop()
        except BaseException:
            pass
        pw = None

    def _ensure_browser():
        nonlocal pw, browser
        if pw is None:
            print("[BROWSER] initializing sync_playwright()...", flush=True)
            parser_logger.info("pw-worker: initializing sync_playwright...")
            pw = sync_playwright().start()
            print("[BROWSER] sync_playwright started ok", flush=True)
        if browser is None or not browser.is_connected():
            try:
                if browser is not None:
                    browser.close()
            except Exception:
                pass
            print("[BROWSER] launching chromium headless...", flush=True)
            _launch_kwargs: Dict[str, Any] = {"headless": True}
            parser_logger.info("pw-worker: launching chromium headless browser (direct egress)...")
            browser = pw.chromium.launch(**_launch_kwargs)
            print("[BROWSER] chromium launched ok", flush=True)
        return browser

    global _pw_last_dequeue_at
    print("[BROWSER] pw-worker thread entered main loop", flush=True)
    while True:
        url, fut = _pw_jobs.get()
        _pw_last_dequeue_at = time.monotonic()
        if url is None:  # shutdown sentinel
            parser_logger.info("pw-worker: received shutdown sentinel, closing browser...")
            _shutdown_pw()
            try:
                fut.set_result(None)
            except Exception:
                pass
            return
        _pw_active_job_url = url
        _pw_active_job_started_at = time.monotonic()
        # BaseException — not just Exception — because Playwright can raise
        # GreenletExit / SystemExit / OSError from its IPC thread that we
        # don't want crashing the worker. KeyboardInterrupt is the one we
        # still want to propagate; handle it explicitly.
        try:
            br = _ensure_browser()
            print(f"[BROWSER] Fetching url={url}...", flush=True)
            parser_logger.info(f"pw-worker: starting fetch for url={url}")
            html, api_data = _do_fetch(br, url)
            fut.set_result((html, api_data))
            _pw_jobs_completed += 1
            _pw_fetches_since_browser_recycle += 1
            print(f"[BROWSER] Fetch completed successfully for url={url}", flush=True)
            parser_logger.info(f"pw-worker: fetch completed successfully for url={url}")
            if _pw_fetches_since_browser_recycle >= _pw_browser_recycle_after_fetches:
                parser_logger.info(
                    "pw-worker: recycling chromium after %s successful fetches",
                    _pw_fetches_since_browser_recycle,
                )
                print(
                    f"[BROWSER] recycling chromium after {_pw_fetches_since_browser_recycle} fetches",
                    flush=True,
                )
                try:
                    if browser is not None:
                        browser.close()
                except Exception:
                    parser_logger.warning("pw-worker: browser recycle close failed", exc_info=True)
                browser = None
                _pw_fetches_since_browser_recycle = 0
        except KeyboardInterrupt:
            try:
                fut.set_exception(KeyboardInterrupt())
            except Exception:
                pass
            _pw_jobs_failed += 1
            _shutdown_pw()
            raise
        except BaseException as e:
            # NEVER call `pw.stop()` from inside the worker loop — it
            # doesn't synchronously drain pending event emissions on the
            # Node side and dying CRBrowserContexts will EPIPE the pipe
            # transport, taking uvicorn with them (the original BUG-01).
            #
            # Recovery strategy:
            #   * transient page/context errors → close `browser`, reuse
            #     `pw`. Next fetch relaunches Chromium under the same
            #     driver. Cheap, common path.
            #   * driver-dead errors (`Connection closed while reading
            #     from the driver`, `Target browser has been closed`,
            #     etc) → EXIT THE LOOP. The outer `_pw_worker_loop_safe`
            #     guard clears `_pw_worker_started` so the feed watchdog
            #     spawns a fresh worker thread with a fresh `pw`. The
            #     OS reaps the dead Node subprocess.
            tb = _traceback.format_exc()
            print(
                f"[BROWSER] Fetch failed for url={url}: {type(e).__name__}: {e}\n{tb}",
                flush=True,
            )
            try:
                if browser is not None:
                    browser.close()
            except Exception:
                pass
            browser = None
            if isinstance(e, PlaywrightTimeoutError):
                parser_logger.warning(f"pw-worker: timeout fetching {url}")
            else:
                parser_logger.exception(f"pw-worker: fetch failed for {url}")
            try:
                fut.set_exception(e if isinstance(e, Exception) else RuntimeError(str(e)))
            except Exception:
                pass
            _pw_jobs_failed += 1

            # Detect "driver / pw is dead beyond recovery" and exit the
            # loop so a fresh worker can take over. Without this, every
            # subsequent fetch loops forever on the same
            # "Connection closed while reading from the driver" error.
            err_text = (str(e) or "").lower()
            DRIVER_DEAD_SIGNS = (
                "connection closed while reading from the driver",
                "browser.launch:",          # any error reaching Chromium
                "browsertype.launch:",      # specific launch failure
                "playwright has been closed",
                "transport endpoint is not connected",
            )
            if any(s in err_text for s in DRIVER_DEAD_SIGNS):
                parser_logger.error(
                    "pw-worker: driver appears dead (%s) — exiting loop "
                    "for clean respawn by watchdog",
                    type(e).__name__,
                )
                print(
                    f"[BROWSER] driver appears dead — exiting loop for respawn",
                    flush=True,
                )
                # Important: do NOT call pw.stop() here. Just abandon
                # the dead pw reference; the OS will reap the Node
                # subprocess. pw.stop() would try to flush events
                # through the dead pipe and EPIPE.
                return
        finally:
            _pw_active_job_url = None
            _pw_active_job_started_at = 0.0


def _pw_worker_loop_safe() -> None:
    """Outer crash-guard around `_pw_worker_loop`.

    If the loop returns (sentinel / driver-dead) or raises, log loudly
    so the watchdog can respawn instead of the failure being silent.
    Without this, a fatal Playwright error would just kill the thread
    and every feed would block at `fut.result(timeout=600)` with no
    diagnostic.

    On exit, immediately spawn a successor instead of waiting up to 60s
    for the feed watchdog to notice — only if it wasn't the shutdown
    sentinel that asked us to leave.
    """
    import traceback as _traceback
    sentinel_exit = False
    try:
        _pw_worker_loop()
        # _pw_worker_loop returned normally — either shutdown sentinel
        # or driver-dead bail-out. We can't easily distinguish those two
        # here, so let `_release_parser_lock_active` decide: if the
        # parser lock is still held, we're in normal operation and
        # should respawn. If not, we're shutting down.
        sentinel_exit = not _PARSER_PID_HELD
    except BaseException:
        tb = _traceback.format_exc()
        print(f"[BROWSER] pw-worker thread CRASHED:\n{tb}", flush=True)
        parser_logger.error("pw-worker thread crashed:\n%s", tb)
    finally:
        global _pw_worker_started
        with _pw_worker_lock:
            _pw_worker_started = False
        if sentinel_exit:
            print("[BROWSER] pw-worker thread exited (shutdown)", flush=True)
        else:
            print(
                "[BROWSER] pw-worker thread exited; spawning immediate replacement",
                flush=True,
            )
            # Give the OS ~500ms to reap the dead Node subprocess and
            # release any pipe handles before the new worker calls
            # `sync_playwright().start()`. Without this, the new
            # subprocess can occasionally inherit a stale pipe handle
            # on Windows.
            time.sleep(0.5)
            try:
                _ensure_pw_worker()
            except Exception:
                parser_logger.exception(
                    "pw-worker: immediate respawn failed; "
                    "feed watchdog will retry within 60s"
                )


def _ensure_pw_worker() -> None:
    global _pw_worker_started, _pw_worker_thread, _pw_last_dequeue_at
    with _pw_worker_lock:
        if _pw_worker_started and _pw_worker_thread is not None and _pw_worker_thread.is_alive():
            return
        t = threading.Thread(target=_pw_worker_loop_safe, name="pw-worker", daemon=True)
        t.start()
        _pw_worker_thread = t
        _pw_worker_started = True
        _pw_last_dequeue_at = time.monotonic()


def _pw_worker_is_wedged() -> bool:
    """True if there are jobs queued but the worker hasn't dequeued in a while.

    Returning True triggers a forced respawn from the feed watchdog. Two
    independent failure modes are covered:
      * worker thread died silently (handle.is_alive() is False)
      * worker thread is blocked on a wedged Chromium pipe (queue grows but
        _pw_last_dequeue_at stays frozen)
    """
    t = _pw_worker_thread
    if t is None or not t.is_alive():
        return True
    if _pw_jobs.qsize() == 0:
        return False
    age = time.monotonic() - _pw_last_dequeue_at
    return age > _pw_worker_stall_seconds


def _do_fetch(browser, url: str) -> Tuple[str, Dict[str, Any]]:
    """Runs on the pw-worker thread. Owns the page lifecycle for one URL."""
    api_data: Dict[str, Any] = {}
    context = browser.new_context(
        ignore_https_errors=False,
        timezone_id=FORCED_TIMEZONE,
        user_agent=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        locale="es-CL",
    )
    try:
        page = context.new_page()

        def handle_response(response):
            url_lower = response.url.lower()
            # [TEMP DIAGNOSTIC — safe to remove] Print every JSON/API XHR the
            # browser sees (url + status + body length) to stdout
            # (-> app.stdout.log), so we can read jugabet's CURRENT odds
            # endpoint directly and tell "they moved the endpoint" apart from
            # "IP soft-block". No behavior change; logs only.
            try:
                _ct = (response.headers or {}).get("content-type", "")
                if ("json" in _ct) or any(
                    _s in url_lower for _s in ("filter", "odds", "market", "graphql", "/api")
                ):
                    try:
                        _blen = len(response.body() or b"")
                    except Exception:
                        _blen = -1
                    print(f"[XHR] {response.status} len={_blen} {response.url}", flush=True)
            except Exception:
                pass
            if "by-market-filter" in url_lower or "by-sport-filter" in url_lower:
                try:
                    data = response.json()
                    if isinstance(data, dict) and data:
                        api_data.update(data)
                        parser_logger.debug(f"pw-worker: intercepted odds data from {response.url}")
                    elif isinstance(data, dict):
                        # HTTP 200 with an empty `{}` odds body is jugabet's
                        # anti-bot soft-block signature (datacenter IP). Surface
                        # it; refresh_once treats a cycle with no odds as degraded
                        # rather than committing a silent zero.
                        parser_logger.warning(
                            f"parser: empty odds body (HTTP {response.status}) from "
                            f"{response.url} — possible anti-bot soft-block"
                        )
                except Exception:
                    parser_logger.warning(
                        f"parser: failed to parse JSON response url={response.url}",
                        exc_info=True,
                    )

        page.on("response", handle_response)

        # Inject EventSource interceptor BEFORE page load so we capture every
        # SSE message Jugabet pushes (Jugabet v2 delivers odds via SSE, not XHR).
        # We override window.EventSource to proxy all messages into
        # window._sseMessages[], which we read back via page.evaluate() after
        # the page has settled.
        _SSE_SHIM = """
        (function() {
            if (window._sseShimInstalled) return;
            window._sseShimInstalled = true;
            window._sseMessages = [];
            const OrigES = window.EventSource;
            if (!OrigES) return;
            window.EventSource = function(url, opts) {
                const es = new OrigES(url, opts);
                const capture = (e) => {
                    try { window._sseMessages.push({url: url, data: e.data, type: e.type}); }
                    catch(ex) {}
                };
                es.addEventListener('message', capture);
                es.onmessage = es.onmessage;  // keep existing handler
                // Also capture named event types Jugabet might use
                ['odds','update','outcome','market','event'].forEach(t => {
                    es.addEventListener(t, capture);
                });
                return es;
            };
            Object.assign(window.EventSource, OrigES);
        })();
        """
        page.add_init_script(_SSE_SHIM)

        # Jugabet v2 streams live odds over a Centrifugo WebSocket
        # (wss://.../realtime/connection/websocket) on a per-user "web_outcomes_*"
        # channel — NOT the DOM, NOT SSE. Listen to the socket the Angular app
        # opens and collect the result market's outcomes (marketType == 2) per
        # event: outcomeType 0=home, 1=draw, 3=away (per /api/v1/sport/layout
        # selectionIds [0,1,3]). Keyed by eventId, which parse_html extracts
        # from the card, so the odds attach straight onto each match.
        ws_outcomes_by_event: Dict[str, Dict[int, Any]] = {}

        def _on_ws(ws):
            def _on_frame(payload):
                try:
                    text = payload if isinstance(payload, str) else payload.decode("utf-8", "ignore")
                except Exception:
                    return
                if "customizedOutcome" not in text:
                    return
                for line in text.split("\n"):
                    line = line.strip()
                    if not line or '"push"' not in line:
                        continue
                    try:
                        co = _json.loads(line)["push"]["pub"]["data"]["data"]["customizedOutcome"]
                    except Exception:
                        continue
                    if not isinstance(co, dict) or co.get("marketType") != 2:
                        continue
                    eid = str(co.get("eventId") or "").strip()
                    ot = co.get("outcomeType")
                    price = co.get("price")
                    if not eid or ot is None or price is None or not co.get("isOpen", True):
                        continue
                    ws_outcomes_by_event.setdefault(eid, {})[ot] = price
            try:
                ws.on("framereceived", _on_frame)
            except Exception:
                pass

        page.on("websocket", _on_ws)

        page.goto(url, wait_until="domcontentloaded", timeout=TIMEOUT_MS)

        # Two-phase Angular-aware wait.
        _ANGULAR_SHELL_SELECTOR = "app-sport-events-widget"
        _ANGULAR_SHELL_WAIT_MS  = 8_000
        _CARD_HYDRATION_WAIT_MS = 25_000

        shell_found = False
        try:
            page.wait_for_selector(_ANGULAR_SHELL_SELECTOR, timeout=_ANGULAR_SHELL_WAIT_MS)
            shell_found = True
            parser_logger.info("pw-worker: Angular shell (app-sport-events-widget) found")
        except PlaywrightTimeoutError:
            parser_logger.warning(
                "pw-worker: Angular shell not found within %dms on %s",
                _ANGULAR_SHELL_WAIT_MS, url,
            )

        card_wait_ms = _CARD_HYDRATION_WAIT_MS if shell_found else SELECTOR_WAIT_MS
        cards_found = False
        try:
            page.wait_for_selector(WAIT_SELECTOR, timeout=card_wait_ms)
            cards_found = True
            parser_logger.info(
                "pw-worker: found selector '%s' (shell_found=%s, waited≤%dms)",
                WAIT_SELECTOR, shell_found, card_wait_ms,
            )
        except PlaywrightTimeoutError:
            parser_logger.warning(
                "pw-worker: selector '%s' not found after %dms on %s",
                WAIT_SELECTOR, card_wait_ms, url,
            )

        # Phase 3 — wait for odds to be populated in the DOM.
        # Jugabet v2 uses SSE (EventSource) to push odds after cards render.
        # We wait up to 20s for p.outcome__odd to appear; if it shows up we know
        # SSE data arrived and odds are now in the DOM. If it times out either
        # SSE is blocked for this IP or the page has no markets.
        _ODDS_DOM_WAIT_MS = 20_000
        odds_in_dom = False
        if cards_found:
            try:
                page.wait_for_selector("p.outcome__odd", timeout=_ODDS_DOM_WAIT_MS)
                odds_in_dom = True
                parser_logger.info("pw-worker: odds found in DOM via SSE (p.outcome__odd visible)")
            except PlaywrightTimeoutError:
                parser_logger.warning(
                    "pw-worker: no p.outcome__odd after %dms — SSE may be blocked for this IP "
                    "or page has no markets; reading HTML anyway", _ODDS_DOM_WAIT_MS,
                )

        # Also wait for XHR odds response (legacy path — still try it).
        try:
            parser_logger.info("pw-worker: waiting for odds XHR responses...")
            with page.expect_response(
                lambda r: (
                    "by-market-filter" in r.url.lower()
                    or "by-sport-filter" in r.url.lower()
                ),
                timeout=ODDS_WAIT_MS,
            ):
                pass
        except PlaywrightTimeoutError:
            parser_logger.debug("pw-worker: timeout/no odds XHR response")

        # Collect any SSE messages captured by the shim.
        try:
            sse_msgs = page.evaluate("window._sseMessages || []")
            if sse_msgs:
                parser_logger.info(
                    "pw-worker: captured %d SSE messages from EventSource shim", len(sse_msgs)
                )
                for msg in sse_msgs:
                    try:
                        import json as _json_sse
                        data = _json_sse.loads(msg.get("data") or "{}")
                        if isinstance(data, dict) and data:
                            api_data.update(data)
                    except Exception:
                        pass
        except Exception:
            parser_logger.debug("pw-worker: SSE shim read failed (non-fatal)", exc_info=True)

        # Bug 6: adaptive scroll — keep paging until the event-card count plateaus.
        url_lower = url.lower()
        if "prematch" in url_lower or "/all" in url_lower:
            prev_count = -1
            for i in range(20):
                try:
                    count = page.evaluate(
                        "document.querySelectorAll('div.event-card').length"
                    )
                    parser_logger.info(f"pw-worker: adaptive scroll {i+1}/20 cards={count}")
                    if count == prev_count:
                        break
                    prev_count = count
                    page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                    page.wait_for_timeout(800)
                except Exception:
                    break

        # Give the WebSocket a moment to push odds for the cards revealed by
        # the scroll, then fold them into api_data keyed by event_id so
        # parse_html can attach them. {event_id: {outcomeType: price}}.
        page.wait_for_timeout(max(JS_SETTLE_MS, 3000))
        if ws_outcomes_by_event:
            parser_logger.info(
                "pw-worker: collected WS odds for %d events", len(ws_outcomes_by_event)
            )
            for _eid, _outs in ws_outcomes_by_event.items():
                _cur = api_data.get(_eid)
                if isinstance(_cur, dict):
                    _cur["ws_outcomes"] = _outs
                else:
                    api_data[_eid] = {"ws_outcomes": _outs}
        else:
            parser_logger.info("pw-worker: no WS odds captured for %s", url)

        html = page.content()
        try:
            rendered_cards = page.locator("div.event-card").evaluate_all(
                "(cards) => cards.map((card) => card.outerHTML)"
            )
            if rendered_cards:
                html = (
                    "<html><body>"
                    + "\n".join(str(card) for card in rendered_cards)
                    + "</body></html>"
                )
                parser_logger.info(
                    "pw-worker: serialized %s Playwright-visible event cards",
                    len(rendered_cards),
                )
        except Exception:
            parser_logger.warning("parser: failed to serialize rendered event cards", exc_info=True)
        if _looks_like_geo_restriction(html):
            raise RuntimeError(
                "Jugabet geo restriction page returned from this server egress"
            )
        return html, api_data
    finally:
        try:
            context.close()
        except Exception:
            parser_logger.warning("parser: context.close() failed", exc_info=True)




def fetch_rendered_html(url: str) -> Tuple[str, Dict[str, Any]]:
    """Submit a fetch job to the pw-worker thread and wait for the result."""
    global _pw_jobs_enqueued
    _ensure_pw_worker()
    q_before = _pw_jobs.qsize()
    _pw_jobs_enqueued += 1
    parser_logger.info(
        "fetch_rendered_html: queuing job for %s (queue_before=%s, enqueued=%s)",
        url,
        q_before,
        _pw_jobs_enqueued,
    )
    fut: _Future = _Future()
    _pw_jobs.put((url, fut))
    # Allow for queue depth: up to ~16 URLs × ~30s each worst case +
    # headroom. This is the deadline before the parser thread gives up,
    # NOT a per-fetch timeout (Playwright bounds the per-fetch part).
    try:
        res = fut.result(timeout=600)
    except _FutureTimeout as e:
        active_age = (
            time.monotonic() - _pw_active_job_started_at
            if _pw_active_job_started_at
            else None
        )
        parser_logger.error(
            "fetch_rendered_html: timed out waiting for %s "
            "(queue_size=%s, active_url=%s, active_age=%s)",
            url,
            _pw_jobs.qsize(),
            _pw_active_job_url,
            round(active_age, 1) if active_age is not None else None,
        )
        raise RuntimeError(
            "Playwright queue timed out after 600s waiting for "
            f"{url}; active_url={_pw_active_job_url}; "
            f"active_age_seconds={round(active_age, 1) if active_age is not None else None}; "
            f"queue_size={_pw_jobs.qsize()}"
        ) from e
    parser_logger.info(f"fetch_rendered_html: job completed for {url}")
    return res


def _set_feed_backoff(key: Tuple[str, str], seconds: int, reason: str) -> None:
    until = time.monotonic() + max(1, seconds)
    with _feed_backoff_lock:
        _feed_backoff_until[key] = until
    parser_logger.warning(
        "parser: backing off feed %s for %ss (%s)",
        key,
        seconds,
        reason,
    )


def _clear_feed_backoff(key: Tuple[str, str]) -> None:
    with _feed_backoff_lock:
        _feed_backoff_until.pop(key, None)


def _feed_backoff_remaining(key: Tuple[str, str]) -> float:
    with _feed_backoff_lock:
        until = _feed_backoff_until.get(key)
    if not until:
        return 0.0
    remaining = until - time.monotonic()
    if remaining <= 0:
        _clear_feed_backoff(key)
        return 0.0
    return remaining


def _looks_like_geo_restriction(html: str) -> bool:
    low = html.lower()
    return (
        "<title>restriction</title>" in low
        or "not available in your country" in low
        or "not available for players residing in this jurisdiction" in low
    )



def parse_html(html: str, api_data: Dict[str, Any] = None) -> List[Dict[str, Any]]:
    soup = BeautifulSoup(html, "html.parser")
    events: List[Dict[str, Any]] = []
    cards = soup.select("div.event-card")
    parser_logger.info(f"parse_html: found {len(cards)} event-card div elements in the page HTML")

    # One-time debug dump: write first card's raw HTML to /tmp so we can
    # inspect the current odds DOM structure without stopping the service.
    # Self-limits: only writes when file absent. Delete the file to refresh.
    _CARD_DEBUG_FILE = "/tmp/jugabet_first_card.html"
    if cards:
        import os as _os
        if not _os.path.exists(_CARD_DEBUG_FILE):
            try:
                with open(_CARD_DEBUG_FILE, "w", encoding="utf-8") as _f:
                    _f.write(str(cards[0]))
                parser_logger.info("parse_html: wrote first card HTML to %s", _CARD_DEBUG_FILE)
            except Exception:
                pass

    for card in cards:
        # --- event link ---
        a_el = card.select_one('a[data-id="event-card"]')
        if a_el is None:
            a_el = card.select_one('a.event-card__additional-info[href*="/events/"]')
        if a_el is None:
            a_el = card.select_one('a[href*="/events/"]')
        if a_el is None:
            a_el = card.find_parent("a", attrs={"data-id": "event-card"})
        event_href = make_abs_url(a_el.get("href") if a_el else None)
        href_event_id, href_home_slug, href_away_slug = _event_parts_from_href(event_href)

        event_id = card.get("data-event-card-id") or href_event_id
        if not event_id:
            parser_logger.debug("parse_html: event card has no event id, skipping")
            continue

        # --- status from data-event-stage attribute (most reliable source) ---
        status = (card.get("data-event-stage") or "").strip().lower()
        if status not in ("prematch", "live"):
            # fallback: check CSS class on time element
            time_el_cls = card.select_one("p.time-status")
            cls = time_el_cls.get("class") or [] if time_el_cls else []
            if "time-status--live" in cls:
                status = "live"
            else:
                status = "prematch"

        # --- team names + logo URLs from data-event-competitors JSON ---
        home_name: Optional[str] = None
        away_name: Optional[str] = None
        home_logo: Optional[str] = None
        away_logo: Optional[str] = None
        home_slug: Optional[str] = None
        away_slug: Optional[str] = None

        competitors_raw = card.get("data-event-competitors")
        if competitors_raw:
            try:
                comps = _json.loads(competitors_raw)
                if len(comps) >= 1:
                    home_name = comps[0].get("name")
                    home_slug = comps[0].get("slug") or None
                    if home_slug:
                        home_logo = LOGO_URL.format(slug=_url_quote(home_slug, safe=""))
                if len(comps) >= 2:
                    away_name = comps[1].get("name")
                    away_slug = comps[1].get("slug") or None
                    if away_slug:
                        away_logo = LOGO_URL.format(slug=_url_quote(away_slug, safe=""))
            except Exception:
                pass

        if href_home_slug and not home_slug:
            home_slug = href_home_slug
            home_name = home_name or _title_from_slug(home_slug)
            home_logo = home_logo or LOGO_URL.format(slug=_url_quote(home_slug, safe=""))
        if href_away_slug and not away_slug:
            away_slug = href_away_slug
            away_name = away_name or _title_from_slug(away_slug)
            away_logo = away_logo or LOGO_URL.format(slug=_url_quote(away_slug, safe=""))

        # fallback: old CSS class text parsing
        if not home_name or not away_name:
            blocks = card.select("div.competitors__competitor")
            if len(blocks) >= 2:
                def _name_from_block(b) -> Optional[str]:
                    el = b.select_one("span.competitors__name")
                    return el.get_text(" ", strip=True) if el else None
                home_name = home_name or _name_from_block(blocks[0])
                away_name = away_name or _name_from_block(blocks[1])
            if not home_name or not away_name:
                names = [n.get_text(" ", strip=True) for n in card.select("span.competitors__name")]
                if len(names) < 2:
                    continue
                home_name = home_name or names[0]
                away_name = away_name or names[1]

        if not home_name or not away_name:
            parser_logger.warning(f"parse_html: event {event_id} missing home or away competitor name, skipping")
            continue

        # --- start time from data-time attribute (ISO datetime, much better than text) ---
        time_raw: Optional[str] = None
        time_utc: Optional[str] = None
        time_el = card.select_one("[data-time]")
        if time_el and time_el.get("data-time"):
            time_raw, time_utc = _parse_data_time(time_el.get("data-time"))
        elif card.select_one("app-time-status[time]"):
            time_raw, time_utc = _parse_epoch_time(
                card.select_one("app-time-status[time]").get("time")
            )
        else:
            # fallback: read text from time-status paragraph
            p_time = card.select_one("p.time-status")
            time_raw = p_time.get_text(" ", strip=True) if p_time else None

        # --- tournament ---
        tournament_el = card.select_one("p.event-card__tournament")
        tournament_name = tournament_el.get_text(" ", strip=True) if tournament_el else None

        # --- live score ---
        home_score_el = card.select_one('[data-id="home-scoreboard-main"]')
        away_score_el = card.select_one('[data-id="away-scoreboard-main"]')
        home_score = to_int_or_none(home_score_el.get_text(" ", strip=True) if home_score_el else None)
        away_score = to_int_or_none(away_score_el.get_text(" ", strip=True) if away_score_el else None)

        # --- market + odds ---
        # Angular v2 removed data-lineup-id attributes. Try multiple selectors.
        market_name_el = (
            card.select_one('[data-lineup-id="market-name"]')
            or card.select_one('.event-card__market-name')
            or card.select_one('[class*="market-name"]')
            or card.select_one('[class*="market__name"]')
        )
        market_name_raw = market_name_el.get_text(" ", strip=True) if market_name_el else None
        market_type = _detect_market_type(market_name_raw)

        market_odds = None
        # Jugabet v2: the result-market odds come from the Centrifugo WebSocket,
        # collected in _do_fetch as api_data[event_id]["ws_outcomes"] =
        # {0: home, 1: draw, 3: away} (selection ids per /api/v1/sport/layout).
        # Build the market straight from that — authoritative over the DOM.
        _ev = api_data.get(event_id) if (api_data and event_id) else None
        _ws_out = _ev.get("ws_outcomes") if isinstance(_ev, dict) else None
        if _ws_out:
            _p1 = _ws_out.get(0)
            _draw = _ws_out.get(1)
            _p2 = _ws_out.get(3)
            if _p1 is not None or _p2 is not None:
                if _draw is not None:
                    market_odds = {
                        "p1": _fmt_odd(_p1), "draw": _fmt_odd(_draw),
                        "p2": _fmt_odd(_p2), "more_odds": False,
                    }
                    market_type = "1x2"
                else:
                    market_odds = {"p1": _fmt_odd(_p1), "p2": _fmt_odd(_p2), "more_odds": False}
                    market_type = "winner"

        if market_odds is None and api_data and event_id:
            market_odds = _parse_odds_from_json(event_id, market_type, api_data, home_name, away_name)

        if market_odds is None:
            # Try all known market container selectors (Angular v2 dropped data-lineup-id).
            market_container = (
                card.select_one('div.event-card__market [data-lineup-id="market-container"]')
                or card.select_one('[data-lineup-id="market-container"]')
                or card.select_one('div.event-card__market')
                or card.select_one('[class*="event-card__market"]')
                or card.select_one('[class*="market-container"]')
            )

            if market_type == "1x2":
                market_odds = _parse_1x2(market_container, home_name, away_name)
            elif market_type == "total":
                market_odds = _parse_total(market_container)
            elif market_type == "winner":
                market_odds = _parse_winner(market_container, home_name, away_name)
            else:
                if market_container and _market_has_more_odds_link(market_container):
                    market_odds = {"more_odds": True}
                elif market_container:
                    market_odds = {
                        "odds": [
                            n.get_text(" ", strip=True).replace("\xa0", " ")
                            for n in market_container.select("p.outcome__odd")
                        ][:10]
                    }
                else:
                    market_odds = {"odds": []}

            # Last-resort: if we still have no useful odds, scan the card
            # directly for outcome elements (Angular v2 may have removed all
            # container wrapper elements that the selectors above rely on).
            # Infer market type from outcome count: 3→1x2, 2→winner, other→raw.
            _needs_fallback = (
                not market_odds
                or (isinstance(market_odds, dict) and not any(
                    market_odds.get(k) for k in ("p1", "p2", "draw", "over", "under", "odds")
                ))
            )
            if _needs_fallback:
                _direct_outcomes = card.select("div.outcome, button.outcome")
                _direct_odds = []
                _direct_names = []
                for _o in _direct_outcomes:
                    _classes = _o.get("class") or []
                    if "outcome--title" in _classes:
                        continue
                    _odd_el = _o.select_one("p.outcome__odd")
                    _desc_el = _o.select_one("p.outcome__description, span.outcome__description")
                    _odd_val = _odd_el.get_text(" ", strip=True).replace("\xa0", " ") if _odd_el else None
                    _desc_val = _desc_el.get_text(" ", strip=True) if _desc_el else None
                    if _odd_val:
                        _direct_odds.append(_odd_val)
                        _direct_names.append(_desc_val)
                if _direct_odds:
                    parser_logger.info(
                        "parse_html: direct-outcome fallback for %s: found %d outcomes %s",
                        event_id, len(_direct_odds), _direct_odds,
                    )
                if len(_direct_odds) == 3:
                    # 1x2 — home / draw / away (positional)
                    _p1, _draw, _p2 = _direct_odds[0], _direct_odds[1], _direct_odds[2]
                    # If middle cell name is NOT draw-like, swap draw and p2
                    if _direct_names[1] and not _is_draw_name(_direct_names[1]):
                        _draw, _p2 = None, _direct_odds[2]
                    market_odds = {"p1": _p1, "draw": _draw, "p2": _p2, "more_odds": False}
                    if market_type == "unknown":
                        market_type = "1x2"
                elif len(_direct_odds) == 2:
                    market_odds = {"p1": _direct_odds[0], "p2": _direct_odds[1], "more_odds": False}
                    if market_type == "unknown":
                        market_type = "winner"
                elif len(_direct_odds) >= 1:
                    market_odds = {"odds": _direct_odds[:10]}


        parser_logger.info(
            f"parse_html: parsed match {event_id} | {home_name} vs {away_name} | "
            f"status={status} | start_time={time_raw} (utc={time_utc}) | "
            f"tournament={tournament_name} | market_type={market_type}"
        )

        events.append({
            "event_id": str(event_id),
            "href": event_href,
            "status": status,
            "time": {"raw": time_raw, "utc": time_utc},
            "tournament": {"name": tournament_name},
            "competitors": {
                "home": {"name": home_name, "logo": home_logo, "slug": home_slug},
                "away": {"name": away_name, "logo": away_logo, "slug": away_slug},
            },
            "score": {"home": home_score, "away": away_score},
            "market": {"name": market_name_raw, "type": market_type, "odds": market_odds},
        })

    parser_logger.info(f"parse_html: finished parsing events. Count={len(events)}")
    return events


def refresh_once(key: Tuple[str, str]) -> None:
    url = FEEDS[key]
    sport, mode = key
    print(f"[PARSER] Starting refresh for {sport}/{mode}...", flush=True)
    parser_logger.info(f"refresh_once: starting refresh for feed {key} using url {url}")
    attempt_epoch = int(time.time())
    with _state_lock:
        prev = _state[key]
        prev.meta = {
            **prev.meta,
            "ok": False,
            "error": "refresh in progress",
            "last_attempt_epoch": attempt_epoch,
            "source_url": url,
            "sport": sport,
            "mode": mode,
            "timezone": FORCED_TIMEZONE,
        }
        _state[key] = prev

    _parser_sem.acquire()
    try:
        html, api_data = fetch_rendered_html(url)
        data = parse_html(html, api_data)
        now_epoch = int(time.time())
        matches_n = len(data)

        if matches_n == 0:
            # Fetched, but nothing real came back. This is how an anti-bot
            # soft-block (empty odds XHR -> 0 matches) or a dead feed surfaces:
            # DO NOT claim ok or advance freshness, and DO NOT write to the DB
            # — a transient block must never deactivate/wipe rows (the 12h
            # deactivate_expired net still cleans up genuinely-finished
            # matches). Keep last-known data until the stale grace lapses.
            reason = (
                "empty odds response (possible anti-bot soft-block)"
                if not api_data
                else "0 matches parsed"
            )
            print(
                f"[PARSER] {sport}/{mode}: 0 matches ({reason}) — degraded, DB left unchanged",
                flush=True,
            )
            parser_logger.warning(
                f"refresh_once: feed {key} produced 0 matches ({reason}); marking "
                f"degraded, keeping last-known data, skipping DB write"
            )
            if not api_data:
                _set_feed_backoff(key, _soft_block_backoff_seconds, reason)
            with _state_lock:
                prev = _state[key]
                prev_success = prev.meta.get("last_success_epoch") or 0
                data_after = prev.data
                if prev_success and (now_epoch - prev_success) > STALE_FEED_GRACE_SECONDS:
                    data_after = []
                prev.data = data_after
                prev.meta = {
                    "ok": False,
                    "error": reason,
                    "empty": True,
                    "last_attempt_epoch": attempt_epoch,
                    "last_updated_epoch": now_epoch,
                    "last_success_epoch": prev_success,
                    "source_url": url,
                    "count": len(data_after),
                    "sport": sport,
                    "mode": mode,
                    "timezone": FORCED_TIMEZONE,
                }
                _state[key] = prev
            return

        _clear_feed_backoff(key)

        with _state_lock:
            _state[key] = FeedState(
                data=data,
                meta={
                    "ok": True,
                    "error": None,
                    "last_attempt_epoch": attempt_epoch,
                    "last_updated_epoch": now_epoch,
                    "last_success_epoch": now_epoch,
                    "source_url": url,
                    "count": matches_n,
                    "sport": sport,
                    "mode": mode,
                    "timezone": FORCED_TIMEZONE,
                },
            )

        # Concise terminal summary: real vs synthetic counts, no per-match
        # lines (those flood the cmd window — 16 feeds × dozens of matches
        # each cycle, most of which are virtual/replay/esports inventory
        # the operator doesn't care about).
        from app.utils.quality import is_synthetic_tournament as _is_syn
        n_synthetic = sum(
            1 for e in data if _is_syn((e.get("tournament") or {}).get("name"))
        )
        n_real = len(data) - n_synthetic
        print(
            f"[PARSER] Completed {sport}/{mode} | parsed {len(data)} matches "
            f"({n_real} real, {n_synthetic} synthetic) | committing to DB...",
            flush=True,
        )
        # Per-match detail goes only to the rotating log file — never to
        # stdout. Operators wanting per-match audit have `logs/app.log`.
        for e in data:
            home_name = e.get("competitors", {}).get("home", {}).get("name") or "Unknown"
            away_name = e.get("competitors", {}).get("away", {}).get("name") or "Unknown"
            t_name = e.get("tournament", {}).get("name") or "Unknown"
            event_id = e.get("event_id") or "Unknown"
            parser_logger.debug(
                "match %s | %s | %s vs %s",
                event_id, t_name, home_name, away_name,
            )
        parser_logger.info(f"refresh_once: feed {key} finished. Parsed {len(data)} matches. Committing to DB...")
        # ── Dual-write: persist to DB (best-effort, never fails the loop) ──
        try:
            from app.parser.persistence import persist_feed_results
            persist_feed_results(data, sport, mode)
        except Exception:
            # DB layer not yet initialized? Log and continue — legacy system unaffected.
            parser_logger.exception(f"parser: DB persist failed sport={sport} mode={mode}")

    except Exception as e:
        print(f"[PARSER] Failed refresh for {sport}/{mode}: {e}", flush=True)
        parser_logger.error(f"refresh_once: feed {key} failed: {e}", exc_info=True)
        err_text = str(e).lower()
        if (
            "geo restriction" in err_text
            or "soft-block" in err_text
            or "timeout" in err_text
            or "target closed" in err_text
        ):
            _set_feed_backoff(key, _soft_block_backoff_seconds, str(e))
        with _state_lock:
            prev = _state[key]
            now_epoch = int(time.time())
            last_success = prev.meta.get("last_success_epoch") or 0
            # Bug 10: if a feed has been failing for longer than
            # STALE_FEED_GRACE_SECONDS, blank the cached `data` so consumers
            # that ignore `ok=False` stop seeing zombie matches.
            stale_grace = STALE_FEED_GRACE_SECONDS
            data_after = prev.data
            if last_success and (now_epoch - last_success) > stale_grace:
                data_after = []
            prev.data = data_after
            prev.meta = {
                "ok": False,
                "error": str(e),
                "last_attempt_epoch": attempt_epoch,
                "last_updated_epoch": now_epoch,
                "last_success_epoch": last_success,
                "source_url": url,
                "count": len(prev.data),
                "sport": sport,
                "mode": mode,
                "timezone": FORCED_TIMEZONE,
            }
            _state[key] = prev
    finally:
        _parser_sem.release()


# Bug 10 grace window: after this many seconds without a successful fetch we
# blank a feed's cached data so consumers reading the in-memory state stop
# returning phantom matches from a long-broken upstream.
STALE_FEED_GRACE_SECONDS = 15 * 60


def _refresh_seconds_for(key: Tuple[str, str]) -> int:
    """Per-feed refresh cadence.

    Live odds change every minute or two on Jugabet's side; the default
    120s default is too slow for those. Prematch overlays (league filters)
    re-scrape data already covered by the primary prematch feed, so they
    can run on a slower cadence and still keep the DB fresh.

    The single pw-worker still serializes fetches, but adjusting the
    schedule changes WHICH feeds win arbitration when the queue is hot.
    """
    sport, mode = key
    if mode == "live":
        return max(30, min(REFRESH_SECONDS, 60))
    if mode.startswith("prematch_leagues"):
        return max(REFRESH_SECONDS, 240)
    return REFRESH_SECONDS


def refresh_loop(key: Tuple[str, str], initial_delay: float = 0.0) -> None:
    if initial_delay > 0:
        time.sleep(initial_delay)
    # Monotonic next-tick scheduling (C3). Old code did
    # `refresh_once(); sleep(REFRESH_SECONDS)` which made the effective cycle
    # period = REFRESH_SECONDS + fetch_time, accumulating phase drift between
    # sports. Now each tick fires REFRESH_SECONDS after the previous tick;
    # if a cycle overruns, the next tick fires immediately and we reset the
    # baseline to avoid death-spiral catch-up.
    cadence = _refresh_seconds_for(key)
    next_at = time.monotonic()
    while True:
        # Bug 9: refresh_once already swallows fetch/parse exceptions, but a
        # bug in the surrounding scheduling code (or an OOM, or a Playwright
        # protocol error escaping the inner handler) would kill the thread
        # silently. Wrap the loop body so the thread can't die.
        try:
            if key not in FEEDS:
                logger.info("parser: feed %s removed from rotation; thread idling", key)
                time.sleep(cadence)
                next_at = time.monotonic()
                continue
            backoff_remaining = _feed_backoff_remaining(key)
            if backoff_remaining > 0:
                logger.warning(
                    "parser: skipping feed %s for %.0fs due to upstream backoff",
                    key,
                    backoff_remaining,
                )
                time.sleep(min(backoff_remaining, cadence))
                next_at = time.monotonic()
                continue
            refresh_once(key)
        except Exception:
            logger.exception(f"parser: refresh_loop iteration crashed for {key}")
        next_at += cadence
        delay = next_at - time.monotonic()
        if delay > 0:
            time.sleep(delay)
        else:
            logger.warning(
                f"parser cycle overran for key={key} by {-delay:.1f}s; "
                f"resetting schedule"
            )
            next_at = time.monotonic()


import atexit
import os as _os
from pathlib import Path as _Path


def _pid_alive(pid: int) -> bool:
    """Cross-platform 'is this PID still running?' check.

    On Windows, `os.kill(pid, 0)` is **NOT** a no-op liveness probe — it
    calls `TerminateProcess(handle, 0)` which kills the target with exit
    code 0. Calling it on the uvicorn worker's own PID (which is exactly
    what the `/health` endpoint and `_acquire_parser_lock` do when the
    pidfile records *our own* pid) silently kills the whole server.
    Spent hours chasing this; it's the root cause of the recurring
    "process exits with no traceback, Node EPIPEs after" crash on the
    Windows dev box.

    Use `OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION)` on Windows —
    that's a true read-only check. On POSIX, the historical
    `os.kill(pid, 0)` behavior is the correct one.
    """
    if _sys.platform == "win32":
        import ctypes
        from ctypes import wintypes
        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        kernel32 = ctypes.windll.kernel32
        OpenProcess = kernel32.OpenProcess
        OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        OpenProcess.restype = wintypes.HANDLE
        CloseHandle = kernel32.CloseHandle
        CloseHandle.argtypes = [wintypes.HANDLE]
        h = OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, int(pid))
        if not h:
            return False
        try:
            # GetExitCodeProcess returns STILL_ACTIVE (259) for running
            # procs. We could check that too, but a non-NULL handle from
            # OpenProcess with PROCESS_QUERY_LIMITED_INFORMATION already
            # proves the process exists.
            return True
        finally:
            CloseHandle(h)
    try:
        _os.kill(int(pid), 0)
        return True
    except (ProcessLookupError, PermissionError, OSError):
        return False

# ── Parser singleton (C1): one parser per host, enforced via pidfile ──
# Without this, `uvicorn --workers 2+` would spawn duplicate parsers in
# each worker process → duplicate feed fetches + SQLite write contention.
_PARSER_PIDFILE = _Path(__file__).resolve().parent / "data" / "parser.pid"
_PARSER_PID_HELD = False


def _acquire_parser_lock() -> bool:
    """Return True if this process becomes the parser owner.

    Uses O_EXCL pidfile creation. If the file already exists, we check
    whether the recorded PID is still alive; if not, the file is stale
    and we reclaim it. Otherwise we refuse to spawn parser threads.
    """
    global _PARSER_PID_HELD
    print(f"[LOCK] _acquire_parser_lock entered (pid={_os.getpid()})", flush=True)
    _PARSER_PIDFILE.parent.mkdir(parents=True, exist_ok=True)
    my_pid = _os.getpid()
    try:
        fd = _os.open(str(_PARSER_PIDFILE), _os.O_CREAT | _os.O_EXCL | _os.O_WRONLY, 0o644)
        try:
            _os.write(fd, str(my_pid).encode("ascii"))
        finally:
            _os.close(fd)
        _PARSER_PID_HELD = True
        atexit.register(_release_parser_lock)
        print(f"[LOCK] new pidfile created for pid={my_pid}", flush=True)
        return True
    except FileExistsError:
        print(f"[LOCK] pidfile exists; checking if owner is alive", flush=True)
        # Check if the recorded pid is alive.
        # CRITICAL: use _pid_alive(), NOT os.kill(pid, 0). On Windows the
        # latter calls TerminateProcess(handle, 0) and kills the target,
        # which here would be either *us* (if the pidfile records our
        # own pid from a prior failed atexit) or a healthy unrelated
        # process that just happens to have the recycled pid.
        try:
            existing = int(_PARSER_PIDFILE.read_text().strip())
        except Exception:
            existing = None
        print(f"[LOCK] existing pid in pidfile = {existing}", flush=True)
        alive = bool(existing) and _pid_alive(existing)
        print(f"[LOCK] _pid_alive({existing}) returned {alive}", flush=True)
        if alive and existing != my_pid:
            logger.warning(
                f"parser singleton: pidfile held by pid={existing}, "
                f"this worker (pid={my_pid}) will NOT spawn parser threads"
            )
            return False
        # Stale pidfile (process died without atexit cleanup). Reclaim.
        logger.info(
            f"parser singleton: reclaiming stale pidfile (was pid={existing}, now pid={my_pid})"
        )
        try:
            _PARSER_PIDFILE.unlink(missing_ok=True)
        except Exception:
            pass
        return _acquire_parser_lock()


def _release_parser_lock() -> None:
    global _PARSER_PID_HELD
    if not _PARSER_PID_HELD:
        return
    try:
        _PARSER_PIDFILE.unlink(missing_ok=True)
    except Exception:
        logger.warning("parser singleton: failed to remove pidfile on exit", exc_info=True)
    _PARSER_PID_HELD = False


def _run_migrations_on_startup() -> None:
    """Apply `alembic upgrade head` before serving traffic.

    Fail-fast: if migrations can't run, the schema is almost certainly
    out of sync with the ORM and every request will explode anyway —
    crashing here gives a clear error instead of obscure runtime
    `OperationalError: no such column`.
    """
    from alembic import command as _alembic_cmd
    from alembic.config import Config as _AlembicCfg

    # Make sure the SQLite directory exists before Alembic tries to open it.
    db_url = SETTINGS.database_url
    if db_url.startswith("sqlite:///"):
        db_path = _Path(db_url.replace("sqlite:///", "", 1))
        db_path.parent.mkdir(parents=True, exist_ok=True)

    ini_path = _Path(__file__).resolve().parent / "alembic.ini"
    cfg = _AlembicCfg(str(ini_path))
    # env.py overrides this with settings.database_url, but set it here too
    # so offline tools (e.g. `alembic` CLI run from another cwd) still work.
    cfg.set_main_option("sqlalchemy.url", SETTINGS.database_url)
    _alembic_cmd.upgrade(cfg, "head")


# BUG-04: registry of feed threads + watchdog. We need to know which thread
# is responsible for each (sport, mode) key so the watchdog can detect a
# silently-dead thread and respawn it. The dict is keyed by FEEDS key.
_feed_threads: Dict[Tuple[str, str], threading.Thread] = {}
_feed_threads_lock = threading.Lock()


def _spawn_feed_thread(key: Tuple[str, str], initial_delay: float = 0.0) -> None:
    t = threading.Thread(
        target=refresh_loop, args=(key, initial_delay), name=f"feed-{key[0]}-{key[1]}",
        daemon=True,
    )
    t.start()
    with _feed_threads_lock:
        _feed_threads[key] = t


def sync_extra_parser_feeds() -> Dict[str, Any]:
    """Reload admin-managed feed links and start any new parser threads."""
    extra = build_extra_feed_map()
    extra_keys = set(extra.keys())
    existing_extra_keys = {key for key in FEEDS if "_extra_" in key[1]}
    added: List[str] = []
    removed: List[str] = []

    for key in existing_extra_keys - extra_keys:
        FEEDS.pop(key, None)
        removed.append(f"{key[0]}/{key[1]}")
        with _state_lock:
            _state.pop(key, None)
        _clear_feed_backoff(key)

    for key, url in extra.items():
        is_new = key not in FEEDS
        FEEDS[key] = url
        with _state_lock:
            if key not in _state:
                _state[key] = FeedState(
                    data=[],
                    meta={
                        "ok": False,
                        "error": "not loaded yet",
                        "last_updated_epoch": None,
                        "last_success_epoch": None,
                        "source_url": url,
                        "count": 0,
                        "sport": key[0],
                        "mode": key[1],
                        "timezone": FORCED_TIMEZONE,
                    },
                )
            else:
                _state[key].meta["source_url"] = url
        if is_new and _PARSER_PID_HELD:
            _spawn_feed_thread(key, initial_delay=0.0)
            added.append(f"{key[0]}/{key[1]}")

    parser_logger.info(
        "parser: synced extra feeds added=%s removed=%s total=%s",
        added,
        removed,
        len(extra),
    )
    return {"added": added, "removed": removed, "total": len(extra)}


def _feed_watchdog_loop() -> None:
    """Re-spawn any feed thread that has died or never produced a first fetch.

    Also revives the pw-worker if it has died or wedged — without this,
    every feed thread is silently parked on `fut.result(timeout=600)` and
    the system looks "fine" except no data is ever produced.

    A feed is considered dead when EITHER:
      * its thread object is missing or not alive, OR
      * meta.last_success_epoch is None AND the thread has been running for
        more than (3 * REFRESH_SECONDS) seconds (first fetch should have
        completed by then; if not, the thread is probably wedged).
    """
    global _pw_worker_started
    started_at = time.time()
    grace = REFRESH_SECONDS * 3
    while True:
        time.sleep(60)
        try:
            # pw-worker health: if dead or wedged, drop the started flag so
            # _ensure_pw_worker spawns a fresh one. The new worker may then
            # find a stale browser handle in its own scope and reinit
            # Playwright from scratch (the loop body already handles that).
            if _pw_worker_is_wedged():
                qsize = _pw_jobs.qsize()
                logger.warning(
                    f"watchdog: pw-worker appears wedged (qsize={qsize}); "
                    f"forcing respawn"
                )
                with _pw_worker_lock:
                    _pw_worker_started = False
                _ensure_pw_worker()

            with _state_lock:
                snap = {k: (s.meta.get("last_success_epoch"),
                            s.meta.get("last_updated_epoch"))
                        for k, s in _state.items()}
            with _feed_threads_lock:
                threads = dict(_feed_threads)
            now = time.time()
            for key in FEEDS:
                t = threads.get(key)
                alive = bool(t and t.is_alive())
                last_success, _last_attempt = snap.get(key, (None, None))
                stuck = (
                    last_success is None
                    and (now - started_at) > grace
                )
                if not alive or stuck:
                    logger.warning(
                        f"watchdog: respawning feed {key} "
                        f"(alive={alive}, last_success={last_success})"
                    )
                    _spawn_feed_thread(key, initial_delay=0.0)
        except Exception:
            logger.exception("watchdog iteration crashed")


@app.on_event("startup")
def startup() -> None:
    # Step-by-step diagnostic prints flush to stdout so we can see exactly
    # which step the process died on if startup is killed mid-flight.
    # A single missing marker tells us the failing line.
    print("[STARTUP] step 1/8: entering startup()", flush=True)
    SETTINGS.validate_production()
    print("[STARTUP] step 2/8: validate_production ok", flush=True)
    _run_migrations_on_startup()
    print("[STARTUP] step 3/8: migrations ok", flush=True)
    if not SETTINGS.parser_enabled:
        print("[STARTUP] parser disabled via settings; no feed threads", flush=True)
        logger.info("parser disabled via settings; not starting feed threads")
        return
    # The parser uses background threads inside THIS process. Without the
    # pidfile guard below, `uvicorn --workers N>1` would spawn one parser
    # per worker. The systemd unit hardcodes `--workers 1`, but the lock is
    # belt-and-braces in case that's ever changed by mistake.
    print(f"[STARTUP] step 4/8: acquiring parser lock (pidfile={_PARSER_PIDFILE})", flush=True)
    lock_ok = _acquire_parser_lock()
    print(f"[STARTUP] step 5/8: parser lock acquire result={lock_ok}", flush=True)
    if not lock_ok:
        print("[STARTUP] another instance holds the parser lock — skipping feed spawn", flush=True)
        return
    # BUG-01 fix: pre-start the dedicated Playwright worker BEFORE any feed
    # thread submits a fetch. Avoids a thundering-herd init race that
    # previously crashed the Node driver with EPIPE.
    print("[STARTUP] step 6/8: starting pw-worker thread...", flush=True)
    _ensure_pw_worker()
    print("[STARTUP] step 7/8: pw-worker spawned, scheduling feed threads...", flush=True)
    logger.info(f"parser: spawning {len(FEEDS)} feed threads (pid={_os.getpid()})")
    # Prioritize important live/league feeds. EVERY key here must exist in
    # FEEDS — otherwise `refresh_once` raises KeyError every cycle for the
    # ghost feed forever. ("nba","live") used to be listed here and isn't
    # a real feed; the resulting thread spammed the log indefinitely.
    _PRIORITY_FEEDS = {
        ("football", "live"),
        ("football", "prematch"),
        ("football", "prematch_leagues_1"),
        ("football", "prematch_leagues_2"),
        ("football", "prematch_leagues_3"),
        ("football", "prematch_leagues_4"),
        ("football", "prematch_worldcup_2026"),
        ("basketball", "live"),
        ("ufc", "live"),
    }
    # Defence in depth: drop any priority entry that isn't in FEEDS.
    _PRIORITY_FEEDS = {k for k in _PRIORITY_FEEDS if k in FEEDS}
    # Feed threads for priority feeds start with no delay; others are staggered.
    # Stagger by 0.5s instead of 2s so the rest of the rotation actually
    # gets a turn within a reasonable window — 8 staggered feeds at 2s
    # each = 16s before the last feed even submits its first job.
    sorted_keys = list(_PRIORITY_FEEDS) + [k for k in FEEDS.keys() if k not in _PRIORITY_FEEDS]
    for idx, key in enumerate(sorted_keys):
        delay = 0.0 if key in _PRIORITY_FEEDS else (idx - len(_PRIORITY_FEEDS)) * 0.5
        _spawn_feed_thread(key, initial_delay=max(0.0, delay))
    # BUG-04: watchdog respawns silently-dead feeds and surfaces stuck ones.
    threading.Thread(target=_feed_watchdog_loop, name="feed-watchdog", daemon=True).start()
    print(
        f"[STARTUP] step 8/8: ALL DONE. parser_threads={len(sorted_keys)} "
        f"pid={_os.getpid()}",
        flush=True,
    )


@app.on_event("shutdown")
def shutdown() -> None:
    flush_hit_buffer()
    # Tell the pw-worker to close its browser + stop Playwright cleanly
    # BEFORE the process exits. Without this, the Node driver subprocess
    # gets reaped mid-write and prints a "Unhandled 'error' event / EPIPE"
    # stack to stderr after the Python process is already gone. Harmless
    # but it looks exactly like a crash in journalctl. Best-effort: if the
    # worker is wedged, we still exit; the daemon thread is killed.
    try:
        if _pw_worker_started and _pw_worker_thread is not None and _pw_worker_thread.is_alive():
            _pw_jobs.put((None, _Future()))
            _pw_worker_thread.join(timeout=3.0)
    except Exception:
        parser_logger.warning("shutdown: pw-worker stop failed", exc_info=True)
    _release_parser_lock()


@app.get("/events/football/hot")
def football_hot(limit: int = Query(5, ge=1, le=10), debug: int = 0, resp: Response = None) -> Dict[str, Any]:
    """
    GET /events/football/hot?limit=5&debug=1
    """
    with _state_lock:
        live_state = _state.get(("football", "live"))
        prem_state = _state.get(("football", "prematch"))

        live_events = list(live_state.data) if live_state else []
        prem_events = list(prem_state.data) if prem_state else []
        
        leagues_events = []
        leagues_ok = False
        for (sport, mode), fstate in _state.items():
            if sport == "football" and mode.startswith("prematch_leagues"):
                if fstate:
                    leagues_events.extend(fstate.data)
                    if fstate.meta.get("ok"):
                        leagues_ok = True

        ok = bool(
            (live_state and live_state.meta.get("ok"))
            or (prem_state and prem_state.meta.get("ok"))
            or leagues_ok
        )

    # Deduplicate events by event_id
    seen_ids = set()
    combined_events = []
    for e in (live_events + prem_events + leagues_events):
        eid = e.get("event_id")
        if eid:
            if eid in seen_ids:
                continue
            seen_ids.add(eid)
        combined_events.append(e)

    payload = pick_hot_football(
        events=combined_events,
        limit=limit,
        timezone=FORCED_TIMEZONE,
        debug=bool(debug) and not SETTINGS.is_production(),
    )

    if resp is not None:
        resp.status_code = 200 if ok else 503

    return payload


@app.get("/events/tennis/hot")
def tennis_hot(limit: int = Query(5, ge=1, le=10), debug: int = 0, resp: Response = None) -> Dict[str, Any]:
    """
    GET /events/tennis/hot?limit=5&debug=1
    """
    with _state_lock:
        live_state = _state.get(("tennis", "live"))
        prem_state = _state.get(("tennis", "prematch"))

        live_events = list(live_state.data) if live_state else []
        prem_events = list(prem_state.data) if prem_state else []

        ok = bool((live_state and live_state.meta.get("ok")) or (prem_state and prem_state.meta.get("ok")))

    payload = pick_hot_tennis(
        events=(live_events + prem_events),
        limit=limit,
        timezone=FORCED_TIMEZONE,
        debug=bool(debug) and not SETTINGS.is_production(),
    )

    if resp is not None:
        resp.status_code = 200 if ok else 503

    return payload


@app.get("/events/basketball/hot")
def basketball_hot(limit: int = Query(5, ge=1, le=10), debug: int = 0, resp: Response = None) -> Dict[str, Any]:
    """
    GET /events/basketball/hot?limit=5&debug=1
    NOTE: Basketball HOT строго winner-only (market.type == "winner" + 2 odds required)
    """
    with _state_lock:
        live_state = _state.get(("basketball", "live"))
        prem_state = _state.get(("basketball", "prematch"))

        live_events = list(live_state.data) if live_state else []
        prem_events = list(prem_state.data) if prem_state else []

        ok = bool((live_state and live_state.meta.get("ok")) or (prem_state and prem_state.meta.get("ok")))

    payload = pick_hot_basketball(
        events=(live_events + prem_events),
        limit=limit,
        timezone=FORCED_TIMEZONE,
        debug=bool(debug) and not SETTINGS.is_production(),
    )

    if resp is not None:
        resp.status_code = 200 if ok else 503

    return payload


@app.get("/events/cybersport/hot")
def cybersport_hot(limit: int = Query(5, ge=1, le=10), debug: int = 0, resp: Response = None) -> Dict[str, Any]:
    """
    GET /events/cybersport/hot?limit=5&debug=1
    """
    with _state_lock:
        live_state = _state.get(("cybersport", "live"))
        prem_state = _state.get(("cybersport", "prematch"))

        live_events = list(live_state.data) if live_state else []
        prem_events = list(prem_state.data) if prem_state else []

        ok = bool((live_state and live_state.meta.get("ok")) or (prem_state and prem_state.meta.get("ok")))

    payload = pick_hot_cybersport(
        events=(live_events + prem_events),
        limit=limit,
        timezone=FORCED_TIMEZONE,
        debug=bool(debug) and not SETTINGS.is_production(),
    )

    if resp is not None:
        resp.status_code = 200 if ok else 503

    return payload


@app.get("/events/fights/hot")
def fights_hot(limit: int = Query(5, ge=1, le=10), debug: int = 0, resp: Response = None) -> Dict[str, Any]:
    with _state_lock:
        boxing_live_state = _state.get(("boxing", "live"))
        boxing_prem_state = _state.get(("boxing", "prematch"))
        mma_live_state = _state.get(("mma", "live"))
        mma_prem_state = _state.get(("mma", "prematch"))
        ufc_live_state = _state.get(("ufc", "live"))
        ufc_prem_state = _state.get(("ufc", "prematch"))

        boxing_live_events = clone_events_with_sport(list(boxing_live_state.data) if boxing_live_state else [], "boxing")
        boxing_prem_events = clone_events_with_sport(list(boxing_prem_state.data) if boxing_prem_state else [], "boxing")

        mma_live_events = clone_events_with_sport(list(mma_live_state.data) if mma_live_state else [], "mma")
        mma_prem_events = clone_events_with_sport(list(mma_prem_state.data) if mma_prem_state else [], "mma")

        ufc_live_events = clone_events_with_sport(list(ufc_live_state.data) if ufc_live_state else [], "ufc")
        ufc_prem_events = clone_events_with_sport(list(ufc_prem_state.data) if ufc_prem_state else [], "ufc")

        ok = any(
            st and st.meta.get("ok")
            for st in (
                boxing_live_state,
                boxing_prem_state,
                mma_live_state,
                mma_prem_state,
                ufc_live_state,
                ufc_prem_state,
            )
        )

    payload = pick_hot_fights(
        events=(
            boxing_live_events
            + boxing_prem_events
            + mma_live_events
            + mma_prem_events
            + ufc_live_events
            + ufc_prem_events
        ),
        limit=limit,
        timezone=FORCED_TIMEZONE,
        debug=bool(debug) and not SETTINGS.is_production(),
    )

    if resp is not None:
        resp.status_code = 200 if ok else 503

    return payload


@app.get("/events/{sport}/{mode}")
def events(sport: str, mode: str, resp: Response) -> Dict[str, Any]:
    sport = sport.lower().strip()
    mode = mode.lower().strip()
    key = (sport, mode)

    if key not in FEEDS:
        resp.status_code = 404
        return {"error": "unknown feed"}

    with _state_lock:
        st = _state[key]
        resp.status_code = 200 if st.meta.get("ok") else 503
        return {"meta": dict(st.meta), "events": list(st.data)}


def feed_health_snapshot() -> Dict[str, Any]:
    """Per-feed health snapshot for the admin diagnostics card.

    Returns a stable, JSON-safe dict keyed by 'sport/mode'. Imported by
    `app/routes/admin_api.py::diagnostics` — keep the shape stable.
    """
    import time as _time

    now_epoch = _time.time()
    out: Dict[str, Any] = {}
    with _state_lock:
        for key, state in _state.items():
            meta = state.meta
            last_ok = meta.get("last_success_epoch")
            last_any = meta.get("last_updated_epoch")
            age_ok = int(now_epoch - last_ok) if last_ok else None
            age_any = int(now_epoch - last_any) if last_any else None
            if last_ok and (now_epoch - last_ok) < 2 * REFRESH_SECONDS:
                health = "ok"
            elif last_ok and (now_epoch - last_ok) < 6 * REFRESH_SECONDS:
                health = "stale"
            else:
                health = "down"
            out[f"{key[0]}/{key[1]}"] = {
                "health": health,
                "ok": bool(meta.get("ok")),
                "error": meta.get("error"),
                "count": int(meta.get("count") or 0),
                "age_seconds_since_success": age_ok,
                "age_seconds_since_attempt": age_any,
            }
    return out


@app.get("/health")
def health() -> Dict[str, Any]:
    """Detailed health for monitors + deploy verification.

    Reports:
      * worker_pid                  PID of the responding uvicorn worker
      * parser_owner_pid            PID holding the parser pidfile (or null if none)
      * parser_owner_alive          Whether the recorded PID still exists
      * parser_freshness_seconds    Seconds since any match row was last touched
      * last_parser_cycle_utc       ISO timestamp of the most recent match update
      * db                          {ok: bool, error?: str}
      * cache                       {campaign_entries, shared_entries}
      * feeds                       Per (sport/mode) feed status snapshot

    Always returns 200 even on partial failure so monitors can read the body;
    `ok: false` indicates degraded state.
    """
    import sqlalchemy as _sa

    from app.database import db_session as _db_session
    from app.models import Match as _Match
    from app.routes.public_render import _png_cache as _campaign_cache
    from app.services import png_cache as _shared_cache_mod

    now_utc = datetime.utcnow()
    overall_ok = True
    out: Dict[str, Any] = {
        "ok": True,
        "now_utc": now_utc.isoformat() + "Z",
        "worker_pid": _os.getpid(),
    }

    # Parser singleton state.
    # CRITICAL — see _pid_alive(): `os.kill(pid, 0)` on Windows kills the
    # target instead of probing. /health was inadvertently killing the
    # uvicorn worker (whose pid IS the parser_owner_pid in single-worker
    # mode) every time it was hit. Always go through _pid_alive.
    owner_pid: Optional[int] = None
    owner_alive: Optional[bool] = None
    try:
        if _PARSER_PIDFILE.exists():
            try:
                owner_pid = int(_PARSER_PIDFILE.read_text().strip())
            except Exception:
                owner_pid = None
        if owner_pid:
            owner_alive = _pid_alive(owner_pid)
    except Exception:
        pass
    out["parser_owner_pid"] = owner_pid
    out["parser_owner_alive"] = owner_alive
    worker_alive = bool(_pw_worker_thread and _pw_worker_thread.is_alive())
    active_age = (
        time.monotonic() - _pw_active_job_started_at
        if _pw_active_job_started_at
        else None
    )
    last_dequeue_age = (
        time.monotonic() - _pw_last_dequeue_at
        if _pw_last_dequeue_at
        else None
    )
    out["parser_worker"] = {
        "alive": worker_alive,
        "queue_size": _pw_jobs.qsize(),
        "active_url": _pw_active_job_url,
        "active_age_seconds": int(active_age) if active_age is not None else None,
        "last_dequeue_age_seconds": int(last_dequeue_age) if last_dequeue_age is not None else None,
        "jobs_enqueued": _pw_jobs_enqueued,
        "jobs_completed": _pw_jobs_completed,
        "jobs_failed": _pw_jobs_failed,
    }

    # Parser freshness via DB
    try:
        with _db_session() as s:
            last = s.query(_sa.func.max(_Match.last_updated_at)).scalar()
        if last:
            age = int((now_utc - last).total_seconds())
            out["parser_freshness_seconds"] = age
            out["last_parser_cycle_utc"] = last.isoformat() + "Z"
        else:
            out["parser_freshness_seconds"] = None
            out["last_parser_cycle_utc"] = None
        out["db"] = {"ok": True}
    except Exception as e:
        overall_ok = False
        out["db"] = {"ok": False, "error": str(e)}

    # Caches
    try:
        out["cache"] = {
            "campaign_entries": len(_campaign_cache),
            "shared_entries": len(_shared_cache_mod._cache),  # noqa: SLF001
        }
    except Exception as e:
        out["cache"] = {"error": str(e)}

    # Legacy in-memory parser state (per sport/mode)
    with _state_lock:
        feeds = {}
        for key, state in _state.items():
            meta = state.meta
            feeds[f"{key[0]}/{key[1]}"] = {
                "ok": bool(meta.get("ok")),
                "error": meta.get("error"),
                "last_attempt_epoch": meta.get("last_attempt_epoch"),
                "last_updated_epoch": meta.get("last_updated_epoch"),
                "count": meta.get("count", 0),
                "backoff_remaining_seconds": int(_feed_backoff_remaining(key)),
            }
    out["feeds"] = feeds
    out["refresh_seconds"] = REFRESH_SECONDS
    out["timezone"] = FORCED_TIMEZONE

    # Degraded detection: the parser can be "running" yet producing nothing
    # (anti-bot soft-block -> every feed empty), which used to still report
    # ok=true while the UI froze. Flag it so monitors actually fire and the
    # JSON matches the UI:
    #   * every feed has 0 matches (strong soft-block signal), or
    #   * no match row has been touched in well over a cycle (freshness frozen).
    degraded_reasons: List[str] = []
    if feeds and all((f.get("count") or 0) == 0 for f in feeds.values()):
        degraded_reasons.append("all parser feeds empty (possible anti-bot soft-block)")
    _fresh = out.get("parser_freshness_seconds")
    if _fresh is not None and _fresh > 6 * REFRESH_SECONDS:
        degraded_reasons.append(f"parser freshness {_fresh}s exceeds {6 * REFRESH_SECONDS}s")
    if degraded_reasons:
        overall_ok = False
        out["degraded"] = True
        out["degraded_reasons"] = degraded_reasons

    out["ok"] = overall_ok
    return out


# =====================================================================
# MANUAL OVERRIDE ENDPOINTS
# Lets you add/remove games from named slots.
# Each slot renders independently via /render/{sport}/manual/{slot}.png
# =====================================================================

@app.get("/manual/slots")
def manual_list_slots(user: Any = Depends(require_login)) -> Dict[str, Any]:
    """List all manual slots with their game counts."""
    return {"slots": manual_store.list_slots()}


@app.post("/manual/slots/{slot}")
def manual_create_slot(
    slot: str,
    body: Dict[str, Any] = Body(...),
    user: Any = Depends(require_role("editor")),
) -> Dict[str, Any]:
    """Create a slot with a sport attached."""
    slot = _validate_manual_slot(slot)
    sport = body.get("sport", "football")
    manual_store.create_slot(slot, sport)
    return {"slot": slot, "sport": sport, "created": True}


@app.get("/manual/slots/{slot}")
def manual_get_slot(slot: str, user: Any = Depends(require_login)) -> Dict[str, Any]:
    """Get all games in a slot."""
    slot = _validate_manual_slot(slot)
    events = manual_store.get_slot(slot)
    return {"slot": slot, "count": len(events), "events": events}


@app.post("/manual/slots/{slot}/games")
def manual_add_game(
    slot: str,
    game: Dict[str, Any] = Body(...),
    user: Any = Depends(require_role("editor")),
) -> Dict[str, Any]:
    """
    Add (or replace) a game in a slot.
    If a game with the same event_id already exists it is replaced.

    Minimal body example:
    {
      "event_id": "my_game_1",
      "status": "prematch",
      "time": {"raw": "Hoy, 20:00"},
      "tournament": {"name": "Premier League"},
      "competitors": {
        "home": {"name": "Man City", "logo": null},
        "away": {"name": "Arsenal", "logo": null}
      },
      "score": {"home": null, "away": null},
      "market": {
        "name": "Resultado",
        "type": "1x2",
        "odds": {"p1": "1.55", "draw": "4.20", "p2": "5.80", "more_odds": false}
      }
    }
    """
    slot = _validate_manual_slot(slot)
    events = manual_store.add_game(slot, game)
    return {"slot": slot, "count": len(events), "events": events}


@app.delete("/manual/slots/{slot}/games/{event_id}")
def manual_remove_game(
    slot: str,
    event_id: str,
    user: Any = Depends(require_role("editor")),
) -> Dict[str, Any]:
    """Remove a single game from a slot by event_id."""
    slot = _validate_manual_slot(slot)
    events = manual_store.remove_game(slot, event_id)
    return {"slot": slot, "count": len(events), "events": events}


@app.delete("/manual/slots/{slot}/games")
def manual_clear_slot(slot: str, user: Any = Depends(require_role("editor"))) -> Dict[str, Any]:
    """Remove all games from a slot (keeps the slot, just empties it)."""
    slot = _validate_manual_slot(slot)
    manual_store.clear_slot(slot)
    return {"slot": slot, "count": 0, "events": []}


@app.delete("/manual/slots/{slot}")
def manual_delete_slot(slot: str, user: Any = Depends(require_role("editor"))) -> Dict[str, Any]:
    """Delete an entire slot."""
    slot = _validate_manual_slot(slot)
    deleted = manual_store.delete_slot(slot)
    return {"slot": slot, "deleted": deleted}
