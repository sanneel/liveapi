"""
Campaign data-health monitor → Telegram alerts.

For every enabled, non-expired campaign we check the matches it actually
renders:

  * manual campaigns — the editor-picked matches (CampaignMatch rows)
  * auto campaigns   — active matches for the campaign's sport, optionally
                       narrowed to one league (tournament_name)

If a campaign's data has gone stale (no match updated within
`campaign_stale_minutes`) or it has no matches at all, the league/feed behind
it is effectively dead — so we send a Telegram alert. Alerts fire only on
state transitions (ok→dead and dead→ok), so a persistently-dead feed is
reported once, not every cycle.

Only the parser-holding process starts the loop (see server.startup), so the
8 uvicorn workers don't each fire duplicate alerts.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Dict, List, Optional

from sqlalchemy import func

from ..config import get_settings
from ..database import db_session
from ..logging_config import get_logger
from ..models import Match
from ..parser import drift_canary
from ..repositories.campaign_repo import CampaignRepository
from ..repositories.log_repo import LogRepository
from .telegram_notify import is_configured, send_telegram

logger = get_logger("app.services.campaign_monitor")

# slug -> "ok" | "dead". Transitions trigger an alert. In-memory: on restart
# every currently-dead campaign re-alerts once, which is the desired behaviour.
_last_state: Dict[str, str] = {}
_state_lock = threading.Lock()

# Parser drift canary state: "ok" | "drifted". Only ok<->drifted transitions
# alert; "unreachable"/"no_events" are inconclusive and never flip the state.
_canary_last_state: Optional[str] = None
_monitor_started = False


@dataclass(frozen=True)
class CampaignHealth:
    slug: str
    title: str
    sport: str
    league: Optional[str]
    mode: str
    match_count: int
    age_sec: Optional[int]
    dead: bool
    reason: str


def _health(campaign, count, age_sec, dead, reason) -> CampaignHealth:
    return CampaignHealth(
        slug=campaign.slug,
        title=campaign.title,
        sport=campaign.sport,
        league=campaign.league,
        mode=campaign.mode,
        match_count=count,
        age_sec=age_sec,
        dead=dead,
        reason=reason,
    )


def _freshness(session, campaign, now_dt: datetime, stale_seconds: int) -> CampaignHealth:
    if campaign.mode == "manual":
        repo = CampaignRepository(session)
        matches = repo.get_matches(campaign.slug)
        count = len(matches)
        configured = len(repo.get_match_rows(campaign.slug))
        # Empty by design (operator never picked matches) — not a parser
        # failure, so never alert on it.
        if configured == 0:
            return _health(campaign, 0, None, False, "no matches configured")
        # Matches were picked but every one's row has since vanished.
        if count == 0:
            return _health(campaign, 0, None, True, "all selected matches were removed")
        stamps = [m.last_updated_at for m in matches if m.last_updated_at]
        last = max(stamps) if stamps else None
    else:
        q = session.query(
            func.max(Match.last_updated_at), func.count(Match.event_id)
        ).filter(Match.is_active.is_(True), Match.sport == campaign.sport)
        if campaign.league:
            q = q.filter(Match.tournament_name == campaign.league)
        last, count = q.one()
        count = int(count or 0)
        # An auto campaign with no live matches = its league/sport feed is dead.
        if count == 0:
            return _health(campaign, 0, None, True, "league has no live matches")

    age_sec = int((now_dt - last).total_seconds()) if last else None
    if age_sec is None:
        return _health(campaign, count, None, True, "matches have no update timestamp")
    if age_sec > stale_seconds:
        return _health(campaign, count, age_sec, True, f"no data update in {age_sec // 60} min")
    return _health(campaign, count, age_sec, False, "ok")


def evaluate() -> List[CampaignHealth]:
    """Health of every enabled, non-expired campaign (read-only)."""
    now_dt = datetime.utcnow()
    stale_seconds = max(60, get_settings().campaign_stale_minutes * 60)
    out: List[CampaignHealth] = []
    with db_session() as session:
        for campaign in CampaignRepository(session).list_all(enabled_only=True):
            if campaign.expires_at and campaign.expires_at < now_dt:
                continue
            out.append(_freshness(session, campaign, now_dt, stale_seconds))
    return out


def _where(h: CampaignHealth) -> str:
    return h.sport + (f" · {h.league}" if h.league else "")


def _format_dead(h: CampaignHealth) -> str:
    return (
        "🔴 <b>Campaign data is dead</b>\n"
        f"<b>{h.title}</b> (/{h.slug})\n"
        f"League: {_where(h)}\n"
        f"Reason: {h.reason} · {h.match_count} matches"
    )


def _format_recovered(h: CampaignHealth) -> str:
    return (
        "🟢 <b>Campaign data recovered</b>\n"
        f"<b>{h.title}</b> (/{h.slug})\n"
        f"League: {_where(h)} · {h.match_count} matches fresh again"
    )


def _format_drift(res: dict) -> str:
    return (
        "🔴 <b>Parser format drift</b>\n"
        f"{res.get('url')}\n"
        "The page still advertises events but the extractor returned 0 — "
        "jugabet likely changed their embedded JSON shape. Odds will go stale "
        "until the parser is updated."
    )


def _format_drift_recovered(res: dict) -> str:
    return (
        "🟢 <b>Parser format drift cleared</b>\n"
        f"{res.get('url')}\n"
        f"Extractor is reading odds again ({res.get('events_with_odds')} events)."
    )


def _format_disabled(slug: str, title: str) -> str:
    return (
        "🟠 <b>Campaign auto-disabled</b>\n"
        f"<b>{title}</b> (/{slug})\n"
        "Every picked match has finished, so it was turned off to avoid "
        "rendering blank. Safe to delete from the Campaigns page."
    )


def _match_still_live(match, now_dt: datetime) -> bool:
    """True until a match's scheduled end has passed.

    Deterministic "is the game over by the clock" rule: a match counts as
    finished once ``start_time_utc + campaign_hide_after_start_hours`` is in the
    past. A football match runs ~2h, so a kickoff that was 2h+ ago is over.

    This replaces the old "active AND refreshed within N minutes" heuristic,
    which wrongly flagged *upcoming* matches as finished whenever the parser
    briefly stopped refreshing them (e.g. during a deploy/restart) — that is
    what auto-disabled campaigns whose games hadn't even started yet.

    A match with no known start time is treated as live, so a campaign is never
    auto-disabled on missing data.
    """
    if match.start_time_utc is None:
        return True
    finished_at = match.start_time_utc + timedelta(
        hours=get_settings().campaign_hide_after_start_hours
    )
    return finished_at > now_dt


def auto_disable_finished() -> List[tuple]:
    """Disable manual campaigns whose every picked match has finished, so they
    stop rendering a blank/stale PNG and the operator can delete them.

    A match is "finished" when its scheduled end has passed — i.e.
    ``start_time_utc + campaign_hide_after_start_hours`` is in the past (see
    ``_match_still_live``) — or when it was removed (``get_matches`` returns
    nothing). Upcoming matches are never "finished", so a campaign whose games
    haven't started yet is never auto-disabled, even if the parser briefly
    stalls. Empty-by-design campaigns (no matches ever picked) are left alone.
    Returns ``[(slug, title)]`` for the campaigns just turned off.
    """
    now_dt = datetime.utcnow()
    disabled: List[tuple] = []
    with db_session() as session:
        repo = CampaignRepository(session)
        log = LogRepository(session)
        for campaign in repo.list_all(enabled_only=True):
            if campaign.mode != "manual":
                continue
            if not repo.get_match_rows(campaign.slug):
                continue  # never had matches — not "finished"
            matches = repo.get_matches(campaign.slug)
            if any(_match_still_live(m, now_dt) for m in matches):
                continue  # at least one match has not finished yet (by the clock)
            if repo.disable(campaign.slug):
                disabled.append((campaign.slug, campaign.title))
                log.record(
                    "campaign.auto_disable",
                    username="monitor",
                    target=campaign.slug,
                    payload={"reason": "all matches finished"},
                )
                logger.info(
                    "campaign monitor: auto-disabled %s (all matches finished)",
                    campaign.slug,
                )
    return disabled


def _run_canary_and_alert() -> int:
    """Run the parser drift canary and alert on ok<->drifted transitions.

    "unreachable"/"no_events"/"unknown" are inconclusive (network, geo-block,
    off-hours) and must never cry wolf, so they leave the last state untouched.
    """
    global _canary_last_state
    if not get_settings().parser_canary_enabled:
        return 0
    res = drift_canary.run_canary_once()
    status = res.get("status")
    if status not in ("ok", "drifted"):
        return 0
    alerts = 0
    with _state_lock:
        prev = _canary_last_state
        if status == "drifted" and prev != "drifted":
            if send_telegram(_format_drift(res)):
                alerts += 1
        elif status == "ok" and prev == "drifted":
            if send_telegram(_format_drift_recovered(res)):
                alerts += 1
        _canary_last_state = status
    return alerts


def run_monitor_once() -> dict:
    """Auto-disable finished manual campaigns, evaluate the rest, run the parser
    drift canary, and alert on any ok↔dead or ok↔drifted transition."""
    alerts = 0
    disabled = auto_disable_finished()
    for slug, title in disabled:
        # A campaign disabled here drops out of evaluate() (enabled-only), so
        # it won't also fire a "dead" alert — this is its single notification.
        with _state_lock:
            _last_state.pop(slug, None)
        if send_telegram(_format_disabled(slug, title)):
            alerts += 1
    healths = evaluate()
    with _state_lock:
        live_slugs = set()
        for h in healths:
            live_slugs.add(h.slug)
            prev = _last_state.get(h.slug)
            cur = "dead" if h.dead else "ok"
            if prev != cur:
                if cur == "dead":
                    if send_telegram(_format_dead(h)):
                        alerts += 1
                elif prev == "dead":  # was dead, now ok
                    if send_telegram(_format_recovered(h)):
                        alerts += 1
            _last_state[h.slug] = cur
        # Forget campaigns that no longer exist so they don't leak memory or
        # fire a spurious "recovered" if re-created later.
        for slug in [s for s in _last_state if s not in live_slugs]:
            _last_state.pop(slug, None)
    alerts += _run_canary_and_alert()
    dead = sum(1 for h in healths if h.dead)
    return {
        "checked": len(healths),
        "dead": dead,
        "disabled": len(disabled),
        "alerts_sent": alerts,
    }


def start_monitor_thread() -> bool:
    """Start the background loop. No-op if disabled via config or already
    running. Returns True only when a thread was actually started.

    Note: the loop runs even when Telegram is unconfigured — auto-disabling
    finished manual campaigns is useful on its own, and the Telegram sends
    simply become no-ops until a token/chat id is set."""
    global _monitor_started
    settings = get_settings()
    if _monitor_started:
        return False
    if not settings.campaign_monitor_enabled:
        logger.info("campaign monitor: disabled via config")
        return False
    if not is_configured():
        logger.info(
            "campaign monitor: Telegram not configured — alerts off, but "
            "auto-disable of finished campaigns still runs"
        )

    _monitor_started = True

    def _loop() -> None:
        time.sleep(30)  # let the parser warm up before the first evaluation
        while True:
            interval = max(60, get_settings().campaign_monitor_interval_seconds)
            try:
                result = run_monitor_once()
                if result["alerts_sent"] or result["disabled"]:
                    logger.info("campaign monitor: %s", result)
            except Exception:  # noqa: BLE001 — loop must never die
                logger.exception("campaign monitor: cycle failed")
            time.sleep(interval)

    threading.Thread(target=_loop, name="campaign-monitor", daemon=True).start()
    logger.info(
        "campaign monitor started (interval=%ss, stale=%smin)",
        settings.campaign_monitor_interval_seconds,
        settings.campaign_stale_minutes,
    )
    return True
