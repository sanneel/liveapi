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

THE PRIZE PHOTO
---------------
Each draft gets its own copy of the promotion's two artwork trees (the six
/contents/v1/copy calls the UI makes) and is re-pointed at that copy, so no two
prizes share a card. A copied content file still spells its own media paths
against the tree it came from, so every one is rewritten to this draft's tree
with a fresh cache-buster, and the photo picked for that prize is written into
every image slot the card names: the widget image, the box on each part, and
the spa's header. --no-photos keeps whatever artwork the copy came with.

The slots are discovered from the content itself rather than listed here, so
the money bonus card and the casino bonus card each get what they actually
have.

Nothing is published. Both sources publish immediately when published
(isImmediatelyAfterPublish), so review each draft first.

A source is named either way you see it in the backoffice: the JRN id the
journey list prints, or the numeric draft id in the editor URL. The script asks
for the right endpoint for whichever you gave it, so a journey already running
is as good a source as a draft — and usually a better one, since it is the shape
you last approved.

Usage:
  python gamif_prizes_jbcl_campaign.py --money-source JRN-0-685173 --casino-source JRN-0-685183
  python gamif_prizes_jbcl_campaign.py --money-source 693903 --casino-source 693908
  python gamif_prizes_jbcl_campaign.py --money-source JRN-0-685173 --casino-source JRN-0-685183 \
      --only 5x --name gamif_5x
"""
from __future__ import annotations

import argparse
import json
import re
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

# The promotion's artwork lives in two S3 trees: a "front" (how it is rendered)
# and a "content" (the copy and the images). Duplicating a journey in the UI
# copies both, part by part, with these filters, captured from the run that set
# the $15 000 photo.
CONTENT_COPIES = [
    {"tree": "front", "part": "spa", "files": None},
    {"tree": "front", "part": "widget", "files": None},
    {"tree": "content", "part": "widgetModulor",
     "files": ["manifest.json", "content/content-es.json", "content/content-en.json"]},
    {"tree": "content", "part": "spa",
     "files": ["manifest.json", "content/content-es.json", "content/content-en.json",
               "media/box.png", "media/bonusHeaderImage.png"]},
    {"tree": "content", "part": "widget",
     "files": ["manifest.json", "content/content-es.json", "content/content-en.json",
               "media/box.png", "media/widgetImgKey.png"]},
    {"tree": "content", "part": "cashier",
     "files": ["manifest.json", "content/content-es.json", "content/content-en.json"]},
]

# The parts whose content-<lang>.json name the images. A copied file keeps the
# OLD tree in its own absolute paths, so every one of them is rewritten to the
# new tree before the card can render its own artwork.
CONTENT_PARTS = ["spa", "widget", "widgetModulor", "cashier"]

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

# A source is named either way the operator sees it: the JRN id printed in the
# journey list, or the numeric draft id in the editor URL.
JRN_RE = re.compile(r"^JRN-\d+-\d+$", re.IGNORECASE)
DRAFT_RE = re.compile(r"^\d{4,}$")


def source_kind(value: str) -> str:
    v = (value or "").strip()
    if JRN_RE.match(v):
        return "journey"
    if DRAFT_RE.match(v):
        return "draft"
    return ""


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
  const COPIES = @COPIES@;               // the six content-tree copies the UI makes
  const CONTENT_PARTS = @CONTENT_PARTS@; // the parts whose content-<lang>.json name images
  const WITH_PHOTOS = @WITH_PHOTOS@;     // one file picker per prize
  const CRM_BASE = BASE.replace(/\/journey-builder\/v0$/, '');
  const AWS_BASE = new URL(BASE).origin + '/api/aws-get';

  const decodeJwt = (t) => { try { return JSON.parse(atob(t.split('.')[1].replace(/-/g,'+').replace(/_/g,'/'))); } catch (e) { return null; } };
  const usableAuth = (v) => {
    if (!v || !/^Bearer\s+\S+/i.test(v)) return null;
    const p = decodeJwt(v.replace(/^Bearer\s+/i, ''));
    if (!p || p.typ !== 'Bearer' || p.exp - Date.now()/1000 < 30) return null;
    return 'Bearer ' + v.replace(/^Bearer\s+/i, '');
  };
  async function obtainAuth(quiet) {
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

  let auth = await obtainAuth();
  const H = (ct) => { const h = { accept: 'application/json, text/plain, */*', authorization: auth, 'x-brand': BRAND }; if (ct) h['content-type'] = ct; return h; };

  // The backoffice's token lives about five minutes. Twelve prizes with a file
  // picker each outlive that, and the first run died silently mid-way, so the
  // token is checked before every prize and re-captured while there is still
  // time. Re-capturing needs the page to make a call of its own: clicking
  // anything in the backoffice is enough.
  const secondsLeft = () => {
    const p = decodeJwt(auth.replace(/^Bearer\s+/i, ''));
    return p && p.exp ? Math.round(p.exp - Date.now() / 1000) : 0;
  };
  async function ensureToken() {
    if (secondsLeft() > 90) return;
    if (MANUAL_TOKEN.trim()) {
      console.warn('    the pasted MANUAL_TOKEN has ' + secondsLeft() + 's left; paste a fresh one if calls start failing');
      return;
    }
    console.log('%cToken has ' + secondsLeft() + 's left — click anything in the backoffice to hand over a fresh one.', 'color:#eab308;font-weight:bold');
    auth = await obtainAuth();
    console.log('%cToken refreshed (' + secondsLeft() + 's).', 'color:#22c55e');
  }
@JSON_GUARD_JS@
@DRAFT_SAVE_JS@
  // The capture creates the draft, writes the artwork, then saves. Same order
  // here, so createAndSaveDraft's single step is split in two.
  async function createDraft(body, label) {
    const r = await fetch(BASE + '/journey-drafts', { method: 'POST', headers: H('application/json'), credentials: 'include', body: JSON.stringify(body) });
    const t = await r.text(); if (!r.ok) throw new Error(label + ' draft not created: HTTP ' + r.status + ' ' + t);
    const numId = parseJsonText(t, label + ' draft create', r.status).id;
    if (!numId) throw new Error(label + ' draft create returned no id: ' + t);
    return numId;
  }
  async function saveDraft(numId, body, label) {
    const r = await fetch(BASE + '/journey-drafts/' + numId, { method: 'PUT', headers: H('application/json'), credentials: 'include', body: JSON.stringify(body) });
    if (!r.ok) throw new Error(label + ' draft ' + numId + ' was created but the save failed: HTTP ' + r.status + ' ' + (await r.text()) + '. Delete that half-made draft before rerunning.');
  }
  const newUuid = () => (typeof crypto !== 'undefined' && crypto.randomUUID) ? crypto.randomUUID()
    : 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, (c) => { const r = Math.random()*16|0; return (c === 'x' ? r : (r&0x3)|0x8).toString(16); });
  // One journey per prize means one URL per prize, and the id behind that URL
  // is the backoffice's to give: this is the call its own API node makes. The
  // local generator is only a fallback, and says so, because an id nobody
  // minted may be an id nothing routes to.
  const randomWebhookId = () => {
    const abc = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789';
    let s = ''; for (let i = 0; i < 12; i++) s += abc[Math.floor(Math.random() * abc.length)];
    return s;
  };
  async function newWebhookId() {
    try {
      const r = await fetch(BASE + '/journey-activities/external-system-source/webhook-id', { headers: H(), credentials: 'include' });
      const t = await r.text();
      if (r.ok) {
        const id = parseJsonText(t, 'mint webhook id', r.status).webhookId;
        if (id) return id;
      }
      console.warn('    the backoffice would not mint a webhook id (HTTP ' + r.status + '); using a generated one');
    } catch (e) {
      console.warn('    could not reach the webhook-id endpoint (' + ((e && e.message) || e) + '); using a generated one');
    }
    return randomWebhookId();
  }
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
  // A source is whatever the operator has to hand: the JRN id the journey list
  // shows, or the numeric draft id in the editor URL. Both answer with the same
  // shape, so the rest of the script does not care which it was given.
  async function getSource(id, label) {
    const isJrn = /^JRN-/i.test(String(id).trim());
    const url = BASE + (isJrn ? '/journeys/' : '/journey-drafts/') + String(id).trim();
    const r = await fetch(url, { headers: H(), credentials: 'include' });
    const t = await r.text();
    if (!r.ok) throw new Error(label + ' source ' + id + ' HTTP ' + r.status + ' ' + t.slice(0, 200));
    const d = parseJsonText(t, label + ' source', r.status);
    if (!d || !Array.isArray(d.activities) || !d.activities.length) throw new Error(label + ' source ' + id + ' has no activities[]');
    console.log('    ' + label + ' source ' + id + (isJrn ? ' (' + (d.status || 'journey') + ')' : ' (draft)') + ': ' + d.journeyName);
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

  // Resolves with the file, or with null for "keep the artwork the copy came
  // with". It never hangs: dismissing the dialog fires 'cancel' and not
  // 'change', which is what stopped the first run dead at prize eight, and the
  // backoffice re-rendering used to take the input out of the page with it.
  function pickFile(label) {
    return new Promise((resolve) => {
      const box = document.createElement('div');
      Object.assign(box.style, { position: 'fixed', top: '12px', left: '12px', zIndex: 999999,
        background: '#fff', padding: '10px', border: '3px solid #22c55e', borderRadius: '6px',
        font: '13px system-ui', boxShadow: '0 2px 12px rgba(0,0,0,.3)' });
      const text = document.createElement('div');
      text.textContent = 'Photo for ' + label;
      text.style.marginBottom = '6px';
      const input = document.createElement('input');
      input.type = 'file'; input.accept = 'image/*';
      const skip = document.createElement('button');
      skip.textContent = 'keep the copied artwork';
      skip.style.marginLeft = '8px';
      box.append(text, input, skip);
      document.body.appendChild(box);
      console.log('%cSelect the photo for ' + label + ', or press "keep the copied artwork".', 'color:#eab308;font-weight:bold');
      const alive = setInterval(() => { if (!document.body.contains(box)) document.body.appendChild(box); }, 1000);
      const finish = (file) => { clearInterval(alive); clearTimeout(timer); box.remove(); resolve(file); };
      input.addEventListener('change', () => finish((input.files && input.files[0]) || null));
      input.addEventListener('cancel', () => { console.warn('    picker dismissed for ' + label + ' — keeping the copied artwork'); finish(null); });
      skip.addEventListener('click', () => { console.warn('    skipped ' + label + ' — keeping the copied artwork'); finish(null); });
      const timer = setTimeout(() => { console.warn('    no photo chosen for ' + label + ' in 5 min — keeping the copied artwork'); finish(null); }, 300000);
    });
  }

  // The two ids in a promotion placement: FrontId is how the card renders,
  // ContentId is its copy and images. Both are found in the body rather than
  // assumed, so a source with a different pair still works.
  function placementIds(body) {
    let front = null, content = null;
    walk(body, (o) => { if (o.FrontId && o.ContentId) { front = o.FrontId; content = o.ContentId; } });
    return { front, content };
  }

  async function copyTree(oldId, newId, part, files) {
    const payload = { sourcePath: 'mf/v1/' + oldId + '/' + part, destinationPath: 'mf/v1/' + newId + '/' + part };
    if (files) payload.fileFilters = files;
    const r = await fetch(CRM_BASE + '/contents/v1/copy', { method: 'POST', headers: H('application/json'), credentials: 'include', body: JSON.stringify(payload) });
    if (!r.ok) { console.warn('    copy ' + part + ' skipped: HTTP ' + r.status); return false; }
    return true;
  }
  async function awsGet(path) {
    const r = await fetch(AWS_BASE + '/' + path + '?t=' + Date.now(), { credentials: 'include' });
    if (!r.ok) return null;
    const t = await r.text();
    try { return JSON.parse(t); } catch (e) { return null; }
  }
  async function s3Put(path, data) {
    const r = await fetch(CRM_BASE + '/promo/v2/s3/upload', { method: 'POST', headers: H('application/json'), credentials: 'include', body: JSON.stringify({ path: path, data: data }) });
    if (!r.ok) throw new Error('write ' + path + ' HTTP ' + r.status + ' ' + (await r.text()));
  }
  async function s3PutFile(path, file) {
    const fd = new FormData();
    fd.append(path, file, file.name);
    const r = await fetch(CRM_BASE + '/promo/v2/s3/upload-content', { method: 'POST', headers: H(), credentials: 'include', body: fd });
    if (!r.ok) throw new Error('upload ' + path + ' HTTP ' + r.status + ' ' + (await r.text()));
  }

  // A copied content file still points at the tree it came from, so the card
  // would read its media out of the campaign it was cloned from. Rewrite every
  // self-path to this draft's own tree, refresh the cache-buster, and report
  // the media paths so the prize photo can be written to each of them.
  const MEDIA_RE = /^([0-9a-fA-F-]{36})\/(spa|widget|widgetModulor|cashier)\/media\/([^?]+)(\?.*)?$/;
  async function retreeContent(newContent, stamp) {
    const mediaPaths = new Set();
    let files = 0;
    for (const part of CONTENT_PARTS) {
      for (const lang of ['es', 'en']) {
        const path = 'mf/v1/' + newContent + '/' + part + '/content/content-' + lang + '.json';
        const data = await awsGet(path);
        if (!data || typeof data !== 'object') continue;
        let touched = false;
        for (const [k, v] of Object.entries(data)) {
          if (typeof v !== 'string') continue;
          const m = MEDIA_RE.exec(v);
          if (!m) continue;
          data[k] = newContent + '/' + m[2] + '/media/' + m[3] + '?t=' + stamp;
          mediaPaths.add('mf/v1/' + newContent + '/' + m[2] + '/media/' + m[3]);
          touched = true;
        }
        if (touched) { await s3Put(path, data); files++; }
      }
    }
    return { mediaPaths: [...mediaPaths], files };
  }

  console.log('%cJBCL gamification prizes — ' + PRIZES.length + ' draft(s)', 'color:#3b82f6;font-weight:bold;font-size:14px');
  const ok = [], fail = [];
  try {
    const sources = {};
    if (PRIZES.some((p) => p.kind === 'money')) sources.money = await getSource(MONEY_SOURCE, 'money bonus');
    if (PRIZES.some((p) => p.kind === 'casino')) sources.casino = await getSource(CASINO_SOURCE, 'casino bonus');
    if (!sources.money) sources.money = await getSource(MONEY_SOURCE, 'money bonus');   // the API node is lifted from it
    const apiTemplate = entryActivity(sources.money);
    if (!apiTemplate || apiTemplate.activityName !== 'external_system_source') {
      throw new Error('the money source does not start with the API node — nothing to clone the webhook entry from.');
    }

    for (const P of PRIZES) {
      console.log('%c' + P.group + '  $' + P.amountText + ' ...', 'color:#3b82f6;font-weight:bold');
      try {
        await ensureToken();
        const photo = WITH_PHOTOS ? await pickFile(P.group + ' $' + P.amountText) : null;
        const src = sources[P.kind];
        const sourceName = String(src.journeyName || '');
        const body = {};
        for (const k of POST_KEYS) if (k in src) body[k] = JSON.parse(JSON.stringify(src[k]));
        body.brand = BRAND;
        body.journeySource = 'UBO';
        body.isArchived = false;
        // Cloning a running journey brings the moment it started with it. These
        // start when they are published, so the stale timestamp goes.
        if (body.isImmediatelyAfterPublish) body.startAt = null;
        delete body.duplicatedFromId;
        delete body.duplicatedFromVersion;

        const webhookId = KEEP_WEBHOOK_ID
          ? ((apiTemplate.initializationData || {}).webhookId || await newWebhookId())
          : await newWebhookId();
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

        // Its own artwork tree, or twelve prizes share one card. The pair is
        // cloned from whatever the source points at, then the journey is
        // re-pointed at the clone before it is created.
        const ids = placementIds(out);
        if (!ids.front || !ids.content) throw new Error('no FrontId/ContentId in the promotion placement — refusing');
        const newFront = newUuid(), newContent = newUuid();
        let copied = 0;
        for (const c of COPIES) {
          const from = c.tree === 'front' ? ids.front : ids.content;
          const to = c.tree === 'front' ? newFront : newContent;
          if (await copyTree(from, to, c.part, c.files)) copied++;
        }
        if (!copied) throw new Error('not one content part copied — refusing rather than sharing the source card');
        let outText = JSON.stringify(out).split(ids.front).join(newFront).split(ids.content).join(newContent);
        const wired = JSON.parse(outText);
        if (JSON.stringify(wired).includes(ids.content)) throw new Error('the journey still points at the source content tree');

        const numId = await createDraft(wired, P.name);

        const stamp = Date.now();
        const art = await retreeContent(newContent, stamp);
        if (!art.files) throw new Error('draft ' + numId + ' created but its content tree has no content-<lang>.json to re-point');
        if (photo) {
          if (!art.mediaPaths.length) throw new Error('draft ' + numId + ' created but its card names no image slot to put the photo in');
          for (const mp of art.mediaPaths) await s3PutFile(mp, photo);
          console.log('    photo -> ' + art.mediaPaths.length + ' slot(s): ' + art.mediaPaths.map((m) => m.split('/').slice(-2).join('/')).join(', '));
        }
        await saveDraft(numId, wired, P.name);

        ok.push({ prize: P.group, amount: P.amountText, journey: wired.reservedJourneyId, draft: numId,
                  webhook: webhookId, photo: photo ? photo.name : 'kept the source card', slots: art.mediaPaths.length });
        console.log('%c    ✓ ' + wired.reservedJourneyId + ' (draft ' + numId + ')  webhook ' + webhookId, 'color:#22c55e');
      } catch (e) {
        const msg = String((e && e.message) || e);
        fail.push({ prize: P.group, amount: P.amountText, error: msg });
        console.error('    ✗ ' + P.group + ' $' + P.amountText + ' — ' + msg);
        if (/HTTP 401|HTTP 403|No token in/.test(msg)) {
          console.error('%cThe token was refused or never arrived. Stopping rather than half-making more drafts.', 'color:#ef4444;font-weight:bold');
          break;
        }
      }
    }
  } catch (e) {
    console.error('%cSTOPPED — ' + ((e && e.message) || e), 'color:#ef4444;font-weight:bold');
  }
  console.log('%cDONE — ' + ok.length + ' created, ' + (PRIZES.length - ok.length) + ' not.', 'color:' + (ok.length === PRIZES.length ? '#22c55e' : '#f59e0b') + ';font-weight:bold;font-size:14px');
  if (ok.length) console.table(ok);
  if (fail.length) console.table(fail);
  const done = new Set(ok.map((o) => o.prize + o.amount));
  const left = [...new Set(PRIZES.filter((p) => !done.has(p.group + p.amountText)).map((p) => p.group))];
  if (left.length) {
    console.log('%cNot created: ' + left.join(', ') + '. Rerun the generator for just those:', 'color:#eab308;font-weight:bold');
    console.log('    python gamif_prizes_jbcl_campaign.py --money-source ' + MONEY_SOURCE + ' --casino-source ' + CASINO_SOURCE + ' --only ' + left.join(','));
  }
  console.log('Each draft has its own promotion content tree, carrying its own prize photo.');
  console.log('Open one, check the API node\'s URL and the amount, then publish — publishing starts it immediately.');
})();
"""

JS_TEMPLATE = inject(JS_TEMPLATE)


def build_js(drafts: list[dict], money_source: str, casino_source: str, keep_webhook: bool,
              with_photos: bool = True) -> str:
    js = JS_TEMPLATE
    js = js.replace("@GENERATED_AT@", datetime.now(LOCAL_TZ).strftime("%Y-%m-%d %H:%M %Z"))
    js = js.replace("@COUNT@", str(len(drafts)))
    js = js.replace("@BASE_URL@", json.dumps(BASE_URL))
    js = js.replace("@BRAND@", json.dumps(BRAND))
    js = js.replace("@MONEY_SOURCE@", json.dumps(money_source))
    js = js.replace("@CASINO_SOURCE@", json.dumps(casino_source))
    js = js.replace("@POST_KEYS@", json.dumps(POST_KEYS))
    js = js.replace("@KEEP_WEBHOOK_ID@", "true" if keep_webhook else "false")
    js = js.replace("@COPIES@", json.dumps(CONTENT_COPIES, ensure_ascii=False))
    js = js.replace("@CONTENT_PARTS@", json.dumps(CONTENT_PARTS))
    js = js.replace("@WITH_PHOTOS@", "true" if with_photos else "false")
    js = js.replace("@PRIZES@", json.dumps(drafts, ensure_ascii=False))
    return js


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--money-source", required=True,
                   help="the money bonus journey to clone: its JRN id (JRN-0-685173) or its draft id (693903)")
    p.add_argument("--casino-source", default="",
                   help="the casino bonus journey to clone: its JRN id (JRN-0-685183) or its draft id (693908)")
    p.add_argument("--only", default="", help=f"comma-separated prize groups to build ({', '.join(GROUPS)}); default all")
    p.add_argument("--keep-webhook-id", action="store_true",
                   help="reuse the source's webhookId instead of minting one per journey (twelve journeys then share one URL)")
    p.add_argument("--no-photos", action="store_true",
                   help="skip the per-prize file pickers and keep the artwork the copied card came with")
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
    money_kind = source_kind(args.money_source)
    casino_kind = source_kind(args.casino_source)
    checks = verify(drafts) + [
        (bool(money_kind), f"the money source {args.money_source.strip()!r} is a JRN id or a draft id ({money_kind or 'neither'})"),
        (not needs_casino or bool(casino_kind),
         f"the casino source {args.casino_source.strip()!r} is a JRN id or a draft id ({casino_kind or 'neither'})"
         " — the 1x/3x/5x prizes need one"),
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
                             args.keep_webhook_id, not args.no_photos), encoding="utf-8")
    print(f"\nConsole script written: {path}  ({len(drafts)} draft(s) in one paste)")
    print("Paste it into the DevTools console on a logged-in JBCL backoffice tab.")
    print("Nothing is published: review each draft, then publish it yourself.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
