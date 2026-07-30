#!/usr/bin/env python3
"""PMCL (Fortunazo) tournament comms — the brand half of `tournament_comms_base`.

The PMCL tournament promo, back as its own generator. A JBCL capture had briefly
replaced this one, which left Fortunazo operators pointing a JugaBet-branded
journey at the wrong backoffice; the two brands are separate entries again.

Captured from the FTCL tournament comms draft: Notification Center ("PMCL
Notification Center", contract 1) + Cat-fish pop-up ("PMCL Pop-up CatFish",
contract 5) + SMS + a marketing email, one journey, gated by two `wait_date`
activities on the tournament window.

What is *not* as it was: the capture wired every channel to the Smartico
deeplink ``#_smartico_dp=dp:gf_tournaments&id=5431``. That is removed — the
operator's link is used as-is, path-only on the notification and pop-up and
behind ``https://{{BrandDomain}}`` on the SMS, and the email opens the same
promo. See `tournament_comms_base` for the rest of the rules.

Usage:
  python tournament_pmcl_campaign.py --date 2026-06-29 \
      --link https://fortunazo.cl/services/promo --spec sheet.tsv
"""
from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import tournament_comms_base as B  # noqa: E402

TEMPLATE_DIR = HERE / "templates" / "tournament"

# PMCL (Fortunazo) backoffice — the same host the NC-For-Discount PMCL generator
# uses (see nc_discount_pmcl_campaign.py), not JugaBet's.
PMCL_BASE_URL = "https://pmi.rea-backoffice.gr8.tech/api/ubo/api/v0/crm/journey-builder/v0"
# The PMCL comms media-library folder. Hardcoded: it is a property of the brand,
# never of the run, and an operator pasting JugaBet's folder here uploaded a
# tournament's artwork into the wrong brand's library.
PMCL_FOLDER_ID = "67e37e66-3532-47d7-b574-195ede915ff4"

PMCL = B.Brand(
    code="PMCL",
    title="PMCL (Fortunazo)",
    base_url=PMCL_BASE_URL,
    folder_id=PMCL_FOLDER_ID,
    # The PMCL capture is one body: the same payload is POSTed to create the
    # draft and PUT back to save it. The save is what finalises the canvas —
    # the version of this generator that only POSTed left nodes unconnected.
    create_tpl=HERE / "templates" / "casino" / "tournament_pmcl_comms.json",
    save_tpl=HERE / "templates" / "casino" / "tournament_pmcl_comms.json",
    nc_node="PMCL Notification Center",
    popup_node="PMCL Pop-up CatFish",
    journey_prefix="FTCL | CS",
    sms_prefix="Fortunazo | ",
    email_create_tpl=TEMPLATE_DIR / "pmcl_email_create.json",
    email_save_tpl=TEMPLATE_DIR / "pmcl_email_save.json",
    email_name_prefix="FTCL Tournament",
    tpl_email_content_id="CSE-0-15017",
    tpl_email_hero="https://{{cdn_hostname}}/73b22051-b16d-46e3-90cb-eeb045f59eea/9278b1e0-8f37-42b2-b988-95cf08112a7c.png",
    # The PMCL email's CTA was the Smartico deeplink; it now opens the same promo
    # every other channel does.
    tpl_email_cta="https://{{BrandDomain}}/#_smartico_dp=dp:gf_tournaments&id=5431",
    email_cta_kind="link",
    tpl_nc_icons=(
        "https://static.contentin.cloud/73b22051-b16d-46e3-90cb-eeb045f59eea/4f5a57d0-5f55-43eb-bc2d-f2034f4b52de.png",
    ),
    tpl_popup_bg="https://static.contentin.cloud/73b22051-b16d-46e3-90cb-eeb045f59eea/2f0324a5-6a95-43f8-8805-895aa7876f6f.png",
    tpl_reserved="JRN-0-620007",
    tpl_journey_names=("FTCL | CS | Torneo Universo Camino a la Gran Final 29.06-19.07",),
)


def read_spec(path: Path, link: str = ""):
    return B.read_spec(PMCL, path, link)


def prepare(spec, **kw):
    return B.prepare(PMCL, spec, **kw)


def verify(bundle: dict):
    return B.verify(bundle)


def main() -> int:
    return B.run_cli(PMCL)


if __name__ == "__main__":
    raise SystemExit(main())
