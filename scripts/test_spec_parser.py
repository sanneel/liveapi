#!/usr/bin/env python3
"""Parse the real comms sheet, the way the marketing team actually lays it out.

Offline, no key. Both cases here are bugs the hand-written fixture never showed,
found by running the parser against a sheet straight out of the spreadsheet:

  * a channel block followed by a second, EMPTY Tittle/Description pair for a
    nameless variant below it — those rows blanked the channel's real copy,
  * the Sms block, which names the channel on one row and ticks TRUE on the row
    underneath — the channel read as switched off.

spec_parser is shared with the GOW and tournament generators, so the simple
one-row-per-channel layout is checked here too.
"""
from __future__ import annotations

import csv
import io
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "journey-cloner"))

from spec_parser import parse_spec  # noqa: E402

failures: list[str] = []


def check(cond: bool, what: str) -> None:
    print(("  ok   " if cond else "  FAIL ") + what)
    if not cond:
        failures.append(what)


def tsv(rows: list[list[str]]) -> str:
    buf = io.StringIO()
    csv.writer(buf, delimiter="\t", quotechar='"', lineterminator="\n").writerows(rows)
    return buf.getvalue()


def row(label="", todo_en="", en="", max_en="", left_en="", todo_es="", es="",
        max_es="", left_es="") -> list[str]:
    """One row of the real sheet: label, EN block, then ES block."""
    return [label, "", todo_en, en, max_en, left_en, "", todo_es, es, max_es, left_es]


def main() -> int:
    print("the real sheet — an empty variant block follows the Notification")
    spec = parse_spec(tsv([
        row("Notification", todo_en="TRUE", todo_es="TRUE"),
        row("Tittle", en="Title EN", max_en="50", left_en="8", es="Title ES", max_es="50", left_es="15"),
        row("Description", en="Body EN", max_en="65", left_en="2", es="Body ES", max_es="65", left_es="8"),
        row("Button", en="GO", max_en="20", left_en="5", es="VAMOS", max_es="20", left_es="8"),
        # the nameless variant's rows, empty but for their symbol counters
        row("Tittle", max_en="80", left_en="80", max_es="80", left_es="80"),
        row("Description", max_en="90", left_en="90", max_es="90", left_es="90"),
    ]), expect_game_offer=False)
    check(spec.nc.title_es == "Title ES", "an empty repeat row does not blank the title")
    check(spec.nc.desc_es == "Body ES", "an empty repeat row does not blank the description")
    check(spec.nc.caption_es == "VAMOS", "the button survives")
    check(not spec.warnings, f"no warning was raised (got {spec.warnings})")

    print("\nthe real sheet — Sms ticks TRUE on the row under its name")
    spec = parse_spec(tsv([
        ["Sms "],
        row('Description (all sms should begin from: "JugaBet |")',
            todo_en="TRUE", en="JugaBet | EN text",
            todo_es="TRUE", es="JugaBet | ES text", max_es="130", left_es="30"),
    ]), expect_game_offer=False)
    check(spec.sms.enabled, "the channel is on")
    check(spec.sms.text_en == "JugaBet | EN text", "EN text")
    check(spec.sms.text_es == "JugaBet | ES text", "ES text")

    print("\na header that says FALSE stays off, whatever its rows carry")
    spec = parse_spec(tsv([
        row("Promo Lobby", todo_en="FALSE", todo_es="FALSE"),
        row("Tittle", todo_en="TRUE", en="should not switch it on"),
    ]), expect_game_offer=False)
    check(not spec.popup.enabled and not spec.nc.enabled, "no channel was switched on")

    print("\nthe simple layout the GOW and tournament sheets use")
    spec = parse_spec(tsv([
        ["Notification", "TRUE"],
        ["Tittle", "Title EN", "Title ES"],
        ["Description", "Body EN", "Body ES"],
        ["Button", "GO", "VAMOS"],
        ["Sms", "TRUE"],
        ["Text", "JugaBet | EN", "JugaBet | ES"],
    ]), expect_game_offer=False)
    check(spec.nc.enabled and spec.nc.title_es == "Title ES", "notification still parses")
    check(spec.sms.enabled and spec.sms.text_es == "JugaBet | ES", "sms still parses")

    print("\nthe repo's own example sheet")
    spec = parse_spec((ROOT / "journey-cloner" / "examples" / "champions_comms.tsv")
                      .read_text(encoding="utf-8"), expect_game_offer=False)
    for name in ("nc", "popup", "sms", "email"):
        check(getattr(spec, name).enabled, f"{name} is ticked TRUE")
    check(spec.nc.title_es == "🏆 ¡La Champions viene con premios!", "nc title")
    check(spec.popup.title_es == "🏆 Champions y premios", "popup title")
    check(spec.email.subject_es == "🏆 JugaBet: La Champions tiene premios", "email subject")
    check(spec.email.desc_es.startswith("La máxima competición europea"), "email body")
    check(spec.email.desc_es.rstrip().endswith("Hazla Legendaria."), "email body, last line")
    check(not spec.warnings, f"no warning was raised (got {spec.warnings})")

    print()
    if failures:
        print(f"FAILED: {len(failures)}")
        for f in failures:
            print("  - " + f)
        return 1
    print("all spec-parser checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
