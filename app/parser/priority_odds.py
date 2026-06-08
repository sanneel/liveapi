"""Priority odds parser — browserless HTTP loop keeping FEATURED odds live.

The heavy Playwright parser DISCOVERS matches (slow, and the part that fails).
This separate loop only refreshes ODDS for the leagues that contain a featured
match — active campaigns, hot pins, and the World Cup cube — by GETting each
league's overlay page (/<sport>/all/1?tournaments=<uuid>) and parsing the
embedded SSR JSON. Pure HTTP, so it's fast (~45s) and can't fail like the
browser feeds. It updates existing matches' odds only; discovery stays with the
main parser.

Featured league set, recomputed each pass:
  * World Cup tournament (the cube) — always
  * tournament of every match in an enabled campaign
  * tournament of every hot-pinned match
"""

from __future__ import annotations

import re
import threading
import time
from collections import defaultdict
from typing import Dict, List, Set, Tuple

from ..database import db_session
from ..logging_config import get_logger
from ..models import Campaign, HotBoost, Match
from ..models.campaign_match import CampaignMatch
from ..repositories.match_repo import MatchRepository
from .embedded_odds import fetch_embedded
from .extra_feeds import load_extra_feeds

_TID_RE = re.compile(r"tournaments=([0-9a-fA-F,]+)")

logger = get_logger("app.parser.priority_odds")

PRIORITY_INTERVAL_SECONDS = 45.0
WORLDCUP_TID = "c19cb5ffb4404c31b869b53dd90161de"
_SITE = "https://jugabet.cl"
# Sports whose overlay pages we know follow the /<sport>/all/1 pattern.
_KNOWN_SPORTS = {"football", "basketball", "tennis", "cybersport", "boxing", "mma", "ufc"}


def collect_priority_tids() -> Dict[str, Set[str]]:
    """Return {sport: {tournament_id, ...}} for every featured match's league."""
    out: Dict[str, Set[str]] = defaultdict(set)
    out["football"].add(WORLDCUP_TID)  # the cube is always priority
    try:
        with db_session() as s:
            campaign_rows = (
                s.query(Match.sport, Match.tournament_id)
                .join(CampaignMatch, CampaignMatch.event_id == Match.event_id)
                .join(Campaign, Campaign.slug == CampaignMatch.campaign_slug)
                .filter(Campaign.enabled.is_(True))
                .filter(Match.tournament_id.isnot(None))
                .distinct()
                .all()
            )
            hot_rows = (
                s.query(Match.sport, Match.tournament_id)
                .join(HotBoost, HotBoost.event_id == Match.event_id)
                .filter(HotBoost.position.isnot(None))
                .filter(Match.tournament_id.isnot(None))
                .distinct()
                .all()
            )
        for sport, tid in list(campaign_rows) + list(hot_rows):
            if sport in _KNOWN_SPORTS and tid:
                out[sport].add(str(tid))
    except Exception:
        logger.exception("priority_odds: collect_priority_tids failed")

    # Admin-added tournament-overlay links (Parser Links) become priority HTTP
    # parses too, so a league you add gets fast odds without the Playwright path.
    try:
        for feed in load_extra_feeds():
            if not feed.get("enabled", True):
                continue
            sport = str(feed.get("sport") or "")
            m = _TID_RE.search(str(feed.get("url") or ""))
            if sport in _KNOWN_SPORTS and m:
                for tid in m.group(1).split(","):
                    if tid:
                        out[sport].add(tid)
    except Exception:
        logger.exception("priority_odds: extra-feed tids failed")
    return out


def _overlay_url(sport: str, tid: str) -> str:
    return f"{_SITE}/{sport}/all/1?tournaments={tid}"


def refresh_once() -> Tuple[int, int]:
    """One pass: GET each featured league overlay, update odds AND keep-alive.

    One URL per tournament (jugabet caps multi-tournament rendered lists, so a
    dedicated single-tournament URL is the reliable form). Besides refreshing
    odds, this is the reliable *keep-alive* for featured matches: the overlay's
    embedded JSON lists every event on the page (``event_ids`` below) even when
    a fixture has no odds yet, so we bump their ``last_updated_at`` so the
    main parser's flaky browser discovery can't let them age out of the
    ``deactivate_not_seen`` window (the "World Cup match vanished" bug).
    Returns (matches_updated, leagues_fetched).
    """
    by_sport = collect_priority_tids()
    updated = 0
    leagues = 0
    for sport, tids in by_sport.items():
        for tid in sorted(tids):
            leagues += 1
            odds, event_tids = fetch_embedded(_overlay_url(sport, tid))
            # event_tids maps every event on the page -> its tournament id,
            # so its keys are the full "seen on this overlay" set, including
            # oddsless upcoming fixtures that `odds` omits.
            seen_ids = list(event_tids.keys()) or list(odds.keys())
            if not seen_ids:
                continue
            try:
                with db_session() as s:
                    repo = MatchRepository(s)
                    repo.touch_seen(seen_ids)
                    for eid, outcomes in odds.items():
                        if repo.update_result_odds(eid, outcomes):
                            updated += 1
            except Exception:
                logger.exception("priority_odds: persist failed for %s/%s", sport, tid)
    return updated, leagues


def _loop() -> None:
    print("[PRIORITY] odds lane started", flush=True)
    while True:
        started = time.monotonic()
        try:
            n, leagues = refresh_once()
            print(f"[PRIORITY] cycle: leagues={leagues} odds_updated={n}", flush=True)
        except Exception as exc:  # noqa: BLE001
            print(f"[PRIORITY] cycle ERROR: {exc!r}", flush=True)
            logger.exception("priority_odds: refresh_once crashed")
        elapsed = time.monotonic() - started
        time.sleep(max(5.0, PRIORITY_INTERVAL_SECONDS - elapsed))


def start_priority_odds_thread() -> None:
    threading.Thread(target=_loop, name="priority-odds", daemon=True).start()
