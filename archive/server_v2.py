#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
server_v2.py — Request-based event fetcher (no Playwright, no HTML parsing).

HOW TO ACTIVATE
---------------
1. Run discover_api_urls.py once:
       python discover_api_urls.py
   This creates api_urls_discovered.json with the real jugabet.cl API URLs.

2. Open api_urls_discovered.json and find the by-sport-filter URLs.
   They will look like:
       https://jugabet.cl/api/sportsbook/v1/...?sportAlias=Football&type=Prematch&...

3. Paste those base URLs into DIRECT_API_CONFIG below.

4. Test on port 8006 while server.py still runs on 8000:
       python -m uvicorn server_v2:app --host 127.0.0.1 --port 8006 --reload

5. Compare output:
       curl http://127.0.0.1:8000/events/football/hot > old.json
       curl http://127.0.0.1:8006/events/football/hot > new.json

6. When satisfied, swap: stop server.py on 8000, start server_v2.py on 8000.
"""

from __future__ import annotations

import re
import threading
import time
import unicodedata
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

import requests
from fastapi import FastAPI, Response, Body

from weights_chile_first import FORCED_TIMEZONE
from hot_scoring import pick_hot as pick_hot_football
from hot_scoring_tennis import pick_hot as pick_hot_tennis
from hot_scoring_basketball import pick_hot as pick_hot_basketball
from hot_scoring_cybersport import pick_hot as pick_hot_cybersport
from hot_scoring_fights import pick_hot as pick_hot_fights
import manual_store


# ======================================================================
# STEP 1: FILL THESE IN after running discover_api_urls.py
# ======================================================================
# Each entry maps (sport, mode) to the direct API URL.
# Leave the URL as "" if not yet discovered — that feed will stay empty.
#
# Example (BetConstruct typical structure):
#   "https://jugabet.cl/api/sportsbook/v1/events/by-sport-filter"
#   with params: sportAlias=Football, type=Prematch, marketTypes=..., count=200

DIRECT_API_BASE_URL = ""   # e.g. "https://jugabet.cl/api/sportsbook/v1/events/by-sport-filter"

# Query params template per sport/mode — fill after discovery
SPORT_PARAMS: Dict[Tuple[str, str], Dict[str, Any]] = {
    ("football",   "prematch"): {"sportAlias": "Football",    "type": "Prematch"},
    ("football",   "live"):     {"sportAlias": "Football",    "type": "Live"},
    ("tennis",     "prematch"): {"sportAlias": "Tennis",      "type": "Prematch"},
    ("tennis",     "live"):     {"sportAlias": "Tennis",      "type": "Live"},
    ("basketball", "prematch"): {"sportAlias": "Basketball",  "type": "Prematch"},
    ("basketball", "live"):     {"sportAlias": "Basketball",  "type": "Live"},
    ("boxing",     "prematch"): {"sportAlias": "Boxing",      "type": "Prematch"},
    ("boxing",     "live"):     {"sportAlias": "Boxing",      "type": "Live"},
    ("mma",        "prematch"): {"sportAlias": "MMA",         "type": "Prematch"},
    ("mma",        "live"):     {"sportAlias": "MMA",         "type": "Live"},
    ("ufc",        "prematch"): {"sportAlias": "UFC",         "type": "Prematch"},
    ("ufc",        "live"):     {"sportAlias": "UFC",         "type": "Live"},
    ("cybersport", "prematch"): {"sportAlias": "Cybersport",  "type": "Prematch"},
    ("cybersport", "live"):     {"sportAlias": "Cybersport",  "type": "Live"},
}

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "application/json",
    "Referer": "https://jugabet.cl/",
}

REFRESH_SECONDS = 120
REQUEST_TIMEOUT = 20
SITE_BASE = "https://jugabet.cl"
# ======================================================================


app = FastAPI(title="Jugabet Events JSON v2 (request-based)", version="2.0")


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
            "source": "direct_api",
            "count": 0,
            "sport": key[0],
            "mode": key[1],
            "timezone": FORCED_TIMEZONE,
        },
    )
    for key in SPORT_PARAMS
}


# ======================================================================
# JSON PARSER
# Converts the raw API response into the same event dict format
# that server.py produces, so all render servers work without changes.
#
# NOTE: The exact parsing logic depends on what jugabet.cl's API returns.
# The structure below is based on BetConstruct's standard API format.
# Adjust field names after inspecting api_urls_discovered.json.
# ======================================================================

_PUNCT_RE = re.compile(r"[,\.\(\)\[\]\{\}\-\_\/]+")
_SPACES_RE = re.compile(r"\s+")


def _norm(text: Optional[str]) -> str:
    if not text:
        return ""
    s = text.strip().lower()
    s = unicodedata.normalize("NFKD", s)
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    s = _PUNCT_RE.sub(" ", s)
    return _SPACES_RE.sub(" ", s).strip()


def _make_abs_url(href: Optional[str]) -> Optional[str]:
    if not href:
        return None
    s = href.strip()
    if s.startswith("//"):
        return "https:" + s
    if s.startswith("/"):
        return SITE_BASE + s
    return s


def _detect_market_type(name: Optional[str]) -> str:
    n = _norm(name)
    if n in {"resultado del partido (tiempo reglamentario)", "resultado del partido", "1x2", "match result"}:
        return "1x2"
    if n in {"total", "totales", "mas menos", "over under"}:
        return "total"
    if "ganador" in n or "winner" in n:
        return "winner"
    return "unknown"


def parse_betconstruct_response(raw: Any, sport: str, mode: str) -> List[Dict[str, Any]]:
    """
    Parse a BetConstruct API response into the internal event list format.

    BetConstruct's by-sport-filter typically returns:
    {
      "result": {
        "sport": [{
          "id": ...,
          "alias": "Football",
          "region": [{
            "id": ...,
            "name": "England",
            "competition": [{
              "id": ...,
              "name": "Premier League",
              "game": [{
                "id": ...,
                "team1_name": "Man City",
                "team2_name": "Arsenal",
                "team1_id": ...,
                "team2_id": ...,
                "start_ts": 1234567890,
                "type": 1,          (1=prematch, 0=live)
                "info": {
                  "current_game_time": "45'",
                  "score1": 2,
                  "score2": 1,
                  "add_info": "1st Half"
                },
                "market": {
                  "market_id": {
                    "name": "Match Result",
                    "type": ...,
                    "event": {
                      "outcome_id": {"name": "1", "price": 1.95},
                      "outcome_id": {"name": "X", "price": 3.50},
                      "outcome_id": {"name": "2", "price": 3.80},
                    }
                  }
                }
              }]
            }]
          }]
        }]
      }
    }

    ADJUST THIS FUNCTION based on what you see in api_urls_discovered.json.
    """
    events: List[Dict[str, Any]] = []

    if not isinstance(raw, dict):
        return events

    result = raw.get("result") or raw
    if not isinstance(result, dict):
        return events

    sports_list = result.get("sport") or []
    if isinstance(sports_list, dict):
        sports_list = list(sports_list.values())

    for sport_block in sports_list:
        if not isinstance(sport_block, dict):
            continue

        regions = sport_block.get("region") or []
        if isinstance(regions, dict):
            regions = list(regions.values())

        for region in regions:
            if not isinstance(region, dict):
                continue

            competitions = region.get("competition") or []
            if isinstance(competitions, dict):
                competitions = list(competitions.values())

            for comp in competitions:
                if not isinstance(comp, dict):
                    continue

                comp_name = comp.get("name") or ""
                games = comp.get("game") or []
                if isinstance(games, dict):
                    games = list(games.values())

                for game in games:
                    if not isinstance(game, dict):
                        continue

                    ev = _parse_game(game, comp_name, sport, mode)
                    if ev:
                        events.append(ev)

    return events


def _parse_game(
    game: Dict[str, Any],
    comp_name: str,
    sport: str,
    mode: str,
) -> Optional[Dict[str, Any]]:
    game_id = str(game.get("id") or "")
    if not game_id:
        return None

    home_name = (game.get("team1_name") or "").strip()
    away_name = (game.get("team2_name") or "").strip()
    if not home_name or not away_name:
        return None

    # Home/away logos — BetConstruct uses team IDs to build logo URLs
    team1_id = game.get("team1_id")
    team2_id = game.get("team2_id")
    home_logo = f"https://jugabet.cl/uploads/teams/{team1_id}.png" if team1_id else None
    away_logo = f"https://jugabet.cl/uploads/teams/{team2_id}.png" if team2_id else None

    # Status
    game_type = game.get("type")
    is_live = (game_type == 0) or (mode == "live")
    status = "live" if is_live else "prematch"

    # Time
    info = game.get("info") or {}
    if is_live:
        add_info = info.get("add_info") or ""
        game_time = info.get("current_game_time") or ""
        time_raw = f"{add_info} {game_time}".strip() if add_info else game_time
    else:
        start_ts = game.get("start_ts")
        if start_ts:
            import datetime
            from zoneinfo import ZoneInfo
            dt = datetime.datetime.fromtimestamp(int(start_ts), tz=ZoneInfo(FORCED_TIMEZONE))
            time_raw = dt.strftime("%-d %b, %H:%M").lower()
        else:
            time_raw = ""

    # Score
    score1 = info.get("score1")
    score2 = info.get("score2")
    home_score = int(score1) if score1 is not None else None
    away_score = int(score2) if score2 is not None else None

    # Market/odds — take first available market
    markets_raw = game.get("market") or {}
    if isinstance(markets_raw, dict):
        markets_list = list(markets_raw.values())
    else:
        markets_list = markets_raw

    market_data = {"name": None, "type": "unknown", "odds": {}}
    for m in markets_list:
        if not isinstance(m, dict):
            continue
        m_name = m.get("name") or ""
        m_type = _detect_market_type(m_name)
        if m_type == "unknown":
            continue

        events_raw = m.get("event") or {}
        if isinstance(events_raw, dict):
            outcomes = list(events_raw.values())
        else:
            outcomes = events_raw

        odds = _parse_outcomes(outcomes, m_type, home_name, away_name)
        if odds:
            market_data = {"name": m_name, "type": m_type, "odds": odds}
            break

    href = f"{SITE_BASE}/events/{game_id}"

    return {
        "event_id": game_id,
        "href": href,
        "status": status,
        "time": {"raw": time_raw},
        "tournament": {"name": comp_name},
        "competitors": {
            "home": {"name": home_name, "logo": home_logo},
            "away": {"name": away_name, "logo": away_logo},
        },
        "score": {"home": home_score, "away": away_score},
        "market": market_data,
    }


def _parse_outcomes(
    outcomes: List[Dict[str, Any]],
    market_type: str,
    home_name: str,
    away_name: str,
) -> Optional[Dict[str, Any]]:
    if not outcomes:
        return None

    def price_str(o: Any) -> Optional[str]:
        p = o.get("price") if isinstance(o, dict) else None
        if p is None:
            return None
        try:
            f = float(p)
            return str(round(f, 2)) if f > 1.0 else None
        except (TypeError, ValueError):
            return None

    def outcome_name(o: Any) -> str:
        return _norm(o.get("name") or "") if isinstance(o, dict) else ""

    if market_type == "1x2":
        p1 = draw = p2 = None
        for o in outcomes:
            n = outcome_name(o)
            pr = price_str(o)
            if not pr:
                continue
            if n in {"x", "empate", "draw"}:
                draw = pr
            elif _norm(home_name) and _norm(home_name) in n:
                p1 = pr
            elif _norm(away_name) and _norm(away_name) in n:
                p2 = pr
        # positional fallback
        priced = [price_str(o) for o in outcomes if price_str(o)]
        if p1 is None and len(priced) >= 1:
            p1 = priced[0]
        if draw is None and len(priced) >= 3:
            draw = priced[1]
        if p2 is None and len(priced) >= 2:
            p2 = priced[-1]
        if not (p1 or draw or p2):
            return None
        return {"p1": p1, "draw": draw, "p2": p2, "more_odds": False}

    if market_type == "winner":
        p1 = p2 = None
        for o in outcomes:
            pr = price_str(o)
            if not pr:
                continue
            n = outcome_name(o)
            if _norm(home_name) and _norm(home_name) in n:
                p1 = pr
            elif _norm(away_name) and _norm(away_name) in n:
                p2 = pr
        priced = [price_str(o) for o in outcomes if price_str(o)]
        if p1 is None and len(priced) >= 1:
            p1 = priced[0]
        if p2 is None and len(priced) >= 2:
            p2 = priced[1]
        if not (p1 or p2):
            return None
        return {"p1": p1, "p2": p2, "more_odds": False}

    return None


# ======================================================================
# FETCH + REFRESH LOOP
# ======================================================================

def fetch_api_direct(sport: str, mode: str) -> List[Dict[str, Any]]:
    if not DIRECT_API_BASE_URL:
        return []

    params = dict(SPORT_PARAMS.get((sport, mode), {}))
    params.setdefault("count", 200)

    resp = requests.get(
        DIRECT_API_BASE_URL,
        params=params,
        headers=HEADERS,
        timeout=REQUEST_TIMEOUT,
    )
    resp.raise_for_status()
    raw = resp.json()
    return parse_betconstruct_response(raw, sport, mode)


def refresh_once(key: Tuple[str, str]) -> None:
    sport, mode = key
    try:
        data = fetch_api_direct(sport, mode)
        with _state_lock:
            _state[key] = FeedState(
                data=data,
                meta={
                    "ok": True,
                    "error": None,
                    "last_updated_epoch": int(time.time()),
                    "source": "direct_api",
                    "count": len(data),
                    "sport": sport,
                    "mode": mode,
                    "timezone": FORCED_TIMEZONE,
                },
            )
    except Exception as e:
        with _state_lock:
            prev = _state[key]
            prev.meta = {
                **prev.meta,
                "ok": False,
                "error": str(e),
                "last_updated_epoch": int(time.time()),
            }
            _state[key] = prev


def refresh_loop(key: Tuple[str, str]) -> None:
    refresh_once(key)
    while True:
        time.sleep(REFRESH_SECONDS)
        refresh_once(key)


@app.on_event("startup")
def startup() -> None:
    for key in SPORT_PARAMS:
        t = threading.Thread(target=refresh_loop, args=(key,), daemon=True)
        t.start()


# ======================================================================
# API ENDPOINTS — identical to server.py so render servers need no changes
# ======================================================================

def _clone_with_sport(events: List[Dict[str, Any]], sport: str) -> List[Dict[str, Any]]:
    return [{**ev, "sport": sport} for ev in events]


@app.get("/events/football/hot")
def football_hot(limit: int = 5, debug: int = 0, resp: Response = None) -> Dict[str, Any]:
    with _state_lock:
        live = list((_state.get(("football", "live")) or FeedState([], {})).data)
        prem = list((_state.get(("football", "prematch")) or FeedState([], {})).data)
    return pick_hot_football(events=live + prem, limit=limit, timezone=FORCED_TIMEZONE, debug=bool(debug))


@app.get("/events/tennis/hot")
def tennis_hot(limit: int = 5, debug: int = 0, resp: Response = None) -> Dict[str, Any]:
    with _state_lock:
        live = list((_state.get(("tennis", "live")) or FeedState([], {})).data)
        prem = list((_state.get(("tennis", "prematch")) or FeedState([], {})).data)
    return pick_hot_tennis(events=live + prem, limit=limit, timezone=FORCED_TIMEZONE, debug=bool(debug))


@app.get("/events/basketball/hot")
def basketball_hot(limit: int = 5, debug: int = 0, resp: Response = None) -> Dict[str, Any]:
    with _state_lock:
        live = list((_state.get(("basketball", "live")) or FeedState([], {})).data)
        prem = list((_state.get(("basketball", "prematch")) or FeedState([], {})).data)
    return pick_hot_basketball(events=live + prem, limit=limit, timezone=FORCED_TIMEZONE, debug=bool(debug))


@app.get("/events/cybersport/hot")
def cybersport_hot(limit: int = 5, debug: int = 0, resp: Response = None) -> Dict[str, Any]:
    with _state_lock:
        live = list((_state.get(("cybersport", "live")) or FeedState([], {})).data)
        prem = list((_state.get(("cybersport", "prematch")) or FeedState([], {})).data)
    return pick_hot_cybersport(events=live + prem, limit=limit, timezone=FORCED_TIMEZONE, debug=bool(debug))


@app.get("/events/fights/hot")
def fights_hot(limit: int = 5, debug: int = 0, resp: Response = None) -> Dict[str, Any]:
    with _state_lock:
        events = []
        for sport in ("boxing", "mma", "ufc"):
            for mode in ("live", "prematch"):
                st = _state.get((sport, mode))
                if st:
                    events.extend(_clone_with_sport(list(st.data), sport))
    return pick_hot_fights(events=events, limit=limit, timezone=FORCED_TIMEZONE, debug=bool(debug))


@app.get("/events/{sport}/{mode}")
def events(sport: str, mode: str, resp: Response) -> Dict[str, Any]:
    key = (sport.lower().strip(), mode.lower().strip())
    if key not in SPORT_PARAMS:
        resp.status_code = 404
        return {"error": "unknown feed"}
    with _state_lock:
        st = _state[key]
        resp.status_code = 200 if st.meta.get("ok") else 503
        return {"meta": dict(st.meta), "events": list(st.data)}


@app.get("/health")
def health() -> Dict[str, Any]:
    with _state_lock:
        return {
            "version": "v2-request-based",
            "api_configured": bool(DIRECT_API_BASE_URL),
            "refresh_seconds": REFRESH_SECONDS,
            "timezone": FORCED_TIMEZONE,
            "feeds": {f"{k[0]}/{k[1]}": dict(v.meta) for k, v in _state.items()},
        }


# ======================================================================
# MANUAL OVERRIDE ENDPOINTS (same as server.py)
# ======================================================================

@app.get("/manual/slots")
def manual_list_slots() -> Dict[str, Any]:
    return {"slots": manual_store.list_slots()}


@app.get("/manual/slots/{slot}")
def manual_get_slot(slot: str) -> Dict[str, Any]:
    events = manual_store.get_slot(slot)
    return {"slot": slot, "count": len(events), "events": events}


@app.post("/manual/slots/{slot}/games")
def manual_add_game(slot: str, game: Dict[str, Any] = Body(...)) -> Dict[str, Any]:
    events = manual_store.add_game(slot, game)
    return {"slot": slot, "count": len(events), "events": events}


@app.delete("/manual/slots/{slot}/games/{event_id}")
def manual_remove_game(slot: str, event_id: str) -> Dict[str, Any]:
    events = manual_store.remove_game(slot, event_id)
    return {"slot": slot, "count": len(events), "events": events}


@app.delete("/manual/slots/{slot}/games")
def manual_clear_slot(slot: str) -> Dict[str, Any]:
    manual_store.clear_slot(slot)
    return {"slot": slot, "count": 0, "events": []}


@app.delete("/manual/slots/{slot}")
def manual_delete_slot(slot: str) -> Dict[str, Any]:
    deleted = manual_store.delete_slot(slot)
    return {"slot": slot, "deleted": deleted}
