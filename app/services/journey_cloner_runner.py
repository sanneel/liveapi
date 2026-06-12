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


def save_template_from_fetch(template_type: str, fetch_text: str) -> Dict[str, Any]:
    if template_type not in TEMPLATE_TYPES:
        raise ValueError(f"Unknown template type: {template_type}")
    body = extract_body_from_fetch(fetch_text)
    output_path = CLONER_DIR / "templates" / f"{template_type}.json"
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


def template_status() -> Dict[str, bool]:
    return {
        key: (CLONER_DIR / "templates" / f"{key}.json").exists()
        for key in TEMPLATE_TYPES
    }


def missing_templates(selected_types: List[str]) -> List[str]:
    status = template_status()
    return [key for key in selected_types if not status.get(key)]


def generate_console_script(
    *,
    home: str,
    away: str,
    code: str,
    date: str,
    chile_time: str,
    selected_types: List[str],
) -> Tuple[int, str, str, str | None, str]:
    """Generate the paste-into-DevTools console script for a campaign.

    Returns (returncode, output_log, display_cmd, js_text or None, js_filename).
    """
    match_name = f"{home.strip()} vs {away.strip()}"
    clean_code = code.strip().upper()
    cmd = [
        python_executable(),
        str(CLONER_DIR / "generate_console_script.py"),
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
