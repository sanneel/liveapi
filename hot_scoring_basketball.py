# hot_scoring_basketball.py
# (додай/встав у файл; блоки позначив коментарями де саме)

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timedelta
from functools import lru_cache
from typing import Any, Dict, Iterable, List, Optional, Tuple
from zoneinfo import ZoneInfo

from weights_basketball_chile_first import (
    FORCED_TIMEZONE,
    EXCLUDE_TOURNAMENT_PATTERNS,
    EXCLUDE_TOURNAMENT_YOUTH_PATTERNS,
    LEAGUE_BOOST_PATTERNS,
    TEAM_BOOST_PATTERNS,
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
    s = unicodedata.normalize("NFKD", s)
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    s = _PUNCT_RE.sub(" ", s)
    s = _SPACES_RE.sub(" ", s).strip()
    return s

def first_matching_weight(text: str, patterns: List[Tuple[str, int]]) -> Tuple[int, Optional[str]]:
    nt = normalize(text)
    for pat, w in patterns:
        if normalize(pat) in nt:
            return w, pat
    return 0, None

def sum_matching_weights(text: str, patterns: List[Tuple[str, int]]) -> Tuple[int, List[Tuple[str, int]]]:
    """
    Basketball league weights:
      - pick ONE best 'tier' match (avoid double counting like: "nba" + "nba. temporada regular")
      - still add additive modifiers (women/virtual penalties etc.) if you keep them here.
    """
    nt = normalize(text)

    TIER_KEYS = {
        # top tiers
        "nba", "euroleague", "euroliga", "acb", "liga endesa",
        "ncaa", "g league", "gleague", "nba g league",
        "lnb", "nbb", "vtb", "aba", "bcl", "champions league",
        # generic "liga" is NOT a tier key (too broad)
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

# ============================================================
# ✅ HARD EXCLUDE: virtual/esports/replay TEAMS (basketball)
# ============================================================

# 1) явні токени/слова (в команді)
_EXCLUDE_TEAM_PATTERNS = [
    "(v)",            # "Team (V)" / "USA (V)" і т.д.
    " virtual",       # "Virtual" у будь-якій формі (normalize прибере accents)
    "virtual ",       # на випадок країв
    " (virtual)",

    "replay",         # "Team (replay)" / "NBA match replay"
    "(replay)",

    "simulated",
    "simulation",
]

# 2) нікнейми в дужках (Dema21/Morzh/Nemo etc.) — вбиваємо ТІЛЬКИ якщо турнір явно esports/virtual
# (щоб не зачепити умовні "(f)" або "(u20)" в інших видах, якщо колись з'являться)
_BRACKET_NICK_RE = re.compile(r"\([^)]{2,}\)")  # будь-які дужки з 2+ символами

_ESPORTS_TOURNAMENT_HINTS = [
    "esports",
    "e sports",
    "e-sports",
    "esportsbattle",
    "e basketball",
    "e-baloncesto",
    "virtual",
    "simulated",
    "replay",
]

def _contains_any(nt: str, needles: List[str]) -> bool:
    return any(normalize(n) in nt for n in needles)

def is_virtual_team(home_name: str, away_name: str, tournament_name: str) -> bool:
    """
    Жорстко відсікаємо:
      - команду з (V)/virtual/replay/simulated у назві
      - ESportsBattle та подібне: якщо в команді є дужки-нікнейм і турнір виглядає як esports/virtual
    """
    hn = normalize(home_name)
    an = normalize(away_name)
    tn = normalize(tournament_name)

    # прямий exclude по назві команди
    if _contains_any(hn, _EXCLUDE_TEAM_PATTERNS) or _contains_any(an, _EXCLUDE_TEAM_PATTERNS):
        return True

    # якщо турнір має esports/virtual/replay hints — і в командах є "(...)" нікнейми
    if _contains_any(tn, _ESPORTS_TOURNAMENT_HINTS):
        if _BRACKET_NICK_RE.search(home_name or "") or _BRACKET_NICK_RE.search(away_name or ""):
            return True

    return False

# -------------------------
# Time parsing (Chile TZ)
# -------------------------

_MONTHS = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
    "ene": 1, "abr": 4, "ago": 8, "dic": 12,
}
_DATE_RE = re.compile(r"\b(\d{1,2})\s+([a-z]{3})\s*(?:,)?\s*(\d{1,2}):(\d{2})\b")
_TIME_RE = re.compile(r"\b(\d{1,2}):(\d{2})\b")

def parse_start_time_chile(time_raw: Optional[str], now_cl: datetime) -> Optional[datetime]:
    if not time_raw:
        return None
    s_norm = normalize(time_raw)

    if "hoy" in s_norm:
        m = _TIME_RE.search(s_norm)
        if not m:
            return None
        hh, mm = int(m.group(1)), int(m.group(2))
        return now_cl.replace(hour=hh, minute=mm, second=0, microsecond=0)

    if "manana" in s_norm:
        m = _TIME_RE.search(s_norm)
        if not m:
            return None
        hh, mm = int(m.group(1)), int(m.group(2))
        return (now_cl + timedelta(days=1)).replace(hour=hh, minute=mm, second=0, microsecond=0)

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
        if dt < (now_cl - timedelta(days=1)):
            dt = datetime(year + 1, month, day, hh, mm, tzinfo=tz)
        return dt

    return None

# -------------------------
# Scoring helpers
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
        if x < 1.01 or x > 100.0:
            return None
        return x
    except Exception:
        return None

def odds_balance_bonus(p1: float, p2: float) -> int:
    diff = abs(p1 - p2)
    if diff <= 0.20:
        return 30
    if diff <= 0.50:
        return 18
    if diff <= 1.00:
        return 7
    return 0

def heavy_favorite_penalty(p1: float, p2: float) -> int:
    fav = min(p1, p2)
    if fav <= 1.06:
        return -50
    if fav <= 1.10:
        return -40
    if fav <= 1.15:
        return -30
    if fav <= 1.20:
        return -18
    return 0

def time_boost(delta: timedelta) -> int:
    secs = max(0, int(delta.total_seconds()))
    if secs <= 2 * 3600:
        return 55
    if secs <= 6 * 3600:
        return 45
    if secs <= 24 * 3600:
        return 40
    if secs <= 2 * 24 * 3600:
        return 35
    if secs <= 3 * 24 * 3600:
        return 30
    return 25

# -------------------------
# ✅ Basketball live stage parsing
# -------------------------

_Q_RE = re.compile(r"\b([1-4])\s*[ºo]?\s*cuarto\b", re.IGNORECASE)
_OT_RE = re.compile(r"\bpro?rroga\b", re.IGNORECASE)

def parse_live_stage(time_raw: Optional[str]) -> Tuple[Optional[int], bool]:
    """
    Returns (quarter, is_overtime)
      "2º cuarto 9'" -> (2, False)
      "1er prórroga" -> (None, True)
      "Descanso" -> (None, False)
    """
    if not time_raw:
        return None, False
    s = normalize(time_raw)
    if _OT_RE.search(s):
        return None, True
    m = _Q_RE.search(s)
    if m:
        try:
            q = int(m.group(1))
            return q, False
        except Exception:
            return None, False
    return None, False

def live_stage_bonus(q: Optional[int], is_ot: bool) -> int:
    if is_ot:
        return 120
    if q is None:
        return 0
    if q <= 2:
        return 10
    if q == 3:
        return 35
    if q == 4:
        return 70
    return 0

def close_game_bonus(home: Any, away: Any) -> int:
    try:
        h = int(home)
        a = int(away)
    except Exception:
        return 0
    diff = abs(h - a)
    if diff <= 2:
        return 90
    if diff <= 5:
        return 55
    if diff <= 8:
        return 25
    return 0

def compute_score(
    event: Dict[str, Any],
    now_cl: datetime,
    horizon_days: int = 4,
    exclude_youth: bool = True,
) -> Optional[ScoredEvent]:
    # ✅ HOT тільки winner
    if not _is_market_winner(event):
        return None

    market = event.get("market") or {}
    odds = (market.get("odds") or {})
    p1 = _parse_odd_strict(odds.get("p1"))
    p2 = _parse_odd_strict(odds.get("p2"))
    # ✅ і тільки якщо ОБИДВА odds є
    if p1 is None or p2 is None:
        return None

    tournament = (event.get("tournament") or {}).get("name") or ""
    if is_excluded_tournament(tournament, exclude_youth=exclude_youth):
        return None

    home = ((event.get("competitors") or {}).get("home") or {}).get("name") or ""
    away = ((event.get("competitors") or {}).get("away") or {}).get("name") or ""

    # ============================================================
    # ✅ ЖОРСТКИЙ EXCLUDE: virtual/esports/replay TEAMS
    # ============================================================
    if is_virtual_team(home, away, tournament):
        return None

    reasons: List[str] = []
    score = 0

    status = (event.get("status") or "").strip().lower()  # "live" | "prematch"

    # League boosts
    league_points, lb_matched = sum_matching_weights(tournament, LEAGUE_BOOST_PATTERNS)
    if league_points:
        score += league_points
        for pat, w in lb_matched:
            reasons.append(f"LEAGUE({pat}){w:+d}")

    # Team boosts
    hb, hpat = first_matching_weight(home, TEAM_BOOST_PATTERNS)
    if hb:
        score += hb
        reasons.append(f"TEAM_HOME({hpat})+{hb}")
    ab, apat = first_matching_weight(away, TEAM_BOOST_PATTERNS)
    if ab:
        score += ab
        reasons.append(f"TEAM_AWAY({apat})+{ab}")

    # Odds
    ob = odds_balance_bonus(p1, p2)
    if ob:
        score += ob
        reasons.append(f"ODDS_BALANCE(p1p2)+{ob}")
    hp = heavy_favorite_penalty(p1, p2)
    if hp:
        score += hp
        reasons.append(f"HEAVY_FAV{hp:+d}")

    # Live vs prematch logic
    if status == "live":
        q, is_ot = parse_live_stage(((event.get("time") or {}).get("raw")) or "")
        sb = live_stage_bonus(q, is_ot)
        if sb:
            score += sb
            reasons.append(f"STAGE({('OT' if is_ot else q)})+{sb}")

        sh = (event.get("score") or {}).get("home")
        sa = (event.get("score") or {}).get("away")
        cb = close_game_bonus(sh, sa)
        if cb:
            score += cb
            reasons.append(f"CLOSE+{cb}")

        # LIVE boost: тільки якщо є реальна релевантність (NBA / топ-ліга / топ-команди)
        if (league_points + hb + ab) > 0:
            score += 140
            reasons.append("LIVE_TOP(+140)")
        else:
            score += 30
            reasons.append("LIVE_WEAK(+30)")
    else:
        # prematch time
        start = parse_start_time_chile(((event.get("time") or {}).get("raw")) or "", now_cl)
        if not start:
            return None
        delta = start - now_cl
        if delta > timedelta(days=horizon_days):
            return None

        tb = time_boost(delta)
        score += tb
        reasons.append(f"TIME+{tb}")

        # Prematch base only if relevance exists
        if (league_points + hb + ab) > 0:
            score += 40
            reasons.append("PRE_BASE(+40|relevance_ok)")

    return ScoredEvent(event=event, score=score, reasons=reasons)

def pick_hot(
    events: Iterable[Dict[str, Any]],
    limit: int = 5,
    timezone: str = FORCED_TIMEZONE,
    horizon_days: int = 4,
    max_live: int = 3,
    max_per_tournament: int = 3,
    max_per_team: int = 1,
    require_min_prematch: int = 2,
    debug: bool = False,
    single_league: bool = False,
) -> Dict[str, Any]:
    # See hot_scoring.pick_hot for single_league rationale.
    limit = max(1, min(int(limit), 50))
    if single_league:
        max_per_tournament = limit
        require_min_prematch = 0
    tz = ZoneInfo(timezone)
    now_cl = datetime.now(tz=tz)

    by_id: Dict[str, ScoredEvent] = {}
    for e in events:
        eid = str(e.get("event_id") or "")
        if not eid:
            continue
        se = compute_score(e, now_cl, horizon_days=horizon_days)
        if not se:
            continue
        prev = by_id.get(eid)
        if prev is None or se.score > prev.score:
            by_id[eid] = se

    scored = list(by_id.values())
    scored.sort(key=lambda x: x.score, reverse=True)

    hot: List[ScoredEvent] = []
    live_count = 0
    prem_count = 0
    per_tournament: Dict[str, int] = {}
    per_team: Dict[str, int] = {}

    def add_team(name: str) -> None:
        nt = normalize(name)
        if nt:
            per_team[nt] = per_team.get(nt, 0) + 1

    for se in scored:
        if len(hot) >= limit:
            break
        e = se.event
        status = (e.get("status") or "").strip().lower()

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

        hot.append(se)
        per_tournament[tkey] = per_tournament.get(tkey, 0) + 1
        add_team(home)
        add_team(away)

        if status == "live":
            live_count += 1
        else:
            prem_count += 1

    # enforce prematch minimum if possible
    if require_min_prematch > 0 and prem_count < require_min_prematch:
        included = {str(x.event.get("event_id")) for x in hot}
        best_prem = next((x for x in scored if (x.event.get("status") == "prematch") and str(x.event.get("event_id")) not in included), None)
        if best_prem:
            weakest_live_i = None
            weakest_live_score = 10**9
            for i, x in enumerate(hot):
                if x.event.get("status") == "live" and x.score < weakest_live_score:
                    weakest_live_i = i
                    weakest_live_score = x.score
            if weakest_live_i is not None:
                hot[weakest_live_i] = best_prem

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
            "winner_only": True,
        },
        "events": out_events,
    }
