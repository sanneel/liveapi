#!/usr/bin/env python3
"""Contract for the tournament comms generators — offline, no key, no network.

Runs the SAME suite against both brands (PMCL and JBCL), because the whole point
of `tournament_comms_base` is that they cannot drift. Pins:

  * any link works and no Smartico id survives — the notification/pop-up get the
    path, the SMS gets https://{{BrandDomain}}<path>;
  * the sheet's Start/End dates own the two Wait/Date gates AND the notification
    revoke period;
  * the journey starts on its date at 12:00 Chile, not on publish;
  * nodes stay connected after the same id-regen the console script runs;
  * copy lands per node and per language (the string-replace trap);
  * verify() refuses on one broken rule at a time.
"""
from __future__ import annotations

import json
import re
import sys
import uuid
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE / "journey-cloner"))

import tournament_comms_base as B  # noqa: E402
import tournament_jbcl_campaign as JBCL_MOD  # noqa: E402
import tournament_pmcl_campaign as PMCL_MOD  # noqa: E402
import comms_engine as E  # noqa: E402

FAILURES: list[str] = []


def check(ok: bool, label: str) -> None:
    print(f"  {'ok  ' if ok else 'FAIL'} {label}")
    if not ok:
        FAILURES.append(label)


SHEET = "\n".join([
    "Event\tTorneo Test Copa",
    "Start date\t20.07.2026",
    "End date\t26.07.2026",
    # Deliberately a Smartico link with an id: the run must keep the PATH and
    # drop the deeplink entirely.
    "Link (Other)\thttps://jugabet.cl/xxx/yy/gg#_smartico_dp=dp:gf_tournaments&id=7777",
    "Notification\tTRUE\tTRUE",
    "Notification Title\tTournament EN\tTorneo ES",
    "Notification Description\tCompete now EN\tCompite ya ES",
    "Notification Button\tEnter EN\tEntrar ES",
    "Notification Pop-up (Cat-fish)\tTRUE\tTRUE",
    "Notification Pop-up (Cat-fish) Title\tPopup EN\tPopup ES",
    "Notification Pop-up (Cat-fish) Description\tPopup desc EN\tPopup desc ES",
    "Notification Pop-up (Cat-fish) Button\tGo EN\tIr ES",
    "Sms\tTRUE\tTRUE",
    "Sms Text\tBrand | tournament sms EN\tBrand | torneo sms ES",
    "Email\tTRUE\tTRUE",
    "Email Tittle\tTournament subject EN\tAsunto torneo ES",
    "Email Pre-header\tPreheader EN\tPre-encabezado ES",
    "Email Description\t⚡ Los dioses te llaman.",
])

LINK = "https://jugabet.cl/xxx/yy/gg"
PATH = "/xxx/yy/gg"
EMAIL_LINK = "https://jugabet.cl/launch/slots/iframe/pragmatic-test-game-1000"


def _tmp(text: str) -> Path:
    import tempfile
    p = Path(tempfile.mkdtemp()) / "sheet.tsv"
    p.write_text(text, encoding="utf-8")
    return p


def run_brand(mod, brand: B.Brand) -> None:
    print(f"\n{'=' * 62}\n{brand.title} tournament comms\n{'=' * 62}")
    spec = mod.read_spec(_tmp(SHEET), LINK)

    print("\nsheet parsing:")
    check(spec.link_path == PATH, f"the link's path is what ships ({spec.link_path!r})")
    check(spec.tournament_start_date == "2026-07-20"
          and spec.tournament_end_date == "2026-07-26",
          "the tournament window comes from the sheet, not an operator field")

    bundle, _report = mod.prepare(spec, date_str="2026-07-18", email_game=EMAIL_LINK)
    create, save = bundle["create"], bundle["save"]
    both = json.dumps(create, ensure_ascii=False) + json.dumps(save, ensure_ascii=False)

    print("\nany link, no Smartico id:")
    check(not B.SMARTICO_RE.search(both), "no Smartico deeplink anywhere")
    check("7777" not in both and "5431" not in both and "5196" not in both,
          "no tournament id anywhere")
    nc_link = f"{PATH}?%$utm_tags%"
    for node in (brand.nc_node, brand.popup_node):
        vals = set()
        for store in E.storages(save, E.comms_node(node)):
            tabs = (store.get("singleChannel") or {}).get("localizedLanguagesTab") or {}
            for tab in tabs.values():
                if isinstance(tab, dict):
                    for k, v in tab.items():
                        if k in E._LINK_FIELDS and not str(v).startswith("%"):
                            vals.add(v)
        check(vals == {nc_link}, f"{node}: every link field is {nc_link} ({sorted(vals)})")
    sms_texts = {e["messageText"] for a in save["activities"]
                 if a.get("activityName") == "dextra_sms"
                 for e in a["initializationData"]["smsSettings"]["localizedMessageTexts"]}
    want_sms_link = "https://{{BrandDomain}}" + PATH
    check(bool(sms_texts) and all(t.endswith("\n" + want_sms_link) for t in sms_texts),
          f"the SMS carries {want_sms_link} on its own line")
    check(all(t.startswith(brand.sms_prefix) for t in sms_texts),
          f"the SMS keeps its {brand.sms_prefix.strip()} prefix")
    check(len(sms_texts) == 2, "SMS EN and ES are distinct")

    print("\nthe sheet's window drives the gates AND the revoke period:")
    # As an ORDERED pair: the two brands store their gates in opposite order in
    # activities[], so a set comparison would let a swapped pair pass.
    gates = sorted(a["initializationData"]["waitTo"] for a in save["activities"]
                   if a.get("activityName") == "wait_date")
    check(gates == [B._gate("2026-07-20"), B._gate("2026-07-26")],
          f"the earlier gate is the start and the later one the end ({gates})")
    labels = sorted(a["initializationData"]["displayData"][0] for a in save["activities"]
                    if a.get("activityName") == "wait_date")
    check(labels == ["20.07.26", "26.07.26"],
          f"both gates' canvas labels show this tournament's days ({labels})")
    mirror = save["rawJourneyData"]["activitiesConfiguration"]
    mlabels = sorted(mirror[a["activityId"]]["displayData"][0] for a in save["activities"]
                     if a.get("activityName") == "wait_date"
                     and isinstance(mirror.get(a["activityId"], {}).get("displayData"), list))
    check(mlabels == ["20.07.26", "26.07.26"],
          f"the editor mirror carries the same labels ({mlabels})")
    revoke = sorted(set(re.findall(r'"expire_after"\s*:\s*"([^"]*)"', both)))
    check(revoke == ["7.00:00:00.000"],
          f"the revoke period is the tournament's 7 days ({revoke})")

    print("\nthe journey starts on its date, not on publish:")
    iv = save["rawJourneyData"]["infoValues"]
    check(save["isImmediatelyAfterPublish"] is False
          and iv["isImmediatelyAfterPublish"] is False,
          "isImmediatelyAfterPublish is false in BOTH storages")
    check(save["startAt"].startswith("2026-07-18") and "T16:00" in save["startAt"],
          f"startAt is the send date at 12:00 Chile ({save['startAt']})")
    check(save["stopAt"].startswith("2026-07-18") and "T23:00" in save["stopAt"],
          f"stopAt is 19:00 the same day ({save['stopAt']})")

    print("\nnodes stay connected — after the SAME id-regen the console script runs:")
    txt = json.dumps(create) + json.dumps(save)
    m = {o: str(uuid.uuid4())
         for o in set(re.findall(r'"(?:activityId|id)"\s*:\s*"([0-9a-fA-F-]{36})"', txt))}

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
    check({a["activityId"] for a in rc["activities"]} == {a["activityId"] for a in rs["activities"]},
          "create and save share the same activity ids after the shared regen")

    print("\nper-node, per-language copy (the string-replace trap):")
    def values_of(body, node):
        got = set()
        for store in E.storages(body, E.comms_node(node)):
            for tab in ((store.get("singleChannel") or {}).get("localizedLanguagesTab") or {}).values():
                if isinstance(tab, dict):
                    for k, v in tab.items():
                        if E._LANG_FIELD_RE.match(k) and not str(v).startswith("%"):
                            got.add(v)
        return got
    nc = values_of(save, brand.nc_node)
    pop = values_of(save, brand.popup_node)
    check({"Tournament EN", "Torneo ES"} <= nc, "NC title EN/ES distinct + correct")
    check({"Enter EN", "Entrar ES"} <= nc, "NC caption EN/ES distinct + correct")
    check({"Go EN", "Ir ES"} <= pop, "pop-up caption EN/ES distinct + correct")
    check("Entrar ES" not in pop, "pop-up is not wearing the notification's caption")

    print("\nemail content is built (hero token, sheet copy, CTA):")
    ec, es = bundle["email_create"], bundle["email_save"]
    check(ec is not None and es is not None, "email create + save bodies built")
    html = es["translations"]["es"]["composition"]["body"]["source"]
    check(B.EMAIL_HERO_TOKEN in html and brand.tpl_email_hero not in html,
          "hero is a token, captured hero gone")
    check(brand.tpl_email_cta not in html, "captured CTA target gone")
    check("Los dioses te llaman" in html, "sheet email body copy is in the HTML")
    check(es["translations"]["es"]["composition"]["subject"] == "Asunto torneo ES",
          "email subject from the sheet")
    check(B.EMAIL_ID_TOKEN in json.dumps(save), "journey email node is the paste-time token")
    check(brand.tpl_email_content_id not in both, "captured email content id gone from the journey")

    print("\nverify (happy path):")
    for ok, msg in mod.verify(bundle):
        check(ok, msg)

    print("\nverify refuses (one broken rule each):")
    def refuses(mutate, label):
        import copy
        b = dict(bundle)
        b["save"] = copy.deepcopy(bundle["save"])
        mutate(b)
        fails = [msg for ok, msg in mod.verify(b) if not ok]
        check(bool(fails), f"{label} -> refused ({fails[0][:46] if fails else 'NOT REFUSED'})")

    def keep_smartico(b):
        s = json.dumps(b["save"], ensure_ascii=False).replace(
            nc_link, "https://x?%$utm_tags%#_smartico_dp=dp:gf_tournaments&id=5431", 1)
        b["save"] = json.loads(s)
    refuses(keep_smartico, "a Smartico deeplink survives")

    def wrong_revoke(b):
        for a in b["save"]["activities"]:
            obj = (a.get("initializationData") or {}).get("objectForSend") or {}
            if "expire_after" in obj:
                obj["expire_after"] = "30.00:00:00.000"
                return
    refuses(wrong_revoke, "the revoke period is not the tournament's length")

    def wrong_gate(b):
        for a in b["save"]["activities"]:
            if a.get("activityName") == "wait_date":
                a["initializationData"]["waitTo"] = "2030-01-01T16:00:00Z"
                return
    refuses(wrong_gate, "a Wait/Date gate is off the tournament window")

    def stale_gate_label(b):
        for a in b["save"]["activities"]:
            if a.get("activityName") == "wait_date":
                a["initializationData"]["displayData"] = ["05.07.26"]
                return
    refuses(stale_gate_label, "a gate's canvas label is the captured tournament's")

    def start_on_publish(b):
        b["save"]["isImmediatelyAfterPublish"] = True
    refuses(start_on_publish, "the journey would start on publish")

    def break_edge(b):
        for a in b["save"]["activities"]:
            for ev in (a.get("events") or []):
                if ev.get("nextActivityId"):
                    ev["nextActivityId"] = "00000000-0000-4000-8000-000000000000"
                    return
    refuses(break_edge, "a nextActivityId points nowhere")

    def wrong_lang(b):
        for store in E.storages(b["save"], E.comms_node(brand.nc_node)):
            tabs = (store.get("singleChannel") or {}).get("localizedLanguagesTab") or {}
            for tab in tabs.values():
                if isinstance(tab, dict):
                    for k, v in tab.items():
                        if E._LANG_FIELD_RE.match(k) and not str(v).startswith("%"):
                            tab[k] = "wrong"
                            return
    refuses(wrong_lang, "a channel field no longer matches the sheet")

    print("\nrefusals on bad input:")
    def raises(fn, label):
        try:
            fn()
        except SystemExit as exc:
            check(True, f"{label} -> refused ({str(exc)[:44]})")
            return
        check(False, f"{label} -> NOT refused")
    raises(lambda: mod.read_spec(_tmp(SHEET), "https://jugabet.cl"),
           "a link with no path")
    raises(lambda: mod.read_spec(_tmp("Sms\tTRUE\nSms Text\tonly this"), LINK),
           "a sheet with no dates and no channels")
    no_dates = "\n".join(l for l in SHEET.splitlines()
                         if not l.startswith(("Start date", "End date")))
    raises(lambda: mod.read_spec(_tmp(no_dates), LINK),
           "a sheet missing the tournament window")
    backwards = SHEET.replace("End date\t26.07.2026", "End date\t10.07.2026")
    raises(lambda: mod.read_spec(_tmp(backwards), LINK),
           "an End date before the Start date")
    no_email_copy = SHEET.replace("Email Description\t⚡ Los dioses te llaman.", "")
    raises(lambda: mod.prepare(mod.read_spec(_tmp(no_email_copy), LINK),
                               date_str="2026-07-18", email_game=EMAIL_LINK),
           "no email body copy and no existing content id")
    if brand.email_cta_kind == "game":
        raises(lambda: mod.prepare(spec, date_str="2026-07-18", email_game=""),
               "no game for the email CTA")


def main() -> int:
    print("tournament comms contract — one suite, both brands")
    run_brand(PMCL_MOD, PMCL_MOD.PMCL)
    run_brand(JBCL_MOD, JBCL_MOD.JBCL)

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
