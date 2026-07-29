#!/usr/bin/env python3
"""Contract tests for the MODE 1 design renderer (journey-planner/).

The planner emits a `diagram` block, python draws the boards, the operator looks
at the PNGs — the model never sees them. So the renderer must never be the thing
that fails: a sloppy-but-honest diagram has to produce a picture, and a reply
with no diagram at all has to refuse cleanly instead of writing a blank board.

Each check below is a shape a model actually emitted:

  * the block inside a ```json fence, with prose around it   -> parsed
  * `randomizer` as a SIBLING of `diagram`                   -> still gets a board
  * a node as a bare string, a chain as "a → b → c"          -> parsed
  * wire activity names (`freespin_bonus`, `dextra_email`)   -> mapped to a family
  * flags as one string instead of a list                    -> parsed
  * a reply with no diagram                                  -> refused, exit 3

No network, no live server. Run: python scripts/test_journey_design.py
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "journey-planner"))

import render_journey_design as R  # noqa: E402

FAILURES: list[str] = []


def check(label: str, condition: bool, detail: str = "") -> None:
    if condition:
        print(f"  [OK]   {label}")
    else:
        FAILURES.append(f"{label}: {detail}")
        print(f"  [FAIL] {label} — {detail}")


# ── family resolution ──────────────────────────────────────────────────────
for wire, expected in [
    ("freespin_bonus", "freespins"), ("free_spins", "freespins"),
    ("external_system_source", "api"), ("notification_center", "notification"),
    ("casino_bonus_v2", "casino_bonus"), ("end_of_journey", "end"),
    ("wait_interval", "wait"), ("dextra_email", "email"),
    ("Promotion", "promotion"), ("scratch card", "scratch"),
    ("wait_for_deposit", "wait"),            # longest match wins, not first
    ("some_new_activity", "unknown"),        # never crashes on the unknown
]:
    got = R.family(wire)[0]
    check(f"{wire!r} -> {expected}", got == expected, f"got {got}")

# ── tolerant parsing ───────────────────────────────────────────────────────
REPLY = """Here is the outline.

━━ OBJECTS TO BUILD ━━
Journey 1: A — entry -> promotion -> spins

```json
{"diagram": {"campaign": "CI campaign", "brand": "JBCL", "journeys": [
   {"name": "A", "flags": "\\u26a0 empty prize added",
    "nodes": [{"type": "external_system_source"}, "promotion",
              {"type": "freespin_bonus", "label": "100 FS",
               "branches": {"Declined": [{"type": "end_of_journey"}]}}]},
   {"name": "B", "chain": "deposit -> freebet -> end_of_journey"}]},
 "randomizer": {"kind": "casino_wof", "date": "2026-08-01", "days": 7,
                "weights": [70, 30], "journeys": ["JRN-0-1", "JRN-0-2"]}}
```

Say which object(s) you want in full."""

try:
    diagram = R.normalise(R.extract_diagram(REPLY))
except Exception as exc:
    diagram = {}
    check("parses a fenced reply with prose", False, f"{type(exc).__name__}: {exc}")

journeys = diagram.get("journeys") or []
names = [j.get("name") for j in journeys]
check("both journeys parsed", names[:2] == ["A", "B"], f"got {names}")
check("sibling randomizer gets a board", any("Randomizer" in str(n) for n in names),
      f"got {names}")
check("bare-string node parsed", [n["type"] for n in journeys[0]["nodes"]][1] == "promotion",
      f"got {journeys[0]['nodes'] if journeys else None}")
check("arrow chain string parsed", len(journeys[1]["nodes"]) == 3,
      f"got {journeys[1]['nodes'] if len(journeys) > 1 else None}")
check("flags string became a list", journeys[0].get("flags") == ["⚠ empty prize added"],
      f"got {journeys[0].get('flags') if journeys else None}")
check("branch kept as a dict of lanes",
      list((journeys[0]["nodes"][2].get("branches") or {})) == ["Declined"],
      f"got {journeys[0]['nodes'][2] if journeys else None}")

# ── flag classification (drives the badge colour on the board) ─────────────
for text, kind in [("⚠ added an empty prize", "warn"), ("❓ assumed 20 CLP", "ask"),
                   ("⛔ UNCAPTURED — no node", "block"), ("just a note", "info")]:
    check(f"flag {kind}", R.flag_kind(text) == kind, f"got {R.flag_kind(text)}")

# ── it actually draws ──────────────────────────────────────────────────────
with tempfile.TemporaryDirectory() as tmp:
    out = Path(tmp)
    images = []
    for i, group in enumerate([journeys[:2], journeys[2:]], 1):
        if group:
            images.append(R.draw_board(dict(diagram, _number_from=1), group, i, 2,
                                       out / f"board_{i}.png", width=R.width_for(6)))
    check("boards written", len(images) == 2 and all((out / im["file"]).stat().st_size > 2000
                                                    for im in images),
          f"got {images}")
    check("board is cropped to its content",
          all(200 < im["h"] < 4000 for im in images), f"got {[im['h'] for im in images]}")

# ── a reply with no diagram refuses, and says so ───────────────────────────
try:
    R.extract_diagram("CAMPAIGN: x\n\nNo JSON here.")
    check("refuses a reply with no diagram", False, "accepted it")
except ValueError as exc:
    check("refuses a reply with no diagram", "no diagram" in str(exc), f"said {exc}")

# A spec reply (MODE 3/5) is not a diagram — it must not be drawn as one.
try:
    R.extract_diagram('```json\n{"recipe": "comms", "journey_name": "x", "knobs": {}}\n```')
    check("refuses a build spec", False, "accepted a MODE 3 spec as a diagram")
except ValueError:
    check("refuses a build spec", True)

print()
if FAILURES:
    print(f"FAILED ({len(FAILURES)}):")
    for failure in FAILURES:
        print(f"  - {failure}")
    sys.exit(1)
print("All journey-design renderer checks passed.")
