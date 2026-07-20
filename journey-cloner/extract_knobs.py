#!/usr/bin/env python3
"""Extract the KNOBS (editable fields) per activity from the fragment library.

For each activity fragment, flattens its `initializationData` into dotted leaf
paths — the exact strings compose.py's apply_values() / _dotted_set() take — and
records each leaf's example value + type. A keyword heuristic flags the
operator-tunable ones ("primary") vs boilerplate. External-reference leaves
(contentId/frontId/CSE/webhookId/template ids) are flagged separately so a
composer keeps them.

Output: library/knobs.json
  { "<activityName>": {
        "primary": [ {path, example, type} ... ],   # what an operator changes
        "external_refs": [ {path, example} ... ],    # KEEP as-is when composing
        "all": [ {path, example, type} ... ] } }

This is the values schema the LLM spec (#2) fills and the composer applies.
Pure on-disk extraction.
"""
from __future__ import annotations

import glob
import json
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent
FRAG = HERE / "library" / "fragments"
OUT = HERE / "library" / "knobs.json"

_UUID = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")

# Substrings (in the dotted path, lowercased) that mark an operator knob.
PRIMARY = (
    "spins", "betamount", "minbonus", "maxbonus", "amount", "percent", "wager",
    "requirement", "expiration", "duration", "waitperiod", "waitto", "provider",
    "lobbygameid", "gamename", "messagetext", "subject", "preheader", "title",
    "description", "mindeposit", "releaselimit", "limittype", "contribution",
    "coeff", "minodd", "days", "timeout", "withwagering", "bonuspercent",
    "targetsystem", "urlshortname", "promocode", "value", "text",
)
# External references — keep, don't treat as tunable.
EXT_REF = ("contentid", "frontid", "template", "webhookid", "cse-", "promotionid",
           "promotionlinkid", "walletgameid", "externalgameid")

# Boilerplate / mirror / content-tree branches to keep OUT of "primary": these
# are audience filter trees, comms variable arrays, upload progress, and the
# casino_bonus_v2 wageringActivity mirror (dups the top-level knobs).
EXCLUDE = ("filterdetails", "objectforsend", "progressdata", ".variables.",
           "wageringactivity", ".column.", "valuessource", "ispredefinedvalues",
           "boundarydefinition", "displaydata", "useddisplayvariables", "placements.1.")


def _flatten(obj, prefix=""):
    out = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            out += _flatten(v, f"{prefix}.{k}" if prefix else str(k))
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            out += _flatten(v, f"{prefix}.{i}")
    else:
        out.append((prefix, obj))
    return out


def _typename(v) -> str:
    return {bool: "bool", int: "int", float: "float", str: "str",
            type(None): "null"}.get(type(v), type(v).__name__)


def _is_ext(path: str, value) -> bool:
    low = path.lower()
    if any(k in low for k in EXT_REF):
        return True
    if isinstance(value, str) and _UUID.match(value):
        return True
    return False


def _is_primary(path: str, value) -> bool:
    if isinstance(value, (dict, list)):
        return False
    low = path.lower()
    if _is_ext(path, value):
        return False
    if any(k in low for k in EXCLUDE):
        return False
    return any(k in low for k in PRIMARY)


def extract() -> dict:
    out = {}
    for f in sorted(glob.glob(str(FRAG / "*.json"))):
        name = Path(f).stem
        if name.startswith("_"):
            continue
        frag = json.load(open(f, encoding="utf-8"))
        init = (frag.get("activity") or {}).get("initializationData")
        if not init:
            continue
        leaves = _flatten(init, "initializationData")
        primary, ext, allp = [], [], []
        for path, val in leaves:
            allp.append({"path": path, "example": val, "type": _typename(val)})
            if _is_ext(path, val):
                ext.append({"path": path, "example": val})
            elif _is_primary(path, val):
                primary.append({"path": path, "example": val, "type": _typename(val)})
        out[name] = {
            "source_template": frag.get("source_template"),   # paths are relative
            "primary": primary, "external_refs": ext, "all": allp,
        }
    return out


def main() -> int:
    knobs = extract()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(knobs, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"wrote {OUT}  ({len(knobs)} activities with initializationData)")
    print()
    for name in sorted(knobs):
        p = knobs[name]["primary"]
        if not p:
            continue
        print(f"── {name}  ({len(p)} primary knobs, {len(knobs[name]['external_refs'])} ext-refs)")
        for k in p[:10]:
            ex = k["example"]
            ex = (ex[:40] + "…") if isinstance(ex, str) and len(ex) > 40 else ex
            print(f"     {k['path']:52s} = {ex!r} ({k['type']})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
