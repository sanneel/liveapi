// Welcome Pack - 1st Deposit / Aff  |  generated 2026-08-06 16:19
//
// Creates one draft per selected brand/mode by cloning the hand-maintained
// source draft and swapping the promocode. Drafts only; nothing is published.
//
// HOW TO RUN (work laptop, on the office VPN):
//   1. Open the Journey Builder backoffice in Chrome, logged in.
//   2. F12 -> Console tab (if Chrome warns, type: allow pasting).
//   3. Paste this whole script and press Enter.
//   4. If it says "Waiting for a token", click anything in the backoffice UI
//      (e.g. refresh the journeys list) so the page makes a request.
//   5. Every draft is fetched, substituted and CHECKED first. Nothing is
//      created until all of them pass.
//   6. Read the "BEFORE PUBLISHING" block at the end. It lists the promotions
//      each new draft still shares with its source.
//
(async () => {
  'use strict';
  // Optional: paste an access token here to skip auto-capture.
  const MANUAL_TOKEN = '';

  const BASE = "https://pmi.rea-backoffice.gr8.tech/api/ubo/api/v0/crm/journey-builder/v0";
  const CODES = ["JUGAWELCOME"];
  const TARGETS = [
  {
    "key": "jbcl_boosted",
    "brand": "JBCL",
    "mode": "boosted",
    "sourceId": 657230
  }
];
  const POST_KEYS = ["journeyName", "brand", "currencyCodes", "activities", "metadata", "reEntryRule", "timeZoneId", "testControlGroupParameters", "activityEventConversionMetrics", "reservedJourneyId", "journeySource", "isArchived", "isUnlimited", "isImmediatelyAfterPublish", "rawJourneyData", "duplicatedFromId"];

  const decodeJwt = (token) => {
    try {
      return JSON.parse(atob(token.split('.')[1].replace(/-/g, '+').replace(/_/g, '/')));
    } catch (e) {
      return null;
    }
  };
  const usableAuth = (value) => {
    if (!value || !/^Bearer\s+\S+/i.test(value)) return null;
    const payload = decodeJwt(value.replace(/^Bearer\s+/i, ''));
    if (!payload || payload.typ !== 'Bearer') return null;
    if (payload.exp - Date.now() / 1000 < 30) return null;
    return 'Bearer ' + value.replace(/^Bearer\s+/i, '');
  };

  async function obtainAuth() {
    if (MANUAL_TOKEN.trim()) {
      const auth = usableAuth('Bearer ' + MANUAL_TOKEN.trim().replace(/^Bearer\s+/i, ''));
      if (!auth) throw new Error('MANUAL_TOKEN is not a valid unexpired access token (typ must be "Bearer").');
      return auth;
    }
    return new Promise((resolve, reject) => {
      let settled = false;
      const origFetch = window.fetch;
      const origSetHeader = XMLHttpRequest.prototype.setRequestHeader;
      const cleanup = () => {
        window.fetch = origFetch;
        XMLHttpRequest.prototype.setRequestHeader = origSetHeader;
      };
      const consider = (value) => {
        const auth = usableAuth(value);
        if (auth && !settled) {
          settled = true;
          cleanup();
          clearTimeout(timer);
          console.log('%cToken captured from the page.', 'color:#22c55e;font-weight:bold');
          resolve(auth);
        }
      };
      window.fetch = function (input, init) {
        try {
          const h = (init && init.headers) || (input && input.headers);
          if (h) {
            if (typeof h.get === 'function') consider(h.get('authorization'));
            else consider(h.authorization || h.Authorization);
          }
        } catch (e) { /* never break the page's own requests */ }
        return origFetch.apply(this, arguments);
      };
      XMLHttpRequest.prototype.setRequestHeader = function (name, value) {
        try {
          if (/^authorization$/i.test(name)) consider(value);
        } catch (e) { /* never break the page's own requests */ }
        return origSetHeader.apply(this, arguments);
      };
      const timer = setTimeout(() => {
        if (!settled) {
          settled = true;
          cleanup();
          reject(new Error('No token captured in 3 minutes. Click around in the backoffice UI and run the script again.'));
        }
      }, 180000);
      console.log('%cWaiting for a token... refresh the journeys list or click anything in the backoffice UI.', 'color:#eab308;font-weight:bold');
    });
  }

  const auth = await obtainAuth();
  const headers = (brand, contentType) => ({
    accept: 'application/json, text/plain, */*',
    authorization: auth,
    'content-type': contentType,
    'x-brand': brand,
  });

  const newUuid = () =>
    (typeof crypto !== 'undefined' && crypto.randomUUID)
      ? crypto.randomUUID()
      : 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, (c) => {
          const r = (Math.random() * 16) | 0;
          return (c === 'x' ? r : (r & 0x3) | 0x8).toString(16);
        });

  // Give every internal activity/node id a fresh UUID. Collect the UUIDs that
  // appear as "activityId"/"id" and string-replace them throughout, so ports,
  // handles, edges, flowIds, boundaryConfiguration and activitiesConfiguration
  // keys — all of which embed the same UUID — stay in sync. Two drafts sharing
  // an activityId are rejected by the backoffice ("activities with the same
  // identifier already exist in other journeys").
  const UUID_RE = /"(?:activityId|id)"\s*:\s*"([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})"/g;
  const regenerateInternalIds = (jsonText) => {
    const oldIds = new Set();
    let m;
    UUID_RE.lastIndex = 0;
    while ((m = UUID_RE.exec(jsonText)) !== null) oldIds.add(m[1]);
    let text = jsonText;
    for (const oldId of oldIds) text = text.split(oldId).join(newUuid());
    return text;
  };

  const escapeRe = (s) => s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  const replaceAll = (text, needle, value) => text.split(needle).join(value);

  async function reserveId(brand) {
    const r = await fetch(BASE + '/journeys/identifier', {
      method: 'POST',
      headers: headers(brand, 'application/x-www-form-urlencoded'),
      credentials: 'include',
    });
    const raw = (await r.text()).trim();
    // Response may be a bare string ("JRN-...") or an object like
    // {"journeyId":"JRN-..."} — mirror parse_identifier_response in Python.
    let id = raw.replace(/^"+|"+$/g, '');
    try {
      const data = JSON.parse(raw);
      if (typeof data === 'string') {
        id = data.trim();
      } else if (data && typeof data === 'object') {
        id = String(data.identifier || data.journeyId || data.id || data.value || '').trim();
      }
    } catch (e) { /* keep the raw text */ }
    if (!r.ok || !id.startsWith('JRN-')) {
      throw new Error('Failed to reserve journey ID: HTTP ' + r.status + ' ' + raw);
    }
    return id;
  }

  const findRegistration = (activities) =>
    (activities || []).find((a) => a && a.activityName === 'registration');

  // ---- fetch + substitute + check, for every target, before creating anything
  async function build(target) {
    const tag = target.key;
    const res = await fetch(`${BASE}/journey-drafts/${target.sourceId}`, {
      method: 'GET',
      credentials: 'include',
      headers: headers(target.brand, 'application/json'),
    });
    if (!res.ok) throw new Error(`[${tag}] source draft ${target.sourceId}: HTTP ${res.status}`);
    let draft = JSON.parse(await res.text());
    // Some endpoints wrap the object; unwrap rather than guess later.
    if (!draft.activities) {
      draft = draft.data || draft.draft || draft.journey || draft;
    }
    if (!Array.isArray(draft.activities) || !draft.activities.length) {
      throw new Error(`[${tag}] source draft ${target.sourceId} has no activities[]`);
    }

    const reg = findRegistration(draft.activities);
    const oldCodes = reg && reg.initializationData && reg.initializationData.promocodeSettings
      ? (reg.initializationData.promocodeSettings.values || []) : [];
    if (!oldCodes.length) {
      throw new Error(`[${tag}] no promocodeSettings.values in the source — nothing to substitute, refusing`);
    }

    // Body = only the keys the backoffice itself posts. A GET returns more.
    const body = {};
    for (const k of POST_KEYS) if (k in draft) body[k] = draft[k];
    body.brand = target.brand;
    body.duplicatedFromId = target.sourceId;

    // Swap the codes by string replacement over the whole serialised body, so
    // the compiled activities[] and the rawJourneyData editor mirror stay
    // byte-identical. If they disagree the builder shows a blank canvas.
    let text = JSON.stringify(body);
    const oldJoined = oldCodes.join(', ');
    const newJoined = CODES.join(', ');
    // Two-stage via sentinels, longest needle first. Direct replacement breaks
    // twice: "A, B" must win over "A", and a new code that contains an old one
    // (old JUGATW -> new JUGATW2) would be eaten by the next pass.
    const subs = [[oldJoined, newJoined]];
    for (const oldCode of oldCodes) subs.push([oldCode, CODES[0]]);
    subs.sort((x, y) => y[0].length - x[0].length);
    const restore = [];
    subs.forEach(([needle, value], i) => {
      if (!needle) return;
      // A raw NUL cannot occur in JSON.stringify output (control chars are
      // encoded as the six literal characters \\u0000), so it cannot collide.
      const token = '\u0000SUB' + i + '\u0000';
      text = replaceAll(text, needle, token);
      restore.push([token, value]);
    });
    for (const [token, value] of restore) text = replaceAll(text, token, value);
    text = regenerateInternalIds(text);
    const out = JSON.parse(text);

    // Belt and braces: set the promocode explicitly in both storages, in case
    // the source ever stops spelling it the way the name does.
    const outReg = findRegistration(out.activities);
    const display = 'Promo codes: ' + newJoined;
    outReg.initializationData.promocodeSettings.values = CODES.slice();
    outReg.initializationData.displayData = [display];
    const mirror = out.rawJourneyData
      && out.rawJourneyData.activitiesConfiguration
      && out.rawJourneyData.activitiesConfiguration[outReg.activityId];
    if (mirror) {
      if (mirror.data && mirror.data.promocodeSettings) {
        mirror.data.promocodeSettings.values = CODES.slice();
      }
      mirror.displayData = [display];
    }

    // The sources are themselves copies, so their names carry "Copy of " (and
    // one has a stray leading space). Take the editor mirror's name, clean it,
    // and keep both storages equal.
    const info = out.rawJourneyData && out.rawJourneyData.infoValues;
    let name = ((info && info.journeyName) || out.journeyName || '').trim();
    name = name.replace(/^(?:Copy of\s+)+/i, '').trim();
    out.journeyName = name;
    if (info) info.journeyName = name;

    // ---- refuse before creating, not after
    const finalText = JSON.stringify(out);
    const problems = [];
    // Boundaries matter both ways: an old code left behind is a leak, but a new
    // code that merely contains an old one (JUGATW2 contains JUGATW) is not.
    for (const oldCode of oldCodes) {
      const leak = new RegExp(`(?<![A-Za-z0-9_])${escapeRe(oldCode)}(?![A-Za-z0-9_])`);
      if (leak.test(finalText)) {
        problems.push(`old promocode ${oldCode} still present`);
      }
    }
    for (const code of CODES) {
      if (!finalText.includes(code)) problems.push(`new promocode ${code} missing`);
    }
    if (!name) problems.push('journey name is empty');
    if (!name.includes(CODES[0])) problems.push(`journey name does not carry ${CODES[0]}: ${name}`);
    if (info && info.journeyName !== out.journeyName) problems.push('journeyName differs between the two storages');
    if (!out.rawJourneyData || !Array.isArray(out.rawJourneyData.elements) || !out.rawJourneyData.elements.length) {
      problems.push('rawJourneyData.elements is empty (builder would show a blank canvas)');
    }
    const mirrorValues = mirror && mirror.data && mirror.data.promocodeSettings
      ? mirror.data.promocodeSettings.values : null;
    if (mirrorValues && mirrorValues.join(',') !== CODES.join(',')) {
      problems.push('promocode differs between the two storages');
    }

    // Promotions could not be duplicated — record exactly which ones this draft
    // will therefore share with its source, so it cannot pass unnoticed.
    const shared = [];
    for (const a of out.activities) {
      const init = a.initializationData || {};
      if (init.promotionLinkId || init.promotionId) {
        shared.push(`${a.activityDisplayName || a.activityName}: promotionLinkId ${init.promotionLinkId || '(none)'}`);
      }
    }

    return { target, body: out, oldCodes, problems, shared, name };
  }

  console.log('%cFetching and checking %d source draft(s)...', 'font-weight:bold', TARGETS.length);
  const built = [];
  for (const target of TARGETS) {
    const b = await build(target);
    console.log(`  [${target.key}] ${b.name}  (was: ${b.oldCodes.join(', ')})`);
    built.push(b);
  }

  // No two drafts created in one run may share an activityId.
  const seen = new Map();
  for (const b of built) {
    for (const a of b.body.activities) {
      if (seen.has(a.activityId)) {
        b.problems.push(`activityId ${a.activityId} collides with ${seen.get(a.activityId)}`);
      } else {
        seen.set(a.activityId, b.target.key);
      }
    }
  }

  const bad = built.filter((b) => b.problems.length);
  if (bad.length) {
    for (const b of bad) {
      console.error(`%c[${b.target.key}] REFUSED:\n  - ${b.problems.join('\n  - ')}`,
        'color:#ef4444;font-weight:bold');
    }
    throw new Error('Nothing was created. Fix the above and re-run.');
  }
  console.log('%cAll checks passed. Creating drafts...', 'color:#22c55e;font-weight:bold');

  // ---- create
  const created = [];
  for (const b of built) {
    b.body.reservedJourneyId = await reserveId(b.target.brand);
    const r = await fetch(BASE + '/journey-drafts', {
      method: 'POST',
      headers: headers(b.target.brand, 'application/json'),
      credentials: 'include',
      body: JSON.stringify(b.body),
    });
    const respText = await r.text();
    if (!r.ok) {
      console.error(`[${b.target.key}] FAILED: HTTP ${r.status}`, respText);
      throw new Error(`Stopped at ${b.target.key}. Drafts created before it were NOT rolled back: ` +
        (created.map((c) => c.id).join(', ') || 'none'));
    }
    created.push({ key: b.target.key, id: b.body.reservedJourneyId, name: b.name, shared: b.shared });
    console.log(`%c[${b.target.key}] Created ${b.body.reservedJourneyId} — ${b.name}`, 'color:#22c55e');
  }

  console.log('%cDONE. %d draft(s):', 'color:#22c55e;font-weight:bold', created.length);
  console.table(created.map((c) => ({ draft: c.key, journeyId: c.id, name: c.name })));

  console.log('%cBEFORE PUBLISHING — each draft still points at its source campaign\'s promotions.\n' +
    'This script cannot duplicate a promotion, so the promo-lobby entry and every\n' +
    '/services/promo/promotion/<id> link in its SMS, NC and pop-up are the source\'s.\n' +
    'Open each draft and re-point these before it goes live:',
    'color:#ef4444;font-weight:bold');
  for (const c of created) {
    console.log(`  ${c.key} (${c.id})`);
    for (const s of c.shared) console.log(`      ${s}`);
  }
})();
