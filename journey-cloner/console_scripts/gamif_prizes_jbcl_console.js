// JBCL gamification prizes — 5 API-triggered draft(s) — generated 2026-09-09 12:16 -03
// Clones the two source drafts live: money bonus "JRN-0-685173", casino bonus
// "JRN-0-685183". Per prize it reserves a journey id and a promotion display
// id, regenerates every internal id, writes the amount (and the rollover, for a
// casino bonus) into both storages, gives the API node its own webhookId, then
// creates the draft and saves it. Nothing is published.
(async () => {
  'use strict';
  const MANUAL_TOKEN = '';
  const CRM_ROOT_RE = /^(https?:\/\/[^/]+\/api\/[A-Za-z0-9_-]+\/api\/v0\/crm)(\/|$)/;

  function apiBase(fallback) {
    const marker = '/api/v0/crm';
    const cut = fallback.indexOf(marker);
    if (cut < 0) return fallback;
    const tail = fallback.slice(cut + marker.length);
    const counts = new Map();
    try {
      for (const e of performance.getEntriesByType('resource')) {
        const m = CRM_ROOT_RE.exec(e.name);
        if (m) counts.set(m[1], (counts.get(m[1]) || 0) + 1);
      }
    } catch (e) {}
    if (!counts.size) {
      console.warn('%cNo backoffice API calls in the page history yet, using the baked-in ' + fallback + '. If a call 404s or 405s, click around the UI once and rerun.', 'color:#eab308');
      return fallback;
    }
    const live = [...counts.entries()].sort((a, b) => b[1] - a[1])[0][0] + tail;
    if (live !== fallback) {
      console.warn('%cThis page calls ' + live + ', not ' + fallback + '. Following the page.', 'color:#eab308');
    }
    return live;
  }

  const BASE = apiBase("https://pmi.rea-backoffice.gr8.tech/api/ubo/api/v0/crm/journey-builder/v0");
  const BRAND = "JBCL";
  const MONEY_SOURCE = "JRN-0-685173";
  const CASINO_SOURCE = "JRN-0-685183";
  const PRIZES = [{"group": "5x", "kind": "casino", "amount": 1000, "wagering": 5, "name": "JBCL | CS | Gamif - casino bonus 5x | 1 000", "amountText": "1 000"}, {"group": "5x", "kind": "casino", "amount": 4000, "wagering": 5, "name": "JBCL | CS | Gamif - casino bonus 5x | 4 000", "amountText": "4 000"}, {"group": "5x", "kind": "casino", "amount": 7000, "wagering": 5, "name": "JBCL | CS | Gamif - casino bonus 5x | 7 000", "amountText": "7 000"}, {"group": "5x", "kind": "casino", "amount": 10000, "wagering": 5, "name": "JBCL | CS | Gamif - casino bonus 5x | 10 000", "amountText": "10 000"}, {"group": "5x", "kind": "casino", "amount": 15000, "wagering": 5, "name": "JBCL | CS | Gamif - casino bonus 5x | 15 000", "amountText": "15 000"}];               // [{group, kind, amount, wagering, name, amountText}]
  const POST_KEYS = ["journeyName", "brand", "currencyCodes", "activities", "metadata", "reEntryRule", "timeZoneId", "testControlGroupParameters", "activityEventConversionMetrics", "reservedJourneyId", "journeySource", "isArchived", "isUnlimited", "isImmediatelyAfterPublish", "rawJourneyData", "stopAt", "startAt", "exitCriteriaId"];
  const KEEP_WEBHOOK_ID = false;
  const COPIES = [{"tree": "front", "part": "spa", "files": null}, {"tree": "front", "part": "widget", "files": null}, {"tree": "content", "part": "widgetModulor", "files": ["manifest.json", "content/content-es.json", "content/content-en.json"]}, {"tree": "content", "part": "spa", "files": ["manifest.json", "content/content-es.json", "content/content-en.json", "media/box.png", "media/bonusHeaderImage.png"]}, {"tree": "content", "part": "widget", "files": ["manifest.json", "content/content-es.json", "content/content-en.json", "media/box.png", "media/widgetImgKey.png"]}, {"tree": "content", "part": "cashier", "files": ["manifest.json", "content/content-es.json", "content/content-en.json"]}];               // the six content-tree copies the UI makes
  const CONTENT_PARTS = ["spa", "widget", "widgetModulor", "cashier"]; // the parts whose content-<lang>.json name images
  const WITH_PHOTOS = true;     // one file picker per prize
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
  function parseJsonText(text, label, status) {
    const t = (text || '').trim();
    if (!t) throw new Error(label + ' returned an empty body (HTTP ' + status + ').');
    if (t[0] === '<') throw new Error(label + ' returned HTML, not JSON (HTTP ' + status + '). Wrong route, or the backoffice tab is logged out.');
    try { return JSON.parse(t); } catch (e) { throw new Error(label + ' returned unparseable JSON (HTTP ' + status + '): ' + t.slice(0, 200)); }
  }

  async function readJson(r, label) {
    const text = await r.text();
    if (!r.ok) throw new Error(label + ' HTTP ' + r.status + ' ' + text.slice(0, 400));
    return parseJsonText(text, label, r.status);
  }


  async function createAndSaveDraft(body, label, hdrs) {
    const jsonHeaders = Object.assign({}, hdrs(), { 'content-type': 'application/json' });
    const payload = JSON.stringify(body);
    const r = await fetch(BASE + '/journey-drafts', { method: 'POST', headers: jsonHeaders, credentials: 'include', body: payload });
    const resp = await r.text();
    if (!r.ok) throw new Error(label + ' draft not created: HTTP ' + r.status + ' ' + resp);
    const numId = parseJsonText(resp, label + ' draft create', r.status).id;
    if (!numId) throw new Error(label + ' draft create returned no id: ' + resp.slice(0, 300));
    const rs = await fetch(BASE + '/journey-drafts/' + numId, { method: 'PUT', headers: jsonHeaders, credentials: 'include', body: payload });
    if (!rs.ok) throw new Error(label + ' draft ' + numId + ' was created but the save failed: HTTP ' + rs.status + ' ' + (await rs.text()) + '. Delete that half-made draft before rerunning.');
    return numId;
  }

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
