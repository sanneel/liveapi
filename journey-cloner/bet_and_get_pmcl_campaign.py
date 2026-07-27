#!/usr/bin/env python3
"""
Build the PMCL (Fortunazo) "Bet and Get" weekend promotion as three linked
drafts, from one console script:

  * a **promo page** draft (its micro-frontend content copied from the captured
    template, then re-uploaded to S3),
  * a **journey** draft (external source -> promotion -> deposit -> freebet ->
    email), and
  * an **email content** (created + saved) that the journey's email activity is
    pointed at.

Captured from a real create flow (the PMCL_BET_AND_GET_AUTOM HAR). Week to week
nothing in the promo page or the journey changes except the dates — only the
email copy (the three top matches for that weekend) is new. So this generator
takes a Friday date plus the email text and bakes everything else verbatim.

Date formula (America/Santiago, DST-aware):
  --date is the promo's **Friday**.
    promo showDate / startDate  = Friday 04:40
    promo endDate               = Sunday 21:59
    journey startAt             = null  (starts immediately)
    journey stopAt              = Sunday 22:00

Usage:
  python bet_and_get_pmcl_campaign.py --date 2026-07-17 --email-spec email.txt

  # or pipe the email text in:
  pbpaste | python bet_and_get_pmcl_campaign.py --date 2026-07-17 --email-spec -

The email spec is three sections separated by blank-line-delimited labels:

    Subject: ...
    Pre-header: ...
    Body:
    ⚽ El fin de semana trae ...
    🇨🇱 Apoya a tu favorito en el [Colo Colo vs Concepcion](https://fortunazo.cl/events/...).
    ...

Markdown-style [label](url) links in the Body become the template's underlined
<a> markup, so the three matches are just three links in the text.

Then paste console_scripts/<name>_console.js into the DevTools console on a
logged-in PMCL backoffice tab. --dry-run writes the prepared payloads to out/
instead.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import uuid
from datetime import datetime, time, timedelta
from pathlib import Path

from create_journeys import LOCAL_TZ, UTC

TEMPLATE_DIR = Path(__file__).resolve().parent / "templates" / "pmcl_betandget"
JOURNEY_PATH = TEMPLATE_DIR / "journey.json"
PROMO_PATH = TEMPLATE_DIR / "promo_page.json"
EMAIL_PATH = TEMPLATE_DIR / "email.json"
S3_PATH = TEMPLATE_DIR / "s3_uploads.json"

BASE_URL = "https://pmi.rea-backoffice.gr8.tech/api/ubo/api/v0/crm"
BRAND = "PMCL"

# Promo-page micro-frontend templates the captured run copied from. Copying
# these is what gives the new page its content; the S3 re-uploads then write
# the (unchanged) copy on top.
CONTENT_TEMPLATE_PATH = "mf/v1/30a89494-e191-4a18-9a5c-e937e55b04dd"
FRONT_TEMPLATE_PATH = "mf/v1/0ae79790-c277-4054-ada8-05c0b1984c74"

# Paste-time placeholders the console script fills in once the real ids exist.
JOURNEY_ID_TOKEN = "@@JOURNEY_ID@@"
PROMO_DISPLAY_ID_TOKEN = "@@PROMO_DISPLAY_ID@@"
EMAIL_CONTENT_ID_TOKEN = "@@EMAIL_CONTENT_ID@@"
CONTENT_ID_TOKEN = "@@CONTENT_ID@@"
FRONT_ID_TOKEN = "@@FRONT_ID@@"
ENTRY_ACTIVITY_ID_TOKEN = "@@ENTRY_ACTIVITY_ID@@"

# Chile-local wall-clock times the formula pins.
PROMO_START = time(4, 40)
PROMO_END = time(21, 59)
JOURNEY_STOP = time(22, 0)

# The single editable paragraph in the captured email body.
_BODY_P_RE = re.compile(r"<p>.*?</p>", re.DOTALL)
_MD_LINK_RE = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")
_LINK_STYLE = 'style="color: inherit; text-decoration: underline;"'

API_DT = "%Y-%m-%dT%H:%M:%S.0000000Z"


def _to_api_utc(dt: datetime) -> str:
    return dt.astimezone(UTC).strftime(API_DT)


def promo_window(date_str: str) -> tuple[datetime, datetime, datetime]:
    """(promo_start, promo_end, journey_stop) as Chile-local datetimes.

    --date is the Friday. The promo runs Friday 04:40 -> Sunday 21:59 and the
    journey stops Sunday 22:00. Sunday is derived, so a date that isn't a
    Friday is rejected by the caller rather than silently shifting the window.
    """
    day = datetime.strptime(date_str, "%Y-%m-%d").date()
    sunday = day + timedelta(days=2)
    start = datetime.combine(day, PROMO_START, tzinfo=LOCAL_TZ)
    end = datetime.combine(sunday, PROMO_END, tzinfo=LOCAL_TZ)
    stop = datetime.combine(sunday, JOURNEY_STOP, tzinfo=LOCAL_TZ)
    return start, end, stop


def parse_email_spec(text: str) -> dict[str, str]:
    """Pull Subject / Pre-header / Body out of the pasted email text."""
    subject = preheader = ""
    body_lines: list[str] = []
    mode = ""
    for raw in text.splitlines():
        line = raw.rstrip()
        low = line.strip().lower()
        if low.startswith("subject:"):
            subject = line.split(":", 1)[1].strip()
            mode = ""
            continue
        if low.startswith("pre-header:") or low.startswith("preheader:"):
            preheader = line.split(":", 1)[1].strip()
            mode = ""
            continue
        if low in ("body:", "body"):
            mode = "body"
            continue
        if mode == "body":
            body_lines.append(line)
    return {
        "subject": subject,
        "preheader": preheader,
        "body": "\n".join(body_lines).strip(),
    }


def _html_escape(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def body_to_html(body: str) -> str:
    """Turn the pasted body into the captured template's paragraph markup:
    single newlines -> <br>, blank lines -> <br><br>, and [label](url) ->
    the template's underlined anchor."""
    def _line(text: str) -> str:
        out, idx = [], 0
        for m in _MD_LINK_RE.finditer(text):
            out.append(_html_escape(text[idx:m.start()]))
            label, url = m.group(1).strip(), m.group(2).strip()
            out.append(f'<a href="{url}" {_LINK_STYLE}>{_html_escape(label)}</a>')
            idx = m.end()
        out.append(_html_escape(text[idx:]))
        return "".join(out)

    blocks = [b for b in re.split(r"\n\s*\n", body.strip())]
    rendered = []
    for block in blocks:
        rendered.append("<br>\n".join(_line(l) for l in block.splitlines() if l.strip()))
    inner = "\n<br><br>\n".join(r for r in rendered if r)
    return f"<p>\n{inner}\n</p>"


def email_name(start_local: datetime) -> str:
    return f"FTCL SP Weekend depandget {start_local:%d.%m.%Y}"


def prepare_email(email: dict[str, str], start_local: datetime) -> dict:
    content = json.loads(EMAIL_PATH.read_text(encoding="utf-8"))
    content["name"] = email_name(start_local)
    comp = content["translations"]["es"]["composition"]
    if email["subject"]:
        comp["subject"] = email["subject"]
    if email["preheader"]:
        comp["preHeader"] = email["preheader"]
    if email["body"]:
        src = comp["body"]["source"]
        html = body_to_html(email["body"])
        new_src, n = _BODY_P_RE.subn(lambda _m: html, src, count=1)
        if n != 1:
            raise ValueError("Could not locate the editable <p> block in the email template.")
        comp["body"]["source"] = new_src
    return content


def prepare_promo_page(start_local: datetime, end_local: datetime) -> dict:
    promo = json.loads(PROMO_PATH.read_text(encoding="utf-8"))
    start_api, end_api = _to_api_utc(start_local), _to_api_utc(end_local)
    promo["showDate"] = start_api
    promo["startDate"] = start_api
    promo["initialShowDate"] = start_api
    promo["endDate"] = end_api
    promo["initialEndDate"] = end_api
    promo["createDate"] = _to_api_utc(datetime.now(LOCAL_TZ))
    promo["contentId"] = CONTENT_ID_TOKEN
    promo["frontId"] = FRONT_ID_TOKEN
    promo["urlShortName"] = str(uuid.uuid4())
    promo["promotionDisplayId"] = None
    # Point the page at the journey this run creates, not the captured one.
    settings = promo["promotionSettings"]["journeyPromotionSettings"]
    settings["journeyId"] = JOURNEY_ID_TOKEN
    settings["activityId"] = ENTRY_ACTIVITY_ID_TOKEN
    return promo


def entry_activity_id(body: dict) -> str:
    for a in body.get("activities", []):
        if a.get("activityName") == "external_system_source":
            return a["activityId"]
    raise ValueError("external_system_source activity not found in the journey template")


def prepare_journey(stop_local: datetime) -> dict:
    body = json.loads(JOURNEY_PATH.read_text(encoding="utf-8"))
    body["startAt"] = None          # start immediately
    body["stopAt"] = _to_api_utc(stop_local)
    body["brand"] = BRAND
    body["reservedJourneyId"] = JOURNEY_ID_TOKEN
    for key in ("duplicatedFromId", "duplicatedFromVersion", "journeyId", "id", "version"):
        body.pop(key, None)
    for a in body.get("activities", []):
        init = a.get("initializationData") or {}
        if a.get("activityName") == "promotion":
            init["promotionDisplayId"] = PROMO_DISPLAY_ID_TOKEN
        if a.get("activityName") == "dextra_email":
            settings = init.get("emailSettings") or {}
            settings["template"] = {"id": EMAIL_CONTENT_ID_TOKEN}
            init["displayData"] = [EMAIL_CONTENT_ID_TOKEN]
    return body


def prepare_s3_uploads() -> list[dict]:
    return json.loads(S3_PATH.read_text(encoding="utf-8"))


def verify(journey: dict, promo: dict, email: dict,
           start_local: datetime, end_local: datetime,
           stop_local: datetime) -> list[tuple[bool, str]]:
    checks: list[tuple[bool, str]] = []
    js = json.dumps(journey, ensure_ascii=False)
    ps = json.dumps(promo, ensure_ascii=False)
    es = json.dumps(email, ensure_ascii=False)

    checks.append((journey.get("startAt") is None, "journey startAt is null (starts immediately)"))
    checks.append((journey.get("stopAt") == _to_api_utc(stop_local),
                   f"journey stopAt {journey.get('stopAt')} = {stop_local:%Y-%m-%d %H:%M} Chile"))
    checks.append((journey.get("brand") == BRAND, f"journey brand is {journey.get('brand')!r}"))
    checks.append((journey.get("reservedJourneyId") == JOURNEY_ID_TOKEN, "journey id is the paste-time token"))
    checks.append(("duplicatedFromId" not in journey, "no stale duplicatedFromId"))

    checks.append((promo["startDate"] == _to_api_utc(start_local),
                   f"promo startDate {promo['startDate']} = {start_local:%Y-%m-%d %H:%M} Chile ({start_local:%A})"))
    checks.append((promo["endDate"] == _to_api_utc(end_local),
                   f"promo endDate {promo['endDate']} = {end_local:%Y-%m-%d %H:%M} Chile ({end_local:%A})"))
    checks.append((promo["showDate"] == promo["startDate"], "promo showDate matches startDate"))
    checks.append((promo["initialEndDate"] == promo["endDate"], "promo initialEndDate matches endDate"))
    checks.append((promo["brand"] == BRAND, f"promo brand is {promo['brand']!r}"))
    checks.append((promo["contentId"] == CONTENT_ID_TOKEN and promo["frontId"] == FRONT_ID_TOKEN,
                   "promo content/front ids are paste-time tokens"))
    checks.append((promo["promotionSettings"]["journeyPromotionSettings"]["journeyId"] == JOURNEY_ID_TOKEN,
                   "promo page points at THIS run's journey"))

    comp = email["translations"]["es"]["composition"]
    checks.append((bool(comp["subject"]), f"email subject set ({comp['subject'][:40]!r})"))
    checks.append((bool(comp["preHeader"]), "email pre-header set"))
    links = re.findall(r'<a href="([^"]+)"', comp["body"]["source"])
    event_links = [l for l in links if "/events/" in l]
    checks.append((len(event_links) == 3, f"email body has 3 match links ({len(event_links)} found)"))
    checks.append((EMAIL_CONTENT_ID_TOKEN in js, "journey email activity points at the new content token"))

    for token in (CONTENT_ID_TOKEN, FRONT_ID_TOKEN):
        checks.append((token not in js, f"no stray {token} in the journey payload"))
    checks.append((PROMO_DISPLAY_ID_TOKEN in js, "promotionDisplayId is the paste-time token"))
    checks.append((EMAIL_CONTENT_ID_TOKEN not in ps, "no email token leaked into the promo page"))
    checks.append(("@@" not in es, "email content has no unresolved placeholders"))
    return checks


JS_TEMPLATE = r"""// PMCL Bet & Get weekend promotion — generated @GENERATED_AT@
// Promo window: @WINDOW@
//
// Paste into the DevTools console on a logged-in PMCL backoffice tab. It will,
// in order:
//   1. capture the auth token from the page's own requests,
//   2. reserve a promotion-display id and a journey id,
//   3. copy the promo-page content + front templates to fresh ids,
//   4. create the journey draft,
//   5. create + save the promo page draft and upload its content to S3,
//   6. create + save the email content and point the journey at it.
// Everything is left as a DRAFT. Heavy logging; stops at the first error.
(async () => {
  'use strict';
  const MANUAL_TOKEN = '';
  const BASE = @BASE_URL@;
  const BRAND = @BRAND@;
  const JOURNEY = @JOURNEY@;
  const PROMO = @PROMO@;
  const EMAIL_CONTENT = @EMAIL_CONTENT@;
  const S3_UPLOADS = @S3_UPLOADS@;
  const CONTENT_TEMPLATE = @CONTENT_TEMPLATE@;
  const FRONT_TEMPLATE = @FRONT_TEMPLATE@;
  const JOURNEY_ID_TOKEN = @JOURNEY_ID_TOKEN@;
  const PROMO_DISPLAY_ID_TOKEN = @PROMO_DISPLAY_ID_TOKEN@;
  const EMAIL_CONTENT_ID_TOKEN = @EMAIL_CONTENT_ID_TOKEN@;
  const CONTENT_ID_TOKEN = @CONTENT_ID_TOKEN@;
  const FRONT_ID_TOKEN = @FRONT_ID_TOKEN@;
  const ENTRY_ACTIVITY_ID_TOKEN = @ENTRY_ACTIVITY_ID_TOKEN@;

  const JB = BASE + '/journey-builder/v0';
  const PROMO_BASE = BASE + '/promo/v2';
  const CONTENT_COPY = BASE + '/contents/v1/copy';
  const EMAIL_BASE = BASE + '/content-studio/v0/eb-backoffice/email/contents';

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
  const headers = () => ({ accept: 'application/json, text/plain, */*', authorization: auth, 'x-brand': BRAND });
  const jsonHeaders = () => ({ ...headers(), 'content-type': 'application/json' });

  async function call(method, url, body, label) {
    const opts = { method, headers: body === undefined ? headers() : jsonHeaders(), credentials: 'include' };
    if (body !== undefined) opts.body = JSON.stringify(body);
    const r = await fetch(url, opts);
    const text = await r.text();
    if (!r.ok) throw new Error(label + ' failed: HTTP ' + r.status + ' ' + text);
    try { return text ? JSON.parse(text) : null; } catch (e) { return text; }
  }

  const newUuid = () => (typeof crypto !== 'undefined' && crypto.randomUUID) ? crypto.randomUUID()
    : 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, (c) => { const r = Math.random()*16|0; return (c === 'x' ? r : (r&0x3)|0x8).toString(16); });
  const UUID_RE = /"(?:activityId|id)"\s*:\s*"([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})"/g;

  // 1. reserve ids
  console.log('Reserving ids...');
  const disp = await call('POST', BASE + '/promo/v0/promotion-display-identifier', undefined, 'promotion-display-identifier');
  const promotionDisplayId = disp.promotionDisplayId;
  console.log('  promotionDisplayId', promotionDisplayId);
  const jid = await call('POST', JB + '/journeys/identifier', undefined, 'journeys/identifier');
  const journeyId = (jid && (jid.journeyId || jid.identifier || jid.id)) || String(jid).replace(/"/g, '');
  if (!String(journeyId).startsWith('JRN-')) throw new Error('Bad journey id: ' + JSON.stringify(jid));
  console.log('  journeyId', journeyId);

  // 2. copy the promo-page content + front templates to fresh ids
  const contentId = newUuid(), frontId = newUuid();
  console.log('Copying promo-page templates...');
  await call('POST', CONTENT_COPY, { sourcePath: CONTENT_TEMPLATE, destinationPath: 'mf/v1/' + contentId }, 'content copy');
  await call('POST', CONTENT_COPY, { sourcePath: FRONT_TEMPLATE, destinationPath: 'mf/v1/' + frontId }, 'front copy');
  console.log('  contentId', contentId, '| frontId', frontId);

  // 3. email content first, so the journey can be created already pointing at
  //    a real content id (posting the placeholder token risks a 4xx).
  console.log('Creating email content...');
  const cse = await call('POST', EMAIL_BASE, EMAIL_CONTENT, 'email content create');
  const cseId = cse.id || cse;
  console.log('  email content', cseId);
  await call('POST', EMAIL_BASE + '/' + cseId, EMAIL_CONTENT, 'email content save');

  // 4. journey draft — regenerate every activity uuid so it is a fresh graph,
  //    then remember the entry activity the promo page has to point at.
  let jText = JSON.stringify(JOURNEY);
  const oldIds = new Set(); let m; UUID_RE.lastIndex = 0;
  while ((m = UUID_RE.exec(jText)) !== null) oldIds.add(m[1]);
  const idMap = {};
  for (const o of oldIds) { idMap[o] = newUuid(); jText = jText.split(o).join(idMap[o]); }
  jText = jText.split(JOURNEY_ID_TOKEN).join(journeyId)
               .split(PROMO_DISPLAY_ID_TOKEN).join(String(promotionDisplayId))
               .split(EMAIL_CONTENT_ID_TOKEN).join(cseId);
  if (jText.includes('@@')) throw new Error('Journey payload still has an unresolved @@token@@.');
  const journeyBody = JSON.parse(jText);
  const entryOld = @ENTRY_OLD_ID@;
  const entryActivityId = idMap[entryOld] || entryOld;

  console.log('Creating journey draft', journeyId, ':', journeyBody.journeyName);
  const draft = await call('POST', JB + '/journey-drafts', journeyBody, 'journey draft create');
  const draftId = (draft && (draft.id || draft.draftId)) || draft;
  console.log('  journey draft', draftId);

  // 5. promo page draft, pointing at this run's journey entry activity
  let pText = JSON.stringify(PROMO)
    .split(CONTENT_ID_TOKEN).join(contentId)
    .split(FRONT_ID_TOKEN).join(frontId)
    .split(JOURNEY_ID_TOKEN).join(journeyId)
    .split(ENTRY_ACTIVITY_ID_TOKEN).join(entryActivityId);
  if (pText.includes('@@')) throw new Error('Promo page payload still has an unresolved @@token@@.');
  const promoBody = JSON.parse(pText);
  console.log('Creating promo page draft...');
  const created = await call('POST', PROMO_BASE + '/promo-drafts/promo-page', promoBody, 'promo page create');
  const promoId = created.id || created;
  console.log('  promo page', promoId);
  await call('PUT', PROMO_BASE + '/promo-drafts/promo-page/' + promoId, promoBody, 'promo page save');

  // 6. promo-page content to S3
  console.log('Uploading promo-page content (' + S3_UPLOADS.length + ' files)...');
  for (const up of S3_UPLOADS) {
    const path = up.path.split(CONTENT_ID_TOKEN).join(contentId).split(FRONT_ID_TOKEN).join(frontId);
    await call('POST', PROMO_BASE + '/s3/upload', { path, data: up.data }, 's3 upload ' + path);
    console.log('  uploaded', path);
  }

  console.log('%cDONE — all three drafts created.', 'color:#22c55e;font-weight:bold;font-size:14px');
  console.log('  Journey draft : ' + journeyId + '  (draft ' + draftId + ')');
  console.log('  Promo page    : ' + promoId);
  console.log('  Email content : ' + cseId);
  console.log('  Promo window  : @WINDOW@');
})();
"""


def build_js(journey: dict, promo: dict, email: dict, uploads: list,
             entry_old_id: str, window: str) -> str:
    js = JS_TEMPLATE
    js = js.replace("@GENERATED_AT@", datetime.now(LOCAL_TZ).strftime("%Y-%m-%d %H:%M %Z"))
    js = js.replace("@WINDOW@", window)
    js = js.replace("@BASE_URL@", json.dumps(BASE_URL))
    js = js.replace("@BRAND@", json.dumps(BRAND))
    js = js.replace("@JOURNEY@", json.dumps(journey, ensure_ascii=False))
    js = js.replace("@PROMO@", json.dumps(promo, ensure_ascii=False))
    js = js.replace("@EMAIL_CONTENT@", json.dumps(email, ensure_ascii=False))
    js = js.replace("@S3_UPLOADS@", json.dumps(uploads, ensure_ascii=False))
    js = js.replace("@CONTENT_TEMPLATE@", json.dumps(CONTENT_TEMPLATE_PATH))
    js = js.replace("@FRONT_TEMPLATE@", json.dumps(FRONT_TEMPLATE_PATH))
    js = js.replace("@JOURNEY_ID_TOKEN@", json.dumps(JOURNEY_ID_TOKEN))
    js = js.replace("@PROMO_DISPLAY_ID_TOKEN@", json.dumps(PROMO_DISPLAY_ID_TOKEN))
    js = js.replace("@EMAIL_CONTENT_ID_TOKEN@", json.dumps(EMAIL_CONTENT_ID_TOKEN))
    js = js.replace("@CONTENT_ID_TOKEN@", json.dumps(CONTENT_ID_TOKEN))
    js = js.replace("@FRONT_ID_TOKEN@", json.dumps(FRONT_ID_TOKEN))
    # @ENTRY_OLD_ID@ deliberately is not a substring of the @@…@@ token above;
    # an earlier "@ENTRY_ACTIVITY_ID@" name matched inside the token this line
    # had just written and corrupted the payload.
    js = js.replace("@ENTRY_ACTIVITY_ID_TOKEN@", json.dumps(ENTRY_ACTIVITY_ID_TOKEN))
    js = js.replace("@ENTRY_OLD_ID@", json.dumps(entry_old_id))
    assert "@ENTRY_OLD_ID@" not in js
    return js


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--date", required=True, help="The promo's FRIDAY, YYYY-MM-DD. Sunday's end is derived.")
    p.add_argument("--email-spec", required=True, help="Path to the email text (Subject/Pre-header/Body), or '-' for stdin")
    p.add_argument("--name", default="pmcl_bet_and_get", help="Output file basename")
    p.add_argument("--allow-any-weekday", action="store_true", help="Skip the Friday check on --date")
    p.add_argument("--dry-run", action="store_true", help="Write the prepared payloads to out/ instead of a console script")
    args = p.parse_args()

    try:
        day = datetime.strptime(args.date, "%Y-%m-%d").date()
    except ValueError:
        print(f"\n--date must be YYYY-MM-DD, got {args.date!r}.", file=sys.stderr)
        return 1
    if day.weekday() != 4 and not args.allow_any_weekday:
        print(f"\n--date {args.date} is a {day:%A}, not a Friday. The promo window is "
              f"Friday 04:40 -> Sunday 21:59; pass --allow-any-weekday to override.", file=sys.stderr)
        return 1

    spec_text = sys.stdin.read() if args.email_spec == "-" else Path(args.email_spec).read_text(encoding="utf-8")
    email_spec = parse_email_spec(spec_text)
    if not email_spec["body"]:
        print("\nEmail spec has no Body: section — nothing written.", file=sys.stderr)
        return 1

    start_local, end_local, stop_local = promo_window(args.date)
    window = (f"{start_local:%a %d.%m %H:%M} -> {end_local:%a %d.%m %H:%M} Chile")

    journey = prepare_journey(stop_local)
    entry_old = entry_activity_id(json.loads(JOURNEY_PATH.read_text(encoding="utf-8")))
    promo = prepare_promo_page(start_local, end_local)
    email = prepare_email(email_spec, start_local)
    uploads = prepare_s3_uploads()

    print("Applied:")
    print(f"  promo page : {start_local:%Y-%m-%d %H:%M} ({start_local:%A}) -> {end_local:%Y-%m-%d %H:%M} ({end_local:%A}) Chile")
    print(f"  journey    : starts immediately -> stops {stop_local:%Y-%m-%d %H:%M} ({stop_local:%A}) Chile")
    print(f"  email      : {email['name']!r}")
    print(f"  promo-page content: {len(uploads)} S3 files, templates copied to fresh ids at paste time")

    print("Verification:")
    all_ok = True
    for ok, msg in verify(journey, promo, email, start_local, end_local, stop_local):
        print(f"  {'OK  ' if ok else 'FAIL'} {msg}")
        all_ok = all_ok and ok
    if not all_ok:
        print("\nVERIFICATION FAILED — not writing output.", file=sys.stderr)
        return 1

    if args.dry_run:
        out = Path("out"); out.mkdir(exist_ok=True)
        for label, payload in (("journey", journey), ("promo_page", promo), ("email", email)):
            path = out / f"{args.name}_{label}.json"
            path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            print(f"\nDry run — {label} written: {path}")
        return 0

    js = build_js(journey, promo, email, uploads, entry_old, window)
    out = Path("console_scripts"); out.mkdir(exist_ok=True)
    path = out / f"{args.name}_console.js"
    path.write_text(js, encoding="utf-8")
    print(f"\nConsole script written: {path}")
    print("Paste it into the DevTools console on a logged-in PMCL backoffice tab.")
    print("It creates the promo page, the journey and the email — all as drafts.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
