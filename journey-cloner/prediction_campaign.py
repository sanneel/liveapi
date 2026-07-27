#!/usr/bin/env python3
"""
Update a "Multi Number Prediction" promo (JBCL gr8.tech backoffice) from a
pasted Google Sheets table: uploads SPA + widget content, the two manifests,
SPA + widget settings, then PUTs the promo draft -- replicating the exact
sequence and JSON shapes captured in
templates/prediction/multi_number_prediction.json (a HAR of one manual edit
of draft 35352, "final-champions-league-2025").

Matches the other promo/v2 campaign builders in this folder
(randomizer_campaign.py, casino_journey.py, gow_campaign.py): prepare() builds
the 9 request bodies from the template + sheet input, verify() sanity-checks
them, --dry-run writes them to out/<name>/ for review, and the live path
renders a console_scripts/<name>_console.js you paste into DevTools on a
logged-in backoffice tab -- it captures the Bearer token from the page's own
traffic and performs the 9 calls itself, using the ACTUAL path each upload
returns (never a locally-guessed filename) when building the manifests.

No secrets are read or written anywhere: BASE_URL/BRAND come from .env (same
convention as the rest of this folder); DRAFT_ID/CONTENT_ID/FRONT_ID identify
the existing draft you're editing (not secret -- just config) and can be
passed as flags or set in .env.

This tool EDITS an existing draft; it does not create one, and it does not GET
the draft's current state first (no such endpoint was captured in the HAR).
Fields the sheet doesn't drive (createDate, filterConditions, betsSettings,
playerVisibility, ...) fall back to the captured template's values, which
belong to a DIFFERENT promo. Pass --base-body <path.json> with a fresh
DevTools capture of the actual draft you're editing to override that base
safely; otherwise treat those fields as placeholders to review in --dry-run.

Input (--sheet <path|- for stdin>): a TSV/CSV block pasted straight from
Google Sheets, in two parts separated by one blank line:
  1. top-level fields -- either a header row + one data row, or one
     "key<TAB>value" row per field (either paste shape is accepted):
       internalName, urlShortName, brand, currency, languages (e.g. "en,es"),
       showDate, hideDate, expirationDate, startDate, endDate,
       headerTitle_en, headerTitle_es, termsText_en, termsText_es,
       prizeStructure_en, prizeStructure_es, howToParticipate_en,
       howToParticipate_es
  2. a header row + one row per prediction question:
       order  question_en  question_es  answer1_en  answer1_es
       answer0_en  answer0_es  answer2_en  answer2_es
     (answer2_en/es may be blank -> that question is Yes/No, maxValue 1)

Usage:
  python prediction_campaign.py --sheet sheet.tsv \
      --draft-id 35352 --content-id 9b5b9fe4-... --front-id c7b5e12f-... \
      --dry-run

  python prediction_campaign.py --sheet sheet.tsv \
      --draft-id 35352 --content-id 9b5b9fe4-... --front-id c7b5e12f-...
  # -> console_scripts/<name>_console.js ready to paste into DevTools
"""
from __future__ import annotations

import argparse
import copy
import csv
import hashlib
import io
import json
import os
import re
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from dotenv import load_dotenv

load_dotenv()

BASE_URL = os.getenv(
    "BASE_URL",
    "https://pmi.rea-backoffice.gr8.tech/api/ubo/api/v0/crm/journey-builder/v0",
).rstrip("/")
BRAND = os.getenv("BRAND", "JBCL")

HERE = Path(__file__).resolve().parent
TEMPLATE_PATH = HERE / "templates" / "prediction" / "multi_number_prediction.json"

REQUIRED_TOP_FIELDS = [
    "internalName", "urlShortName", "brand", "currency", "languages",
    "showDate", "hideDate", "expirationDate", "startDate", "endDate",
    "headerTitle_en", "headerTitle_es", "termsText_en", "termsText_es",
    "prizeStructure_en", "prizeStructure_es", "howToParticipate_en", "howToParticipate_es",
]
_TOP_FIELDS_LOWER = {f.lower(): f for f in REQUIRED_TOP_FIELDS}

REQUIRED_QUESTION_COLUMNS = [
    "order", "question_en", "question_es",
    "answer1_en", "answer1_es", "answer0_en", "answer0_es",
]
OPTIONAL_QUESTION_COLUMNS = ["answer2_en", "answer2_es"]
ALL_QUESTION_COLUMNS = REQUIRED_QUESTION_COLUMNS + OPTIONAL_QUESTION_COLUMNS


class SheetError(ValueError):
    """A problem with the pasted sheet input -- always meant to be shown to
    the person who pasted it, not a stack trace."""


# --------------------------------------------------------------------------
# Template
# --------------------------------------------------------------------------

def load_template() -> dict:
    return json.loads(TEMPLATE_PATH.read_text(encoding="utf-8-sig"))


# --------------------------------------------------------------------------
# Sheet parsing
# --------------------------------------------------------------------------

def _sniff_delimiter(text: str) -> str:
    first_line = text.split("\n", 1)[0]
    return "\t" if "\t" in first_line else ","


def _read_rows(text: str) -> list[list[str]]:
    """csv.reader (not a naive line split) so a multi-paragraph rich-text
    cell that Google Sheets quoted because it contains embedded newlines is
    kept as ONE row/cell, not mistaken for a blank-line block separator."""
    delim = _sniff_delimiter(text)
    return [row for row in csv.reader(io.StringIO(text), delimiter=delim)]


def _split_blocks(rows: list[list[str]]) -> tuple[list[list[str]], list[list[str]]]:
    sep = next((i for i, r in enumerate(rows) if all(not c.strip() for c in r)), None)
    if sep is None:
        raise SheetError(
            "Couldn't find the blank line separating the top-level fields from "
            "the questions table. Paste both blocks with exactly one empty line "
            "between them."
        )
    top_rows = [r for r in rows[:sep] if any(c.strip() for c in r)]
    q_rows = [r for r in rows[sep + 1:] if any(c.strip() for c in r)]
    return top_rows, q_rows


def _parse_top(top_rows: list[list[str]]) -> dict[str, str]:
    if not top_rows:
        raise SheetError("No top-level fields found before the blank-line separator.")
    first = [c.strip() for c in top_rows[0]]
    header_hits = sum(1 for c in first if c.lower() in _TOP_FIELDS_LOWER)
    if len(top_rows) >= 2 and header_hits >= max(3, len(first) // 2):
        header = first
        data = [c.strip() for c in top_rows[1]] + [""] * len(header)
        return {header[i]: data[i] for i in range(len(header)) if header[i]}
    kv: dict[str, str] = {}
    for r in top_rows:
        cells = [c.strip() for c in r]
        if len(cells) < 2 or not cells[0]:
            raise SheetError(f"Top-level row {r!r} isn't a 'key<TAB>value' pair.")
        kv[cells[0]] = cells[1]
    return kv


def validate_top(top: dict[str, str]) -> None:
    missing = [f for f in REQUIRED_TOP_FIELDS if not top.get(f, "").strip()]
    if missing:
        raise SheetError(
            f"Missing/blank top-level field(s): {', '.join(missing)}. "
            f"Got fields: {sorted(top.keys())}"
        )
    langs = [l.strip() for l in top["languages"].split(",") if l.strip()]
    if not langs:
        raise SheetError("'languages' is blank -- expected e.g. \"en,es\".")
    unsupported = [l for l in langs if l not in ("en", "es")]
    if unsupported:
        raise SheetError(
            f"'languages' contains {unsupported} -- this tool only builds en/es "
            f"content (the SPA/widget content templates only have en+es)."
        )


def to_platform_utc(value: str, *, field: str) -> str:
    """Parse a date the sheet gives us (assumed UTC if it has no offset) into
    the platform's exact '.0000000Z' shape."""
    v = value.strip()
    iso = v[:-1] + "+00:00" if v.endswith("Z") else v
    try:
        dt = datetime.fromisoformat(iso)
    except ValueError as e:
        raise SheetError(f"Bad date for '{field}': {value!r} ({e})") from e
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.0000000Z")


def build_forecast_title(order: str | int, question: str, answer1: str, answer0: str, answer2: str) -> str:
    line2 = f"( {answer1} - 1"
    if answer2:
        line2 += f" / {answer2} - 2"
    line2 += f" / {answer0} - 0 )"
    return f"<p>{order}. {question}</p>\n<p>{line2}</p>\n"


def _parse_questions(q_rows: list[list[str]]) -> list[dict[str, Any]]:
    if len(q_rows) < 2:
        raise SheetError("Questions block needs a header row plus at least one question row.")
    header = [c.strip() for c in q_rows[0]]
    missing = [c for c in REQUIRED_QUESTION_COLUMNS if c not in header]
    if missing:
        raise SheetError(
            f"Questions table is missing required column(s): {', '.join(missing)}. "
            f"Header seen: {header}"
        )
    idx = {name: header.index(name) for name in header if name}

    out: list[dict[str, Any]] = []
    seen_orders: set[str] = set()
    for n, r in enumerate(q_rows[1:], start=2):
        cells = [c.strip() for c in r] + [""] * len(header)
        get = lambda col: cells[idx[col]] if col in idx else ""  # noqa: E731

        row = {col: get(col) for col in ALL_QUESTION_COLUMNS}
        blanks = [col for col in REQUIRED_QUESTION_COLUMNS if not row[col]]
        if blanks:
            raise SheetError(f"question row {n}: blank required column(s): {', '.join(blanks)}")

        if bool(row["answer2_en"]) != bool(row["answer2_es"]):
            raise SheetError(
                f"question row {n}: answer2_en/answer2_es must both be blank or both "
                f"filled (got en={row['answer2_en']!r} es={row['answer2_es']!r})"
            )

        try:
            order = int(row["order"])
        except ValueError:
            raise SheetError(f"question row {n}: 'order' must be an integer, got {row['order']!r}") from None
        row["order"] = order
        if str(order) in seen_orders:
            raise SheetError(f"question row {n}: duplicate order {order} -- each question needs a distinct order")
        seen_orders.add(str(order))

        row["uuid"] = str(uuid4())
        has_answer2 = bool(row["answer2_en"])
        row["has_answer2"] = has_answer2
        row["title_en"] = build_forecast_title(order, row["question_en"], row["answer1_en"], row["answer0_en"], row["answer2_en"] if has_answer2 else "")
        row["title_es"] = build_forecast_title(order, row["question_es"], row["answer1_es"], row["answer0_es"], row["answer2_es"] if has_answer2 else "")
        out.append(row)

    if not out:
        raise SheetError("No question rows found.")
    return out


def parse_sheet(text: str) -> tuple[dict[str, str], list[dict[str, Any]]]:
    rows = _read_rows(text)
    top_rows, q_rows = _split_blocks(rows)
    top = _parse_top(top_rows)
    validate_top(top)
    questions = _parse_questions(q_rows)
    return top, questions


# --------------------------------------------------------------------------
# Payload builders
# --------------------------------------------------------------------------

def content_hash12(data: dict) -> str:
    """A stable 12-hex-char suffix, same shape as the platform's captured
    filenames (e.g. content-en-165c12cb8196.json). This is a LOCAL guess used
    only for --dry-run display and as the path sent in the upload request --
    live mode always uses the path the upload response actually returns for
    the manifest, so this guess being 'wrong' relative to whatever the real
    UI computes doesn't matter for correctness."""
    canon = json.dumps(data, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return hashlib.md5(canon).hexdigest()[:12]


def build_spa_content_data(lang: str, top: dict, questions: list[dict], template: dict) -> dict:
    base = copy.deepcopy(template["spa_content"][lang])
    base["headerTitleKey"] = top[f"headerTitle_{lang}"]
    base["ModalDetailsTitleDescriptionKey"] = top[f"termsText_{lang}"]
    base["PrizeFunText"] = top[f"prizeStructure_{lang}"]
    base["prizePoolDescriptionKey"] = top[f"howToParticipate_{lang}"]
    for q in questions:
        base[f"{q['uuid']}.forecastMultiTitleKey"] = q[f"title_{lang}"]
    return base


def build_widget_content_data(lang: str, top: dict, template: dict) -> dict:
    base = copy.deepcopy(template["widget_content"]["en"])
    if lang != "en":
        overrides = {k: v for k, v in template["widget_content"].get(lang, {}).items() if not k.startswith("_")}
        base.update(overrides)
    # The sheet gives one headerTitle per language, reused verbatim for the
    # widget's title (the captured template additionally bolds it with
    # <strong> for the widget vs. plain <p> for SPA -- not reproduced here
    # since the sheet doesn't carry that distinction; adjust if it matters).
    base["titleKey"] = top[f"headerTitle_{lang}"]
    return base


def build_prediction_validation_rule(questions: list[dict]) -> list[dict]:
    return [
        {"id": q["uuid"], "minValue": 0, "maxValue": 2 if q["has_answer2"] else 1}
        for q in questions
    ]


def build_put_body(top: dict, questions: list[dict], cfg: "Config", base_put: dict) -> dict:
    body = copy.deepcopy(base_put)
    body["internalName"] = top["internalName"]
    body["urlShortName"] = top["urlShortName"]
    langs = [l.strip() for l in top["languages"].split(",") if l.strip()]
    body["languages"] = langs
    body["currencies"] = [{"brand": top["brand"], "currency": top["currency"]}]
    for k in ("showDate", "hideDate", "expirationDate", "startDate", "endDate"):
        body[k] = to_platform_utc(top[k], field=k)
    body["initialShowDate"] = body["showDate"]
    body["initialExpirationDate"] = body["expirationDate"]
    body["initialEndDate"] = body["endDate"]
    body["predictionValidationRule"] = build_prediction_validation_rule(questions)
    body["id"] = str(cfg.draft_id)
    body["contentId"] = cfg.content_id
    body["frontId"] = cfg.front_id
    # Inherited from base_put untouched (not in the sheet's input schema):
    # playerVisibility, predictionAccountingPolicy, betsSettings,
    # filterConditions, subType, entrySourceRules, hasCsv, promoCode,
    # createDate, redirect, riskLevels.
    return body


# --------------------------------------------------------------------------
# Prepare / verify
# --------------------------------------------------------------------------

@dataclass
class Config:
    draft_id: str
    content_id: str
    front_id: str
    base_url: str
    brand: str


@dataclass
class PreparedBodies:
    spa_content: dict[str, dict]
    widget_content: dict[str, dict]
    spa_manifest: dict
    widget_manifest: dict
    spa_settings: dict
    widget_settings: dict
    put_body: dict
    questions: list[dict]
    top: dict
    cfg: Config


def prepare(sheet_text: str, cfg: Config, base_body_path: str | None = None) -> tuple[PreparedBodies, list[str]]:
    template = load_template()
    top, questions = parse_sheet(sheet_text)

    report = [
        f"internalName = {top['internalName']!r}",
        f"urlShortName = {top['urlShortName']!r}",
        f"{len(questions)} question(s), orders = {[q['order'] for q in questions]}",
        f"answer2 present on question(s) {[q['order'] for q in questions if q['has_answer2']]} (maxValue 2); "
        f"Yes/No on {[q['order'] for q in questions if not q['has_answer2']]} (maxValue 1)",
    ]

    spa_data = {lang: build_spa_content_data(lang, top, questions, template) for lang in ("en", "es")}
    widget_data = {lang: build_widget_content_data(lang, top, template) for lang in ("en", "es")}

    spa_content = {}
    for lang in ("en", "es"):
        fname = f"content-{lang}-{content_hash12(spa_data[lang])}.json"
        spa_content[lang] = {"path": f"mf/v1/{cfg.content_id}/spa/content/{fname}", "data": spa_data[lang]}

    widget_content = {}
    for lang in ("en", "es"):
        fname = f"content-{lang}-{content_hash12(widget_data[lang])}.json"
        widget_content[lang] = {"path": f"mf/v1/{cfg.content_id}/widget/content/{fname}", "data": widget_data[lang]}

    spa_manifest = {
        "path": f"mf/v1/{cfg.content_id}/spa/manifest.json",
        "data": {lang: spa_content[lang]["path"].rsplit("/", 1)[-1] for lang in ("en", "es")},
    }
    widget_manifest = {
        "path": f"mf/v1/{cfg.content_id}/widget/manifest.json",
        "data": {lang: widget_content[lang]["path"].rsplit("/", 1)[-1] for lang in ("en", "es")},
    }
    spa_settings = {"path": f"mf/v1/{cfg.front_id}/spa/settings.json", "data": copy.deepcopy(template["spa_settings"])}
    widget_settings = {"path": f"mf/v1/{cfg.front_id}/widget/settings.json", "data": copy.deepcopy(template["widget_settings"])}

    if base_body_path:
        base_put = json.loads(Path(base_body_path).read_text(encoding="utf-8-sig"))
        report.append(f"put_body base = {base_body_path} (overrides the packaged template)")
    else:
        base_put = template["put_body"]
        report.append(
            "put_body base = packaged template captured from a DIFFERENT promo -- "
            "createDate/filterConditions/betsSettings/etc. are that promo's values, "
            "not this draft's. Pass --base-body <captured-draft.json> to fix."
        )

    put_body = build_put_body(top, questions, cfg, base_put)
    report.append(f"predictionValidationRule: {len(put_body['predictionValidationRule'])} entrie(s), uuids = {[r['id'] for r in put_body['predictionValidationRule']]}")

    bodies = PreparedBodies(spa_content, widget_content, spa_manifest, widget_manifest,
                            spa_settings, widget_settings, put_body, questions, top, cfg)
    return bodies, report


def verify(b: PreparedBodies) -> list[tuple[bool, str]]:
    out: list[tuple[bool, str]] = []
    put = b.put_body
    out.append((bool(put.get("internalName")), "internalName set"))
    out.append((bool(put.get("urlShortName")), "urlShortName set"))
    dates = [put.get(k) for k in ("showDate", "startDate", "endDate", "hideDate")]
    out.append((all(dates) and dates == sorted(dates), "dates ordered show <= start <= end <= hide"))
    out.append((bool(put.get("languages")), "languages set"))
    out.append((bool(put.get("currencies")), "currencies set"))
    out.append((bool(put.get("contentId")) and bool(put.get("frontId")), "contentId + frontId present"))

    rules = put.get("predictionValidationRule", [])
    out.append((bool(rules), f"{len(rules)} predictionValidationRule entrie(s) present"))
    out.append((len({r["id"] for r in rules}) == len(rules), "no duplicate question uuids in predictionValidationRule"))

    ids_in_rules = {r["id"] for r in rules}
    for lang in ("en", "es"):
        ids_in_content = {k.rsplit(".", 1)[0] for k in b.spa_content[lang]["data"] if k.endswith(".forecastMultiTitleKey")}
        out.append((ids_in_rules == ids_in_content, f"predictionValidationRule ids exactly match forecastMultiTitleKey uuids in SPA content ({lang})"))
        out.append((bool(b.spa_content[lang]["path"]), f"spa content ({lang}) path present"))
        out.append((bool(b.widget_content[lang]["path"]), f"widget content ({lang}) path present"))

    out.append((b.spa_manifest["data"]["en"] == b.spa_content["en"]["path"].rsplit("/", 1)[-1], "spa manifest.en matches spa content(en) filename"))
    out.append((b.spa_manifest["data"]["es"] == b.spa_content["es"]["path"].rsplit("/", 1)[-1], "spa manifest.es matches spa content(es) filename"))
    out.append((b.widget_manifest["data"]["en"] == b.widget_content["en"]["path"].rsplit("/", 1)[-1], "widget manifest.en matches widget content(en) filename"))
    out.append((b.widget_manifest["data"]["es"] == b.widget_content["es"]["path"].rsplit("/", 1)[-1], "widget manifest.es matches widget content(es) filename"))
    return out


# --------------------------------------------------------------------------
# Request plan / dry-run
# --------------------------------------------------------------------------

def crm_base(base_url: str) -> str:
    return re.sub(r"/journey-builder/v0$", "", base_url.rstrip("/"))


def build_request_plan(b: PreparedBodies, cfg: Config) -> str:
    base = crm_base(cfg.base_url)
    upload_url = f"{base}/promo/v2/s3/upload"
    put_url = f"{base}/promo/v2/promo-drafts/multi-number-prediction/{cfg.draft_id}?draftId={cfg.draft_id}"
    steps = [
        ("SPA content (en)", b.spa_content["en"]),
        ("SPA content (es)", b.spa_content["es"]),
        ("Widget content (en)", b.widget_content["en"]),
        ("Widget content (es)", b.widget_content["es"]),
        ("SPA manifest", b.spa_manifest),
        ("Widget manifest", b.widget_manifest),
        ("SPA settings", b.spa_settings),
        ("Widget settings", b.widget_settings),
    ]
    lines = ["Request plan (dry-run -- nothing sent):"]
    for n, (label, payload) in enumerate(steps, start=1):
        size = len(json.dumps(payload, ensure_ascii=False).encode("utf-8"))
        lines.append(f"  {n}. POST {upload_url}  [{label}]  path={payload['path']}  ({size} bytes)")
    put_size = len(json.dumps(b.put_body, ensure_ascii=False).encode("utf-8"))
    lines.append(f"  9. PUT  {put_url}  [promo draft]  ({put_size} bytes)")
    return "\n".join(lines)


def write_dry_run(out: Path, b: PreparedBodies) -> None:
    steps = [
        ("01_spa_content_en.json", b.spa_content["en"]),
        ("02_spa_content_es.json", b.spa_content["es"]),
        ("03_widget_content_en.json", b.widget_content["en"]),
        ("04_widget_content_es.json", b.widget_content["es"]),
        ("05_spa_manifest.json", b.spa_manifest),
        ("06_widget_manifest.json", b.widget_manifest),
        ("07_spa_settings.json", b.spa_settings),
        ("08_widget_settings.json", b.widget_settings),
        ("09_put_body.json", b.put_body),
    ]
    for fname, payload in steps:
        (out / fname).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


# --------------------------------------------------------------------------
# Console script (live mode)
# --------------------------------------------------------------------------

JS_TEMPLATE = r"""// Multi Number Prediction console script — @LABEL@ — generated @GENERATED_AT@
// draft: @DRAFT_ID@   contentId: @CONTENT_ID@   frontId: @FRONT_ID@
//
// Paste into the DevTools console on a logged-in backoffice tab. It:
//   1. captures the auth token from the page's own requests,
//   2. uploads SPA content (en, es) and widget content (en, es),
//   3. uploads the SPA + widget manifests using the ACTUAL path each upload
//      above returned (never a locally-guessed filename),
//   4. uploads SPA + widget settings.json,
//   5. PUTs the promo draft.
// Stops at the first non-2xx response. Set PREVIEW=true to log the 9 request
// bodies WITHOUT sending them.
(async () => {
  'use strict';
  const PREVIEW = false;
  const MANUAL_TOKEN = '';
  const BASE = @BASE_URL@;
  const BRAND = @BRAND@;
  const DRAFT_ID = @DRAFT_ID@;
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

  const SPA_EN = @SPA_EN@;
  const SPA_ES = @SPA_ES@;
  const WIDGET_EN = @WIDGET_EN@;
  const WIDGET_ES = @WIDGET_ES@;
  const SPA_SETTINGS = @SPA_SETTINGS@;
  const WIDGET_SETTINGS = @WIDGET_SETTINGS@;
  const PUT_BODY = @PUT_BODY@;

  if (PREVIEW) {
    console.log('%cPREVIEW — not sending. 9 request bodies:', 'color:#eab308;font-weight:bold');
    [SPA_EN, SPA_ES, WIDGET_EN, WIDGET_ES, SPA_SETTINGS, WIDGET_SETTINGS].forEach((p) => console.log(p.path, p));
    console.log('PUT body', PUT_BODY);
    return;
  }

  const auth = await obtainAuth();
  const headers = () => ({ accept: 'application/json, text/plain, */*', authorization: auth, 'content-type': 'application/json', 'x-brand': BRAND });

  async function upload(payload, label) {
    const r = await fetch(CRM_BASE + '/promo/v2/s3/upload', { method: 'POST', headers: headers(), credentials: 'include', body: JSON.stringify(payload) });
    const text = await r.text();
    if (!r.ok) throw new Error(label + ' upload HTTP ' + r.status + ' ' + text);
    let parsed = {}; try { parsed = JSON.parse(text); } catch (e) {}
    const path = parsed.path || payload.path;
    console.log('%c✓ ' + label, 'color:#22c55e', path);
    return path;
  }

  console.log('Uploading SPA + widget content...');
  const spaEnPath = await upload(SPA_EN, 'SPA content (en)');
  const spaEsPath = await upload(SPA_ES, 'SPA content (es)');
  const widgetEnPath = await upload(WIDGET_EN, 'widget content (en)');
  const widgetEsPath = await upload(WIDGET_ES, 'widget content (es)');

  const basename = (p) => p.split('/').pop();
  const spaManifest = { path: SPA_EN.path.replace(/\/[^/]+$/, '/manifest.json'), data: { en: basename(spaEnPath), es: basename(spaEsPath) } };
  const widgetManifest = { path: WIDGET_EN.path.replace(/\/[^/]+$/, '/manifest.json'), data: { en: basename(widgetEnPath), es: basename(widgetEsPath) } };

  console.log('Uploading manifests (using the actual returned paths above)...');
  await upload(spaManifest, 'SPA manifest');
  await upload(widgetManifest, 'widget manifest');

  console.log('Uploading settings...');
  await upload(SPA_SETTINGS, 'SPA settings');
  await upload(WIDGET_SETTINGS, 'widget settings');

  console.log('Saving the promo draft (PUT)...');
  const putUrl = CRM_BASE + '/promo/v2/promo-drafts/multi-number-prediction/' + encodeURIComponent(DRAFT_ID) + '?draftId=' + encodeURIComponent(DRAFT_ID);
  const r = await fetch(putUrl, { method: 'PUT', headers: headers(), credentials: 'include', body: JSON.stringify(PUT_BODY) });
  const text = await r.text();
  if (!r.ok) throw new Error('promo draft PUT HTTP ' + r.status + ' ' + text);
  console.log('%c✓ Draft ' + DRAFT_ID + ' saved.', 'color:#22c55e;font-weight:bold');
})().catch((e) => console.error('%cFAILED: ' + e.message, 'color:#ef4444;font-weight:bold'));
"""


def build_js(b: PreparedBodies, cfg: Config) -> str:
    js = JS_TEMPLATE
    subs = {
        "@LABEL@": b.top.get("internalName", str(cfg.draft_id)),
        "@GENERATED_AT@": datetime.now(timezone.utc).isoformat(),
        "@BASE_URL@": json.dumps(cfg.base_url),
        "@BRAND@": json.dumps(cfg.brand),
        "@DRAFT_ID@": json.dumps(str(cfg.draft_id)),
        "@CONTENT_ID@": cfg.content_id,
        "@FRONT_ID@": cfg.front_id,
        "@SPA_EN@": json.dumps(b.spa_content["en"], ensure_ascii=False),
        "@SPA_ES@": json.dumps(b.spa_content["es"], ensure_ascii=False),
        "@WIDGET_EN@": json.dumps(b.widget_content["en"], ensure_ascii=False),
        "@WIDGET_ES@": json.dumps(b.widget_content["es"], ensure_ascii=False),
        "@SPA_SETTINGS@": json.dumps(b.spa_settings, ensure_ascii=False),
        "@WIDGET_SETTINGS@": json.dumps(b.widget_settings, ensure_ascii=False),
        "@PUT_BODY@": json.dumps(b.put_body, ensure_ascii=False),
    }
    for k, v in subs.items():
        js = js.replace(k, str(v))
    return js


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--sheet", required=True, help="path to pasted TSV/CSV, or - for stdin")
    p.add_argument("--draft-id", default=os.getenv("DRAFT_ID", ""), help="existing draft id, e.g. 35352 (or set DRAFT_ID in .env)")
    p.add_argument("--content-id", default=os.getenv("CONTENT_ID", ""), help="existing contentId GUID (or set CONTENT_ID in .env)")
    p.add_argument("--front-id", default=os.getenv("FRONT_ID", ""), help="existing frontId GUID (or set FRONT_ID in .env)")
    p.add_argument("--base-body", default="", help="path to a fresh DevTools capture of the ACTUAL draft's PUT body, "
                                                    "overriding the packaged template (recommended -- see module docstring)")
    p.add_argument("--name", default="", help="output basename (default: draft-<draft-id>)")
    p.add_argument("--dry-run", action="store_true", help="write the 9 prepared bodies + request plan to out/<name>/ instead of a console script")
    args = p.parse_args()

    missing_cfg = [flag for flag, val in (("--draft-id", args.draft_id), ("--content-id", args.content_id), ("--front-id", args.front_id)) if not val]
    if missing_cfg:
        print(f"Missing required config: {', '.join(missing_cfg)} (pass as flags, or set DRAFT_ID/CONTENT_ID/FRONT_ID in .env)", file=sys.stderr)
        return 1

    try:
        text = sys.stdin.read() if args.sheet == "-" else Path(args.sheet).read_text(encoding="utf-8-sig")
    except OSError as e:
        print(f"Couldn't read --sheet: {e}", file=sys.stderr)
        return 1

    cfg = Config(draft_id=args.draft_id, content_id=args.content_id, front_id=args.front_id, base_url=BASE_URL, brand=BRAND)

    try:
        bodies, report = prepare(text, cfg, base_body_path=args.base_body or None)
    except SheetError as e:
        print(f"Sheet error: {e}", file=sys.stderr)
        return 1

    print(f"Prepared prediction promo for draft {cfg.draft_id}:")
    for line in report:
        print(f"  • {line}")

    checks = verify(bodies)
    print("Verification:")
    all_ok = True
    for ok, msg in checks:
        if not ok:
            print(f"  FAIL {msg}")
        all_ok = all_ok and ok
    print(f"  {'OK  ' if all_ok else 'FAIL'} {len(checks)} check(s)")
    if not all_ok:
        print("\nVERIFICATION FAILED -- not writing output.", file=sys.stderr)
        return 1

    basename = args.name or f"draft-{cfg.draft_id}"
    plan = build_request_plan(bodies, cfg)

    if args.dry_run:
        out = Path("out") / basename
        out.mkdir(parents=True, exist_ok=True)
        write_dry_run(out, bodies)
        (out / "00_request_plan.txt").write_text(plan, encoding="utf-8")
        print(f"\nDry run -- 9 request bodies + request plan written to {out}/")
        print(plan)
        return 0

    print("\n" + plan)
    js = build_js(bodies, cfg)
    out = Path("console_scripts")
    out.mkdir(exist_ok=True)
    path = out / f"{basename}_console.js"
    path.write_text(js, encoding="utf-8")
    print(f"\nConsole script written: {path}")
    print("Paste it into the DevTools console on a logged-in backoffice tab (F12 -> Console -> allow pasting).")
    print("Tip: set PREVIEW=true at the top of the script to log the 9 request bodies WITHOUT sending them.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
