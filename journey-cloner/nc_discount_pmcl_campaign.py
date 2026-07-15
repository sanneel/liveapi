#!/usr/bin/env python3
"""Build "NC For Discount" notification journeys for PMCL (fortunazo.cl).

Business flow: promote discounted games to active players via Notification
Center push, twice a week (Saturday 12:00 / Sunday 13:00 Chile time). Each
game/day is its own journey: segment (active players) -> notification
(template 16001) -> end. Four rotating message variants by calendar position
(Sat1, Sun1, Sat2, Sun2).

Before first run:
  1. Set PMCL_FOLDER_ID to your PMCL media-library folder UUID (find it in
     the backoffice URL when you open Media Library for the PMCL brand).

Usage:
  python nc_discount_pmcl_campaign.py                 # July calendar
  python nc_discount_pmcl_campaign.py --name nc_july  # custom output name
  python nc_discount_pmcl_campaign.py --dry-run       # write bodies to out/
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

from create_journeys import LOCAL_TZ, UTC, utc_api

HERE = Path(__file__).resolve().parent
TEMPLATE_PATH = HERE / "templates" / "casino" / "nc_discount_pmcl.json"
BASE_URL = "https://pmi.rea-backoffice.gr8.tech/api/ubo/api/v0/crm/journey-builder/v0"
BRAND = "PMCL"

# Media-library folder for PMCL image uploads. Find it in the backoffice URL
# when you open the Media Library for the PMCL brand, e.g.:
#   /media-library/folders/<this-uuid>
PMCL_FOLDER_ID = ""  # ← fill in before first run

# ── template literals from the captured body (nc_discount_pmcl.json) ────
# Replace stop BEFORE start in every s.replace() call — stop contains the
# same date prefix as start, so replacing start first would corrupt stop.
TPL_SLUG = "tada-jackpot-joker"
# link-en / link-es were never updated from the source JBCL template;
# they still carry a stale jugabet.cl/gamzix link. Replace the whole string.
TPL_STALE_LINK = (
    "https://jugabet.cl/services/slots/game/"
    "gamzix-coin-win-2-hold-the-spin?%$utm_tags%"
)
TPL_TITLE = "🔥 ¡[game name] está rompiendo récords! 🔥"
TPL_DES = "Cada vez más jugadores la eligen. ¿Ya la probaste?"
TPL_CAPTION = " ¡Juega ahora!"
TPL_ICON_SRC = (
    "https://static.contentin.cloud/"
    "73b22051-b16d-46e3-90cb-eeb045f59eea/"
    "4900707b-109a-4c20-85fc-012c09913c4b.jpg"
)
TPL_JOURNEY = "PMCL | CS | NC For Discount 18.07"
TPL_STARTAT = "2026-07-18T16:00:00Z"
TPL_STOPAT = "2026-07-18T17:00:00Z"
TPL_RESERVED = "JRN-0-617221"

ICON_TOKEN = "%%ICON%%"
RESERVED_TOKEN = "%%RESERVED%%"

# ── per-day copy variants (indexed by calendar position 0-3) ────────────
DAY_COPY = [
    # 0 — first Saturday, 12:00
    {
        "title": "🔥 ¡{name} está rompiendo récords! 🔥",
        "des": "Cada vez más jugadores la eligen. ¿Ya la probaste?",
        "caption": "¡Juega ahora!",
        "time": (12, 0),
    },
    # 1 — first Sunday, 13:00
    {
        "title": "🔥 ¡{name} no para de sumar jugadores! 🔥",
        "des": "Una de las favoritas del momento.",
        "caption": "¡A jugar!",
        "time": (13, 0),
    },
    # 2 — second Saturday, 12:00
    {
        "title": "⭐ Los jugadores eligieron {name} como su favorita. ⭐",
        "des": "¿Te unes a la diversión?",
        "caption": "¡A jugar!",
        "time": (12, 0),
    },
    # 3 — second Sunday, 13:00
    {
        "title": "🔥 Todos están jugando {name}. 🔥",
        "des": "No te quedes fuera de la acción.",
        "caption": "¡Juega ahora!",
        "time": (13, 0),
    },
]

# ── games calendar (date, url-slug, display name) ────────────────────────
CALENDAR = [
    ("2026-07-18", "tada-jackpot-joker",      "Jackpot Joker"),       # Sat — Day 1
    ("2026-07-19", "tada-3-coin-golden-ox",    "3 Coin Golden Ox"),    # Sun — Day 2
    ("2026-07-25", "tada-fortune-garuda-500",  "Fortune Garuda 500"),  # Sat — Day 3
    ("2026-07-26", "tada-fortune-gems-500",    "Fortune Gems 500"),    # Sun — Day 4
]


def game_url(slug: str) -> str:
    return f"https://fortunazo.cl/services/slots/game/{slug}"


def _window(day: datetime, hh: int, mm: int) -> tuple[str, str, datetime, datetime]:
    """1-hour journey window. Returns plain-UTC strings (for infoValues via
    string replacement) and the UTC datetimes (for dotnet-format top-level
    startAt/stopAt set explicitly after parsing)."""
    local = day.replace(hour=hh, minute=mm, second=0, microsecond=0, tzinfo=LOCAL_TZ)
    start = local.astimezone(UTC)
    stop = (local + timedelta(hours=1)).astimezone(UTC)
    fmt = "%Y-%m-%dT%H:%M:%SZ"
    return start.strftime(fmt), stop.strftime(fmt), start, stop


def prepare_game(date_str: str, slug: str, name: str, day_index: int) -> tuple[dict, list[str]]:
    day = datetime.strptime(date_str, "%Y-%m-%d")
    cp = DAY_COPY[day_index]
    title = cp["title"].format(name=name)
    des = cp["des"]
    caption = cp["caption"]
    hh, mm = cp["time"]
    start_at, stop_at, start_dt, stop_dt = _window(day, hh, mm)
    journey_name = f"PMCL | CS | NC For Discount {day:%d.%m}"

    s = TEMPLATE_PATH.read_text(encoding="utf-8")
    s = s.replace(TPL_JOURNEY, journey_name)
    # Stale full JBCL link (link-en / link-es) → fortunazo.cl game URL
    s = s.replace(TPL_STALE_LINK, f"{game_url(slug)}?%$utm_tags%")
    # Common link/deeplink slug → new slug (also hits the relative paths)
    s = s.replace(TPL_SLUG, slug)
    s = s.replace(TPL_TITLE, title)
    s = s.replace(TPL_DES, des)
    s = s.replace(TPL_CAPTION, " " + caption)  # keep the leading-space style
    s = s.replace(TPL_ICON_SRC, ICON_TOKEN)
    s = s.replace(TPL_STOPAT, stop_at)         # stop before start (date prefix overlap)
    s = s.replace(TPL_STARTAT, start_at)
    s = s.replace(TPL_RESERVED, RESERVED_TOKEN)

    body = json.loads(s)
    body["duplicatedFromId"] = None
    body["duplicatedFromVersion"] = None
    # Top-level schedule must be .NET fractional format; infoValues was already
    # updated by the string replacements above.
    body["startAt"] = utc_api(start_dt, dotnet_fraction=True)
    body["stopAt"] = utc_api(stop_dt, dotnet_fraction=True)
    body["isImmediatelyAfterPublish"] = False
    body["timeZoneId"] = "Chile/Continental"

    report = [
        f"{day:%a %d.%m} {hh:02d}:{mm:02d} Chile -> startAt {start_at}",
        f"journeyName = {journey_name!r}",
        f"title = {title!r}",
        f"link = {game_url(slug)}",
    ]
    return body, report


def verify(body: dict, slug: str) -> list[tuple[bool, str]]:
    s = json.dumps(body, ensure_ascii=False)
    iv = body.get("rawJourneyData", {}).get("infoValues", {})
    start = iv.get("startAt", "")
    stop = iv.get("stopAt", "")
    top_start = body.get("startAt", "")
    top_stop = body.get("stopAt", "")
    # Literals that must be gone regardless of which game is being processed
    # (don't include the template date since the first game shares it).
    stale = [lit for lit in (
        TPL_TITLE, TPL_ICON_SRC, TPL_RESERVED,
        "jugabet.cl", "gamzix-coin-win",
        "[game name]",
    ) if lit in s]
    return [
        (RESERVED_TOKEN in s,
         "reservedJourneyId placeholder present (filled at paste)"),
        (ICON_TOKEN in s,
         "icon-src placeholder present (uploaded at paste)"),
        (f"/services/slots/game/{slug}" in s,
         f"new slug {slug!r} in link/deeplink"),
        (f"fortunazo.cl/services/slots/game/{slug}" in s,
         f"fortunazo.cl link-en/link-es updated to {slug!r}"),
        ("jugabet.cl" not in s,
         "no stale jugabet.cl links"),
        ("gamzix-coin-win" not in s,
         "no stale JBCL slug"),
        (body.get("duplicatedFromId") is None,
         "no stale duplicatedFromId"),
        (bool(start and stop and start < stop),
         f"infoValues startAt {start} < stopAt {stop}"),
        (bool(top_start and "." in top_start),
         f"top-level startAt in dotnet format ({top_start[:30]}...)"),
        (not stale,
         "no leftover template literals"
         + (f" (LEAK: {stale})" if stale else "")),
    ]


JS_TEMPLATE = r"""// NC For Discount — PMCL — @COUNT@ notification journeys — generated @GENERATED_AT@
// One journey per game/day (segment -> notification -> end). For each game:
//   1. reserves a JRN-* id
//   2. pops a file picker for that game's image (200x200 px recommended)
//   3. uploads the image to the PMCL media library
//   4. creates + saves the draft (POST /journey-drafts + PUT /journey-drafts/<id>)
// Drafts are left unpublished for review. One failure doesn't stop the rest.
(async () => {
  'use strict';
  const MANUAL_TOKEN = '';
  const BASE = @BASE_URL@;
  const BRAND = @BRAND@;
  const FOLDER_ID = @FOLDER_ID@;
  const GAMES = @GAMES@;   // [{date, name, slug, body}]
  const CRM_BASE = BASE.replace(/\/journey-builder\/v0$/, '');

  const decodeJwt = (t) => { try { return JSON.parse(atob(t.split('.')[1].replace(/-/g,'+').replace(/_/g,'/'))); } catch (e) { return null; } };
  const usableAuth = (v) => {
    if (!v || !/^Bearer\s+\S+/i.test(v)) return null;
    const p = decodeJwt(v.replace(/^Bearer\s+/i, ''));
    if (!p || p.typ !== 'Bearer' || p.exp - Date.now()/1000 < 30) return null;
    return 'Bearer ' + v.replace(/^Bearer\s+/i, '');
  };
  async function obtainAuth() {
    if (MANUAL_TOKEN.trim()) { const a = usableAuth('Bearer ' + MANUAL_TOKEN.trim()); if (!a) throw new Error('MANUAL_TOKEN invalid'); return a; }
    return new Promise((resolve, reject) => {
      let done = false; const of = window.fetch, oh = XMLHttpRequest.prototype.setRequestHeader;
      const clean = () => { window.fetch = of; XMLHttpRequest.prototype.setRequestHeader = oh; };
      const take = (v) => { const a = usableAuth(v); if (a && !done) { done = true; clean(); clearTimeout(t); console.log('%cToken captured.', 'color:#22c55e'); resolve(a); } };
      window.fetch = function (i, n) { try { const h = (n && n.headers) || (i && i.headers); if (h) { if (typeof h.get === 'function') take(h.get('authorization')); else take(h.authorization || h.Authorization); } } catch (e) {} return of.apply(this, arguments); };
      XMLHttpRequest.prototype.setRequestHeader = function (k, v) { try { if (/^authorization$/i.test(k)) take(v); } catch (e) {} return oh.apply(this, arguments); };
      const t = setTimeout(() => { if (!done) { done = true; clean(); reject(new Error('No token in 3 min. Click around the UI and rerun.')); } }, 180000);
      console.log('%cWaiting for a token — click anything in the backoffice UI.', 'color:#eab308');
    });
  }

  function pickFile(label) {
    return new Promise((resolve, reject) => {
      const input = document.createElement('input');
      input.type = 'file'; input.accept = 'image/*';
      Object.assign(input.style, { position: 'fixed', top: '12px', left: '12px', zIndex: 999999, background: '#fff', padding: '8px', border: '3px solid #22c55e', borderRadius: '6px' });
      document.body.appendChild(input);
      console.log('%cSelect the image for ' + label + ' (top-left of the page).', 'color:#eab308;font-weight:bold');
      input.addEventListener('change', () => { const f = input.files && input.files[0]; input.remove(); if (!f) { reject(new Error('No file selected for ' + label)); return; } resolve(f); });
    });
  }
  function imageDims(file) {
    return new Promise((resolve, reject) => {
      const url = URL.createObjectURL(file); const img = new Image();
      img.onload = () => { URL.revokeObjectURL(url); resolve({ width: img.naturalWidth, height: img.naturalHeight }); };
      img.onerror = () => { URL.revokeObjectURL(url); reject(new Error('Could not read dimensions for ' + file.name)); };
      img.src = url;
    });
  }

  // All journeys clone the same template, so their activity UUIDs collide.
  // Regenerate every activityId/id UUID before each create (global string
  // replace keeps handles, ports, edges and rawJourneyData keys in sync).
  const newUuid = () => (typeof crypto !== 'undefined' && crypto.randomUUID) ? crypto.randomUUID()
    : 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, (c) => { const r = Math.random()*16|0; return (c === 'x' ? r : (r&0x3)|0x8).toString(16); });
  const UUID_RE = /"(?:activityId|id)"\s*:\s*"([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})"/g;
  function regenIds(txt) {
    const old = new Set(); let m; UUID_RE.lastIndex = 0;
    while ((m = UUID_RE.exec(txt)) !== null) old.add(m[1]);
    let t = txt;
    for (const o of old) t = t.split(o).join(newUuid());
    return t;
  }

  const auth = await obtainAuth();
  const H = (ct) => { const h = { accept: 'application/json, text/plain, */*', authorization: auth, 'x-brand': BRAND }; if (ct) h['content-type'] = ct; return h; };

  async function reserveId() {
    const r = await fetch(BASE + '/journeys/identifier', { method: 'POST', headers: H('application/json'), credentials: 'include', body: '' });
    const t = await r.text(); if (!r.ok) throw new Error('reserve id failed HTTP ' + r.status + ' ' + t);
    const id = JSON.parse(t).journeyId; if (!id) throw new Error('no journeyId in reserve response: ' + t); return id;
  }
  async function uploadIcon(file, label) {
    const dims = await imageDims(file);
    const base = (file.name || 'icon').replace(/\.[^./]+$/, '');
    const url = CRM_BASE + '/media-library/v0/folder/' + FOLDER_ID + '/upload/' + encodeURIComponent(base) + '.png?height=' + dims.height + '&width=' + dims.width;
    const fd = new FormData(); fd.append('file', file, file.name);
    const r = await fetch(url, { method: 'PUT', headers: H(), credentials: 'include', body: fd });
    const t = await r.text(); if (!r.ok) throw new Error(label + ' icon upload failed HTTP ' + r.status + ' ' + t);
    const asset = JSON.parse(t);
    const tfd = new FormData(); tfd.append('file', file, file.name);
    await fetch(CRM_BASE + '/media-library/v0/asset/thumb/' + asset.id + '.png', { method: 'PUT', headers: H(), credentials: 'include', body: tfd }).catch(() => {});
    return asset.absolute_link;
  }
  async function createOne(G) {
    const jid = await reserveId();
    console.log('    reserved ' + jid);
    const iconFile = await pickFile(G.name + ' (' + G.date + ')');
    const iconUrl = await uploadIcon(iconFile, G.name);
    console.log('    icon uploaded -> ' + iconUrl);
    let bodyStr = G.body.split('%%RESERVED%%').join(jid).split('%%ICON%%').join(iconUrl);
    bodyStr = regenIds(bodyStr);
    const body = JSON.parse(bodyStr);
    let r = await fetch(BASE + '/journey-drafts', { method: 'POST', headers: H('application/json'), credentials: 'include', body: JSON.stringify(body) });
    let t = await r.text(); if (!r.ok) throw new Error('create HTTP ' + r.status + ' ' + t);
    const numId = JSON.parse(t).id; if (!numId) throw new Error('no draft id in create response: ' + t);
    r = await fetch(BASE + '/journey-drafts/' + numId, { method: 'PUT', headers: H('application/json'), credentials: 'include', body: JSON.stringify(body) });
    t = await r.text(); if (!r.ok) throw new Error('draft ' + jid + ' created but save failed HTTP ' + r.status + ' ' + t);
    return { jid, numId };
  }

  console.log('Creating ' + GAMES.length + ' PMCL notification journey(s)...');
  const ok = [], fail = [];
  for (const G of GAMES) {
    console.log('%c' + G.date + '  ' + G.name + ' ...', 'color:#3b82f6;font-weight:bold');
    try { const res = await createOne(G); ok.push({ name: G.name, jid: res.jid }); console.log('%c    ✓ ' + res.jid, 'color:#22c55e'); }
    catch (e) { const msg = String((e && e.message) || e); fail.push({ name: G.name, err: msg }); console.error('    ✗ ' + G.name + ' — ' + msg); }
  }
  console.log('%cDONE — ' + ok.length + ' created, ' + fail.length + ' failed.', 'color:' + (fail.length ? '#f59e0b' : '#22c55e') + ';font-weight:bold;font-size:14px');
  ok.forEach((o) => console.log('  ✓ ' + o.jid + '  (' + o.name + ')'));
  fail.forEach((f) => console.log('  ✗ ' + f.name + ' — ' + f.err));
  console.log('Drafts are unpublished — review + publish them in the Journeys UI.');
})();
"""


def build_js(games: list[dict]) -> str:
    if not PMCL_FOLDER_ID:
        raise SystemExit(
            "PMCL_FOLDER_ID is not set. Open Media Library in the PMCL backoffice, "
            "copy the folder UUID from the URL, and paste it into PMCL_FOLDER_ID "
            "at the top of this script."
        )
    payload = [
        {"date": g["date"], "name": g["name"], "slug": g["slug"],
         "body": json.dumps(g["body"], ensure_ascii=False)}
        for g in games
    ]
    js = JS_TEMPLATE
    js = js.replace("@COUNT@", str(len(games)))
    js = js.replace("@GENERATED_AT@", datetime.now(LOCAL_TZ).strftime("%Y-%m-%d %H:%M %Z"))
    js = js.replace("@BASE_URL@", json.dumps(BASE_URL))
    js = js.replace("@BRAND@", json.dumps(BRAND))
    js = js.replace("@FOLDER_ID@", json.dumps(PMCL_FOLDER_ID))
    js = js.replace("@GAMES@", json.dumps(payload, ensure_ascii=False))
    return js


def main() -> int:
    p = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("--name", default="nc_discount_pmcl",
                   help="output basename (default: nc_discount_pmcl)")
    p.add_argument("--dry-run", action="store_true",
                   help="write prepared bodies to out/ instead of a console script")
    args = p.parse_args()

    games: list[dict] = []
    all_ok = True
    print(f"NC For Discount PMCL — {len(CALENDAR)} game(s):")
    for idx, (date_str, slug, name) in enumerate(CALENDAR):
        body, report = prepare_game(date_str, slug, name, idx)
        games.append({"date": date_str, "slug": slug, "name": name, "body": body})
        print(f"  • [{idx + 1}] {name}  ({date_str})")
        for line in report:
            print("        " + line)
        for ok, msg in verify(body, slug):
            if not ok:
                print(f"        FAIL  {msg}")
            all_ok = all_ok and ok

    if not all_ok:
        print("\nVERIFICATION FAILED — not writing output.", file=sys.stderr)
        return 1

    if args.dry_run:
        out = Path("out")
        out.mkdir(exist_ok=True)
        path = out / f"{args.name}_journeys.json"
        path.write_text(
            json.dumps([g["body"] for g in games], ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"\nDry run — {len(games)} body(ies) written: {path}")
        return 0

    js = build_js(games)
    out = Path("console_scripts")
    out.mkdir(exist_ok=True)
    path = out / f"{args.name}_console.js"
    path.write_text(js, encoding="utf-8")
    print(f"\nConsole script written: {path}  ({len(games)} journeys in one paste)")
    print("Paste into DevTools console on a logged-in PMCL backoffice tab.")
    print("A file picker pops up per game — select that game's image.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
