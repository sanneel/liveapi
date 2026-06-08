"""Run the Journey Cloner CLI from the integrated admin UI."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Tuple

from ..config import BASE_DIR


CLONER_DIR = BASE_DIR / "journey-cloner"
SCRIPT_PATH = CLONER_DIR / "create_journeys.py"
TEMPLATE_TYPES = ("followup", "bfr", "two_hours", "aft")


def python_executable() -> str:
    if os.name == "nt":
        candidate = CLONER_DIR / ".venv" / "Scripts" / "python.exe"
    else:
        candidate = CLONER_DIR / ".venv" / "bin" / "python"
    if candidate.exists():
        return str(candidate)
    return sys.executable


def template_status() -> Dict[str, bool]:
    return {
        key: (CLONER_DIR / "templates" / f"{key}.json").exists()
        for key in TEMPLATE_TYPES
    }


def missing_templates(selected_types: List[str]) -> List[str]:
    status = template_status()
    return [key for key in selected_types if not status.get(key)]


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
) -> Tuple[int, str, str]:
    match_name = f"{home.strip()} vs {away.strip()}"
    cmd = [
        python_executable(),
        str(SCRIPT_PATH),
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
