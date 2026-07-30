#!/usr/bin/env python3
"""JBCL (JugaBet) tournament comms — the brand half of `tournament_comms_base`.

Captured from `fef8c394-tornm.har`: a JBCL tournament announced on Notification
Center ("JBCL NC Dynamic 2026", template 1935) + Cat-fish pop-up ("JBCL Pop-up
CatFish 2026", template 20678) + SMS + a marketing email, one journey, gated by
two `wait_date` activities on the tournament window.

Every rule — any-link (no Smartico id), sheet-owned tournament window, revoke
period = tournament length, start on the send date at 12:00 Chile, structural
per-language copy — lives in `tournament_comms_base`. This file is only what the
JBCL capture happens to contain.

Usage:
  python tournament_jbcl_campaign.py --date 2026-07-20 \
      --link https://jugabet.cl/page/torneo-x \
      --email-link https://jugabet.cl/launch/slots/iframe/<game> --spec sheet.tsv
"""
from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from casino_journey import DEFAULT_BASE_URL  # noqa: E402
from comms_campaign import DEFAULT_FOLDER_ID  # noqa: E402
import tournament_comms_base as B  # noqa: E402

TEMPLATE_DIR = HERE / "templates" / "tournament"

JBCL = B.Brand(
    code="JBCL",
    title="JBCL (JugaBet)",
    base_url=DEFAULT_BASE_URL,
    folder_id=DEFAULT_FOLDER_ID,
    create_tpl=TEMPLATE_DIR / "tournament_comms_create.json",
    save_tpl=TEMPLATE_DIR / "tournament_comms_save.json",
    nc_node="JBCL NC Dynamic 2026",
    popup_node="JBCL Pop-up CatFish 2026",
    journey_prefix="JBCL | CS&SP",
    sms_prefix="JugaBet | ",
    email_create_tpl=TEMPLATE_DIR / "tournament_email_create.json",
    email_save_tpl=TEMPLATE_DIR / "tournament_email_save.json",
    email_name_prefix="JBCL - Tournament",
    tpl_email_content_id="CSE-0-14726",
    tpl_email_hero="https://{{cdn_hostname}}/c93ad623-44ae-40f6-9aa5-b1aef7fd931a/f4323497-5894-43ae-935c-0be3ef5c5056.png",
    # The JBCL email's CTA opens a slot, so the literal swapped is the game slug.
    tpl_email_cta="pragmatic-jugabet-leyendas-del-olympus-1000",
    email_cta_kind="game",
    tpl_nc_icons=(
        "https://static.contentin.cloud/73b22051-b16d-46e3-90cb-eeb045f59eea/3247d38f-d24e-4fc1-a753-ac9ced71f539.png",
        "https://static.contentin.cloud/c93ad623-44ae-40f6-9aa5-b1aef7fd931a/bc58e148-13fa-4f6c-a946-3b5b6926dfce.png",
    ),
    tpl_popup_bg="https://static.contentin.cloud/c93ad623-44ae-40f6-9aa5-b1aef7fd931a/77311945-dfcd-4f56-a9b9-48e44709ae28.png",
    tpl_reserved="JRN-0-636011",
    # The notification/pop-up nodes label their objectForSend metadata with a
    # shorter spelling of the same journey (no "&SP", no dates) — a second
    # literal, so a second thing that can be left as the capture's.
    tpl_journey_names=(
        "JBCL | CS&SP | Torneo Leyendas Ganadoras 21-30.06",
        "JBCL | CS | Torneo Leyendas Ganadoras",
    ),
    tpl_links=("/page/torneo-leyendas-ganadoras",),
)


def read_spec(path: Path, link: str = ""):
    return B.read_spec(JBCL, path, link)


def prepare(spec, **kw):
    return B.prepare(JBCL, spec, **kw)


def verify(bundle: dict):
    return B.verify(bundle)


def main() -> int:
    return B.run_cli(JBCL)


if __name__ == "__main__":
    raise SystemExit(main())
