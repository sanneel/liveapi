"""Run the Journey Cloner CLI from the integrated admin UI."""

from __future__ import annotations

import os
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Tuple

from ..config import BASE_DIR


CLONER_DIR = BASE_DIR / "journey-cloner"
SCRIPT_PATH = CLONER_DIR / "create_journeys.py"
OUTPUT_DIR = BASE_DIR / "data" / "journey_cloner_out"
TEMPLATE_TYPES = ("followup", "bfr", "two_hours", "aft")

# Keys must match TEAMS in journey-cloner/create_journeys.py. Each team's
# templates live in journey-cloner/templates/<team>/.
TEAMS: Dict[str, str] = {"udch": "UDCH", "colocolo": "Colo Colo"}
DEFAULT_TEAM = "udch"

# Teams that reuse another team's template files (mirror base_team in the
# cloner's TEAMS). A team's own file still takes precedence when present.
TEAM_BASE: Dict[str, str] = {"colocolo": "udch"}


def resolve_team(team: str | None) -> str:
    key = (team or DEFAULT_TEAM).strip().lower()
    if key not in TEAMS:
        raise ValueError(
            f"Unknown team {team!r}. Known teams: {', '.join(sorted(TEAMS))}"
        )
    return key


def templates_dir(team: str) -> Path:
    return CLONER_DIR / "templates" / resolve_team(team)


def extract_body_from_fetch(fetch_text: str) -> Dict[str, Any]:
    match = re.search(r'"body"\s*:\s*"((?:\\.|[^"\\])*)"', fetch_text, flags=re.DOTALL)
    if not match:
        raise ValueError(
            'Could not find a string field named "body". Paste Chrome DevTools '
            'Copy as fetch for POST /journey-drafts.'
        )

    escaped_json_body = '"' + match.group(1) + '"'
    body_text = json.loads(escaped_json_body)
    body = json.loads(body_text)
    if not isinstance(body, dict):
        raise ValueError("Extracted body is not a JSON object.")
    return body


def save_template_from_fetch(
    template_type: str, fetch_text: str, team: str = DEFAULT_TEAM
) -> Dict[str, Any]:
    if template_type not in TEMPLATE_TYPES:
        raise ValueError(f"Unknown template type: {template_type}")
    body = extract_body_from_fetch(fetch_text)
    output_path = templates_dir(team) / f"{template_type}.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(body, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return {
        "path": str(output_path),
        "journeyName": body.get("journeyName"),
        "duplicatedFromId": body.get("duplicatedFromId"),
        "reservedJourneyId": body.get("reservedJourneyId"),
    }


def python_executable() -> str:
    if os.name == "nt":
        candidate = CLONER_DIR / ".venv" / "Scripts" / "python.exe"
    else:
        candidate = CLONER_DIR / ".venv" / "bin" / "python"
    if candidate.exists():
        return str(candidate)
    return sys.executable


def template_exists(team: str, template_type: str) -> bool:
    """A team's own file, or an inherited base team's file, exists."""
    team = resolve_team(team)
    if (templates_dir(team) / f"{template_type}.json").exists():
        return True
    base = TEAM_BASE.get(team)
    return bool(base) and (templates_dir(base) / f"{template_type}.json").exists()


def team_inherits(team: str) -> bool:
    return resolve_team(team) in TEAM_BASE


def template_status(team: str = DEFAULT_TEAM) -> Dict[str, bool]:
    return {key: template_exists(team, key) for key in TEMPLATE_TYPES}


def missing_templates(selected_types: List[str], team: str = DEFAULT_TEAM) -> List[str]:
    status = template_status(team)
    return [key for key in selected_types if not status.get(key)]


def generate_console_script(
    *,
    home: str,
    away: str,
    code: str,
    date: str,
    chile_time: str,
    selected_types: List[str],
    team: str = DEFAULT_TEAM,
) -> Tuple[int, str, str, str | None, str]:
    """Generate the paste-into-DevTools console script for a campaign.

    Returns (returncode, output_log, display_cmd, js_text or None, js_filename).
    """
    match_name = f"{home.strip()} vs {away.strip()}"
    clean_code = code.strip().upper()
    cmd = [
        python_executable(),
        str(CLONER_DIR / "generate_console_script.py"),
        "--team",
        resolve_team(team),
        "--match",
        match_name,
        "--code",
        clean_code,
        "--date",
        date.strip(),
        "--time",
        chile_time.strip(),
        "--types",
        *selected_types,
    ]

    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"

    display_cmd = " ".join(
        part if " " not in part else repr(part) for part in cmd
    )

    proc = subprocess.run(
        cmd,
        cwd=CLONER_DIR,
        env=env,
        text=True,
        encoding="utf-8",
        capture_output=True,
        timeout=300,
    )
    output = proc.stdout
    if proc.stderr:
        output += "\nSTDERR:\n" + proc.stderr

    js_filename = f"{clean_code}_console.js"
    js_text = None
    if proc.returncode == 0:
        js_path = CLONER_DIR / "console_scripts" / js_filename
        if js_path.exists():
            js_text = js_path.read_text(encoding="utf-8")
        else:
            output += f"\nERROR: expected script file not found: {js_path}"
    return proc.returncode, output, display_cmd, js_text, js_filename


GOW_SCRIPT_PATH = CLONER_DIR / "gow_campaign.py"


def parse_bets(raw: str) -> List[int]:
    """Parse the bets field ('120 200 500 800' or '120,200,500,800') to ints."""
    parts = [p for p in re.split(r"[\s,]+", (raw or "").strip()) if p]
    if not parts:
        raise ValueError("Enter the per-tier bet values, e.g. 120 200 500 800")
    try:
        bets = [int(p) for p in parts]
    except ValueError:
        raise ValueError(f"Bets must be whole numbers, got: {raw!r}")
    if any(b <= 0 for b in bets):
        raise ValueError("Bet values must be positive.")
    return bets


def _gow_basename(game_name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", (game_name or "").lower()).strip("_")
    return f"gow_{slug or 'campaign'}"


def generate_gow_console_script(
    *,
    game_name: str,
    provider: str,
    date: str,
    bets: List[int],
    provider_name: str = "",
    spins: int | None = None,
) -> Tuple[int, str, str, str | None, str]:
    """Generate the paste-into-DevTools console script for a Game-of-the-Week
    casino campaign (free-spin offer + 4 deposit tiers + promo page).

    The real game ids are resolved from the live games catalog at paste time, so
    only the game name + provider slug are needed here.

    Returns (returncode, output_log, display_cmd, js_text or None, js_filename).
    """
    basename = _gow_basename(game_name)
    cmd = [
        python_executable(),
        str(GOW_SCRIPT_PATH),
        "--date",
        date.strip(),
        "--game-name",
        game_name.strip(),
        "--provider",
        provider.strip(),
        "--bets",
        *[str(b) for b in bets],
        "--name",
        basename,
    ]
    if provider_name.strip():
        cmd += ["--provider-name", provider_name.strip()]
    if spins is not None:
        cmd += ["--spins", str(spins)]

    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"

    display_cmd = " ".join(
        part if " " not in part else repr(part) for part in cmd
    )

    proc = subprocess.run(
        cmd,
        cwd=CLONER_DIR,
        env=env,
        text=True,
        encoding="utf-8",
        capture_output=True,
        timeout=300,
    )
    output = proc.stdout
    if proc.stderr:
        output += "\nSTDERR:\n" + proc.stderr

    js_filename = f"{basename}_console.js"
    js_text = None
    if proc.returncode == 0:
        js_path = CLONER_DIR / "console_scripts" / js_filename
        if js_path.exists():
            js_text = js_path.read_text(encoding="utf-8")
        else:
            output += f"\nERROR: expected script file not found: {js_path}"
    return proc.returncode, output, display_cmd, js_text, js_filename


def run_journey_cloner(
    *,
    token: str,
    home: str,
    away: str,
    code: str,
    date: str,
    chile_time: str,
    selected_types: List[str],
    dry_run: bool,
    team: str = DEFAULT_TEAM,
) -> Tuple[int, str, str]:
    match_name = f"{home.strip()} vs {away.strip()}"
    cmd = [
        python_executable(),
        str(SCRIPT_PATH),
        "--team",
        resolve_team(team),
        "--match",
        match_name,
        "--code",
        code.strip().upper(),
        "--date",
        date.strip(),
        "--time",
        chile_time.strip(),
        "--types",
        *selected_types,
        "--yes",
    ]
    if dry_run:
        cmd.append("--dry-run")

    env = os.environ.copy()
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    env["JOURNEY_CLONER_OUT_DIR"] = str(OUTPUT_DIR)
    if token.strip():
        env["AUTH_TOKEN"] = token.strip()

    display_cmd = " ".join(
        ["AUTH_TOKEN=***" if token.strip() else "AUTH_TOKEN=(from .env)", *[
            part if " " not in part else repr(part) for part in cmd
        ]]
    )

    proc = subprocess.run(
        cmd,
        cwd=CLONER_DIR,
        env=env,
        text=True,
        capture_output=True,
        timeout=300,
    )
    output = proc.stdout
    if proc.stderr:
        output += "\nSTDERR:\n" + proc.stderr
    return proc.returncode, output, display_cmd
