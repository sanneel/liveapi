#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import faulthandler as _faulthandler
import json as _json
import re
import sys as _sys
import threading
import time

# Dump a Python traceback for every thread on segfault/abort/timeout.
# Without this, a Playwright Node-subprocess death silently kills uvicorn
# with no diagnostic. Writes to stderr.
_faulthandler.enable(_sys.stderr)
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import quote as _url_quote
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
from app.routes.admin_hot import router as admin_hot_router
from app.routes.admin_hot_override import router as admin_hot_override_router
from app.routes.admin_logs import router as admin_logs_router
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

logger = get_logger("server")

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
    ("football", "prematch_mundial"): "https://jugabet.cl/football/all/1?tournaments=c19cb5ffb4404c31b869b53dd90161de",
    ("football", "prematch_chile"): "https://jugabet.cl/football/all/1?tournaments=fc7f16ba2ec24f528179d20490404fb5,013358a438324b18975b19aeef58684f",
}


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
        dt_utc = datetime.strptime(data_time.strip(), "%m/%d/%Y %H:%M:%S %z")
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
from concurrent.futures import Future as _Future

_pw_jobs: "_queue.Queue[Tuple[str, _Future]]" = _queue.Queue()
_pw_worker_started = False
_pw_worker_lock = threading.Lock()


def _pw_worker_loop() -> None:
    """Dedicated thread: owns Playwright + Browser for the process lifetime.

    Pops (url, future) jobs off the queue, runs the fetch, sets the result
    (or exception) on the future. Restarts Playwright in-place if the
    Node driver dies between jobs.
    """
    pw = None
    browser = None

    def _ensure_browser():
        nonlocal pw, browser
        if pw is None:
            pw = sync_playwright().start()
        if browser is None or not browser.is_connected():
            try:
                if browser is not None:
                    browser.close()
            except Exception:
                pass
            browser = pw.chromium.launch(headless=True)
        return browser

    while True:
        url, fut = _pw_jobs.get()
        if url is None:  # shutdown sentinel
            try:
                if browser is not None:
                    browser.close()
                if pw is not None:
                    pw.stop()
            except Exception:
                pass
            return
        try:
            br = _ensure_browser()
            html, api_data = _do_fetch(br, url)
            fut.set_result((html, api_data))
        except Exception as e:
            # Driver may be dead — force reinit on next job.
            try:
                if browser is not None:
                    browser.close()
            except Exception:
                pass
            browser = None
            if isinstance(e, PlaywrightTimeoutError):
                logger.warning(f"parser: timeout fetching {url}")
            else:
                logger.exception(f"parser: fetch_rendered_html failed for {url}")
            fut.set_exception(e)


def _ensure_pw_worker() -> None:
    global _pw_worker_started
    with _pw_worker_lock:
        if _pw_worker_started:
            return
        t = threading.Thread(target=_pw_worker_loop, name="pw-worker", daemon=True)
        t.start()
        _pw_worker_started = True


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
            if "by-market-filter" in url_lower or "by-sport-filter" in url_lower:
                try:
                    data = response.json()
                    if isinstance(data, dict):
                        api_data.update(data)
                except Exception:
                    logger.warning(
                        f"parser: failed to parse JSON response url={response.url}",
                        exc_info=True,
                    )

        page.on("response", handle_response)
        page.goto(url, wait_until="domcontentloaded", timeout=TIMEOUT_MS)

        try:
            page.wait_for_selector(WAIT_SELECTOR, timeout=TIMEOUT_MS)
        except PlaywrightTimeoutError:
            pass

        # Bug 4: wait for odds XHR before reading content
        try:
            with page.expect_response(
                lambda r: (
                    "by-market-filter" in r.url.lower()
                    or "by-sport-filter" in r.url.lower()
                ),
                timeout=TIMEOUT_MS,
            ):
                pass
        except PlaywrightTimeoutError:
            pass


        # Bug 6: adaptive scroll — keep paging until the event-card count
        # plateaus, bounded at 20 iterations.
        url_lower = url.lower()
        if "prematch" in url_lower or "/all" in url_lower:
            prev_count = -1
            for _ in range(20):
                try:
                    count = page.evaluate(
                        "document.querySelectorAll('div.event-card').length"
                    )
                    if count == prev_count:
                        break
                    prev_count = count
                    page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                    page.wait_for_timeout(800)
                except Exception:
                    break

        page.wait_for_timeout(JS_SETTLE_MS)
        html = page.content()
        if _looks_like_geo_restriction(html):
            raise RuntimeError(
                "Jugabet geo restriction page returned; use a Chile egress IP/proxy"
            )
        return html, api_data
    finally:
        try:
            context.close()
        except Exception:
            logger.warning("parser: context.close() failed", exc_info=True)


def fetch_rendered_html(url: str) -> Tuple[str, Dict[str, Any]]:
    """Submit a fetch job to the pw-worker thread and wait for the result.

    Called from N parser threads concurrently; the pw-worker serializes
    them onto a single Playwright instance. Cycle wall-clock is set by
    sum-of-fetches rather than max-of-fetches, but eliminates the
    multi-process Node EPIPE crash that previously killed the whole
    uvicorn process.
    """
    _ensure_pw_worker()
    fut: _Future = _Future()
    _pw_jobs.put((url, fut))
    # Bound the per-job wait so a stuck worker doesn't pin a parser thread
    # forever; Playwright's own internal timeouts fire first in normal cases.
    return fut.result(timeout=TIMEOUT_MS / 1000 * 3 + 30)


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

    for card in soup.select("div.event-card"):
        event_id = card.get("data-event-card-id")
        if not event_id:
            continue

        # --- event link ---
        a_el = card.select_one('a[data-id="event-card"]')
        if a_el is None:
            a_el = card.find_parent("a", attrs={"data-id": "event-card"})
        event_href = make_abs_url(a_el.get("href") if a_el else None)

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
            continue

        # --- start time from data-time attribute (ISO datetime, much better than text) ---
        time_raw: Optional[str] = None
        time_utc: Optional[str] = None
        time_el = card.select_one("[data-time]")
        if time_el and time_el.get("data-time"):
            time_raw, time_utc = _parse_data_time(time_el.get("data-time"))
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
        market_name_el = card.select_one('[data-lineup-id="market-name"]')
        market_name_raw = market_name_el.get_text(" ", strip=True) if market_name_el else None
        market_type = _detect_market_type(market_name_raw)

        market_odds = None
        if api_data and event_id:
            market_odds = _parse_odds_from_json(event_id, market_type, api_data, home_name, away_name)

        if market_odds is None:
            market_container = card.select_one('div.event-card__market [data-lineup-id="market-container"]')
            if market_container is None:
                market_container = card.select_one('[data-lineup-id="market-container"]')

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

    return events


def refresh_once(key: Tuple[str, str]) -> None:
    url = FEEDS[key]
    sport, mode = key

    _parser_sem.acquire()
    try:
        html, api_data = fetch_rendered_html(url)
        data = parse_html(html, api_data)

        with _state_lock:
            _state[key] = FeedState(
                data=data,
                meta={
                    "ok": True,
                    "error": None,
                    "last_updated_epoch": int(time.time()),
                    "last_success_epoch": int(time.time()),
                    "source_url": url,
                    "count": len(data),
                    "sport": sport,
                    "mode": mode,
                    "timezone": FORCED_TIMEZONE,
                },
            )

        # ── Dual-write: persist to DB (best-effort, never fails the loop) ──
        try:
            from app.parser.persistence import persist_feed_results
            persist_feed_results(data, sport, mode)
        except Exception:
            # DB layer not yet initialized? Log and continue — legacy system unaffected.
            logger.exception(f"parser: DB persist failed sport={sport} mode={mode}")

    except Exception as e:
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


def refresh_loop(key: Tuple[str, str], initial_delay: float = 0.0) -> None:
    if initial_delay > 0:
        time.sleep(initial_delay)
    # Monotonic next-tick scheduling (C3). Old code did
    # `refresh_once(); sleep(REFRESH_SECONDS)` which made the effective cycle
    # period = REFRESH_SECONDS + fetch_time, accumulating phase drift between
    # sports. Now each tick fires REFRESH_SECONDS after the previous tick;
    # if a cycle overruns, the next tick fires immediately and we reset the
    # baseline to avoid death-spiral catch-up.
    next_at = time.monotonic()
    while True:
        # Bug 9: refresh_once already swallows fetch/parse exceptions, but a
        # bug in the surrounding scheduling code (or an OOM, or a Playwright
        # protocol error escaping the inner handler) would kill the thread
        # silently. Wrap the loop body so the thread can't die.
        try:
            refresh_once(key)
        except Exception:
            logger.exception(f"parser: refresh_loop iteration crashed for {key}")
        next_at += REFRESH_SECONDS
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
        return True
    except FileExistsError:
        # Check if the recorded pid is alive
        try:
            existing = int(_PARSER_PIDFILE.read_text().strip())
        except Exception:
            existing = None
        alive = False
        if existing:
            try:
                _os.kill(existing, 0)
                alive = True
            except (ProcessLookupError, PermissionError, OSError):
                alive = False
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


def _feed_watchdog_loop() -> None:
    """Re-spawn any feed thread that has died or never produced a first fetch.

    A feed is considered dead when EITHER:
      * its thread object is missing or not alive, OR
      * meta.last_success_epoch is None AND the thread has been running for
        more than (3 * REFRESH_SECONDS) seconds (first fetch should have
        completed by then; if not, the thread is probably wedged).
    """
    started_at = time.time()
    grace = REFRESH_SECONDS * 3
    while True:
        time.sleep(60)
        try:
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
    SETTINGS.validate_production()
    _run_migrations_on_startup()
    if not SETTINGS.parser_enabled:
        logger.info("parser disabled via settings; not starting feed threads")
        return
    # The parser uses background threads inside THIS process. Without the
    # pidfile guard below, `uvicorn --workers N>1` would spawn one parser
    # per worker. The systemd unit hardcodes `--workers 1`, but the lock is
    # belt-and-braces in case that's ever changed by mistake.
    if not _acquire_parser_lock():
        return
    # BUG-01 fix: pre-start the dedicated Playwright worker BEFORE any feed
    # thread submits a fetch. Avoids a thundering-herd init race that
    # previously crashed the Node driver with EPIPE.
    _ensure_pw_worker()
    logger.info(f"parser: spawning {len(FEEDS)} feed threads (pid={_os.getpid()})")
    for idx, key in enumerate(FEEDS.keys()):
        _spawn_feed_thread(key, initial_delay=idx * 2.0)
    # BUG-04: watchdog respawns silently-dead feeds and surfaces stuck ones.
    threading.Thread(target=_feed_watchdog_loop, name="feed-watchdog", daemon=True).start()


@app.on_event("shutdown")
def shutdown() -> None:
    flush_hit_buffer()
    _release_parser_lock()


@app.get("/events/football/hot")
def football_hot(limit: int = Query(5, ge=1, le=10), debug: int = 0, resp: Response = None) -> Dict[str, Any]:
    """
    GET /events/football/hot?limit=5&debug=1
    """
    with _state_lock:
        live_state = _state.get(("football", "live"))
        prem_state = _state.get(("football", "prematch"))
        chile_state = _state.get(("football", "prematch_chile"))

        live_events = list(live_state.data) if live_state else []
        prem_events = list(prem_state.data) if prem_state else []
        chile_events = list(chile_state.data) if chile_state else []

        ok = bool(
            (live_state and live_state.meta.get("ok"))
            or (prem_state and prem_state.meta.get("ok"))
            or (chile_state and chile_state.meta.get("ok"))
        )

    # Deduplicate events by event_id
    seen_ids = set()
    combined_events = []
    for e in (live_events + prem_events + chile_events):
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

    # Parser singleton state
    owner_pid = None
    owner_alive = None
    try:
        if _PARSER_PIDFILE.exists():
            try:
                owner_pid = int(_PARSER_PIDFILE.read_text().strip())
            except Exception:
                owner_pid = None
        if owner_pid:
            try:
                _os.kill(owner_pid, 0)
                owner_alive = True
            except (ProcessLookupError, PermissionError, OSError):
                owner_alive = False
    except Exception:
        pass
    out["parser_owner_pid"] = owner_pid
    out["parser_owner_alive"] = owner_alive

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
                "last_updated_epoch": meta.get("last_updated_epoch"),
                "count": meta.get("count", 0),
            }
    out["feeds"] = feeds
    out["refresh_seconds"] = REFRESH_SECONDS
    out["timezone"] = FORCED_TIMEZONE
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
