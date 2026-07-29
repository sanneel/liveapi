#!/usr/bin/env python3
"""Contract for sport_comms_campaign.py — offline, no key, no network.

Two things this pins down, both of which are the bugs the runbook warns about:

  * `verify()` REFUSES rather than warns. Every guard is exercised by feeding it
    a body that violates exactly one rule and asserting it fails.
  * the prepared body differs from the captured template ONLY in the fields the
    generator means to change. That is the check that catches a value silently
    shipping the capture's own copy.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE / "journey-cloner"))

import sport_comms_campaign as G  # noqa: E402
from spec_parser import parse_spec  # noqa: E402

FAILURES: list[str] = []


def check(ok: bool, label: str) -> None:
    print(f"  {'ok  ' if ok else 'FAIL'} {label}")
    if not ok:
        FAILURES.append(label)


SHEET = "\n".join([
    "Event\tInglaterra vs Argentina",
    "Link (Other)\thttps://jugabet.cl/services/promo/offers/randomizer/eng-arg-final",
    "Notification\tTRUE",
    "Notification Title\tEngland vs Argentina: scratch and win\tInglaterra vs Argentina: raspa y gana",
    "Notification Description\tScratch the card, win a Bonus.\tRaspa la tarjeta, gana un Bono.",
    "Notification Button\tPlay now\tJuega ahora",
    "Notification Pop-up (Cat-fish)\tTRUE",
    "Notification Pop-up (Cat-fish) Title\tScratch & Win\tRaspa y Gana",
    "Notification Pop-up (Cat-fish) Description\tFinal on Sunday. Scratch and win.\tFinal el domingo. Raspa y gana.",
    "Notification Pop-up (Cat-fish) Button\tPlay\tJugar",
    "Sms\tTRUE",
    "Sms Text\tJugaBet | Scratch and win with the final. https://jugabet.cl/services/promo/offers/randomizer/OLD-SLUG"
    "\tJugaBet | Raspa y gana con la final.",
    "Email\tTRUE",
    "Email Tittle\tScratch and win with the final\tRaspa y Gana con la final",
    "Email Pre-header\tEngland vs Argentina, scratch and win\tInglaterra vs Argentina, raspa y gana",
    "Email Description\tScratch the card.\tRaspa la tarjeta.",
    "Email Button\tPlay\tJugar",
])


def campaign(**over) -> dict:
    base = {
        "slug": "eng-arg-final",
        "title": "ENG vs ARG Final",
        "sport": "football",
        "mode": "manual",
        "enabled": True,
        "expires_at": datetime.now(timezone.utc) + timedelta(days=7),
        "image_url": "https://example.test/r/eng-arg-final.png",
    }
    base.update(over)
    return base


def main() -> int:
    print("sport_comms_campaign contract\n")

    print("sheet parsing:")
    spec = parse_spec(SHEET, expect_game_offer=False)
    check(spec.promo_slug == "eng-arg-final", f"promo slug from the Link row ({spec.promo_slug!r})")
    check(spec.nc.title_en != spec.nc.title_es, "notification EN and ES copy kept apart")
    check(bool(spec.email.subject_es and spec.email.preheader_es), "email subject + pre-header parsed")

    print("\nprepare:")
    bundle, report = G.prepare(campaign(), spec)
    create, save = bundle["journey_create"], bundle["journey_save"]
    both = json.dumps(create, ensure_ascii=False) + json.dumps(save, ensure_ascii=False)
    email = json.dumps(bundle["email_save"], ensure_ascii=False)

    check("ENG vs ARG Final" in save["journeyName"], "journey named from the campaign title")
    check(save["journeyName"] == save["rawJourneyData"]["infoValues"]["journeyName"],
          "journeyName identical in both storages")
    check("/randomizer/eng-arg-final" in both, "channels link to the sheet's promo slug")
    # The sheet's own SMS copy carried a stale link; it must have been rewritten.
    check("OLD-SLUG" not in both, "stale promo link in the sheet's SMS copy rewritten")
    check(both.count("/randomizer/eng-arg-final") >= 6, "every channel link rewritten")
    check("Inglaterra vs Argentina: raspa y gana" in both, "ES notification title written")
    check("England vs Argentina: scratch and win" in both, "EN notification title written")
    check("Raspa y Gana con la final" in email, "email subject written")
    check(G.TPL_EMAIL_CONTENT_ID not in both, "captured email content id gone")
    check(G.EMAIL_ID_TOKEN in both, "email id placeholder present")

    print("\nverify (the happy path):")
    for ok, msg in G.verify(bundle):
        check(ok, msg)

    print("\ndiff against the captured template — only intended fields may differ:")
    template = json.loads(G.TPL_SAVE.read_text(encoding="utf-8"))

    def leaves(obj, path=""):
        if isinstance(obj, dict):
            for k, v in obj.items():
                yield from leaves(v, f"{path}.{k}" if path else k)
        elif isinstance(obj, list):
            for i, v in enumerate(obj):
                yield from leaves(v, f"{path}.{i}")
        else:
            yield path, obj

    tpl = dict(leaves(template))
    new = dict(leaves(save))
    changed = {k for k in tpl.keys() & new.keys() if tpl[k] != new[k]}

    # Match on the VALUE that landed, not the field name: a value the generator
    # never meant to write is exactly the bug this check exists to catch, and it
    # can land in a field whose name says nothing (objectForSend.variables.N.value).
    written = [
        bundle["journey_name"], bundle["journey_name_nc"],
        G.PROMO_URL.format(slug="eng-arg-final"),
        "eng-arg-final", spec.nc.title_en, spec.nc.title_es, spec.nc.desc_en,
        spec.nc.desc_es, spec.nc.caption_en, spec.nc.caption_es,
        spec.popup.title_en, spec.popup.title_es, spec.popup.desc_en,
        spec.popup.desc_es, spec.popup.caption_en, spec.popup.caption_es,
        G.RESERVED_TOKEN, G.EMAIL_ID_TOKEN, G.NC_ICON_TOKEN, G.POPUP_BG_TOKEN,
        save["rawJourneyData"]["infoValues"]["stopAt"], save["stopAt"],
    ]
    written += [G._sms_text(spec.sms.text_en, "eng-arg-final"),
                G._sms_text(spec.sms.text_es, "eng-arg-final")]

    def explained(value) -> bool:
        if value is None:          # lineage we deliberately cleared
            return True
        if not isinstance(value, str):
            return False
        return any(w and (w == value or w in value) for w in written)

    unexplained = sorted(k for k in changed if not explained(new[k]))
    check(not unexplained, f"every changed leaf holds a value we meant to write ({len(changed)} changed)"
          + (f" — {[(k, str(new[k])[:40]) for k in unexplained[:3]]}" if unexplained else ""))
    check(set(tpl) - set(new) == set() and set(new) - set(tpl) == set(),
          "no field added or dropped versus the template")

    print("\nverify refuses (each body breaks exactly one rule):")

    def refuses(mutate, label):
        import copy
        broken = copy.deepcopy(bundle)
        mutate(broken)
        failed = [m for ok, m in G.verify(broken) if not ok]
        check(bool(failed), f"{label} -> refused ({failed[0][:52] if failed else 'NOT REFUSED'})")

    def unwire_email(b):
        s = json.dumps(b["journey_save"], ensure_ascii=False)
        b["journey_save"] = json.loads(s.replace(G.EMAIL_ID_TOKEN, G.TPL_EMAIL_CONTENT_ID))
    refuses(unwire_email, "journey still points at the copied campaign's email")

    def keep_old_slug(b):
        s = json.dumps(b["journey_save"], ensure_ascii=False)
        b["journey_save"] = json.loads(s.replace("/randomizer/eng-arg-final",
                                                 f"/randomizer/{G.TPL_SLUG_EN}", 1))
    refuses(keep_old_slug, "one channel left on the captured promo slug")

    def keep_icon(b):
        s = json.dumps(b["journey_save"], ensure_ascii=False)
        b["journey_save"] = json.loads(s.replace(G.NC_ICON_TOKEN, G.TPL_NC_ICON))
    refuses(keep_icon, "notification keeps the captured artwork")

    def keep_name(b):
        b["journey_save"]["journeyName"] = G.TPL_JOURNEY_SP
    refuses(keep_name, "journey keeps the captured name")

    def desync(b):
        b["journey_save"]["rawJourneyData"]["infoValues"]["journeyName"] = "something else"
    refuses(desync, "the two storages disagree on journeyName")

    def dangle(b):
        for a in b["journey_save"]["activities"]:
            for ev in (a.get("events") or []):
                if ev.get("nextActivityId"):
                    ev["nextActivityId"] = "00000000-0000-4000-8000-000000000000"
                    return
    refuses(dangle, "a nextActivityId points nowhere")

    def strip_position(b):
        acts = {a.get("activityId") for a in b["journey_save"]["activities"]}
        for e in b["journey_save"]["rawJourneyData"]["elements"]:
            if e.get("id") in acts:
                e["positionAbsolute"] = None
                return
    refuses(strip_position, "an activity node lost positionAbsolute")

    def alien_node(b):
        b["journey_save"]["rawJourneyData"]["elements"].append(
            {"id": "not-an-activity", "type": "somethingElse",
             "position": {"x": 0, "y": 0}, "positionAbsolute": {"x": 0, "y": 0}})
    refuses(alien_node, "a canvas node that is neither activity nor scaffolding")

    print("\nrefusals on bad input:")

    def raises(fn, label):
        try:
            fn()
        except SystemExit as exc:
            check(True, f"{label} -> refused ({str(exc)[:48]})")
            return
        check(False, f"{label} -> NOT refused")

    raises(lambda: G.prepare(campaign(expires_at=None), spec),
           "campaign with no expiry and no stop date")
    raises(lambda: G.prepare(campaign(expires_at=datetime.now(timezone.utc) - timedelta(days=1)), spec),
           "campaign already expired")
    raises(lambda: G.prepare(campaign(), spec, stop_at="not-a-date"),
           "an unparseable stop date")
    raises(lambda: G.prepare(campaign(expires_at=None), spec, stop_at="2020-01-01T00:00"),
           "a stop date in the past")

    print("\npromo link given on the run:")
    sheet_path = _write_tmp(SHEET)
    over = G.read_spec(sheet_path, "https://jugabet.cl/services/promo/offers/randomizer/other-page")
    check(over.promo_slug == "other-page", "an explicit link overrides the sheet's Link row")
    check(G.read_spec(sheet_path, "bare-slug").promo_slug == "bare-slug", "a bare slug is accepted")
    check(G.read_spec(sheet_path, "").promo_slug == "eng-arg-final", "blank falls back to the sheet")

    # A sheet with NO Link row must still build when the field supplies one.
    no_link = _write_tmp("\n".join(l for l in SHEET.splitlines() if not l.startswith("Link")))
    spec2 = G.read_spec(no_link, "https://jugabet.cl/services/promo/offers/randomizer/only-field")
    b5, _ = G.prepare(campaign(), spec2)
    both5 = json.dumps(b5["journey_save"], ensure_ascii=False) + json.dumps(b5["email_save"], ensure_ascii=False)
    check("/randomizer/only-field" in both5, "a sheet with no Link row builds from the field alone")
    # The whole reason this is one field: it has to be right in all four at once.
    save5 = json.dumps(b5["journey_save"], ensure_ascii=False)
    for chan, probe in [("sms", "jugabet.cl/services/promo/offers/randomizer/only-field"),
                        ("notification/pop-up", "/randomizer/only-field?%$utm_tags%"),
                        ("email", "/randomizer/only-field")]:
        src = json.dumps(b5["email_save"], ensure_ascii=False) if chan == "email" else save5
        check(probe in src, f"the link reached {chan}")

    raises(lambda: G.read_spec(sheet_path, "https://jugabet.cl/es/football/live"),
           "a link that is not a randomizer promo page")
    raises(lambda: G.read_spec(no_link, ""),
           "no link in either the field or the sheet")

    print("\nstop date:")
    # The whole point of the field: a campaign with no expiry is still usable,
    # which is what an eligibility filter on the dropdown took away.
    future = (datetime.now() + timedelta(days=5)).strftime("%Y-%m-%dT%H:%M")
    b2, _ = G.prepare(campaign(expires_at=None), spec, stop_at=future)
    check(b2["journey_save"]["rawJourneyData"]["infoValues"]["stopAt"].startswith(future[:10]),
          f"a campaign with no expiry builds when given a stop date ({future[:10]})")
    b3, _ = G.prepare(campaign(), spec)
    check(bool(b3["journey_save"]["stopAt"]), "campaign expiry is still the default stop date")
    b4, _ = G.prepare(campaign(), spec, stop_at=future)
    check(b4["journey_save"]["rawJourneyData"]["infoValues"]["stopAt"].startswith(future[:10]),
          "an explicit stop date overrides the campaign expiry")
    raises(lambda: G.read_spec(_write_tmp("Sms\tTRUE\nSms Text\tonly this")),
           "sheet with no Link row / missing channels")

    print()
    if FAILURES:
        print(f"FAILED — {len(FAILURES)} check(s):")
        for f in FAILURES:
            print("  - " + f)
        return 1
    print("All checks passed.")
    return 0


def _write_tmp(text: str) -> Path:
    import tempfile
    p = Path(tempfile.mkdtemp()) / "sheet.tsv"
    p.write_text(text, encoding="utf-8")
    return p


if __name__ == "__main__":
    raise SystemExit(main())
