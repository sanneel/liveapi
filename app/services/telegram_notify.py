"""
Outbound Telegram alerts — best-effort, never raises.

Configured via TELEGRAM_BOT_TOKEN + TELEGRAM_CHAT_ID (see app/config.py).
If either is blank, sending is a no-op so the rest of the app is unaffected.
"""

from __future__ import annotations

import httpx

from ..config import get_settings
from ..logging_config import get_logger

logger = get_logger("app.services.telegram")

_API = "https://api.telegram.org/bot{token}/sendMessage"
_TIMEOUT = 10.0


def is_configured() -> bool:
    s = get_settings()
    return bool(s.telegram_bot_token and s.telegram_chat_id)


def send_telegram(text: str) -> bool:
    """Send an HTML-formatted message. Returns True on success, False otherwise.
    Never raises — failures are logged so a flaky network can't break callers."""
    s = get_settings()
    if not (s.telegram_bot_token and s.telegram_chat_id):
        logger.info("telegram: not configured; skipping message")
        return False
    try:
        resp = httpx.post(
            _API.format(token=s.telegram_bot_token),
            json={
                "chat_id": s.telegram_chat_id,
                "text": text,
                "parse_mode": "HTML",
                "disable_web_page_preview": True,
            },
            timeout=_TIMEOUT,
        )
        if resp.status_code == 200:
            return True
        logger.warning("telegram: send failed status=%s body=%s", resp.status_code, resp.text[:200])
        return False
    except Exception as exc:  # noqa: BLE001 — best-effort notifier
        logger.warning("telegram: send error: %s", exc)
        return False
