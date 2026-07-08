#!/usr/bin/env python3
"""Premium casino "Ace" free-spins promo cards — 4-suit deck.

Single source of truth for both the HTML template (casino_card.html) and the
per-card transparent PNGs used in email. Deposits are fixed per suit; the
free-spins count is a variable you pass in (--free-spins). Drop a 360x330 game
PNG into the black artwork well of each card in your email tool.

  ♥ hearts   $10.000 CLP
  ♦ diamonds $20.000 CLP
  ♣ clubs    $30.000 CLP
  ♠ spades   $50.000 CLP

Usage:
  python render_cards.py --html                 # (re)write casino_card.html (keeps {{FREE_SPINS}})
  python render_cards.py --free-spins 50         # render 4 transparent PNGs into out/
  python render_cards.py --free-spins 100 --scale 3
"""
from __future__ import annotations

import argparse
import base64
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
LOGO_PATH = HERE.parent.parent / "logos" / "logo_jugabet.png"


def _logo_uri() -> str:
    try:
        return "data:image/png;base64," + base64.b64encode(LOGO_PATH.read_bytes()).decode("ascii")
    except OSError:
        return ""


LOGO_URI = _logo_uri()

# fixed per suit (Chilean format $10.000). deposit tier -> paired spin value.
SUITS = [
    ("hearts",   "&#9829;", "$10.000", "$100"),
    ("diamonds", "&#9830;", "$20.000", "$200"),
    ("clubs",    "&#9827;", "$30.000", "$500"),
    ("spades",   "&#9824;", "$50.000", "$800"),
]

CSS = r"""
  :root{--gold-hi:#fdf3c0;--gold:#e9c565;--gold-mid:#c9962f;--gold-lo:#7c561a;
    --green-hi:#47e07d;--green:#2bb257;--green-lo:#14682f;
    --white-hi:#fff;--white:#e6ebf3;--white-lo:#aab2be;}
  *{box-sizing:border-box;margin:0;padding:0;}
  .card{position:relative;width:360px;aspect-ratio:2/3;border-radius:26px;padding:9px;
    container-type:inline-size;font-family:"Georgia","Times New Roman",serif;
    background:linear-gradient(135deg,#7c561a 0%,#f7e79f 18%,#c9962f 34%,#8a5f16 50%,#f3d98a 66%,#b98529 82%,#6d4a15 100%);
    box-shadow:0 0 0 1px rgba(0,0,0,.6),0 26px 60px -20px rgba(0,0,0,.8),0 0 54px -8px rgba(201,150,47,.4);}
  .inner{position:relative;height:100%;border-radius:17px;overflow:hidden;display:flex;flex-direction:column;
    padding:5.5cqw 6cqw 5cqw;background:radial-gradient(130% 80% at 50% 42%,#141416 0%,#0a0a0b 55%,#050506 100%);}
  .inner::before{content:"";position:absolute;inset:0;opacity:.5;pointer-events:none;
    background-image:repeating-linear-gradient(45deg,rgba(201,150,47,.05) 0 1px,transparent 1px 22px),
      repeating-linear-gradient(-45deg,rgba(201,150,47,.05) 0 1px,transparent 1px 22px);}
  .rule{position:absolute;inset:3cqw;border:1px solid rgba(233,197,101,.55);border-radius:12px;
    box-shadow:inset 0 0 18px rgba(201,150,47,.14),0 0 8px rgba(201,150,47,.1);pointer-events:none;}
  .gold-text{background:linear-gradient(180deg,var(--gold-hi) 0%,var(--gold) 44%,var(--gold-mid) 60%,#f2d98a 100%);
    -webkit-background-clip:text;background-clip:text;color:transparent;
    filter:drop-shadow(0 1px 0 rgba(0,0,0,.55)) drop-shadow(0 2px 4px rgba(0,0,0,.5));}
  .white-text{background:linear-gradient(180deg,var(--white-hi) 0%,var(--white) 48%,var(--white-lo) 60%,#eef2f7 100%);
    -webkit-background-clip:text;background-clip:text;color:transparent;
    filter:drop-shadow(0 1px 0 rgba(0,0,0,.6)) drop-shadow(0 3px 5px rgba(0,0,0,.5));}
  .corner{position:absolute;z-index:3;display:flex;flex-direction:column;align-items:center;line-height:.82;}
  .corner.tl{top:5cqw;left:6cqw;} .corner.br{bottom:4.5cqw;right:6cqw;transform:rotate(180deg);}
  .corner .a{font-size:11.5cqw;font-weight:700;letter-spacing:-.02em;} .corner .suit{font-size:6.4cqw;margin-top:.3cqw;}
  .well{position:relative;flex:1 1 auto;min-height:34cqw;margin:10cqw 1.5cqw 0;border-radius:10px;
    background:radial-gradient(90% 75% at 50% 45%,#000 42%,#040404 80%,#0a0a0a 100%);
    box-shadow:inset 0 0 40px rgba(0,0,0,.9),inset 0 0 0 1px rgba(233,197,101,.16);}
  .well::after{content:"";position:absolute;inset:0;border-radius:10px;
    background:radial-gradient(120% 90% at 50% 40%,transparent 58%,rgba(0,0,0,.8) 100%);}
  .divider{display:flex;align-items:center;gap:3cqw;margin:3.4cqw 1cqw 0;}
  .divider .line{flex:1;height:2px;box-shadow:0 0 6px rgba(201,150,47,.35);
    background:linear-gradient(90deg,transparent,rgba(233,197,101,.15),var(--gold-mid),rgba(233,197,101,.15),transparent);}
  .divider .gem{font-size:3.2cqw;filter:drop-shadow(0 0 4px rgba(233,197,101,.5));}
  .hero{display:flex;align-items:center;justify-content:center;gap:2.4cqw;margin-top:2.6cqw;}
  .reel{width:16cqw;height:auto;flex:0 0 auto;filter:drop-shadow(0 3px 6px rgba(0,0,0,.55));}
  .hero .fs{font-family:"Arial Black","Helvetica Neue",Arial,sans-serif;font-weight:900;font-size:13cqw;letter-spacing:-.01em;}
  .hero .fsl{font-family:"Arial Black","Helvetica Neue",Arial,sans-serif;font-weight:800;font-size:7.4cqw;letter-spacing:.02em;margin-left:2.2cqw;}
  .stats{display:grid;grid-template-columns:1.14fr 1px 0.86fr;align-items:center;column-gap:2cqw;margin-top:3.4cqw;}
  .stats .cell{text-align:center;min-width:0;}
  .stats .k{font-size:3.4cqw;font-weight:700;letter-spacing:.18em;text-transform:uppercase;}
  .stats .v{font-family:"Arial Black","Helvetica Neue",Arial,sans-serif;font-weight:800;font-size:8.4cqw;
    line-height:1.05;margin-top:1.2cqw;white-space:nowrap;font-variant-numeric:tabular-nums;}
  .stats .cur{font-size:.46em;letter-spacing:.01em;margin-left:.12em;}
  .stats .vsep{width:1px;height:12cqw;align-self:center;box-shadow:0 0 6px rgba(201,150,47,.4);
    background:linear-gradient(180deg,transparent,var(--gold-mid),transparent);}
  .cta{position:relative;margin:3.6cqw auto 0;display:block;width:66%;border:none;cursor:pointer;border-radius:999px;padding:3cqw 3cqw;
    background:linear-gradient(180deg,var(--green-hi) 0%,var(--green) 46%,var(--green-lo) 100%);
    box-shadow:inset 0 2px 1px rgba(255,255,255,.5),inset 0 -3px 6px rgba(0,0,0,.45),0 0 0 2px var(--gold-mid),
      0 0 0 3px rgba(0,0,0,.4),0 8px 22px -8px rgba(20,104,47,.8),0 0 22px -4px rgba(71,224,125,.5);overflow:hidden;}
  .cta::before{content:"";position:absolute;left:0;right:0;top:0;height:50%;border-radius:999px 999px 40% 40%;
    background:linear-gradient(180deg,rgba(255,255,255,.5),rgba(255,255,255,0));}
  .cta .txt{position:relative;font-family:"Arial Black","Helvetica Neue",Arial,sans-serif;font-weight:900;font-size:5.8cqw;
    letter-spacing:.08em;white-space:nowrap;text-transform:uppercase;display:flex;align-items:center;justify-content:center;gap:2.2cqw;}
  .cta .spark{font-family:Georgia,serif;color:var(--gold-hi);filter:drop-shadow(0 1px 2px rgba(0,0,0,.5));}
"""

# JUGABET card back (shared by the deck and the GIF renderer)
BACK_CSS = r"""
  .backface{padding:10cqw 7cqw;align-items:center;justify-content:space-between;}
  .backface::before{opacity:.9;background-image:
    repeating-linear-gradient(45deg,rgba(233,197,101,.11) 0 1.5px,transparent 1.5px 15px),
    repeating-linear-gradient(-45deg,rgba(233,197,101,.11) 0 1.5px,transparent 1.5px 15px);}
  .bpips{display:flex;gap:5cqw;font-size:5cqw;justify-content:center;z-index:1;}
  .bcore{position:relative;z-index:1;flex:1;width:100%;display:grid;place-items:center;}
  .bglow{position:absolute;width:90%;height:42%;border-radius:50%;filter:blur(26px);
    background:radial-gradient(closest-side,rgba(180,216,0,.22),transparent 72%);}
  .blogo{position:relative;width:76%;height:auto;filter:drop-shadow(0 4px 12px rgba(0,0,0,.6));}
"""


def card_html(idx: int, suit_glyph: str, deposit: str, bet: str, free_spins: str) -> str:
    gid = f"g{idx}"
    return f"""  <div class="card">
    <div class="inner">
      <span class="rule"></span>
      <div class="corner tl"><span class="a gold-text">A</span><span class="suit gold-text">{suit_glyph}</span></div>
      <div class="corner br"><span class="a gold-text">A</span><span class="suit gold-text">{suit_glyph}</span></div>
      <div class="well"></div>
      <div class="divider"><span class="line"></span><span class="gem gold-text">&#9670;</span><span class="line"></span></div>
      <div class="hero">
        <svg class="reel" viewBox="0 0 72 62" aria-hidden="true">
          <defs>
            <linearGradient id="{gid}" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#fdf3c0"/><stop offset=".45" stop-color="#e9c565"/><stop offset="1" stop-color="#a9781f"/></linearGradient>
            <linearGradient id="{gid}s" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#ff6a5a"/><stop offset="1" stop-color="#c31f1f"/></linearGradient>
          </defs>
          <rect x="12" y="50" width="34" height="6" rx="2.5" fill="url(#{gid})" stroke="#7c561a" stroke-width="1"/>
          <rect x="22" y="8" width="14" height="9" rx="2.5" fill="url(#{gid})" stroke="#7c561a" stroke-width="1.5"/>
          <rect x="4" y="15" width="50" height="36" rx="9" fill="url(#{gid})" stroke="#7c561a" stroke-width="2"/>
          <rect x="9" y="21" width="40" height="24" rx="4" fill="#0b0b0d" stroke="#5a3f12" stroke-width="1"/>
          <line x1="22.3" y1="22" x2="22.3" y2="44" stroke="#33251a" stroke-width="1"/>
          <line x1="35.6" y1="22" x2="35.6" y2="44" stroke="#33251a" stroke-width="1"/>
          <g fill="url(#{gid}s)" font-family="Arial Black, Arial" font-weight="900" font-size="17" text-anchor="middle">
            <text x="15.6" y="39.5">7</text><text x="29" y="39.5">7</text><text x="42.4" y="39.5">7</text>
          </g>
          <rect x="56.5" y="21" width="3" height="17" rx="1.5" fill="url(#{gid})"/>
          <circle cx="58" cy="17" r="4.4" fill="url(#{gid}s)" stroke="#7c561a" stroke-width="1.2"/>
        </svg>
        <span class="fs gold-text">{free_spins}</span><span class="fsl white-text">Free Spins</span>
      </div>
      <div class="stats">
        <div class="cell"><div class="k gold-text">Deposit</div><div class="v gold-text">{deposit}<span class="cur"> CLP</span></div></div>
        <span class="vsep"></span>
        <div class="cell"><div class="k gold-text">Spin Value</div><div class="v gold-text">{bet}<span class="cur"> CLP</span></div></div>
      </div>
      <button class="cta" type="button"><span class="txt"><span class="spark">&#9670;</span><span class="white-text">Play Now</span><span class="spark">&#9670;</span></span></button>
    </div>
  </div>"""


def back_html(suit_glyph: str) -> str:
    return f"""  <div class="card back">
    <div class="inner backface">
      <span class="rule"></span>
      <div class="bpips"><span class="gold-text">&#9824;</span><span class="gold-text">&#9829;</span><span class="gold-text">&#9830;</span><span class="gold-text">&#9827;</span></div>
      <div class="bcore"><div class="bglow"></div><img class="blogo" src="{LOGO_URI}" alt="JugaBet"/></div>
      <div class="bpips"><span class="gold-text">&#9827;</span><span class="gold-text">&#9830;</span><span class="gold-text">&#9829;</span><span class="gold-text">&#9824;</span></div>
    </div>
  </div>"""


def deck_html(free_spins: str) -> str:
    scenes = []
    for i, (_, g, d, b) in enumerate(SUITS):
        front = card_html(i + 1, g, d, b, free_spins)
        back = back_html(g)
        delay = -2.75 * i  # stagger so the four cards spin out of phase
        scenes.append(f'<div class="scene"><div class="spinner" style="animation-delay:{delay}s">\n{front}\n{back}\n</div></div>')
    deck = "\n".join(scenes)
    return f"""<style>{CSS}
  body{{min-height:100vh;padding:6vmin 5vmin;background:radial-gradient(120% 90% at 50% 0%,#16161a 0%,#0b0b0d 55%,#050506 100%);}}
  .deck-scroll{{overflow-x:auto;padding:26px 0 18px;}}
  .deck{{display:flex;gap:6vmin;width:max-content;margin:0 auto;perspective:2000px;}}
  .scene{{width:360px;aspect-ratio:2/3;flex:0 0 auto;}}
  .spinner{{position:relative;width:100%;height:100%;transform-style:preserve-3d;animation:spin 12s cubic-bezier(.65,.03,.35,.97) infinite;}}
  .spinner .card{{position:absolute;inset:0;width:100%;height:100%;aspect-ratio:auto;
    -webkit-backface-visibility:hidden;backface-visibility:hidden;}}
  .spinner .card .inner{{min-height:0;}}
  .spinner .card.back{{transform:rotateY(180deg);}}
  @keyframes spin{{0%{{transform:rotateY(0deg)}}45%{{transform:rotateY(180deg)}}55%{{transform:rotateY(180deg)}}100%{{transform:rotateY(360deg)}}}}
  /* ── JUGABET card back ── */{BACK_CSS}
  @media(prefers-reduced-motion:no-preference){{.card{{animation:glow 6s ease-in-out infinite;}}
    @keyframes glow{{0%,100%{{box-shadow:0 0 0 1px rgba(0,0,0,.6),0 26px 60px -20px rgba(0,0,0,.8),0 0 40px -10px rgba(201,150,47,.32);}}
      50%{{box-shadow:0 0 0 1px rgba(0,0,0,.6),0 26px 60px -20px rgba(0,0,0,.8),0 0 66px -4px rgba(246,226,122,.55);}}}}}}
  @media(prefers-reduced-motion:reduce){{.spinner{{animation:none;}}}}
</style>
<div class="deck-scroll"><div class="deck">
{deck}
</div></div>
"""


def single_html(idx: int, free_spins: str) -> str:
    _, glyph, deposit, bet = SUITS[idx]
    return f"""<!doctype html><html><head><meta charset="utf-8"><style>{CSS}
  body{{background:transparent;display:grid;place-items:center;min-height:100vh;padding:0;}}
  .card{{width:360px;height:540px;aspect-ratio:auto;}}
  .inner{{min-height:0;}}
</style></head><body>
{card_html(idx + 1, glyph, deposit, bet, free_spins)}
</body></html>"""


def single_back_html(idx: int) -> str:
    _, glyph, _deposit, _bet = SUITS[idx]
    return f"""<!doctype html><html><head><meta charset="utf-8"><style>{CSS}{BACK_CSS}
  body{{background:transparent;display:grid;place-items:center;min-height:100vh;padding:0;}}
  .card{{width:360px;height:540px;aspect-ratio:auto;}}
  .inner{{min-height:0;}}
</style></head><body>
{back_html(glyph)}
</body></html>"""


def chrome_bin() -> str:
    for p in Path("/opt/pw-browsers").glob("chromium-*/chrome-linux/chrome"):
        return str(p)
    for name in ("chromium", "chromium-browser", "google-chrome"):
        if shutil.which(name):
            return name
    sys.exit("No Chromium binary found (set PLAYWRIGHT_BROWSERS_PATH or install chromium).")


def render_png(html: str, out: Path, scale: int) -> None:
    # card 360x540 centered, + room for the outer glow -> 460 x 648 viewport
    W, H = 460, 648
    with tempfile.NamedTemporaryFile("w", suffix=".html", delete=False, encoding="utf-8") as f:
        f.write(html)
        tmp = f.name
    try:
        cmd = [chrome_bin(), "--headless=new", "--no-sandbox", "--disable-gpu",
               "--hide-scrollbars", "--force-color-profile=srgb",
               f"--force-device-scale-factor={scale}", "--default-background-color=00000000",
               f"--window-size={W},{H}", f"--screenshot={out}", f"file://{tmp}"]
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=90)
        if not out.exists() or out.stat().st_size == 0:
            sys.exit(f"render failed for {out.name}:\n{r.stderr[-800:]}")
    finally:
        os.unlink(tmp)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--free-spins", default="{{FREE_SPINS}}", help="value baked into the PNGs (e.g. 50). Default keeps the template token.")
    ap.add_argument("--scale", type=int, default=2, help="device pixel scale for crisp PNGs (default 2)")
    ap.add_argument("--html", action="store_true", help="only (re)write casino_card.html (keeps {{FREE_SPINS}} unless --free-spins given)")
    ap.add_argument("--out", default=str(HERE / "out"), help="PNG output dir")
    args = ap.parse_args()

    # always keep the repo template with the {{FREE_SPINS}} variable unless overridden
    tpl_fs = args.free_spins if args.free_spins != "{{FREE_SPINS}}" else "{{FREE_SPINS}}"
    (HERE / "casino_card.html").write_text(deck_html("{{FREE_SPINS}}"), encoding="utf-8")
    print(f"wrote {HERE/'casino_card.html'} (one-row deck template)")
    if args.html:
        return 0

    out = Path(args.out); out.mkdir(parents=True, exist_ok=True)
    fs = args.free_spins
    for i, (name, _, deposit, _bet) in enumerate(SUITS):
        dep = deposit.replace("$", "").replace(".", "")
        png = out / f"card_{name}_{dep}_fs{fs if fs.isdigit() else 'var'}.png"
        render_png(single_html(i, fs), png, args.scale)
        print(f"  rendered {png.name}  ({png.stat().st_size} bytes)")
    print(f"\nDone — {len(SUITS)} PNGs in {out}. Free spins = {fs!r}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
