#!/usr/bin/env python3
"""Build the PMCL (Fortunazo) "Sorry Bonus" drafts — one journey per player.

Business flow, from the captured run: a player is owed a goodwill casino bonus,
so a journey targets that single player_id, offers the promotion for two days
and grants a fixed no-deposit casino bonus (30x wagering, 48h to use, release
limit 20x). One journey per player, because the segment IS the player and the
amount is per player.

Paste a list of "<player_id> <amount>" lines — the amount in major CLP, the
number that also names the journey:

    pmcl0000000000000a1 - 6240 casino bonus
    pmcl0000000000000b2 - 1680 casino bonus

This clones templates/casino/sorry_bonus_pmcl.json once per line and writes,
into BOTH storages (compiled activities and the rawJourneyData mirror):

  * the player_id the segment filters on,
  * the bonus amount (minor units and _majorUnits, in all three places it is
    stored: the bonus activity, its wageringActivity, and the promotion
    placement that advertises it),
  * the journeyName "PMCL | CS | Sorry Bonus | $<amount> Casino Bonus",
  * stopAt (default: 00:00 Chile, two days after the run — the window the
    capture used).

The generated console script, for EACH player: reserves a promotion display id
and a journey id, clones the promotion's two content trees into a fresh pair of
uuids (the six /contents/v1/copy calls the capture made), regenerates every
activity uuid, then creates the draft and saves it.

It stops there. The capture went on to publish (PUT /journeys) and start the
journey (PUT /journeys/<id>/start); this never does — the drafts are left for
review, and publishing one starts it immediately (isImmediatelyAfterPublish).

Usage:
  python sorry_bonus_pmcl_campaign.py --list players.txt
  pbpaste | python sorry_bonus_pmcl_campaign.py --list -
  python sorry_bonus_pmcl_campaign.py --list - --stop-date 2026-09-12
  python sorry_bonus_pmcl_campaign.py --list - --dry-run
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, time, timedelta
from pathlib import Path

from create_journeys import LOCAL_TZ, utc_api, walk_dicts
from casino_journey import DEFAULT_BASE_URL
from console_js import inject

HERE = Path(__file__).resolve().parent
TEMPLATE_PATH = HERE / "templates" / "casino" / "sorry_bonus_pmcl.json"
OUT_DIR = HERE / "out"
SCRIPT_DIR = HERE / "console_scripts"

BRAND = "PMCL"

# Paste-time placeholders the console script fills in per draft.
PLAYER_TOKEN = "%%PLAYER_ID%%"
RESERVED_TOKEN = "%%RESERVED%%"
PROMO_DISPLAY_TOKEN = "%%PROMO_DISPLAY_ID%%"
FRONT_TOKEN = "%%FRONT_ID%%"
CONTENT_TOKEN = "%%CONTENT_ID%%"

# The promotion's two content trees, as the capture copied them. FrontId comes
# from the first, ContentId from the second; the file filters are the ones the
# backoffice sent, kept verbatim so a clone carries the same files.
CONTENT_COPIES = [
    {"src": "e65301de-0a2b-4ac2-a6f2-ad96115a36d2", "dst": FRONT_TOKEN, "part": "spa"},
    {"src": "e65301de-0a2b-4ac2-a6f2-ad96115a36d2", "dst": FRONT_TOKEN, "part": "widget"},
    {"src": "6a3d9ebb-ad27-4c42-bbba-cb7ed49981f1", "dst": CONTENT_TOKEN, "part": "widgetModulor",
     "files": ["manifest.json", "content/content-es.json", "content/content-en.json"]},
    {"src": "6a3d9ebb-ad27-4c42-bbba-cb7ed49981f1", "dst": CONTENT_TOKEN, "part": "spa",
     "files": ["manifest.json", "content/content-es.json", "content/content-en.json",
               "media/box.png", "media/bonusHeaderImage.png"]},
    {"src": "6a3d9ebb-ad27-4c42-bbba-cb7ed49981f1", "dst": CONTENT_TOKEN, "part": "widget",
     "files": ["manifest.json", "content/content-es.json", "content/content-en.json",
               "media/box.png", "media/widgetImgKey.png"]},
    {"src": "6a3d9ebb-ad27-4c42-bbba-cb7ed49981f1", "dst": CONTENT_TOKEN, "part": "cashier",
     "files": ["manifest.json", "content/content-es.json", "content/content-en.json"]},
]

# The captured amount, kept in the template. Nothing may ship carrying it.
TPL_AMOUNT_MAJOR = 10200
TPL_STOP_AT = "2026-09-10T03:00:00"

_LINE_RE = re.compile(r"^\s*(?P<player>[A-Za-z][A-Za-z0-9_-]{6,})\D+(?P<amount>[\d.,]+)")


def parse_list(text: str) -> tuple[list[tuple[str, int]], list[str]]:
    """"<player_id> - <amount> casino bonus" lines -> [(player, major CLP)]."""
    rows: list[tuple[str, int]] = []
    problems: list[str] = []
    seen: set[str] = set()
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        m = _LINE_RE.match(line)
        if not m:
            problems.append(f"cannot read a player and an amount from {line!r}")
            continue
        player = m.group("player")
        amount = int(m.group("amount").replace(".", "").replace(",", ""))
        if amount <= 0:
            problems.append(f"{player}: amount {amount} is not a bonus")
            continue
        if player in seen:
            problems.append(f"{player}: listed twice")
            continue
        seen.add(player)
        rows.append((player, amount))
    return rows, problems


def stop_at_default(run_date: datetime) -> datetime:
    """00:00 Chile, two days out — the window the capture used."""
    return datetime.combine((run_date + timedelta(days=2)).date(), time(0, 0), tzinfo=LOCAL_TZ)


def set_bonus_amount(body: dict, major: int) -> int:
    """Write the amount everywhere it is stored, in both units.

    The bonus lives three times over (the casino_bonus activity, its
    wageringActivity, and the promotion placement that advertises it) and each
    of those has a mirror in rawJourneyData. Walking every dict writes all six
    and cannot miss one the way a path-by-path edit did.
    """
    minor = major * 100
    written = 0
    for d in walk_dicts(body):
        if "fixedBonusAmount" in d and "fixedBonusAmount_majorUnits" in d:
            d["fixedBonusAmount"] = minor
            d["fixedBonusAmount_majorUnits"] = major
            written += 1
    return written


def prepare(player: str, major: int, stop_local: datetime) -> tuple[dict, list[str]]:
    body = json.loads(TEMPLATE_PATH.read_text(encoding="utf-8"))
    text = json.dumps(body, ensure_ascii=False).replace(PLAYER_TOKEN, player)
    body = json.loads(text)

    name = f"PMCL | CS | Sorry Bonus | ${major} Casino Bonus"
    body["journeyName"] = name
    body["rawJourneyData"]["infoValues"]["journeyName"] = name

    written = set_bonus_amount(body, major)
    body["stopAt"] = utc_api(stop_local, dotnet_fraction=True)
    body["rawJourneyData"]["infoValues"]["stopAt"] = utc_api(stop_local)

    report = [
        f"player   {player}",
        f"bonus    ${major} CLP ({major * 100} minor) written in {written} places",
        f"name     {name}",
        f"stopAt   {body['stopAt']} ({stop_local:%d.%m %H:%M} Chile)",
    ]
    return body, report


def verify(body: dict, player: str, major: int) -> list[tuple[bool, str]]:
    s = json.dumps(body, ensure_ascii=False)
    iv = body.get("rawJourneyData", {}).get("infoValues", {})
    amounts = {(d["fixedBonusAmount"], d["fixedBonusAmount_majorUnits"])
               for d in walk_dicts(body)
               if "fixedBonusAmount" in d and "fixedBonusAmount_majorUnits" in d}
    seg = [d for d in walk_dicts(body) if d.get("fieldName") == "player_id"]
    targeted = {v for d in seg for v in (d.get("values") or [])}
    return [
        (PLAYER_TOKEN not in s, "player placeholder filled"),
        (targeted == {player}, f"the segment targets exactly {player} (found {sorted(targeted)})"),
        (amounts == {(major * 100, major)},
         f"every bonus field is ${major} / {major * 100} minor (found {sorted(amounts)})"),
        (str(TPL_AMOUNT_MAJOR) not in body["journeyName"], "journeyName carries this run's amount"),
        (body["journeyName"] == iv.get("journeyName"), "both storages agree on journeyName"),
        (body.get("stopAt", "").startswith(iv.get("stopAt", "x")[:16]),
         f"both storages agree on stopAt ({body.get('stopAt')})"),
        (TPL_STOP_AT not in s, "the captured stop date is gone"),
        (RESERVED_TOKEN in s, "journey id placeholder present (reserved at paste)"),
        (PROMO_DISPLAY_TOKEN in s, "promotion display id placeholder present (reserved at paste)"),
        (FRONT_TOKEN in s and CONTENT_TOKEN in s, "content tree placeholders present (cloned at paste)"),
        (body.get("duplicatedFromId") is None, "no stale duplicatedFromId"),
        ("Copy of" not in body["journeyName"], "not named 'Copy of' anything"),
    ]


JS_TEMPLATE = r"""// PMCL Sorry Bonus — @COUNT@ journey draft(s) — generated @GENERATED_AT@
// One journey per player: segment (that player_id) -> promotion -> casino bonus.
// For each, it reserves a promotion display id and a journey id, clones the
// promotion's two content trees into a fresh pair, regenerates every activity
// uuid, creates the draft and saves it. Drafts only: the recorded run also
// published and started the journey, this never does. Publishing one starts it
// immediately, so review each draft before you do.
(async () => {
  'use strict';
  const MANUAL_TOKEN = '';
@API_BASE_JS@
  const BASE = apiBase(@BASE_URL@);
  const BRAND = @BRAND@;
  const DRAFTS = @DRAFTS@;          // [{player, amount, name, body}]
  const COPIES = @COPIES@;          // the six content-tree copies, per draft
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

  const auth = await obtainAuth();
  const H = (ct) => { const h = { accept: 'application/json, text/plain, */*', authorization: auth, 'x-brand': BRAND }; if (ct) h['content-type'] = ct; return h; };
@JSON_GUARD_JS@
@DRAFT_SAVE_JS@
  const newUuid = () => (typeof crypto !== 'undefined' && crypto.randomUUID) ? crypto.randomUUID()
    : 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, (c) => { const r = Math.random()*16|0; return (c === 'x' ? r : (r&0x3)|0x8).toString(16); });
  // Every id the draft owns, regenerated per draft: two drafts sharing an
  // activityId collide. promotionId and promotionLinkId are matched by name
  // because they sit under their own keys, not under "id".
  const UUID_RE = /"(?:activityId|id|promotionId|promotionLinkId)"\s*:\s*"([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})"/g;
  function regen(txt) {
    const olds = new Set(); let m; UUID_RE.lastIndex = 0;
    while ((m = UUID_RE.exec(txt)) !== null) olds.add(m[1]);
    let t = txt;
    for (const o of olds) t = t.split(o).join(newUuid());
    return t;
  }

  async function reserveJourneyId() {
    const r = await fetch(BASE + '/journeys/identifier', { method: 'POST', headers: H('application/json'), credentials: 'include', body: '' });
    const t = await r.text(); if (!r.ok) throw new Error('reserve journey id HTTP ' + r.status + ' ' + t);
    const id = parseJsonText(t, 'reserve journey id', r.status).journeyId;
    if (!id) throw new Error('no journeyId: ' + t);
    return id;
  }
  async function reservePromoDisplayId() {
    const r = await fetch(CRM_BASE + '/promo/v0/promotion-display-identifier', { method: 'POST', headers: H('application/json'), credentials: 'include', body: '' });
    const t = await r.text(); if (!r.ok) throw new Error('reserve promotion display id HTTP ' + r.status + ' ' + t);
    const id = parseJsonText(t, 'reserve promotion display id', r.status).promotionDisplayId;
    if (!id) throw new Error('no promotionDisplayId: ' + t);
    return String(id);
  }
  // The promotion's artwork and copy live in two S3 trees. Each draft gets its
  // own pair, or every draft would share one promotion's content.
  async function cloneContent(frontId, contentId) {
    for (const c of COPIES) {
      const dst = c.dst === '%%FRONT_ID%%' ? frontId : contentId;
      const payload = { sourcePath: 'mf/v1/' + c.src + '/' + c.part, destinationPath: 'mf/v1/' + dst + '/' + c.part };
      if (c.files) payload.fileFilters = c.files;
      const r = await fetch(CRM_BASE + '/contents/v1/copy', { method: 'POST', headers: H('application/json'), credentials: 'include', body: JSON.stringify(payload) });
      const t = await r.text(); if (!r.ok) throw new Error('content copy ' + c.part + ' HTTP ' + r.status + ' ' + t);
    }
  }

  console.log('%cPMCL Sorry Bonus — ' + DRAFTS.length + ' draft(s)', 'color:#3b82f6;font-weight:bold;font-size:14px');
  const ok = [], fail = [];
  for (const D of DRAFTS) {
    console.log('%c' + D.player + '  $' + D.amount + ' ...', 'color:#3b82f6;font-weight:bold');
    try {
      const displayId = await reservePromoDisplayId();
      const jid = await reserveJourneyId();
      const frontId = newUuid(), contentId = newUuid();
      await cloneContent(frontId, contentId);
      let text = regen(D.body);
      text = text.split('%%RESERVED%%').join(jid)
                 .split('%%PROMO_DISPLAY_ID%%').join(displayId)
                 .split('%%FRONT_ID%%').join(frontId)
                 .split('%%CONTENT_ID%%').join(contentId);
      if (text.includes('%%')) throw new Error('a placeholder was left unfilled — refusing to create the draft.');
      const numId = await createAndSaveDraft(JSON.parse(text), D.name, H);
      ok.push({ player: D.player, amount: D.amount, journey: jid, draft: numId });
      console.log('%c    ✓ ' + jid + ' (draft ' + numId + ')', 'color:#22c55e');
    } catch (e) {
      const msg = String((e && e.message) || e);
      fail.push({ player: D.player, error: msg });
      console.error('    ✗ ' + D.player + ' — ' + msg);
    }
  }
  console.log('%cDONE — ' + ok.length + ' created, ' + fail.length + ' failed.', 'color:' + (fail.length ? '#f59e0b' : '#22c55e') + ';font-weight:bold;font-size:14px');
  if (ok.length) console.table(ok);
  if (fail.length) console.table(fail);
  console.log('The drafts are unpublished. Check the player and the amount on each, then publish —');
  console.log('publishing starts the journey immediately (isImmediatelyAfterPublish).');
})();
"""

JS_TEMPLATE = inject(JS_TEMPLATE)


def build_js(drafts: list[dict]) -> str:
    js = JS_TEMPLATE
    js = js.replace("@GENERATED_AT@", datetime.now(LOCAL_TZ).strftime("%Y-%m-%d %H:%M %Z"))
    js = js.replace("@COUNT@", str(len(drafts)))
    js = js.replace("@BASE_URL@", json.dumps(DEFAULT_BASE_URL))
    js = js.replace("@BRAND@", json.dumps(BRAND))
    js = js.replace("@COPIES@", json.dumps(CONTENT_COPIES, ensure_ascii=False))
    js = js.replace("@DRAFTS@", json.dumps(drafts, ensure_ascii=False))
    return js


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--list", required=True, help="file of '<player_id> - <amount>' lines, or '-' for stdin")
    p.add_argument("--stop-date", default="", help="YYYY-MM-DD; the promotion closes 00:00 Chile that day (default: two days out)")
    p.add_argument("--skip", default="",
                   help="comma-separated player ids to leave out (one who already has a Sorry Bonus journey: "
                        "a second draft grants the bonus twice)")
    p.add_argument("--name", default="sorry_bonus_pmcl", help="output basename")
    p.add_argument("--dry-run", action="store_true", help="write the prepared bodies to out/ instead of a console script")
    args = p.parse_args()

    text = sys.stdin.read() if args.list == "-" else Path(args.list).read_text(encoding="utf-8")
    rows, problems = parse_list(text)
    for w in problems:
        print(f"  WARN  {w}", file=sys.stderr)
    if not rows:
        print("\nno '<player_id> <amount>' lines found — nothing written.", file=sys.stderr)
        return 1

    skip = {s.strip() for s in args.skip.split(",") if s.strip()}
    if skip:
        rows = [r for r in rows if r[0] not in skip]
        print(f"  skipping {len(skip)} player(s) named by --skip")
    print("  a player who already has a Sorry Bonus journey must be in --skip:"
          " publishing a second draft grants the bonus twice.")

    now = datetime.now(LOCAL_TZ)
    if args.stop_date:
        try:
            day = datetime.strptime(args.stop_date, "%Y-%m-%d")
        except ValueError:
            print(f"\n--stop-date must be YYYY-MM-DD, got {args.stop_date!r}.", file=sys.stderr)
            return 1
        stop_local = datetime.combine(day.date(), time(0, 0), tzinfo=LOCAL_TZ)
    else:
        stop_local = stop_at_default(now)
    if stop_local <= now:
        print(f"\nstop {stop_local:%Y-%m-%d %H:%M} Chile is already past — nothing written.", file=sys.stderr)
        return 1

    drafts, failed = [], 0
    for player, major in rows:
        body, report = prepare(player, major, stop_local)
        print(f"\n{player}  ${major}")
        for line in report:
            print(f"  {line}")
        checks = verify(body, player, major)
        for good, label in checks:
            print(f"  {'ok  ' if good else 'FAIL'}   {label}")
        if not all(good for good, _ in checks):
            failed += 1
            continue
        drafts.append({"player": player, "amount": major,
                       "name": body["journeyName"],
                       "body": json.dumps(body, ensure_ascii=False)})

    if failed:
        print(f"\n{failed} of {len(rows)} failed verification — nothing written.", file=sys.stderr)
        return 1

    if args.dry_run:
        OUT_DIR.mkdir(parents=True, exist_ok=True)
        for d in drafts:
            out = OUT_DIR / f"{args.name}_{d['player']}.json"
            out.write_text(json.dumps(json.loads(d["body"]), ensure_ascii=False, indent=1), encoding="utf-8")
            print(f"  wrote {out}")
        return 0

    SCRIPT_DIR.mkdir(parents=True, exist_ok=True)
    path = SCRIPT_DIR / f"{args.name}_console.js"
    path.write_text(build_js(drafts), encoding="utf-8")
    print(f"\nConsole script written: {path}  ({len(drafts)} draft(s) in one paste)")
    print("Paste it into the DevTools console on a logged-in PMCL backoffice tab.")
    print("Nothing is published: review each draft, then publish it yourself.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
