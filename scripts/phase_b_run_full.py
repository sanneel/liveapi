"""
Phase B full-run: ensure an admin test user exists, then exercise every
health check including the override flow (POST→re-read→DELETE).

Idempotent. Run repeatedly without side effects beyond a single
`phase_b_test` user in the `users` table.

Credentials are persisted to `data/.phase_b_creds` so subsequent runs
reuse the same user. Delete that file (or pass new ones via env) to
rotate.

Usage:
    venv_win\\Scripts\\python scripts\\phase_b_run_full.py

Env overrides (optional):
    PHASE_B_USERNAME, PHASE_B_PASSWORD    use these instead of the cached pair
    PHASE_B_BASE_URL, PHASE_B_SPORT       passed through to phase_b_health
"""

from __future__ import annotations

import json
import os
import secrets
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

CREDS_FILE = PROJECT_ROOT / "data" / ".phase_b_creds"
DEFAULT_USER = "phase_b_test"


def _load_dotenv() -> None:
    """Minimal .env loader — no external dep (python-dotenv not required).

    Reads KEY=VALUE lines from PROJECT_ROOT/.env into os.environ, but does
    NOT overwrite any var already set in the shell (shell wins). Lines
    starting with # and blank lines are ignored. Surrounding single/double
    quotes on the value are stripped.
    """
    env_file = PROJECT_ROOT / ".env"
    if not env_file.exists():
        return
    try:
        for raw in env_file.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip()
            if (value.startswith('"') and value.endswith('"')) or (
                value.startswith("'") and value.endswith("'")
            ):
                value = value[1:-1]
            if key and key not in os.environ:
                os.environ[key] = value
    except Exception:
        # .env loading is best-effort; don't crash the health run.
        pass


def _load_or_create_creds() -> tuple[str, str]:
    """Returns (username, password). Prefers env > cached file > newly generated."""
    env_user = os.environ.get("PHASE_B_USERNAME")
    env_pass = os.environ.get("PHASE_B_PASSWORD")
    if env_user and env_pass:
        return env_user, env_pass

    if CREDS_FILE.exists():
        try:
            data = json.loads(CREDS_FILE.read_text(encoding="utf-8"))
            u = data.get("username")
            p = data.get("password")
            if isinstance(u, str) and isinstance(p, str) and u and p:
                return u, p
        except Exception:
            pass  # fall through to regenerate

    username = DEFAULT_USER
    password = secrets.token_urlsafe(24)  # ~32 chars, satisfies the 14-char min
    CREDS_FILE.parent.mkdir(parents=True, exist_ok=True)
    CREDS_FILE.write_text(
        json.dumps({"username": username, "password": password}, indent=2),
        encoding="utf-8",
    )
    print(f"[setup] generated test credentials -> {CREDS_FILE}")
    return username, password


def _ensure_admin(username: str, password: str) -> None:
    """Call scripts/create_admin.py non-interactively. Role=editor is the
    minimum required for the override POST/DELETE endpoints."""
    cmd = [
        sys.executable,
        str(PROJECT_ROOT / "scripts" / "create_admin.py"),
        "--username", username,
        "--password", password,
        "--role", "editor",
    ]
    print(f"[setup] ensuring user '{username}' (role=editor)...")
    result = subprocess.run(cmd, cwd=str(PROJECT_ROOT))
    if result.returncode != 0:
        print(
            "[setup] create_admin.py failed — cannot run override flow check",
            file=sys.stderr,
        )
        sys.exit(result.returncode)


def main() -> int:
    # Pull TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID (and any other) from .env
    # so the wrapper works without manual `set` commands in PowerShell/cmd.
    _load_dotenv()

    username, password = _load_or_create_creds()
    _ensure_admin(username, password)

    # Inject into env before importing phase_b_health (it reads at module load).
    os.environ["PHASE_B_USERNAME"] = username
    os.environ["PHASE_B_PASSWORD"] = password

    from phase_b_health import main as run_health  # noqa: E402
    exit_code = run_health()

    print(
        "\n[hint] credentials cached at data/.phase_b_creds — "
        "delete to rotate, or set PHASE_B_USERNAME/PHASE_B_PASSWORD env vars."
    )
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
