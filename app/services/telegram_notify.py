"""
Telegram I/O — best-effort, never raises.

Configured via TELEGRAM_BOT_TOKEN + TELEGRAM_CHAT_ID (see app/config.py).
If either is blank, sending is a no-op so the rest of the app is unaffected.

Beyond one-way alerts, messages can carry inline buttons (``send_telegram`` with
``buttons``); the user's tap arrives at the /telegram/webhook route, which uses
``answer_callback`` (stop the spinner) and ``edit_message_text`` (replace the
alert with the action's result, which also strips the now-spent buttons).
"""

from __future__ import annotations

from typing import List, Optional, Tuple

import requests

from ..config import get_settings
from ..logging_config import get_logger

logger = get_logger("app.services.telegram")

# (button label, callback_data). callback_data must be <=64 bytes and is always
# server-generated — the webhook re-validates it against a fixed whitelist.
Button = Tuple[str, str]

_API = "https://api.telegram.org/bot{token}/{method}"
_TIMEOUT = 10.0


def is_configured() -> bool:
    s = get_settings()
    return bool(s.telegram_bot_token and s.telegram_chat_id)


def _keyboard(buttons: Optional[List[List[Button]]]) -> Optional[dict]:
    if not buttons:
        return None
    return {
        "inline_keyboard": [
            [{"text": text, "callback_data": data} for (text, data) in row]
            for row in buttons
        ]
    }


def _post(method: str, payload: dict) -> bool:
    """POST to a Telegram Bot API method. Returns True on HTTP 200, never raises."""
    s = get_settings()
    if not s.telegram_bot_token:
        logger.info("telegram: not configured; skipping %s", method)
        return False
    try:
        resp = requests.post(
            _API.format(token=s.telegram_bot_token, method=method),
            json=payload,
            timeout=_TIMEOUT,
        )
        if resp.status_code == 200:
            return True
        logger.warning(
            "telegram: %s failed status=%s body=%s", method, resp.status_code, resp.text[:200]
        )
        return False
    except Exception as exc:  # noqa: BLE001 — best-effort notifier
        logger.warning("telegram: %s error: %s", method, exc)
        return False


def send_telegram(text: str, buttons: Optional[List[List[Button]]] = None) -> bool:
    """Send an HTML-formatted message, optionally with an inline-button keyboard.
    Returns True on success. Never raises."""
    s = get_settings()
    if not s.telegram_chat_id:
        logger.info("telegram: no chat id; skipping message")
        return False
    payload = {
        "chat_id": s.telegram_chat_id,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }
    markup = _keyboard(buttons)
    if markup:
        payload["reply_markup"] = markup
    return _post("sendMessage", payload)


def answer_callback(callback_query_id: str, text: Optional[str] = None) -> bool:
    """Acknowledge a button tap so the client stops showing a loading spinner.
    ``text`` (if given) shows as a transient toast to the user."""
    if not callback_query_id:
        return False
    payload: dict = {"callback_query_id": callback_query_id}
    if text:
        payload["text"] = text
    return _post("answerCallbackQuery", payload)


def edit_message_text(
    chat_id: str,
    message_id: int,
    text: str,
    buttons: Optional[List[List[Button]]] = None,
) -> bool:
    """Replace a message's text (and, by default, drop its inline keyboard so a
    spent action can't be re-tapped). Returns True on success."""
    payload: dict = {
        "chat_id": chat_id,
        "message_id": message_id,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }
    markup = _keyboard(buttons)
    if markup:
        payload["reply_markup"] = markup
    return _post("editMessageText", payload)
