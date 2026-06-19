"""
Handlers for Telegram inline-button callbacks.

Every action is a fixed, whitelisted operation. ``callback_data`` is always
server-generated (see campaign_monitor button builders); the only untrusted part
is a campaign slug, which we re-validate against the DB before acting. The
webhook layer (app/routes/telegram_webhook.py) owns authentication and the
Telegram I/O — this module just decides *what* to do and returns the text to
show, plus whether a service restart should fire afterwards.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Tuple

from ..config import get_settings
from ..database import db_session
from ..logging_config import get_logger
from ..repositories.campaign_repo import CampaignRepository

logger = get_logger("app.services.telegram_actions")

# How many trailing parser.log lines the Diagnose button scans for failure
# signatures. Enough to cover the last few refresh cycles without reading a
# multi-MB file into memory.
_PARSER_LOG_TAIL_LINES = 200


def handle_callback(data: str) -> Tuple[str, bool]:
    """Map a callback_data string to (result_html, restart_pending).

    ``restart_pending`` is True only for the restart action, so the webhook can
    edit the message *before* the service is torn down under it.
    """
    if data.startswith("reenable:"):
        return _reenable(data.split(":", 1)[1]), False
    if data == "restart":
        return (
            "♻️ <b>Restart triggered</b>\nThe service will be back in a few seconds.",
            True,
        )
    if data.startswith("diag:"):
        return _diagnose(data.split(":", 1)[1]), False
    logger.warning("telegram action: unknown callback_data=%r", data)
    return "⚠️ Unknown action.", False


def _reenable(slug: str) -> str:
    with db_session() as session:
        repo = CampaignRepository(session)
        campaign = repo.find_by_slug(slug)
        if campaign is None:
            return f"⚠️ Campaign <b>/{slug}</b> not found."
        if campaign.enabled:
            return f"ℹ️ <b>/{slug}</b> is already enabled."
        repo.enable(slug)
    logger.info("telegram action: re-enabled campaign %s", slug)
    return f"✅ Re-enabled <b>/{slug}</b>."


def _recent_parser_signals() -> dict:
    """Count failure signatures in the tail of parser.log. Cross-process safe —
    reads the file from disk, so it works from any uvicorn worker."""
    path = Path(get_settings().log_dir) / "parser.log"
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return {"available": False, "drift": 0, "soft_block": 0, "zero": 0}
    tail = lines[-_PARSER_LOG_TAIL_LINES:]
    low = [ln.lower() for ln in tail]
    return {
        "available": True,
        "drift": sum(1 for ln in low if "drift" in ln),
        "soft_block": sum(1 for ln in low if "soft-block" in ln),
        "zero": sum(1 for ln in low if "0 matches" in ln),
    }


def _diagnose(slug: str) -> str:
    """Read-only triage: campaign freshness + recent parser-log signatures, then
    a recommendation. Never executes a fix — it only tells the operator which
    button to press."""
    settings = get_settings()
    # Imported lazily to keep this module import-light and avoid any import cycle.
    from .campaign_monitor import _freshness

    with db_session() as session:
        repo = CampaignRepository(session)
        campaign = repo.find_by_slug(slug)
        if campaign is None:
            return f"⚠️ Campaign <b>/{slug}</b> not found."
        health = _freshness(session, campaign, datetime.utcnow(), settings)

    sig = _recent_parser_signals()
    if not health.dead:
        verdict = "✅ Data looks fresh again — no action needed."
    elif sig["drift"]:
        verdict = (
            "🧬 Looks like <b>parser format drift</b> — a code fix is needed; "
            "Restart won't help."
        )
    elif sig["soft_block"] or sig["zero"]:
        verdict = (
            "🤖 Looks like an <b>anti-bot soft-block</b> — tap ♻️ Restart to "
            "re-kick the parser, or wait for the backoff to clear."
        )
    else:
        verdict = "⏳ Parser looks stalled with no clear cause — tap ♻️ Restart."

    log_line = (
        f"Parser log (last {_PARSER_LOG_TAIL_LINES}): "
        f"drift={sig['drift']} · soft-block={sig['soft_block']} · zero-parse={sig['zero']}"
        if sig["available"]
        else "Parser log: unavailable"
    )
    return (
        f"🔍 <b>Diagnose · /{slug}</b>\n"
        f"Freshness: {health.reason} · {health.match_count} matches\n"
        f"{log_line}\n"
        f"{verdict}"
    )
