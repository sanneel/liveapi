# hot_scoring.py | football

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timedelta
from functools import lru_cache
from typing import Any, Dict, Iterable, List, Optional, Tuple

from zoneinfo import ZoneInfo

from .weights_chile_first import (
    FORCED_TIMEZONE,
    EXCLUDE_TOURNAMENT_PATTERNS,
    EXCLUDE_TOURNAMENT_YOUTH_PATTERNS,
    LEAGUE_BOOST_PATTERNS,
    TEAM_BOOST_PATTERNS,
)
from .hot_weights_config import (
    HORIZON_DAYS as CFG_HORIZON_DAYS,
    TIME_BOOST_WITHIN_6H,
    TIME_BOOST_WITHIN_24H,
    TIME_BOOST_WITHIN_48H,
    TIME_BOOST_WITHIN_72H,
    TIME_BOOST_WITHIN_96H,
    LIVE_BOOST,
    LIVE_BOOST_REQUIRES_PRIORITY,
    MAX_LIVE as CFG_MAX_LIVE,
    MAX_PER_TOURNAMENT as CFG_MAX_PER_TOURNAMENT,
    MAX_PER_TEAM as CFG_MAX_PER_TEAM,
    REQUIRE_MIN_PREMATCH as CFG_REQUIRE_MIN_PREMATCH,
    EXCLUDE_YOUTH as CFG_EXCLUDE_YOUTH,
)


# -------------------------
# Normalization / matching
# -------------------------

_PUNCT_RE = re.compile(r"[,\.\(\)\[\]\{\}\-\_\/]+")
_SPACES_RE = re.compile(r"\s+")


@lru_cache(maxsize=8192)
def normalize(text: Optional[str]) -> str:
    if not text:
        return ""
    s = text.strip().lower()
    # remove accents/diacritics: "mañana" -> "manana"
    s = unicodedata.normalize("NFKD", s)
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    s = _PUNCT_RE.sub(" ", s)
    s = _SPACES_RE.sub(" ", s).strip()
    return s


def contains_pattern(text: str, pattern: str) -> bool:
    return normalize(pattern) in normalize(text)


def first_matching_weight(text: str, patterns: List[Tuple[str, int]]) -> Tuple[int, Optional[str]]:
    nt = normalize(text)
    for pat, w in patterns:
        if normalize(pat) in nt:
            return w, pat
    return 0, None


def sum_matching_weights(text: str, patterns: List[Tuple[str, int]]) -> Tuple[int, List[Tuple[str, int]]]:
    """
    Football league weights:
      - pick ONE best 'tier' match (avoid double-counting like broad+specific)
      - still add additive modifiers if they appear in the future

    Right now your football weights are mostly tier-like, so this mainly
    protects against order-dependent weaker matches winning over stronger ones.
    """
    nt = normalize(text)

    TIER_KEYS = {
        "division",
        "liga",
        "league",
        "serie",
        "bundesliga",
        "ligue",
        "libertadores",
        "sudamericana",
        "champions league",
        "europa league",
        "conference league",
        "copa",
        "cup",
        "primera",
        "laliga",
        "fifa",
    }

    def is_tier_pattern(pat: str) -> bool:
        p = normalize(pat)
        return any(k in p for k in TIER_KEYS)

    total = 0
    matched: List[Tuple[str, int]] = []
    best_tier: Optional[Tuple[str, int]] = None  # (pat, w)

    for pat, w in patterns:
        if normalize(pat) in nt:
            if is_tier_pattern(pat):
                if best_tier is None or w > best_tier[1]:
                    best_tier = (pat, w)
            else:
                total += w
                matched.append((pat, w))

    if best_tier is not None:
        total += best_tier[1]
        matched.append(best_tier)

    return total, matched


# -------------------------
# Time parsing (Chile TZ)
# -------------------------

_MONTHS = {
    # english-like 3-letter
    "jan": 1,
    "feb": 2,
    "mar": 3,
    "apr": 4,
    "may": 5,
    "jun": 6,
    "jul": 7,
    "aug": 8,
    "sep": 9,
    "oct": 10,
    "nov": 11,
    "dec": 12,
    # spanish (often same, but keep extra just in case)
    "ene": 1,
    "abr": 4,
    "ago": 8,
    "dic": 12,
}

_DATE_RE = re.compile(r"\b(\d{1,2})\s+([a-z]{3})\s*(?:,)?\s*(\d{1,2}):(\d{2})\b")
_TIME_RE = re.compile(r"\b(\d{1,2}):(\d{2})\b")


def parse_start_time_chile(time_raw: Optional[str], now_cl: datetime) -> Optional[datetime]:
    """
    Parses prematch time formats (Chile timezone, because Playwright renders in America/Santiago):
      1) "14 feb, 00:30"
      2) "Mañana, 22:00" (also supports "Hoy, 17:00")
    Returns aware datetime in America/Santiago, or None if unknown/not prematch time.
    """
    if not time_raw:
        return None

    s_norm = normalize(time_raw)

    # 2) "hoy, HH:MM"
    if "hoy" in s_norm:
        m = _TIME_RE.search(s_norm)
        if not m:
            return None
        hh, mm = int(m.group(1)), int(m.group(2))
        return now_cl.replace(hour=hh, minute=mm, second=0, microsecond=0)

    # 2) "manana, HH:MM" (mañana -> manana after normalize)
    if "manana" in s_norm:
        m = _TIME_RE.search(s_norm)
        if not m:
            return None
        hh, mm = int(m.group(1)), int(m.group(2))
        dt = (now_cl + timedelta(days=1)).replace(hour=hh, minute=mm, second=0, microsecond=0)
        return dt

    # 1) "14 feb, 00:30"
    m = _DATE_RE.search(s_norm)
    if m:
        day = int(m.group(1))
        mon = m.group(2)
        hh = int(m.group(3))
        mm = int(m.group(4))
        month = _MONTHS.get(mon)
        if not month:
            return None

        tz = now_cl.tzinfo
        year = now_cl.year
        dt = datetime(year, month, day, hh, mm, tzinfo=tz)

        # year roll rule: if parsed dt is "too far in the past", assume next year
        if dt < (now_cl - timedelta(days=1)):
            dt = datetime(year + 1, month, day, hh, mm, tzinfo=tz)

        return dt

    # Otherwise (likely live string like "1ª parte 44'") -> None
    return None


# -------------------------
# Scoring
# -------------------------


@dataclass
class ScoredEvent:
    event: Dict[str, Any]
    score: int
    reasons: List[str]


def _football_weights() -> Tuple[
    List[Tuple[str, int]], List[Tuple[str, int]], List[Tuple[str, int]]
]:
    """Return (league, team, word) weight lists for football scoring.

    Reads the admin-editable DB weights (`hot_weight` table) via the weights
    provider, which seeds itself from the static lists below the first time.
    Falls back to the static module lists if the provider/DB is unavailable
    (e.g. running the scorer in isolation or in a test), so this module stays
    importable and deterministic without a database.
    """
    try:
        from app.services.weights_provider import get_weights

        ws = get_weights("football")
        if ws.league or ws.team or ws.word:
            return list(ws.league), list(ws.team), list(ws.word)
    except Exception:
        pass
    return list(LEAGUE_BOOST_PATTERNS), list(TEAM_BOOST_PATTERNS), []


def is_excluded_tournament(tournament_name: str, exclude_youth: bool = True) -> bool:
    nt = normalize(tournament_name)
    for p in EXCLUDE_TOURNAMENT_PATTERNS:
        if normalize(p) in nt:
            return True
    if exclude_youth:
        for p in EXCLUDE_TOURNAMENT_YOUTH_PATTERNS:
            if normalize(p) in nt:
                return True
    return False


def _is_market_1x2(event: Dict[str, Any]) -> bool:
    """
    Only allow hot scoring for true 1x2.
    New parser emits event["market"]["type"].
    For backward compatibility: if no market.type exists, we fall back to old behavior.
    """
    market = event.get("market") or {}
    mtype = (market.get("type") or "").strip().lower()
    if mtype:
        return mtype == "1x2"
    # backward-compat: older payloads have only odds_1x2
    return True


def compute_score(
    event: Dict[str, Any],
    now_cl: datetime,
    horizon_days: int = CFG_HORIZON_DAYS,
    exclude_youth: bool = CFG_EXCLUDE_YOUTH,
) -> Optional[ScoredEvent]:
    """
    Returns ScoredEvent or None (excluded).
    """
    # 1) Only 1x2 events are eligible for hot
    if not _is_market_1x2(event):
        return None

    market = event.get("market") or {}
    odds = market.get("odds") or {}

    p1 = odds.get("p1")
    draw = odds.get("draw")
    p2 = odds.get("p2")

    def _is_valid_odd(v: Any) -> bool:
        if not v:
            return False
        s = str(v).strip()
        if s in {"-", "−", "−,−"}:
            return False
        try:
            float(s.replace(",", "."))
            return True
        except Exception:
            return False

    if not (_is_valid_odd(p1) and _is_valid_odd(draw) and _is_valid_odd(p2)):
        return None

    tournament = (event.get("tournament") or {}).get("name") or ""
    if is_excluded_tournament(tournament, exclude_youth=exclude_youth):
        return None

    reasons: List[str] = []
    score = 0

    status = event.get("status")  # already based on score presence

    # Admin-editable weights (DB-backed; falls back to static lists).
    league_patterns, team_patterns, word_patterns = _football_weights()

    # League boost: best tier + additive modifiers
    league_points = 0
    lb_total, lb_matched = sum_matching_weights(tournament, league_patterns)
    if lb_total:
        league_points += lb_total
        score += lb_total
        for pat, w in lb_matched:
            reasons.append(f"LEAGUE({pat}){w:+d}")

    # Team boosts
    team_points = 0
    home = ((event.get("competitors") or {}).get("home") or {}).get("name") or ""
    away = ((event.get("competitors") or {}).get("away") or {}).get("name") or ""

    hb, hpat = first_matching_weight(home, team_patterns)
    if hb:
        team_points += hb
        score += hb
        reasons.append(f"TEAM_HOME({hpat}){hb:+d}")

    ab, apat = first_matching_weight(away, team_patterns)
    if ab:
        team_points += ab
        score += ab
        reasons.append(f"TEAM_AWAY({apat}){ab:+d}")

    # Keyword ('word') weights — generic catch-all matched against the
    # tournament name + both team names. Each matching keyword counts once.
    word_points = 0
    if word_patterns:
        haystack = f"{tournament} {home} {away}"
        nt = normalize(haystack)
        for pat, w in word_patterns:
            if normalize(pat) in nt:
                word_points += w
                score += w
                reasons.append(f"WORD({pat}){w:+d}")

    # LIVE boost rule (tunable in hot_weights_config.LIVE_BOOST):
    # When LIVE_BOOST_REQUIRES_PRIORITY=True, only boost live matches that
    # already earned league/team points — keeps random live games from
    # outranking a boosted prematch.
    if status == "live":
        eligible = (league_points + team_points + word_points) > 0 if LIVE_BOOST_REQUIRES_PRIORITY else True
        if eligible:
            score += LIVE_BOOST
            reasons.append(f"LIVE(+{LIVE_BOOST}|boosted)")
        else:
            reasons.append("LIVE(+0|no-boost)")

    # Prematch time window + boost
    if status == "prematch":
        time_raw = ((event.get("time") or {}).get("raw")) or ""
        start = parse_start_time_chile(time_raw, now_cl)
        if not start:
            # If we cannot parse time, it’s safer to exclude from "hot"
            return None

        delta = start - now_cl
        if delta > timedelta(days=horizon_days):
            return None
        if delta.total_seconds() < -3600:
            # already started but no score? (rare/edge)
            # keep but don’t boost much:
            reasons.append("TIME(past?)")
        else:
            tb = time_boost(delta)
            score += tb
            reasons.append(f"TIME+{tb}")

    return ScoredEvent(event=event, score=score, reasons=reasons)


def time_boost(delta: timedelta) -> int:
    """Time-to-match boost. Buckets are tunable via hot_weights_config."""
    secs = max(0, int(delta.total_seconds()))
    if secs <= 6 * 3600:
        return TIME_BOOST_WITHIN_6H
    if secs <= 24 * 3600:
        return TIME_BOOST_WITHIN_24H
    if secs <= 2 * 24 * 3600:
        return TIME_BOOST_WITHIN_48H
    if secs <= 3 * 24 * 3600:
        return TIME_BOOST_WITHIN_72H
    return TIME_BOOST_WITHIN_96H  # up to horizon_days; > horizon already excluded


# -------------------------
# Selection (diversity)
# -------------------------


def pick_hot(
    events: Iterable[Dict[str, Any]],
    limit: int = 5,
    timezone: str = FORCED_TIMEZONE,
    horizon_days: int = CFG_HORIZON_DAYS,
    max_live: int = CFG_MAX_LIVE,
    max_per_tournament: int = CFG_MAX_PER_TOURNAMENT,
    max_per_team: int = CFG_MAX_PER_TEAM,
    require_min_prematch: int = CFG_REQUIRE_MIN_PREMATCH,
    exclude_youth: bool = CFG_EXCLUDE_YOUTH,
    debug: bool = False,
    single_league: bool = False,
) -> Dict[str, Any]:
    """
    Returns payload:
      { meta: {...}, events: [...] }
    If debug=True, each event includes: _hot_score, _hot_reasons

    When single_league=True (auto campaign filtered to one league):
      - max_per_tournament cap is disabled; the user explicitly wants every
        eligible match in that one tournament.
      - require_min_prematch is disabled; without it the picker can swap a
        hot live match for a weaker prematch from "another tournament" that
        does not exist in single-league mode.
    """
    limit = max(1, min(int(limit), 50))
    if single_league:
        max_per_tournament = limit
        require_min_prematch = 0

    tz = ZoneInfo(timezone)
    now_cl = datetime.now(tz=tz)

    # Deduplicate by event_id (keep best score later)
    by_id: Dict[str, ScoredEvent] = {}

    for e in events:
        eid = str(e.get("event_id") or "")
        if not eid:
            continue
        se = compute_score(e, now_cl, horizon_days=horizon_days, exclude_youth=exclude_youth)
        if not se:
            continue
        prev = by_id.get(eid)
        if (prev is None) or (se.score > prev.score):
            by_id[eid] = se

    scored: List[ScoredEvent] = list(by_id.values())
    scored.sort(key=lambda x: x.score, reverse=True)

    hot: List[ScoredEvent] = []
    live_count = 0
    prematch_count = 0
    per_tournament: Dict[str, int] = {}
    per_team: Dict[str, int] = {}

    def add_team(team: str) -> None:
        nt = normalize(team)
        if nt:
            per_team[nt] = per_team.get(nt, 0) + 1

    for se in scored:
        if len(hot) >= limit:
            break

        e = se.event
        status = e.get("status")

        tname = (e.get("tournament") or {}).get("name") or ""
        tkey = normalize(tname)
        if per_tournament.get(tkey, 0) >= max_per_tournament:
            continue

        home = ((e.get("competitors") or {}).get("home") or {}).get("name") or ""
        away = ((e.get("competitors") or {}).get("away") or {}).get("name") or ""

        if max_per_team > 0:
            if per_team.get(normalize(home), 0) >= max_per_team:
                continue
            if per_team.get(normalize(away), 0) >= max_per_team:
                continue

        if status == "live" and live_count >= max_live:
            continue

        # accept
        hot.append(se)
        per_tournament[tkey] = per_tournament.get(tkey, 0) + 1
        add_team(home)
        add_team(away)

        if status == "live":
            live_count += 1
        else:
            prematch_count += 1

    # Ensure at least 1 prematch if possible
    if require_min_prematch > 0 and prematch_count < require_min_prematch:
        # find best prematch not already included
        included_ids = {str(x.event.get("event_id")) for x in hot}
        best_prematch = next(
            (
                x
                for x in scored
                if x.event.get("status") == "prematch"
                and str(x.event.get("event_id")) not in included_ids
            ),
            None,
        )
        if best_prematch and hot:
            # replace the weakest live (if any)
            weakest_live_idx = None
            weakest_live_score = 10**9
            for i, x in enumerate(hot):
                if x.event.get("status") == "live" and x.score < weakest_live_score:
                    weakest_live_idx = i
                    weakest_live_score = x.score
            if weakest_live_idx is not None:
                hot[weakest_live_idx] = best_prematch

    out_events: List[Dict[str, Any]] = []
    for se in hot:
        e = dict(se.event)
        if debug:
            e["_hot_score"] = se.score
            e["_hot_reasons"] = se.reasons
        out_events.append(e)

    return {
        "meta": {
            "timezone": timezone,
            "generated_at_epoch": int(now_cl.timestamp()),
            "limit": limit,
            "horizon_days": horizon_days,
            "max_live": max_live,
            "max_per_tournament": max_per_tournament,
            "max_per_team": max_per_team,
            "require_min_prematch": require_min_prematch,
            "single_league": bool(single_league),
            "debug": bool(debug),
            "candidates_scored": len(scored),
        },
        "events": out_events,
    }