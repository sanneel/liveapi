#!/usr/bin/env python3
"""
Build the FULL "Game of the Week" promo in one console script: the casino
free-spin journey + promo page (gow_campaign.py) AND the communications
journey (comms_campaign.py: Notification + Pop-up + SMS, Email left
untouched) — created together, with the comms links pointed at the exact
promo-page id the campaign step generates. No promo-page-id needs to be
typed in by hand; it is captured client-side mid-script.

Everything (game/provider/bets and all NC/Pop-up/SMS copy) is read from one
pasted spec blob (see spec_parser.py) -- only the date is a separate input.

Usage:
  python gow_combined.py --date 2026-07-01 --spec spec.txt

Then paste console_scripts/<name>_console.js into the DevTools console on a
logged-in backoffice tab. Three file pickers will pop up in turn: the
campaign photo, then the NC icon, then the Pop-up background. Use --dry-run
to write both prepared payloads to out/ without generating a script.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

from create_journeys import BRAND, LOCAL_TZ
from casino_journey import (
    DEFAULT_BASE_URL,
    chile_same_day_window,
    resolve_game,
    utc_dotnet,
    verify as casino_verify,
)
from gow_campaign import (
    DEFAULT_PROMO_DESCRIPTION,
    DEFAULT_PROMO_SOURCE_CONTENT_ID,
    DEFAULT_PROMO_SOURCE_FRONT_ID,
    PLACEMENTS,
    PROMO_REWARD_IDS,
    WEEKDAYS_EN,
    WEEKDAYS_ES,
    prepare_campaign,
)
from comms_campaign import (
    DEFAULT_FOLDER_ID,
    DEFAULT_PUBLIC_DOMAIN,
    EMAIL_CONTENT_ID_TOKEN,
    EMAIL_HERO_TOKEN,
    EMAIL_PROMO_TOKEN,
    NC_ICON_TOKEN,
    POPUP_BG_TOKEN,
    email_dict_from_spec,
    make_cs_variant,
    RESERVED_ID_CS_TOKEN,
    nc_dict_from_spec,
    popup_dict_from_spec,
    prepare_comms,
    sms_dict_from_spec,
    verify as comms_verify,
)
from spec_parser import parse_spec

RESERVED_CAMPAIGN_ID_TOKEN = "DRY-RUN-CASINO"
RESERVED_COMMS_ID_TOKEN = "DRY-RUN-COMMS"
PROMO_PAGE_ID_TOKEN = "@@PROMO_PAGE_ID@@"


def prepare_both(
    *,
    date_str: str,
    days: int,
    game: dict[str, str],
    bets_major: list[int],
    spins: int | None,
    public_domain: str,
    journey_name: str,
    nc: dict[str, str],
    popup: dict[str, str],
    sms: dict[str, str],
    email: dict[str, str] | None = None,
):
    campaign_body, campaign_report, start_local, stop_local = prepare_campaign(
        date_str=date_str, days=days, game=game, bets_major=bets_major,
        spins=spins, reserved_id=RESERVED_CAMPAIGN_ID_TOKEN,
    )
    # The comms entry window is always same-day 12:00->19:00 Chile time on
    # --date, independent of the campaign's own (possibly multi-day) window.
    # The promo page is created in this same run, so its id is only known at
    # paste time — promo links stay as PROMO_PAGE_ID_TOKEN here (in both the
    # journey payload and the email content) and the console script fills them.
    comms_body, comms_report, comms_start_local, comms_stop_local, email_content = prepare_comms(
        date_str=date_str,
        promo_page_id=PROMO_PAGE_ID_TOKEN,
        public_domain=public_domain,
        journey_name=journey_name,
        nc=nc, popup=popup, sms=sms, email=email,
    )
    comms_body["reservedJourneyId"] = RESERVED_COMMS_ID_TOKEN
    return (
        campaign_body, comms_body, campaign_report, comms_report,
        start_local, stop_local, comms_start_local, comms_stop_local, email_content,
    )


JS_TEMPLATE = r"""// GOW combined console script (campaign + comms) — generated @GENERATED_AT@
// Campaign journey: @CAMPAIGN_JOURNEY_NAME@
// Comms journey:    @COMMS_JOURNEY_NAME@
//
// Paste into the DevTools console on a logged-in backoffice tab. It will, in
// order:
//   1. capture the auth token from the page's own requests,
//   2. STEP 1/2 -- CAMPAIGN: pop up a file picker for the campaign photo,
//      reserve a journey id, create the free-spin journey draft, fork the 5
//      placements' visual bundles + upload the photo, fork + upload the
//      promo-page visual bundle, and create the Promo Page draft.
//   3. STEP 2/2 -- COMMS: pop up file pickers for the NC icon and the Pop-up
//      background, reserve a second journey id, and create the comms
//      journey draft (Notification + Pop-up + SMS) wired to the SAME
//      promo-page id step 2 just created (Email is left untouched).
// Heavy logging throughout; it stops at the first error.
(async () => {
  'use strict';
  const MANUAL_TOKEN = '';
  const BASE = @BASE_URL@;
  const BRAND = @BRAND@;
  const CAMPAIGN_PAYLOAD = @CAMPAIGN_PAYLOAD@;
  const COMMS_PAYLOAD = @COMMS_PAYLOAD@;
  const COMMS_PAYLOAD_CS = @COMMS_PAYLOAD_CS@;   // CS (segment 301) duplicate, null if not made
  const RESERVED_ID_CS_TOKEN = @RESERVED_ID_CS_TOKEN@;
  const PLACEMENTS = @PLACEMENTS@;
  const PROMO_SOURCE_CONTENT_ID = @PROMO_SOURCE_CONTENT_ID@;
  const PROMO_SOURCE_FRONT_ID = @PROMO_SOURCE_FRONT_ID@;
  const PROMO_DESCRIPTION = @PROMO_DESCRIPTION@;
  const PROMO_INTERNAL_NAME = @PROMO_INTERNAL_NAME@;
  const SHOW_DATE = @SHOW_DATE@;
  const START_DATE = @START_DATE@;
  const END_DATE = @END_DATE@;
  const BETS = @BETS@;
  const GAME_NAME = @GAME_NAME@;
  const PROVIDER_NAME = @PROVIDER_NAME@;
  const END_WEEKDAY_EN = @END_WEEKDAY_EN@;
  const END_WEEKDAY_ES = @END_WEEKDAY_ES@;
  const PROMO_REWARD_IDS = @PROMO_REWARD_IDS@;
  const FOLDER_ID = @FOLDER_ID@;
  const NC_ICON_TOKEN = @NC_ICON_TOKEN@;
  const POPUP_BG_TOKEN = @POPUP_BG_TOKEN@;
  const RESERVED_CAMPAIGN_ID_TOKEN = @RESERVED_CAMPAIGN_ID_TOKEN@;
  const RESERVED_COMMS_ID_TOKEN = @RESERVED_COMMS_ID_TOKEN@;
  const PROMO_PAGE_ID_TOKEN = @PROMO_PAGE_ID_TOKEN@;
  const EMAIL_CONTENT = @EMAIL_CONTENT@;            // null when email is left untouched
  const EMAIL_HERO_TOKEN = @EMAIL_HERO_TOKEN@;
  const EMAIL_PROMO_TOKEN = @EMAIL_PROMO_TOKEN@;
  const EMAIL_CONTENT_ID_TOKEN = @EMAIL_CONTENT_ID_TOKEN@;

  const CRM_BASE = BASE.replace(/\/journey-builder\/v0$/, '');
  const CONTENT_BASE = CRM_BASE + '/content-studio/v0/eb-backoffice/email/contents';
  const AWS_BASE = new URL(BASE).origin + '/api/aws-get';

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

  function pickFile(label) {
    return new Promise((resolve, reject) => {
      const input = document.createElement('input');
      input.type = 'file';
      input.accept = 'image/*';
      Object.assign(input.style, { position: 'fixed', top: '12px', left: '12px', zIndex: 999999, background: '#fff', padding: '8px', border: '3px solid #22c55e', borderRadius: '6px' });
      document.body.appendChild(input);
      console.log('%cSelect the ' + label + ' in the file picker (top-left of the page).', 'color:#eab308;font-weight:bold');
      input.addEventListener('change', () => {
        const f = input.files && input.files[0];
        input.remove();
        if (!f) { reject(new Error('No file selected.')); return; }
        console.log('Photo selected for ' + label + ':', f.name, '(' + f.size + ' bytes)');
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

  const auth = await obtainAuth();
  const headers = (ct) => { const h = { accept: 'application/json, text/plain, */*', authorization: auth, 'x-brand': BRAND }; if (ct) h['content-type'] = ct; return h; };

  async function uploadAsset(file, label) {
    const dims = await imageDims(file);
    const baseName = (file.name || 'photo').replace(/\.[^./]+$/, '');
    const url = CRM_BASE + '/media-library/v0/folder/' + FOLDER_ID + '/upload/'
      + encodeURIComponent(baseName) + '.png?height=' + dims.height + '&width=' + dims.width;
    const fd = new FormData();
    fd.append('file', file, file.name);
    const r = await fetch(url, { method: 'PUT', headers: headers(), credentials: 'include', body: fd });
    const resp = await r.text();
    if (!r.ok) throw new Error(label + ' upload failed: HTTP ' + r.status + ' ' + resp);
    const asset = JSON.parse(resp);
    console.log('  [' + label + '] uploaded asset', asset.id, '->', asset.absolute_link);

    const thumbFd = new FormData();
    thumbFd.append('file', file, file.name);
    const tr = await fetch(CRM_BASE + '/media-library/v0/asset/thumb/' + asset.id + '.png', { method: 'PUT', headers: headers(), credentials: 'include', body: thumbFd });
    if (!tr.ok) console.warn('  [' + label + '] thumbnail upload failed (non-fatal): HTTP ' + tr.status, await tr.text());

    return asset;
  }

  // Creates the marketing-email content (create -> save -> publish), wiring in
  // the uploaded hero photo and the promo-page link created in step 1, and
  // returns its CSE id so the journey's email activity can point at it.
  async function buildAndPublishEmail(promoPageId) {
    const heroFile = await pickFile('EMAIL HERO');
    const heroAsset = await uploadAsset(heroFile, 'EMAIL HERO');
    let cText = JSON.stringify(EMAIL_CONTENT);
    cText = cText.split(EMAIL_HERO_TOKEN).join('https://{{cdn_hostname}}' + heroAsset.relative_link);
    if (promoPageId) cText = cText.split(EMAIL_PROMO_TOKEN).join(promoPageId);
    const content = JSON.parse(cText);

    let r = await fetch(CONTENT_BASE, { method: 'POST', headers: { ...headers(), 'content-type': 'application/json' }, credentials: 'include', body: JSON.stringify(content) });
    let resp = await r.text();
    if (!r.ok) throw new Error('Email content create failed: HTTP ' + r.status + ' ' + resp);
    const cseId = JSON.parse(resp).id;
    console.log('  created email content', cseId);

    r = await fetch(CONTENT_BASE + '/' + cseId, { method: 'POST', headers: { ...headers(), 'content-type': 'application/json' }, credentials: 'include', body: JSON.stringify(content) });
    resp = await r.text();
    if (!r.ok) throw new Error('Email content save failed: HTTP ' + r.status + ' ' + resp);

    r = await fetch(CONTENT_BASE + '/' + cseId + '/publish', { method: 'PATCH', headers: { ...headers(), 'content-type': 'application/json' }, credentials: 'include', body: '{}' });
    if (!r.ok) throw new Error('Email content publish failed: HTTP ' + r.status + ' ' + await r.text());
    console.log('  published email content', cseId);
    return cseId;
  }

  const newUuid = () => (typeof crypto !== 'undefined' && crypto.randomUUID) ? crypto.randomUUID()
    : 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, (c) => { const r = Math.random()*16|0; return (c === 'x' ? r : (r&0x3)|0x8).toString(16); });
  const UUID_RE = /"(?:activityId|id)"\s*:\s*"([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})"/g;
  function regen(txt) {
    const old = new Set(); let m; UUID_RE.lastIndex = 0;
    while ((m = UUID_RE.exec(txt)) !== null) old.add(m[1]);
    const map = new Map();
    let t = txt;
    for (const o of old) { const n = newUuid(); map.set(o, n); t = t.split(o).join(n); }
    return { text: t, map };
  }
  function walkReplace(o, map) {
    if (Array.isArray(o)) { for (const v of o) walkReplace(v, map); return; }
    if (o && typeof o === 'object') {
      for (const k of Object.keys(o)) {
        const v = o[k];
        if (typeof v === 'string' && map.has(v)) o[k] = map.get(v);
        else walkReplace(v, map);
      }
    }
  }

  async function reserveId() {
    const r = await fetch(BASE + '/journeys/identifier', { method: 'POST', headers: headers('application/x-www-form-urlencoded'), credentials: 'include' });
    const raw = (await r.text()).trim(); let id = raw.replace(/^"+|"+$/g, '');
    try { const d = JSON.parse(raw); if (typeof d === 'string') id = d.trim(); else if (d && typeof d === 'object') id = String(d.identifier || d.journeyId || d.id || d.value || '').trim(); } catch (e) {}
    if (!r.ok || !id.startsWith('JRN-')) throw new Error('Reserve failed: HTTP ' + r.status + ' ' + raw);
    return id;
  }

  function findFreespin(o) {
    if (!o || typeof o !== 'object') return null;
    if (o.freespinActivity && typeof o.freespinActivity === 'object' && o.freespinActivity.lobbyGameId) return o.freespinActivity;
    for (const k in o) { if (o[k] && typeof o[k] === 'object') { const r = findFreespin(o[k]); if (r) return r; } }
    return null;
  }
  const normGame = (s) => (s || '').replace(/[™®]/g, '').replace(/\s+/g, ' ').trim().toLowerCase();
  async function searchGames(provider, term) {
    let url = BASE + '/journey-activities/free-spins-bonus-deposit/data/games'
      + '?freeSpinTypes=regular&productType=slots&page=0&size=100'
      + '&translationKey=' + encodeURIComponent(term);
    if (provider) url += '&gameProvider=' + encodeURIComponent(provider);
    const r = await fetch(url, { headers: headers('application/json'), credentials: 'include' });
    if (!r.ok) throw new Error('Game search HTTP ' + r.status);
    return (((await r.json()) || {}).items) || [];
  }
  async function resolveGame(provider, gameName) {
    const want = normGame(gameName);
    const term = (gameName || '').trim().split(/\s+/)[0];
    let items = [];
    try { items = await searchGames(provider, term); } catch (e) { if (provider) throw e; }
    let exact = items.filter((it) => normGame(it.translationKey) === want);
    if (!exact.length && provider) {
      let all = [];
      try { all = await searchGames('', term); } catch (e) { /* provider-less search may be unsupported */ }
      const allExact = all.filter((it) => normGame(it.translationKey) === want);
      if (allExact.length) { items = all; exact = allExact; }
    }
    if (exact.length === 1) return exact[0];
    if (exact.length > 1) {
      const pref = exact.find((it) => (it.gameProvider || '').toLowerCase() === (provider || '').toLowerCase());
      if (pref) return pref;
      throw new Error('Game "' + gameName + '" matches multiple providers: ' + exact.map((i) => i.gameProvider + '/' + i.translationKey).join(', ') + '. Set the right provider.');
    }
    const starts = items.filter((it) => normGame(it.translationKey).indexOf(want) === 0);
    if (starts.length === 1) return starts[0];
    throw new Error('Game "' + gameName + '" not found exactly' + (provider ? ' for provider "' + provider + '"' : '') + '. Candidates: ' + (items.map((i) => i.translationKey).join(', ') || 'none'));
  }

  async function copyContentsTarget(srcPath, destPath, fileFilters) {
    const body = { sourcePath: srcPath, destinationPath: destPath };
    if (fileFilters) body.fileFilters = fileFilters;
    const r = await fetch(CRM_BASE + '/contents/v1/copy', { method: 'POST', headers: headers('application/json'), credentials: 'include', body: JSON.stringify(body) });
    if (!r.ok) throw new Error('copy failed ' + srcPath + ' -> ' + destPath + ': HTTP ' + r.status + ' ' + await r.text());
  }
  const JSON_FILTERS = ['manifest.json', 'content/content-es.json', 'content/content-en.json'];
  function contentFileFilters(target, role, itemContentIds) {
    if (target === 'widgetModulor' || target === 'cashier') return JSON_FILTERS;
    if (target === 'widget') return JSON_FILTERS.concat(['media/box.png', 'media/widgetImgKey.png']);
    if (target === 'spa') {
      if (role === 'offer') {
        return JSON_FILTERS.concat(
          ['media/HeaderImageKey.png', 'media/prizeImageKey.png'],
          itemContentIds.map((id) => `media/${id}.itemImageKey.png`)
        );
      }
      return JSON_FILTERS.concat(['media/box.png', 'media/bonusHeaderImage.png']);
    }
    return undefined;
  }
  async function cloneBundle(oldId, newId, targets, role, itemContentIds) {
    await Promise.all(targets.map((t) => {
      const filters = role ? contentFileFilters(t, role, itemContentIds || []) : undefined;
      return copyContentsTarget(`mf/v1/${oldId}/${t}`, `mf/v1/${newId}/${t}`, filters);
    }));
  }
  async function copyBundleS3(oldId, newId) {
    const url = CRM_BASE + `/promo/v2/s3/copy?destination=${encodeURIComponent('mf/v1/' + newId)}&source=${encodeURIComponent('mf/v1/' + oldId)}`;
    const r = await fetch(url, { method: 'POST', headers: headers('application/json'), credentials: 'include' });
    if (!r.ok) throw new Error('s3 copy failed ' + oldId + ' -> ' + newId + ': HTTP ' + r.status + ' ' + await r.text());
  }
  async function awsGet(path) {
    const r = await fetch(AWS_BASE + '/' + path, { credentials: 'include' });
    if (!r.ok) throw new Error('GET ' + path + ' failed: HTTP ' + r.status);
    return r.text();
  }
  async function s3Upload(path, dataObj) {
    const r = await fetch(CRM_BASE + '/promo/v2/s3/upload', { method: 'POST', headers: headers('application/json'), credentials: 'include', body: JSON.stringify({ path, data: dataObj }) });
    if (!r.ok) throw new Error('upload failed ' + path + ': HTTP ' + r.status + ' ' + await r.text());
  }
  async function uploadContentMulti(fields) {
    const fd = new FormData();
    for (const [path, file] of Object.entries(fields)) fd.append(path, file, 'photo.png');
    const r = await fetch(CRM_BASE + '/promo/v2/s3/upload-content', { method: 'POST', headers: { authorization: auth, 'x-brand': BRAND }, credentials: 'include', body: fd });
    if (!r.ok) throw new Error('upload-content failed: HTTP ' + r.status + ' ' + await r.text());
  }

  function replaceBetText(str, bets) {
    let i = 0;
    return str.replace(/\b(Bet|Apuesta)\b(\s*)\$[\d,]+/gi, (m, w, sp) => {
      const v = bets[Math.min(i, bets.length - 1)]; i++; return w + sp + '$' + v;
    });
  }
  const WEEKDAY_RE_EN = /\b(Sunday|Monday|Tuesday|Wednesday|Thursday|Friday|Saturday)\b/g;
  const WEEKDAY_RE_ES = /\b(lunes|martes|mi[ée]rcoles|jueves|viernes|s[áa]bado|domingo)\b/gi;
  function replaceWeekday(str, lang) {
    return lang === 'es' ? str.replace(WEEKDAY_RE_ES, END_WEEKDAY_ES) : str.replace(WEEKDAY_RE_EN, END_WEEKDAY_EN);
  }

  async function fixJourneyContentJson(newId, oldId, role, itemContentIds) {
    const targets = ['spa', 'widget', 'widgetModulor', 'cashier'];
    const langs = ['en', 'es'];
    const jobs = [];
    for (const t of targets) for (const l of langs) jobs.push([t, l]);
    await Promise.all(jobs.map(async ([t, l]) => {
      const path = `mf/v1/${newId}/${t}/content/content-${l}.json`;
      let txt;
      try { txt = await awsGet(path); } catch (e) { console.warn('  (no content at', path, '— skipping)'); return; }
      const fixed = txt.split(oldId).join(newId);
      const content = JSON.parse(fixed);
      if (role === 'offer') {
        if (typeof content.ToGetDescrText === 'string') content.ToGetDescrText = replaceBetText(content.ToGetDescrText, BETS);
        (itemContentIds || []).forEach((id, i) => {
          for (const suffix of ['FlowItemKey', 'bonusDescription']) {
            const key = id + suffix;
            if (typeof content[key] === 'string') content[key] = replaceBetText(content[key], [BETS[i]]);
          }
        });
      } else if (typeof content.bonusToGetDescrText === 'string') {
        content.bonusToGetDescrText = replaceWeekday(content.bonusToGetDescrText, l);
      }
      await s3Upload(path, content);
    }));
  }

  async function fixPromoContentJson(newId, oldId) {
    const baseName = (p) => (p || '').split('/').pop();
    const manifests = {};
    await Promise.all(['spa', 'widget'].map(async (t) => {
      manifests[t] = JSON.parse(await awsGet(`mf/v1/${newId}/${t}/manifest.json`));
    }));
    const jobs = [];
    for (const t of ['spa', 'widget']) for (const [lang, fname] of Object.entries(manifests[t])) jobs.push([t, lang, fname]);
    await Promise.all(jobs.map(async ([t, lang, fname]) => {
      const path = `mf/v1/${newId}/${t}/content/${fname}`;
      const txt = await awsGet(path);
      const fixed = txt.split(oldId).join(newId);
      const content = JSON.parse(fixed);
      if (t === 'spa') {
        if (typeof content.ToGetDescrText === 'string') {
          content.ToGetDescrText = replaceWeekday(replaceBetText(content.ToGetDescrText, BETS), lang);
        }
        PROMO_REWARD_IDS.forEach((id, i) => {
          const titleKey = id + 'TitleItemKey';
          const catKey = id + 'CategoryItemKey';
          if (typeof content[titleKey] === 'string') content[titleKey] = replaceBetText(content[titleKey], [BETS[i]]);
          if (typeof content[catKey] === 'string') content[catKey] = `<p>| ${GAME_NAME} | ${PROVIDER_NAME}&nbsp;</p>\n`;
        });
      }
      await s3Upload(path, content);
    }));
    const spaFname = manifests.spa.en || Object.values(manifests.spa)[0];
    const spaContent = JSON.parse(await awsGet(`mf/v1/${newId}/spa/content/${spaFname}`));
    const widgetFname = manifests.widget.en || Object.values(manifests.widget)[0];
    const widgetContent = JSON.parse(await awsGet(`mf/v1/${newId}/widget/content/${widgetFname}`));
    return {
      prizeImageKey: baseName(spaContent.prizeImageKey),
      headerImageKey: baseName(spaContent.HeaderImageKey),
      widgetImgKey: baseName(widgetContent.widgetImgKey),
    };
  }

  console.log('%c=== STEP 1/2: Campaign (free-spin journey + promo page) ===', 'color:#3b82f6;font-weight:bold');
  const campaignPhoto = await pickFile('campaign photo');

  console.log('Reserving campaign journey id...');
  const campaignJourneyId = await reserveId();
  console.log('  reserved', campaignJourneyId);

  const idMap = new Map();
  const fresh = {};
  for (const p of PLACEMENTS) {
    fresh[p.role] = { contentId: newUuid(), frontId: newUuid() };
    idMap.set(p.contentId, fresh[p.role].contentId);
    idMap.set(p.frontId, fresh[p.role].frontId);
  }
  walkReplace(CAMPAIGN_PAYLOAD, idMap);

  const fsSample = findFreespin(CAMPAIGN_PAYLOAD);
  let campaignText = JSON.stringify(CAMPAIGN_PAYLOAD);
  if (fsSample) {
    const hit = await resolveGame(fsSample.provider, GAME_NAME);
    console.log('Resolved game "' + GAME_NAME + '" ->', { provider: hit.gameProvider, lobbyId: hit.lobbyId, walletId: hit.walletId, externalGameId: hit.externalGameId, name: hit.translationKey });
    const swaps = [];
    if (fsSample.lobbyGameId && hit.lobbyId) swaps.push([fsSample.lobbyGameId, hit.lobbyId]);
    if (fsSample.walletGameId && hit.walletId) swaps.push([fsSample.walletGameId, hit.walletId]);
    if (fsSample.externalGameId && hit.externalGameId) swaps.push([fsSample.externalGameId, hit.externalGameId]);
    const uniq = swaps.filter(([a, b], i) => a && a !== b && swaps.findIndex((s) => s[0] === a) === i).sort((a, b) => b[0].length - a[0].length);
    for (const [a, b] of uniq) campaignText = campaignText.split(a).join(b);
    if (fsSample.provider && hit.gameProvider && fsSample.provider !== hit.gameProvider) {
      campaignText = campaignText.split('"provider":"' + fsSample.provider + '"').join('"provider":"' + hit.gameProvider + '"');
    }
    if (uniq.length) console.log('  rewrote game ids:', uniq.map((s) => s[0] + ' -> ' + s[1]).join(', '));
  }
  campaignText = campaignText.split(RESERVED_CAMPAIGN_ID_TOKEN).join(campaignJourneyId);
  const campaignRegen = regen(campaignText);
  const campaignBody = JSON.parse(campaignRegen.text);

  console.log('Creating campaign journey draft', campaignJourneyId, ':', campaignBody.journeyName);
  let r = await fetch(BASE + '/journey-drafts', { method: 'POST', headers: headers('application/json'), credentials: 'include', body: JSON.stringify(campaignBody) });
  let resp = await r.text();
  if (!r.ok) { console.error('FAILED HTTP ' + r.status, resp); throw new Error('Campaign journey draft not created.'); }
  console.log('%cCampaign journey draft created: ' + campaignJourneyId, 'color:#22c55e;font-weight:bold');

  console.log('Cloning visual bundles and uploading the campaign photo (5 placements, in parallel)...');
  const placementErrors = [];
  await Promise.all(PLACEMENTS.map(async (p) => {
    const ids = fresh[p.role];
    console.log('  [' + p.role + ']', 'content', p.contentId, '->', ids.contentId, '| front', p.frontId, '->', ids.frontId);
    try {
      await Promise.all([
        cloneBundle(p.contentId, ids.contentId, ['spa', 'widget', 'widgetModulor', 'cashier'], p.role, p.itemContentIds),
        cloneBundle(p.frontId, ids.frontId, ['spa', 'widget']),
      ]);
      await fixJourneyContentJson(ids.contentId, p.contentId, p.role, p.itemContentIds);
      const fields = {};
      fields[`mf/v1/${ids.contentId}/widget/media/widgetImgKey.png`] = campaignPhoto;
      if (p.role === 'offer') {
        for (const itemId of p.itemContentIds) fields[`mf/v1/${ids.contentId}/spa/media/${itemId}.itemImageKey.png`] = campaignPhoto;
        fields[`mf/v1/${ids.contentId}/spa/media/prizeImageKey.png`] = campaignPhoto;
      } else {
        fields[`mf/v1/${ids.contentId}/spa/media/bonusHeaderImage.png`] = campaignPhoto;
      }
      await uploadContentMulti(fields);
      console.log('    [' + p.role + '] photo uploaded to', Object.keys(fields).length, 'slot(s)');
    } catch (e) {
      console.error('  [' + p.role + '] FAILED:', e.message);
      placementErrors.push(p.role + ': ' + e.message);
    }
  }));
  if (placementErrors.length) {
    console.error('%cSome placements failed, continuing to the promo page anyway:', 'color:#ef4444', placementErrors);
  } else {
    console.log('%cAll 5 visual bundles cloned + photo uploaded.', 'color:#22c55e');
  }

  const offerPlacement = PLACEMENTS.find((p) => p.role === 'offer');
  const offerNewActivityId = campaignRegen.map.get(offerPlacement.activityId);
  if (!offerNewActivityId) throw new Error('Could not resolve the regenerated offer activityId — cannot link the promo page.');
  console.log('Offer activityId (regenerated):', offerNewActivityId);

  console.log('Cloning promo-page visual bundle from', PROMO_SOURCE_CONTENT_ID, '/', PROMO_SOURCE_FRONT_ID, '...');
  const promoContentId = newUuid(), promoFrontId = newUuid();
  await copyBundleS3(PROMO_SOURCE_CONTENT_ID, promoContentId);
  await copyBundleS3(PROMO_SOURCE_FRONT_ID, promoFrontId);
  const slotNames = await fixPromoContentJson(promoContentId, PROMO_SOURCE_CONTENT_ID);
  console.log('  promo content', promoContentId, '| front', promoFrontId, '| photo slots', slotNames);
  const promoFields = {};
  if (slotNames.prizeImageKey) promoFields[`mf/v1/${promoContentId}/spa/media/${slotNames.prizeImageKey}`] = campaignPhoto;
  if (slotNames.headerImageKey) promoFields[`mf/v1/${promoContentId}/spa/media/${slotNames.headerImageKey}`] = campaignPhoto;
  if (slotNames.widgetImgKey) promoFields[`mf/v1/${promoContentId}/widget/media/${slotNames.widgetImgKey}`] = campaignPhoto;
  if (Object.keys(promoFields).length) await uploadContentMulti(promoFields);
  console.log('%cPromo-page visual bundle cloned + photo uploaded.', 'color:#22c55e');

  const promoPageId = newUuid();
  const promoPayload = {
    type: 'PromoPage',
    internalName: PROMO_INTERNAL_NAME,
    brand: BRAND,
    playerVisibility: 'Unauthorized',
    showDate: SHOW_DATE,
    startDate: START_DATE,
    endDate: END_DATE,
    currencies: [{ brand: BRAND, currency: 'CLP' }],
    currencyMode: 'single',
    filterConditions: [{ values: [{ id: 31, name: 'Negative' }], conditionType: 'MultiSelect', key: 'Business', filterType: 'fairplay_business_segment', displayName: 'fairplay_business_segment', operator: 'notIn' }],
    promotionDisplayId: null,
    languages: ['en', 'es'],
    urlShortName: promoPageId,
    promotionSettings: { type: 'JourneyPromotion', journeyPromotionSettings: { journeyId: campaignJourneyId, activityId: offerNewActivityId, activityDescription: PROMO_DESCRIPTION } },
    contentId: promoContentId,
    frontId: promoFrontId,
  };
  console.log('Creating promo page draft:', PROMO_INTERNAL_NAME);
  r = await fetch(CRM_BASE + '/promo/v2/promo-drafts/promo-page', { method: 'POST', headers: headers('application/json'), credentials: 'include', body: JSON.stringify(promoPayload) });
  resp = await r.text();
  if (!r.ok) { console.error('FAILED HTTP ' + r.status, resp); throw new Error('Promo page draft not created (journey draft ' + campaignJourneyId + ' was already created).'); }
  console.log('%cSTEP 1/2 DONE — promo page id: ' + promoPageId, 'color:#22c55e;font-weight:bold');

  console.log('%c=== STEP 2/2: Communications (Notification + Pop-up + SMS' + (EMAIL_CONTENT ? ' + Email' : '') + ') ===', 'color:#3b82f6;font-weight:bold');
  const ncIconFile = await pickFile('NC ICON');
  const ncIconUrl = (await uploadAsset(ncIconFile, 'NC ICON')).absolute_link;
  const popupBgFile = await pickFile('POP-UP BACKGROUND');
  const popupBgUrl = (await uploadAsset(popupBgFile, 'POP-UP BACKGROUND')).absolute_link;

  let emailContentId = null;
  if (EMAIL_CONTENT) {
    console.log('Creating + publishing email content (promo page ' + promoPageId + ')...');
    emailContentId = await buildAndPublishEmail(promoPageId);
  }

  console.log('Reserving comms journey id...');
  const commsJourneyId = await reserveId();
  console.log('  reserved', commsJourneyId);

  let commsText = JSON.stringify(COMMS_PAYLOAD);
  commsText = commsText.split(RESERVED_COMMS_ID_TOKEN).join(commsJourneyId);
  commsText = commsText.split(NC_ICON_TOKEN).join(ncIconUrl);
  commsText = commsText.split(POPUP_BG_TOKEN).join(popupBgUrl);
  commsText = commsText.split(PROMO_PAGE_ID_TOKEN).join(promoPageId);
  if (emailContentId) commsText = commsText.split(EMAIL_CONTENT_ID_TOKEN).join(emailContentId);
  commsText = regen(commsText).text;
  const commsBody = JSON.parse(commsText);

  console.log('Creating comms journey draft', commsJourneyId, ':', commsBody.journeyName);
  r = await fetch(BASE + '/journey-drafts', { method: 'POST', headers: headers('application/json'), credentials: 'include', body: JSON.stringify(commsBody) });
  resp = await r.text();
  if (!r.ok) { console.error('FAILED HTTP ' + r.status, resp); throw new Error('Comms journey draft not created.'); }

  let csCommsId = null;
  if (COMMS_PAYLOAD_CS) {
    csCommsId = await reserveId();
    console.log('  reserved comms (CS)', csCommsId);
    let t2 = JSON.stringify(COMMS_PAYLOAD_CS);
    t2 = t2.split(RESERVED_ID_CS_TOKEN).join(csCommsId);
    t2 = t2.split(NC_ICON_TOKEN).join(ncIconUrl);
    t2 = t2.split(POPUP_BG_TOKEN).join(popupBgUrl);
    t2 = t2.split(PROMO_PAGE_ID_TOKEN).join(promoPageId);
    if (emailContentId) t2 = t2.split(EMAIL_CONTENT_ID_TOKEN).join(emailContentId);
    t2 = regen(t2).text;
    const csBody = JSON.parse(t2);
    console.log('Creating CS comms journey draft', csCommsId, ':', csBody.journeyName);
    const rcs = await fetch(BASE + '/journey-drafts', { method: 'POST', headers: headers('application/json'), credentials: 'include', body: JSON.stringify(csBody) });
    const respcs = await rcs.text();
    if (!rcs.ok) { console.error('FAILED HTTP ' + rcs.status, respcs); throw new Error('CS comms journey draft not created.'); }
  }

  console.log('%cDONE.', 'color:#22c55e;font-weight:bold;font-size:14px');
  console.log('  Campaign journey draft: ' + campaignJourneyId);
  console.log('  Promo page draft id:    ' + promoPageId);
  console.log('  Comms journey draft (CS&SP): ' + commsJourneyId);
  if (csCommsId) console.log('  Comms journey draft (CS):    ' + csCommsId);
  if (emailContentId) console.log('  Email content created + published: ' + emailContentId);
  else console.log('  Email activity left untouched — edit it by hand in the backoffice.');
})();
"""


def build_js(
    campaign_body: dict,
    comms_body: dict,
    *,
    promo_source_content_id: str,
    promo_source_front_id: str,
    promo_description: str,
    promo_internal_name: str,
    show_date: str,
    start_date: str,
    end_date: str,
    bets_major: list[int],
    game_name: str,
    provider_name: str,
    end_weekday_en: str,
    end_weekday_es: str,
    public_domain: str,
    email_content: dict | None = None,
    comms_cs_body: dict | None = None,
) -> str:
    js = JS_TEMPLATE
    js = js.replace("@COMMS_PAYLOAD_CS@", json.dumps(comms_cs_body, ensure_ascii=False))
    js = js.replace("@RESERVED_ID_CS_TOKEN@", json.dumps(RESERVED_ID_CS_TOKEN))
    js = js.replace("@GENERATED_AT@", datetime.now(LOCAL_TZ).strftime("%Y-%m-%d %H:%M %Z"))
    js = js.replace("@CAMPAIGN_JOURNEY_NAME@", str(campaign_body.get("journeyName", "")))
    js = js.replace("@COMMS_JOURNEY_NAME@", str(comms_body.get("journeyName", "")))
    js = js.replace("@BASE_URL@", json.dumps(DEFAULT_BASE_URL))
    js = js.replace("@BRAND@", json.dumps(BRAND))
    js = js.replace("@CAMPAIGN_PAYLOAD@", json.dumps(campaign_body, ensure_ascii=False))
    js = js.replace("@COMMS_PAYLOAD@", json.dumps(comms_body, ensure_ascii=False))
    js = js.replace("@PLACEMENTS@", json.dumps(PLACEMENTS, ensure_ascii=False))
    js = js.replace("@PROMO_SOURCE_CONTENT_ID@", json.dumps(promo_source_content_id))
    js = js.replace("@PROMO_SOURCE_FRONT_ID@", json.dumps(promo_source_front_id))
    js = js.replace("@PROMO_DESCRIPTION@", json.dumps(promo_description))
    js = js.replace("@PROMO_INTERNAL_NAME@", json.dumps(promo_internal_name))
    js = js.replace("@SHOW_DATE@", json.dumps(show_date))
    js = js.replace("@START_DATE@", json.dumps(start_date))
    js = js.replace("@END_DATE@", json.dumps(end_date))
    js = js.replace("@BETS@", json.dumps(bets_major))
    js = js.replace("@GAME_NAME@", json.dumps(game_name))
    js = js.replace("@PROVIDER_NAME@", json.dumps(provider_name))
    js = js.replace("@END_WEEKDAY_EN@", json.dumps(end_weekday_en))
    js = js.replace("@END_WEEKDAY_ES@", json.dumps(end_weekday_es))
    js = js.replace("@PROMO_REWARD_IDS@", json.dumps(PROMO_REWARD_IDS))
    js = js.replace("@FOLDER_ID@", json.dumps(DEFAULT_FOLDER_ID))
    js = js.replace("@NC_ICON_TOKEN@", json.dumps(NC_ICON_TOKEN))
    js = js.replace("@POPUP_BG_TOKEN@", json.dumps(POPUP_BG_TOKEN))
    js = js.replace("@RESERVED_CAMPAIGN_ID_TOKEN@", json.dumps(RESERVED_CAMPAIGN_ID_TOKEN))
    js = js.replace("@RESERVED_COMMS_ID_TOKEN@", json.dumps(RESERVED_COMMS_ID_TOKEN))
    js = js.replace("@PROMO_PAGE_ID_TOKEN@", json.dumps(PROMO_PAGE_ID_TOKEN))
    js = js.replace("@EMAIL_CONTENT@", json.dumps(email_content, ensure_ascii=False))
    js = js.replace("@EMAIL_HERO_TOKEN@", json.dumps(EMAIL_HERO_TOKEN))
    js = js.replace("@EMAIL_PROMO_TOKEN@", json.dumps(EMAIL_PROMO_TOKEN))
    js = js.replace("@EMAIL_CONTENT_ID_TOKEN@", json.dumps(EMAIL_CONTENT_ID_TOKEN))
    return js


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--date", required=True, help="Campaign start date YYYY-MM-DD (Chile); comms send the same day 12:00->19:00")
    p.add_argument("--days", type=int, default=1, help="Campaign journey duration in days (default 1)")
    p.add_argument("--spec", required=True, help="Path to the pasted spec blob, or '-' to read it from stdin")
    p.add_argument("--spins", type=int, help="Free-spin count override (default: keep template value)")
    p.add_argument("--public-domain", default=DEFAULT_PUBLIC_DOMAIN, help=f"Public site domain for the SMS link (default {DEFAULT_PUBLIC_DOMAIN})")
    p.add_argument("--journey-name", default="", help="Override the comms journey name (default: reuse template name with the date refreshed)")
    p.add_argument("--promo-source-content-id", default=DEFAULT_PROMO_SOURCE_CONTENT_ID)
    p.add_argument("--promo-source-front-id", default=DEFAULT_PROMO_SOURCE_FRONT_ID)
    p.add_argument("--promo-description", default=DEFAULT_PROMO_DESCRIPTION)
    p.add_argument("--name", default="gow_combined", help="Output file basename (default: gow_combined)")
    p.add_argument("--dry-run", action="store_true", help="Write both prepared payloads to out/ instead of a console script")
    args = p.parse_args()

    spec_text = sys.stdin.read() if args.spec == "-" else Path(args.spec).read_text(encoding="utf-8")
    spec = parse_spec(spec_text)
    for w in spec.warnings:
        print(f"  WARN  {w}", file=sys.stderr)
    if not spec.bets or not spec.game_name or not spec.provider:
        print("\nspec is missing game/provider/bets (check the Offer cell).", file=sys.stderr)
        return 1
    if not spec.nc.title_en or not spec.popup.title_en or not spec.sms.text_en:
        print("\nspec is missing Notification/Pop-up/Sms copy — nothing written.", file=sys.stderr)
        return 1

    game = resolve_game(SimpleNamespace(
        game=None, lobby_game_id=None, wallet_game_id=None, external_game_id=None,
        provider=spec.provider, game_name=spec.game_name, provider_name=spec.provider_name,
    ))

    (
        campaign_body, comms_body, campaign_report, comms_report,
        start_local, stop_local, comms_start_local, comms_stop_local, email_content,
    ) = prepare_both(
        date_str=args.date, days=args.days, game=game, bets_major=spec.bets,
        spins=args.spins, public_domain=args.public_domain, journey_name=args.journey_name,
        nc=nc_dict_from_spec(spec.nc), popup=popup_dict_from_spec(spec.popup), sms=sms_dict_from_spec(spec.sms),
        email=email_dict_from_spec(spec),
    )
    comms_cs_body = make_cs_variant(comms_body)
    comms_report.append(f"CS variant: segment 301, journeyName = {comms_cs_body.get('journeyName')!r}")

    print("Campaign:")
    for line in campaign_report:
        print("  " + line)
    print("Comms:")
    for line in comms_report:
        print("  " + line)

    print("Verification (campaign):")
    all_ok = True
    for ok, msg in casino_verify(campaign_body, game, spec.bets):
        print(f"  {'OK  ' if ok else 'FAIL'} {msg}")
        all_ok = all_ok and ok
    print("Verification (comms):")
    for ok, msg in comms_verify(comms_body, PROMO_PAGE_ID_TOKEN):
        print(f"  {'OK  ' if ok else 'FAIL'} {msg}")
        all_ok = all_ok and ok
    if not all_ok:
        print("\nVERIFICATION FAILED — not writing output.", file=sys.stderr)
        return 1

    if args.dry_run:
        out = Path("out")
        out.mkdir(exist_ok=True)
        (out / f"{args.name}_campaign_journey.json").write_text(json.dumps(campaign_body, ensure_ascii=False, indent=2), encoding="utf-8")
        (out / f"{args.name}_comms_journey.json").write_text(json.dumps(comms_body, ensure_ascii=False, indent=2), encoding="utf-8")
        (out / f"{args.name}_comms_cs_journey.json").write_text(json.dumps(comms_cs_body, ensure_ascii=False, indent=2), encoding="utf-8")
        if email_content is not None:
            (out / f"{args.name}_email.json").write_text(json.dumps(email_content, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\nDry run — journey payloads written under out/{args.name}_*.json")
        print("(promo-page payload is built at paste-time in the browser, not in dry-run output)")
        return 0

    show_date = start_local
    start_date = start_local + timedelta(minutes=1)
    end_date = stop_local - timedelta(minutes=1)
    promo_internal_name = f"{BRAND}|CS|GOW-{start_local:%d-%m-%y}"

    last_day = (stop_local - timedelta(days=1)).weekday()
    end_weekday_en = WEEKDAYS_EN[last_day]
    end_weekday_es = WEEKDAYS_ES[last_day]

    js = build_js(
        campaign_body, comms_body,
        promo_source_content_id=args.promo_source_content_id,
        promo_source_front_id=args.promo_source_front_id,
        promo_description=args.promo_description,
        promo_internal_name=promo_internal_name,
        show_date=utc_dotnet(show_date),
        start_date=utc_dotnet(start_date),
        end_date=utc_dotnet(end_date),
        bets_major=spec.bets,
        game_name=game["game_name"],
        provider_name=game["provider_name"],
        end_weekday_en=end_weekday_en,
        end_weekday_es=end_weekday_es,
        public_domain=args.public_domain,
        email_content=email_content,
        comms_cs_body=comms_cs_body,
    )
    print(f"\nVisual content text: bets {spec.bets}, game {game['game_name']!r}, end weekday {end_weekday_en}/{end_weekday_es}")
    print(f"Comms window: {comms_start_local:%Y-%m-%d %H:%M} -> {comms_stop_local:%H:%M} Chile")

    out = Path("console_scripts")
    out.mkdir(exist_ok=True)
    path = out / f"{args.name}_console.js"
    path.write_text(js, encoding="utf-8")
    print(f"\nConsole script written: {path}")
    print("Paste it into the DevTools console on a logged-in backoffice tab.")
    if email_content is not None:
        print("Four file pickers will pop up in turn: campaign photo, NC icon, Pop-up background, then Email hero.")
    else:
        print("Three file pickers will pop up in turn: campaign photo, then NC icon, then Pop-up background.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
