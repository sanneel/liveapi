// Randomizer console script — Sport Wheel of Fortune — generated 2026-07-03 11:02 UTC
// randomizers: 3: JBCL|SP|WOF|14.07.26, JBCL|SP|WOF|21.07.26, JBCL|SP|WOF|28.07.26
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
  const PAYLOADS = [{"playerVisibility": "Authorized", "showDate": "2026-07-14T04:00:00.0000000Z", "hideDate": "2026-07-15T04:00:00.0000000Z", "startDate": "2026-07-14T04:01:00.0000000Z", "endDate": "2026-07-15T03:59:00.0000000Z", "urlShortName": "sport-14-07-2026", "internalName": "JBCL|SP|WOF|14.07.26", "randomizerShotPolicy": "Once", "randomizationType": "FortuneWheel", "isExternalVisualSettings": false, "isUsedInJourney": false, "daysToAccept": null, "type": "Randomizer", "subType": null, "languages": ["en", "es"], "hasCsv": false, "promoCode": null, "redirect": null, "riskLevels": null, "entrySourceRules": null, "initialShowDate": "2026-07-14T04:00:00.0000000Z", "initialEndDate": "2026-07-15T03:59:00.0000000Z", "currencies": [{"brand": "JBCL", "currency": "CLP"}], "contentId": "50691caf-4694-4a47-9ff2-bac498c3a8ee", "frontId": "a3d54b7c-a8e2-4970-b6d3-7f6ef8e76480", "prizes": [{"weight": "0.1", "type": "JourneyPrize", "isLimitedPrize": false, "prizeQuantity": null, "journeyPrizeSettings": {"journeyId": "JRN-0-222277", "activityId": "73371e55-46e1-47c6-be64-0271db68583f", "isEmptyPrize": false, "activityDescription": "JBCL | SP | RB - Wheel of fortune | Free | Money"}}, {"weight": "3", "type": "JourneyPrize", "isLimitedPrize": false, "prizeQuantity": null, "journeyPrizeSettings": {"journeyId": "JRN-0-253210", "activityId": "2db95ef0-2098-4eb6-a078-28e779620026", "isEmptyPrize": false, "activityDescription": "JBCL | SP | RB - Wheel of fortune | Free | Bonuses"}}, {"weight": "25", "type": "JourneyPrize", "isLimitedPrize": false, "prizeQuantity": null, "journeyPrizeSettings": {"journeyId": "JRN-0-253216", "activityId": "1faa001a-f221-4f53-b184-75e564aa1a60", "isEmptyPrize": false, "activityDescription": "JBCL | SP | RB - Wheel of fortune | Dep | Bonus"}}, {"weight": "10", "type": "JourneyPrize", "isLimitedPrize": false, "prizeQuantity": null, "journeyPrizeSettings": {"journeyId": "JRN-0-253218", "activityId": "b6148588-a5c8-4cf9-ace8-1af8574f7deb", "isEmptyPrize": false, "activityDescription": "JBCL | SP | RB - Wheel of fortune | Bet | Insurance"}}, {"weight": "36.9", "type": "JourneyPrize", "isLimitedPrize": false, "prizeQuantity": null, "journeyPrizeSettings": {"journeyId": "JRN-0-222272", "activityId": "ff2e626c-7ec7-4c1c-859e-078ef18004be", "isEmptyPrize": false, "activityDescription": "JBCL | SP | RB - Wheel of fortune | Dep | Freebet"}}, {"weight": "25", "type": "JourneyPrize", "isLimitedPrize": false, "prizeQuantity": null, "journeyPrizeSettings": {"journeyId": "JRN-0-222271", "activityId": "62b2f5c3-d12f-4a17-bbb0-a8d9a328cd41", "isEmptyPrize": false, "activityDescription": "JBCL | SP | RB - Wheel of fortune | Bet | Freebet"}}], "filterConditions": [{"conditionType": "MultiSelect", "key": "Sport", "filterType": "fairplay_sport_segment", "displayName": "fairplay_sport_segment", "operator": "notIn", "values": [{"id": 40, "name": "VIP-Platinum"}, {"id": 42, "name": "VIP-Silver"}, {"id": 41, "name": "VIP-Gold"}, {"id": 36, "name": "Suspicious"}, {"id": 51, "name": "Scammer"}, {"id": 39, "name": "No status"}, {"id": 48, "name": "Monitoring"}, {"id": 47, "name": "Dangerous"}, {"id": 49, "name": "Arbitrageur"}, {"id": 45, "name": "Good guys-X"}]}]}, {"playerVisibility": "Authorized", "showDate": "2026-07-21T04:00:00.0000000Z", "hideDate": "2026-07-22T04:00:00.0000000Z", "startDate": "2026-07-21T04:01:00.0000000Z", "endDate": "2026-07-22T03:59:00.0000000Z", "urlShortName": "sport-21-07-2026", "internalName": "JBCL|SP|WOF|21.07.26", "randomizerShotPolicy": "Once", "randomizationType": "FortuneWheel", "isExternalVisualSettings": false, "isUsedInJourney": false, "daysToAccept": null, "type": "Randomizer", "subType": null, "languages": ["en", "es"], "hasCsv": false, "promoCode": null, "redirect": null, "riskLevels": null, "entrySourceRules": null, "initialShowDate": "2026-07-21T04:00:00.0000000Z", "initialEndDate": "2026-07-22T03:59:00.0000000Z", "currencies": [{"brand": "JBCL", "currency": "CLP"}], "contentId": "50691caf-4694-4a47-9ff2-bac498c3a8ee", "frontId": "a3d54b7c-a8e2-4970-b6d3-7f6ef8e76480", "prizes": [{"weight": "0.1", "type": "JourneyPrize", "isLimitedPrize": false, "prizeQuantity": null, "journeyPrizeSettings": {"journeyId": "JRN-0-222277", "activityId": "73371e55-46e1-47c6-be64-0271db68583f", "isEmptyPrize": false, "activityDescription": "JBCL | SP | RB - Wheel of fortune | Free | Money"}}, {"weight": "3", "type": "JourneyPrize", "isLimitedPrize": false, "prizeQuantity": null, "journeyPrizeSettings": {"journeyId": "JRN-0-253210", "activityId": "2db95ef0-2098-4eb6-a078-28e779620026", "isEmptyPrize": false, "activityDescription": "JBCL | SP | RB - Wheel of fortune | Free | Bonuses"}}, {"weight": "25", "type": "JourneyPrize", "isLimitedPrize": false, "prizeQuantity": null, "journeyPrizeSettings": {"journeyId": "JRN-0-253216", "activityId": "1faa001a-f221-4f53-b184-75e564aa1a60", "isEmptyPrize": false, "activityDescription": "JBCL | SP | RB - Wheel of fortune | Dep | Bonus"}}, {"weight": "10", "type": "JourneyPrize", "isLimitedPrize": false, "prizeQuantity": null, "journeyPrizeSettings": {"journeyId": "JRN-0-253218", "activityId": "b6148588-a5c8-4cf9-ace8-1af8574f7deb", "isEmptyPrize": false, "activityDescription": "JBCL | SP | RB - Wheel of fortune | Bet | Insurance"}}, {"weight": "36.9", "type": "JourneyPrize", "isLimitedPrize": false, "prizeQuantity": null, "journeyPrizeSettings": {"journeyId": "JRN-0-222272", "activityId": "ff2e626c-7ec7-4c1c-859e-078ef18004be", "isEmptyPrize": false, "activityDescription": "JBCL | SP | RB - Wheel of fortune | Dep | Freebet"}}, {"weight": "25", "type": "JourneyPrize", "isLimitedPrize": false, "prizeQuantity": null, "journeyPrizeSettings": {"journeyId": "JRN-0-222271", "activityId": "62b2f5c3-d12f-4a17-bbb0-a8d9a328cd41", "isEmptyPrize": false, "activityDescription": "JBCL | SP | RB - Wheel of fortune | Bet | Freebet"}}], "filterConditions": [{"conditionType": "MultiSelect", "key": "Sport", "filterType": "fairplay_sport_segment", "displayName": "fairplay_sport_segment", "operator": "notIn", "values": [{"id": 40, "name": "VIP-Platinum"}, {"id": 42, "name": "VIP-Silver"}, {"id": 41, "name": "VIP-Gold"}, {"id": 36, "name": "Suspicious"}, {"id": 51, "name": "Scammer"}, {"id": 39, "name": "No status"}, {"id": 48, "name": "Monitoring"}, {"id": 47, "name": "Dangerous"}, {"id": 49, "name": "Arbitrageur"}, {"id": 45, "name": "Good guys-X"}]}]}, {"playerVisibility": "Authorized", "showDate": "2026-07-28T04:00:00.0000000Z", "hideDate": "2026-07-29T04:00:00.0000000Z", "startDate": "2026-07-28T04:01:00.0000000Z", "endDate": "2026-07-29T03:59:00.0000000Z", "urlShortName": "sport-28-07-2026", "internalName": "JBCL|SP|WOF|28.07.26", "randomizerShotPolicy": "Once", "randomizationType": "FortuneWheel", "isExternalVisualSettings": false, "isUsedInJourney": false, "daysToAccept": null, "type": "Randomizer", "subType": null, "languages": ["en", "es"], "hasCsv": false, "promoCode": null, "redirect": null, "riskLevels": null, "entrySourceRules": null, "initialShowDate": "2026-07-28T04:00:00.0000000Z", "initialEndDate": "2026-07-29T03:59:00.0000000Z", "currencies": [{"brand": "JBCL", "currency": "CLP"}], "contentId": "50691caf-4694-4a47-9ff2-bac498c3a8ee", "frontId": "a3d54b7c-a8e2-4970-b6d3-7f6ef8e76480", "prizes": [{"weight": "0.1", "type": "JourneyPrize", "isLimitedPrize": false, "prizeQuantity": null, "journeyPrizeSettings": {"journeyId": "JRN-0-222277", "activityId": "73371e55-46e1-47c6-be64-0271db68583f", "isEmptyPrize": false, "activityDescription": "JBCL | SP | RB - Wheel of fortune | Free | Money"}}, {"weight": "3", "type": "JourneyPrize", "isLimitedPrize": false, "prizeQuantity": null, "journeyPrizeSettings": {"journeyId": "JRN-0-253210", "activityId": "2db95ef0-2098-4eb6-a078-28e779620026", "isEmptyPrize": false, "activityDescription": "JBCL | SP | RB - Wheel of fortune | Free | Bonuses"}}, {"weight": "25", "type": "JourneyPrize", "isLimitedPrize": false, "prizeQuantity": null, "journeyPrizeSettings": {"journeyId": "JRN-0-253216", "activityId": "1faa001a-f221-4f53-b184-75e564aa1a60", "isEmptyPrize": false, "activityDescription": "JBCL | SP | RB - Wheel of fortune | Dep | Bonus"}}, {"weight": "10", "type": "JourneyPrize", "isLimitedPrize": false, "prizeQuantity": null, "journeyPrizeSettings": {"journeyId": "JRN-0-253218", "activityId": "b6148588-a5c8-4cf9-ace8-1af8574f7deb", "isEmptyPrize": false, "activityDescription": "JBCL | SP | RB - Wheel of fortune | Bet | Insurance"}}, {"weight": "36.9", "type": "JourneyPrize", "isLimitedPrize": false, "prizeQuantity": null, "journeyPrizeSettings": {"journeyId": "JRN-0-222272", "activityId": "ff2e626c-7ec7-4c1c-859e-078ef18004be", "isEmptyPrize": false, "activityDescription": "JBCL | SP | RB - Wheel of fortune | Dep | Freebet"}}, {"weight": "25", "type": "JourneyPrize", "isLimitedPrize": false, "prizeQuantity": null, "journeyPrizeSettings": {"journeyId": "JRN-0-222271", "activityId": "62b2f5c3-d12f-4a17-bbb0-a8d9a328cd41", "isEmptyPrize": false, "activityDescription": "JBCL | SP | RB - Wheel of fortune | Bet | Freebet"}}], "filterConditions": [{"conditionType": "MultiSelect", "key": "Sport", "filterType": "fairplay_sport_segment", "displayName": "fairplay_sport_segment", "operator": "notIn", "values": [{"id": 40, "name": "VIP-Platinum"}, {"id": 42, "name": "VIP-Silver"}, {"id": 41, "name": "VIP-Gold"}, {"id": 36, "name": "Suspicious"}, {"id": 51, "name": "Scammer"}, {"id": 39, "name": "No status"}, {"id": 48, "name": "Monitoring"}, {"id": 47, "name": "Dangerous"}, {"id": 49, "name": "Arbitrageur"}, {"id": 45, "name": "Good guys-X"}]}]}];     // one randomizer body per date
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
