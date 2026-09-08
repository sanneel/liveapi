#!/usr/bin/env python3
"""Run a generated comms_copy_update console script against a stubbed backoffice.

Offline, no key. It builds a fake comms draft of the shape the real ones have
(both storages, both languages), generates the script from the example sheet,
executes it under node with `_comms_copy_harness.js` standing in for the browser
and the API, and then asserts on what the script tried to save:

  * the copy landed in the compiled activity AND its rawJourneyData mirror,
  * each picked photo reached its slot in both storages,
  * the email was created, saved and published BEFORE the draft was pointed at
    it, with both photo tokens filled,
  * the refusals fire when a slot or a node is missing.
"""
from __future__ import annotations

import copy as copymod
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CLONER = ROOT / "journey-cloner"
HARNESS = ROOT / "scripts" / "_comms_copy_harness.js"
SPEC = CLONER / "examples" / "champions_comms.tsv"

DRAFT_ID = "690315"
NAME = "JBCL | CS | Champions | comms"
LINK = "https://jugabet.cl/services/promo/offers/randomizer/cl-round-1?%$utm_tags%"
OLD_LINK = "https://jugabet.cl/services/promo/offers/randomizer/old-round?%$utm_tags%"
OLD_ICON = "https://cdn.example/old-icon.png"
OLD_BG = "https://cdn.example/old-background.png"

failures: list[str] = []


def check(cond: bool, what: str) -> None:
    print(("  ok   " if cond else "  FAIL ") + what)
    if not cond:
        failures.append(what)


def nc_init() -> dict:
    return {
        "contract": 1,
        "objectForSend": {"variables": [
            {"name": "title-en", "value": "OLD nc title en"},
            {"name": "title-es", "value": "OLD nc title es"},
            {"name": "des-en", "value": "OLD nc description en"},
            {"name": "des-es", "value": "OLD nc description es"},
            {"name": "caption-en", "value": "OLD NC CAPTION EN"},
            {"name": "caption-es", "value": "OLD NC CAPTION ES"},
            {"name": "link-en", "value": OLD_LINK},
            {"name": "link-es", "value": OLD_LINK},
            {"name": "icon", "value": OLD_ICON},
        ]},
        "singleChannel": {"localizedLanguagesTab": {
            "en": {"title": "OLD nc title en", "des": "OLD nc description en",
                   "caption": "OLD NC CAPTION EN", "link": OLD_LINK},
            "es": {"title": "OLD nc title es", "des": "OLD nc description es",
                   "caption": "OLD NC CAPTION ES", "link": OLD_LINK},
            "common": {"icon": OLD_ICON},
        }},
    }


def popup_init() -> dict:
    return {
        "contract": 5,
        "objectForSend": {"variables": [
            {"name": "title_en", "value": "OLD popup title en"},
            {"name": "title_es", "value": "OLD popup title es"},
            {"name": "description_en", "value": "OLD popup description en"},
            {"name": "description_es", "value": "OLD popup description es"},
            {"name": "caption_en", "value": "OLD POPUP CAPTION EN"},
            {"name": "caption_es", "value": "OLD POPUP CAPTION ES"},
            {"name": "background_image_src", "value": OLD_BG},
        ]},
        "singleChannel": {"localizedLanguagesTab": {
            "en": {"title": "OLD popup title en", "description": "OLD popup description en",
                   "caption": "OLD POPUP CAPTION EN"},
            "es": {"title": "OLD popup title es", "description": "OLD popup description es",
                   "caption": "OLD POPUP CAPTION ES"},
            "common": {"background_image_src": OLD_BG},
        }},
    }


def sms_init() -> dict:
    return {"rawValues": {"messageText": "JugaBet | OLD sms text en",
                          "localizedMessageTexts": {"en": {"messageText": "JugaBet | OLD sms text en"},
                                                    "es": {"messageText": "JugaBet | OLD sms text es"}}}}


def email_init() -> dict:
    return {"emailSettings": {"template": {"id": "CSE-0-11111", "name": "Last week's email"}},
            "displayData": ["CSE-0-11111"]}


def make_draft(*, with_email: bool = True, with_icon: bool = True) -> dict:
    nodes = [("nc-1", "notification_center", nc_init()),
             ("popup-1", "notification_center", popup_init()),
             ("sms-1", "dextra_sms", sms_init())]
    if with_email:
        nodes.append(("email-1", "dextra_email", email_init()))
    if not with_icon:
        vs = nodes[0][2]["objectForSend"]["variables"]
        nodes[0][2]["objectForSend"]["variables"] = [v for v in vs if v["name"] != "icon"]
        nodes[0][2]["singleChannel"]["localizedLanguagesTab"]["common"].pop("icon")

    activities, config = [], {}
    for aid, kind, init in nodes:
        activities.append({"journeyActivityId": aid, "activityName": kind,
                           "initializationData": copymod.deepcopy(init)})
        config[aid] = copymod.deepcopy(init)
    return {"id": int(DRAFT_ID), "journeyName": "JBCL | CS | Last week | comms",
            "activities": activities,
            "rawJourneyData": {"infoValues": {"journeyName": "JBCL | CS | Last week | comms"},
                               "activitiesConfiguration": config}}


def generate(tmp: Path, *, channels: str = "") -> Path:
    sys.path.insert(0, str(CLONER))
    cmd = [sys.executable, str(CLONER / "comms_copy_update.py"),
           "--draft-id", DRAFT_ID, "--name", NAME, "--link", LINK,
           "--spec", str(SPEC), "--live", "--basename", "harness_" + (channels or "all").replace(",", "_")]
    if channels:
        cmd += ["--channels", channels]
    subprocess.run(cmd, cwd=CLONER, check=True, capture_output=True, text=True)
    out = CLONER / "console_scripts" / f"harness_{(channels or 'all').replace(',', '_')}_console.js"
    dest = tmp / out.name
    dest.write_text(out.read_text(encoding="utf-8"), encoding="utf-8")
    out.unlink()
    return dest


def run(script: Path, draft: dict, tmp: Path) -> dict:
    dpath, opath = tmp / "draft.json", tmp / "result.json"
    dpath.write_text(json.dumps(draft), encoding="utf-8")
    proc = subprocess.run(["node", str(HARNESS), str(script), str(dpath), str(opath)],
                          capture_output=True, text=True)
    if not opath.exists():
        raise SystemExit(f"harness produced nothing.\n{proc.stdout}\n{proc.stderr}")
    return json.loads(opath.read_text(encoding="utf-8"))


def variables(body: dict, storage: str, aid: str) -> dict:
    init = (body["rawJourneyData"]["activitiesConfiguration"][aid] if storage == "mirror"
            else next(a["initializationData"] for a in body["activities"] if a["journeyActivityId"] == aid))
    return {v["name"]: v["value"] for v in init["objectForSend"]["variables"]}


def main() -> int:
    if not shutil.which("node"):
        print("node is not installed — skipping (the generator's own checks still run).")
        return 0

    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)

        print("full run — copy, four photos, email")
        res = run(generate(tmp), make_draft(), tmp)
        check(not res.get("error"), f"script ran without refusing (got {res.get('error')!r})")
        put = res.get("put")
        check(bool(put), "the draft was saved")
        if put:
            for storage in ("compiled", "mirror"):
                nc = variables(put, storage, "nc-1")
                check(nc["title-es"] == "🏆 ¡La Champions viene con premios!", f"nc title_es in {storage}")
                check(nc["des-en"].startswith("⚽ Real Madrid vs. Inter."), f"nc desc_en in {storage}")
                check(nc["caption-es"] == "RASPA Y GANA", f"nc caption_es in {storage}")
                check(nc["link-es"] == LINK, f"nc link in {storage}")
                check(nc["icon"] == "https://cdn.example/asset-1.png", f"nc icon photo in {storage}")
                pop = variables(put, storage, "popup-1")
                check(pop["description_es"].startswith("⚽ Real Madrid vs Inter."), f"popup desc_es in {storage}")
                check(pop["background_image_src"] == "https://cdn.example/asset-2.png",
                      f"popup background photo in {storage}")

            body = json.dumps(put, ensure_ascii=False)
            check(OLD_LINK not in body, "the previous campaign's link is gone")
            check(OLD_ICON not in body and OLD_BG not in body, "the previous campaign's artwork is gone")
            check("OLD nc title es" not in body, "the previous campaign's copy is gone")
            check(put["journeyName"] == NAME, "journeyName set")
            check(put["rawJourneyData"]["infoValues"]["journeyName"] == NAME, "journeyName set in infoValues")

            for storage in ("compiled", "mirror"):
                init = (put["rawJourneyData"]["activitiesConfiguration"]["email-1"] if storage == "mirror"
                        else next(a["initializationData"] for a in put["activities"]
                                  if a["journeyActivityId"] == "email-1"))
                check(init["emailSettings"]["template"]["id"] == "CSE-0-99999",
                      f"email activity points at the new content in {storage}")
                check(init["displayData"] == ["CSE-0-99999"], f"email displayData refreshed in {storage}")

        contents = res.get("contents") or []
        check(len(contents) >= 1, "the email content was created")
        if contents:
            src = contents[0]["translations"]["es"]["composition"]["body"]["source"]
            check("@@EMAIL_TOP_IMAGE_URL@@" not in src and "@@EMAIL_CTA_IMAGE_URL@@" not in src,
                  "both email photo tokens were filled")
            check(src.count("https://{{cdn_hostname}}/folder/asset-") == 2,
                  "both email photos are cdn_hostname-relative")
            check(src.count(LINK) == 2, "both email links point at this campaign")
            check("[[block(CSE-0-6450)]]" in src, "the footer block survived (unsubscribe + legal)")
            check("Raspa y Gana" in src, "the sheet's email body is in the content")
            check(contents[0]["translations"]["es"]["composition"]["subject"]
                  == "¡La Champions viene con premios!", "subject from the sheet")
        check(len(res.get("published") or []) == 1, "the content was published exactly once")
        check(len(res.get("uploads") or []) == 4, "four photos were uploaded")

        print("\nrefusal — the NC node has no icon variable")
        res = run(generate(tmp, channels="nc"), make_draft(with_icon=False, with_email=False), tmp)
        check("no captured variable is named icon" in str(res.get("error")),
              f"refused before asking for a photo (got {res.get('error')!r})")
        check(res.get("put") is None, "nothing was saved")
        check(not (res.get("uploads") or []), "nothing was uploaded")

        print("\nrefusal — the email is wanted but the draft has no email node")
        res = run(generate(tmp), make_draft(with_email=False), tmp)
        check("expected exactly one email node" in str(res.get("error")),
              f"refused on the missing node (got {res.get('error')!r})")
        check(res.get("put") is None, "nothing was saved")

    print()
    if failures:
        print(f"FAILED: {len(failures)}")
        for f in failures:
            print("  - " + f)
        return 1
    print("all checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
