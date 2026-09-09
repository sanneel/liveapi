// JBCL gamification prizes — 12 API-triggered draft(s) — generated 2026-09-09 11:05 -03
// Clones the two source drafts live: money bonus "693903", casino bonus
// "693908". Per prize it reserves a journey id and a promotion display
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
  const MONEY_SOURCE = "693903";
  const CASINO_SOURCE = "693908";
  const PRIZES = [{"group": "cash", "kind": "money", "amount": 90000, "wagering": null, "name": "JBCL | CS&SP | Gamif - money bonus | 90 000", "amountText": "90 000"}, {"group": "cash", "kind": "money", "amount": 120000, "wagering": null, "name": "JBCL | CS&SP | Gamif - money bonus | 120 000", "amountText": "120 000"}, {"group": "cash", "kind": "money", "amount": 150000, "wagering": null, "name": "JBCL | CS&SP | Gamif - money bonus | 150 000", "amountText": "150 000"}, {"group": "1x", "kind": "casino", "amount": 45000, "wagering": 1, "name": "JBCL | CS | Gamif - casino bonus 1x | 45 000", "amountText": "45 000"}, {"group": "1x", "kind": "casino", "amount": 60000, "wagering": 1, "name": "JBCL | CS | Gamif - casino bonus 1x | 60 000", "amountText": "60 000"}, {"group": "3x", "kind": "casino", "amount": 20000, "wagering": 3, "name": "JBCL | CS | Gamif - casino bonus 3x | 20 000", "amountText": "20 000"}, {"group": "3x", "kind": "casino", "amount": 30000, "wagering": 3, "name": "JBCL | CS | Gamif - casino bonus 3x | 30 000", "amountText": "30 000"}, {"group": "5x", "kind": "casino", "amount": 1000, "wagering": 5, "name": "JBCL | CS | Gamif - casino bonus 5x | 1 000", "amountText": "1 000"}, {"group": "5x", "kind": "casino", "amount": 4000, "wagering": 5, "name": "JBCL | CS | Gamif - casino bonus 5x | 4 000", "amountText": "4 000"}, {"group": "5x", "kind": "casino", "amount": 7000, "wagering": 5, "name": "JBCL | CS | Gamif - casino bonus 5x | 7 000", "amountText": "7 000"}, {"group": "5x", "kind": "casino", "amount": 10000, "wagering": 5, "name": "JBCL | CS | Gamif - casino bonus 5x | 10 000", "amountText": "10 000"}, {"group": "5x", "kind": "casino", "amount": 15000, "wagering": 5, "name": "JBCL | CS | Gamif - casino bonus 5x | 15 000", "amountText": "15 000"}];               // [{group, kind, amount, wagering, name, amountText}]
  const POST_KEYS = ["journeyName", "brand", "currencyCodes", "activities", "metadata", "reEntryRule", "timeZoneId", "testControlGroupParameters", "activityEventConversionMetrics", "reservedJourneyId", "journeySource", "isArchived", "isUnlimited", "isImmediatelyAfterPublish", "rawJourneyData", "stopAt", "startAt", "exitCriteriaId"];
  const KEEP_WEBHOOK_ID = false;
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
