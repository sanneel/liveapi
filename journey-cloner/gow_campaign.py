#!/usr/bin/env python3
"""
Build a full "Game of the Week" casino campaign: the Journey Builder draft
(free-spin offer + 4 deposit-tier rewards) AND the Promo Page draft that
points at it — both with their visual bundles populated by a photo you pick
when the script runs.

This wraps casino_journey.py's game/bets/dates logic (same template,
templates/casino/gow.json) and adds the parts that script doesn't do:
  * forking the 5 journey placements' visual bundles (1 offer + 4 tiers) to
    fresh content/front ids, fixing their content-<lang>.json self-references,
    and uploading your photo into every image slot,
  * forking a promo-page visual bundle (cloned from a known prior GOW promo
    page, since promo pages are always built by duplicating one) and
    uploading the photo there too,
  * creating the Promo Page draft itself, wired to the new journey's offer
    activity.

Usage:
  python gow_campaign.py --date 2026-07-01 \
      --game lagrancopa --bets 120 200 400 800

Then paste console_scripts/<name>_console.js into the DevTools console on a
logged-in backoffice tab. A file picker will pop up — select the campaign
photo there (nothing is embedded in the script). Use --dry-run to write the
prepared journey payload to out/ without generating a script.

The promo-page visual bundle is cloned from a known-good prior GOW promo page
(see PROMO_SOURCE_CONTENT_ID/PROMO_SOURCE_FRONT_ID below — these are exactly
what the backoffice UI itself clones from when you "create" a new instance of
this recurring promo). If a more recent GOW promo page exists by the time you
run this, override with --promo-source-content-id/--promo-source-front-id.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timedelta
from pathlib import Path

from create_journeys import (
    BRAND,
    LOCAL_TZ,
    clear_stale_campaign_connector_ids,
    strip_duplicate_lineage,
    strip_promotion_display_ids,
)
from casino_journey import (
    DEFAULT_BASE_URL,
    GAMES,
    TEMPLATE_PATH,
    chile_window,
    resolve_game,
    set_bets,
    set_dates,
    set_game,
    utc_dotnet,
    verify as casino_verify,
)

# The 5 visual placements in templates/casino/gow.json: 1 free-spin offer
# (multipurpose_promotion, with a per-tier-option flow of 4 items) + 4
# deposit-tier reward placements (promotion). Ids are read straight from the
# template — see REA_BACKOFFICE_AND_JOURNEYS.md §17.8 for how this table was
# derived from a live capture.
PLACEMENTS: list[dict] = [
    {
        "role": "offer",
        "activityId": "a9f6c0d4-f79c-40f3-b7be-e5d550399bc0",
        "contentId": "f9107c2e-8f11-420e-9e06-2718b455efb5",
        "frontId": "c99fbbc3-0725-4521-9bfe-03817f81d4f6",
        "itemContentIds": [
            "f118cfe4-e5a6-462e-afab-0b8a9fb80119",
            "43af79db-5acd-42fe-8a0b-1dc8395b9183",
            "31a1054a-b138-4593-ae17-eebd8e9c561c",
            "350567a9-8f8f-434c-b235-3da13dfa53ca",
        ],
    },
    {
        "role": "tier1",
        "activityId": "b6c72dd0-ff4e-4f25-9eee-d71b505b3ba1",
        "contentId": "e3b199fb-5675-4838-a81d-224b7ab538fc",
        "frontId": "2f8741c0-657c-4ee4-8932-d3ffdb5333a1",
    },
    {
        "role": "tier2",
        "activityId": "51883c3a-6981-4e80-bd5b-e145ae1fd4bd",
        "contentId": "22ea33ce-e62a-42dd-9f48-58c0627dd833",
        "frontId": "79537e59-86e9-4f78-b00c-b75986e17cc7",
    },
    {
        "role": "tier3",
        "activityId": "0b751e83-e831-4024-9f37-5229f5d6675e",
        "contentId": "1f4afead-e1b7-4875-b621-3be665e689fb",
        "frontId": "2a4d286c-6528-4312-bf10-f0ab64e73f46",
    },
    {
        "role": "tier4",
        "activityId": "8f494e63-6d08-41ee-a2a6-be122c195763",
        "contentId": "d8cefb1a-77f8-4a2e-8dfb-664cb371027f",
        "frontId": "b08cc140-6ab4-40c8-852a-222d59d7a6b5",
    },
]

# Most recently captured GOW promo page (PRPG-0-7768). Promo pages are always
# created by cloning an existing one's visual bundle wholesale (the backoffice
# UI does the same), so this is the source the script forks from.
DEFAULT_PROMO_SOURCE_CONTENT_ID = "f8341ab2-1e83-4c28-a895-9fc4a12a9a34"
DEFAULT_PROMO_SOURCE_FRONT_ID = "9c930c93-ecb5-4832-acb4-732217572f8f"
DEFAULT_PROMO_DESCRIPTION = "JBCL | CS | RB - Game of the week | 50 FS"

# The promo page's content-<lang>-<hash>.json mixes GOW's 4 reward items in
# among unrelated other promotions' reward items in the same file. These are
# the 4 GOW-specific reward-item UUIDs (ascending by bet tier) as found in
# DEFAULT_PROMO_SOURCE_CONTENT_ID's bundle — if a different --promo-source-
# content-id is used, this table would need updating too.
PROMO_REWARD_IDS: list[str] = [
    "29ebecb8-1535-4268-a07c-c427191271e8",
    "4be12719-736b-4057-84ec-00cf67565d8e",
    "5f782f80-a642-4312-8f9f-9d05fb8676dd",
    "bff89a48-063b-44ed-bcb1-02bdfb23f01f",
]

WEEKDAYS_EN = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
WEEKDAYS_ES = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]


def clean_journey_name(name: str, start_local: datetime) -> str:
    """Strip "Copy of " lineage prefixes and refresh the trailing date.

    The template's journeyName accumulates a "Copy of " prefix every time a
    prior week's journey was duplicated to make this one, plus the previous
    week's date suffix (e.g. "Copy of Copy of Copy of ... | 24.06").
    """
    name = re.sub(r"^(Copy of )+", "", name)
    name = re.sub(r"\s*\|\s*\d{2}\.\d{2}\s*$", "", name)
    return f"{name} | {start_local:%d.%m}"


def set_name(body: dict, start_local: datetime) -> str:
    new_name = clean_journey_name(body.get("journeyName", ""), start_local)
    body["journeyName"] = new_name
    raw = body.get("rawJourneyData")
    if isinstance(raw, dict):
        info = raw.get("infoValues")
        if isinstance(info, dict):
            info["journeyName"] = new_name
    return new_name


def prepare_campaign(
    *,
    date_str: str,
    days: int,
    game: dict[str, str],
    bets_major: list[int],
    spins: int | None,
    reserved_id: str,
) -> tuple[dict, list[str], datetime, datetime]:
    body = json.loads(TEMPLATE_PATH.read_text(encoding="utf-8-sig"))
    report: list[str] = []

    n = set_game(body, game, spins)
    report.append(
        f"set game {game['game_name']!r} ({game['lobby_game_id']}) on {n} free-spin activities"
        + (f", spins={spins}" if spins is not None else "")
    )
    report.extend(set_bets(body, bets_major))

    start_local, stop_local = chile_window(date_str, days)
    set_dates(body, start_local, stop_local)
    report.append(
        f"startAt {body['startAt']} ({start_local:%Y-%m-%d %H:%M} Chile) -> "
        f"stopAt {body['stopAt']} ({stop_local:%Y-%m-%d %H:%M} Chile)"
    )

    new_name = set_name(body, start_local)
    report.append(f"journeyName = {new_name!r}")

    removed = strip_duplicate_lineage(body)
    if removed:
        report.append(f"removed {', '.join(removed)}")
    cc = clear_stale_campaign_connector_ids(body)
    if cc:
        report.append(f"cleared {cc} stale campaignId(s)")
    dd = strip_promotion_display_ids(body)
    if dd:
        report.append(f"removed {dd} stale promotionDisplayId(s) (backend assigns fresh ones on create)")

    body["reservedJourneyId"] = reserved_id
    report.append(f"reservedJourneyId = {reserved_id}")
    return body, report, start_local, stop_local


JS_TEMPLATE = r"""// Game-of-Week campaign console script — generated @GENERATED_AT@
// Journey: @JOURNEY_NAME@
//
// Paste into the DevTools console on a logged-in backoffice tab. It will:
//   1. capture the auth token from the page's own requests,
//   2. pop up a file picker for you to choose the campaign photo,
//   3. reserve a journey id and create the journey draft,
//   4. fork the 5 placements' visual bundles and upload the photo into each,
//   5. fork a promo-page visual bundle and upload the photo there,
//   6. create the Promo Page draft wired to the new journey.
// Heavy logging throughout; it stops at the first error.
(async () => {
  'use strict';
  const MANUAL_TOKEN = '';
  const BASE = @BASE_URL@;
  const BRAND = @BRAND@;
  const PAYLOAD = @PAYLOAD@;
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

  const CRM_BASE = BASE.replace(/\/journey-builder\/v0$/, '');
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

  function pickFile() {
    return new Promise((resolve, reject) => {
      const input = document.createElement('input');
      input.type = 'file';
      input.accept = 'image/*';
      Object.assign(input.style, { position: 'fixed', top: '12px', left: '12px', zIndex: 999999, background: '#fff', padding: '8px', border: '3px solid #22c55e', borderRadius: '6px' });
      document.body.appendChild(input);
      console.log('%cSelect the campaign photo in the file picker (top-left of the page).', 'color:#eab308;font-weight:bold');
      input.addEventListener('change', () => {
        const f = input.files && input.files[0];
        input.remove();
        if (!f) { reject(new Error('No file selected.')); return; }
        console.log('Photo selected:', f.name, '(' + f.size + ' bytes)');
        resolve(f);
      });
    });
  }

  const auth = await obtainAuth();
  const headers = (ct) => ({ accept: 'application/json, text/plain, */*', authorization: auth, 'content-type': ct, 'x-brand': BRAND });

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

  // Find the first freespinActivity anywhere in the payload (they all share the
  // same game), so we know the baked provider + game ids to look up / replace.
  function findFreespin(o) {
    if (!o || typeof o !== 'object') return null;
    if (o.freespinActivity && typeof o.freespinActivity === 'object' && o.freespinActivity.lobbyGameId) return o.freespinActivity;
    for (const k in o) { if (o[k] && typeof o[k] === 'object') { const r = findFreespin(o[k]); if (r) return r; } }
    return null;
  }
  const normGame = (s) => (s || '').replace(/[™®]/g, '').replace(/\s+/g, ' ').trim().toLowerCase();
  // One catalog query. translationKey is a case-insensitive substring filter and
  // the endpoint pages at size=100 (a provider can have 500+ slots), so we always
  // narrow with a search term — never fetch a whole provider and scan.
  async function searchGames(provider, term) {
    let url = BASE + '/journey-activities/free-spins-bonus-deposit/data/games'
      + '?freeSpinTypes=regular&productType=slots&page=0&size=100'
      + '&translationKey=' + encodeURIComponent(term);
    if (provider) url += '&gameProvider=' + encodeURIComponent(provider);
    const r = await fetch(url, { headers: headers('application/json'), credentials: 'include' });
    if (!r.ok) throw new Error('Game search HTTP ' + r.status);
    return (((await r.json()) || {}).items) || [];
  }
  // Resolve the exact catalog game (slot) + provider. The baked ids can be stale,
  // and the casino backend rejects publish if lobbyId/provider don't match a real
  // catalog game ("Game with lobbyId=... is not found"). We match the FULL name
  // exactly (ignoring the ™ glyph the catalog appends) — never a loose substring,
  // so we can't pick the wrong slot. If the typed provider doesn't contain the
  // game we retry across all providers and use whichever provider really owns it.
  async function resolveGame(provider, gameName) {
    const want = normGame(gameName);
    const term = (gameName || '').trim().split(/\s+/)[0];
    let items = [];
    try { items = await searchGames(provider, term); } catch (e) { if (provider) throw e; }
    let exact = items.filter((it) => normGame(it.translationKey) === want);
    if (!exact.length && provider) {
      // typed provider may be wrong/missing the game — search every provider
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
    // no exact name match — allow a single unambiguous prefix, else fail with the list
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
  // Mirrors what the real backoffice "duplicate" action sends: an unfiltered
  // copy on a multi-year-old bundle folder can hang/stall recursively
  // enumerating ancient assets, so the real UI always scopes ContentId
  // copies to named files via fileFilters. FrontId copies (spa/widget only)
  // are small and copied unfiltered, same as production.
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
    // Each target is an independent destination folder, safe to copy concurrently.
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

  // The visual content also bakes the bet amounts / game name / a literal
  // "until the end of <weekday>" line as plain marketing text (separate from
  // the {{PLACEHOLDER}} tokens the backend substitutes at runtime, which
  // need no fixing). These helpers rewrite that baked text to match this
  // run's --bets/--game/--date instead of whatever the template last had.
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

  // content-<lang>.json embeds absolute self-paths that include the bundle's
  // own id; after a raw copy they still point at the OLD id, so fetch, fix,
  // reupload. Constant filenames on journey bundles (no hash suffix).
  async function fixJourneyContentJson(newId, oldId, role, itemContentIds) {
    const targets = ['spa', 'widget', 'widgetModulor', 'cashier'];
    const langs = ['en', 'es'];
    // Each target/lang file is independent, safe to fetch+fix+reupload concurrently.
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

  // Promo-page content filenames are hash-suffixed and discovered via
  // manifest.json (not constant like journey bundles). Returns the bare
  // media filenames for the photo slots so the caller can upload to them.
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

  const photo = await pickFile();

  console.log('Reserving journey id...');
  const realId = await reserveId();
  console.log('  reserved', realId);

  const idMap = new Map();
  const fresh = {};
  for (const p of PLACEMENTS) {
    fresh[p.role] = { contentId: newUuid(), frontId: newUuid() };
    idMap.set(p.contentId, fresh[p.role].contentId);
    idMap.set(p.frontId, fresh[p.role].frontId);
  }
  walkReplace(PAYLOAD, idMap);

  // Swap the baked free-spin game ids + provider for the real catalog ones before posting.
  const fsSample = findFreespin(PAYLOAD);
  let text = JSON.stringify(PAYLOAD);
  if (fsSample) {
    const hit = await resolveGame(fsSample.provider, GAME_NAME);
    console.log('Resolved game "' + GAME_NAME + '" ->', { provider: hit.gameProvider, lobbyId: hit.lobbyId, walletId: hit.walletId, externalGameId: hit.externalGameId, name: hit.translationKey });
    const swaps = [];
    if (fsSample.lobbyGameId && hit.lobbyId) swaps.push([fsSample.lobbyGameId, hit.lobbyId]);
    if (fsSample.walletGameId && hit.walletId) swaps.push([fsSample.walletGameId, hit.walletId]);
    if (fsSample.externalGameId && hit.externalGameId) swaps.push([fsSample.externalGameId, hit.externalGameId]);
    // dedupe by source, drop no-ops, longest source first so a substring id can't be partly rewritten
    const uniq = swaps.filter(([a, b], i) => a && a !== b && swaps.findIndex((s) => s[0] === a) === i).sort((a, b) => b[0].length - a[0].length);
    for (const [a, b] of uniq) text = text.split(a).join(b);
    // provider is a plain word — replace only the freespin "provider":"x" field, surgically
    if (fsSample.provider && hit.gameProvider && fsSample.provider !== hit.gameProvider) {
      text = text.split('"provider":"' + fsSample.provider + '"').join('"provider":"' + hit.gameProvider + '"');
    }
    if (uniq.length) console.log('  rewrote game ids:', uniq.map((s) => s[0] + ' -> ' + s[1]).join(', '));
  }
  text = text.split('DRY-RUN-CASINO').join(realId);
  const regenResult = regen(text);
  const body = JSON.parse(regenResult.text);

  console.log('Creating journey draft', realId, ':', body.journeyName);
  const r = await fetch(BASE + '/journey-drafts', { method: 'POST', headers: headers('application/json'), credentials: 'include', body: JSON.stringify(body) });
  const resp = await r.text();
  if (!r.ok) { console.error('FAILED HTTP ' + r.status, resp); throw new Error('Journey draft not created.'); }
  console.log('%cJourney draft created: ' + realId, 'color:#22c55e;font-weight:bold');

  console.log('Cloning visual bundles and uploading the photo (5 placements, in parallel)...');
  const placementErrors = [];
  // The 5 placements clone to entirely distinct content/front ids, so they're
  // safe to run concurrently instead of one after another — this is most of
  // why earlier runs felt slow (dozens of strictly sequential round-trips).
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
      fields[`mf/v1/${ids.contentId}/widget/media/widgetImgKey.png`] = photo;
      if (p.role === 'offer') {
        for (const itemId of p.itemContentIds) fields[`mf/v1/${ids.contentId}/spa/media/${itemId}.itemImageKey.png`] = photo;
        fields[`mf/v1/${ids.contentId}/spa/media/prizeImageKey.png`] = photo;
      } else {
        fields[`mf/v1/${ids.contentId}/spa/media/bonusHeaderImage.png`] = photo;
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
  const offerNewActivityId = regenResult.map.get(offerPlacement.activityId);
  if (!offerNewActivityId) throw new Error('Could not resolve the regenerated offer activityId — cannot link the promo page.');
  console.log('Offer activityId (regenerated):', offerNewActivityId);

  console.log('Cloning promo-page visual bundle from', PROMO_SOURCE_CONTENT_ID, '/', PROMO_SOURCE_FRONT_ID, '...');
  const promoContentId = newUuid(), promoFrontId = newUuid();
  await copyBundleS3(PROMO_SOURCE_CONTENT_ID, promoContentId);
  await copyBundleS3(PROMO_SOURCE_FRONT_ID, promoFrontId);
  const slotNames = await fixPromoContentJson(promoContentId, PROMO_SOURCE_CONTENT_ID);
  console.log('  promo content', promoContentId, '| front', promoFrontId, '| photo slots', slotNames);
  const promoFields = {};
  if (slotNames.prizeImageKey) promoFields[`mf/v1/${promoContentId}/spa/media/${slotNames.prizeImageKey}`] = photo;
  if (slotNames.headerImageKey) promoFields[`mf/v1/${promoContentId}/spa/media/${slotNames.headerImageKey}`] = photo;
  if (slotNames.widgetImgKey) promoFields[`mf/v1/${promoContentId}/widget/media/${slotNames.widgetImgKey}`] = photo;
  if (Object.keys(promoFields).length) await uploadContentMulti(promoFields);
  console.log('%cPromo-page visual bundle cloned + photo uploaded.', 'color:#22c55e');

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
    urlShortName: newUuid(),
    promotionSettings: { type: 'JourneyPromotion', journeyPromotionSettings: { journeyId: realId, activityId: offerNewActivityId, activityDescription: PROMO_DESCRIPTION } },
    contentId: promoContentId,
    frontId: promoFrontId,
  };
  console.log('Creating promo page draft:', PROMO_INTERNAL_NAME);
  const pr = await fetch(CRM_BASE + '/promo/v2/promo-drafts/promo-page', { method: 'POST', headers: headers('application/json'), credentials: 'include', body: JSON.stringify(promoPayload) });
  const presp = await pr.text();
  if (!pr.ok) { console.error('FAILED HTTP ' + pr.status, presp); throw new Error('Promo page draft not created (journey draft ' + realId + ' was already created).'); }

  console.log('%cDONE.', 'color:#22c55e;font-weight:bold;font-size:14px');
  console.log('  Journey draft:    ' + realId);
  console.log('  Promo page draft: ' + presp);
})();
"""


def build_js(
    body: dict,
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
) -> str:
    js = JS_TEMPLATE
    js = js.replace("@GENERATED_AT@", datetime.now(LOCAL_TZ).strftime("%Y-%m-%d %H:%M %Z"))
    js = js.replace("@JOURNEY_NAME@", str(body.get("journeyName", "")))
    js = js.replace("@BASE_URL@", json.dumps(DEFAULT_BASE_URL))
    js = js.replace("@BRAND@", json.dumps(BRAND))
    js = js.replace("@PAYLOAD@", json.dumps(body, ensure_ascii=False))
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
    return js


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--date", required=True, help="Campaign start date YYYY-MM-DD (Chile)")
    p.add_argument("--days", type=int, default=1, help="Duration in days (default 1 -> next-day 00:00 stop)")
    p.add_argument("--bets", type=int, nargs="+", required=True, help="Per-tier bet (major units, ascending by deposit tier), e.g. 120 200 400 800")
    p.add_argument("--spins", type=int, help="Free-spin count (default: keep template value)")
    p.add_argument("--game", help="Known game shorthand: " + ", ".join(GAMES))
    p.add_argument("--lobby-game-id")
    p.add_argument("--wallet-game-id")
    p.add_argument("--external-game-id")
    p.add_argument("--provider")
    p.add_argument("--game-name")
    p.add_argument("--provider-name")
    p.add_argument("--promo-source-content-id", default=DEFAULT_PROMO_SOURCE_CONTENT_ID, help="ContentId of an existing GOW promo page to clone the visual bundle from")
    p.add_argument("--promo-source-front-id", default=DEFAULT_PROMO_SOURCE_FRONT_ID, help="FrontId of an existing GOW promo page to clone the visual bundle from")
    p.add_argument("--promo-description", default=DEFAULT_PROMO_DESCRIPTION, help="Free-text activityDescription shown in the promo page's journey link")
    p.add_argument("--name", default="gow_campaign", help="Output file basename (default: gow_campaign)")
    p.add_argument("--dry-run", action="store_true", help="Write prepared payload to out/ instead of a console script")
    args = p.parse_args()

    game = resolve_game(args)
    reserved_id = "DRY-RUN-CASINO"
    body, report, start_local, stop_local = prepare_campaign(
        date_str=args.date, days=args.days, game=game,
        bets_major=args.bets, spins=args.spins, reserved_id=reserved_id,
    )

    print("Applied:")
    for line in report:
        print("  " + line)

    print("Verification:")
    all_ok = True
    for ok, msg in casino_verify(body, game, args.bets):
        print(f"  {'OK  ' if ok else 'FAIL'} {msg}")
        all_ok = all_ok and ok
    if not all_ok:
        print("\nVERIFICATION FAILED — not writing output.", file=sys.stderr)
        return 1

    if args.dry_run:
        out = Path("out")
        out.mkdir(exist_ok=True)
        path = out / f"{args.name}_journey.json"
        path.write_text(json.dumps(body, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\nDry run — journey payload written: {path}")
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
        body,
        promo_source_content_id=args.promo_source_content_id,
        promo_source_front_id=args.promo_source_front_id,
        promo_description=args.promo_description,
        promo_internal_name=promo_internal_name,
        show_date=utc_dotnet(show_date),
        start_date=utc_dotnet(start_date),
        end_date=utc_dotnet(end_date),
        bets_major=args.bets,
        game_name=game["game_name"],
        provider_name=game["provider_name"],
        end_weekday_en=end_weekday_en,
        end_weekday_es=end_weekday_es,
    )
    print(f"\nVisual content text: bets {args.bets}, game {game['game_name']!r}, end weekday {end_weekday_en}/{end_weekday_es}")

    out = Path("console_scripts")
    out.mkdir(exist_ok=True)
    path = out / f"{args.name}_console.js"
    path.write_text(js, encoding="utf-8")
    print(f"\nConsole script written: {path}")
    print("Paste it into the DevTools console on a logged-in backoffice tab.")
    print("A file picker will pop up at the top-left of the page — pick the campaign photo there.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
