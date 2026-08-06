// Journey draft capturer — downloads the FULL bodies of one or more existing
// journey drafts, so they can be turned into templates for a generator.
//
// Why this exists: a "Copy as fetch" of a GET /journey-drafts/<id> tells us the
// URL and nothing about the journey — the body is in the *response*. This
// script re-issues those GETs from a logged-in tab and saves what comes back.
//
// HOW TO RUN
//   1. Open the backoffice, logged in, in a normal tab (any page).
//   2. F12 -> Console. Paste this whole file, Enter.
//   3. Click anything in the UI so it fires a request — the token is captured
//      from the page's own traffic (nobody types a token in).
//   4. A file downloads: journey_drafts_capture_<timestamp>.json
//
// The download is scrubbed: any bearer token, cookie, or JWT-shaped string in
// the responses is replaced before the file is written. Save it OUTSIDE the
// repo and hand over the path — these bodies are campaign content, not secrets,
// but the capture is never committed.
(async () => {
  'use strict';

  // Which drafts to pull. brand must match the journey's brand or the API 403s.
  const BASE = "https://pmi.rea-backoffice.gr8.tech/api/ubo/api/v0/crm/journey-builder/v0";
  const DRAFTS = [
    { id: "657225", brand: "PMCL", label: "pmcl_boosted" },
    { id: "657226", brand: "PMCL", label: "pmcl_normal"  },
    { id: "657229", brand: "JBCL", label: "jbcl_normal"  },
    { id: "657230", brand: "JBCL", label: "jbcl_boosted" },
  ];

  const MANUAL_TOKEN = '';

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
      window.fetch = function (i, n) { try { const h = (n && n.headers) || (i && i.headers); if (h) { if (typeof h.get === 'function') take(h.get('authorization')); else if (typeof h === 'object') { for (const k in h) if (/^authorization$/i.test(k)) take(h[k]); } } } catch (e) {} return of.apply(this, arguments); };
      XMLHttpRequest.prototype.setRequestHeader = function (k, v) { try { if (/^authorization$/i.test(k)) take(v); } catch (e) {} return oh.apply(this, arguments); };
      const t = setTimeout(() => { if (!done) { done = true; clean(); reject(new Error('No token in 3 min. Click around the UI and rerun.')); } }, 180000);
      console.log('%cWaiting for a token — click anything in the backoffice UI.', 'color:#eab308');
    });
  }

  // Nothing that can authenticate anybody leaves this page. JWTs are three
  // base64url segments; cookie/auth-ish keys go regardless of their value.
  const JWT_RE = /\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b/g;
  const SECRET_KEY_RE = /^(authorization|cookie|set-cookie|x-api-key|token|access_token|refresh_token|id_token|password|secret)$/i;
  function scrub(value) {
    if (typeof value === 'string') return value.replace(JWT_RE, '<REDACTED-JWT>');
    if (Array.isArray(value)) return value.map(scrub);
    if (value && typeof value === 'object') {
      const out = {};
      for (const [k, v] of Object.entries(value)) out[k] = SECRET_KEY_RE.test(k) ? '<REDACTED>' : scrub(v);
      return out;
    }
    return value;
  }

  const auth = await obtainAuth();
  const H = (brand) => ({ accept: 'application/json, text/plain, */*', authorization: auth, 'x-brand': brand });

  const captured = [];
  for (const d of DRAFTS) {
    const url = BASE + '/journey-drafts/' + d.id;
    const r = await fetch(url, { headers: H(d.brand), credentials: 'include' });
    const text = await r.text();
    if (!r.ok) { console.error('%c' + d.label + ' (' + d.id + ') FAILED HTTP ' + r.status, 'color:#ef4444', text.slice(0, 400)); continue; }
    let draft; try { draft = JSON.parse(text); } catch (e) { console.error(d.label + ': response was not JSON'); continue; }
    captured.push({ id: d.id, brand: d.brand, label: d.label, draft: scrub(draft) });
    console.log('%c' + d.label + ' (' + d.id + ') ok — ' + Math.round(text.length / 1024) + ' KB', 'color:#22c55e');
  }

  if (!captured.length) throw new Error('Nothing captured — every draft failed. Check you are logged in and the ids are right.');

  const payload = { capturedAt: new Date().toISOString(), base: BASE, drafts: captured };
  const json = JSON.stringify(payload, null, 2);
  if (JWT_RE.test(json)) throw new Error('Refusing to download: a JWT survived scrubbing.');

  const stamp = new Date().toISOString().replace(/[-:]/g, '').replace(/\..+/, '');
  const blob = new Blob([json], { type: 'application/json' });
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = 'journey_drafts_capture_' + stamp + '.json';
  document.body.appendChild(a); a.click(); a.remove();
  setTimeout(() => URL.revokeObjectURL(a.href), 10000);

  console.log('%cCaptured ' + captured.length + '/' + DRAFTS.length + ' drafts -> ' + a.download, 'color:#22c55e;font-weight:bold');
})();
