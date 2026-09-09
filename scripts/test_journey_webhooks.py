#!/usr/bin/env python3
"""Contract for the webhook lister — offline, no network.

It reads journeys and writes a table an integration is configured from, so the
pins are that it stays read-only and that the numbers come from the payload:

  * only JRN ids are accepted, duplicates and anything else are reported;
  * the amount and the rollover are read from the bonus activity, not parsed
    out of the journey name;
  * it creates nothing: no POST, no PUT, no draft, no publish;
  * when no URL can be resolved it prints the ids and says what to send back,
    rather than inventing a URL.
"""
from __future__ import annotations

import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE / "journey-cloner"))

import journey_webhooks as W  # noqa: E402

failures: list[str] = []


def check(good: bool, label: str) -> None:
    print(f"  [{'OK' if good else 'FAIL'}]   {label}")
    if not good:
        failures.append(label)


def section(title: str) -> None:
    print(f"\n── {title}")


section("the id list")
ids, problems = W.parse_ids("JRN-0-685173, JRN-0-685175\nJRN-0-685173\n693903\nnonsense\n\nJRN-0-685177 ")
check(ids == ["JRN-0-685173", "JRN-0-685175", "JRN-0-685177"], f"reads ids in the order given ({ids})")
check(any("twice" in p for p in problems), "a repeated id is reported, not fetched twice")
check(any("693903" in p for p in problems), "a draft id is refused: this endpoint takes journeys")
check(any("nonsense" in p for p in problems), "anything else is reported")
check(all(c for c, _ in W.verify(ids)), "a clean list passes")
check(not all(c for c, _ in W.verify([])), "an empty list is refused")
check(not all(c for c, _ in W.verify(["JRN-0-1", "jrn-0-1"])), "the same id twice in any case is refused")

section("the emitted script")
js = W.build_js(ids)
check("apiBase(" in js, "it follows the API gateway the page is using")
check("'/journeys/' + id" in js, "it reads each journey by its JRN id")
check("method: 'POST'" not in js and "method: 'PUT'" not in js and "method: 'PATCH'" not in js,
      "it is read-only: no POST, PUT or PATCH anywhere")
check("journey-drafts" not in js and "/publish" not in js and "/start" not in js,
      "it touches no draft and publishes nothing")
check("fixedBonusAmount_majorUnits" in js and "currencyAmounts" in js,
      "the amount comes from the mechanic, in the units each kind stores")
check("wageringRequirement" in js, "the rollover comes from the casino bonus itself")
check("external_system_source" in js, "it looks for the API node")
check("does not start at an API node" in js, "a journey without one is listed as missing, not skipped silently")
check("the API node carries no webhookId" in js, "an API node without an id is reported")
check(W.WEBHOOK_URL_TEMPLATE == "https://webhooks.flw.rest/{id}/",
      "the URL is the one an API node shows, in one place")
check("https://webhooks.flw.rest/" in js, "the template travels with the script")
check("{id}" in W.WEBHOOK_URL_TEMPLATE, "the template names where the id goes")
other = W.build_js(ids, "https://example.test/hook/{id}")
check("https://webhooks.flw.rest/" not in other and "https://example.test/hook/" in other,
      "--url-template replaces it without touching anything else")
check("Amount (CLP)\', \'Prize\', \'Webhook URL\', \'Journey ID\', \'Webhook ID" in js,
      "the sheet block is headed")
check("__webhookTsv" in js and "__webhookCsv" in js,
      "both a paste-into-A1 block and a CSV are left behind")
check("paste into A1" in js, "it says where to paste")
check(all(i in js for i in ids), "the ids travel with the script")

print()
if failures:
    print(f"{len(failures)} check(s) failed:")
    for f in failures:
        print(f"  - {f}")
    raise SystemExit(1)
print("All webhook-lister checks passed.")
