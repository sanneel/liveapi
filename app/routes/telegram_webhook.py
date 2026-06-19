"""
Telegram inline-button webhook.

  POST /telegram/webhook   receives callback_query updates from Telegram

Security model (all three gates required — this is a remote action trigger):
  1. The X-Telegram-Bot-Api-Secret-Token header must equal
     TELEGRAM_WEBHOOK_SECRET (Telegram echoes whatever we passed to setWebhook).
     Blank secret = endpoint disabled (403).
  2. The pressing user / chat must match TELEGRAM_CHAT_ID.
  3. callback_data is matched against a fixed whitelist in telegram_actions —
     never free-form input, never a shell.
"""

from __future__ import annotations

import hmac
import subprocess

from fastapi import APIRouter, Header, HTTPException, Request

from ..config import get_settings
from ..logging_config import get_logger
from ..services.telegram_actions import handle_callback
from ..services.telegram_notify import answer_callback, edit_message_text

logger = get_logger("app.routes.telegram_webhook")

router = APIRouter()


def _trigger_restart() -> None:
    """Fire-and-forget service restart via a narrow sudoers rule. Detached
    (start_new_session) so it survives this worker being torn down by the very
    restart it triggers. Requires:
        <user> ALL=(root) NOPASSWD: /usr/bin/systemctl restart <service>
    """
    service = get_settings().jugabet_service_name
    try:
        subprocess.Popen(  # noqa: S603,S607 — fixed argv, no shell, no user input
            ["sudo", "-n", "systemctl", "restart", service],
            start_new_session=True,
        )
        logger.info("telegram action: restart triggered for %s", service)
    except Exception as exc:  # noqa: BLE001 — never let a spawn failure 500 the webhook
        logger.warning("telegram action: restart spawn failed: %s", exc)


@router.post("/telegram/webhook")
async def telegram_webhook(
    request: Request,
    x_telegram_bot_api_secret_token: str | None = Header(default=None),
) -> dict:
    settings = get_settings()
    secret = settings.telegram_webhook_secret
    # Gate 1: shared secret. Constant-time compare; blank secret disables the route.
    if not secret or not hmac.compare_digest(
        x_telegram_bot_api_secret_token or "", secret
    ):
        raise HTTPException(status_code=403, detail="forbidden")

    update = await request.json()
    callback = update.get("callback_query")
    if not callback:
        return {"ok": True}  # we only act on button taps; ignore everything else

    message = callback.get("message") or {}
    chat = message.get("chat") or {}
    from_id = str((callback.get("from") or {}).get("id", ""))
    chat_id = str(chat.get("id", ""))
    allowed = str(settings.telegram_chat_id or "")

    # Gate 2: only the configured operator may act.
    if allowed and from_id != allowed and chat_id != allowed:
        logger.warning("telegram webhook: rejected callback from id=%s chat=%s", from_id, chat_id)
        answer_callback(callback.get("id"), "Not authorized.")
        return {"ok": True}

    # Gate 3: whitelisted action only.
    text, restart_pending = handle_callback(callback.get("data") or "")
    answer_callback(callback.get("id"))
    message_id = message.get("message_id")
    if chat_id and message_id:
        edit_message_text(chat_id, message_id, text)

    # Restart last, only after the result message is safely sent — the restart
    # kills this very worker.
    if restart_pending:
        _trigger_restart()

    return {"ok": True}
