#!/usr/bin/env python3
"""Emit generators_catalog.json — what every generator is, for the AI planner.

    python build_generators_catalog.py            # write the file
    python build_generators_catalog.py --check    # exit 1 if it is stale
    python build_generators_catalog.py --print    # stdout, write nothing

The planner used to know about recipes and games but nothing about the twenty-odd
generators, so asked about Welcome Pack or a tournament it had two options: say
nothing useful, or invent. This is the third grounded block alongside
recipes_catalog.json and the games index, and it is built the same way — from the
code, by a command, checked for drift in CI — because a hand-written list of
scripts is exactly the thing that goes quietly stale and then reads as authority.

Every field is derived, never described:

  registry        GENERATORS in app/services/promotions_catalog.py — the one place
                  that says what exists and where it is driven from.
  purpose         that entry's own `what`, plus the script's module docstring
                  summary. Both are already-curated prose with one home each.
  inputs          harvested by running the script's own `--help`. A flag the
                  planner tells an operator about is therefore a flag that
                  exists; if --help cannot run, inputs are omitted rather than
                  guessed.
  driven_from     tab / route / shell, so the planner can route someone to the
                  UI instead of composing a spec for a thing that has a form.
"""
from __future__ import annotations

import argparse
import ast
import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
OUT_FILE = HERE / "generators_catalog.json"
sys.path.insert(0, str(REPO))

HELP_TIMEOUT = 30


def _docstring_summary(path: Path) -> str:
    """The module docstring's first paragraph, collapsed to one line.

    Parsed with ast rather than matched as a string: every generator opens with a
    shebang, so looking for a leading triple quote found nothing and every summary
    came out empty — a silently blank field, which is worse than a missing one.
    """
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (OSError, SyntaxError, ValueError):
        return ""
    doc = ast.get_docstring(tree) or ""
    if not doc:
        return ""
    return " ".join(doc.strip().split("\n\n")[0].split())


def _cli_options(path: Path) -> dict:
    """The script's own --help, reduced to its usage line and flag names.

    Running the real thing rather than parsing the source: a flag the planner
    offers an operator is then a flag that argparse actually accepts.
    """
    py = REPO / ".venv" / "bin" / "python"
    exe = str(py) if py.exists() else sys.executable
    try:
        proc = subprocess.run([exe, str(path), "--help"], capture_output=True,
                              text=True, timeout=HELP_TIMEOUT, cwd=HERE)
    except (OSError, subprocess.TimeoutExpired):
        return {}
    if proc.returncode != 0:
        return {}
    out = proc.stdout
    flags, required = [], []
    for line in out.splitlines():
        stripped = line.strip()
        if not stripped.startswith("-"):
            continue
        flag = stripped.split()[0].rstrip(",")
        if flag in ("-h", "--help") or flag in flags:
            continue
        flags.append(flag)
    # argparse prints required options inside the usage block without brackets.
    usage = out.split("usage:", 1)[-1].split("\n\n", 1)[0] if "usage:" in out else ""
    usage_flat = " ".join(usage.split())
    for flag in flags:
        # "[--foo BAR]" is optional; a bare "--foo BAR" in usage is required.
        if f"[{flag}" not in usage_flat and flag in usage_flat:
            required.append(flag)
    return {"flags": flags, "required": required}


def build() -> dict:
    from app.services.promotions_catalog import GENERATORS

    entries = []
    for g in GENERATORS:
        script = g.get("script")
        path = HERE / script if script else None
        entry = {
            "key": g["key"],
            "label": g["label"],
            "group": g["group"],
            "brand": g["brand"],
            "what": g["what"],
            "script": script,
        }
        if g.get("tab"):
            entry["driven_from"] = f"Optimization tab: {g['tab']}"
        elif g.get("route"):
            entry["driven_from"] = f"page: {g['route']}"
        else:
            entry["driven_from"] = "shell only"
        if g.get("legacy"):
            entry["legacy"] = True
        if g.get("superseded_by"):
            entry["superseded_by"] = g["superseded_by"]
        if path and path.exists():
            summary = _docstring_summary(path)
            if summary:
                entry["summary"] = summary
            cli = _cli_options(path)
            if cli.get("flags"):
                entry["cli"] = cli
        elif script:
            entry["missing_script"] = True
        entries.append(entry)

    return {
        "_legend": {
            "what": "the registry's one-line description of the generator",
            "summary": "the script's own module docstring, first paragraph",
            "driven_from": "where an operator runs it: an Optimization tab, its "
                           "own page, or a shell",
            "cli.required": "flags argparse will refuse to run without",
            "superseded_by": "prefer that generator for anything new",
            "legacy": "kept for reference; do not propose it",
        },
        "_rules": [
            "These are GENERATORS, not composer recipes. They are run by an "
            "operator, not by you: point at the tab and say what it needs.",
            "Never write a spec for one of these — a spec is only for `recipe` "
            "and `chain` shapes in the RECIPES CATALOG.",
            "Only these keys exist. A generator not listed here is ⛔ UNCAPTURED; "
            "say so rather than describing one that might exist.",
            "Quote `what`/`summary` rather than paraphrasing what a script does.",
        ],
        "generators": entries,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", action="store_true",
                    help="exit 1 if the file on disk is not what this would write")
    ap.add_argument("--print", dest="to_stdout", action="store_true",
                    help="print and write nothing")
    args = ap.parse_args()

    payload = json.dumps(build(), ensure_ascii=False, indent=2) + "\n"
    if args.to_stdout:
        print(payload, end="")
        return 0
    if args.check:
        on_disk = OUT_FILE.read_text(encoding="utf-8") if OUT_FILE.exists() else ""
        if on_disk == payload:
            print(f"{OUT_FILE.name} is up to date")
            return 0
        print(f"{OUT_FILE.name} is STALE — run: python {Path(__file__).name}")
        return 1
    OUT_FILE.write_text(payload, encoding="utf-8")
    n = len(json.loads(payload)["generators"])
    print(f"wrote {OUT_FILE} ({n} generators, {len(payload)} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
