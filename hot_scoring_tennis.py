# hot_scoring_tennis.py

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timedelta
from functools import lru_cache
from typing import Any, Dict, Iterable, List, Optional, Tuple

from zoneinfo import ZoneInfo

from weights_tennis_chile_first import (
    FORCED_TIMEZONE,
    EXCLUDE_TOURNAMENT_PATTERNS,
    EXCLUDE_TOURNAMENT_YOUTH_PATTERNS,
    LEAGUE_BOOST_PATTERNS,
    TEAM_BOOST_PATTERNS,  # player boosts (kept name for compatibility)
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
    Tennis tournament weights:
      - pick ONE best 'tier' match (to avoid double-counting like: "atp." + "atp challenger" + "challenger")
      - still add all additive signals (geo/surface/penalties etc.)

    Heuristic:
      - consider a pattern 'tier-like' if it contains keywords below.
      - choose the highest weight among matched tier-like patterns.
    """
    nt = normalize(text)

    TIER_KEYS = {
        "atp", "wta", "challenger", "itf", "grand slam", "slam",
        "copa davis", "davis", "billie jean", "bjk", "fed cup",
        "olympic", "juegos olimpicos", "olimpicos",
    }

    def is_tier_pattern(pat: str) -> bool:
        p = normalize(pat)
        return any(k in p for k in TIER_KEYS)

    total = 0
    matched: List[Tuple[str, int]] = []

    best_tier: Optional[Tuple[str, int]] = None  # (pat, w)

    # First pass: collect matches
    for pat, w in patterns:
        if normalize(pat) in nt:
            if is_tier_pattern(pat):
                if best_tier is None or w > best_tier[1]:
                    best_tier = (pat, w)
            else:
                total += w
                matched.append((pat, w))

    # Add best tier only once
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

    return None


# -------------------------
# Tennis live parsing (Set X)
# -------------------------

_SET_RE = re.compile(r"\bset\s*(\d+)\b", re.IGNORECASE)


def parse_set_no(time_raw: Optional[str]) -> Optional[int]:
    """
    Examples:
      "Set 1" -> 1
      "Set 3" -> 3
    """
    if not time_raw:
        return None
    m = _SET_RE.search(str(time_raw))
    if not m:
        return None
    try:
        n = int(m.group(1))
        if 1 <= n <= 7:
            return n
    except Exception:
        return None
    return None


# -------------------------
# Scoring
# -------------------------

@dataclass
class ScoredEvent:
    event: Dict[str, Any]
    score: int
    reasons: List[str]


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


def _is_market_winner(event: Dict[str, Any]) -> bool:
    market = event.get("market") or {}
    mtype = (market.get("type") or "").strip().lower()
    return mtype == "winner"


def _parse_odd_strict(v: Any) -> Optional[float]:
    """
    STRICT: must be parseable float and > 1.0
    Rejects '-', '−', '−,−', empty, None.
    """
    if v is None:
        return None
    s = str(v).strip()
    if not s:
        return None
    if s in {"-", "−", "−,−"}:
        return None
    try:
        x = float(s.replace(",", "."))
        if x <= 1.0:
            return None
        # safety clamps against broken payloads
        if x < 1.01 or x > 100.0:
            return None
        return x
    except Exception:
        return None


def time_boost(delta: timedelta) -> int:
    secs = max(0, int(delta.total_seconds()))
    if secs <= 2 * 3600:
        return 70
    if secs <= 6 * 3600:
        return 60
    if secs <= 24 * 3600:
        return 55
    if secs <= 2 * 24 * 3600:
        return 50
    if secs <= 3 * 24 * 3600:
        return 45
    return 35  # up to horizon (excluded above)


def odds_balance_bonus(p1: float, p2: float) -> int:
    """
    Closer odds -> more interesting.
    Uses absolute difference as a simple proxy.
    """
    diff = abs(p1 - p2)
    if diff <= 0.20:
        return 35
    if diff <= 0.50:
        return 20
    if diff <= 1.00:
        return 8
    return 0


def heavy_favorite_penalty(p1: float, p2: float) -> int:
    """
    If match is almost decided (very low favorite), push down.
    Tuned to penalize 1.14 more clearly.
    """
    fav = min(p1, p2)
    if fav <= 1.12:
        return -45
    if fav <= 1.15:
        return -35
    if fav <= 1.20:
        return -25
    return 0


def set_stage_bonus(set_no: Optional[int]) -> int:
    if set_no is None:
        return 0
    if set_no == 1:
        return 0
    if set_no == 2:
        return 25
    if set_no == 3:
        return 70
    if set_no == 4:
        return 80
    if set_no >= 5:
        return 95
    return 0


def set_drama_bonus(set_no: Optional[int], sets_home: Any, sets_away: Any) -> int:
    """
    With your data, score.home/away are SETS won.
    Big drama = deciding set with 1-1 (BO3).
    """
    try:
        sh = int(sets_home) if sets_home is not None else 0
        sa = int(sets_away) if sets_away is not None else 0
    except Exception:
        sh, sa = 0, 0

    if set_no == 3 and sh == 1 and sa == 1:
        return 80  # must-watch
    if set_no == 2 and ((sh == 1 and sa == 0) or (sh == 0 and sa == 1)):
        return 25
    return 0


def compute_score(
    event: Dict[str, Any],
    now_cl: datetime,
    horizon_days: int = 4,
    exclude_youth: bool = True,
) -> Optional[ScoredEvent]:
    """
    Returns ScoredEvent or None (excluded).
    """
    # 1) Only WINNER events are eligible for hot tennis
    if not _is_market_winner(event):
        return None

    market = event.get("market") or {}
    odds = market.get("odds") or {}

    p1_raw = odds.get("p1")
    p2_raw = odds.get("p2")

    # STRICT: both odds must parse, else skip
    p1 = _parse_odd_strict(p1_raw)
    p2 = _parse_odd_strict(p2_raw)
    if p1 is None or p2 is None:
        return None

    tournament = (event.get("tournament") or {}).get("name") or ""
    if is_excluded_tournament(tournament, exclude_youth=exclude_youth):
        return None

    reasons: List[str] = []
    score = 0

    status = event.get("status")  # "live" or "prematch" (in your feed)

    # League/tournament boosts (additive for tennis)
    league_points = 0
    lb_total, lb_matched = sum_matching_weights(tournament, LEAGUE_BOOST_PATTERNS)
    if lb_total:
        league_points += lb_total
        score += lb_total
        for pat, w in lb_matched:
            reasons.append(f"LEAGUE({pat}){w:+d}")

    # Player boosts (Chile-first / stars)
    player_points = 0
    home = ((event.get("competitors") or {}).get("home") or {}).get("name") or ""
    away = ((event.get("competitors") or {}).get("away") or {}).get("name") or ""

    hb, hpat = first_matching_weight(home, TEAM_BOOST_PATTERNS)
    if hb:
        player_points += hb
        score += hb
        reasons.append(f"PLAYER_HOME({hpat})+{hb}")

    ab, apat = first_matching_weight(away, TEAM_BOOST_PATTERNS)
    if ab:
        player_points += ab
        score += ab
        reasons.append(f"PLAYER_AWAY({apat})+{ab}")

    # Odds: balance + heavy favorite penalty (applies to both prematch & live)
    ob = odds_balance_bonus(p1, p2)
    if ob:
        score += ob
        reasons.append(f"ODDS_BALANCE+{ob}")

    # We'll apply HEAVY_FAV a bit smarter for LIVE (after we know clutch)
    hp_raw = heavy_favorite_penalty(p1, p2)

    if status == "live":
        set_no = parse_set_no(((event.get("time") or {}).get("raw")) or "")
        sb = set_stage_bonus(set_no)
        if sb:
            score += sb
            reasons.append(f"SET_STAGE({set_no})+{sb}")

        sh = (event.get("score") or {}).get("home")
        sa = (event.get("score") or {}).get("away")
        db = set_drama_bonus(set_no, sh, sa)
        if db:
            score += db
            reasons.append(f"SET_DRAMA+{db}")

        # If super clutch (Set 3 and 1-1), reduce heavy favorite penalty impact
        if hp_raw != 0:
            try:
                sh_i = int(sh) if sh is not None else 0
                sa_i = int(sa) if sa is not None else 0
            except Exception:
                sh_i, sa_i = 0, 0

            is_super_clutch = (set_no == 3 and sh_i == 1 and sa_i == 1)
            hp = int(hp_raw * 0.5) if is_super_clutch else hp_raw
            if hp != 0:
                score += hp
                reasons.append(f"HEAVY_FAV{hp:+d}{'|clutch_half' if is_super_clutch else ''}")

        # Base live boost ONLY if tournament or players give relevance
        if (league_points + player_points) > 0:
            score += 300
            reasons.append("LIVE_BASE(+300|relevance_ok)")
        else:
            reasons.append("LIVE_BASE(+0|no_relevance)")

    else:
        # prematch (apply heavy favorite normally)
        if hp_raw != 0:
            score += hp_raw
            reasons.append(f"HEAVY_FAV{hp_raw:+d}")

    # PREMATCH: time window + boost
    if status == "prematch":
        time_raw = ((event.get("time") or {}).get("raw")) or ""
        start = parse_start_time_chile(time_raw, now_cl)
        if not start:
            return None

        delta = start - now_cl
        if delta > timedelta(days=horizon_days):
            return None

        if delta.total_seconds() < -3600:
            reasons.append("TIME(past?)")
        else:
            tb = time_boost(delta)
            score += tb
            reasons.append(f"TIME+{tb}")

    return ScoredEvent(event=event, score=score, reasons=reasons)


# -------------------------
# Selection (diversity)
# -------------------------

def pick_hot(
    events: Iterable[Dict[str, Any]],
    limit: int = 5,
    timezone: str = FORCED_TIMEZONE,
    horizon_days: int = 4,
    max_live: int = 2,
    max_per_tournament: int = 2,
    max_per_team: int = 1,  # for tennis: max_per_player (kept arg name for compatibility)
    require_min_prematch: int = 2,
    exclude_youth: bool = True,
    debug: bool = False,
    single_league: bool = False,
) -> Dict[str, Any]:
    """
    Returns payload:
      { meta: {...}, events: [...] }
    If debug=True, each event includes: _hot_score, _hot_reasons

    When single_league=True, the per-tournament cap and require_min_prematch
    swap are disabled so a league-filtered campaign returns up to `limit`
    matches from the single tournament.
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

    def add_team(name: str) -> None:
        # In tennis this is a "player key". For doubles it is the full string (with slashes),
        # which is fine for diversity limiting.
        nt = normalize(name)
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

    # Ensure at least N prematch if possible
    if require_min_prematch > 0 and prematch_count < require_min_prematch:
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