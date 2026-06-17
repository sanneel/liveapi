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
