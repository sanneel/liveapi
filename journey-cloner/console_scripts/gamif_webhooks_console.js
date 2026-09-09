// Webhook URLs for 12 journey(s) — generated 2026-09-09 12:15 -03
// Read-only: it fetches each journey, reads its API node and its bonus, and
// prints the amount / rollover / webhook table. Nothing is created or changed.
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
  const IDS = ["JRN-0-685173", "JRN-0-685175", "JRN-0-685177", "JRN-0-685178", "JRN-0-685180", "JRN-0-685182", "JRN-0-685183", "JRN-0-685242", "JRN-0-685244", "JRN-0-685245", "JRN-0-685096", "JRN-0-685110"];
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


  const walk = (o, fn) => {
    if (Array.isArray(o)) { o.forEach((v) => walk(v, fn)); return; }
    if (o && typeof o === 'object') { fn(o); Object.values(o).forEach((v) => walk(v, fn)); }
  };
  const spaced = (n) => String(n).replace(/\B(?=(\d{3})+(?!\d))/g, ' ');

  async function getJourney(id) {
    const r = await fetch(BASE + '/journeys/' + id, { headers: H(), credentials: 'include' });
    const t = await r.text();
    if (!r.ok) throw new Error('HTTP ' + r.status + ' ' + t.slice(0, 160));
    return parseJsonText(t, 'journey ' + id, r.status);
  }

  // The URL is composed by the backoffice, not stored on the activity, so it is
  // asked for once and reused. Whatever this endpoint answers is printed raw the
  // first time, which is how the shape gets pinned down for good.
  let urlTemplate = null, configShown = false;
  async function webhookUrlFor(id, activity) {
    const direct = activity.initializationData && (activity.initializationData.webhookUrl || activity.initializationData.url);
    if (direct) return direct;
    if (urlTemplate === null) {
      urlTemplate = '';
      try {
        const r = await fetch(BASE + '/journey-activities/external-system-source', { headers: H(), credentials: 'include' });
        const t = await r.text();
        if (r.ok) {
          if (!configShown) { console.log('    external-system-source config:', t.slice(0, 400)); configShown = true; }
          const m = t.match(/https?:\/\/[^"'\s]+/);
          if (m) urlTemplate = m[0];
        }
      } catch (e) {}
    }
    if (!urlTemplate) return '';
    const wid = activity.initializationData.webhookId;
    return urlTemplate.includes('{') ? urlTemplate.replace(/\{[^}]*\}/, wid)
         : urlTemplate.replace(/\/+$/, '') + '/' + wid;
  }

  // What the journey actually grants, read from the mechanic rather than from
  // the name: a money bonus keeps major units, a casino bonus minor units with
  // a _majorUnits twin, and the rollover is the casino bonus's own.
  function prizeOf(j) {
    let major = null, rollover = null, kind = '';
    walk(j, (o) => {
      if ('fixedBonusAmount_majorUnits' in o) { major = o.fixedBonusAmount_majorUnits; kind = 'casino bonus'; }
      if (Array.isArray(o.currencyAmounts)) for (const c of o.currencyAmounts) if (typeof c.amount === 'number') { major = c.amount; kind = 'money bonus'; }
      if (typeof o.wageringRequirement === 'number') rollover = o.wageringRequirement;
    });
    return { major: major, rollover: kind === 'casino bonus' ? rollover : null, kind: kind };
  }

  console.log('%cWebhook URLs — ' + IDS.length + ' journey(s)', 'color:#3b82f6;font-weight:bold;font-size:14px');
  const rows = [], missing = [];
  for (const id of IDS) {
    try {
      const j = await getJourney(id);
      const api = (j.activities || []).find((a) => a.activityName === 'external_system_source');
      if (!api) { missing.push({ id: id, name: j.journeyName, why: 'does not start at an API node' }); continue; }
      const wid = (api.initializationData || {}).webhookId || '';
      if (!wid) { missing.push({ id: id, name: j.journeyName, why: 'the API node carries no webhookId' }); continue; }
      const p = prizeOf(j);
      rows.push({
        id: id,
        name: (j.journeyName || '').trim(),
        amount: p.major === null ? '?' : spaced(p.major),
        prize: p.rollover ? p.rollover + 'x' : (p.kind || '?'),
        webhookId: wid,
        url: await webhookUrlFor(id, api),
      });
      console.log('    ' + id + '  ' + (j.journeyName || '').trim());
    } catch (e) {
      missing.push({ id: id, why: String((e && e.message) || e) });
      console.error('    ✗ ' + id + ' — ' + String((e && e.message) || e));
    }
  }

  console.log('%c' + rows.length + ' of ' + IDS.length + ' read.', 'color:' + (rows.length === IDS.length ? '#22c55e' : '#f59e0b') + ';font-weight:bold;font-size:14px');
  if (rows.length) console.table(rows);
  if (missing.length) { console.log('%cNot listed:', 'color:#f59e0b;font-weight:bold'); console.table(missing); }

  const pad = (s, n) => String(s).padEnd(n);
  const text = rows.map((r) => pad(r.amount, 10) + pad(r.prize, 14) + (r.url || r.webhookId)).join('\n');
  console.log('%cThe table, ready to copy:', 'color:#3b82f6;font-weight:bold');
  console.log(text);
  const tsv = rows.map((r) => [r.amount, r.prize, r.url || r.webhookId, r.id, r.name].join('\t')).join('\n');
  window.__webhookRows = rows;
  window.__webhookTsv = tsv;
  try { await navigator.clipboard.writeText(text); console.log('%cCopied to the clipboard.', 'color:#22c55e'); }
  catch (e) { console.log('Clipboard blocked; copy the block above, or copy(window.__webhookTsv) for a spreadsheet.'); }
  if (rows.some((r) => !r.url)) {
    console.log('%cNo URL came back for ' + rows.filter((r) => !r.url).length + ' of them, so the ids are shown instead.', 'color:#eab308;font-weight:bold');
    console.log('Open one journey\'s API node, copy its Webhook URL, and send it — the pattern then fills in for every row.');
  }
})();
