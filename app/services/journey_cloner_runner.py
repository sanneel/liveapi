"""Run the Journey Cloner CLI from the integrated admin UI."""

from __future__ import annotations

import datetime
import os
import json
import re
import subprocess
import sys
import uuid
from pathlib import Path
from typing import Any, Dict, List, Tuple

from ..config import BASE_DIR, get_settings


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
COMMS_SCRIPT_PATH = CLONER_DIR / "comms_campaign.py"
COMBINED_SCRIPT_PATH = CLONER_DIR / "gow_combined.py"
RANDOMIZER_SCRIPT_PATH = CLONER_DIR / "randomizer_campaign.py"
NC_DISCOUNT_SCRIPT_PATH = CLONER_DIR / "nc_discount_campaign.py"
NC_DISCOUNT_PMCL_SCRIPT_PATH = CLONER_DIR / "nc_discount_pmcl_campaign.py"
PREDICTION_SCRIPT_PATH = CLONER_DIR / "prediction_campaign.py"
TOURNAMENT_PMCL_SCRIPT_PATH = CLONER_DIR / "tournament_pmcl_campaign.py"
COMPOSE_SCRIPT_PATH = CLONER_DIR / "compose.py"
CHAIN_COMPOSER_SCRIPT_PATH = CLONER_DIR / "journey_composer.py"
BET_AND_GET_PMCL_SCRIPT_PATH = CLONER_DIR / "bet_and_get_pmcl_campaign.py"
SPORT_COMMS_SCRIPT_PATH = CLONER_DIR / "sport_comms_campaign.py"
COMMS_BUILDER_SCRIPT_PATH = CLONER_DIR / "comms_builder.py"

# Randomizer promos (weighted prize wheels / scratch cards). Keys must match
# randomizer_campaign.py --kind.
RANDOMIZER_KINDS: Dict[str, str] = {
    "sport_wof": "Sport Wheel of Fortune",
    "casino_wof": "Casino Wheel of Fortune",
    "casino_scratch": "Raspa y Gana (Scratch Card)",
}


def _date_slug(date: str) -> str:
    return re.sub(r"[^0-9]", "", date) or "date"


def _unique_basename(prefix: str, date: str) -> str:
    # console_scripts/<basename>_console.js is a shared filesystem path, and
    # _run_gow_cli writes then immediately reads it back. A date-only name
    # let two concurrent requests for the same date (the sync route runs in
    # FastAPI's threadpool, so this does happen) race: one request's read
    # could pick up the other request's freshly-overwritten file instead of
    # its own. The uuid suffix makes every generated script its own file.
    return f"{prefix}_{_date_slug(date)}_{uuid.uuid4().hex[:8]}"


def _run_gow_cli(
    cmd: List[str], *, spec_text: str | None = None, basename: str
) -> Tuple[int, str, str, str | None, str]:
    """Run one of the generator CLIs. When spec_text is given it is piped via
    stdin (the gow_*.py spec-driven flow); randomizer CLIs pass None.

    Returns (returncode, output_log, display_cmd, js_text or None, js_filename).
    """
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    # Make the .env-configured Figma token visible to the subprocess so a
    # --figma-game export can reach api.figma.com (same source figma_runner uses).
    figma_token = (get_settings().figma_token or os.environ.get("FIGMA_TOKEN", "")).strip()
    if figma_token:
        env["FIGMA_TOKEN"] = figma_token

    display_cmd = " ".join(
        part if " " not in part else repr(part) for part in cmd
    ) + ("  < (pasted spec piped via stdin)" if spec_text is not None else "")

    proc = subprocess.run(
        cmd,
        cwd=CLONER_DIR,
        env=env,
        text=True,
        encoding="utf-8",
        capture_output=True,
        timeout=300,
        input=spec_text,
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


def generate_gow_console_script(
    *,
    date: str,
    spec_text: str,
    spins: int | None = None,
    figma_game: str = "",
    figma_key: str = "",
) -> Tuple[int, str, str, str | None, str]:
    """Generate the paste-into-DevTools console script for a Game-of-the-Week
    casino campaign (free-spin offer + 4 deposit tiers + promo page).

    Game name, provider, and bet tiers are all parsed from the pasted spec
    blob; the real game ids are resolved from the live games catalog at
    paste time. When figma_game is given, the campaign photo is exported from
    Figma and embedded (no file picker).

    Returns (returncode, output_log, display_cmd, js_text or None, js_filename).
    """
    basename = _unique_basename("gow_campaign", date)
    cmd = [
        python_executable(),
        str(GOW_SCRIPT_PATH),
        "--date",
        date.strip(),
        "--spec",
        "-",
        "--name",
        basename,
    ]
    if spins is not None:
        cmd += ["--spins", str(spins)]
    if figma_game.strip():
        cmd += ["--figma-game", figma_game.strip()]
        if figma_key.strip():
            cmd += ["--figma-key", figma_key.strip()]
    return _run_gow_cli(cmd, spec_text=spec_text, basename=basename)


def generate_comms_console_script(
    *,
    date: str,
    spec_text: str,
    promo_page_id: str,
    public_domain: str = "",
    journey_name: str = "",
) -> Tuple[int, str, str, str | None, str]:
    """Generate the paste-into-DevTools console script for the GOW
    communications journey (Notification Center + Pop-up + SMS; Email is
    left untouched and edited by hand). The window is always the same day,
    12:00 -> 19:00 Chile time.

    Notification/Pop-up/SMS copy is parsed from the pasted spec blob.

    Returns (returncode, output_log, display_cmd, js_text or None, js_filename).
    """
    basename = _unique_basename("gow_comms", date)
    cmd = [
        python_executable(),
        str(COMMS_SCRIPT_PATH),
        "--date",
        date.strip(),
        "--promo-page-id",
        promo_page_id.strip(),
        "--spec",
        "-",
        "--name",
        basename,
    ]
    if public_domain.strip():
        cmd += ["--public-domain", public_domain.strip()]
    if journey_name.strip():
        cmd += ["--journey-name", journey_name.strip()]
    return _run_gow_cli(cmd, spec_text=spec_text, basename=basename)


def generate_gow_combined_console_script(
    *,
    date: str,
    spec_text: str,
    days: int = 1,
    spins: int | None = None,
    public_domain: str = "",
    journey_name: str = "",
    figma_game: str = "",
    figma_key: str = "",
) -> Tuple[int, str, str, str | None, str]:
    """Generate the paste-into-DevTools console script that creates the GOW
    casino campaign (free-spin offer + promo page) AND the communications
    journey (Notification Center + Pop-up + SMS) together in one paste, with
    the comms links pointed at the promo page created in the same run.

    When ``figma_game`` is given, the campaign/NC/Pop-up images are exported
    from Figma and embedded into the script so no file pickers appear at paste
    time. Requires FIGMA_TOKEN to be configured (read from settings/env).

    Returns (returncode, output_log, display_cmd, js_text or None, js_filename).
    """
    basename = _unique_basename("gow_combined", date)
    cmd = [
        python_executable(),
        str(COMBINED_SCRIPT_PATH),
        "--date",
        date.strip(),
        "--days",
        str(days),
        "--spec",
        "-",
        "--name",
        basename,
    ]
    if spins is not None:
        cmd += ["--spins", str(spins)]
    if public_domain.strip():
        cmd += ["--public-domain", public_domain.strip()]
    if journey_name.strip():
        cmd += ["--journey-name", journey_name.strip()]
    if figma_game.strip():
        cmd += ["--figma-game", figma_game.strip()]
        if figma_key.strip():
            cmd += ["--figma-key", figma_key.strip()]
    return _run_gow_cli(cmd, spec_text=spec_text, basename=basename)


def generate_randomizer_console_script(
    *,
    kind: str,
    date: str,
    days: str = "",
    weights: str = "",
    journeys: str = "",
) -> Tuple[int, str, str, str | None, str]:
    """Generate the console script for one or MORE Randomizer promos (Sport WOF,
    Casino WOF, or Raspa y Gana scratch card). `date` may hold several dates
    (space/comma/newline separated) -> one draft per date, created in one paste.
    Prizes/segment/visual come from the captured template; only dates, name and
    optional weights/journeys change.

    Returns (returncode, output_log, display_cmd, js_text or None, js_filename).
    """
    if kind not in RANDOMIZER_KINDS:
        raise ValueError(f"Unknown randomizer kind: {kind}")
    dates = [d for d in re.split(r"[\s,;]+", date.strip()) if d]
    if not dates:
        raise ValueError("At least one date is required.")
    basename = _unique_basename(f"randomizer_{kind}", dates[0])
    cmd = [
        python_executable(),
        str(RANDOMIZER_SCRIPT_PATH),
        "--kind", kind,
        "--dates", *dates,
        "--name", basename,
    ]
    if days.strip():
        cmd += ["--days", days.strip()]
    if weights.strip():
        cmd += ["--weights", *weights.split()]
    if journeys.strip():
        cmd += ["--journeys", *journeys.split()]
    return _run_gow_cli(cmd, basename=basename)


def generate_tournament_pmcl_console_script(
    *,
    date: str,
    spec_text: str,
    tournament_id: str = "",
    folder_id: str = "",
    journey_name: str = "",
    tournament_start: str = "",
    tournament_end: str = "",
    no_photos: bool = False,
) -> Tuple[int, str, str, str | None, str]:
    """Generate the paste-into-DevTools console script for the PMCL (Fortunazo)
    tournament communications journey (Notification Center + Pop-up + SMS; email
    left untouched). Copy comes from the pasted spec blob; every channel's link
    is pointed at the Smartico tournament deeplink. When a media-library
    ``folder_id`` is given the script uploads a fresh NC icon + Pop-up
    background, otherwise the template's existing images are kept.

    ``tournament_start`` / ``tournament_end`` (YYYY-MM-DD) set the two Wait/Date
    activities and the notification revoke period to the exact tournament run.
    Both override the spec's own "Start date"/"End date" rows when given.

    Returns (returncode, output_log, display_cmd, js_text or None, js_filename).
    """
    basename = _unique_basename("tournament_pmcl", date)
    cmd = [
        python_executable(),
        str(TOURNAMENT_PMCL_SCRIPT_PATH),
        "--date",
        date.strip(),
        "--spec",
        "-",
        "--name",
        basename,
    ]
    if tournament_id.strip():
        cmd += ["--tournament-id", tournament_id.strip()]
    if folder_id.strip():
        cmd += ["--folder-id", folder_id.strip()]
    if journey_name.strip():
        cmd += ["--journey-name", journey_name.strip()]
    if tournament_start.strip():
        cmd += ["--tournament-start", tournament_start.strip()]
    if tournament_end.strip():
        cmd += ["--tournament-end", tournament_end.strip()]
    if no_photos:
        cmd += ["--no-photos"]
    return _run_gow_cli(cmd, spec_text=spec_text, basename=basename)


def generate_nc_discount_pmcl_console_script(folder_id: str) -> Tuple[int, str, str, str | None, str]:
    """Generate the "NC For Discount PMCL" console script for fortunazo.cl."""
    basename = _unique_basename("nc_discount_pmcl", "")
    cmd = [python_executable(), str(NC_DISCOUNT_PMCL_SCRIPT_PATH),
           "--name", basename, "--folder-id", folder_id]
    return _run_gow_cli(cmd, basename=basename)


def generate_prediction_console_script(
    *,
    sheet_text: str,
    draft_id: str,
    content_id: str,
    front_id: str,
    base_body_path: str = "",
    name: str = "",
    dry_run: bool = False,
) -> Tuple[int, str, str, str | None, str]:
    """Generate (or dry-run) a Multi Number Prediction promo update from a
    pasted Google Sheets table, via prediction_campaign.py. sheet_text is
    piped via stdin (--sheet -), same as the gow/comms spec textareas.

    Returns (returncode, output_log, display_cmd, js_text or None, basename).
    When dry_run is True, js_text is always None -- prediction_campaign.py
    writes the 9 request bodies + a request plan to out/<basename>/ instead
    of a console script, and that request plan is appended to output_log so
    it's still visible without pasting anything.
    """
    if not draft_id.strip() or not content_id.strip() or not front_id.strip():
        raise ValueError("Draft id, Content id, and Front id are all required.")
    basename = name.strip() or _unique_basename("prediction", draft_id.strip())
    cmd = [
        python_executable(),
        str(PREDICTION_SCRIPT_PATH),
        "--sheet", "-",
        "--draft-id", draft_id.strip(),
        "--content-id", content_id.strip(),
        "--front-id", front_id.strip(),
        "--name", basename,
    ]
    if base_body_path.strip():
        cmd += ["--base-body", base_body_path.strip()]
    if dry_run:
        cmd.append("--dry-run")

    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    display_cmd = " ".join(
        part if " " not in part else repr(part) for part in cmd
    ) + "  < (pasted sheet piped via stdin)"

    proc = subprocess.run(
        cmd,
        cwd=CLONER_DIR,
        env=env,
        text=True,
        encoding="utf-8",
        capture_output=True,
        timeout=120,
        input=sheet_text,
    )
    output = proc.stdout
    if proc.stderr:
        output += "\nSTDERR:\n" + proc.stderr

    if dry_run:
        plan_path = CLONER_DIR / "out" / basename / "00_request_plan.txt"
        if proc.returncode == 0 and plan_path.exists():
            output += "\n\n" + plan_path.read_text(encoding="utf-8")
        return proc.returncode, output, display_cmd, None, basename

    js_filename = f"{basename}_console.js"
    js_text = None
    if proc.returncode == 0:
        js_path = CLONER_DIR / "console_scripts" / js_filename
        if js_path.exists():
            js_text = js_path.read_text(encoding="utf-8")
        else:
            output += f"\nERROR: expected script file not found: {js_path}"
    return proc.returncode, output, display_cmd, js_text, js_filename


def generate_sport_comms_console_script(
    *,
    campaign_slug: str,
    sheet_text: str,
    promo_link: str = "",
    stop_at: str = "",
    name: str = "",
    dry_run: bool = False,
) -> Tuple[int, str, str, str | None, str]:
    """Build the sport scratch-card comms journey for a liveapi campaign.

    Wraps journey-cloner/sport_comms_campaign.py. The pasted content sheet goes
    in over stdin (--spec -) so it never touches disk; the campaign is read from
    this app's own database by the generator.

    Returns (returncode, output_log, display_cmd, js_text or None, basename).
    A refusal — no such campaign, no expiry, a sheet missing its Link row, or a
    verify() check that failed — exits non-zero with the reason in the log, and
    js_text is None. That is the generator working, not a crash.
    """
    if not campaign_slug.strip():
        raise ValueError("Pick the liveapi campaign this promo belongs to.")
    if not sheet_text.strip():
        raise ValueError("Paste the content sheet (channel copy + the Link row).")

    # _unique_basename slugs on digits only, which would flatten a campaign
    # slug to "date". Keep the slug readable; the uuid still makes the
    # console_scripts/<basename>.js path unique per request.
    safe = re.sub(r"[^a-z0-9]+", "-", campaign_slug.strip().lower()).strip("-") or "campaign"
    basename = name.strip() or f"sport_comms_{safe}_{uuid.uuid4().hex[:8]}"
    cmd = [
        python_executable(),
        str(SPORT_COMMS_SCRIPT_PATH),
        "--campaign", campaign_slug.strip(),
        "--spec", "-",
        "--name", basename,
    ]
    if promo_link.strip():
        cmd += ["--promo-link", promo_link.strip()]
    if stop_at.strip():
        cmd += ["--stop-at", stop_at.strip()]
    if dry_run:
        cmd.append("--dry-run")

    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    display_cmd = " ".join(
        part if " " not in part else repr(part) for part in cmd
    ) + "  < (pasted sheet piped via stdin)"

    proc = subprocess.run(
        cmd,
        cwd=CLONER_DIR,
        env=env,
        text=True,
        encoding="utf-8",
        capture_output=True,
        timeout=120,
        input=sheet_text,
    )
    output = proc.stdout
    if proc.stderr:
        output += "\nSTDERR:\n" + proc.stderr

    if dry_run:
        return proc.returncode, output, display_cmd, None, basename

    js_filename = f"{basename}_console.js"
    js_text = None
    if proc.returncode == 0:
        js_path = CLONER_DIR / "console_scripts" / js_filename
        if js_path.exists():
            js_text = js_path.read_text(encoding="utf-8")
        else:
            output += f"\nERROR: expected script file not found: {js_path}"
    return proc.returncode, output, display_cmd, js_text, js_filename


def git_pull() -> Tuple[int, str]:
    """Run git pull in the repo root. Returns (returncode, combined output)."""
    import subprocess
    repo_root = str(CLONER_DIR.parent)
    result = subprocess.run(
        ["git", "pull"],
        cwd=repo_root,
        capture_output=True,
        text=True,
        timeout=60,
    )
    return result.returncode, (result.stdout + result.stderr).strip()


def _strip_fences(text: str) -> str:
    """Return the JSON object inside a planner reply — the last ```json block if
    fenced, else the first balanced {...}, else the text as-is. Mirrors
    compose._extract_json, which is not importable from here (journey-cloner is
    not a package on the app's path)."""
    blob = (text or "").strip()
    fences = re.findall(r"```(?:json|JSON)?\s*(.*?)```", blob, re.S)
    if fences:
        return fences[-1].strip()
    depth, start = 0, None
    for i, ch in enumerate(blob):
        if ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}" and depth:
            depth -= 1
            if depth == 0 and start is not None:
                return blob[start:i + 1]
    return blob


def generate_composed_console_script(
    spec_text: str, *, mode: str = "spec"
) -> Tuple[int, str, str, str | None, str]:
    """Turn a planner reply into a pasteable console script.

    `spec_text` is the LLM's reply VERBATIM — compose.py's _extract_json pulls
    the object out of a ```json fence or a "Here is the spec:" lead-in, so the
    operator never has to hand-clean it. A spec the composer refuses (unknown
    recipe, ⛔ blocker, invented knob or game, out-of-range amount) exits 3 and
    the refusal text comes back in the log for the operator to paste back into
    the chat.

    mode: "spec"       -> compose.py --spec            (MODE 3 recipe spec)
          "graph"      -> compose.py --graph           (MODE 4 linear graph)
          "chain"      -> journey_composer.py compose  (MODE 5 arbitrary chain —
                          repeated activities, choosable flows, branches)
          "randomizer" -> randomizer_campaign.py       (MODE 6 wheel / scratch
                          card; flag-driven, so the spec becomes argv)
          "batch"      -> compose.py --batch            (many recipe specs into
                          ONE script: one token capture, one paste, N drafts)

    Returns (returncode, output_log, display_cmd, js_text or None, js_filename).
    """
    if mode not in ("spec", "graph", "chain", "randomizer", "batch"):
        raise ValueError(
            f"mode must be 'spec', 'graph', 'chain', 'randomizer' or "
            f"'batch', got {mode!r}")
    # Date the artifact so console_scripts/ stays browsable; _unique_basename's
    # uuid suffix keeps concurrent requests from reading each other's file.
    basename = _unique_basename("planner", datetime.date.today().isoformat())
    if mode == "randomizer":
        # randomizer_campaign.py is flag-driven, not stdin-driven, so the spec is
        # translated into argv here rather than piped.
        try:
            spec = json.loads(_strip_fences(spec_text))
        except ValueError as exc:
            return 3, f"⛔ REFUSED — could not parse a randomizer spec: {exc}", "", None, ""
        cmd = [python_executable(), str(RANDOMIZER_SCRIPT_PATH),
               "--kind", str(spec.get("kind", "")), "--name", basename]
        dates = spec.get("dates") or ([spec["date"]] if spec.get("date") else [])
        if not dates:
            return 3, "⛔ REFUSED — randomizer spec needs `date` or `dates`.", "", None, ""
        cmd += (["--dates", *[str(d) for d in dates]] if len(dates) > 1
                else ["--date", str(dates[0])])
        if spec.get("days"):
            cmd += ["--days", str(spec["days"])]
        if spec.get("weights"):
            cmd += ["--weights", *[str(w) for w in spec["weights"]]]
        if spec.get("journeys"):
            cmd += ["--journeys", *[str(j) for j in spec["journeys"]]]
        if spec.get("internal_name"):
            cmd += ["--internal-name", str(spec["internal_name"])]
        if spec.get("url_short"):
            cmd += ["--url-short", str(spec["url_short"])]
        return _run_gow_cli(cmd, basename=basename)
    if mode == "batch":
        # Many recipe specs -> ONE console script. Exit 4 means PARTIAL: some
        # composed, some refused, and the script still carries the ones that
        # worked — worth returning, since _run_gow_cli only reads the file on 0.
        cmd = [python_executable(), str(COMPOSE_SCRIPT_PATH), "--batch",
               "--name", basename]
        code, log, display_cmd, js, js_name = _run_gow_cli(
            cmd, spec_text=spec_text, basename=basename)
        if code == 4 and js is None:
            js_path = CLONER_DIR / "console_scripts" / f"{basename}_console.js"
            if js_path.exists():
                js = js_path.read_text(encoding="utf-8")
        return code, log, display_cmd, js, js_name
    if mode == "chain":
        cmd = [python_executable(), str(CHAIN_COMPOSER_SCRIPT_PATH), "compose", "-",
               "--script", "--name", basename]
    else:
        cmd = [python_executable(), str(COMPOSE_SCRIPT_PATH), f"--{mode}",
               "--name", basename]
    return _run_gow_cli(cmd, spec_text=spec_text, basename=basename)


def generate_nc_discount_console_script() -> Tuple[int, str, str, str | None, str]:
    """Generate the "NC For Discount" console script: one notification journey
    per game/day from the baked July calendar (segment -> notification -> end).

    Returns (returncode, output_log, display_cmd, js_text or None, js_filename).
    """
    basename = _unique_basename("nc_discount", "")
    cmd = [python_executable(), str(NC_DISCOUNT_SCRIPT_PATH), "--name", basename]
    return _run_gow_cli(cmd, basename=basename)


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


def generate_bet_and_get_pmcl_console_script(
    *,
    date: str,
    email_spec: str,
    allow_any_weekday: bool = False,
) -> Tuple[int, str, str, str | None, str]:
    """Generate the PMCL "Bet & Get" weekend console script: promo page +
    journey + email, all created as drafts by one paste.

    ``date`` is the promo's Friday (YYYY-MM-DD); the Sunday end is derived.
    ``email_spec`` is the pasted Subject / Pre-header / Body text.
    """
    basename = _unique_basename("pmcl_bet_and_get", date)
    cmd = [
        python_executable(),
        str(BET_AND_GET_PMCL_SCRIPT_PATH),
        "--date", date.strip(),
        "--email-spec", "-",
        "--name", basename,
    ]
    if allow_any_weekday:
        cmd += ["--allow-any-weekday"]
    return _run_gow_cli(cmd, spec_text=email_spec, basename=basename)


def generate_comms_builder_console_script(
    *,
    sheet_text: str,
    channels: List[str],
    splits: List[str],
    waits: Dict[str, str],
    variant: str = "",
    date: str = "",
    days: str = "",
    journey_name: str = "",
    link: str = "",
    email_template: str = "",
    email_heading: str = "",
    artwork: str = "PICK",
) -> Tuple[int, str, str, str | None, str]:
    """Build a JBCL comms journey from ticked channels + the pasted sheet.

    Wraps journey-cloner/comms_builder.py, which is deterministic: the chain is
    exactly the channels/splits/waits passed in, and every word of copy comes
    from the sheet via spec_parser. No model is involved, so there is nothing to
    hallucinate — and a gap (a channel with no copy, a split on SMS, a missing
    link or date) exits non-zero with the reason instead of being filled in.

    The sheet goes in over stdin so it never touches disk.

    Returns (returncode, output_log, display_cmd, js_text or None, js_filename).
    """
    if not sheet_text.strip():
        raise ValueError("Paste the content sheet (the channel copy + the Link row).")
    if not channels:
        raise ValueError("Tick at least one channel.")

    basename = _unique_basename("comms_builder", date)
    cmd = [
        python_executable(),
        str(COMMS_BUILDER_SCRIPT_PATH),
        "--sheet", "-",
        "--channels", ",".join(channels),
        "--splits", ",".join(splits),          # explicit, so "none ticked" means none
        "--out-name", basename,
        "--script",
    ]
    if variant.strip():
        cmd += ["--variant", variant.strip()]
    for chan, dur in waits.items():
        if dur.strip():
            cmd += ["--wait", f"{chan}={dur.strip()}"]
    if date.strip():
        cmd += ["--date", date.strip()]
    if days.strip():
        cmd += ["--days", days.strip()]
    if journey_name.strip():
        cmd += ["--name", journey_name.strip()]
    if link.strip():
        cmd += ["--link", link.strip()]
    if email_template.strip():
        cmd += ["--email-template", email_template.strip()]
    if email_heading.strip():
        cmd += ["--email-heading", email_heading.strip()]
    if artwork.strip() and artwork.strip() != "PICK":
        cmd += ["--artwork", artwork.strip()]

    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    display_cmd = " ".join(
        part if " " not in part else repr(part) for part in cmd
    ) + "  < (pasted sheet piped via stdin)"

    proc = subprocess.run(
        cmd,
        cwd=CLONER_DIR,
        env=env,
        text=True,
        encoding="utf-8",
        capture_output=True,
        timeout=180,
        input=sheet_text,
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
            output += f"\n(expected {js_filename} but it was not written)"
    return proc.returncode, output, display_cmd, js_text, js_filename
