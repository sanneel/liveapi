#!/usr/bin/env python3
"""Build a NEW comms journey draft from an existing one, with this run's content.

The other generators in this folder build a journey from a template captured in
this repo. This one takes a live journey as its template instead: the marketing
team already has a comms journey of the right shape in the backoffice, and each
week it needs new copy, new photos and a new email. The source journey is read
and never written — the run ends in a brand-new draft.

What the emitted console script does, in order:
  1. captures the bearer token from the page's own requests (the backoffice
     never gives it to the server, so nothing here can run server-side),
  2. reads the SOURCE draft and works out where every field currently lives,
  3. prints the whole plan and stops if DRY_RUN is left on,
  4. opens a file picker per photo slot — NC icon, pop-up background, and the
     email's top and CTA images — uploading each into the media library the
     backoffice's own picker uses,
  5. creates, saves and publishes the marketing email from the captured shell
     with this run's subject, pre-header, body and link,
  6. reserves a fresh journey id, regenerates every activity id, drops the
     source's lineage and server-minted ids, and POSTs a new draft,
  7. reads the new draft back and proves that nothing in it is still the
     source's: not a word of copy, not a link, not a photo, not the email.

Why it writes the way it does: a journey lives twice — the compiled
``activities[]`` and the ``rawJourneyData`` editor mirror — and disagreement
between them is a blank canvas in the builder, so every write lands in both.
Copy goes in by path rather than by string swap, because a copied draft
routinely holds the same string in its English and Spanish variable and a
whole-body replace could not then place different EN and ES copy. The link
still goes in by swap: that one *should* reach every channel.

Usage:
  python comms_copy_update.py --source-draft-id 690315 \
      --name "JBCL | CS | Champions | comms" \
      --link "https://jugabet.cl/services/promo/offers/randomizer/cl-round-1?%$utm_tags%" \
      --spec spec.txt

  # copy straight from the pasted sheet block:
  pbpaste | python comms_copy_update.py --source-draft-id 690315 --name "..." \
      --link "..." --spec -

Channels default to whatever the sheet ticked TRUE. --channels overrides it.
Email is built unless --no-email; it needs a subject, a pre-header and a body,
which come from the sheet unless given on the command line.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from datetime import datetime
from pathlib import Path

from create_journeys import BRAND, LOCAL_TZ
from spec_parser import parse_spec
from email_content import (
    EMAIL_CTA_IMAGE_TOKEN,
    EMAIL_TOP_IMAGE_TOKEN,
    body_html_from_text,
    prepare_comms_email_content,
)

HERE = Path(__file__).resolve().parent
OUT_DIR = HERE / "console_scripts"

# The media-library folder the backoffice's own photo picker uploads into.
DEFAULT_FOLDER_ID = "c5c7c614-5169-4346-b90b-8225836a1c63"

# A captured comms draft that is known to POST. Its top-level keys are the shape
# a create accepts, so anything the GET adds on top of them (the numeric id,
# version, status, timestamps) is the source draft's own identity and is dropped.
POSTABLE_SHAPE_PATH = HERE / "templates" / "casino" / "gow_comms.json"


def postable_keys() -> list[str]:
    body = json.loads(POSTABLE_SHAPE_PATH.read_text(encoding="utf-8"))
    # the lineage markers are stripped, not carried
    return sorted(k for k in body if k not in ("duplicatedFromId", "duplicatedFromVersion"))

CHANNELS = ("popup", "nc", "sms", "email")

# Every photo slot the script can fill, and which channel has to be in play for
# it to be asked for.
PHOTO_SLOTS = [
    ("nc", "nc.icon", "NC ICON"),
    ("popup", "popup.background_image_src", "POP-UP BACKGROUND"),
    ("email", "email.top_image", "EMAIL TOP IMAGE"),
    ("email", "email.cta_image", "EMAIL CTA IMAGE"),
]

GSM7 = set(
    "@£$¥èéùìòÇ\nØø\rÅåΔ_ΦΓΛΩΠΨΣΘΞÆæßÉ !\"#¤%&'()*+,-./0123456789:;<=>?"
    "¡ABCDEFGHIJKLMNOPQRSTUVWXYZÄÖÑÜ§¿abcdefghijklmnopqrstuvwxyzäöñüà"
    "\f^{}\\[~]|€"
)


def u16(s: str) -> int:
    """Length in UTF-16 code units — what the backoffice's counters use."""
    return sum(2 if ord(c) > 0xFFFF else 1 for c in s)


def build_copy(spec, link: str, channels: list[str]) -> dict:
    """The per-channel copy block, with the promo link already substituted."""
    copy: dict = {}
    if "popup" in channels:
        c = spec.popup
        copy["popup"] = {
            "title_en": c.title_en, "title_es": c.title_es,
            "desc_en": c.desc_en, "desc_es": c.desc_es,
            "caption_en": c.caption_en, "caption_es": c.caption_es,
        }
    if "nc" in channels:
        c = spec.nc
        copy["nc"] = {
            "title_en": c.title_en, "title_es": c.title_es,
            "desc_en": c.desc_en, "desc_es": c.desc_es,
            "caption_en": c.caption_en, "caption_es": c.caption_es,
            "link_en": link, "link_es": link,
        }
    if "sms" in channels:
        copy["sms"] = {"text_en": spec.sms.text_en, "text_es": spec.sms.text_es}
    return copy


def check_copy(copy: dict, errors: list[str]) -> None:
    """The checks that can be made without the draft — length, charset, leftovers.

    Everything here has shipped wrong at least once, which is why it refuses
    rather than warns.
    """
    for role, fields in copy.items():
        for field, value in fields.items():
            if field.startswith("link"):
                continue
            if not str(value).strip():
                errors.append(f"{role}.{field} is empty — the copied campaign's copy would ship.")
                continue
            if re.search(r"#(REF|VALUE|NAME|DIV/0)!", str(value)):
                errors.append(f"{role}.{field} carries a spreadsheet error: {value!r}")
            if "CLP" in str(value):
                errors.append(f"{role}.{field} says CLP — the sheet's amounts ship without a currency code.")
    sms = copy.get("sms") or {}
    for lang in ("en", "es"):
        text = sms.get(f"text_{lang}") or ""
        if not text:
            continue
        if not text.startswith("JugaBet | "):
            errors.append(f"sms.text_{lang} does not start with 'JugaBet | '.")
        bad = sorted({c for c in text if c not in GSM7})
        if bad:
            errors.append(
                f"sms.text_{lang} has characters outside GSM-7 ({''.join(bad)}) — "
                "the message silently becomes UCS-2 and costs double per segment.")
        if u16(text) > 160:
            errors.append(f"sms.text_{lang} is {u16(text)} units, over the 160 of one segment.")


def build_email(args, spec, link: str) -> dict | None:
    if args.no_email:
        return None
    subject = (args.email_subject or spec.email.subject_es).strip()
    preheader = (args.email_preheader or spec.email.preheader_es).strip()
    cta = (args.email_cta or spec.email.button_es or "").strip()
    if args.email_body_html:
        body = args.email_body_html
    else:
        text = (args.email_body_text or spec.email.desc_es or "").strip()
        body = body_html_from_text(text) if text else ""
    return prepare_comms_email_content(
        name=args.email_name or f"{BRAND} CS - {args.name.split('|')[-2].strip() if '|' in args.name else args.name} "
                                f"{datetime.now(LOCAL_TZ):%d.%m}",
        subject_es=subject, preheader_es=preheader, body_html=body, link=link, cta_text=cta,
    )


JS_TEMPLATE = r"""// @JOURNEY_NAME@ — comms copy, artwork and email. Generated @GENERATED_AT@.
//
// Paste into the DevTools console on a logged-in backoffice tab.
//
// WHAT IT DOES
//   Reads journey draft @SOURCE_DRAFT_ID@ as its template and CREATES A NEW
//   DRAFT from it: this run's copy for the channels the sheet ticked, a photo
//   you pick per artwork slot, and a freshly created and published marketing
//   email the new draft's email activity points at. The source journey is only
//   read — it is never written, so rerunning this is always safe. For another
//   date: change the copy and rerun; you get another new draft.
//
// HOW IT WRITES
//   A journey lives TWICE — compiled `activities[]` and the `rawJourneyData`
//   editor mirror — and disagreement between them is a blank canvas in the
//   builder, so every write below lands in both. Copy goes in BY PATH, because
//   the source draft routinely holds one string in its English and Spanish
//   variable and a whole-body replace could not then place different EN and ES
//   copy. The link goes in by whole-body swap: it SHOULD reach every channel.
//   Field locations come from journey_composer.py.
//
//   Before the POST the body is made standalone: a fresh reservedJourneyId, a
//   fresh uuid for every activity (shared activityIds collide), no
//   duplicatedFrom* lineage, no server-minted promotionDisplayId, no stale
//   campaign-connector campaignId, and only the top-level keys a POSTable
//   comms draft carries.
//
// IT REFUSES RATHER THAN WARNS
//   The generator already checked the copy — lengths in UTF-16 units, GSM-7 on
//   the SMS, the "JugaBet |" prefix, no CLP, no #REF!/#VALUE!. This script
//   re-checks what only the live draft can tell it: every node present exactly
//   once, every field matched to a captured variable, no ambiguous swap, every
//   photo slot filled, the email published before the draft points at it, the
//   name in all three of its homes, every activity id freshly minted, and a
//   readback proving the new draft shares no content with the source.
(async () => {
  'use strict';
  const DRY_RUN = true;               // THE SWITCH. true = preview only. false = writes.
  const SOURCE_DRAFT_ID = @SOURCE_DRAFT_ID@;   // read only; never written
  const BRAND = @BRAND@;
  const JOURNEY_NAME = @JOURNEY_NAME_JSON@;

  // Leaving a photo slot on the previous campaign's artwork is how the old
  // promotion's picture ships under a new name. Set this true only when that
  // is deliberate — the slot's picker is then skipped and listed at the end.
  const KEEP_INHERITED_ASSETS = false;
  const ALLOW_SHARED_COPY_REWRITE = true;
  // Which language's text a place holding one message for both should get.
  const SMS_DEFAULT_LANG = @SMS_DEFAULT_LANG@;

  const LINK = @LINK@;
  const COPY = @COPY@;
  const ROLES = @ROLES@;                    // only the channels the sheet ticked TRUE
  const FOLDER_ID = @FOLDER_ID@;
  const EMAIL_NAME = @EMAIL_NAME@;
  const EMAIL_CONTENT = @EMAIL_CONTENT@;   // null when the email is left alone
  const KEEP_KEYS = @KEEP_KEYS@;          // the top-level shape a create accepts
  const TOP_IMAGE_TOKEN = @TOK_TOP_IMAGE@;
  const CTA_IMAGE_TOKEN = @TOK_CTA_IMAGE@;

  const HOST = "https://pmi.rea-backoffice.gr8.tech";
  // journey-drafts for an EXISTING draft answers under /api/core; the create
  // path other generators use is /api/ubo. The real base is sniffed off the
  // page's own requests below, so this only matters if nothing is sniffed.
  const CRM_FALLBACK = HOST + '/api/core/api/v0/crm';
  let CRM_BASE = CRM_FALLBACK, sniffedCrm = null;
  const takeUrl = (u) => { if (sniffedCrm) return;
    const m = String(u || '').match(/^(https?:\/\/[^\/]+\/api\/[^\/]+\/api\/v\d+\/crm)\//);
    if (m) sniffedCrm = m[1]; };
  const decodeJwt = (t) => { try { return JSON.parse(atob(t.split('.')[1].replace(/-/g,'+').replace(/_/g,'/'))); } catch (e) { return null; } };
  const usableAuth = (v) => { if (!v || !/^Bearer\s+\S+/i.test(v)) return null;
    const p = decodeJwt(v.replace(/^Bearer\s+/i, ''));
    if (!p || p.typ !== 'Bearer' || p.exp - Date.now()/1000 < 30) return null;
    return 'Bearer ' + v.replace(/^Bearer\s+/i, ''); };
  const auth = await new Promise((resolve, reject) => {
    let done = false; const of = window.fetch, oh = XMLHttpRequest.prototype.setRequestHeader,
          oo = XMLHttpRequest.prototype.open;
    const clean = () => { window.fetch = of; XMLHttpRequest.prototype.setRequestHeader = oh;
                          XMLHttpRequest.prototype.open = oo; };
    const take = (v) => { const a = usableAuth(v); if (a && !done) { done = true; clean(); clearTimeout(t);
      console.log('%cToken captured.', 'color:#22c55e'); resolve(a); } };
    window.fetch = function (i, n) {
      try { takeUrl((i && i.url) || i); } catch (e) {}
      try { const h = (n && n.headers) || (i && i.headers); if (h) { if (typeof h.get === 'function') take(h.get('authorization')); else take(h.authorization || h.Authorization); } } catch (e) {}
      return of.apply(this, arguments); };
    XMLHttpRequest.prototype.open = function (m2, u2) { try { takeUrl(u2); } catch (e) {} return oo.apply(this, arguments); };
    XMLHttpRequest.prototype.setRequestHeader = function (k, v) { try { if (/^authorization$/i.test(k)) take(v); } catch (e) {} return oh.apply(this, arguments); };
    const t = setTimeout(() => { if (!done) { done = true; clean(); reject(new Error('No token in 3 min. Click around the UI and rerun.')); } }, 180000);
    console.log('%cWaiting for a token — click anything in the backoffice UI.', 'color:#eab308');
  });
  if (sniffedCrm) { CRM_BASE = sniffedCrm; console.log('CRM base sniffed: ' + CRM_BASE); }
  const CONTENT_BASE = CRM_BASE + '/content-studio/v0/eb-backoffice/email/contents';

  // Say it before anything else, so a preview run is never mistaken for a failed one.
  console.log(DRY_RUN
    ? '%cPREVIEW ONLY — this run writes NOTHING, uploads NOTHING and creates NO email. Set DRY_RUN = false to apply.'
    : '%cWRITE MODE — this run will create a new draft from ' + SOURCE_DRAFT_ID + '.',
    'color:' + (DRY_RUN ? '#eab308' : '#ef4444') + ';font-weight:bold;font-size:14px');

  // journey-drafts take x-brand (singular). The drafts LIST wants x-brands;
  // content-studio and media-library take none. Wrong one = 403 with an empty body.
  async function send(method, url, body) {
    const h = { accept: 'application/json, text/plain, */*', authorization: auth, 'x-brand': BRAND };
    if (body !== undefined) h['content-type'] = 'application/json';
    const r = await fetch(url, { method, headers: h, credentials: 'include',
                                 body: body === undefined ? undefined : JSON.stringify(body) });
    const t = await r.text();
    const where = method + ' ' + (url.split('/crm/')[1] || url);
    if (!r.ok) throw new Error(where + ' HTTP ' + r.status + ' ' + t.slice(0, 300));
    if (/^\s*<(!doctype|html)/i.test(t)) throw new Error(where + ' returned the backoffice HTML page, not JSON — the URL is not an API route.');
    try { return JSON.parse(t); } catch (e) { if (!t.trim()) return {}; throw new Error(where + ' non-JSON body: ' + t.slice(0, 160)); }
  }
  const u16 = (s) => Array.from(String(s)).reduce((n, c) => n + (c.codePointAt(0) > 0xFFFF ? 2 : 1), 0);
  const fail = (m) => { throw new Error(m); };

  // Where a string actually lives inside one node, and how to replace it there.
  // The SMS node's shape is not knowable in advance — writing only the paths a
  // generator happens to know is how the source journey's message survived a
  // run that reported success.
  function exactPaths(root, needle) {
    const out = [];
    const walk = (val, p) => {
      if (typeof val === 'string') { if (val === needle) out.push(p || '(root)'); return; }
      if (!val || typeof val !== 'object') return;
      if (Array.isArray(val)) { val.forEach((v, i) => walk(v, p + '[' + i + ']')); return; }
      for (const k of Object.keys(val)) walk(val[k], p ? p + '.' + k : k);
    };
    walk(root, '');
    return out;
  }
  function replaceExact(root, oldV, newV) {
    let n = 0;
    const walk = (parent, key, val) => {
      if (typeof val === 'string') { if (val === oldV) { parent[key] = newV; n++; } return; }
      if (!val || typeof val !== 'object') return;
      if (Array.isArray(val)) { val.forEach((v, i) => walk(val, i, v)); return; }
      for (const k of Object.keys(val)) walk(val, k, val[k]);
    };
    const box = { r: root }; walk(box, 'r', root);
    return n;
  }
"""

JS_TEMPLATE += r"""
  // ── the browse button ───────────────────────────────────────────────────
  // A real <input type="file"> pinned to the top-left of the page: the console
  // cannot open a file dialog on its own, and a click has to come from the
  // operator for the browser to allow it.
  function pickFile(label) {
    return new Promise((resolve, reject) => {
      const wrap = document.createElement('div');
      Object.assign(wrap.style, { position: 'fixed', top: '12px', left: '12px', zIndex: 999999,
        background: '#fff', color: '#111', padding: '10px 12px', border: '3px solid #22c55e',
        borderRadius: '8px', font: '13px/1.4 system-ui, sans-serif',
        boxShadow: '0 6px 24px rgba(0,0,0,.35)' });
      const title = document.createElement('div');
      title.textContent = 'Choose the ' + label + ' photo';
      title.style.fontWeight = '700';
      title.style.marginBottom = '6px';
      const input = document.createElement('input');
      input.type = 'file';
      input.accept = 'image/*';
      wrap.appendChild(title); wrap.appendChild(input);
      document.body.appendChild(wrap);
      console.log('%cBrowse for the ' + label + ' photo — the picker is at the top-left of the page.',
                  'color:#eab308;font-weight:bold');
      input.addEventListener('change', () => {
        const f = input.files && input.files[0];
        wrap.remove();
        if (!f) { reject(new Error('No file chosen for ' + label + '.')); return; }
        console.log('  [' + label + '] ' + f.name + ' (' + f.size + ' bytes)');
        resolve(f);
      });
    });
  }

  function imageDims(file) {
    return new Promise((resolve, reject) => {
      const url = URL.createObjectURL(file);
      const img = new Image();
      img.onload = () => { URL.revokeObjectURL(url); resolve({ width: img.naturalWidth, height: img.naturalHeight }); };
      img.onerror = () => { URL.revokeObjectURL(url); reject(new Error('Could not read image dimensions for ' + file.name)); };
      img.src = url;
    });
  }

  const mediaHeaders = () => ({ accept: 'application/json, text/plain, */*', authorization: auth, 'x-brand': BRAND });

  // Uploads into the same media-library folder and endpoint the backoffice's
  // own photo picker uses, and returns the asset — absolute_link for the
  // on-site channels, relative_link for the email (whose body references
  // images as https://{{cdn_hostname}}<relative_link>).
  async function uploadAsset(file, label) {
    const dims = await imageDims(file);
    const baseName = (file.name || 'photo').replace(/\.[^./]+$/, '');
    const url = CRM_BASE + '/media-library/v0/folder/' + FOLDER_ID + '/upload/'
      + encodeURIComponent(baseName) + '.png?height=' + dims.height + '&width=' + dims.width;
    const fd = new FormData();
    fd.append('file', file, file.name);
    const r = await fetch(url, { method: 'PUT', headers: mediaHeaders(), credentials: 'include', body: fd });
    const resp = await r.text();
    if (!r.ok) throw new Error(label + ' upload failed: HTTP ' + r.status + ' ' + resp);
    const asset = JSON.parse(resp);
    if (!asset || !asset.absolute_link) throw new Error(label + ' upload returned no link: ' + resp.slice(0, 200));
    console.log('  [' + label + '] uploaded ' + asset.id + ' -> ' + asset.absolute_link);

    const thumbFd = new FormData();
    thumbFd.append('file', file, file.name);
    const tr = await fetch(CRM_BASE + '/media-library/v0/asset/thumb/' + asset.id + '.png',
                           { method: 'PUT', headers: mediaHeaders(), credentials: 'include', body: thumbFd });
    if (!tr.ok) console.warn('  [' + label + '] thumbnail upload failed (non-fatal): HTTP ' + tr.status);
    return asset;
  }

  async function pickAndUpload(label) {
    return await uploadAsset(await pickFile(label), label);
  }

  // A new draft needs an identifier the backoffice minted for it; reusing the
  // source's is "the journey with the same identifier already exists".
  async function reserveId() {
    const r = await fetch(CRM_BASE + '/journey-builder/v0/journeys/identifier', { method: 'POST',
      headers: { accept: 'application/json, text/plain, */*', authorization: auth, 'x-brand': BRAND,
                 'content-type': 'application/x-www-form-urlencoded' }, credentials: 'include' });
    const raw = (await r.text()).trim();
    let id = raw.replace(/^"+|"+$/g, '');
    try { const d = JSON.parse(raw);
          if (typeof d === 'string') id = d.trim();
          else if (d && typeof d === 'object') id = String(d.identifier || d.journeyId || d.id || d.value || '').trim();
    } catch (e) {}
    if (!r.ok || !id.startsWith('JRN-')) throw new Error('Reserve failed: HTTP ' + r.status + ' ' + raw.slice(0, 200));
    return id;
  }

  const newUuid = () => (typeof crypto !== 'undefined' && crypto.randomUUID) ? crypto.randomUUID()
    : 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, (c) => {
        const r = Math.random() * 16 | 0; return (c === 'x' ? r : (r & 0x3) | 0x8).toString(16); });
  const UUID_RE = /"(?:activityId|journeyActivityId|id)"\s*:\s*"([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})"/g;
  // Text-level, not per-field: the same uuid is also an OBJECT KEY in
  // rawJourneyData.activitiesConfiguration and an endpoint in every edge, and
  // a draft whose ids only half-changed points its edges at the source's nodes.
  function regenIds(body) {
    let txt = JSON.stringify(body);
    const old = new Set(); let m; UUID_RE.lastIndex = 0;
    while ((m = UUID_RE.exec(txt)) !== null) old.add(m[1]);
    for (const o of old) txt = txt.split(o).join(newUuid());
    return { body: JSON.parse(txt), count: old.size };
  }

  // create -> save -> publish. The draft is only pointed at the content after
  // the publish succeeds: an unpublished content id on a live email activity
  // is an email that renders as nothing.
  async function publishEmail(content) {
    let r = await fetch(CONTENT_BASE, { method: 'POST',
      headers: { accept: 'application/json, text/plain, */*', authorization: auth, 'x-brand': BRAND, 'content-type': 'application/json' },
      credentials: 'include', body: JSON.stringify(content) });
    let resp = await r.text();
    if (!r.ok) throw new Error('Email content create failed: HTTP ' + r.status + ' ' + resp.slice(0, 300));
    const cseId = (JSON.parse(resp) || {}).id;
    if (!cseId) throw new Error('Email content create returned no id: ' + resp.slice(0, 200));
    console.log('  created email content ' + cseId);

    r = await fetch(CONTENT_BASE + '/' + cseId, { method: 'POST',
      headers: { accept: 'application/json, text/plain, */*', authorization: auth, 'x-brand': BRAND, 'content-type': 'application/json' },
      credentials: 'include', body: JSON.stringify(content) });
    if (!r.ok) throw new Error('Email content save failed: HTTP ' + r.status + ' ' + (await r.text()).slice(0, 300));

    r = await fetch(CONTENT_BASE + '/' + cseId + '/publish', { method: 'PATCH',
      headers: { accept: 'application/json, text/plain, */*', authorization: auth, 'x-brand': BRAND, 'content-type': 'application/json' },
      credentials: 'include', body: '{}' });
    if (!r.ok) throw new Error('Email content publish failed: HTTP ' + r.status + ' ' + (await r.text()).slice(0, 300));
    console.log('  published email content ' + cseId);
    return cseId;
  }
"""

JS_TEMPLATE += r"""
  // ── the draft ────────────────────────────────────────────────────────────
  if (!JOURNEY_NAME.trim()) fail('JOURNEY_NAME is empty.');
  const draft = await send('GET', CRM_BASE + '/journey-builder/v0/journey-drafts/' + SOURCE_DRAFT_ID);
  const acts = draft.activities;
  if (!Array.isArray(acts) || !acts.length) fail('draft ' + SOURCE_DRAFT_ID + ' has no activities[] — not a journey draft body.');
  if (!draft.rawJourneyData) fail('draft ' + SOURCE_DRAFT_ID + ' has no rawJourneyData mirror. A draft built from it would open as a blank canvas.');
  const akey = (a) => { const n = a.activityName || '?'; const i = a.initializationData || {};
                        return (n === 'notification_center' && 'contract' in i) ? n + '#contract' + i.contract : n; };
  const want = { nc: 'notification_center#contract1', popup: 'notification_center#contract5',
                 sms: 'dextra_sms', email: 'dextra_email' };
  const found = {};
  for (const role of ROLES) {
    const hits = acts.filter((a) => akey(a) === want[role]);
    if (hits.length !== 1) fail('expected exactly one ' + role + ' node (' + want[role] + ') in source draft ' + SOURCE_DRAFT_ID
      + ', found ' + hits.length + '. Node kinds present: ' + [...new Set(acts.map(akey))].join(', '));
    found[role] = hits[0];
  }
  console.log('%csource draft ' + SOURCE_DRAFT_ID + ' — ' + acts.length + ' activities; found ' + ROLES.join(', '),
              'color:#22c55e');

  // ── locate each field's CURRENT value ────────────────────────────────────
  const STEM = { title: 'title', desc: 'des', caption: 'caption', link: 'link' };
  // The language is a SUFFIX, not a substring: "des-en" contains "es", so a
  // naive includes() test puts Spanish copy in the English variable.
  const langOf = (name) => { const m = String(name).toLowerCase().match(/(?:^|[-_])(en|es)$/); return m ? m[1] : null; };
  const plan = [];
  const varsOf = (node) => ((node.initializationData || {}).objectForSend || {}).variables || [];
  // A card's variables are of two kinds. Some hold copy ("title-es" -> the
  // Spanish headline); the rest are the template's own slots, holding a
  // reference the platform resolves from the first kind ("title" -> "%title_es%",
  // "buttons_1_link" -> "%link%?%$utm_tags%"). A slot reference is structure, not
  // content: it is identical in every campaign, and overwriting one breaks the
  // card. Anything left after its %...% runs are removed is a real value.
  const isSlotRef = (v) => typeof v === 'string' && v.indexOf('%') > -1
    && !/[A-Za-z0-9]/.test(v.replace(/%[^%]*%/g, ''));
  function currentVar(node, stem, lang) {
    const hits = varsOf(node).filter((v) => { const n = (v.name || '').toLowerCase();
                                              return n.indexOf(stem) > -1 && langOf(n) === lang; });
    return hits.length ? hits : null;
  }
  const writes = [];
  for (const role of ROLES) {
    if (role === 'sms' || role === 'email') continue;
    for (const field of Object.keys(COPY[role] || {})) {
      const m = field.match(/^(title|desc|caption)_(en|es)$/); if (!m) continue;
      const hits = currentVar(found[role], STEM[m[1]], m[2]);
      if (!hits) fail(role + ': no captured variable matches ' + field
        + '. Variables present: ' + varsOf(found[role]).map((v) => v.name).join(', ')
        + '. A field with no match never writes, and the copied campaign\'s value ships.');
      for (const h of hits) writes.push({ role, field, varName: h.name, stem: STEM[m[1]], lang: m[2],
                                          oldValue: String(h.value == null ? '' : h.value),
                                          newValue: COPY[role][field] });
    }
    // the link is shared by every channel, so it goes through the swap below
    for (const lang of ['en', 'es']) {
      const v = (COPY[role] || {})['link_' + lang]; if (v == null) continue;
      const hits = currentVar(found[role], STEM.link, lang);
      if (!hits) continue;                     // not every node carries a link
      for (const h of hits) plan.push({ label: role + '.link_' + lang + ' [' + h.name + ']',
                                        role: role, varName: h.name,
                                        oldValue: String(h.value == null ? '' : h.value), newValue: v });
    }
  }
  // The SMS is written BY PATH too, per language. These are the holders
  // journey_composer.py knows:
  //   rawValues.messageText                      (the EN default)
  //   rawValues.localizedMessageTexts.{en|es}    (dict form, .messageText or a bare string)
  //   smsSettings.localizedMessageTexts[]        (list form, matched on languageCode)
  const smsWrites = [];
  let smsAmbiguous = false;
  if (ROLES.indexOf('sms') > -1) {
    for (const lang of ['en', 'es']) {
      const v = (COPY.sms || {})['text_' + lang];
      if (v == null) continue;
      const olds = new Set();
      for (const holder of [(found.sms.initializationData || {}).rawValues,
                            (found.sms.initializationData || {}).smsSettings]) {
        if (!holder || typeof holder !== 'object') continue;
        if (lang === 'en' && typeof holder.messageText === 'string') olds.add(holder.messageText);
        const loc = holder.localizedMessageTexts;
        if (loc && !Array.isArray(loc) && typeof loc === 'object') {
          for (const k of Object.keys(loc)) if (k.toLowerCase() === lang) {
            const x = loc[k]; olds.add(typeof x === 'string' ? x : (x && x.messageText)); }
        } else if (Array.isArray(loc)) {
          for (const it of loc) if (it && String(it.languageCode || '').toLowerCase() === lang) olds.add(it.messageText);
        }
      }
      const real = [...olds].filter((x) => typeof x === 'string' && x.trim());
      if (!real.length) fail('sms: no captured message text found for ' + lang
        + '. rawValues/smsSettings keys: ' + Object.keys(found.sms.initializationData || {}).join(', '));
      smsWrites.push({ lang, newValue: v, oldValue: real[0],
                       paths: exactPaths(found.sms, real[0]) });
    }
    // One string serving both languages cannot be split by an exact-match
    // replace, so the per-language paths below are all the separation there is.
    const olds = smsWrites.map((w) => w.oldValue);
    smsAmbiguous = olds.length > 1 && olds[0] === olds[1];
  }
  // The pop-up holds its promo link in ONE language-independent `link` (its
  // per-language slots read "%link%?%$utm_tags%"), so the link_en/link_es swap
  // above never reaches it — the pop-up shipped the source journey's link.
  // Same for `deeplink`, which both cards carry once.
  const LINK_NAMES = ['link', 'deeplink'];
  const commonWrites = [];
  for (const role of ROLES) {
    if (role === 'sms' || role === 'email') continue;
    for (const v of varsOf(found[role])) {
      if (LINK_NAMES.indexOf(String(v.name || '').toLowerCase()) === -1) continue;
      if (isSlotRef(v.value)) continue;
      commonWrites.push({ role, varName: v.name, newValue: LINK,
                          oldValue: String(v.value == null ? '' : v.value) });
    }
  }

  if (!draft.journeyName) fail('source draft ' + SOURCE_DRAFT_ID + ' has no journeyName.');
  const nameWas = { top: String(draft.journeyName),
                    info: ((draft.rawJourneyData || {}).infoValues || {}).journeyName };

  // ── is a whole-body replace unambiguous? ────────────────────────────────
  let json = JSON.stringify(draft);
  const groups = new Map();
  for (const p of plan) {
    if (p.oldValue === p.newValue) { p.skip = 'already correct'; continue; }
    if (!p.oldValue) fail(p.label + ' has an empty current value — nothing to replace, so the new copy could not be placed by string swap. Set it once in the builder, then rerun.');
    if (u16(p.oldValue) < 6) fail(p.label + ' current value ' + JSON.stringify(p.oldValue)
      + ' is too short to replace across the body without hitting unrelated text. Refusing.');
    if (!groups.has(p.oldValue)) groups.set(p.oldValue, { oldValue: p.oldValue, newValue: p.newValue, labels: [] });
    const g = groups.get(p.oldValue);
    if (g.newValue !== p.newValue) {
      fail('these fields all currently hold ' + JSON.stringify(p.oldValue) + ' but need different new copy:'
        + '\n        ' + g.labels.concat([p.label]).join('\n        ')
        + '\n      A whole-body replace cannot tell them apart. Give them distinct copy.');
    }
    g.labels.push(p.label);
  }
  const swaps = [...groups.values()];
  const nodeScope = (labels) => {
    const roles = [...new Set(labels.map((l) => l.split('.')[0]))].filter((r) => found[r]);
    let blob = '';
    for (const r of roles) {
      const a = found[r]; blob += JSON.stringify(a);
      const id = a.journeyActivityId || a.activityId;
      const cfg = ((draft.rawJourneyData || {}).activitiesConfiguration || {})[id];
      if (cfg) blob += JSON.stringify(cfg);
    }
    return blob;
  };
  for (const g of swaps) {
    const needle = JSON.stringify(g.oldValue).slice(1, -1);
    g.hits = json.split(needle).length - 1;
    if (!g.hits) fail(g.labels.join(' / ') + ': the current value is not in the serialised body — cannot place the new copy.');
    const inNode = nodeScope(g.labels).split(needle).length - 1;
    g.outside = Math.max(0, g.hits - inNode);
  }
  const spill = swaps.filter((g) => g.outside > 0);
  if (spill.length) {
    console.warn('  NOTE — ' + spill.length + ' string(s) also appear outside the node being edited,'
      + ' in a journey of ' + acts.length + ' activities. They would be rewritten as well:');
    for (const g of spill) {
      const needle = JSON.stringify(g.oldValue).slice(1, -1);
      const targets = new Set(g.labels.map((l) => l.split('.')[0]).filter((r) => found[r]).map((r) => akey(found[r])));
      const others = acts.filter((a) => JSON.stringify(a).indexOf(needle) > -1 && !targets.has(akey(a)))
                         .map((a) => akey(a) + (a.journeyActivityId ? ' [' + a.journeyActivityId + ']' : ''));
      console.warn('    ' + g.labels.join(' + ') + '  ' + g.outside + ' extra: ' + JSON.stringify(g.oldValue));
      console.warn('        also held by: ' + (others.length ? [...new Set(others)].join(', ') : 'the same node or its mirror'));
    }
    if (!DRY_RUN && !ALLOW_SHARED_COPY_REWRITE) {
      fail(spill.length + ' string(s) are shared with another activity, which would be rewritten in'
        + ' the new draft too (the source journey is untouched either way).'
        + ' Set ALLOW_SHARED_COPY_REWRITE = true if that is what you want.');
    }
  }
"""

JS_TEMPLATE += r"""
  // ── the photo slots ─────────────────────────────────────────────────────
  // Located BEFORE anything is uploaded: being asked to browse for a photo and
  // only then told the slot does not exist wastes the operator's time, and a
  // slot that silently has no home is how the copied campaign's artwork ships.
  const varMatch = (node, stems) => varsOf(node).filter((v) =>
    stems.indexOf(String(v.name || '').toLowerCase()) > -1);
  const slots = [];
  if (ROLES.indexOf('nc') > -1) slots.push({ key: 'nc.icon', label: 'NC ICON', role: 'nc',
    stems: ['icon'], kind: 'variable' });
  if (ROLES.indexOf('popup') > -1) slots.push({ key: 'popup.background_image_src', label: 'POP-UP BACKGROUND',
    role: 'popup', stems: ['background_image_src', 'backgroundimagesrc'], kind: 'variable' });
  for (const s of slots) {
    const hits = varMatch(found[s.role], s.stems);
    if (!hits.length) fail(s.key + ': no captured variable is named ' + s.stems.join('/')
      + ' on the ' + s.role + ' node. Variables present: ' + varsOf(found[s.role]).map((v) => v.name).join(', ')
      + '. Uploading a photo with nowhere to put it would leave the source journey\'s artwork in place.');
    s.names = hits.map((h) => h.name);
    s.oldValue = hits[0].value == null ? '' : String(hits[0].value);
  }
  if (EMAIL_CONTENT) {
    for (const [tok, label, key] of [[TOP_IMAGE_TOKEN, 'EMAIL TOP IMAGE', 'email.top_image'],
                                     [CTA_IMAGE_TOKEN, 'EMAIL CTA IMAGE', 'email.cta_image']]) {
      if (JSON.stringify(EMAIL_CONTENT).indexOf(tok) === -1)
        fail(key + ': ' + tok + ' is not in the prepared email content — the photo slot has drifted.');
      slots.push({ key: key, label: label, kind: 'email', token: tok, oldValue: '' });
    }
    const es = (found.email.initializationData || {}).emailSettings;
    if (!es || typeof es !== 'object')
      fail('email: the dextra_email node has no emailSettings — nothing to point at the new content.');
    slots.push({ key: 'email.template.id', label: null, kind: 'template',
                 oldValue: String(((es.template || {}).id) || '') });
  }
  // ── nothing may be left as the source journey's ─────────────────────────
  // A content field this run never writes ships the source's value, and that
  // is how last week's campaign goes out under this week's name. Knowable from
  // the plan alone, so it refuses HERE — before a photo is uploaded, an email
  // is published, or a draft exists to have to delete.
  const written = new Set();
  for (const w of writes) written.add(w.role + '::' + w.varName);
  for (const pl of plan) if (pl.role) written.add(pl.role + '::' + pl.varName);
  for (const w of commonWrites) written.add(w.role + '::' + w.varName);
  for (const s of slots) if (s.kind === 'variable') for (const n of s.names) written.add(s.role + '::' + n);
  // What this run supplies, whatever variable it happens to land in. A field
  // that already holds one of these is this campaign's, not the source's.
  const ours = new Set([LINK]);
  for (const r of Object.keys(COPY)) for (const v of Object.values(COPY[r] || {})) if (v) ours.add(String(v));
  const CONTENT_RE = /(title|des|caption|link|icon|image|deeplink|text|message)/i;
  const leaks = [];
  for (const role of ROLES) {
    if (role === 'sms' || role === 'email') continue;
    for (const v of varsOf(found[role])) {
      const name = String(v.name || '');
      if (!CONTENT_RE.test(name) || written.has(role + '::' + name)) continue;
      const was = v.value == null ? '' : String(v.value);
      if (!was.trim() || isSlotRef(was) || ours.has(was)) continue;
      leaks.push(role + '.' + name + ' would stay the source journey\'s: ' + JSON.stringify(was));
    }
  }
  const touched = new Set(ROLES.map((r) => want[r]));
  for (const a of acts) {
    const k = akey(a);
    const role = Object.keys(want).find((r) => want[r] === k);
    if (role && !touched.has(k))
      leaks.push('the ' + role + ' activity is not in ROLES, so all of its content would stay the source journey\'s');
  }
  if (leaks.length) fail('the new draft would still carry the source journey\'s content:\n      '
    + leaks.join('\n      ')
    + '\n      Give the sheet a value for each, or regenerate with that channel in --channels.');

  console.log('  photos and email:');
  for (const s of slots) {
    const ph = typeof s.oldValue === 'string' && /^%.*%$/.test(s.oldValue.trim());
    if (s.kind === 'template') {
      console.log('    ' + s.key + '  currently ' + JSON.stringify(s.oldValue)
        + '  ->  the content this run creates and publishes');
    } else if (KEEP_INHERITED_ASSETS) {
      console.log('    ' + s.key + '  KEEPING: ' + JSON.stringify(s.oldValue)
        + (ph ? '   <-- an UNSET placeholder: renders as nothing' : ''));
    } else {
      console.log('    ' + s.key + '  browse for a photo  (was ' + JSON.stringify(s.oldValue) + ')');
    }
  }
  if (KEEP_INHERITED_ASSETS && EMAIL_CONTENT)
    fail('KEEP_INHERITED_ASSETS is on, but the email is being rebuilt and its two photo slots'
       + ' are tokens with no inherited value to keep — they would publish as broken images.'
       + ' Either let the pickers run, or regenerate the script with --no-email.');

  // ── the plan ────────────────────────────────────────────────────────────
  console.log('%c' + JOURNEY_NAME + '  — a NEW draft, built from ' + SOURCE_DRAFT_ID
              + (DRY_RUN ? '   [DRY RUN — nothing created]' : ''),
              'color:#3b82f6;font-weight:bold;font-size:14px');
  for (const p of plan) if (p.skip) console.log('    = ' + p.label + '  (' + p.skip + ')');
  for (const w of smsWrites) {
    if (w.oldValue === w.newValue) { console.log('    = sms.text_' + w.lang + '  (already correct)'); continue; }
    console.log('    sms.text_' + w.lang + '  (' + w.paths.length + ' place(s) in the node: '
                + (w.paths.join(', ') || 'none') + ')'
                + '\n        old: ' + JSON.stringify(w.oldValue) + '\n        new: ' + JSON.stringify(w.newValue));
  }
  if (smsAmbiguous) {
    console.warn('  NOTE — the source SMS node holds ONE string for both languages, so only the'
      + ' per-language paths it carries can be told apart. Every other place holding that string'
      + ' gets the ' + SMS_DEFAULT_LANG.toUpperCase() + ' text (change SMS_DEFAULT_LANG to flip it).');
  }
  if (smsWrites.length) {
    // Every message-length string the node holds, wherever it keeps it. The
    // shape differs between captured journeys, and a message sitting somewhere
    // this script does not list is one it would not replace.
    const claimed = new Set(smsWrites.map((w) => w.oldValue));
    const others = [];
    const walk = (val, p) => {
      if (typeof val === 'string') {
        if (val.length > 30 && !claimed.has(val) && !/^https?:\/\//.test(val) && !isSlotRef(val))
          others.push('        ' + (p || '(root)') + ' = ' + JSON.stringify(val));
        return;
      }
      if (!val || typeof val !== 'object') return;
      if (Array.isArray(val)) { val.forEach((v, i) => walk(v, p + '[' + i + ']')); return; }
      for (const k of Object.keys(val)) walk(val[k], p ? p + '.' + k : k);
    };
    walk(found.sms, '');
    if (others.length) {
      console.warn('  NOTE — the SMS activity also holds ' + others.length + ' other long string(s),'
        + ' which this run does NOT replace. Check none of them is the message that actually sends:'
        + '\n' + others.join('\n'));
    }
  }
  for (const w of writes) {
    if (w.oldValue === w.newValue) { console.log('    = ' + w.role + '.' + w.field + ' [' + w.varName + ']  (already correct)'); continue; }
    console.log('    ' + w.role + '.' + w.field + ' [' + w.varName + ']  (by path)'
                + '\n        old: ' + JSON.stringify(w.oldValue) + '\n        new: ' + JSON.stringify(w.newValue));
  }
  for (const g of swaps) {
    console.log('    ' + g.labels.join(' + ') + '  x' + g.hits + (g.outside ? '  (' + g.outside + ' outside this node)' : '')
                + '\n        old: ' + JSON.stringify(g.oldValue) + '\n        new: ' + JSON.stringify(g.newValue));
  }
  for (const w of commonWrites) {
    if (w.oldValue === w.newValue) { console.log('    = ' + w.role + '.' + w.varName + '  (already this campaign\'s link)'); continue; }
    console.log('    ' + w.role + '.' + w.varName + '  (by path, language-independent)'
                + '\n        old: ' + JSON.stringify(w.oldValue) + '\n        new: ' + JSON.stringify(w.newValue));
  }
  // The card's own slot appends the utm tags to whatever the variable holds, so
  // a value that already carries them renders the query string twice. The source
  // journey is already shaped this way, so it is a note, not a refusal — but it
  // is the operator's call, and it is invisible until an email lands.
  const utmDoubled = [], utmSeen = new Set();
  for (const role of ROLES) {
    if (role === 'sms' || role === 'email') continue;
    for (const v of varsOf(found[role])) {
      const ref = String(v.value == null ? '' : v.value);
      const m = isSlotRef(ref) ? ref.match(/^%([^%]+)%\?%\$utm_tags%$/) : null;
      if (!m || utmSeen.has(role + '::' + v.name)) continue;
      utmSeen.add(role + '::' + v.name);
      const target = m[1].toLowerCase();
      const supplied = [...writes, ...commonWrites, ...plan].find((w) => w.role === role
        && String(w.varName || '').toLowerCase() === target);
      if (supplied && String(supplied.newValue).indexOf('%$utm_tags%') > -1)
        utmDoubled.push(role + '.' + v.name + ' -> %' + m[1] + '%');
    }
  }
  if (utmDoubled.length) {
    console.warn('  NOTE — these card slots append "?%$utm_tags%" themselves, and the link this run'
      + ' writes already ends with it, so the rendered URL carries the tags twice:'
      + '\n        ' + utmDoubled.join('\n        ')
      + '\n        renders as ' + LINK + '?%$utm_tags%'
      + '\n      The source journey is already shaped this way. Pass --link without the'
      + ' "?%$utm_tags%" suffix if that is not what you want.');
  }

  if (EMAIL_CONTENT) {
    const comp = ((EMAIL_CONTENT.translations || {}).es || {}).composition || {};
    console.log('    email content (created + published, then pointed at)'
      + '\n        name:       ' + JSON.stringify(EMAIL_CONTENT.name)
      + '\n        subject:    ' + JSON.stringify(comp.subject)
      + '\n        preHeader:  ' + JSON.stringify(comp.preHeader));
  }
  console.log('    journeyName (all 3 homes, set directly)'
              + '\n        old: ' + JSON.stringify(nameWas.top)
              + (nameWas.info !== nameWas.top ? '\n        old (infoValues + notification metadata): ' + JSON.stringify(nameWas.info) : '')
              + '\n        new: ' + JSON.stringify(JOURNEY_NAME));
  if (DRY_RUN) {
    console.log('%cDRY RUN — nothing uploaded, no email created, draft untouched.'
      + ' Set DRY_RUN = false to apply.', 'color:#eab308;font-weight:bold');
    return;
  }

  // ── the uploads ─────────────────────────────────────────────────────────
  const uploaded = {};
  if (!KEEP_INHERITED_ASSETS) {
    for (const s of slots) {
      if (s.kind === 'template') continue;
      const asset = await pickAndUpload(s.label);
      // The on-site channels take the absolute URL; the email body references
      // its images as https://{{cdn_hostname}}<relative_link>.
      uploaded[s.key] = s.kind === 'email'
        ? 'https://{{cdn_hostname}}' + asset.relative_link
        : asset.absolute_link;
    }
  }

  // ── the email ───────────────────────────────────────────────────────────
  let cseId = null;
  if (EMAIL_CONTENT) {
    let cText = JSON.stringify(EMAIL_CONTENT);
    cText = cText.split(TOP_IMAGE_TOKEN).join(uploaded['email.top_image']);
    cText = cText.split(CTA_IMAGE_TOKEN).join(uploaded['email.cta_image']);
    for (const tok of [TOP_IMAGE_TOKEN, CTA_IMAGE_TOKEN]) {
      if (cText.indexOf(tok) > -1) fail(tok + ' is still in the email content — refusing to publish an email with a broken image.');
    }
    console.log('Creating + publishing the email...');
    cseId = await publishEmail(JSON.parse(cText));
  }
"""

JS_TEMPLATE += r"""
  // ── one whole-body pass, then the targeted writes, then save ────────────
  for (const g of swaps) {
    json = json.split(JSON.stringify(g.oldValue).slice(1, -1)).join(JSON.stringify(g.newValue).slice(1, -1));
  }
  const patched = JSON.parse(json);

  // Both storages or neither: the compiled activity and its rawJourneyData
  // mirror. Writing one and not the other is a blank canvas in the builder.
  const holdersFor = (role) => {
    const node = patched.activities.find((a) => akey(a) === want[role]);
    if (!node) fail(role + ': node vanished from the patched body');
    const id = node.journeyActivityId || node.activityId;
    const cfg = ((patched.rawJourneyData || {}).activitiesConfiguration || {})[id];
    return [node.initializationData, cfg].filter((h) => h && typeof h === 'object');
  };

  const applied = [], smsApplied = [];
  for (const w of writes) {
    let hit = 0;
    for (const holder of holdersFor(w.role)) {
      for (const v of ((holder.objectForSend || {}).variables) || []) if (v.name === w.varName) { v.value = w.newValue; hit++; }
      const tabs = ((holder.singleChannel || {}).localizedLanguagesTab) || {};
      for (const [tabLang, tab] of Object.entries(tabs)) {
        if (!tab || typeof tab !== 'object') continue;
        for (const tk of Object.keys(tab)) {
          const tn = tk.toLowerCase();
          const tabIsLang = String(tabLang).toLowerCase() === w.lang;
          if (tn.indexOf(w.stem) > -1 && (langOf(tn) === w.lang || (langOf(tn) === null && tabIsLang))) {
            tab[tk] = w.newValue; hit++;
          }
        }
      }
    }
    if (!hit) fail(w.role + '.' + w.field + ' [' + w.varName + ']: nothing was written. Refusing to save a'
      + ' body where a field silently kept the copied campaign\'s value.');
    applied.push({ w, hit });
  }

  for (const w of smsWrites) {
    let hit = 0;
    for (const root of holdersFor('sms')) {
      for (const holder of [root.rawValues, root.smsSettings]) {
        if (!holder || typeof holder !== 'object') continue;
        if (w.lang === 'en' && typeof holder.messageText === 'string') { holder.messageText = w.newValue; hit++; }
        const loc = holder.localizedMessageTexts;
        if (loc && !Array.isArray(loc) && typeof loc === 'object') {
          for (const k of Object.keys(loc)) {
            if (k.toLowerCase() !== w.lang) continue;
            if (loc[k] && typeof loc[k] === 'object' && 'messageText' in loc[k]) { loc[k].messageText = w.newValue; hit++; }
            else { loc[k] = w.newValue; hit++; }
          }
        } else if (Array.isArray(loc)) {
          for (const it of loc) if (it && String(it.languageCode || '').toLowerCase() === w.lang) { it.messageText = w.newValue; hit++; }
        }
      }
    }
    smsApplied.push({ w, hit });
  }
  // The paths above are only the shapes journey_composer.py happens to know. Any
  // other place the node keeps its message is swept here by exact match, scoped
  // to the SMS node and its mirror, so an unknown shape cannot ship the source
  // journey's text under this campaign's name.
  const smsSwept = [];
  if (smsWrites.length) {
    const fallback = smsWrites.find((w) => w.lang === SMS_DEFAULT_LANG) || smsWrites[0];
    const pairs = smsAmbiguous
      ? [{ oldValue: smsWrites[0].oldValue, newValue: fallback.newValue, lang: fallback.lang }]
      : smsWrites;
    for (const w of pairs) {
      if (w.oldValue === w.newValue) continue;
      let n = 0;
      for (const root of holdersFor('sms')) n += replaceExact(root, w.oldValue, w.newValue);
      if (n) smsSwept.push({ lang: w.lang, n });
    }
  }
  for (const { w, hit } of smsApplied) {
    const swept = smsSwept.reduce((t, x) => t + (x.lang === w.lang ? x.n : 0), 0);
    if (!hit && !swept && w.oldValue !== w.newValue)
      fail('sms.text_' + w.lang + ': nothing was written. Refusing to build a draft where the'
        + ' source journey\'s SMS silently survived.');
  }
  for (const root of holdersFor('sms')) {
    for (const w of smsWrites) {
      const left = exactPaths(root, w.oldValue);
      if (left.length) fail('sms.text_' + w.lang + ': the source journey\'s message is still at '
        + left.join(', ') + ' after the write. Refusing to build a draft that would send it.');
    }
  }

  // The language-independent promo link, written by exact variable name so it
  // cannot touch a template slot that merely mentions "link".
  const commonApplied = [];
  for (const w of commonWrites) {
    let hit = 0;
    for (const holder of holdersFor(w.role)) {
      for (const v of ((holder.objectForSend || {}).variables) || [])
        if (v.name === w.varName) { v.value = w.newValue; hit++; }
      const tabs = ((holder.singleChannel || {}).localizedLanguagesTab) || {};
      for (const tab of Object.values(tabs)) {
        if (!tab || typeof tab !== 'object') continue;
        for (const tk of Object.keys(tab)) if (tk === w.varName) { tab[tk] = w.newValue; hit++; }
      }
    }
    if (!hit) fail(w.role + '.' + w.varName + ': the promo link was not written anywhere. Refusing to'
      + ' build a draft whose ' + w.role + ' still points at the source journey\'s promotion.');
    commonApplied.push({ w, hit });
  }

  // The photos. Language-independent, so they live once in the `common` tab
  // alongside the variable — and in the mirror, same as the copy above.
  const assetApplied = [];
  for (const s of slots) {
    if (s.kind !== 'variable') continue;
    const value = uploaded[s.key];
    if (value == null) continue;                       // KEEP_INHERITED_ASSETS
    let hit = 0;
    const names = new Set();
    for (const holder of holdersFor(s.role)) {
      for (const v of ((holder.objectForSend || {}).variables) || [])
        if (s.stems.indexOf(String(v.name || '').toLowerCase()) > -1) { v.value = value; names.add(v.name); hit++; }
      const tabs = ((holder.singleChannel || {}).localizedLanguagesTab) || {};
      for (const tab of Object.values(tabs)) {
        if (!tab || typeof tab !== 'object') continue;
        for (const tk of Object.keys(tab))
          if (s.stems.indexOf(tk.toLowerCase()) > -1) { tab[tk] = value; hit++; }
      }
    }
    if (!hit) fail(s.key + ': the uploaded photo was not written anywhere. Refusing to build a draft'
      + ' where the source journey\'s artwork silently survived.');
    assetApplied.push({ key: s.key, value, hit, names: [...names] });
  }

  if (cseId) {
    let hit = 0;
    for (const holder of holdersFor('email')) {
      const es = holder.emailSettings;
      if (es && typeof es === 'object') {
        es.template = Object.assign({}, es.template, { id: cseId });
        if (EMAIL_NAME && 'name' in es.template) es.template.name = EMAIL_NAME;
        hit++;
      }
      // displayData is what the builder prints on the card; the old id left
      // there is how a reviewer sees the wrong email and approves it anyway.
      if ('displayData' in holder) holder.displayData = [String(cseId)];
    }
    if (!hit) fail('email.template.id: the new content id was not written. Refusing to save a body'
      + ' where the email activity still points at the copied campaign\'s email.');
  }

  if (!patched.rawJourneyData || !Array.isArray(patched.activities)) fail('patched body lost a storage — refusing to save.');
  patched.journeyName = JOURNEY_NAME;
  patched.rawJourneyData.infoValues = patched.rawJourneyData.infoValues || {};
  patched.rawJourneyData.infoValues.journeyName = JOURNEY_NAME;
  const setNames = (o) => { if (o && typeof o === 'object') {
      if (o.metadata && typeof o.metadata === 'object' && 'journeyName' in o.metadata) o.metadata.journeyName = JOURNEY_NAME;
      for (const v of Object.values(o)) setNames(v); } };
  setNames(patched);
  const nameHomes = [];
  if (patched.journeyName !== JOURNEY_NAME) nameHomes.push('journeyName');
  if (((patched.rawJourneyData || {}).infoValues || {}).journeyName !== JOURNEY_NAME) nameHomes.push('rawJourneyData.infoValues.journeyName');
  const walk = (o, out) => { if (o && typeof o === 'object') {
      if (o.metadata && typeof o.metadata === 'object' && 'journeyName' in o.metadata
          && o.metadata.journeyName !== JOURNEY_NAME) out.push('a notification metadata.journeyName');
      for (const v of Object.values(o)) walk(v, out); } return out; };
  walk(patched, nameHomes);
  if (nameHomes.length) fail('the journey name did not reach: ' + [...new Set(nameHomes)].join(', '));

  // ── make the body standalone, then create the new draft ─────────────────
  // Posted with the source's lineage or its server-minted ids, a create is
  // rejected ("the journey with the same identifier already exists", or a 422
  // on a promotionDisplayId that already exists).
  for (const key of ['duplicatedFromId', 'duplicatedFromVersion']) delete patched[key];
  let connectors = 0, displayIds = 0;
  const scrub = (o) => {
    if (!o || typeof o !== 'object') return;
    if (Array.isArray(o)) { for (const v of o) scrub(v); return; }
    const cc = o.campaignConnectorConditions;
    if (cc && typeof cc === 'object' && cc.campaignId) { cc.campaignId = ''; connectors++; }
    if ('promotionDisplayId' in o) { delete o.promotionDisplayId; displayIds++; }
    for (const v of Object.values(o)) scrub(v);
  };
  scrub(patched);

  // A GET hands back fields the server owns (the numeric id, version, status,
  // timestamps). KEEP_KEYS is the top-level shape of a real POSTable comms
  // draft, so anything outside it is the source's own identity.
  const dropped = Object.keys(patched).filter((k) => KEEP_KEYS.indexOf(k) === -1);
  for (const k of dropped) delete patched[k];
  if (dropped.length) console.log('  dropped the source draft\'s own field(s): ' + dropped.join(', '));
  if (connectors || displayIds)
    console.log('  cleared ' + connectors + ' campaign-connector id(s) and ' + displayIds + ' promotionDisplayId(s)');

  console.log('Reserving a journey id...');
  const reserved = await reserveId();
  patched.reservedJourneyId = reserved;
  console.log('  reserved ' + reserved);

  const regenerated = regenIds(patched);
  console.log('  regenerated ' + regenerated.count + ' activity id(s)');
  if (!regenerated.count) fail('no activity id was regenerated — shared activityIds collide with the source journey.');

  const created = await send('POST', CRM_BASE + '/journey-builder/v0/journey-drafts', regenerated.body);
  const newDraftId = created && (created.id || created.journeyDraftId || created.draftId);
  console.log('%cCreated draft ' + (newDraftId || '(the create response carried no id)') + '   ' + reserved,
              'color:#22c55e;font-weight:bold');

  // ── readback ────────────────────────────────────────────────────────────
  if (!newDraftId) console.warn('  no draft id came back, so the checks below run on the body that was sent.');
  const backObj = newDraftId
    ? await send('GET', CRM_BASE + '/journey-builder/v0/journey-drafts/' + newDraftId)
    : regenerated.body;
  const back = JSON.stringify(backObj);
  const bad = [];
  for (const g of swaps) {
    const nv = JSON.stringify(g.newValue).slice(1, -1), ov = JSON.stringify(g.oldValue).slice(1, -1);
    if (back.indexOf(nv) === -1) bad.push(g.labels.join(' / ') + ': the new copy is not in the created draft');
    else if (back.indexOf(ov) > -1) bad.push(g.labels.join(' / ') + ': the source journey\'s copy is still there');
  }
  const backNode = (role) => (backObj.activities || []).find((a) => akey(a) === want[role]);
  // Checked on the node itself rather than on a path this script guessed: an
  // unknown shape must read as a failure, never as "the field was not there".
  const smsBack = backNode('sms');
  if (smsWrites.length && !smsBack) bad.push('sms: the created draft has no dextra_sms activity');
  for (const w of smsWrites) {
    if (!smsBack) break;
    const left = exactPaths(smsBack, w.oldValue);
    if (left.length) bad.push('sms.text_' + w.lang + ': the source journey\'s message is still at '
                              + left.join(', '));
    if (!exactPaths(smsBack, w.newValue).length && !(smsAmbiguous && w.lang !== SMS_DEFAULT_LANG))
      bad.push('sms.text_' + w.lang + ': the new message is nowhere in the created SMS activity');
  }
  for (const { w } of applied) {
    const vs = ((( backNode(w.role) || {}).initializationData || {}).objectForSend || {}).variables || [];
    const v = vs.find((x) => x.name === w.varName);
    if (!v || v.value !== w.newValue) {
      bad.push(w.role + '.' + w.field + ' [' + w.varName + ']: reads back as '
               + JSON.stringify(v && v.value) + ', expected ' + JSON.stringify(w.newValue));
    }
  }
  for (const { w } of commonApplied) {
    const vs = (((backNode(w.role) || {}).initializationData || {}).objectForSend || {}).variables || [];
    const v = vs.find((x) => x.name === w.varName);
    if (!v || v.value !== w.newValue) {
      bad.push(w.role + '.' + w.varName + ': reads back as ' + JSON.stringify(v && v.value)
               + ', expected ' + JSON.stringify(w.newValue));
    }
  }
  for (const a of assetApplied) {
    const role = a.key.split('.')[0];
    const vs = (((backNode(role) || {}).initializationData || {}).objectForSend || {}).variables || [];
    const slot = slots.find((s) => s.key === a.key);
    const v = vs.find((x) => slot.stems.indexOf(String(x.name || '').toLowerCase()) > -1);
    if (!v || v.value !== a.value) {
      bad.push(a.key + ': reads back as ' + JSON.stringify(v && v.value) + ', expected ' + JSON.stringify(a.value));
    }
  }
  if (cseId) {
    const gotId = ((((backNode('email') || {}).initializationData || {}).emailSettings || {}).template || {}).id;
    if (String(gotId) !== String(cseId))
      bad.push('email.template.id: reads back as ' + JSON.stringify(gotId) + ', expected ' + JSON.stringify(cseId));
  }
  if (bad.length) fail('the draft was created, but the readback disagrees:\n      ' + bad.join('\n      '));

  console.log('%cDONE — new draft ' + (newDraftId || reserved) + ' created and verified ('
              + (plan.filter((p) => !p.skip).length + applied.length + smsApplied.length
                 + commonApplied.length) + ' copy field(s), '
              + assetApplied.length + ' photo(s)' + (cseId ? ', 1 email' : '')
              + '); nothing is the source journey\'s.',
              'color:#22c55e;font-weight:bold;font-size:14px');
  for (const a of assetApplied) console.log('    ' + a.key + ' -> ' + a.value);
  if (cseId) console.log('    email content ' + cseId + ' created, published, and pointed at.');
  console.log('    source draft ' + SOURCE_DRAFT_ID + ' was not modified.');
  if (KEEP_INHERITED_ASSETS) {
    console.log('%cSTILL TO DO BY HAND — the photo slots are the source journey\'s:',
                'color:#f59e0b;font-weight:bold;font-size:14px');
    for (const s of slots) if (s.kind === 'variable') console.log('    ' + s.key + '  currently ' + JSON.stringify(s.oldValue));
    console.log('    DO NOT PUBLISH until those are changed.');
  }
  console.log('Unpublished. Open the new journey in the builder and check the canvas is not blank.');
})();
"""


def build_js(*, source_draft_id: str, name: str, link: str, copy: dict, roles: list[str],
             email_content: dict | None, live: bool, sms_default_lang: str) -> str:
    js = JS_TEMPLATE
    js = js.replace("@GENERATED_AT@", datetime.now(LOCAL_TZ).strftime("%Y-%m-%d %H:%M %Z"))
    js = js.replace("@JOURNEY_NAME@", name)
    js = js.replace("@JOURNEY_NAME_JSON@", json.dumps(name, ensure_ascii=False))
    js = js.replace("@SOURCE_DRAFT_ID@", json.dumps(source_draft_id))
    js = js.replace("@SMS_DEFAULT_LANG@", json.dumps(sms_default_lang))
    js = js.replace("@KEEP_KEYS@", json.dumps(postable_keys()))
    js = js.replace("@BRAND@", json.dumps(BRAND))
    js = js.replace("@LINK@", json.dumps(link, ensure_ascii=False))
    js = js.replace("@ROLES@", json.dumps(roles))
    js = js.replace("@FOLDER_ID@", json.dumps(DEFAULT_FOLDER_ID))
    js = js.replace("@TOK_TOP_IMAGE@", json.dumps(EMAIL_TOP_IMAGE_TOKEN))
    js = js.replace("@TOK_CTA_IMAGE@", json.dumps(EMAIL_CTA_IMAGE_TOKEN))
    js = js.replace("@EMAIL_NAME@", json.dumps((email_content or {}).get("name", ""), ensure_ascii=False))
    if live:
        js = js.replace("const DRY_RUN = true;", "const DRY_RUN = false;", 1)
    # The @@...@@ paste-time tokens are not placeholders — @@EMAIL_TOP_IMAGE_URL@@
    # contains @EMAIL_TOP_IMAGE_URL@, so the scan has to refuse a doubled @.
    left = sorted(set(re.findall(r"(?<!@)@[A-Z0-9_]+@(?!@)", js)) - {"@COPY@", "@EMAIL_CONTENT@"})
    if left:
        raise SystemExit(f"unfilled template placeholders: {', '.join(left)}")
    js = js.replace("@COPY@", json.dumps(copy, ensure_ascii=False, indent=2))
    js = js.replace("@EMAIL_CONTENT@", json.dumps(email_content, ensure_ascii=False))
    for ph in ("@COPY@", "@EMAIL_CONTENT@"):
        if ph in js:
            raise SystemExit(f"unfilled template placeholder: {ph}")
    return js


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--source-draft-id", required=True,
                    help="the numeric id of the journey draft to build FROM; it is read, never written")
    ap.add_argument("--name", required=True, help="the journey name to set")
    ap.add_argument("--link", required=True, help="the promo link every channel points at")
    ap.add_argument("--spec", required=True,
                    help="the pasted sheet block; '-' reads stdin")
    ap.add_argument("--channels", default="",
                    help="comma-separated subset of popup,nc,sms,email (default: whatever the sheet ticked)")
    ap.add_argument("--no-email", action="store_true", help="leave the email activity alone")
    ap.add_argument("--email-name", default="", help="content-studio name (default: derived from --name)")
    ap.add_argument("--email-subject", default="", help="overrides the sheet's Email Tittle (ES)")
    ap.add_argument("--email-preheader", default="", help="overrides the sheet's Email Pre-header (ES)")
    ap.add_argument("--email-body-text", default="",
                    help="plain email copy; blank lines become the shell's paragraph breaks")
    ap.add_argument("--email-body-html", default="",
                    help="email copy that already carries its own markup, used verbatim")
    ap.add_argument("--email-cta", default="",
                    help="the CTA words (they go in the image's alt text — the shell's CTA is a picture)")
    ap.add_argument("--sms-default-lang", default="es", choices=["es", "en"],
                    help="when the SMS node keeps one message for both languages, which one "
                         "every un-separable copy of it gets (default: es)")
    ap.add_argument("--live", action="store_true",
                    help="emit the script with DRY_RUN already off")
    ap.add_argument("--basename", default="", help="output name under console_scripts/")
    args = ap.parse_args()

    text = sys.stdin.read() if args.spec == "-" else Path(args.spec).read_text(encoding="utf-8")
    spec = parse_spec(text, expect_game_offer=False)

    if args.channels.strip():
        channels = [c.strip().lower() for c in args.channels.split(",") if c.strip()]
        unknown = [c for c in channels if c not in CHANNELS]
        if unknown:
            raise SystemExit(f"unknown channel(s): {', '.join(unknown)} (known: {', '.join(CHANNELS)})")
    else:
        channels = [c for c in CHANNELS if getattr(spec, c).enabled]
    if args.no_email and "email" in channels:
        channels.remove("email")
    if not channels:
        raise SystemExit("no channels — the sheet ticked none and --channels is empty.")

    copy = build_copy(spec, args.link, channels)
    errors: list[str] = []
    check_copy(copy, errors)
    if errors:
        for e in errors:
            print(f"  REFUSED: {e}", file=sys.stderr)
        raise SystemExit("the copy would ship wrong — fix the sheet, not this check.")
    for w in spec.warnings:
        print(f"  note: {w}", file=sys.stderr)

    email_content = build_email(args, spec, args.link) if "email" in channels else None

    js = build_js(source_draft_id=args.source_draft_id, name=args.name, link=args.link, copy=copy,
                  roles=channels, email_content=email_content, live=args.live,
                  sms_default_lang=args.sms_default_lang)

    stamp = hashlib.sha1(js.encode("utf-8")).hexdigest()[:8]
    base = args.basename or f"comms_copy_{args.source_draft_id}_{stamp}"
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUT_DIR / f"{base}_console.js"
    out.write_text(js, encoding="utf-8")

    print(f"wrote {out.relative_to(HERE)}")
    print(f"  source   draft {args.source_draft_id} (read only; a NEW draft is created)")
    print(f"  name     {args.name}")
    print(f"  channels {', '.join(channels)}")
    print(f"  photos   {', '.join(l for r, k, l in PHOTO_SLOTS if r in channels)}")
    if email_content:
        print(f"  email    {email_content['name']!r} — created, published and pointed at")
        if not (args.email_cta or spec.email.button_es):
            print("  note: no CTA words given. The shell's call to action is an image, so the "
                  "words have to be in the artwork you upload.")
    else:
        print("  email    left alone")
    print(f"  DRY_RUN  {'off — it creates on paste' if args.live else 'on — preview first, then flip it'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
