#!/usr/bin/env python3
"""Contract for tournament_pmcl_campaign.py — offline, no key, no network.

Pins the two failures the rebuild fixes: nodes that must stay connected (the
graph is checked after the same id-regen the console script does), and copy that
must land per node and per language (the string-replace trap). Also feeds
verify() one-broken-rule bodies to prove it refuses.
"""
from __future__ import annotations

import json
import re
import sys
import uuid
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE / "journey-cloner"))

import tournament_pmcl_campaign as T  # noqa: E402
import comms_engine as E  # noqa: E402
from spec_parser import parse_spec  # noqa: E402

FAILURES: list[str] = []


def check(ok: bool, label: str) -> None:
    print(f"  {'ok  ' if ok else 'FAIL'} {label}")
    if not ok:
        FAILURES.append(label)


SHEET = "\n".join([
    "Event\tTorneo Test Copa",
    "Link (Other)\thttps://jugabet.cl/page/torneo-test-copa#_smartico_dp=dp:gf_tournaments&id=7777",
    "Notification\tTRUE\tTRUE",
    "Notification Title\tTournament EN\tTorneo ES",
    "Notification Description\tCompete now EN\tCompite ya ES",
    "Notification Button\tEnter EN\tEntrar ES",
    "Notification Pop-up (Cat-fish)\tTRUE\tTRUE",
    "Notification Pop-up (Cat-fish) Title\tPopup EN\tPopup ES",
    "Notification Pop-up (Cat-fish) Description\tPopup desc EN\tPopup desc ES",
    "Notification Pop-up (Cat-fish) Button\tGo EN\tIr ES",
    "Sms\tTRUE\tTRUE",
    "Sms Text\tJugaBet | tournament sms EN\tJugaBet | torneo sms ES",
    "Email\tTRUE\tTRUE",
    "Email Tittle\tTournament subject EN\tAsunto torneo ES",
    "Email Pre-header\tPreheader EN\tPre-encabezado ES",
    "Email Description\t⚡ Los dioses te llaman.\\nJuega y gana ES.",
])

EMAIL_LINK = "https://jugabet.cl/launch/slots/iframe/pragmatic-test-game-1000"


def _spec():
    p = _tmp(SHEET)
    return T.read_spec(p, "https://jugabet.cl/page/torneo-test-copa#_smartico_dp=dp:gf_tournaments&id=7777")


def _tmp(text: str) -> Path:
    import tempfile
    p = Path(tempfile.mkdtemp()) / "sheet.tsv"
    p.write_text(text, encoding="utf-8")
    return p


def main() -> int:
    print("tournament_pmcl_campaign contract\n")

    spec = _spec()
    print("sheet parsing:")
    check(spec.promo_slug == "torneo-test-copa", f"page slug from the link ({spec.promo_slug!r})")
    check(spec.tournament_id == "7777", f"tournament id from the link ({spec.tournament_id!r})")

    bundle, report = T.prepare(
        spec, date_str="2026-07-20", tournament_start="2026-07-20",
        tournament_end="2026-07-27", email_game=EMAIL_LINK, upload_photos=True)
    create, save = bundle["create"], bundle["save"]

    print("\nnodes stay connected — after the SAME id-regen the console script runs:")
    # regen from the union, applied to both (what applyMap does at paste time)
    txt = json.dumps(create) + json.dumps(save)
    old = set(re.findall(r'"(?:activityId|id)"\s*:\s*"([0-9a-fA-F-]{36})"', txt))
    m = {o: str(uuid.uuid4()) for o in old}

    def apply(b):
        s = json.dumps(b)
        for o, n in m.items():
            s = s.replace(o, n)
        return json.loads(s)

    rc, rs = apply(create), apply(save)
    for label, b in (("create", rc), ("save", rs)):
        check(not E.dangling_edges(b), f"{label}: every nextActivityId resolves")
        check(not E.canvas_edges_to_missing_node(b), f"{label}: every canvas edge connects two real nodes")
        check(not E.activity_nodes_without_position(b), f"{label}: every activity node has positionAbsolute")
    ca = {a["activityId"] for a in rc["activities"]}
    sa = {a["activityId"] for a in rs["activities"]}
    check(ca == sa, "create and save share the same activity ids after the shared regen")

    print("\nper-node, per-language copy (the string-replace trap):")
    def tabs(body, node):
        got = {}
        for a in body["activities"]:
            init = a.get("initializationData") or {}
            if a.get("activityName") == "notification_center" and (init.get("singleChannel") or {}).get("activityName") == node:
                for tab in init["singleChannel"]["localizedLanguagesTab"].values():
                    if isinstance(tab, dict):
                        for k, v in tab.items():
                            if E._LANG_FIELD_RE.match(k) and not str(v).startswith("%"):
                                got[k] = v
        return got
    nc = tabs(save, T.NC_NODE)
    pop = tabs(save, T.POPUP_NODE)
    check(nc.get("title-en") == "Tournament EN" and nc.get("title-es") == "Torneo ES", "NC title EN/ES distinct + correct")
    check(nc.get("caption-en") == "Enter EN" and nc.get("caption-es") == "Entrar ES", "NC caption EN/ES distinct + correct")
    check(pop.get("caption_en") == "Go EN" and pop.get("caption_es") == "Ir ES", "pop-up caption EN/ES distinct + correct")
    check(pop.get("caption_es") != nc.get("caption-es"), "pop-up is not wearing the notification's caption")
    sms = {}
    for a in save["activities"]:
        if a.get("activityName") == "dextra_sms":
            for e in a["initializationData"]["smsSettings"]["localizedMessageTexts"]:
                sms[e["languageCode"]] = e["messageText"]
    check(sms.get("en") != sms.get("es") and "EN" in sms.get("en", ""), "SMS EN/ES distinct + correct")

    print("\nlinks + schedule:")
    both = json.dumps(create, ensure_ascii=False) + json.dumps(save, ensure_ascii=False)
    check(set(re.findall(r"/page/([a-z-]+)", both)) == {"torneo-test-copa"}, "one page slug everywhere")
    check(set(re.findall(r"[?&]id=(\d+)", both)) <= {"7777"}, "one tournament id everywhere")
    check(save["stopAt"].startswith("2026-07-20"), "stopAt is the send-day window")
    wd = [a["initializationData"]["waitTo"] for a in save["activities"] if a.get("activityName") == "wait_date"]
    check(wd == ["2026-07-27T16:00:00Z", "2026-07-20T16:00:00Z"], f"wait_date gates = tournament window ({wd})")

    print("\nemail content is built (hero token, sheet copy, game link):")
    ec, es = bundle["email_create"], bundle["email_save"]
    check(ec is not None and es is not None, "email create + save bodies built")
    html = es["translations"]["es"]["composition"]["body"]["source"]
    check("%%EMAIL_HERO%%" in html and "f4323497" not in html, "hero is a token, captured hero gone")
    check("/launch/slots/iframe/pragmatic-test-game-1000" in html, "email CTA links to this run's game")
    check("pragmatic-jugabet-leyendas-del-olympus" not in html, "captured game link gone")
    check("Los dioses te llaman" in html, "sheet email body copy is in the HTML")
    check(es["translations"]["es"]["composition"]["subject"] == "Asunto torneo ES", "email subject from the sheet")
    check("%%EMAIL_CONTENT_ID%%" in json.dumps(save), "journey email node is the paste-time token")
    check("CSE-0-14726" not in json.dumps(save), "captured email content id gone from the journey")

    print("\nverify (happy path):")
    for ok, msg in T.verify(bundle):
        check(ok, msg)

    print("\nverify refuses (one broken rule each):")
    def refuses(mutate, label):
        import copy
        b = copy.deepcopy(bundle)
        mutate(b)
        fails = [m for ok, m in T.verify(b) if not ok]
        check(bool(fails), f"{label} -> refused ({fails[0][:46] if fails else 'NOT REFUSED'})")

    def keep_slug(b):
        s = json.dumps(b["save"], ensure_ascii=False).replace("/page/torneo-test-copa", "/page/" + T.TPL_PAGE_SLUG, 1)
        b["save"] = json.loads(s)
    refuses(keep_slug, "a captured page slug survives")

    def keep_email(b):
        # in the build-email path the journey holds the paste-time token; a body
        # that still names the captured content must refuse
        s = json.dumps(b["save"], ensure_ascii=False).replace(T.EMAIL_ID_TOKEN, T.TPL_EMAIL_CONTENT_ID)
        b["save"] = json.loads(s)
    refuses(keep_email, "the email keeps the captured content id")

    def break_edge(b):
        for a in b["save"]["activities"]:
            for ev in (a.get("events") or []):
                if ev.get("nextActivityId"):
                    ev["nextActivityId"] = "00000000-0000-4000-8000-000000000000"
                    return
    refuses(break_edge, "a nextActivityId points nowhere")

    def wrong_lang(b):
        for a in b["save"]["activities"]:
            init = a.get("initializationData") or {}
            if (init.get("singleChannel") or {}).get("activityName") == T.NC_NODE:
                tab = init["singleChannel"]["localizedLanguagesTab"].get("en", {})
                for k in tab:
                    if k == "caption-en":
                        tab[k] = "wrong"
                        return
    refuses(wrong_lang, "a channel field no longer matches the sheet")

    print("\nrefusals on bad input:")
    def raises(fn, label):
        try:
            fn()
        except SystemExit as exc:
            check(True, f"{label} -> refused ({str(exc)[:42]})")
            return
        check(False, f"{label} -> NOT refused")
    raises(lambda: T.read_spec(_tmp(SHEET), "https://jugabet.cl/es/promo"), "a link that is not a tournament page")
    raises(lambda: T.read_spec(_tmp("Sms\tTRUE\nSms Text\tonly this"), ""), "a sheet missing the link + channels")

    print()
    if FAILURES:
        print(f"FAILED — {len(FAILURES)} check(s):")
        for f in FAILURES:
            print("  - " + f)
        return 1
    print("All checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
