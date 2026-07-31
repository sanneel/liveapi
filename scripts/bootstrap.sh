#!/usr/bin/env bash
# Bring a fresh clone to the state CLAUDE.md assumes: a .venv with every
# dependency installed, so the offline test suite reports code problems rather
# than environment ones.
#
# This exists because the failure mode without it is misleading, not obvious. On
# a clone with no .venv, running the tests under the system interpreter gives:
#
#   test_composer_contract.py  FAILED - recipes_catalog.json ... stale
#   test_journey_design.py     pillow is required: pip install pillow
#
# Both read as regressions in the code. Neither is. The first is worse than it
# looks: the catalog builder imports randomizer_campaign to publish the wheel
# palette, python-dotenv is missing so the import fails, and the "stale" verdict
# is really "this environment cannot see the randomizers". Following the test's
# own advice (`compose.py --catalog`) used to then commit a truncated catalog.
# The builder now refuses instead, but the cure is still to fix the environment.
#
# Usage:  ./scripts/bootstrap.sh          # create/refresh .venv, then verify
#         ./scripts/bootstrap.sh --check  # verify only, no install
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV="$REPO/.venv"
PY="$VENV/bin/python"
cd "$REPO"

if [[ "${1:-}" != "--check" ]]; then
  if [[ ! -x "$PY" ]]; then
    echo "==> creating .venv"
    python3 -m venv "$VENV"
  fi
  echo "==> installing dependencies"
  "$PY" -m pip install --quiet --upgrade pip
  # Both files, deliberately: journey-cloner pins the generators' own deps and
  # must agree with the root pins. A conflict here is a bug worth seeing.
  "$PY" -m pip install --quiet -r requirements.txt -r journey-cloner/requirements.txt
fi

if [[ ! -x "$PY" ]]; then
  echo "no .venv at $VENV — run without --check first" >&2
  exit 1
fi

echo "==> verifying"
fail=0

# The imports whose absence produces a misleading test failure.
"$PY" - <<'PY' || fail=1
import importlib.util, sys
missing = [m for m in ("dotenv", "PIL", "fastapi", "jinja2", "requests")
           if not importlib.util.find_spec(m)]
if missing:
    print("  missing: " + ", ".join(missing))
    sys.exit(1)
print("  imports            ok")
PY

# The randomizer palette is the canary: it is the thing that silently empties.
"$PY" - <<'PY' || fail=1
import json, pathlib, sys
kinds = (json.loads(pathlib.Path("journey-cloner/recipes_catalog.json")
         .read_text(encoding="utf-8")).get("randomizer") or {}).get("kinds") or {}
if not kinds:
    print("  randomizer palette EMPTY — catalog was written by a broken env")
    sys.exit(1)
print(f"  randomizer palette ok ({', '.join(kinds)})")
PY

echo "==> offline test suite"
for t in test_composer_contract test_journey_design test_har_analyse; do
  if "$PY" "scripts/$t.py" >/dev/null 2>&1; then
    printf '  %-26s PASS\n' "$t"
  else
    printf '  %-26s FAIL\n' "$t"; fail=1
  fi
done

if [[ "$fail" -ne 0 ]]; then
  echo
  echo "Something above failed. Re-run without --check to reinstall, and only" >&2
  echo "then treat a failure as a real regression." >&2
  exit 1
fi

echo
echo "Ready. Use $PY (not bare python) — see CLAUDE.md."
