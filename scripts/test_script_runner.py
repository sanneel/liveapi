#!/usr/bin/env python3
"""Contract tests for the Script Runner extension (extension/).

The extension replaces "copy the script, F12, paste" with one button. It only
gets to do that by making one edit to a generated script — swapping the
MANUAL_TOKEN line for a token it read off the backoffice's own traffic — and that
edit is a contract spanning two languages:

  * Python writes  `const MANUAL_TOKEN = '';`  into every emitted console script.
  * extension/config.js declares that exact string and splits on it.

If a generator ever reformats that line, the split silently finds nothing, the
extension skips seeding, and the operator is back to "Waiting for a token…" with
no explanation. So the string is asserted identical on both sides, and asserted
to appear exactly once per generator — twice would make seeding ambiguous, and
the extension refuses rather than guessing.

Also checks the manifest is coherent: valid JSON, the permissions the runner
actually uses, and every file it names present on disk.

The JS behaviour tests are browser pages (there is no JS runtime on the deploy
box) — see extension/tests/serve.py.

No network, no key, fast. Run: python scripts/test_script_runner.py
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
EXT = REPO / "extension"
CLONER = REPO / "journey-cloner"

FAILURES: list[str] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    if ok:
        print(f"  [OK]   {label}")
    else:
        FAILURES.append(f"{label}: {detail}")
        print(f"  [FAIL] {label} — {detail}")


# ── the manifest ───────────────────────────────────────────────────────────
print("── manifest")

manifest_path = EXT / "manifest.json"
manifest: dict = {}
try:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    check("manifest.json parses", True)
except Exception as exc:  # noqa: BLE001
    check("manifest.json parses", False, str(exc))

check("manifest v3", manifest.get("manifest_version") == 3,
      str(manifest.get("manifest_version")))

# Each of these is load-bearing, and a missing one fails at the worst moment
# (mid-run, on someone else's machine) rather than at install.
NEEDED_PERMISSIONS = {
    "debugger": "runs the script in the page, the way the console does",
    "webRequest": "reads the bearer token off backoffice traffic",
    "storage": "holds the queue across service-worker restarts",
    "tabs": "finds the logged-in backoffice tab",
    "scripting": "registers the CRM content script for granted origins",
}
have = set(manifest.get("permissions") or [])
for perm, why in NEEDED_PERMISSIONS.items():
    check(f"permission {perm!r} declared ({why})", perm in have)

hosts = manifest.get("host_permissions") or []
check("backoffice host permission declared",
      any("rea-backoffice.gr8.tech" in h for h in hosts), str(hosts))
check("CRM origins are optional, not baked in",
      bool(manifest.get("optional_host_permissions")),
      "the CRM hostname is deployment-specific (DEPLOY.md)")

# Files the manifest names, plus the ones registerContentScripts injects.
referenced = [
    (manifest.get("background") or {}).get("service_worker"),
    (manifest.get("action") or {}).get("default_popup"),
    manifest.get("options_page"),
    "content.js",
    "content.css",
]
for rel in referenced:
    if not rel:
        continue
    check(f"{rel} exists", (EXT / rel).is_file())

# ── the MANUAL_TOKEN contract ──────────────────────────────────────────────
print("\n── MANUAL_TOKEN contract (Python emits it, config.js splits on it)")

config_js = (EXT / "config.js").read_text(encoding="utf-8")
m = re.search(r"MANUAL_TOKEN_LINE\s*=\s*(['\"])(.*?)\1", config_js)
js_line = m.group(2) if m else None
check("config.js declares MANUAL_TOKEN_LINE", bool(js_line), "not found")

# Every generator that emits a console script embeds this line in its JS
# template. Discovered by grep, not listed, so a new generator is covered.
generators = sorted(
    p for p in CLONER.glob("*.py")
    if "MANUAL_TOKEN" in p.read_text(encoding="utf-8")
)
check("found generators that emit a MANUAL_TOKEN knob", len(generators) > 0,
      f"{len(generators)} files")

for path in generators:
    text = path.read_text(encoding="utf-8")
    # The generators are Python holding a JS template, so the line appears
    # verbatim in the source. A generator may hold more than one template
    # (compose.py has a single-journey and a batch one), so the per-template
    # "exactly once" property is checked in extension/tests/generator.test.html;
    # here we only assert the string is the one config.js splits on.
    count = text.count(js_line) if js_line else 0
    check(f"{path.name}: emits the exact line config.js expects", count >= 1,
          f"found {count} occurrence(s) of {js_line!r}")

# ── emitted scripts, if any have been generated here ───────────────────────
print("\n── emitted console scripts")

emitted = sorted((CLONER / "console_scripts").glob("*.js"))
if not emitted:
    print("  (none generated in this checkout — skipped)")
else:
    bad_count = [p.name for p in emitted
                 if p.read_text(encoding="utf-8").count(js_line) > 1]
    check("no emitted script carries the line twice", not bad_count,
          ", ".join(bad_count[:3]))

    with_line = [p for p in emitted
                 if p.read_text(encoding="utf-8").count(js_line) == 1]
    check("most emitted scripts expose the knob",
          len(with_line) / len(emitted) > 0.5,
          f"{len(with_line)}/{len(emitted)}")

    # The token is only useful if the script's BASE is the host the extension
    # holds a permission for.
    off_host = [
        p.name for p in emitted
        if "rea-backoffice.gr8.tech" not in p.read_text(encoding="utf-8")
    ]
    check("every emitted script targets the permitted backoffice host",
          not off_host, ", ".join(off_host[:3]))

print()
if FAILURES:
    print(f"FAILED ({len(FAILURES)}):")
    for f in FAILURES:
        print(f"  - {f}")
    sys.exit(1)
print("All Script Runner contract checks passed.")
