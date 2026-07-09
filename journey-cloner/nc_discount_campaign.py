#!/usr/bin/env python3
"""Build the "NC For Discount" notification journeys — one per game/day.

Business flow (from the brief): promote discounted games to active players via a
Notification Center push, twice a week (Mon 20:00 / Fri 21:00 Chile). Each day
is its own journey: segment (active players) -> notification (template 1935) ->
end. The notification carries the game image, a Spanish message, a CTA button
and a deep link to the game.

This clones the captured journey (templates/casino/nc_discount.json) once per
game, swapping — by string replacement so the editor mirror (rawJourneyData) and
the compiled activities stay identical:

  * the game slug in the launch link/deeplink,
  * the title (game name), description and CTA caption (Mon vs Fri wording),
  * the journeyName and the send time (startAt, Chile-local -> UTC),
  * the notification icon (uploaded per game at paste time).

The generated console script, for EACH game: reserves a journey id, uploads the
game image (a file picker pops up, labelled with the game), then creates the
draft (POST /journey-drafts) and saves it (PUT /journey-drafts/<id>). Drafts are
left unpublished for review. Heavy logging; one bad game doesn't stop the rest.

Usage:
  python nc_discount_campaign.py                 # the July calendar from the brief
  python nc_discount_campaign.py --name nc_july  # custom output basename
  python nc_discount_campaign.py --dry-run       # write the prepared bodies to out/
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

from create_journeys import BRAND, LOCAL_TZ, UTC
from casino_journey import DEFAULT_BASE_URL
from comms_campaign import DEFAULT_FOLDER_ID

HERE = Path(__file__).resolve().parent
TEMPLATE_PATH = HERE / "templates" / "casino" / "nc_discount.json"

# ── literals in the captured template we swap per game ──────────────────
TPL_SLUG = "gamzix-coin-win-2-hold-the-spin"
# The captured template links to the game via the in-app deeplink path
# (/launch/slots/iframe/<slug>). The notification must point at the public
# game page instead, so we swap the whole path — not just the slug — in every
# link field (link-en, link-es, deeplink). The %$utm_tags% suffix is kept.
TPL_LINK = f"/launch/slots/iframe/{TPL_SLUG}"


def game_url(slug: str) -> str:
    """Public game-page URL used in the notification links."""
    return f"https://jugabet.cl/services/slots/game/{slug}"
TPL_TITLE = "🔥El más jugado del día - Coin Win 2: Hold The Spin"
TPL_DES = "No te lo pierdas. Sumérgete en la diversión."
TPL_CAPTION = " ¡A jugar!"
TPL_ICON = "https://static.contentin.cloud/c93ad623-44ae-40f6-9aa5-b1aef7fd931a/2db55af6-381a-417c-b8ad-bbe307e6875b.png"
TPL_JOURNEY = "JBCL | CS | NC For Discount 29.06"
TPL_COPY_JOURNEY = "Copy of " + TPL_JOURNEY
TPL_STARTAT = "2026-06-30T00:00:00Z"
TPL_STOPAT = "2026-06-30T01:00:00Z"   # journey window end (start + 1h)
TPL_RESERVED = "JRN-0-609352"

ICON_TOKEN = "%%ICON%%"
RESERVED_TOKEN = "%%RESERVED%%"

# ── per-weekday copy (Monday vs Friday), from the brief ─────────────────
MON = {
    "title": "🔥 El favorito del día: {name} 🔥",
    "des": "Miles ya lo están jugando. ¿Y tú?",
    "caption": "¡A jugar!",
    "time": (20, 0),   # 20:00 Chile
}
FRI = {
    "title": "🔥 El más jugado de hoy: {name} 🔥",
    "des": "El favorito de miles de jugadores.",
    "caption": "¡Juega ahora!",
    "time": (21, 0),   # 21:00 Chile
}

# ── the July "games on discount" calendar (date, url-slug, display name) ─
CALENDAR = [
    ("2026-07-10", "playtech-the-racaroon",              "The Racaroon"),
    ("2026-07-13", "playtech-gold-trio-tres-amigos",     "Gold Trio"),
    ("2026-07-17", "playson-tornado-power-hold-and-win", "Tornado"),
    ("2026-07-20", "amigo-1000-olympus-rivals",          "1000 Olympus Rivals"),
    ("2026-07-24", "pragmatic-sweet-bonanza-1000",       "Sweet Bonanza 1000"),
    ("2026-07-27", "3oaks-egypt-fire",                   "Egypt Fire"),
    ("2026-07-31", "gamzix-coin-win-2-hold-the-spin",    "Coin Win 2: Hold The Spin"),
]


def _copy_for(day: datetime) -> dict:
    wd = day.weekday()
    if wd == 0:
        return MON
    if wd == 4:
        return FRI
    raise SystemExit(f"{day:%Y-%m-%d} is a {day:%A} — the brief only covers Monday/Friday.")


def _window(day: datetime, hh: int, mm: int) -> tuple[str, str]:
    """(startAt, stopAt) in UTC. The journey window is 1h, as in the template."""
    local = day.replace(hour=hh, minute=mm, second=0, microsecond=0, tzinfo=LOCAL_TZ)
    start = local.astimezone(UTC)
    stop = (local + timedelta(hours=1)).astimezone(UTC)
    fmt = "%Y-%m-%dT%H:%M:%SZ"
    return start.strftime(fmt), stop.strftime(fmt)


def prepare_game(date_str: str, slug: str, name: str) -> tuple[dict, list[str]]:
    day = datetime.strptime(date_str, "%Y-%m-%d")
    cp = _copy_for(day)
    title = cp["title"].format(name=name)
    des = cp["des"]
    caption = cp["caption"]
    hh, mm = cp["time"]
    start_at, stop_at = _window(day, hh, mm)
    journey_name = f"JBCL | CS | NC For Discount {day:%d.%m}"

    s = TEMPLATE_PATH.read_text(encoding="utf-8")
    s = s.replace(TPL_COPY_JOURNEY, journey_name)   # top-level name (had "Copy of")
    s = s.replace(TPL_JOURNEY, journey_name)        # metadata copies
    s = s.replace(TPL_LINK, game_url(slug))         # deeplink path -> public game URL (all link fields)
    s = s.replace(TPL_SLUG, slug)                   # any remaining bare slug (safety net)
    s = s.replace(TPL_TITLE, title)
    s = s.replace(TPL_DES, des)
    s = s.replace(TPL_CAPTION, " " + caption)       # keep the leading-space style
    s = s.replace(TPL_ICON, ICON_TOKEN)             # filled at paste time
    s = s.replace(TPL_STOPAT, stop_at)              # replace stop BEFORE start
    s = s.replace(TPL_STARTAT, start_at)            # (start is a prefix of stop's date)
    s = s.replace(TPL_RESERVED, RESERVED_TOKEN)     # reserved at paste time

    body = json.loads(s)
    body["duplicatedFromId"] = None
    body["duplicatedFromVersion"] = None

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
    start, stop = iv.get("startAt", ""), iv.get("stopAt", "")
    # Only always-stale literals (the game may itself be the template game, so
    # don't flag its slug/name). Old dates/ids and the "Copy of" prefix must go.
    stale = [lit for lit in (TPL_TITLE, TPL_ICON, TPL_STARTAT, TPL_STOPAT, TPL_RESERVED,
                             TPL_COPY_JOURNEY, "2026-06-30", "JRN-0-571678") if lit in s]
    return [
        (RESERVED_TOKEN in s, "reservedJourneyId placeholder present (filled at paste)"),
        (ICON_TOKEN in s, "icon placeholder present (uploaded at paste)"),
        (game_url(slug) in s, f"link points at public game URL {game_url(slug)}"),
        ("/launch/slots/iframe/" not in s, "old deeplink path removed"),
        (body.get("duplicatedFromId") is None, "no stale duplicatedFromId"),
        (bool(start and stop and start < stop), f"startAt {start} < stopAt {stop}"),
        (not stale, "no leftover template literals" + (f" (LEAK: {stale})" if stale else "")),
    ]


JS_TEMPLATE = r"""// NC For Discount — @COUNT@ notification journeys — generated @GENERATED_AT@
// One journey per game/day (segment -> notification -> end). For each game it
// reserves a journey id, pops a file picker for that game's 200x200 image,
// uploads it, then creates + saves the draft. Drafts are left unpublished.
(async () => {
  'use strict';
  const MANUAL_TOKEN = '';
  const BASE = @BASE_URL@;
  const BRAND = @BRAND@;
  const FOLDER_ID = @FOLDER_ID@;
  const GAMES = @GAMES@;            // [{date, name, slug, body}]
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
      img.onerror = () => { URL.revokeObjectURL(url); reject(new Error('Could not read image dimensions for ' + file.name)); };
      img.src = url;
    });
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
    const iconFile = await pickFile(G.name);
    const iconUrl = await uploadIcon(iconFile, G.name);
    console.log('    icon uploaded -> ' + iconUrl);
    let bodyStr = G.body.split('%%RESERVED%%').join(jid).split('%%ICON%%').join(iconUrl);
    const body = JSON.parse(bodyStr);
    let r = await fetch(BASE + '/journey-drafts', { method: 'POST', headers: H('application/json'), credentials: 'include', body: JSON.stringify(body) });
    let t = await r.text(); if (!r.ok) throw new Error('create HTTP ' + r.status + ' ' + t);
    const numId = JSON.parse(t).id; if (!numId) throw new Error('no draft id in create response: ' + t);
    r = await fetch(BASE + '/journey-drafts/' + numId, { method: 'PUT', headers: H('application/json'), credentials: 'include', body: JSON.stringify(body) });
    t = await r.text(); if (!r.ok) throw new Error('draft ' + jid + ' created but save failed HTTP ' + r.status + ' ' + t);
    return { jid: jid, numId: numId };
  }

  console.log('Creating ' + GAMES.length + ' notification journey(s)...');
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
    payload = [{"date": g["date"], "name": g["name"], "slug": g["slug"],
                "body": json.dumps(g["body"], ensure_ascii=False)} for g in games]
    js = JS_TEMPLATE
    js = js.replace("@COUNT@", str(len(games)))
    js = js.replace("@GENERATED_AT@", datetime.now(LOCAL_TZ).strftime("%Y-%m-%d %H:%M %Z"))
    js = js.replace("@BASE_URL@", json.dumps(DEFAULT_BASE_URL))
    js = js.replace("@BRAND@", json.dumps(BRAND))
    js = js.replace("@FOLDER_ID@", json.dumps(DEFAULT_FOLDER_ID))
    js = js.replace("@GAMES@", json.dumps(payload, ensure_ascii=False))
    return js


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--name", default="nc_discount", help="output basename (default: nc_discount)")
    p.add_argument("--dry-run", action="store_true", help="write the prepared bodies to out/ instead of a script")
    args = p.parse_args()

    games: list[dict] = []
    all_ok = True
    print(f"NC For Discount — {len(CALENDAR)} game(s):")
    for date_str, slug, name in CALENDAR:
        body, report = prepare_game(date_str, slug, name)
        games.append({"date": date_str, "slug": slug, "name": name, "body": body})
        print(f"  • {name}")
        for line in report:
            print("      " + line)
        for ok, msg in verify(body, slug):
            if not ok:
                print(f"      FAIL {msg}")
            all_ok = all_ok and ok
    if not all_ok:
        print("\nVERIFICATION FAILED — not writing output.", file=sys.stderr)
        return 1

    if args.dry_run:
        out = Path("out"); out.mkdir(exist_ok=True)
        path = out / f"{args.name}_journeys.json"
        path.write_text(json.dumps([g["body"] for g in games], ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\nDry run — {len(games)} body(ies) written: {path}")
        return 0

    js = build_js(games)
    out = Path("console_scripts"); out.mkdir(exist_ok=True)
    path = out / f"{args.name}_console.js"
    path.write_text(js, encoding="utf-8")
    print(f"\nConsole script written: {path}  ({len(games)} journeys in one paste)")
    print("Paste it into the DevTools console on a logged-in backoffice tab.")
    print("A file picker pops up per game — select that game's 200x200 image.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
