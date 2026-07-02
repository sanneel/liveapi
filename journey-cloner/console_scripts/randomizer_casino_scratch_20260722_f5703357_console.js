// Randomizer console script — Raspa y Gana (Scratch Card) — generated 2026-07-02 13:35 UTC
// randomizers: 2: FTCL|CS|FDSC|22.07, FTCL|CS|FDSC|29.07
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
  const BRAND = "PMCL";
  const FLOW = "draftid_post";             // 'create_put' | 'draftid_post'
  const PAYLOADS = [{"randomizationType": "ScratchCard", "type": "Randomizer", "isExternalVisualSettings": false, "internalName": "FTCL|CS|FDSC|22.07", "promoCode": null, "randomizerShotPolicy": "Once", "showDate": "2026-07-22T04:00:00.0000000Z", "startDate": "2026-07-22T04:01:00.0000000Z", "endDate": "2026-07-24T03:59:00.0000000Z", "hideDate": "2026-07-24T04:00:00.0000000Z", "daysToAccept": null, "currencies": [{"brand": "PMCL", "currency": "CLP"}], "currencyMode": "single", "urlShortName": "22-07-26", "playerVisibility": "Authorized", "filterConditions": [{"values": [{"id": 31, "name": "Negative"}, {"id": 34, "name": "Premium"}], "conditionType": "MultiSelect", "key": "Business", "filterType": "fairplay_business_segment", "displayName": "fairplay_business_segment", "operator": "notIn"}], "promotionDisplayId": null, "languages": ["es"], "prizes": [{"id": "41056226-cbd5-4bc2-ac92-6d29ccf1a87e", "weight": 3, "type": "JourneyPrize", "isEmptyPrize": false, "isLimitedPrize": false, "prizeQuantity": null, "journeyPrizeSettings": {"journeyId": "JRN-0-424485", "activityId": "41056226-cbd5-4bc2-ac92-6d29ccf1a87e", "activityDescription": "PMCL | CS | RB - Weekend Scratch Card - 100 No deposit FS", "isEmptyPrize": false}}, {"id": "7b7a3306-9fba-44bd-aeab-186f84a1d248", "weight": 50, "type": "JourneyPrize", "isEmptyPrize": false, "isLimitedPrize": false, "prizeQuantity": null, "journeyPrizeSettings": {"journeyId": "JRN-0-426567", "activityId": "7b7a3306-9fba-44bd-aeab-186f84a1d248", "activityDescription": "PMCL | CS | RB - Weekend Scratch Card - 50 deposit FS", "isEmptyPrize": false}}, {"id": "454f0df8-0d80-41b6-9001-c68a5c2c671e", "weight": 42, "type": "JourneyPrize", "isEmptyPrize": false, "isLimitedPrize": false, "prizeQuantity": null, "journeyPrizeSettings": {"journeyId": "JRN-0-426571", "activityId": "454f0df8-0d80-41b6-9001-c68a5c2c671e", "activityDescription": "PMCL | CS | RB - Weekend Scratch Card - 50% deposit bonus", "isEmptyPrize": false}}, {"id": "95fb49fd-d895-42ee-9a54-e5b5997eb878", "weight": 5, "type": "JourneyPrize", "isEmptyPrize": false, "isLimitedPrize": false, "prizeQuantity": null, "journeyPrizeSettings": {"journeyId": "JRN-0-426582", "activityId": "95fb49fd-d895-42ee-9a54-e5b5997eb878", "activityDescription": "PMCL | CS | RB - Weekend Scratch Card - 100% deposit bonus", "isEmptyPrize": false}}, {"id": "a0e58dd8-5ea5-4fe9-ade4-ac321b952d00", "weight": 0, "type": "JourneyPrize", "isEmptyPrize": true, "isLimitedPrize": false, "prizeQuantity": null, "journeyPrizeSettings": {"journeyId": "JRN-0-426590", "activityId": "a0e58dd8-5ea5-4fe9-ade4-ac321b952d00", "activityDescription": "PMCL | CS | RB - Weekend Scratch Card - empty prize", "isEmptyPrize": true}}], "isUsedInJourney": false, "completedBy": null, "riskLevels": null, "contentId": "1185f89f-eb30-4053-a3a9-11b7839ab782", "frontId": "c02fbc11-d41b-4589-ba4d-cdcd40d352c5"}, {"randomizationType": "ScratchCard", "type": "Randomizer", "isExternalVisualSettings": false, "internalName": "FTCL|CS|FDSC|29.07", "promoCode": null, "randomizerShotPolicy": "Once", "showDate": "2026-07-29T04:00:00.0000000Z", "startDate": "2026-07-29T04:01:00.0000000Z", "endDate": "2026-07-31T03:59:00.0000000Z", "hideDate": "2026-07-31T04:00:00.0000000Z", "daysToAccept": null, "currencies": [{"brand": "PMCL", "currency": "CLP"}], "currencyMode": "single", "urlShortName": "29-07-26", "playerVisibility": "Authorized", "filterConditions": [{"values": [{"id": 31, "name": "Negative"}, {"id": 34, "name": "Premium"}], "conditionType": "MultiSelect", "key": "Business", "filterType": "fairplay_business_segment", "displayName": "fairplay_business_segment", "operator": "notIn"}], "promotionDisplayId": null, "languages": ["es"], "prizes": [{"id": "41056226-cbd5-4bc2-ac92-6d29ccf1a87e", "weight": 3, "type": "JourneyPrize", "isEmptyPrize": false, "isLimitedPrize": false, "prizeQuantity": null, "journeyPrizeSettings": {"journeyId": "JRN-0-424485", "activityId": "41056226-cbd5-4bc2-ac92-6d29ccf1a87e", "activityDescription": "PMCL | CS | RB - Weekend Scratch Card - 100 No deposit FS", "isEmptyPrize": false}}, {"id": "7b7a3306-9fba-44bd-aeab-186f84a1d248", "weight": 50, "type": "JourneyPrize", "isEmptyPrize": false, "isLimitedPrize": false, "prizeQuantity": null, "journeyPrizeSettings": {"journeyId": "JRN-0-426567", "activityId": "7b7a3306-9fba-44bd-aeab-186f84a1d248", "activityDescription": "PMCL | CS | RB - Weekend Scratch Card - 50 deposit FS", "isEmptyPrize": false}}, {"id": "454f0df8-0d80-41b6-9001-c68a5c2c671e", "weight": 42, "type": "JourneyPrize", "isEmptyPrize": false, "isLimitedPrize": false, "prizeQuantity": null, "journeyPrizeSettings": {"journeyId": "JRN-0-426571", "activityId": "454f0df8-0d80-41b6-9001-c68a5c2c671e", "activityDescription": "PMCL | CS | RB - Weekend Scratch Card - 50% deposit bonus", "isEmptyPrize": false}}, {"id": "95fb49fd-d895-42ee-9a54-e5b5997eb878", "weight": 5, "type": "JourneyPrize", "isEmptyPrize": false, "isLimitedPrize": false, "prizeQuantity": null, "journeyPrizeSettings": {"journeyId": "JRN-0-426582", "activityId": "95fb49fd-d895-42ee-9a54-e5b5997eb878", "activityDescription": "PMCL | CS | RB - Weekend Scratch Card - 100% deposit bonus", "isEmptyPrize": false}}, {"id": "a0e58dd8-5ea5-4fe9-ade4-ac321b952d00", "weight": 0, "type": "JourneyPrize", "isEmptyPrize": true, "isLimitedPrize": false, "prizeQuantity": null, "journeyPrizeSettings": {"journeyId": "JRN-0-426590", "activityId": "a0e58dd8-5ea5-4fe9-ade4-ac321b952d00", "activityDescription": "PMCL | CS | RB - Weekend Scratch Card - empty prize", "isEmptyPrize": true}}], "isUsedInJourney": false, "completedBy": null, "riskLevels": null, "contentId": "1185f89f-eb30-4053-a3a9-11b7839ab782", "frontId": "c02fbc11-d41b-4589-ba4d-cdcd40d352c5"}];     // one randomizer body per date
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
