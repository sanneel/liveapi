#!/usr/bin/env python3
"""
Register (or delete) the Telegram webhook for inline-button actions.

The bot token and webhook secret are read from app config (.env). The secret is
passed to Telegram as ``secret_token`` so it echoes it back in the
X-Telegram-Bot-Api-Secret-Token header on every callback — that's gate 1 of the
webhook's auth.

Usage:
  python scripts/set_telegram_webhook.py --url https://jb-service.cl
  python scripts/set_telegram_webhook.py --info
  python scripts/set_telegram_webhook.py --delete
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import requests

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from app.config import get_settings  # noqa: E402

WEBHOOK_PATH = "/telegram/webhook"
_API = "https://api.telegram.org/bot{token}/{method}"


def _call(token: str, method: str, payload: dict | None = None) -> dict:
    resp = requests.post(_API.format(token=token, method=method), json=payload or {}, timeout=15)
    data = resp.json()
    print(f"{method}: {data}")
    return data


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--url", help="Public base URL, e.g. https://jb-service.cl")
    ap.add_argument("--delete", action="store_true", help="Remove the webhook")
    ap.add_argument("--info", action="store_true", help="Show current webhook info")
    args = ap.parse_args()

    s = get_settings()
    if not s.telegram_bot_token:
        print("ERROR: TELEGRAM_BOT_TOKEN is not set.")
        return 1

    if args.info:
        _call(s.telegram_bot_token, "getWebhookInfo")
        return 0

    if args.delete:
        _call(s.telegram_bot_token, "deleteWebhook", {"drop_pending_updates": True})
        return 0

    if not args.url:
        print("ERROR: pass --url <public base URL> (or --info / --delete).")
        return 1
    if not s.telegram_webhook_secret:
        print("ERROR: TELEGRAM_WEBHOOK_SECRET is not set — refusing to register an unauthenticated webhook.")
        return 1

    full_url = args.url.rstrip("/") + WEBHOOK_PATH
    data = _call(
        s.telegram_bot_token,
        "setWebhook",
        {
            "url": full_url,
            "secret_token": s.telegram_webhook_secret,
            "allowed_updates": ["callback_query"],
            "drop_pending_updates": True,
        },
    )
    return 0 if data.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
