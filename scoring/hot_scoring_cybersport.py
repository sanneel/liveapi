#hot_scoring_cybersport.py
#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import re
from functools import lru_cache
from typing import Any, Dict, List, Optional, Tuple

from .weights_cybersport_chile import (
    ACADEMY_PATTERNS,
    ACADEMY_PENALTY,
    ALLOWED_MARKET_TYPES,
    BASE_SCORE,
    FORCED_TIMEZONE,
    GAME_NAME_PATTERNS,
    GAME_WEIGHTS,
    HARD_EXCLUDE_MARKET_NAME_PATTERNS,
    HARD_EXCLUDE_TOURNAMENT_PATTERNS,
    LATAM_TEAM_BONUS,
    LATAM_TEAMS,
    LIVE_BONUS,
    LIVE_GENERIC_STAGE_BONUS,
    LOW_SIGNAL_FORMAT_PATTERNS,
    LOW_SIGNAL_FORMAT_PENALTY,
    MAP_STAGE_BONUS,
    MAX_PER_TEAM,
    MAX_PER_TOURNAMENT,
    MOBILE_LOW_PRIORITY_PATTERNS,
    MOBILE_LOW_PRIORITY_PENALTY,
    ODDS_CLOSE_BONUS,
    ODDS_COINFLIP_BONUS,
    ODDS_EXTREME_FAVORITE_PENALTY,
    ODDS_HEAVY_FAVORITE_PENALTY,
    POPULAR_TEAM_BONUS,
    POPULAR_TEAMS,
    QUALIFIER_PATTERNS,
    QUALIFIER_PENALTY,
    TIER1_TOURNAMENT_PATTERNS,
    TIER2_TOURNAMENT_PATTERNS,
    TIER3_TOURNAMENT_PATTERNS,
    TOURNAMENT_TIER1_BONUS,
    TOURNAMENT_TIER2_BONUS,
    TOURNAMENT_TIER3_PENALTY,
)


# -------------------------
# Text helpers
# -------------------------
_SPACES_RE = re.compile(r"\s+")
_MAP_RE = re.compile(r"\bmapa\s*([1-9])\b", re.IGNORECASE)


@lru_cache(maxsize=8192)
def normalize(text: Optional[str]) -> str:
    if not text:
        return ""
    s = str(text).strip().lower()
    s = s.replace("’", "'")
    s = _SPACES_RE.sub(" ", s)
    return s

def is_valid_odd(value: Any) -> bool:
    if value is None:
        return False
    s = str(value).strip()
    if not s:
        return False

    s = s.replace(",", ".")
    s = s.replace("−", "-")
    s = s.replace("–", "-")
    s = s.replace("—", "-")

    try:
        v = float(s)
    except Exception:
        return False

    return v > 1.0

def contains_any(text: Optional[str], patterns: List[str]) -> bool:
    s = normalize(text)
    return any(normalize(p) in s for p in patterns)

# -------------------------
# Event field helpers
# -------------------------
def tournament_name(event: Dict[str, Any]) -> str:
    return ((event.get("tournament") or {}).get("name")) or ""


def market_name(event: Dict[str, Any]) -> str:
    return ((event.get("market") or {}).get("name")) or ""


def market_type(event: Dict[str, Any]) -> str:
    return normalize((event.get("market") or {}).get("type"))


def home_name(event: Dict[str, Any]) -> str:
    return (((event.get("competitors") or {}).get("home") or {}).get("name")) or ""


def away_name(event: Dict[str, Any]) -> str:
    return (((event.get("competitors") or {}).get("away") or {}).get("name")) or ""


def time_raw(event: Dict[str, Any]) -> str:
    return ((event.get("time") or {}).get("raw")) or ""


def odds_dict(event: Dict[str, Any]) -> Dict[str, Any]:
    return (((event.get("market") or {}).get("odds")) or {})


# -------------------------
# Classification helpers
# -------------------------
def detect_game(tournament: str) -> str:
    n = normalize(tournament)

    for game_key, patterns in GAME_NAME_PATTERNS.items():
        for pattern in patterns:
            if pattern in n:
                return game_key

    return "other"


def parse_map_stage(raw: str) -> Optional[int]:
    s = normalize(raw)
    m = _MAP_RE.search(s)
    if not m:
        return None
    try:
        return int(m.group(1))
    except Exception:
        return None


def is_tier1_tournament(event: Dict[str, Any]) -> bool:
    return contains_any(tournament_name(event), TIER1_TOURNAMENT_PATTERNS)


def is_tier2_tournament(event: Dict[str, Any]) -> bool:
    return contains_any(tournament_name(event), TIER2_TOURNAMENT_PATTERNS)


def is_tier3_tournament(event: Dict[str, Any]) -> bool:
    return contains_any(tournament_name(event), TIER3_TOURNAMENT_PATTERNS)


# -------------------------
# Hard exclude
# -------------------------
def is_hard_excluded(event: Dict[str, Any]) -> bool:
    if market_type(event) not in ALLOWED_MARKET_TYPES:
        return True

    t_name = tournament_name(event)
    m_name = market_name(event)

    if contains_any(t_name, HARD_EXCLUDE_TOURNAMENT_PATTERNS):
        return True

    if contains_any(m_name, HARD_EXCLUDE_MARKET_NAME_PATTERNS):
        return True

    odds = odds_dict(event)
    if not is_valid_odd(odds.get("p1")) or not is_valid_odd(odds.get("p2")):
        return True

    if not home_name(event) or not away_name(event):
        return True

    return False


# -------------------------
# Weight helpers
# -------------------------
def _best_weight(text: str, patterns: List[Tuple[str, int]]) -> int:
    """Points of the highest-value weight whose pattern appears in `text`.

    Patterns arrive sorted by points desc, so the first textual match is the
    best one — this reproduces the old "best tier wins" behaviour.
    """
    nt = normalize(text)
    for pat, w in patterns:
        if normalize(pat) in nt:
            return int(w)
    return 0


def _cybersport_static_weights() -> Tuple[
    List[Tuple[str, int]], List[Tuple[str, int]], List[Tuple[str, int]]
]:
    """Rebuild (league, team, word) weight lists from the static module — used
    as a fallback when the DB provider is unavailable (tests / isolation)."""
    league = (
        [(p, TOURNAMENT_TIER1_BONUS) for p in TIER1_TOURNAMENT_PATTERNS]
        + [(p, TOURNAMENT_TIER2_BONUS) for p in TIER2_TOURNAMENT_PATTERNS]
        + [(p, TOURNAMENT_TIER3_PENALTY) for p in TIER3_TOURNAMENT_PATTERNS]
    )
    team = (
        [(p, POPULAR_TEAM_BONUS) for p in POPULAR_TEAMS]
        + [(p, LATAM_TEAM_BONUS) for p in LATAM_TEAMS]
    )
    word = [(g, int(w)) for g, w in GAME_WEIGHTS.items() if g != "other"]
    return league, team, word


def _cybersport_weights() -> Tuple[
    List[Tuple[str, int]], List[Tuple[str, int]], List[Tuple[str, int]]
]:
    """Admin-editable (league, team, word) weights for cybersport.

    Reads the DB provider (seeded from the static lists the first time); falls
    back to the static lists if the provider/DB is unavailable, so this module
    stays importable and deterministic without a database.
    """
    try:
        from app.services.weights_provider import get_weights

        ws = get_weights("cybersport")
        if ws.league or ws.team or ws.word:
            return list(ws.league), list(ws.team), list(ws.word)
    except Exception:
        pass
    return _cybersport_static_weights()


def game_weight(event: Dict[str, Any]) -> int:
    game = detect_game(tournament_name(event))
    _, _, word = _cybersport_weights()
    word_points = {normalize(p): int(w) for p, w in word}
    val = word_points.get(normalize(game))
    if val is not None:
        return val
    # Detected game not in the editable table (e.g. "other") -> static default.
    return int(GAME_WEIGHTS.get(game, GAME_WEIGHTS.get("other", 0)))


def tournament_weight(event: Dict[str, Any]) -> int:
    # Best matching tournament weight (table seeded from the tier lists, so a
    # Tier-1 event still scores its Tier-1 value until an admin edits it).
    league, _, _ = _cybersport_weights()
    return _best_weight(tournament_name(event), league)


def team_weight(event: Dict[str, Any]) -> int:
    # Each recognised side now contributes its own editable weight. (Previously
    # one shared popular/LATAM bonus applied once even if both sides matched.)
    _, team, _ = _cybersport_weights()
    return _best_weight(home_name(event), team) + _best_weight(away_name(event), team)


def academy_penalty(event: Dict[str, Any]) -> int:
    if contains_any(home_name(event), ACADEMY_PATTERNS) or contains_any(away_name(event), ACADEMY_PATTERNS):
        return ACADEMY_PENALTY
    return 0


def qualifier_penalty(event: Dict[str, Any]) -> int:
    if contains_any(tournament_name(event), QUALIFIER_PATTERNS):
        return QUALIFIER_PENALTY
    return 0


def low_signal_format_penalty(event: Dict[str, Any]) -> int:
    t_name = tournament_name(event)
    m_name = market_name(event)

    if contains_any(t_name, LOW_SIGNAL_FORMAT_PATTERNS) or contains_any(m_name, LOW_SIGNAL_FORMAT_PATTERNS):
        return LOW_SIGNAL_FORMAT_PENALTY

    return 0


def mobile_low_priority_penalty(event: Dict[str, Any]) -> int:
    if contains_any(tournament_name(event), MOBILE_LOW_PRIORITY_PATTERNS):
        return MOBILE_LOW_PRIORITY_PENALTY

    return 0


def live_bonus(event: Dict[str, Any]) -> int:
    if normalize(event.get("status")) != "live":
        return 0

    stage = parse_map_stage(time_raw(event))
    tier3 = is_tier3_tournament(event)

    if tier3:
        bonus = 30
        if stage is not None:
            tier3_map_bonus = {
                1: 5,
                2: 12,
                3: 20,
                4: 25,
                5: 25,
            }
            bonus += tier3_map_bonus.get(stage, 0)
        elif normalize(time_raw(event)) == "live":
            bonus += 10
        elif normalize(time_raw(event)) == "descanso":
            bonus += 10
        return bonus

    bonus = LIVE_BONUS

    if stage is not None:
        bonus += MAP_STAGE_BONUS.get(stage, MAP_STAGE_BONUS.get(5, 0))
    elif normalize(time_raw(event)) == "live":
        bonus += LIVE_GENERIC_STAGE_BONUS
    elif normalize(time_raw(event)) == "descanso":
        bonus += LIVE_GENERIC_STAGE_BONUS

    return bonus


def odds_bonus(event: Dict[str, Any]) -> int:
    odds = odds_dict(event)

    try:
        p1 = float(str(odds.get("p1")).replace(",", "."))
        p2 = float(str(odds.get("p2")).replace(",", "."))
    except Exception:
        return 0

    if p1 <= 1.15 or p2 <= 1.15:
        return ODDS_EXTREME_FAVORITE_PENALTY

    if p1 <= 1.20 or p2 <= 1.20:
        return ODDS_HEAVY_FAVORITE_PENALTY

    diff = abs(p1 - p2)

    if diff < 0.30:
        return ODDS_COINFLIP_BONUS

    if diff < 0.50:
        return ODDS_CLOSE_BONUS

    return 0


# -------------------------
# Main scoring
# -------------------------
def score_event(event: Dict[str, Any]) -> int:
    score = BASE_SCORE

    score += game_weight(event)
    score += tournament_weight(event)
    score += team_weight(event)

    score += academy_penalty(event)
    score += qualifier_penalty(event)
    score += low_signal_format_penalty(event)
    score += mobile_low_priority_penalty(event)

    score += live_bonus(event)
    score += odds_bonus(event)

    return score


# -------------------------
# HOT picker
# -------------------------
def pick_hot(
    events: List[Dict[str, Any]],
    limit: int = 5,
    timezone: Optional[str] = None,
    debug: bool = False,
    single_league: bool = False,
) -> Dict[str, Any]:
    limit = max(1, int(limit))
    # When the caller has already filtered to a single tournament (auto
    # campaign with league set), disable the per-tournament cap so we don't
    # cut the result down to MAX_PER_TOURNAMENT below the requested limit.
    per_tournament_cap = limit if single_league else MAX_PER_TOURNAMENT

    scored: List[Tuple[int, Dict[str, Any]]] = []

    for event in events:
        if is_hard_excluded(event):
            continue

        score = score_event(event)
        scored.append((score, event))

    scored.sort(key=lambda x: x[0], reverse=True)

    selected: List[Dict[str, Any]] = []
    per_team: Dict[str, int] = {}
    per_tournament: Dict[str, int] = {}

    for score, event in scored:
        if len(selected) >= limit:
            break

        h = normalize(home_name(event))
        a = normalize(away_name(event))
        t = normalize(tournament_name(event))

        if per_team.get(h, 0) >= MAX_PER_TEAM:
            continue
        if per_team.get(a, 0) >= MAX_PER_TEAM:
            continue
        if per_tournament.get(t, 0) >= per_tournament_cap:
            continue

        per_team[h] = per_team.get(h, 0) + 1
        per_team[a] = per_team.get(a, 0) + 1
        per_tournament[t] = per_tournament.get(t, 0) + 1

        event_out = dict(event)
        if debug:
            event_out["_score"] = score

        selected.append(event_out)

    return {
        "meta": {
            "limit": limit,
            "selected": len(selected),
            "timezone": timezone or FORCED_TIMEZONE,
            "single_league": bool(single_league),
        },
        "events": selected,
    }