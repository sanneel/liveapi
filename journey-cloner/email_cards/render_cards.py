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
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent

# fixed deposits per suit (Chilean format $10.000)
SUITS = [
    ("hearts",   "&#9829;", "$10.000"),
    ("diamonds", "&#9830;", "$20.000"),
    ("clubs",    "&#9827;", "$30.000"),
    ("spades",   "&#9824;", "$50.000"),
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
  .hero{display:flex;align-items:center;justify-content:center;gap:2.6cqw;margin-top:3cqw;}
  .reel{width:12.5cqw;height:12.5cqw;flex:0 0 auto;filter:drop-shadow(0 3px 6px rgba(0,0,0,.6));}
  .hero .fs{font-family:"Arial Black","Helvetica Neue",Arial,sans-serif;font-weight:900;font-size:13cqw;letter-spacing:-.01em;}
  .hero .fsl{font-family:"Arial Black","Helvetica Neue",Arial,sans-serif;font-weight:800;font-size:7.4cqw;letter-spacing:.02em;margin-left:2.2cqw;}
  .deposit{text-align:center;margin-top:3cqw;}
  .deposit .k{font-size:4.2cqw;font-weight:700;letter-spacing:.3em;text-transform:uppercase;}
  .deposit .v{font-family:"Arial Black","Helvetica Neue",Arial,sans-serif;font-weight:800;font-size:12.5cqw;
    line-height:1.05;margin-top:.8cqw;white-space:nowrap;font-variant-numeric:tabular-nums;}
  .deposit .cur{font-size:.62em;letter-spacing:.02em;}
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


def card_html(idx: int, suit_glyph: str, deposit: str, free_spins: str) -> str:
    gid = f"g{idx}"
    return f"""  <div class="card">
    <div class="inner">
      <span class="rule"></span>
      <div class="corner tl"><span class="a gold-text">A</span><span class="suit gold-text">{suit_glyph}</span></div>
      <div class="corner br"><span class="a gold-text">A</span><span class="suit gold-text">{suit_glyph}</span></div>
      <div class="well"></div>
      <div class="divider"><span class="line"></span><span class="gem gold-text">&#9670;</span><span class="line"></span></div>
      <div class="hero">
        <svg class="reel" viewBox="0 0 64 64" aria-hidden="true">
          <defs><linearGradient id="{gid}" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#fdf3c0"/><stop offset=".5" stop-color="#e9c565"/><stop offset="1" stop-color="#a9781f"/></linearGradient></defs>
          <rect x="8" y="16" width="40" height="34" rx="7" fill="url(#{gid})" stroke="#7c561a" stroke-width="2"/>
          <rect x="13" y="21" width="30" height="24" rx="4" fill="#0b0b0d"/>
          <g fill="url(#{gid})" font-family="Arial Black, Arial" font-weight="900" font-size="15" text-anchor="middle"><text x="21" y="38">7</text><text x="35" y="38">7</text></g>
          <circle cx="52" cy="24" r="4" fill="url(#{gid})" stroke="#7c561a" stroke-width="1.5"/><rect x="50.5" y="24" width="3" height="16" fill="url(#{gid})"/>
        </svg>
        <span class="fs gold-text">{free_spins}</span><span class="fsl white-text">Free Spins</span>
      </div>
      <div class="deposit">
        <div class="k gold-text">Deposit</div>
        <div class="v gold-text">{deposit}<span class="cur"> CLP</span></div>
      </div>
      <button class="cta" type="button"><span class="txt"><span class="spark">&#9670;</span><span class="white-text">Play Now</span><span class="spark">&#9670;</span></span></button>
    </div>
  </div>"""


def deck_html(free_spins: str) -> str:
    cards = "\n".join(card_html(i + 1, g, d, free_spins) for i, (_, g, d) in enumerate(SUITS))
    return f"""<style>{CSS}
  body{{min-height:100vh;padding:5vmin;background:radial-gradient(120% 90% at 50% 0%,#16161a 0%,#0b0b0d 55%,#050506 100%);}}
  .deck-scroll{{overflow-x:auto;padding-bottom:10px;}}
  .deck{{display:flex;gap:4vmin;width:max-content;margin:0 auto;}}
  @media(prefers-reduced-motion:no-preference){{.card{{animation:glow 6s ease-in-out infinite;}}
    @keyframes glow{{0%,100%{{box-shadow:0 0 0 1px rgba(0,0,0,.6),0 26px 60px -20px rgba(0,0,0,.8),0 0 40px -10px rgba(201,150,47,.32);}}
      50%{{box-shadow:0 0 0 1px rgba(0,0,0,.6),0 26px 60px -20px rgba(0,0,0,.8),0 0 66px -4px rgba(246,226,122,.55);}}}}}}
</style>
<div class="deck-scroll"><div class="deck">
{cards}
</div></div>
"""


def single_html(idx: int, free_spins: str) -> str:
    _, glyph, deposit = SUITS[idx]
    return f"""<!doctype html><html><head><meta charset="utf-8"><style>{CSS}
  body{{background:transparent;display:grid;place-items:center;min-height:100vh;padding:0;}}
  .card{{width:360px;height:540px;aspect-ratio:auto;}}
  .inner{{min-height:0;}}
</style></head><body>
{card_html(idx + 1, glyph, deposit, free_spins)}
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
    for i, (name, _, deposit) in enumerate(SUITS):
        dep = deposit.replace("$", "").replace(".", "")
        png = out / f"card_{name}_{dep}_fs{fs if fs.isdigit() else 'var'}.png"
        render_png(single_html(i, fs), png, args.scale)
        print(f"  rendered {png.name}  ({png.stat().st_size} bytes)")
    print(f"\nDone — {len(SUITS)} PNGs in {out}. Free spins = {fs!r}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
