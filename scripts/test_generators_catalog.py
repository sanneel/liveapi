#!/usr/bin/env python3
"""Contract tests for what the AI planner knows about the generators.

The planner was grounded in recipes and games but knew nothing about the
twenty-odd finished generators, so a question about Welcome Pack or a tournament
left it two options: say nothing useful, or invent. generators_catalog.json is the
third grounded block, built from the code by
journey-cloner/build_generators_catalog.py.

A catalog like this is only worth having while it is TRUE, so:

  * it matches what the builder emits right now (the drift check — the same one
    recipes_catalog.json has, for the same reason)
  * every generator in the registry is in it, and nothing else is
  * every named script exists on disk
  * every `driven_from` tab is a real tab, and every `superseded_by` a real key
  * the required flags it advertises are flags argparse actually refuses without
  * the prompt really carries it, with the rule that these are routed to and
    never spec'd — a block present but unexplained is how "there is a script for
    that" gets said about a script that does not exist

No network, no model. Run: python scripts/test_generators_catalog.py
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "journey-cloner"))
sys.path.insert(0, str(REPO / "journey-planner"))

CATALOG = REPO / "journey-cloner" / "generators_catalog.json"
BUILDER = REPO / "journey-cloner" / "build_generators_catalog.py"
PY = REPO / ".venv" / "bin" / "python"
EXE = str(PY) if PY.exists() else sys.executable

FAILURES: list[str] = []


def check(label: str, condition: bool, detail: str = "") -> None:
    if condition:
        print(f"  [OK]   {label}")
    else:
        print(f"  [FAIL] {label}" + (f" — {detail}" if detail else ""))
        FAILURES.append(label if not detail else f"{label}: {detail}")



print("\nthe catalog is current")
check("generators_catalog.json exists", CATALOG.exists(),
      f"run: python {BUILDER.relative_to(REPO)}")
rc = subprocess.run([EXE, str(BUILDER), "--check"], capture_output=True, text=True,
                    cwd=REPO / "journey-cloner")
check("it matches what the builder emits now", rc.returncode == 0,
      rc.stdout.strip() or rc.stderr.strip()[-160:])

data = json.loads(CATALOG.read_text(encoding="utf-8"))
entries = data["generators"]
by_key = {g["key"]: g for g in entries}

print("\nit describes exactly the registry, no more and no less")
from app.services.promotions_catalog import GENERATORS  # noqa: E402
reg = {g["key"]: g for g in GENERATORS}
check("every registered generator is in the catalog",
      not (set(reg) - set(by_key)), str(sorted(set(reg) - set(by_key))))
check("the catalog invents none", not (set(by_key) - set(reg)),
      str(sorted(set(by_key) - set(reg))))
check("no duplicate keys", len(by_key) == len(entries))

print("\nevery fact in it is checkable")
missing = [g["key"] for g in entries
           if g.get("script") and not (REPO / "journey-cloner" / g["script"]).exists()]
check("every named script exists on disk", not missing, str(missing))
check("no entry is flagged as a missing script",
      not [g["key"] for g in entries if g.get("missing_script")],
      str([g["key"] for g in entries if g.get("missing_script")]))

from app.routes.admin_views import _PROMO_TABS  # noqa: E402
bad_tab = []
for g in entries:
    df = g.get("driven_from", "")
    if df.startswith("Optimization tab: "):
        tab = df.split(": ", 1)[1]
        if tab not in _PROMO_TABS:
            bad_tab.append((g["key"], tab))
check("every tab it points at is a real tab", not bad_tab, str(bad_tab))
bad_sup = [(g["key"], g["superseded_by"]) for g in entries
           if g.get("superseded_by") and g["superseded_by"] not in by_key]
check("every superseded_by names a generator in the catalog", not bad_sup, str(bad_sup))
check("the text comes from the registry, not a paraphrase",
      all(g["what"] == reg[g["key"]]["what"] for g in entries))

print("\nthe advertised required flags are really required")
# Spot-check by running each generator with NO arguments: anything it lists as
# required must make argparse refuse. Telling an operator a flag is needed when it
# is not (or missing one that is) is the failure this catches.
checked = 0
for g in entries:
    required = (g.get("cli") or {}).get("required") or []
    if not required or not g.get("script"):
        continue
    rc = subprocess.run([EXE, str(REPO / "journey-cloner" / g["script"])],
                        capture_output=True, text=True, timeout=60,
                        cwd=REPO / "journey-cloner")
    err = (rc.stderr or "") + (rc.stdout or "")
    named = [f for f in required if f in err]
    check(f"{g['key']}: refuses with no args and names a required flag",
          rc.returncode != 0 and bool(named),
          f"exit {rc.returncode}, required={required}, said: {err.strip()[-110:]}")
    checked += 1
check("at least a few generators were exercised this way", checked >= 3, str(checked))

print("\nthe planner actually receives it, with its rules")
import planner  # noqa: E402
prompt = planner.SYSTEM_PROMPT
check("the placeholder was substituted", "<GENERATORS_CATALOG>" not in prompt)
check("the catalog body is in the prompt", '"generators"' in prompt)
for key in sorted(reg):
    check(f"the prompt names {key}", key in prompt)
check("the prompt says never to spec a generator",
      "Never write a spec for one of these" in prompt)
check("the prompt says the list is complete",
      "a generator not here does not exist" in prompt.lower()
      or "complete list" in prompt)
check("the prompt keeps generators and recipes apart",
      "not composable" in prompt or "Keep the two" in prompt)
check("the rules travel with the data", "_rules" in prompt)

# The web AI page builds its own prompt, so wiring a block only into
# journey-planner/planner.py reaches the CLI and not the UI — which is exactly
# what happened: the page shipped a literal <GENERATORS_CATALOG> tag.
from app.routes.admin_planner import _build_system_prompt  # noqa: E402
for lean in (False, True):
    web = _build_system_prompt(lean=lean)
    check(f"the web page's prompt (lean={lean}) carries the catalog",
          '"generators"' in web and "welcome_pack" in web)
    check(f"the web page's prompt (lean={lean}) has no unfilled block",
          not re.findall(r"<([A-Z_]+)>\n</\1>", web),
          str(re.findall(r"<([A-Z_]+)>\n</\1>", web)))
from app.routes.admin_planner import _assert_no_unfilled_blocks  # noqa: E402
try:
    _assert_no_unfilled_blocks("intro\n<GAMES_REGISTRY>\n</GAMES_REGISTRY>\nrest")
    check("an unfilled block is a hard error, not an empty section", False,
          "it was accepted; a typo'd tag would tell the model there are no games")
except RuntimeError as exc:
    check("an unfilled block is a hard error, not an empty section",
          "GAMES_REGISTRY" in str(exc), str(exc)[:90])
check("a fully substituted prompt passes the same guard",
      _assert_no_unfilled_blocks("all filled in") is None)

print()
if FAILURES:
    print(f"FAILED ({len(FAILURES)}):")
    for f in FAILURES:
        print(f"  - {f}")
    sys.exit(1)
print("All generators-catalog checks passed.")
