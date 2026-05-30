#hot_scoring_fights.py
#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import re
import unicodedata
from datetime import datetime, timedelta
from functools import lru_cache
from typing import Any, Dict, List, Optional, Tuple

from zoneinfo import ZoneInfo

from weights_fights_chile_first import (
    ALLOWED_MARKET_TYPES,
    BASE_SCORE,
    BOTH_CHILE_FIGHTERS_BONUS,
    BOTH_GLOBAL_STARS_BONUS,
    BOTH_LATAM_FIGHTERS_BONUS,
    CHILE_FIGHTER_BONUS,
    CHILE_FIGHTERS,
    CROSSOVER_BIG_FIGHT_BONUS,
    FEATURED_TOURNAMENT_BONUS,
    FEATURED_TOURNAMENT_PATTERNS,
    FORCED_TIMEZONE,
    GLOBAL_FIGHT_STARS,
    GLOBAL_FIGHT_STAR_BONUS,
    HARD_EXCLUDE_MARKET_NAME_PATTERNS,
    HARD_EXCLUDE_TOURNAMENT_PATTERNS,
    LATAM_FIGHTERS,
    LATAM_FIGHTER_BONUS,
    LIVE_BONUS,
    LONGSHOT_10_PLUS_PENALTY,
    LONGSHOT_5_PLUS_PENALTY,
    LONGSHOT_8_PLUS_PENALTY,
    MAX_PER_FIGHTER,
    MAX_PER_SPORT,
    MAX_PER_TOURNAMENT,
    ODDS_ABSURD_FAVORITE_PENALTY,
    ODDS_CLOSE_BONUS,
    ODDS_COINFLIP_BONUS,
    ODDS_DECENT_BONUS,
    ODDS_EXTREME_FAVORITE_PENALTY,
    ODDS_HEAVY_FAVORITE_PENALTY,
    SPORT_BASE_WEIGHTS,
    STARTS_TODAY_BONUS,
    STARTS_TOMORROW_BONUS,
    STARTS_WITHIN_2_DAYS_BONUS,
    STARTS_WITHIN_4_DAYS_BONUS,
    TIER1_TOURNAMENT_PATTERNS,
    TIER2_TOURNAMENT_PATTERNS,
    TIER3_TOURNAMENT_PATTERNS,
    TOURNAMENT_TIER1_BONUS,
    TOURNAMENT_TIER2_BONUS,
    TOURNAMENT_TIER3_BONUS,
    UFC_PROMOTION_BONUS,
)

# -------------------------
# Text helpers
# -------------------------
_SPACES_RE = re.compile(r"\s+")

_MONTHS_ES = {
    "ene": 1,
    "feb": 2,
    "mar": 3,
    "abr": 4,
    "may": 5,
    "jun": 6,
    "jul": 7,
    "ago": 8,
    "sep": 9,
    "oct": 10,
    "nov": 11,
    "dic": 12,
}


@lru_cache(maxsize=8192)
def normalize(text: Optional[str]) -> str:
    if not text:
        return ""
    s = str(text).strip().lower()
    s = unicodedata.normalize("NFKD", s)
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    s = s.replace("’", "'")
    s = _SPACES_RE.sub(" ", s)
    return s


def contains_any(text: Optional[str], patterns: List[str]) -> bool:
    s = normalize(text)
    return any(normalize(p) in s for p in patterns)


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


def parse_odd(value: Any) -> Optional[float]:
    if not is_valid_odd(value):
        return None
    try:
        return float(str(value).strip().replace(",", "."))
    except Exception:
        return None


# -------------------------
# Event field helpers
# -------------------------
def sport_name(event: Dict[str, Any]) -> str:
    return normalize(event.get("sport"))


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


def status_name(event: Dict[str, Any]) -> str:
    return normalize(event.get("status"))


def time_raw(event: Dict[str, Any]) -> str:
    return ((event.get("time") or {}).get("raw")) or ""


def odds_dict(event: Dict[str, Any]) -> Dict[str, Any]:
    return (((event.get("market") or {}).get("odds")) or {})


# -------------------------
# Time parsing
# -------------------------
def parse_time_raw(raw: str, now_local: datetime) -> Optional[datetime]:
    s = " ".join(str(raw or "").replace("\xa0", " ").strip().split())
    if not s:
        return None

    s_norm = normalize(s)

    # Hoy, 19:00 / Hoy , 19:00
    m = re.match(r"^hoy\s*,?\s*(\d{1,2}):(\d{2})$", s_norm)
    if m:
        hh = int(m.group(1))
        mm = int(m.group(2))
        return now_local.replace(hour=hh, minute=mm, second=0, microsecond=0)

    # Mañana, 00:00 / Manana , 00:00
    m = re.match(r"^manana\s*,?\s*(\d{1,2}):(\d{2})$", s_norm)
    if m:
        hh = int(m.group(1))
        mm = int(m.group(2))
        dt = now_local.replace(hour=hh, minute=mm, second=0, microsecond=0)
        return dt + timedelta(days=1)

    # 15 mar, 01:00
    m = re.match(r"^(\d{1,2})\s+([a-z]{3})\s*,?\s*(\d{1,2}):(\d{2})$", s_norm)
    if m:
        day = int(m.group(1))
        mon = _MONTHS_ES.get(m.group(2))
        hh = int(m.group(3))
        mm = int(m.group(4))
        if mon is None:
            return None

        year = now_local.year
        try:
            dt = datetime(year, mon, day, hh, mm, tzinfo=now_local.tzinfo)
        except Exception:
            return None

        # Якщо дата виглядає як уже минула більше ніж на 30 днів,
        # вважаємо що це наступний рік.
        if dt < now_local - timedelta(days=30):
            try:
                dt = datetime(year + 1, mon, day, hh, mm, tzinfo=now_local.tzinfo)
            except Exception:
                return None

        return dt

    return None


def is_within_horizon(event: Dict[str, Any], now_local: datetime, horizon_days: int) -> bool:
    dt = parse_time_raw(time_raw(event), now_local)
    if dt is None:
        return False

    delta = dt - now_local
    if delta.total_seconds() < 0:
        return False

    return delta <= timedelta(days=horizon_days)


# -------------------------
# Hard exclude
# -------------------------
def is_hard_excluded(event: Dict[str, Any], now_local: datetime, horizon_days: int) -> bool:
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

    if not is_within_horizon(event, now_local, horizon_days):
        return True

    return False


# -------------------------
# Weights
# -------------------------
def _best_weight(text: str, patterns: List[Tuple[str, int]]) -> int:
    """Points of the highest-value weight whose pattern appears in `text`."""
    nt = normalize(text)
    for pat, w in patterns:
        if normalize(pat) in nt:
            return int(w)
    return 0


def _sum_weights(text: str, patterns: List[Tuple[str, int]]) -> int:
    """Sum of every matching weight (featured + tier add together)."""
    nt = normalize(text)
    total = 0
    for pat, w in patterns:
        if normalize(pat) in nt:
            total += int(w)
    return total


def _fights_static_weights() -> Tuple[
    List[Tuple[str, int]], List[Tuple[str, int]], List[Tuple[str, int]]
]:
    """Rebuild (league, team, word) weight lists from the static module — used
    as a fallback when the DB provider is unavailable (tests / isolation)."""
    league = (
        [(p, TOURNAMENT_TIER1_BONUS) for p in TIER1_TOURNAMENT_PATTERNS]
        + [(p, TOURNAMENT_TIER2_BONUS) for p in TIER2_TOURNAMENT_PATTERNS]
        + [(p, FEATURED_TOURNAMENT_BONUS) for p in FEATURED_TOURNAMENT_PATTERNS]
    )
    team = (
        [(p, CHILE_FIGHTER_BONUS) for p in CHILE_FIGHTERS]
        + [(p, LATAM_FIGHTER_BONUS) for p in LATAM_FIGHTERS]
        + [(p, GLOBAL_FIGHT_STAR_BONUS) for p in GLOBAL_FIGHT_STARS]
    )
    word = [(s, int(w)) for s, w in SPORT_BASE_WEIGHTS.items() if s != "other"]
    return league, team, word


def _fights_weights(sport: str) -> Tuple[
    List[Tuple[str, int]], List[Tuple[str, int]], List[Tuple[str, int]]
]:
    """Admin-editable (league, team, word) weights for one combat sport.

    The fight scorer covers ufc / mma / boxing, each of which is an independent
    editable slice; we read the slice matching the event's sport so an edit to
    e.g. boxing only affects boxing. Falls back to the shared static lists if
    the provider/DB is unavailable.
    """
    slug = sport if sport in ("ufc", "mma", "boxing") else "ufc"
    try:
        from app.services.weights_provider import get_weights

        ws = get_weights(slug)
        if ws.league or ws.team or ws.word:
            return list(ws.league), list(ws.team), list(ws.word)
    except Exception:
        pass
    return _fights_static_weights()


def sport_weight(event: Dict[str, Any]) -> int:
    s = sport_name(event)
    _, _, word = _fights_weights(s)
    word_points = {normalize(p): int(w) for p, w in word}
    base = word_points.get(normalize(s))
    if base is None:
        base = int(SPORT_BASE_WEIGHTS.get(s, SPORT_BASE_WEIGHTS.get("other", 0)))
    if s == "ufc":
        base += int(UFC_PROMOTION_BONUS)
    return base


def tournament_weight(event: Dict[str, Any]) -> int:
    # Featured + tier weights add together (seeded from the static tiers, so
    # scoring is unchanged until an admin edits a row).
    league, _, _ = _fights_weights(sport_name(event))
    return _sum_weights(tournament_name(event), league)


def fighter_weight(event: Dict[str, Any]) -> int:
    h = home_name(event)
    a = away_name(event)

    # Per-fighter points come from the editable table now (seeded from the
    # Chile / LATAM / global-star lists). Each side adds its own value.
    _, team, _ = _fights_weights(sport_name(event))
    score = _best_weight(h, team) + _best_weight(a, team)

    # Bucket membership is still needed for the "both sides" combo bonuses,
    # which have no per-name representation and stay fixed in code.
    h_chile = contains_any(h, CHILE_FIGHTERS)
    a_chile = contains_any(a, CHILE_FIGHTERS)

    h_latam = contains_any(h, LATAM_FIGHTERS)
    a_latam = contains_any(a, LATAM_FIGHTERS)

    h_global = contains_any(h, GLOBAL_FIGHT_STARS)
    a_global = contains_any(a, GLOBAL_FIGHT_STARS)

    if h_chile and a_chile:
        score += BOTH_CHILE_FIGHTERS_BONUS

    if h_latam and a_latam:
        score += BOTH_LATAM_FIGHTERS_BONUS

    if h_global and a_global:
        score += BOTH_GLOBAL_STARS_BONUS

    left_any = h_chile or h_latam or h_global
    right_any = a_chile or a_latam or a_global
    if left_any and right_any:
        score += CROSSOVER_BIG_FIGHT_BONUS

    return score


def time_weight(event: Dict[str, Any], now_local: datetime) -> int:
    dt = parse_time_raw(time_raw(event), now_local)
    if dt is None:
        return 0

    delta = dt - now_local
    hours = delta.total_seconds() / 3600.0

    if hours < 0:
        return 0

    if dt.date() == now_local.date():
        return STARTS_TODAY_BONUS

    if dt.date() == (now_local + timedelta(days=1)).date():
        return STARTS_TOMORROW_BONUS

    if hours <= 48:
        return STARTS_WITHIN_2_DAYS_BONUS

    if hours <= 96:
        return STARTS_WITHIN_4_DAYS_BONUS

    return 0


def live_weight(event: Dict[str, Any]) -> int:
    if status_name(event) == "live":
        return LIVE_BONUS
    return 0


def odds_weight(event: Dict[str, Any]) -> int:
    odds = odds_dict(event)

    p1 = parse_odd(odds.get("p1"))
    p2 = parse_odd(odds.get("p2"))

    if p1 is None or p2 is None:
        return 0

    best = min(p1, p2)
    worst = max(p1, p2)
    diff = abs(p1 - p2)

    score = 0

    if diff <= 0.15:
        score += ODDS_COINFLIP_BONUS
    elif diff <= 0.35:
        score += ODDS_CLOSE_BONUS
    elif diff <= 0.60:
        score += ODDS_DECENT_BONUS

    if best <= 1.08:
        score += ODDS_ABSURD_FAVORITE_PENALTY
    elif best <= 1.15:
        score += ODDS_EXTREME_FAVORITE_PENALTY
    elif best <= 1.25:
        score += ODDS_HEAVY_FAVORITE_PENALTY

    if worst >= 10.0:
        score += LONGSHOT_10_PLUS_PENALTY
    elif worst >= 8.0:
        score += LONGSHOT_8_PLUS_PENALTY
    elif worst >= 5.0:
        score += LONGSHOT_5_PLUS_PENALTY

    return score


# -------------------------
# Main scoring
# -------------------------
def score_event(event: Dict[str, Any], now_local: datetime) -> int:
    score = BASE_SCORE

    score += sport_weight(event)
    score += tournament_weight(event)
    score += fighter_weight(event)
    score += time_weight(event, now_local)
    score += live_weight(event)
    score += odds_weight(event)

    return score


# -------------------------
# HOT picker
# -------------------------
def pick_hot(
    events: List[Dict[str, Any]],
    limit: int = 5,
    timezone: Optional[str] = None,
    debug: bool = False,
    horizon_days: int = 4,
    single_league: bool = False,
    single_sport: bool = False,
) -> Dict[str, Any]:
    limit = max(1, int(limit))
    # When the caller already filtered to one tournament, disable the
    # per-tournament cap so we don't cut below the requested limit.
    # When the caller has narrowed to a single canonical combat sport
    # (ufc / mma / boxing), the per-sport cap of 3 makes no sense — every
    # candidate is in that sport — so disable it too. MAX_PER_SPORT only
    # exists to balance the fights-union view (ufc+mma+boxing).
    per_tournament_cap = limit if (single_league or single_sport) else MAX_PER_TOURNAMENT
    per_sport_cap = limit if single_sport else MAX_PER_SPORT
    tz = ZoneInfo(timezone or FORCED_TIMEZONE)
    now_local = datetime.now(tz)

    scored: List[Tuple[int, Dict[str, Any]]] = []

    for event in events:
        if is_hard_excluded(event, now_local, horizon_days):
            continue

        score = score_event(event, now_local)
        scored.append((score, event))

    # Deterministic tiebreaker chain. Without it, equal-score events resolved
    # in DB insertion order, which churned between parser cycles. Order:
    #   1. higher score first
    #   2. live events before prematch
    #   3. UFC > MMA > boxing > other (sport priority)
    #   4. earlier start_time first (sooner = hotter)
    #   5. event_id ascending (final stable fallback)
    _SPORT_PRIORITY = {"ufc": 0, "mma": 1, "boxing": 2}

    def _tiebreak_key(item: Tuple[int, Dict[str, Any]]) -> Tuple:
        score, event = item
        is_live = 0 if status_name(event) == "live" else 1
        sport_rank = _SPORT_PRIORITY.get(sport_name(event), 9)
        dt = parse_time_raw(time_raw(event), now_local)
        # Use a far-future sentinel for unparseable times so they sort last.
        start_ts = dt.timestamp() if dt is not None else float("inf")
        eid = str(event.get("event_id") or "")
        return (-score, is_live, sport_rank, start_ts, eid)

    scored.sort(key=_tiebreak_key)

    selected: List[Dict[str, Any]] = []
    per_fighter: Dict[str, int] = {}
    per_tournament: Dict[str, int] = {}
    per_sport: Dict[str, int] = {}

    for score, event in scored:
        if len(selected) >= limit:
            break

        h = normalize(home_name(event))
        a = normalize(away_name(event))
        t = normalize(tournament_name(event))
        s = sport_name(event)

        if per_fighter.get(h, 0) >= MAX_PER_FIGHTER:
            continue
        if per_fighter.get(a, 0) >= MAX_PER_FIGHTER:
            continue
        if per_tournament.get(t, 0) >= per_tournament_cap:
            continue
        if per_sport.get(s, 0) >= per_sport_cap:
            continue

        per_fighter[h] = per_fighter.get(h, 0) + 1
        per_fighter[a] = per_fighter.get(a, 0) + 1
        per_tournament[t] = per_tournament.get(t, 0) + 1
        per_sport[s] = per_sport.get(s, 0) + 1

        event_out = dict(event)
        if debug:
            event_out["_score"] = score
            event_out["_sport"] = s
            event_out["_tournament_norm"] = t
            event_out["_time_parsed"] = (
                parse_time_raw(time_raw(event), now_local).isoformat()
                if parse_time_raw(time_raw(event), now_local) is not None
                else None
            )

        selected.append(event_out)

    return {
        "meta": {
            "limit": limit,
            "selected": len(selected),
            "timezone": timezone or FORCED_TIMEZONE,
            "horizon_days": horizon_days,
            "single_league": bool(single_league),
            "single_sport": bool(single_sport),
        },
        "events": selected,
    }