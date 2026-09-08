#!/usr/bin/env python3
"""Run a generated comms_copy_update console script against a stubbed backoffice.

Offline, no key. It builds a fake comms draft of the shape the real ones have
(both storages, both languages), generates the script from the example sheet,
executes it under node with `_comms_copy_harness.js` standing in for the browser
and the API, and then asserts on what the script tried to create:

  * a NEW draft was POSTed and the source draft was never written,
  * the new draft carries a freshly reserved journey id and fresh activity ids,
  * the copy landed in the compiled activity AND its rawJourneyData mirror,
  * each picked photo reached its slot in both storages,
  * the email was created, saved and published BEFORE the draft was pointed at
    it, with both photo tokens filled,
  * the refusals fire when a slot or a node is missing, or when a channel the
    draft carries was left out and would ship the source journey's content.
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

SOURCE_DRAFT_ID = "690315"
NAME = "JBCL | CS | Champions | comms"
LINK = "https://jugabet.cl/services/promo/offers/randomizer/cl-round-1?%$utm_tags%"
OLD_LINK = "https://jugabet.cl/services/promo/offers/randomizer/old-round?%$utm_tags%"
OLD_ICON = "https://cdn.example/old-icon.png"
OLD_BG = "https://cdn.example/old-background.png"

# Real uuids: the script regenerates every activity id, and a draft whose ids
# did not change collides with the source journey in the builder.
NODE_IDS = {
    "nc": "11111111-1111-4111-8111-111111111111",
    "popup": "22222222-2222-4222-8222-222222222222",
    "sms": "33333333-3333-4333-8333-333333333333",
    "email": "44444444-4444-4444-8444-444444444444",
}

failures: list[str] = []


def check(cond: bool, what: str) -> None:
    print(("  ok   " if cond else "  FAIL ") + what)
    if not cond:
        failures.append(what)


def nc_init() -> dict:
    """The captured shape, from a real draft.

    Two kinds of variable live side by side: the ones holding copy
    (``title-en``) and the template's own slots holding a reference the platform
    resolves from them (``title`` -> ``"%title-en%"``). The slots repeat per
    language and are identical in every campaign; overwriting one breaks the
    card, so nothing here may treat them as content.
    """
    slots = []
    for lang in ("en", "es"):
        slots += [
            {"name": "title", "value": f"%title-{lang}%"},
            {"name": "icon-src", "value": "%icon%"},
            {"name": "description", "value": f"%des-{lang}%"},
            {"name": "buttons_1_link", "value": f"%link-{lang}%?%$utm_tags%"},
            {"name": "buttons_1_caption", "value": f"%caption-{lang}%"},
            {"name": "buttons_1_deeplink", "value": "%deeplink%?%$utm_tags%"},
        ]
    return {
        "contract": 1,
        "objectForSend": {"variables": slots + [
            {"name": "title-en", "value": "OLD nc title en"},
            {"name": "title-es", "value": "OLD nc title es"},
            {"name": "des-en", "value": "OLD nc description en"},
            {"name": "des-es", "value": "OLD nc description es"},
            {"name": "caption-en", "value": "OLD NC CAPTION EN"},
            {"name": "caption-es", "value": "OLD NC CAPTION ES"},
            {"name": "link-en", "value": OLD_LINK},
            {"name": "link-es", "value": OLD_LINK},
            {"name": "deeplink", "value": OLD_LINK},
            {"name": "icon", "value": OLD_ICON},
        ]},
        "singleChannel": {"localizedLanguagesTab": {
            "en": {"title": "OLD nc title en", "des": "OLD nc description en",
                   "caption": "OLD NC CAPTION EN", "link": OLD_LINK},
            "es": {"title": "OLD nc title es", "des": "OLD nc description es",
                   "caption": "OLD NC CAPTION ES", "link": OLD_LINK},
            "common": {"icon": OLD_ICON, "deeplink": OLD_LINK},
        }},
    }


def popup_init() -> dict:
    """The pop-up keeps its promo link in ONE language-independent ``link``:
    its per-language slots read ``"%link%?%$utm_tags%"``. Nothing per-language
    reaches it, which is how the pop-up shipped the source journey's link."""
    slots = []
    for lang in ("en", "es"):
        slots += [
            {"name": "title", "value": f"%title_{lang}%"},
            {"name": "description", "value": f"%description_{lang}%"},
            {"name": "buttons_1_link", "value": "%link%?%$utm_tags%"},
            {"name": "buttons_1_caption", "value": f"%caption_{lang}%"},
            {"name": "buttons_1_deeplink", "value": "%deeplink%?%$utm_tags%"},
        ]
    return {
        "contract": 5,
        "objectForSend": {"variables": slots + [
            {"name": "title_en", "value": "OLD popup title en"},
            {"name": "title_es", "value": "OLD popup title es"},
            {"name": "description_en", "value": "OLD popup description en"},
            {"name": "description_es", "value": "OLD popup description es"},
            {"name": "caption_en", "value": "OLD POPUP CAPTION EN"},
            {"name": "caption_es", "value": "OLD POPUP CAPTION ES"},
            {"name": "link", "value": OLD_LINK},
            {"name": "deeplink", "value": OLD_LINK},
            {"name": "background_image_src", "value": OLD_BG},
        ]},
        "singleChannel": {"localizedLanguagesTab": {
            "en": {"title": "OLD popup title en", "description": "OLD popup description en",
                   "caption": "OLD POPUP CAPTION EN"},
            "es": {"title": "OLD popup title es", "description": "OLD popup description es",
                   "caption": "OLD POPUP CAPTION ES"},
            "common": {"background_image_src": OLD_BG, "link": OLD_LINK, "deeplink": OLD_LINK},
        }},
    }


def sms_init() -> dict:
    return {"rawValues": {"messageText": "JugaBet | OLD sms text en",
                          "localizedMessageTexts": {"en": {"messageText": "JugaBet | OLD sms text en"},
                                                    "es": {"messageText": "JugaBet | OLD sms text es"}}}}


def email_init() -> dict:
    return {"emailSettings": {"template": {"id": "CSE-0-11111", "name": "Last week's email"}},
            "displayData": ["CSE-0-11111"]}


def make_draft(*, with_email: bool = True, with_icon: bool = True,
               drop_popup: bool = False) -> dict:
    nodes = [(NODE_IDS["nc"], "notification_center", nc_init()),
             (NODE_IDS["popup"], "notification_center", popup_init()),
             (NODE_IDS["sms"], "dextra_sms", sms_init())]
    if drop_popup:
        nodes = [n for n in nodes if n[0] != NODE_IDS["popup"]]
    if with_email:
        nodes.append((NODE_IDS["email"], "dextra_email", email_init()))
    if not with_icon:
        vs = nodes[0][2]["objectForSend"]["variables"]
        nodes[0][2]["objectForSend"]["variables"] = [v for v in vs if v["name"] != "icon"]
        nodes[0][2]["singleChannel"]["localizedLanguagesTab"]["common"].pop("icon")

    activities, config = [], {}
    for aid, kind, init in nodes:
        activities.append({"journeyActivityId": aid, "activityName": kind,
                           "initializationData": copymod.deepcopy(init)})
        config[aid] = copymod.deepcopy(init)
    return {"id": int(SOURCE_DRAFT_ID), "version": 3, "status": "DRAFT",
            "duplicatedFromId": "JRN-0-111111", "duplicatedFromVersion": 1,
            "reservedJourneyId": "JRN-0-111111",
            "brand": "JBCL", "journeyName": "JBCL | CS | Last week | comms",
            "activities": activities,
            "rawJourneyData": {"infoValues": {"journeyName": "JBCL | CS | Last week | comms"},
                               "activitiesConfiguration": config}}


def generate(tmp: Path, *, channels: str = "") -> Path:
    sys.path.insert(0, str(CLONER))
    cmd = [sys.executable, str(CLONER / "comms_copy_update.py"),
           "--source-draft-id", SOURCE_DRAFT_ID, "--name", NAME, "--link", LINK,
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


def node_of(body: dict, kind: str, contract: int | None = None) -> dict:
    """The created draft's activity ids are all fresh, so nodes are found by
    kind the way the console script finds them, not by the source's id."""
    for a in body["activities"]:
        if a["activityName"] != kind:
            continue
        if contract is None or a["initializationData"].get("contract") == contract:
            return a
    raise AssertionError(f"no {kind} node (contract {contract}) in the created draft")


def init_of(body: dict, storage: str, kind: str, contract: int | None = None) -> dict:
    a = node_of(body, kind, contract)
    if storage == "mirror":
        return body["rawJourneyData"]["activitiesConfiguration"][a["journeyActivityId"]]
    return a["initializationData"]


def variables(body: dict, storage: str, kind: str, contract: int | None = None) -> dict:
    return {v["name"]: v["value"] for v in init_of(body, storage, kind, contract)["objectForSend"]["variables"]}


def main() -> int:
    if not shutil.which("node"):
        print("node is not installed — skipping (the generator's own checks still run).")
        return 0

    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)

        print("full run — a new draft with copy, four photos and an email")
        res = run(generate(tmp), make_draft(), tmp)
        check(not res.get("error"), f"script ran without refusing (got {res.get('error')!r})")
        new_draft = res.get("created")
        check(bool(new_draft), "a NEW draft was POSTed")
        check(res.get("put") is None, "the source draft was never written")
        check(res.get("reserved") == ["JRN-0-777001"], "a fresh journey id was reserved")

        if new_draft:
            check(new_draft.get("reservedJourneyId") == "JRN-0-777001",
                  "the new draft carries the reserved id, not the source's")
            for gone in ("id", "version", "status", "duplicatedFromId", "duplicatedFromVersion"):
                check(gone not in new_draft, f"the source's {gone} was dropped")
            ids = {a["journeyActivityId"] for a in new_draft["activities"]}
            check(not (ids & set(NODE_IDS.values())), "every activity id was regenerated")
            check(set(new_draft["rawJourneyData"]["activitiesConfiguration"]) == ids,
                  "the mirror is keyed by the new activity ids")

            for storage in ("compiled", "mirror"):
                nc = variables(new_draft, storage, "notification_center", 1)
                check(nc["title-es"] == "🏆 ¡La Champions viene con premios!", f"nc title_es in {storage}")
                check(nc["des-en"].startswith("⚽ Real Madrid vs. Inter."), f"nc desc_en in {storage}")
                check(nc["caption-es"] == "RASPA Y GANA", f"nc caption_es in {storage}")
                check(nc["link-es"] == LINK, f"nc link in {storage}")
                check(nc["icon"] == "https://cdn.example/asset-1.png", f"nc icon photo in {storage}")
                pop = variables(new_draft, storage, "notification_center", 5)
                check(pop["description_es"].startswith("⚽ Real Madrid vs Inter."), f"popup desc_es in {storage}")
                check(pop["background_image_src"] == "https://cdn.example/asset-2.png",
                      f"popup background photo in {storage}")
                # The pop-up's link is language-independent; nothing per-language
                # reaches it, so it needs its own write or it ships the source's.
                check(pop["link"] == LINK, f"popup link in {storage}")
                check(pop["deeplink"] == LINK, f"popup deeplink in {storage}")
                check(nc["deeplink"] == LINK, f"nc deeplink in {storage}")
                # The template's own slots are structure, identical in every
                # campaign. Rewriting one breaks the card.
                for holder, label in ((nc, "nc"), (pop, "popup")):
                    for name, value in holder.items():
                        if name in ("title", "description", "icon-src") or name.startswith("buttons_1_"):
                            check(value.startswith("%") and value.endswith(("%", "%$utm_tags%")),
                                  f"{label}.{name} is still a slot reference in {storage}")
                em = init_of(new_draft, storage, "dextra_email")
                check(em["emailSettings"]["template"]["id"] == "CSE-0-99999",
                      f"email activity points at the new content in {storage}")
                check(em["displayData"] == ["CSE-0-99999"], f"email displayData refreshed in {storage}")

            body = json.dumps(new_draft, ensure_ascii=False)
            check(OLD_LINK not in body, "the source journey's link is gone")
            check(OLD_ICON not in body and OLD_BG not in body, "the source journey's artwork is gone")
            check("OLD nc title es" not in body, "the source journey's copy is gone")
            check("CSE-0-11111" not in body, "the source journey's email is gone")
            check(new_draft["journeyName"] == NAME, "journeyName set")
            check(new_draft["rawJourneyData"]["infoValues"]["journeyName"] == NAME,
                  "journeyName set in infoValues")

        contents = res.get("contents") or []
        check(len(contents) >= 1, "the email content was created")
        if contents:
            src = contents[0]["translations"]["es"]["composition"]["body"]["source"]
            check("@@EMAIL_TOP_IMAGE_URL@@" not in src and "@@EMAIL_CTA_IMAGE_URL@@" not in src,
                  "both email photo tokens were filled")
            check(src.count("https://{{cdn_hostname}}/folder/asset-") == 2,
                  "both email photos are cdn_hostname-relative")
            check(src.count(LINK) == 2, "both email links point at this campaign")
            check(src.count("[[block(CSE-0-10142)]]") == 1, "the banner block is intact")
            check(src.count("[[block(CSE-0-6450)]]") == 1, "the footer block is intact")
            check('width="85%"' in src, "the CTA image keeps its captured width")
            check("La máxima competición europea" in src and "Hazla Legendaria" in src,
                  "the sheet's email body is in the content, first line to last")
            check(contents[0]["translations"]["es"]["composition"]["subject"]
                  == "¡La Champions viene con premios!", "subject from the sheet")
        check(len(res.get("published") or []) == 1, "the content was published exactly once")
        check(len(res.get("uploads") or []) == 4, "four photos were uploaded")

        print("\nrefusal — the NC node has no icon variable")
        res = run(generate(tmp, channels="nc"), make_draft(with_icon=False, with_email=False,
                                                           drop_popup=True), tmp)
        check("no captured variable is named icon" in str(res.get("error")),
              f"refused before asking for a photo (got {res.get('error')!r})")
        check(res.get("created") is None, "nothing was created")
        check(not (res.get("uploads") or []), "nothing was uploaded")

        print("\nrefusal — the email is wanted but the source draft has no email node")
        res = run(generate(tmp), make_draft(with_email=False), tmp)
        check("expected exactly one email node" in str(res.get("error")),
              f"refused on the missing node (got {res.get('error')!r})")
        check(res.get("created") is None, "nothing was created")

        print("\nrefusal — a channel the draft carries was left out of --channels")
        res = run(generate(tmp, channels="nc,popup,sms"), make_draft(), tmp)
        check("would still carry the source journey's content" in str(res.get("error")),
              f"refused on the untouched email activity (got {res.get('error')!r})")
        check(res.get("created") is None, "no draft was created")
        check(not (res.get("uploads") or []), "no photo was uploaded")
        check(not (res.get("contents") or []), "no email was published")

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
