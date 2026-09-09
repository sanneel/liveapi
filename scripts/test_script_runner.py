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

import hashlib
import json
import re
import sys
import zipfile
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

# ── distribution: wiring ───────────────────────────────────────────────────
print("\n── distribution wiring")

server = (REPO / "server.py").read_text(encoding="utf-8")
check("router imported in server.py", "script_runner import router" in server)
check("router registered in server.py", "include_router(script_runner_router)" in server)
# admin_views_router owns the broad /admin routes, so ours has to land first.
check("registered before admin_views_router",
      server.find("include_router(script_runner_router)")
      < server.find("include_router(admin_views_router)"))

base_html = (REPO / "app" / "templates" / "base.html").read_text(encoding="utf-8")
check("nav entry present", "/admin/tools/script-runner" in base_html)

routes = (REPO / "app" / "routes" / "script_runner.py").read_text(encoding="utf-8")
for path in ("/script-runner/update.xml", "/script-runner/runner.crx",
             "/script-runner/script-runner.zip", "/admin/tools/script-runner"):
    check(f"route {path} defined", f'"{path}"' in routes)
# Chrome cannot log in, so the file routes must not be behind require_role.
public_part = routes[:routes.index("/admin/tools/script-runner")]
check("the three file routes are unauthenticated (Chrome cannot log in)",
      "require_role" not in public_part)

gitignore = (REPO / ".gitignore").read_text(encoding="utf-8")
check("signing key is gitignored", "deploy/script-runner.pem" in gitignore)
check("build output is gitignored", "app/static/script-runner/" in gitignore)

# ── the install page template ──────────────────────────────────────────────
print("\n── install page template")

tpl_path = REPO / "app" / "templates" / "script_runner.html"
tpl = tpl_path.read_text(encoding="utf-8")

tags = re.findall(r"\{%-?\s*(\w+)", tpl)
PAIRS = {"block": "endblock", "if": "endif", "for": "endfor", "with": "endwith"}
stack: list[str] = []
tag_errors: list[str] = []
for tag in tags:
    if tag in PAIRS:
        stack.append(tag)
    elif tag.startswith("end"):
        if not stack:
            tag_errors.append(f"stray {tag}")
        elif PAIRS[stack[-1]] != tag:
            tag_errors.append(f"{tag} closes {stack[-1]}")
        else:
            stack.pop()
check("Jinja tags balanced", not tag_errors and not stack,
      "; ".join(tag_errors) or f"unclosed: {stack}")

# Every name the template reads must be in the view's context.
CONTEXT = {"request", "current_user", "active", "meta", "policy", "forcelist",
           "base", "crm_origin_pattern", "loader", "bookmarklet",
           "ttl_minutes", "max_reads"}
used = set(re.findall(r"\{\{\s*(\w+)", tpl))
check("template uses only names the view passes", used <= CONTEXT,
      f"missing from context: {sorted(used - CONTEXT)}")

# ── distribution: packed artifacts ─────────────────────────────────────────
print("\n── packed artifacts")

DIST = REPO / "app" / "static" / "script-runner"
runner_json = DIST / "runner.json"
if not runner_json.is_file():
    print("  (not packed in this checkout — run scripts/pack_script_runner.py)")
else:
    dist_meta = json.loads(runner_json.read_text(encoding="utf-8"))
    crx = (DIST / "runner.crx").read_bytes()

    check("CRX is CRX3", crx[:4] == b"Cr24" and
          int.from_bytes(crx[4:8], "little") == 3)

    # The id IT pins comes from runner.json. If it disagreed with the id Chrome
    # signed into the CRX, the policy would look right and never install
    # anything — so check them against each other, not against a constant.
    header_len = int.from_bytes(crx[8:12], "little")
    header = crx[12:12 + header_len]
    # CrxFileHeader field 10000 (signed_header_data), wire type 2.
    TAG = bytes([0x82, 0xF1, 0x04])

    def _varint(buf: bytes, i: int) -> tuple[int, int]:
        n = shift = 0
        while True:
            byte = buf[i]
            i += 1
            n |= (byte & 0x7F) << shift
            if not byte & 0x80:
                return n, i
            shift += 7

    try:
        i = header.index(TAG) + len(TAG)
        size, i = _varint(header, i)
        signed = header[i:i + size]
        # SignedData field 1 (crx_id), 16 bytes.
        assert signed[0] == 0x0A and signed[1] == 0x10
        embedded = signed[2:18].hex().translate(
            str.maketrans("0123456789abcdef", "abcdefghijklmnop"))
    except (ValueError, AssertionError, IndexError) as exc:
        embedded = f"unparseable ({exc})"
    check("runner.json id matches the id Chrome signed into the CRX",
          embedded == dist_meta.get("id"),
          f"crx={embedded} runner.json={dist_meta.get('id')}")

    check("crx_sha256 matches the served bytes",
          hashlib.sha256(crx).hexdigest() == dist_meta.get("crx_sha256"))

    update_xml = (DIST / "update.xml").read_text(encoding="utf-8")
    check("update.xml carries the extension id", dist_meta["id"] in update_xml)
    check("update.xml version matches the manifest",
          dist_meta["version"] == manifest.get("version"),
          f'{dist_meta["version"]} vs {manifest.get("version")}')
    # The route substitutes the real origin; a literal placeholder must survive
    # to the file, or every install would point at the wrong host.
    check("update.xml keeps the @BASE@ placeholder for the route to fill",
          "@BASE@" in update_xml)

    shipped = zipfile.ZipFile(DIST / "script-runner.zip").namelist()
    check("ZIP excludes tests/ and README",
          not any(n.startswith("tests") or n == "README.md" for n in shipped),
          ", ".join(n for n in shipped if n.startswith("tests"))[:60])
    check("ZIP contains the manifest", "manifest.json" in shipped)


# ── run codes ──────────────────────────────────────────────────────────────
# The job store is what makes the no-install route possible: the page hands the
# script back, the operator gets a code, and a fixed five-line loader fetches it.
# GET /run/<code> is PUBLIC by necessity, so the code IS the credential and its
# limits are security properties, not conveniences.
print("\n── run codes")

import importlib.util  # noqa: E402

_spec = importlib.util.spec_from_file_location(
    "run_jobs", REPO / "app" / "services" / "run_jobs.py")
run_jobs = importlib.util.module_from_spec(_spec)
sys.modules["run_jobs"] = _spec.loader and run_jobs
_spec.loader.exec_module(run_jobs)

SCRIPT = "(async () => { console.log(1); })();"

job = run_jobs.create("gow_console.js", SCRIPT, "sandro")
check("a code is minted", bool(job.code))
check("code is long enough to be unguessable",
      len(job.code) >= 10 and 31 ** len(job.code) > 10 ** 14,
      f"len={len(job.code)}, alphabet={len(run_jobs.ALPHABET)}")
check("code alphabet excludes look-alike characters",
      not (set("O0I1L") & set(run_jobs.ALPHABET)),
      "".join(sorted(set("O0I1L") & set(run_jobs.ALPHABET))))

check("exact code claims the script", (run_jobs.claim(job.code) or {}) and
      run_jobs.claim(job.code).text == SCRIPT)
# Codes get read off a screen and typed.
spaced = job.code[:5].lower() + "-" + job.code[5:].lower()
check("claim tolerates case and separators", run_jobs.claim(spaced) is not None, spaced)

check("unknown code returns nothing", run_jobs.claim("ZZZZZZZZZZ") is None)
check("empty code returns nothing", run_jobs.claim("") is None and run_jobs.claim(None) is None)

# Reads are capped so a leaked code is not a standing grant.
spent = run_jobs.create("n.js", SCRIPT, "u")
for _ in range(run_jobs.MAX_READS):
    run_jobs.claim(spent.code)
check(f"code dies after MAX_READS ({run_jobs.MAX_READS}) reads",
      run_jobs.claim(spent.code) is None)

for bad, label in [("an empty", ""), ("a whitespace-only", "   "), ("a None", None)]:
    try:
        run_jobs.create("n.js", label, "u")
        check(f"refuses {bad} script", False, "accepted it")
    except (ValueError, TypeError, AttributeError):
        check(f"refuses {bad} script", True)
try:
    run_jobs.create("n.js", "x" * (run_jobs.MAX_SCRIPT_BYTES + 1), "u")
    check("refuses an oversize script", False, "accepted it")
except ValueError:
    check("refuses an oversize script", True)

# A runaway page must not be able to pin hundreds of 650 KB scripts in memory.
for i in range(run_jobs.MAX_JOBS + 10):
    run_jobs.create(f"j{i}.js", SCRIPT, "u")
check("outstanding jobs are capped",
      run_jobs.stats()["outstanding"] <= run_jobs.MAX_JOBS, str(run_jobs.stats()))

run_jobs.TTL_SECONDS = 0
stale = run_jobs.create("t.js", SCRIPT, "u")
check("code expires by TTL", run_jobs.claim(stale.code) is None)

# ── CORS on the public handover ────────────────────────────────────────────
print("\n── CORS on /run/{code}")

routes_src = (REPO / "app" / "routes" / "script_runner.py").read_text(encoding="utf-8")
check("never sends a wildcard origin", '"Access-Control-Allow-Origin": "*"' not in routes_src)
check("allows only the backoffice origin",
      'ALLOWED_ORIGIN_SUFFIX = ".rea-backoffice.gr8.tech"' in routes_src)
check("varies on Origin", '"Vary": "Origin"' in routes_src)
check("both public endpoints are rate limited",
      routes_src.count("@limiter.limit") >= 2,
      f'{routes_src.count("@limiter.limit")} limited')
# A guesser must not be able to tell a spent code from a nonexistent one.
check("missing and expired codes are indistinguishable",
      "Deliberately identical" in routes_src)

print()
if FAILURES:
    print(f"FAILED ({len(FAILURES)}):")
    for f in FAILURES:
        print(f"  - {f}")
    sys.exit(1)
print("All Script Runner contract checks passed.")
