#!/usr/bin/env python3
"""Assemble a full JugaBet promo email around the 4 Ace cards.

Two outputs:
  email_jugabet.html          production — card GIFs referenced by URL you host
  email_jugabet_preview.html  self-contained — GIFs embedded as data URIs (renders anywhere)

Usage:
  python build_email.py                     # both files, FREE SPINS = 50
  python build_email.py --free-spins 100    # re-render cards first if you changed values
"""
from __future__ import annotations

import argparse
import base64
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT = HERE / "out"

# suit, deposit (for alt text), gif filename
CARDS = [
    ("hearts",   "10000"),
    ("diamonds", "20000"),
    ("clubs",    "30000"),
    ("spades",   "50000"),
]

# your hosted paths — upload out/*_flip.gif and point these at them
CDN = "https://{{cdn_hostname}}/REPLACE_WITH_YOUR_UPLOAD_PATH"
LOGO_URL = "http://dextra-pm.com/i/038ab59740854999b9a952db2212317c/timg_655b26966d131.png"
PROMO_URL = "https://jugabet.cl/services/promo/offers/promoPage/REPLACE-PROMO-ID"
IG = "https://{{cdn_hostname}}/c93ad623-44ae-40f6-9aa5-b1aef7fd931a/59a51064-7e29-46cd-be70-0c7e6df8d359.png"
FB = "https://{{cdn_hostname}}/c93ad623-44ae-40f6-9aa5-b1aef7fd931a/a4a04198-bdf2-435a-9d74-90830bf3862b.png"
APP = "https://{{cdn_hostname}}/c93ad623-44ae-40f6-9aa5-b1aef7fd931a/4febbd21-7381-4756-82f9-0e9a8a11e20d.png"

SUBJECT = "🂡 Elige tu depósito y llévate 50 giros gratis"
PREHEADER = "Cuatro cartas, cuatro depósitos. Elige la tuya y juega con 50 giros gratis."
FS = "50"


def gif_src(suit: str, embed: bool) -> str:
    if embed:
        p = OUT / f"card_{suit}_{dict(CARDS)[suit]}_flip.gif"
        return "data:image/gif;base64," + base64.b64encode(p.read_bytes()).decode("ascii")
    return f"{CDN}/card_{suit}_flip.gif"


def logo_src(embed: bool) -> str:
    logo = HERE.parent.parent / "logos" / "logo_jugabet.png"
    if embed and logo.exists():
        return "data:image/png;base64," + base64.b64encode(logo.read_bytes()).decode("ascii")
    return LOGO_URL


def card_cell(suit: str, deposit: str, embed: bool) -> str:
    return f"""              <td align="center" valign="top" width="50%" style="padding:8px;">
                <a href="{PROMO_URL}" target="_blank" style="text-decoration:none;">
                  <img src="{gif_src(suit, embed)}" width="250" alt="Depósito ${deposit} — {FS} giros gratis"
                       style="display:block;width:250px;max-width:100%;height:auto;border:0;outline:none;margin:0 auto;">
                </a>
              </td>"""


def build(embed: bool) -> str:
    rows = ""
    for i in range(0, len(CARDS), 2):
        a = card_cell(*CARDS[i], embed=embed)
        b = card_cell(*CARDS[i + 1], embed=embed)
        rows += f"          <tr>\n{a}\n{b}\n          </tr>\n"
    return f"""<!doctype html>
<html xmlns="http://www.w3.org/1999/xhtml">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>JugaBet — {FS} giros gratis</title>
</head>
<body style="margin:0;padding:0;background:#08070d;">
  <div style="display:none;max-height:0;overflow:hidden;opacity:0;">{PREHEADER}</div>
  <table role="presentation" width="100%" border="0" cellspacing="0" cellpadding="0" bgcolor="#08070d" style="background:#08070d;">
    <tr>
      <td align="center" style="padding:0;">
        <table role="presentation" width="600" border="0" cellspacing="0" cellpadding="0"
               style="width:600px;max-width:600px;margin:0 auto;background:
               radial-gradient(120% 80% at 50% 0%,#1b1430 0%,#0d0a1a 55%,#08070d 100%);background-color:#0b0a14;">

          <!-- logo -->
          <tr>
            <td align="center" style="padding:22px 20px 6px;">
              <a href="https://jugabet.cl/es/" target="_blank"><img src="{logo_src(embed)}" width="150" alt="JugaBet"
                 style="display:inline-block;width:150px;height:auto;border:0;"></a>
            </td>
          </tr>

          <!-- heading -->
          <tr>
            <td align="center" style="padding:14px 24px 2px;">
              <div style="font-family:Verdana,Geneva,sans-serif;text-transform:uppercase;font-weight:bold;line-height:1.15;">
                <span style="font-size:26px;color:#FAF9F8;">Obtén </span>
                <span style="font-size:46px;color:#B6DE13;">{FS}</span>
                <span style="font-size:26px;color:#FAF9F8;"> giros gratis</span>
              </div>
            </td>
          </tr>
          <tr>
            <td align="center" style="padding:6px 24px 4px;">
              <div style="font-family:Verdana,Geneva,sans-serif;font-size:16px;letter-spacing:.06em;color:#C9B98F;text-transform:uppercase;">
                Elige tu depósito
              </div>
            </td>
          </tr>

          <!-- 2x2 Ace cards -->
          <tr>
            <td style="padding:10px 12px 6px;">
              <table role="presentation" width="100%" border="0" cellspacing="0" cellpadding="0">
{rows}          </table>
            </td>
          </tr>

          <!-- CTA -->
          <tr>
            <td align="center" style="padding:10px 24px 30px;">
              <table role="presentation" border="0" cellspacing="0" cellpadding="0" align="center">
                <tr>
                  <td align="center" bgcolor="#2bb257"
                      style="border-radius:999px;background:linear-gradient(180deg,#47e07d,#1c7d3a);border:2px solid #c9962f;">
                    <a href="{PROMO_URL}" target="_blank"
                       style="display:inline-block;padding:14px 46px;font-family:Verdana,Geneva,sans-serif;font-weight:bold;
                       font-size:18px;letter-spacing:.08em;text-transform:uppercase;color:#ffffff;text-decoration:none;">
                       Juega ya</a>
                  </td>
                </tr>
              </table>
            </td>
          </tr>

          <!-- footer -->
          <tr>
            <td style="padding:0 15px 15px;">
              <table role="presentation" width="100%" border="0" cellspacing="0" cellpadding="0"
                     style="border-radius:12px;background:rgba(0,0,0,.5);">
                <tr>
                  <td align="center" style="padding:18px 0 6px;">
                    <table role="presentation" align="center" border="0" cellspacing="0" cellpadding="0">
                      <tr>
                        <td align="center"><a href="https://www.instagram.com/jugabetcl" target="_blank"><img src="{IG}" width="36" alt="Instagram" style="display:block;border:0;height:auto;"></a></td>
                        <td width="26" style="font-size:0;line-height:0;">&nbsp;</td>
                        <td align="center"><a href="https://www.facebook.com/Jugabet" target="_blank"><img src="{FB}" width="36" alt="Facebook" style="display:block;border:0;height:auto;"></a></td>
                        <td width="26" style="font-size:0;line-height:0;">&nbsp;</td>
                        <td align="center"><a href="https://jugabet.onelink.me/eW3L/0p6i6pdr" target="_blank"><img src="{APP}" height="36" alt="App" style="display:block;border:0;width:auto;"></a></td>
                      </tr>
                    </table>
                  </td>
                </tr>
                <tr>
                  <td align="center" style="padding:6px 24px 18px;">
                    <p style="margin:0 0 8px;font-family:Verdana,Geneva,sans-serif;color:#B7C8E5;font-size:13px;line-height:1.4;">
                      ¿Tienes algún problema?<br>Contacta a soporte
                      <a href="mailto:support@jugabet.cl" style="color:#B9D532;">support@jugabet.cl</a>
                    </p>
                    <p style="margin:0;font-family:Verdana,Geneva,sans-serif;color:#8894ab;font-size:10px;line-height:1.5;">
                      ¿No quieres más correos? <a href="{{{{ unsubscribe_url }}}}" style="color:#B9D532;">Darse de baja</a><br>
                      Todos los derechos reservados.
                    </p>
                  </td>
                </tr>
              </table>
            </td>
          </tr>

        </table>
      </td>
    </tr>
  </table>
</body>
</html>
"""


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--free-spins", default="50")
    a = ap.parse_args()
    global FS
    FS = a.free_spins
    prod = HERE / "email_jugabet.html"
    prev = HERE / "email_jugabet_preview.html"
    prod.write_text(build(embed=False), encoding="utf-8")
    prev.write_text(build(embed=True), encoding="utf-8")
    print(f"wrote {prod.name} (hosted-URL placeholders) and {prev.name} (self-contained, {prev.stat().st_size//1024} KB)")
    print(f"Subject:  {SUBJECT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
