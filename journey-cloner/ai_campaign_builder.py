#!/usr/bin/env python3
"""AI-drivable campaign builder — the single entry point an agent (or a human)
uses to design and generate a REA/gr8.tech journey campaign *accurately*.

It is deliberately grounded: every choosable value comes from `catalog.json`
(the Phase-1 extract of the real captured journeys) and every flow is validated
by the exact Phase-3 gatekeeper in `plan_lint.py`. It never invents an activity,
an event, or a transition, and it never POSTs to the live backoffice.

An agent uses it in three moves:

  1. DISCOVER what it may choose (sources, activities, events, legal next
     steps, channels, rewards, segments, recipes, automations + their knobs):

        python ai_campaign_builder.py options --json

  2. PLAN a flow from structured input (source + PROMOTION/etc.), and have it
     validated by plan_lint before anyone commits:

        echo '{"campaign":"Win-back 50 FS","source":"segment[301]",
               "recipe":"free spins after a deposit",
               "knobs":{"freespin_bonus":{"spins":50,"game":"lagrancopa"}}}' \
          | python ai_campaign_builder.py plan - --json

  3. BUILD it by dispatching to the correct real compiler (safe dry-run by
     default -> writes prepared payloads under out/; --execute emits the
     browser console script instead; neither performs a live POST):

        echo '{"automation":"casino","args":{"date":"2026-08-01",
               "bets":[120,200,400,800],"game":"lagrancopa","spins":50}}' \
          | python ai_campaign_builder.py build - --json

All three modes accept a JSON object from a file path or '-' (stdin) and, with
--json, print a single machine-readable JSON result. Exit code 0 = success /
approvable; 1 = errors.

Live creation is intentionally out of scope: the compilers emit a console
script (or dry-run payloads); the only path that calls POST /journey-drafts is
create_journeys.py, run by a human with a fresh AUTH_TOKEN. This tool prints
that hand-off step, it does not take it.
"""
from __future__ import annotations

import argparse
import contextlib
import io
import json
import re
import subprocess
import sys
from pathlib import Path

import plan_lint  # reuse the exact gatekeeper (ALIASES, grammar, lint)

HERE = Path(__file__).resolve().parent
CATALOG = HERE / "catalog.json"


# ── Automations: how a plan maps onto a real compiler ────────────────────────
# Sourced directly from each compiler's argparse (verified, not guessed). Keys
# are the automation `key`s in catalog.json where they overlap. `required` /
# `optional` are the arg names (python style; '_' becomes '--dashed'); `flags`
# are store_true switches. `choices` pins the enumerable ones.
GAMES = ["lagrancopa", "spinandscoremegaways"]  # casino_journey.py / gow_campaign.py GAMES
RANDOMIZER_KINDS = ["sport_wof", "casino_wof", "casino_scratch"]  # randomizer_campaign.py KINDS

AUTOMATIONS: dict[str, dict] = {
    "casino": {
        "script": "casino_journey.py",
        "creates": "a casino campaign journey (deposit -> promotion -> freespin -> wagering) draft/script",
        "required": ["date", "bets"],
        "optional": ["days", "spins", "game", "lobby_game_id", "wallet_game_id",
                     "external_game_id", "provider", "game_name", "provider_name", "name"],
        "choices": {"game": GAMES},
        "flags": ["dry_run"],
    },
    "gow": {
        "script": "gow_combined.py",
        "creates": "Game-of-the-Week campaign journey + promo page + comms journeys + email content (one console script)",
        "required": ["date", "spec"],
        "optional": ["days", "spins", "public_domain", "journey_name",
                     "promo_source_content_id", "promo_source_front_id",
                     "promo_description", "name", "figma_game", "figma_key",
                     "figma_page", "photo", "popup", "email_hero"],
        "choices": {},
        "flags": ["dry_run"],
    },
    "gow_campaign": {
        "script": "gow_campaign.py",
        "creates": "GOW campaign journey + promo page only (no comms)",
        "required": ["date"],
        "optional": ["days", "spec", "bets", "spins", "game", "lobby_game_id",
                     "wallet_game_id", "external_game_id", "provider", "game_name",
                     "provider_name", "promo_source_content_id", "promo_source_front_id",
                     "promo_description", "name", "photo", "figma_game", "figma_key", "figma_page"],
        "choices": {"game": GAMES},
        "flags": ["dry_run"],
    },
    "comms": {
        "script": "comms_campaign.py",
        "creates": "the 2 comms journeys (on-site / pop-up / SMS / email) that link an existing GOW promo page",
        "required": ["date", "promo_page_id", "spec"],
        "optional": ["public_domain", "journey_name", "name"],
        "choices": {},
        "flags": ["dry_run"],
    },
    "sport_wof": {
        "script": "randomizer_campaign.py",
        "creates": "a Sport Wheel-of-Fortune randomizer promo (weighted slices route to journeys)",
        "fixed": {"kind": "sport_wof"},
        "required": [],  # one of date / dates is required; validated below
        "optional": ["date", "dates", "days", "internal_name", "url_short", "weights", "journeys", "name"],
        "choices": {},
        "flags": ["dry_run", "debug"],
    },
    "casino_wof": {
        "script": "randomizer_campaign.py",
        "creates": "a Casino Wheel-of-Fortune randomizer promo",
        "fixed": {"kind": "casino_wof"},
        "required": [],
        "optional": ["date", "dates", "days", "internal_name", "url_short", "weights", "journeys", "name"],
        "choices": {},
        "flags": ["dry_run", "debug"],
    },
    "casino_scratch": {
        "script": "randomizer_campaign.py",
        "creates": "a Raspa-y-Gana scratch-card randomizer promo",
        "fixed": {"kind": "casino_scratch"},
        "required": [],
        "optional": ["date", "dates", "days", "internal_name", "url_short", "weights", "journeys", "name"],
        "choices": {},
        "flags": ["dry_run", "debug"],
    },
    "nc_discount": {
        "script": "nc_discount_campaign.py",
        "creates": "a notification-center discount comms script",
        "required": [],
        "optional": ["name"],
        "choices": {},
        "flags": ["dry_run"],
    },
}

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def load_catalog() -> dict:
    return json.loads(CATALOG.read_text(encoding="utf-8"))


# ── Mode 1: options ──────────────────────────────────────────────────────────
def build_options(cat: dict) -> dict:
    """The full menu of what may be chosen, all derived from catalog.json."""
    acts = {a["key"]: a for a in cat["activities"]}

    # legal next steps per activity, straight from the observed grammar
    next_by_from: dict[str, list] = {}
    for t in cat["transitions_observed"]:
        next_by_from.setdefault(t["from"], []).append({"event": t["on_event"], "to": t["to"]})

    activities = []
    for key, a in sorted(acts.items()):
        activities.append({
            "key": key,
            "purpose": a.get("purpose", ""),
            "emits_events": [re.sub(r"\s*\(.*\)$", "", e) for e in a.get("emits_events", [])],
            "knobs": a.get("knobs", []),
            "allowed_next": next_by_from.get(key, []),
            "is_source": key in plan_lint.SOURCE_TYPES,
            "is_channel": key in plan_lint.CHANNELS,
            "is_terminal": key in plan_lint.TERMINALS,
        })

    return {
        "brand": cat.get("meta", {}).get("brand"),
        "sources": [
            {"token": "segment[<template_id>]", "resolves_to": "dwh_source",
             "note": "segment/DWH-targeted entry; use a segment template_id from `segments` below"},
            {"token": "api[<label>]", "resolves_to": "external_system_source",
             "note": "API/external trigger entry (no audience filter)"},
        ],
        "aliases": {k: v for k, v in plan_lint.ALIASES.items() if v},
        "activities": activities,
        "channels": cat.get("channels", {}),
        "reward_presets": cat.get("reward_presets", []),
        "segments": cat.get("segments", []),
        "recipes": cat.get("recipes", []),
        "invariants": cat.get("invariants", []),
        "automations": {
            key: {
                "script": spec["script"],
                "creates": spec["creates"],
                "required": spec.get("required", []),
                "optional": spec.get("optional", []),
                "choices": spec.get("choices", {}),
                "flags": spec.get("flags", []),
                **({"fixed": spec["fixed"]} if "fixed" in spec else {}),
            }
            for key, spec in AUTOMATIONS.items()
        },
    }


# ── Mode 2: plan (build DSL + validate with plan_lint) ───────────────────────
def _source_key(source: str) -> str | None:
    m = re.match(r"(\w+)", source.strip())
    kind = (m.group(1).lower() if m else "")
    if kind == "segment":
        return "dwh_source"
    if kind in ("api", "external", "external_system_source"):
        return "external_system_source"
    return None


def _event_between(grammar: set, frm: str, to: str) -> str | None:
    """Pick an observed event that legally connects frm -> to, preferring the
    'positive/forward' one (Satisfied/Accepted/Completed/Sent/Finished/...)."""
    cands = [e for (f, e, t) in grammar if f == frm and t == to]
    if not cands:
        return None
    forward = re.compile(r"(Satisf|Accept|Complet|Sent|Finish|Success|Added|Collect)", re.I)
    cands.sort(key=lambda e: (0 if forward.search(e) else 1, e))
    return cands[0]


def expand_recipe(cat: dict, source: str, recipe_name: str, knobs: dict) -> tuple[list[dict], list[str]]:
    """Turn a curated recipe into concrete edges by *walking the observed
    grammar* over the recipe's activity set — so every emitted edge is a real
    (from, event, to) triple seen in a captured journey, in the order the
    platform actually wires them (not the recipe's logical listing order).
    Returns (edges, notes)."""
    notes: list[str] = []
    recipe = next((r for r in cat["recipes"] if r["intent"].lower() == recipe_name.lower()), None)
    if recipe is None:
        raise ValueError(f"unknown recipe {recipe_name!r}. Known: "
                         + ", ".join(r["intent"] for r in cat["recipes"]))
    grammar = {(t["from"], t["on_event"], t["to"]) for t in cat["transitions_observed"]}
    skey = _source_key(source)
    wanted = set(recipe["pattern"])

    edges: list[dict] = []
    visited: set = set()
    current = skey
    # greedy forward walk into still-unvisited recipe nodes
    while True:
        nxt = None
        for target in (wanted - visited):
            ev = _event_between(grammar, current, target)
            if ev:
                nxt = (ev, target)
                break
        if current == skey and nxt is None:
            # no observed source->node edge; fall back to the activation event
            first = next((n for n in recipe["pattern"] if n not in visited), None)
            if first is None:
                break
            nxt = ("PlayerAdded", first)
            notes.append(f"source -> {first} not in observed grammar; used activation event PlayerAdded")
        if nxt is None:
            break
        ev, target = nxt
        edges.append({"from": "source" if current == skey else current,
                      "event": ev, "to": target, "knobs": knobs.get(target, {})})
        visited.add(target)
        current = target

    missing = wanted - visited
    if missing:
        notes.append(f"recipe nodes not reachable via observed grammar from this source: {sorted(missing)}")

    # terminal from the last reached node
    if current not in plan_lint.TERMINALS:
        term_to = "end_of_journey" if _event_between(grammar, current, "end_of_journey") else \
                  ("end_of_path" if _event_between(grammar, current, "end_of_path") else None)
        if term_to:
            edges.append({"from": current, "event": _event_between(grammar, current, term_to),
                          "to": term_to, "knobs": {}})
        else:
            notes.append(f"no observed terminal transition from {current}; add an explicit `end` edge if needed")
    return edges, notes


def _knobs_to_str(knobs) -> str:
    if not knobs:
        return ""
    if isinstance(knobs, str):
        return knobs
    return ", ".join(f'{k}={json.dumps(v) if isinstance(v, str) else v}' for k, v in knobs.items())


def build_dsl(campaign: str, source: str, edges: list[dict]) -> str:
    lines = [f"campaign: {campaign or '(unnamed)'}", f"source: {source}"]
    for e in edges:
        frm, ev, to = e["from"], e.get("event", ""), e["to"]
        lhs = f"{frm}.{ev}" if ev else frm
        knob = _knobs_to_str(e.get("knobs"))
        rhs = f"{to}({knob})" if knob else to
        lines.append(f"{lhs} -> {rhs}")
    return "\n".join(lines) + "\n"


def do_plan(spec: dict) -> dict:
    cat = load_catalog()
    campaign = spec.get("campaign", "")
    source = spec.get("source", "")
    if not source:
        return {"ok": False, "approvable": False, "errors": ["missing `source` (e.g. \"segment[301]\" or \"api[PromoPage]\")"]}

    notes: list[str] = []
    if "edges" in spec and spec["edges"]:
        edges = spec["edges"]
    elif "recipe" in spec:
        edges, notes = expand_recipe(cat, source, spec["recipe"], spec.get("knobs", {}))
    else:
        return {"ok": False, "approvable": False,
                "errors": ["provide either `edges` (explicit) or `recipe` (a name from options.recipes)"]}

    dsl = build_dsl(campaign, source, edges)

    # run the exact gatekeeper, capturing its report
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        code = plan_lint.lint(dsl)
    report = buf.getvalue()

    return {
        "ok": code == 0,
        "approvable": code == 0,
        "dsl": dsl,
        "edges": edges,
        "notes": notes,
        "lint_report": report.strip().splitlines(),
    }


# ── Mode 3: build (dispatch to the real compiler) ────────────────────────────
def _validate_args(auto: str, spec: dict, args: dict) -> list[str]:
    errs: list[str] = []
    cfg = AUTOMATIONS[auto]
    for req in cfg.get("required", []):
        if req not in args or args[req] in (None, "", []):
            errs.append(f"missing required arg {req!r} for automation {auto!r}")
    for name, allowed in cfg.get("choices", {}).items():
        if name in args and args[name] not in allowed:
            errs.append(f"{name}={args[name]!r} not in {allowed}")
    # semantic checks grounded in the compilers / catalog invariants
    for dkey in ("date",):
        if args.get(dkey) and not _DATE_RE.match(str(args[dkey])):
            errs.append(f"{dkey} must be YYYY-MM-DD, got {args[dkey]!r}")
    if auto in ("sport_wof", "casino_wof", "casino_scratch") and not (args.get("date") or args.get("dates")):
        errs.append("randomizer needs `date` or `dates`")
    if "bets" in args and args["bets"]:
        b = args["bets"]
        if not (isinstance(b, list) and all(isinstance(x, int) for x in b)):
            errs.append("bets must be a list of integers (major units, ascending)")
        elif b != sorted(b):
            errs.append(f"bets should be ascending by deposit tier, got {b}")
    if "weights" in args and args["weights"]:
        try:
            total = sum(float(w) for w in args["weights"])
            if abs(total - 100.0) > 0.001:
                errs.append(f"randomizer prize weights must sum to 100, got {total}")
        except (TypeError, ValueError):
            errs.append("weights must be numbers")
    return errs


def build_command(auto: str, args: dict, execute: bool) -> list[str]:
    cfg = AUTOMATIONS[auto]
    cmd = [sys.executable, str(HERE / cfg["script"])]
    merged = dict(cfg.get("fixed", {}))
    merged.update(args)
    flags = set(cfg.get("flags", []))
    for name, val in merged.items():
        opt = "--" + name.replace("_", "-")
        if name in flags:
            if val:
                cmd.append(opt)
            continue
        if val is None or val == "":
            continue
        if isinstance(val, (list, tuple)):
            cmd.append(opt)
            cmd.extend(str(v) for v in val)
        else:
            cmd.extend([opt, str(val)])
    # safety: default to the compiler's dry-run unless the caller explicitly executes
    if not execute and "dry_run" in flags and not merged.get("dry_run"):
        cmd.append("--dry-run")
    return cmd


def do_build(spec: dict, execute: bool, run: bool) -> dict:
    auto = spec.get("automation")
    if auto not in AUTOMATIONS:
        return {"ok": False, "errors": [f"unknown automation {auto!r}. Known: {', '.join(AUTOMATIONS)}"]}
    args = spec.get("args", {})
    errs = _validate_args(auto, spec, args)
    if errs:
        return {"ok": False, "automation": auto, "errors": errs}

    cmd = build_command(auto, args, execute)
    result = {
        "ok": True,
        "automation": auto,
        "script": AUTOMATIONS[auto]["script"],
        "command": cmd,
        "mode": "execute (emit console script / real payload)" if execute else "dry-run (prepared payloads to out/)",
        "live_post": False,
        "handoff": "To create drafts live: paste the emitted console script into a logged-in "
                   "backoffice DevTools console, OR run create_journeys.py with a fresh AUTH_TOKEN. "
                   "This tool never calls POST /journey-drafts.",
    }
    if run:
        proc = subprocess.run(cmd, cwd=str(HERE), capture_output=True, text=True)
        result["returncode"] = proc.returncode
        result["stdout"] = proc.stdout
        result["stderr"] = proc.stderr
        result["ok"] = proc.returncode == 0
    return result


# ── CLI ──────────────────────────────────────────────────────────────────────
def _read_spec(arg: str) -> dict:
    text = sys.stdin.read() if arg == "-" else Path(arg).read_text(encoding="utf-8")
    return json.loads(text)


def _emit(obj: dict, as_json: bool) -> None:
    if as_json:
        print(json.dumps(obj, ensure_ascii=False, indent=2))
        return
    # human summary
    if "lint_report" in obj:
        print(obj["dsl"])
        for line in obj["lint_report"]:
            print(line)
        for n in obj.get("notes", []):
            print(f"  note  {n}")
    elif "command" in obj:
        print(f"automation: {obj['automation']}  ({obj['script']})  mode={obj['mode']}")
        print("command:", " ".join(obj["command"]))
        if "stdout" in obj:
            print("--- stdout ---\n" + obj["stdout"])
            if obj.get("stderr"):
                print("--- stderr ---\n" + obj["stderr"])
        print(obj["handoff"])
    else:
        print(json.dumps(obj, ensure_ascii=False, indent=2))


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="mode", required=True)

    po = sub.add_parser("options", help="dump the catalog-derived menu of everything choosable")
    po.add_argument("--json", action="store_true")

    pp = sub.add_parser("plan", help="build a flow DSL from structured input and validate it with plan_lint")
    pp.add_argument("spec", help="JSON spec file path, or '-' for stdin")
    pp.add_argument("--json", action="store_true")

    pb = sub.add_parser("build", help="dispatch an approved campaign to the correct real compiler")
    pb.add_argument("spec", help="JSON spec file path, or '-' for stdin")
    pb.add_argument("--execute", action="store_true",
                    help="emit the console script / real payload instead of a dry-run (still never POSTs live)")
    pb.add_argument("--run", action="store_true",
                    help="actually invoke the compiler subprocess (default: just construct & return the command)")
    pb.add_argument("--json", action="store_true")

    a = p.parse_args()

    if a.mode == "options":
        _emit(build_options(load_catalog()), a.json or True if not sys.stdout.isatty() else a.json)
        return 0
    if a.mode == "plan":
        res = do_plan(_read_spec(a.spec))
        _emit(res, a.json)
        return 0 if res.get("approvable") else 1
    if a.mode == "build":
        res = do_build(_read_spec(a.spec), a.execute, a.run)
        _emit(res, a.json)
        return 0 if res.get("ok") else 1
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
