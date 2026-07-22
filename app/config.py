"""
Application settings.

All settings come from environment variables (or .env in dev).
Never hard-code secrets. Never commit .env.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import List
from urllib.parse import urlsplit

from pydantic_settings import BaseSettings, SettingsConfigDict


BASE_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(BASE_DIR / ".env"),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    app_env: str = "development"

    # ── Figma (GOW image export) ─────────────────────────────────────
    # Read-only File-content personal access token. Set it in .env or the
    # process environment; used by app/services/figma_runner.py.
    figma_token: str = ""

    # ── Journey Planner ──────────────────────────────────────────────
    # Which LLM backs the /admin/planner chat: "groq" (free tier, cheapest) or
    # "gemini". Auto-resolved at request time: if planner_provider is unset it
    # prefers Groq when GROQ_API_KEY is present, else Gemini.
    planner_provider: str = ""          # "groq" | "gemini" | "" (auto)

    # Groq — free tier at console.groq.com; OpenAI-compatible chat API.
    # 8b-instant fits the free tier's ~30K TPM (70b-versatile is capped at 12K
    # TPM, too small for this ~17K-token prompt → HTTP 413). For 70b quality,
    # set GROQ_MODEL=llama-3.3-70b-versatile AND upgrade to Groq's Dev tier.
    groq_api_key: str = ""
    groq_model: str = "llama-3.1-8b-instant"

    # Max output tokens per reply. Counts toward Groq's per-minute token limit,
    # so keep it modest; MODE 1/3 replies are short, MODE 2 asks per-object.
    planner_max_tokens: int = 4096

    # Gemini (fallback). Server-side key, never shipped to the browser.
    gemini_api_key: str = ""
    # flash-lite is the cheapest 2.5 tier — materially lower input/output price
    # than 2.0/2.5-flash, enough for the planner's structured MODE 1/2/3 output.
    gemini_model: str = "gemini-2.5-flash-lite"
    # 2.5 models run "thinking" by default — those tokens bill at the output
    # rate and dominate cost. 0 disables it (planner needs no chain-of-thought);
    # raise it only if answer quality needs it.
    gemini_thinking_budget: int = 0

    # ── Database ──────────────────────────────────────────────────────
    database_url: str = f"sqlite:///{BASE_DIR / 'data' / 'jugabet.db'}"

    # ── Site / parser ────────────────────────────────────────────────
    site_base: str = "https://jugabet.cl"
    forced_timezone: str = "America/Santiago"
    parser_refresh_seconds: int = 120
    parser_timeout_ms: int = 30000
    parser_js_settle_ms: int = 1200
    parser_enabled: bool = True
    parser_max_concurrency: int = 8
    # Drift canary: probes a live jugabet listing URL each monitor cycle and
    # flags when the page still advertises events but our extractor yields none
    # (i.e. jugabet changed their embedded JSON shape). See app/parser/drift_canary.py.
    parser_canary_enabled: bool = True
    parser_canary_url: str = "https://jugabet.cl/football/all/1"

    # ── Match lifecycle ──────────────────────────────────────────────
    # Hours after start_time_utc a match is considered expired. Was 6,
    # which was too tight for: UFC events (5-6h cards), Champions League
    # nights with delayed kickoff + extra time + post-match coverage that
    # keeps the row visible on Jugabet, and any match whose start_time
    # the parser misread by an hour. 12h handles every realistic case
    # without keeping truly-finished matches active for the whole next day.
    match_deactivate_after_hours: int = 12

    # Hours after start_time_utc a match stops appearing in a rendered
    # campaign / hot PNG, even while the parser still keeps the row active.
    # A match kicking off at 18:00 vanishes from the PNG at 20:00 (default 2h)
    # so finished games drop off without waiting for full deactivation.
    campaign_hide_after_start_hours: int = 2

    # ── Logging ──────────────────────────────────────────────────────
    log_level: str = "INFO"
    log_dir: str = str(BASE_DIR / "logs")
    log_max_bytes: int = 10 * 1024 * 1024  # 10 MB per file
    log_backup_count: int = 10

    # ── Security (used in later phases) ──────────────────────────────
    jwt_secret_key: str = "CHANGE_ME_IN_PRODUCTION_USE_A_LONG_RANDOM_STRING"
    jwt_algorithm: str = "HS256"
    jwt_access_expire_minutes: int = 60
    jwt_refresh_expire_days: int = 7

    # ── Cookies ──────────────────────────────────────────────────────
    cookie_secure: bool = False        # set True in production (HTTPS only)
    cookie_samesite: str = "lax"
    allowed_hosts: str = "127.0.0.1,localhost,::1"
    public_base_url: str = ""
    public_cache_seconds: int = 30
    public_cache_max_entries: int = 256
    allowed_logo_hosts: str = "jugabet.cl,www.jugabet.cl"
    # Hosts permitted for Campaign.fallback_image_url. Defaults match logo
    # allow-list; override via env to add a CDN host. Validated at write time.
    allowed_fallback_image_hosts: str = "jugabet.cl,www.jugabet.cl"

    # ── Telegram alerts / campaign monitor ───────────────────────────
    # Create a bot with @BotFather → telegram_bot_token; get your numeric
    # chat id from @userinfobot → telegram_chat_id. Blank disables alerts.
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""
    # Inline-button actions: Telegram echoes this secret in the
    # X-Telegram-Bot-Api-Secret-Token header on every webhook call. Blank
    # disables the webhook endpoint entirely (it 403s), so buttons are inert
    # until a secret is set and the webhook is registered.
    telegram_webhook_secret: str = ""
    # systemd unit the "♻️ Restart" button restarts (via a narrow sudoers rule).
    jugabet_service_name: str = "jugabet"
    campaign_monitor_enabled: bool = True
    campaign_monitor_interval_seconds: int = 300   # how often to re-check
    # A *live* match refreshes every ~minute, so 20 min of silence means its
    # feed is genuinely dead. A *prematch* match (kickoff hours/days away) is
    # refreshed on a slow, low-priority cadence and routinely sits 20-90 min
    # between updates while perfectly healthy — judging it by the live window
    # produced a constant dead/recovered alert flap. Prematch matches get their
    # own, far more generous window so we only alert on a real outage.
    campaign_stale_minutes: int = 20               # live data older than this = "dead"
    campaign_prematch_stale_minutes: int = 180     # prematch data older than this = "dead"

    # ── Rate limits ──────────────────────────────────────────────────
    admin_login_max_attempts: int = 5
    admin_login_lockout_minutes: int = 15

    def is_production(self) -> bool:
        return self.app_env.strip().lower() == "production"

    def allowed_host_list(self) -> List[str]:
        return [h.strip() for h in self.allowed_hosts.split(",") if h.strip()]

    def allowed_logo_host_list(self) -> List[str]:
        return [h.strip().lower() for h in self.allowed_logo_hosts.split(",") if h.strip()]

    def allowed_fallback_image_host_list(self) -> List[str]:
        return [h.strip().lower() for h in self.allowed_fallback_image_hosts.split(",") if h.strip()]

    def validate_production(self) -> None:
        """Fail fast when production security settings are unsafe."""
        if not self.is_production():
            return

        errors: List[str] = []
        if (
            not self.jwt_secret_key
            or self.jwt_secret_key == "CHANGE_ME_IN_PRODUCTION_USE_A_LONG_RANDOM_STRING"
            or len(self.jwt_secret_key) < 48
        ):
            errors.append("JWT_SECRET_KEY must be a unique random value of at least 48 characters")
        if not self.cookie_secure:
            errors.append("COOKIE_SECURE must be true behind HTTPS")
        if self.cookie_samesite.lower() not in {"lax", "strict", "none"}:
            errors.append("COOKIE_SAMESITE must be lax, strict, or none")
        if self.cookie_samesite.lower() == "none" and not self.cookie_secure:
            errors.append("COOKIE_SAMESITE=none requires COOKIE_SECURE=true")
        hosts = self.allowed_host_list()
        if not hosts or "*" in hosts:
            errors.append("ALLOWED_HOSTS must list the production domain(s), not *")
        if not self.public_base_url.startswith("https://"):
            errors.append("PUBLIC_BASE_URL must be the public https:// origin")
        else:
            public_host = urlsplit(self.public_base_url).hostname
            if public_host and public_host not in hosts:
                errors.append("ALLOWED_HOSTS must include the PUBLIC_BASE_URL host")

        if errors:
            raise RuntimeError("Unsafe production configuration: " + "; ".join(errors))


@lru_cache
def get_settings() -> Settings:
    return Settings()
