// Randomizer console script — Casino Wheel of Fortune — generated 2026-07-02 13:35 UTC
// randomizers: 1: JBCL|CS|WOF|22.07.26
//
// Paste into the DevTools console on a logged-in backoffice tab. It:
//   1. captures the auth token from the page's own requests,
//   2. for EACH randomizer in the batch: creates a draft
//      (POST /promo/v2/promo-drafts/randomizer) then fills it (POST /promo/v2/randomizer?draftId=<id>).
// One bad one doesn't stop the rest; a summary prints at the end.
// Set PREVIEW=true to log the request bodies WITHOUT sending them.
// Set DEBUG=true to create ONE draft and print the create response (to find
// the right fill identifier) without attempting the fill.
(async () => {
  'use strict';
  const PREVIEW = false;
  const MANUAL_TOKEN = '';
  const BASE = "https://pmi.rea-backoffice.gr8.tech/api/ubo/api/v0/crm/journey-builder/v0";
  const BRAND = "JBCL";
  const FLOW = "draftid_post";             // 'create_put' | 'draftid_post'
  const PAYLOADS = [{"randomizationType": "FortuneWheel", "type": "Randomizer", "isExternalVisualSettings": false, "internalName": "JBCL|CS|WOF|22.07.26", "promoCode": null, "randomizerShotPolicy": "Once", "showDate": "2026-07-22T04:01:00.0000000Z", "startDate": "2026-07-22T04:02:00.0000000Z", "endDate": "2026-07-25T03:58:00.0000000Z", "hideDate": "2026-07-25T03:59:00.0000000Z", "daysToAccept": null, "currencies": [{"brand": "JBCL", "currency": "CLP"}], "currencyMode": "single", "urlShortName": "22-07-26", "playerVisibility": "Authorized", "filterConditions": [{"values": [{"id": 34, "name": "Premium"}, {"id": 31, "name": "Negative"}], "conditionType": "MultiSelect", "key": "Business", "filterType": "fairplay_business_segment", "displayName": "fairplay_business_segment", "operator": "notIn"}], "promotionDisplayId": null, "languages": ["en", "es"], "prizes": [{"id": "3b286e69-b355-420a-a960-4db936a874c4", "weight": "60", "type": "JourneyPrize", "isEmptyPrize": false, "isLimitedPrize": false, "prizeQuantity": null, "journeyPrizeSettings": {"journeyId": "JRN-0-572381", "activityId": "3b286e69-b355-420a-a960-4db936a874c4", "activityDescription": "Wheel of fortune | 50FS to dep", "isEmptyPrize": false}}, {"id": "65ed8cee-45b8-48bc-9ef3-69149b78a6d3", "weight": "30", "type": "JourneyPrize", "isEmptyPrize": false, "isLimitedPrize": false, "prizeQuantity": null, "journeyPrizeSettings": {"journeyId": "JRN-0-572307", "activityId": "65ed8cee-45b8-48bc-9ef3-69149b78a6d3", "activityDescription": "JBCL | CS | RB - Wheel of fortune | dep bonuses", "isEmptyPrize": false}}, {"id": "f1804fa5-a469-4493-9c9a-420c1f89dd86", "weight": "8", "type": "JourneyPrize", "isEmptyPrize": false, "isLimitedPrize": false, "prizeQuantity": null, "journeyPrizeSettings": {"journeyId": "JRN-0-423152", "activityId": "f1804fa5-a469-4493-9c9a-420c1f89dd86", "activityDescription": "JBCL | 50 FS no-dep Wheel of Fortune ", "isEmptyPrize": false}}, {"id": "0feeaefe-08a0-4a85-bcff-b572b47e3d1b", "weight": "2", "type": "JourneyPrize", "isEmptyPrize": false, "isLimitedPrize": false, "prizeQuantity": null, "journeyPrizeSettings": {"journeyId": "JRN-0-572386", "activityId": "0feeaefe-08a0-4a85-bcff-b572b47e3d1b", "activityDescription": "JBCL | 50 FS no-dep Wheel of Fortune ", "isEmptyPrize": false}}], "isUsedInJourney": false, "completedBy": null, "riskLevels": null, "contentId": "7ba28ac6-a192-4e7c-90fd-3f76e3ffe8df", "frontId": "83d4e58a-fbcd-4300-b20b-50482bcc6b36"}];     // one randomizer body per date
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
  const headers = () => ({ accept: 'application/json, text/plain, */*', authorization: auth, 'content-type': 'application/json', 'x-brand': BRAND });

  if (PREVIEW) {
    console.log('%cPREVIEW — not sending. ' + PAYLOADS.length + ' randomizer(s):', 'color:#eab308;font-weight:bold');
    PAYLOADS.forEach((P) => console.log(P.internalName + '  (' + P.showDate + ')', P));
    return;
  }

  // While the exact fill identifier is being confirmed, DEBUG=true creates ONE
  // draft, logs the full create response (so we can see which field is the
  // randomization id), and does NOT attempt the fill — avoids piling up orphans.
  const DEBUG = false;

  // create one draft then fill it; returns the new draft id
  async function createOne(P) {
    let r = await fetch(CRM_BASE + '/promo/v2/promo-drafts/randomizer', { method: 'POST', headers: headers(), credentials: 'include', body: JSON.stringify(P) });
    let resp = await r.text();
    if (!r.ok) throw new Error('create HTTP ' + r.status + ' ' + resp);
    let created = {}; try { created = JSON.parse(resp); } catch (e) {}
    if (DEBUG) {
      console.log('%cCREATE RESPONSE (copy this whole object to share):', 'color:#eab308;font-weight:bold');
      console.log(JSON.stringify(created, null, 2));
      console.log('%ctop-level keys: ' + Object.keys(created).join(', '), 'color:#eab308');
      throw new Error('DEBUG mode — stopped before fill so nothing else is created. See CREATE RESPONSE above.');
    }
    const id = created.id || created.draftId || created.promotionDraftId || (created.data && created.data.id);
    if (!id) throw new Error('no draft id in create response: ' + resp);
    if (FLOW === 'draftid_post') {
      r = await fetch(CRM_BASE + '/promo/v2/randomizer?draftId=' + encodeURIComponent(id), { method: 'POST', headers: headers(), credentials: 'include', body: JSON.stringify(P) });
    } else {
      // the fill model wants id as a STRING (a numeric id 400s with
      // "$.id could not be converted to System.String").
      r = await fetch(CRM_BASE + '/promo/v2/randomizer/' + encodeURIComponent(id), { method: 'PUT', headers: headers(), credentials: 'include', body: JSON.stringify({ ...P, id: String(id) }) });
    }
    resp = await r.text();
    if (!r.ok) throw new Error('draft ' + id + ' created but fill failed HTTP ' + r.status + ' ' + resp);
    return id;
  }

  const QUEUE = DEBUG ? PAYLOADS.slice(0, 1) : PAYLOADS;
  console.log('Creating ' + QUEUE.length + ' randomizer draft(s)...' + (DEBUG ? ' (DEBUG: 1 only, no fill)' : ''));
  const ok = [], fail = [];
  for (const P of PAYLOADS) {
    console.log('  ' + P.internalName + ' ...');
    try { const id = await createOne(P); ok.push({ name: P.internalName, id }); console.log('%c    ✓ ' + id, 'color:#22c55e'); }
    catch (e) { const msg = String((e && e.message) || e); fail.push({ name: P.internalName, err: msg }); console.error('    ✗ ' + P.internalName + ' — ' + msg); }
  }

  console.log('%cDONE — ' + ok.length + ' created, ' + fail.length + ' failed.',
              'color:' + (fail.length ? '#f59e0b' : '#22c55e') + ';font-weight:bold;font-size:14px');
  ok.forEach((o) => console.log('  ✓ ' + o.id + '  (' + o.name + ')'));
  fail.forEach((f) => console.log('  ✗ ' + f.name + ' — ' + f.err));
})();
