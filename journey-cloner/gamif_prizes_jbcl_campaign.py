#!/usr/bin/env python3
"""JBCL gamification prizes: one API-triggered journey per prize amount.

Twelve journeys, all entered through the API (webhook) node so Smartico can
push a winner into the one that matches their prize:

    cash   90 000 / 120 000 / 150 000        money bonus
    1x     45 000 / 60 000                   casino bonus, wagering 1x
    3x     20 000 / 30 000                   casino bonus, wagering 3x
    5x     1 000 / 4 000 / 7 000 / 10 000 / 15 000   casino bonus, wagering 5x

WHY THIS ONE HAS NO templates/ FILE
-----------------------------------
Like welcome_pack_campaign.py, the console script GETs the two source drafts at
paste time and clones what it finds, instead of carrying a stored copy:

  * both sources are maintained by hand in the backoffice (one money bonus, one
    casino bonus), so a stored copy would drift the first time someone edits
    them there;
  * the operator captured them as fetch bodies, not as a HAR of a full run, so
    the surrounding calls (promotion content copies) were never recorded.

The trade is the same one welcome_pack makes: shape is whatever those two
drafts are on the day you paste, so look at them before a run that matters.

WHAT IT SUBSTITUTES, PER DRAFT
------------------------------
  * the amount, in every field that stores it and in both storages. A money
    bonus stores major units (200000 means $200 000); a casino bonus stores
    minor units plus a _majorUnits twin, so a $45 000 bonus is 4500000/45000.
  * the wagering requirement, for the casino prizes only (1x, 3x, 5x).
  * the journeyName, the webhook node's description, the money bonus's
    transaction title, and the notification's %money-amount% variable.
  * a fresh webhookId per journey, so twelve prizes are twelve URLs and not
    one. --keep-webhook-id reuses the source's if you would rather set them by
    hand in the UI afterwards.
  * fresh ids everywhere, and a promotion display id reserved per draft.

THE CASINO SOURCE'S ENTRY NODE
------------------------------
The casino source the operator captured starts from a DWH segment (one
player_id), not from the API. When that is still true, the script lifts the API
node out of the money source and puts it in place of the segment, keeping the
activity id so every dependency and edge still resolves, and refuses if a
player_id filter survives. Hand-make one casino draft that already starts with
the API node, pass its id as --casino-source, and no transplant happens.

WHAT IT DOES NOT DO
-------------------
Each draft points at the SAME promotion content tree as its source draft: the
backoffice copies that tree when you duplicate a journey in the UI, and those
copy calls were not captured here. For a set of prizes sharing one card that is
usually what you want; if a prize needs its own card, copy the tree by hand and
re-point that draft before publishing.

Nothing is published. Both sources publish immediately when published
(isImmediatelyAfterPublish), so review each draft first.

Usage:
  python gamif_prizes_jbcl_campaign.py --money-source 693903 --casino-source 693908
  python gamif_prizes_jbcl_campaign.py --money-source 693903 --casino-source 693908 \
      --only cash,5x --name gamif_cash
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

from create_journeys import LOCAL_TZ
from console_js import inject

HERE = Path(__file__).resolve().parent
OUT_DIR = HERE / "console_scripts"

BRAND = "JBCL"
BASE_URL = "https://pmi.rea-backoffice.gr8.tech/api/ubo/api/v0/crm/journey-builder/v0"

# Only the keys the backoffice itself posts. A GET of a draft returns more.
POST_KEYS = [
    "journeyName", "brand", "currencyCodes", "activities", "metadata",
    "reEntryRule", "timeZoneId", "testControlGroupParameters",
    "activityEventConversionMetrics", "reservedJourneyId", "journeySource",
    "isArchived", "isUnlimited", "isImmediatelyAfterPublish", "rawJourneyData",
    "stopAt", "startAt", "exitCriteriaId",
]

# The prize table from the brief. "kind" picks the source draft; "wagering" is
# the casino bonus's rollover and is meaningless for a money bonus.
PRIZES = [
    {"group": "cash", "kind": "money", "amount": 90000, "wagering": None},
    {"group": "cash", "kind": "money", "amount": 120000, "wagering": None},
    {"group": "cash", "kind": "money", "amount": 150000, "wagering": None},
    {"group": "1x", "kind": "casino", "amount": 45000, "wagering": 1},
    {"group": "1x", "kind": "casino", "amount": 60000, "wagering": 1},
    {"group": "3x", "kind": "casino", "amount": 20000, "wagering": 3},
    {"group": "3x", "kind": "casino", "amount": 30000, "wagering": 3},
    {"group": "5x", "kind": "casino", "amount": 1000, "wagering": 5},
    {"group": "5x", "kind": "casino", "amount": 4000, "wagering": 5},
    {"group": "5x", "kind": "casino", "amount": 7000, "wagering": 5},
    {"group": "5x", "kind": "casino", "amount": 10000, "wagering": 5},
    {"group": "5x", "kind": "casino", "amount": 15000, "wagering": 5},
]

GROUPS = ("cash", "1x", "3x", "5x")


def spaced(amount: int) -> str:
    """200000 -> '200 000', the way the captured names and titles write it."""
    return f"{amount:,}".replace(",", " ")


def journey_name(prize: dict) -> str:
    if prize["kind"] == "money":
        return f"{BRAND} | CS&SP | Gamif - money bonus | {spaced(prize['amount'])}"
    return (f"{BRAND} | CS | Gamif - casino bonus {prize['wagering']}x "
            f"| {spaced(prize['amount'])}")


def prepare(groups: list[str]) -> tuple[list[dict], list[str]]:
    prizes = [p for p in PRIZES if p["group"] in groups]
    drafts = [{**p, "name": journey_name(p), "amountText": spaced(p["amount"])} for p in prizes]
    report = [f"{len(drafts)} draft(s) from {len(set(d['kind'] for d in drafts))} source(s)"]
    for d in drafts:
        wag = f"{d['wagering']}x rollover" if d["wagering"] else "money bonus, no rollover"
        report.append(f"  {d['group']:>4}  ${d['amountText']:>8}  {wag:24} {d['name']}")
    return drafts, report


def verify(drafts: list[dict]) -> list[tuple[bool, str]]:
    names = [d["name"] for d in drafts]
    money = [d for d in drafts if d["kind"] == "money"]
    casino = [d for d in drafts if d["kind"] == "casino"]
    return [
        (bool(drafts), "at least one prize selected"),
        (len(set(names)) == len(names), "every journey name is distinct"),
        (all(d["amount"] > 0 for d in drafts), "every amount is positive"),
        (all(d["wagering"] is None for d in money), "money bonuses carry no rollover"),
        (all(d["wagering"] in (1, 3, 5) for d in casino),
         "every casino bonus rolls over 1x, 3x or 5x"),
        (all(str(d["amount"]) not in d["name"] or d["amountText"] in d["name"] for d in drafts),
         "each name spells its own amount"),
    ]


JS_TEMPLATE = r"""// JBCL gamification prizes — @COUNT@ API-triggered draft(s) — generated @GENERATED_AT@
// Clones the two source drafts live: money bonus @MONEY_SOURCE@, casino bonus
// @CASINO_SOURCE@. Per prize it reserves a journey id and a promotion display
// id, regenerates every internal id, writes the amount (and the rollover, for a
// casino bonus) into both storages, gives the API node its own webhookId, then
// creates the draft and saves it. Nothing is published.
(async () => {
  'use strict';
  const MANUAL_TOKEN = '';
@API_BASE_JS@
  const BASE = apiBase(@BASE_URL@);
  const BRAND = @BRAND@;
  const MONEY_SOURCE = @MONEY_SOURCE@;
  const CASINO_SOURCE = @CASINO_SOURCE@;
  const PRIZES = @PRIZES@;               // [{group, kind, amount, wagering, name, amountText}]
  const POST_KEYS = @POST_KEYS@;
  const KEEP_WEBHOOK_ID = @KEEP_WEBHOOK_ID@;
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
  // Same alphabet and length as the webhookId the backoffice minted for the
  // captured API node. One journey per prize means one URL per prize.
  const newWebhookId = () => {
    const abc = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789';
    let s = ''; for (let i = 0; i < 12; i++) s += abc[Math.floor(Math.random() * abc.length)];
    return s;
  };
  const UUID_RE = /"(?:activityId|id|promotionId|promotionLinkId|flowId|nodeId|filterConditionId)"\s*:\s*"([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})"/g;
  function regenIds(text) {
    const olds = new Set(); let m; UUID_RE.lastIndex = 0;
    while ((m = UUID_RE.exec(text)) !== null) olds.add(m[1]);
    let t = text;
    for (const o of olds) t = t.split(o).join(newUuid());
    return t;
  }
  const walk = (o, fn) => {
    if (Array.isArray(o)) { o.forEach((v) => walk(v, fn)); return; }
    if (o && typeof o === 'object') { fn(o); Object.values(o).forEach((v) => walk(v, fn)); }
  };

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
  async function getDraft(numId, label) {
    const r = await fetch(BASE + '/journey-drafts/' + numId, { headers: H(), credentials: 'include' });
    const t = await r.text(); if (!r.ok) throw new Error(label + ' source draft ' + numId + ' HTTP ' + r.status + ' ' + t);
    const d = parseJsonText(t, label + ' source draft', r.status);
    if (!d || !Array.isArray(d.activities) || !d.activities.length) throw new Error(label + ' source draft ' + numId + ' has no activities[]');
    return d;
  }

  const findActivity = (body, name) => body.activities.find((a) => a.activityName === name);
  const entryActivity = (body) => body.activities.find((a) => (a.events || []).some((e) => e.eventType === 'Activation'));

  // The casino source starts from a DWH segment. Put the money source's API
  // node in its place, keeping the activity id so every dependency, edge, port
  // and mirror key still resolves, and drop the segment's filter with it.
  function useApiEntry(body, apiTemplate, description, webhookId) {
    const entry = entryActivity(body);
    if (!entry) throw new Error('the source has no activation node');
    const nextId = (entry.events[0].nextActivityId) || null;
    if (entry.activityName !== 'external_system_source' && !nextId) {
      throw new Error('the segment node fans out into paths this script cannot rewire; give it a source that already starts with the API node');
    }
    entry.activityName = 'external_system_source';
    entry.activityDisplayName = 'API';
    entry.dataKeys = [];
    entry.initializationData = {
      webhookId: webhookId,
      description: description,
      targetSystem: 'Webhook',
      isWebhookUrlHidden: (apiTemplate.initializationData || {}).isWebhookUrlHidden === true,
      displayData: ['Webhook'],
    };
    entry.events = [{
      eventName: 'PlayerAdded', eventType: 'Activation',
      eventDisplayName: 'Players added to journey',
      nextActivityId: nextId, isUsedInChoosableFlow: false,
    }];
    const raw = body.rawJourneyData || {};
    for (const el of (raw.elements || [])) {
      if (el.id !== entry.activityId || !el.data || el.type !== 'source') continue;
      el.data.name = 'external_system_source';
      el.data.activityDisplayName = 'API';
      el.data.events = [{ isHidden: false, eventName: 'PlayerAdded', eventType: 'Activation', eventDisplayName: 'Players added to journey' }];
    }
    if (raw.activitiesConfiguration && raw.activitiesConfiguration[entry.activityId]) {
      raw.activitiesConfiguration[entry.activityId] = {
        data: { dataKeys: [], webhookId: webhookId, description: description, targetSystem: 'Webhook', isWebhookUrlHidden: false },
        error: false, isTouched: true, displayData: ['Webhook'], displayName: 'API',
      };
    }
  }

  // A money bonus stores major units; a casino bonus stores minor units and a
  // _majorUnits twin. Both live several times over, in the mechanic, in the
  // promotion placement that advertises it, and in the rawJourneyData mirror.
  function setAmount(body, prize) {
    const major = prize.amount, minor = prize.amount * 100;
    let money = 0, casino = 0, wagering = 0;
    walk(body, (o) => {
      if ('fixedBonusAmount' in o && 'fixedBonusAmount_majorUnits' in o) {
        o.fixedBonusAmount = minor; o.fixedBonusAmount_majorUnits = major; casino++;
      }
      if (Array.isArray(o.currencyAmounts)) {
        for (const c of o.currencyAmounts) if ('amount' in c) { c.amount = major; money++; }
      }
      if (o.bonusAmount && typeof o.bonusAmount === 'object') {
        for (const k of Object.keys(o.bonusAmount)) { o.bonusAmount[k] = major; money++; }
      }
      if (prize.wagering && 'wageringRequirement' in o) { o.wageringRequirement = prize.wagering; wagering++; }
    });
    return { money, casino, wagering };
  }

  // The amount is also spelled out in copy: the transaction title, the
  // notification's money-amount variable, and the node labels the builder
  // prints. Only STRING values are rewritten: a replace over the serialised
  // body turned the number 3000000 into "30 0000" the first time this ran,
  // because the source's own amount is a substring of it.
  function setAmountText(body, sourceName, prize) {
    const m = sourceName.match(/(\d[\d  ]*\d)/);        // "… | 200 000 - …"
    const oldText = m ? m[1] : '';
    if (!oldText) return 0;
    let hits = 0;
    walk(body, (o) => {
      for (const [k, v] of Object.entries(o)) {
        if (typeof v === 'string' && v.includes(oldText)) { o[k] = v.split(oldText).join(prize.amountText); hits++; }
      }
    });
    return hits;
  }

  console.log('%cJBCL gamification prizes — ' + PRIZES.length + ' draft(s)', 'color:#3b82f6;font-weight:bold;font-size:14px');
  const ok = [], fail = [];
  try {
    const sources = {};
    sources.money = await getDraft(MONEY_SOURCE, 'money bonus');
    console.log('    money source  ' + MONEY_SOURCE + ': ' + sources.money.journeyName);
    if (PRIZES.some((p) => p.kind === 'casino')) {
      sources.casino = await getDraft(CASINO_SOURCE, 'casino bonus');
      console.log('    casino source ' + CASINO_SOURCE + ': ' + sources.casino.journeyName);
    }
    const apiTemplate = entryActivity(sources.money);
    if (!apiTemplate || apiTemplate.activityName !== 'external_system_source') {
      throw new Error('the money source does not start with the API node — nothing to clone the webhook entry from.');
    }

    for (const P of PRIZES) {
      console.log('%c' + P.group + '  $' + P.amountText + ' ...', 'color:#3b82f6;font-weight:bold');
      try {
        const src = sources[P.kind];
        const sourceName = String(src.journeyName || '');
        const body = {};
        for (const k of POST_KEYS) if (k in src) body[k] = JSON.parse(JSON.stringify(src[k]));
        body.brand = BRAND;
        body.journeySource = 'UBO';
        body.isArchived = false;
        delete body.duplicatedFromId;
        delete body.duplicatedFromVersion;

        const webhookId = KEEP_WEBHOOK_ID
          ? ((apiTemplate.initializationData || {}).webhookId || newWebhookId())
          : newWebhookId();
        useApiEntry(body, apiTemplate, P.name, webhookId);

        const counts = setAmount(body, P);
        if (P.kind === 'money' && !counts.money) throw new Error('no money bonus amount field in the source — refusing');
        if (P.kind === 'casino' && !counts.casino) throw new Error('no casino bonus amount field in the source — refusing');
        if (P.kind === 'casino' && !counts.wagering) throw new Error('no wageringRequirement in the source — refusing');

        body.journeyName = P.name;
        if (body.rawJourneyData && body.rawJourneyData.infoValues) body.rawJourneyData.infoValues.journeyName = P.name;

        setAmountText(body, sourceName, P);
        const out = JSON.parse(regenIds(JSON.stringify(body)));
        out.journeyName = P.name;
        if (out.rawJourneyData && out.rawJourneyData.infoValues) out.rawJourneyData.infoValues.journeyName = P.name;

        const displayId = await reservePromoDisplayId();
        walk(out, (o) => { if ('promotionDisplayId' in o) o.promotionDisplayId = displayId; });
        out.reservedJourneyId = await reserveJourneyId();

        // Refusals, not warnings: each one was the whole point of a field.
        const s = JSON.stringify(out);
        const entry = entryActivity(out);
        const problems = [];
        if (!entry || entry.activityName !== 'external_system_source') problems.push('the journey does not start at the API node');
        if (!(entry.initializationData || {}).webhookId) problems.push('the API node has no webhookId');
        if (s.includes('"player_id"')) problems.push('a player_id filter survived the entry swap');
        if (s.includes('Copy of')) problems.push('the name still says "Copy of"');
        if (!s.includes(P.amountText)) problems.push('the amount ' + P.amountText + ' is nowhere in the body');
        const amounts = new Set(); const rollovers = new Set();
        walk(out, (o) => {
          if ('fixedBonusAmount_majorUnits' in o) amounts.add(o.fixedBonusAmount_majorUnits);
          if (Array.isArray(o.currencyAmounts)) o.currencyAmounts.forEach((c) => amounts.add(c.amount));
          if ('wageringRequirement' in o) rollovers.add(o.wageringRequirement);
        });
        if (amounts.size && ![...amounts].every((a) => a === P.amount)) problems.push('mixed amounts in the body: ' + [...amounts].join(', '));
        if (P.wagering && [...rollovers].some((r) => r !== P.wagering)) problems.push('mixed rollovers in the body: ' + [...rollovers].join(', '));
        if (problems.length) throw new Error(problems.join('; '));

        const numId = await createAndSaveDraft(out, P.name, H);
        ok.push({ prize: P.group, amount: P.amountText, journey: out.reservedJourneyId, draft: numId, webhook: webhookId });
        console.log('%c    ✓ ' + out.reservedJourneyId + ' (draft ' + numId + ')  webhook ' + webhookId, 'color:#22c55e');
      } catch (e) {
        const msg = String((e && e.message) || e);
        fail.push({ prize: P.group, amount: P.amountText, error: msg });
        console.error('    ✗ ' + P.group + ' $' + P.amountText + ' — ' + msg);
      }
    }
  } catch (e) {
    console.error('%cSTOPPED — ' + ((e && e.message) || e), 'color:#ef4444;font-weight:bold');
  }
  console.log('%cDONE — ' + ok.length + ' created, ' + fail.length + ' failed.', 'color:' + (fail.length ? '#f59e0b' : '#22c55e') + ';font-weight:bold;font-size:14px');
  if (ok.length) console.table(ok);
  if (fail.length) console.table(fail);
  console.log('Every draft points at its source draft\'s promotion content, so they share one card.');
  console.log('Open one, check the API node\'s URL and the amount, then publish — publishing starts it immediately.');
})();
"""

JS_TEMPLATE = inject(JS_TEMPLATE)


def build_js(drafts: list[dict], money_source: str, casino_source: str, keep_webhook: bool) -> str:
    js = JS_TEMPLATE
    js = js.replace("@GENERATED_AT@", datetime.now(LOCAL_TZ).strftime("%Y-%m-%d %H:%M %Z"))
    js = js.replace("@COUNT@", str(len(drafts)))
    js = js.replace("@BASE_URL@", json.dumps(BASE_URL))
    js = js.replace("@BRAND@", json.dumps(BRAND))
    js = js.replace("@MONEY_SOURCE@", json.dumps(money_source))
    js = js.replace("@CASINO_SOURCE@", json.dumps(casino_source))
    js = js.replace("@POST_KEYS@", json.dumps(POST_KEYS))
    js = js.replace("@KEEP_WEBHOOK_ID@", "true" if keep_webhook else "false")
    js = js.replace("@PRIZES@", json.dumps(drafts, ensure_ascii=False))
    return js


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--money-source", required=True, help="draft id of the money bonus journey to clone (numeric, e.g. 693903)")
    p.add_argument("--casino-source", default="", help="draft id of the casino bonus journey to clone (numeric, e.g. 693908)")
    p.add_argument("--only", default="", help=f"comma-separated prize groups to build ({', '.join(GROUPS)}); default all")
    p.add_argument("--keep-webhook-id", action="store_true",
                   help="reuse the source's webhookId instead of minting one per journey (twelve journeys then share one URL)")
    p.add_argument("--name", default="gamif_prizes_jbcl", help="output basename")
    args = p.parse_args()

    groups = [g.strip() for g in args.only.split(",") if g.strip()] or list(GROUPS)
    unknown = [g for g in groups if g not in GROUPS]
    if unknown:
        print(f"\nunknown prize group(s) {unknown}; pick from {', '.join(GROUPS)}.", file=sys.stderr)
        return 1

    drafts, report = prepare(groups)
    for line in report:
        print(line)

    needs_casino = any(d["kind"] == "casino" for d in drafts)
    checks = verify(drafts) + [
        (bool(args.money_source.strip()), "a money bonus source draft was given"),
        (not needs_casino or bool(args.casino_source.strip()),
         "a casino bonus source draft was given (the 1x/3x/5x prizes need one)"),
    ]
    print()
    for good, label in checks:
        print(f"  {'ok  ' if good else 'FAIL'}   {label}")
    if not all(good for good, _ in checks):
        print("\nnothing written.", file=sys.stderr)
        return 1

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUT_DIR / f"{args.name}_console.js"
    path.write_text(build_js(drafts, args.money_source.strip(), args.casino_source.strip(),
                             args.keep_webhook_id), encoding="utf-8")
    print(f"\nConsole script written: {path}  ({len(drafts)} draft(s) in one paste)")
    print("Paste it into the DevTools console on a logged-in JBCL backoffice tab.")
    print("Nothing is published: review each draft, then publish it yourself.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
