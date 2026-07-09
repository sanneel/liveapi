"""Render premium Ace slot-cards (PNG + flip GIF) from an uploaded game image.

Backs the /admin/slot-cards page: an admin drops a slot-game photo, and we drop
it into the black artwork well of the branded card and render the front PNG plus
the front<->JUGABET-back flip GIF for email — the same assets email_cards/
produces on the CLI, reusing that exact code.

Rendering needs headless Chromium (already installed for the parser via
Playwright), so it is done in a worker process by importing the email_cards
modules. Kept out of the request thread's hot path — each call spends a few
seconds in Chromium.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from ..config import BASE_DIR

EMAIL_CARDS_DIR = BASE_DIR / "journey-cloner" / "email_cards"

# Suit -> deposit tier, mirrored from render_cards.SUITS for the UI dropdown.
# (name, glyph label, deposit, spin value)
SUITS: List[Tuple[str, str, str, str]] = [
    ("hearts", "♥ Hearts", "$10.000", "$100"),
    ("diamonds", "♦ Diamonds", "$20.000", "$200"),
    ("clubs", "♣ Clubs", "$30.000", "$500"),
    ("spades", "♠ Spades", "$50.000", "$800"),
]
SUIT_NAMES = [s[0] for s in SUITS]

MAX_IMAGE_BYTES = 18 * 1024 * 1024
ALLOWED_MIME = {"image/png", "image/jpeg", "image/jpg", "image/webp", "image/gif"}


def _load(mod_name: str):
    """Import a module from email_cards/ by path (it is not a package)."""
    path = EMAIL_CARDS_DIR / f"{mod_name}.py"
    spec = importlib.util.spec_from_file_location(f"_slotcards_{mod_name}", path)
    if spec is None or spec.loader is None:  # pragma: no cover - defensive
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    # make_gif does `import render_cards as R`, so render_cards must be importable
    # from the email_cards dir while we load it.
    sys.path.insert(0, str(EMAIL_CARDS_DIR))
    try:
        spec.loader.exec_module(module)
    finally:
        try:
            sys.path.remove(str(EMAIL_CARDS_DIR))
        except ValueError:
            pass
    return module


def suit_choices() -> List[Dict[str, str]]:
    return [
        {"value": s[0], "label": s[1], "deposit": s[2], "bet": s[3]}
        for s in SUITS
    ]


def _validate(image_bytes: bytes, mime: str, gif_width: int) -> int:
    if not image_bytes:
        raise ValueError("No image supplied.")
    if len(image_bytes) > MAX_IMAGE_BYTES:
        raise ValueError("Image is too large (max 18 MB).")
    if mime not in ALLOWED_MIME:
        raise ValueError("Image must be PNG, JPG, WEBP or GIF.")
    return max(120, min(500, int(gif_width or 300)))


def _fmt_bet(bet: str) -> str:
    """Normalise a typed spin value ('800') to the card's '$800' style. Blank
    stays blank so the tier default is used."""
    bet = (bet or "").strip()
    if bet and not bet.startswith("$"):
        bet = "$" + bet
    return bet


def _render_one(R, G, idx: int, fs: str, data_uri: str, gif_width: int, bet: str) -> Dict[str, object]:
    """Render one tier's front PNG + flip GIF into a temp dir and return bytes.

    render_cards/make_gif call sys.exit() (SystemExit) when Chromium is missing
    or a render fails — convert that to a RuntimeError so the route reports the
    real reason instead of a bare 500 'Internal Server Error'."""
    import tempfile

    bet = _fmt_bet(bet)
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        png_path = tmp / "front.png"
        try:
            R.render_png(R.single_html(idx, fs, data_uri, bet), png_path, scale=2)
            gif_path = G.make_one(idx, fs, gif_width, tmp, data_uri, bet)
        except SystemExit as exc:  # sys.exit() from chrome_bin()/render_png()
            raise RuntimeError(str(exc) or "Chromium render failed") from exc
        _, label, deposit, default_bet = SUITS[idx]
        return {
            "suit": SUIT_NAMES[idx],
            "label": label,
            "deposit": deposit,
            "bet": bet or default_bet,
            "png": png_path.read_bytes(),
            "gif": gif_path.read_bytes(),
            "gif_name": gif_path.name,
        }


def _prep():
    R = _load("render_cards")
    G = _load("make_gif")
    # make_gif imported its own copy of render_cards; keep them in sync so both
    # share the exact same geometry/helpers.
    G.R = R
    return R, G


def _data_uri(image_bytes: bytes, mime: str) -> str:
    import base64
    return f"data:{mime};base64," + base64.b64encode(image_bytes).decode("ascii")


def render_card(
    image_bytes: bytes,
    mime: str,
    suit: str,
    free_spins: str,
    gif_width: int = 300,
    bet: str = "",
) -> Dict[str, object]:
    """Render one card's front PNG and flip GIF with `image_bytes` in the well.

    Returns {'png', 'gif', 'gif_name', ...}. Raises ValueError on bad input so
    the route can turn it into a 400.
    """
    if suit not in SUIT_NAMES:
        raise ValueError(f"Unknown suit: {suit!r}")
    gif_width = _validate(image_bytes, mime, gif_width)
    fs = (free_spins or "50").strip() or "50"
    R, G = _prep()
    return _render_one(R, G, SUIT_NAMES.index(suit), fs, _data_uri(image_bytes, mime), gif_width, (bet or "").strip())


def render_all(
    image_bytes: bytes,
    mime: str,
    free_spins: str,
    bets: Optional[List[str]] = None,
    gif_width: int = 300,
) -> List[Dict[str, object]]:
    """Render all four tiers (hearts/diamonds/clubs/spades) from one image.

    `bets` overrides the spin value per tier (index-aligned with SUITS); blank
    entries fall back to the tier default. Returns one dict per tier."""
    gif_width = _validate(image_bytes, mime, gif_width)
    fs = (free_spins or "50").strip() or "50"
    bets = (bets or []) + [""] * len(SUITS)
    R, G = _prep()
    data_uri = _data_uri(image_bytes, mime)
    return [
        _render_one(R, G, idx, fs, data_uri, gif_width, (bets[idx] or "").strip())
        for idx in range(len(SUITS))
    ]


def render_grid(
    image_bytes: bytes,
    mime: str,
    free_spins: str,
    bets: Optional[List[str]] = None,
    total_width: int = 560,
    cols: int = 2,
) -> Dict[str, object]:
    """Render ONE transparent GIF with all four tiers in a grid (each flipping
    front<->JUGABET back), plus the four transparent front PNGs for individual
    use. `total_width` is the whole grid's pixel width."""
    _validate(image_bytes, mime, 300)
    total_width = max(240, min(1000, int(total_width or 560)))
    cols = 2 if cols not in (1, 2, 4) else cols
    fs = (free_spins or "50").strip() or "50"
    bets = [(b or "").strip() for b in ((bets or []) + [""] * len(SUITS))]
    R, G = _prep()
    data_uri = _data_uri(image_bytes, mime)

    import tempfile

    cell_width = max(120, (total_width - 0) // cols)
    grid_cards = [(idx, data_uri, _fmt_bet(bets[idx])) for idx in range(len(SUITS))]

    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        try:
            gif_path = G.make_grid(grid_cards, fs, cell_width, tmp / "grid.gif", cols=cols)
            cards = []
            for idx in range(len(SUITS)):
                bet = _fmt_bet(bets[idx])
                png_path = tmp / f"front_{idx}.png"
                R.render_png(R.single_html(idx, fs, data_uri, bet), png_path, scale=2)
                # Individual reveal GIF at cell_width so all 4 are identical
                # dimensions: starts on the JUGABET back, flips ONCE to the
                # front and stays (email plays it on open — the closest email
                # gets to "click turns the card around").
                ind_gif_path = G.make_one(idx, fs, cell_width, tmp, data_uri, bet, reveal=True)
                _, label, deposit, default_bet = SUITS[idx]
                cards.append({
                    "suit": SUIT_NAMES[idx],
                    "label": label,
                    "deposit": deposit,
                    "bet": bet or default_bet,
                    "png": png_path.read_bytes(),
                    "gif": ind_gif_path.read_bytes(),
                    "gif_name": ind_gif_path.name,
                })
        except SystemExit as exc:
            raise RuntimeError(str(exc) or "Chromium render failed") from exc
        return {"gif": gif_path.read_bytes(), "gif_name": "slot_cards_gow.gif", "cards": cards}


def build_flip_page(
    game_img_url: str,
    free_spins: str,
    bets: Optional[List[str]] = None,
    links: Optional[List[str]] = None,
    heading: str = "",
) -> str:
    """The public click-to-flip landing page (the real click behaviour email can't do).

    All four cards start face-down on the JUGABET back; clicking (or Enter/Space
    on) a card turns THAT card around, each one independently. The front's Play
    Now button is a real link when a per-suit link is given. Pure HTML/CSS/JS —
    no Chromium in the request path — reusing render_cards' exact card markup so
    the page cards are pixel-for-pixel the GIF cards."""
    from html import escape

    R = _load("render_cards")
    fs = escape((free_spins or "50").strip() or "50")
    bets = [(b or "").strip() for b in ((bets or []) + [""] * len(SUITS))]
    links = [(l or "").strip() for l in ((links or []) + [""] * len(SUITS))]
    img_attr = escape(game_img_url or "", quote=True)

    scenes = []
    for i, (name, glyph, deposit, default_bet) in enumerate(R.SUITS):
        bet = escape(_fmt_bet(bets[i]) or default_bet)
        front = R.card_html(i + 1, glyph, deposit, bet, fs, img_attr)
        # If the stored well image has expired, hide the broken-image icon and
        # leave the styled black well instead.
        front = front.replace('<img class="game" ', '<img class="game" onerror="this.remove()" ')
        link = links[i]
        if link.startswith(("http://", "https://")):
            front = front.replace(
                '<button class="cta" type="button">',
                f'<a class="cta" href="{escape(link, quote=True)}" target="_blank" rel="noopener" '
                'onclick="event.stopPropagation()">',
            ).replace("</button>", "</a>")
        back = R.back_html(glyph)
        scenes.append(
            f'<div class="scene" role="button" tabindex="0" aria-label="Revelar carta {name}">'
            f'<div class="spinner">\n{front}\n{back}\n</div></div>'
        )

    head = escape(heading) if heading else f'OBTÉN <span class="n">{fs}</span> GIROS GRATIS'
    deck = "\n".join(scenes)
    return f"""<!doctype html><html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{fs} Giros Gratis · JugaBet</title>
<style>{R.CSS}{R.BACK_CSS}
  html{{background:#190f3c;}}
  body{{min-height:100vh;padding:5vmin 4vmin;
    background:radial-gradient(120% 90% at 50% 0%,#3b2a86 0%,#2a1a68 45%,#190f3c 100%);}}
  h1{{text-align:center;color:#fff;font-family:"Arial Black","Helvetica Neue",Arial,sans-serif;
    font-weight:900;font-size:clamp(22px,6vw,44px);letter-spacing:.02em;margin:0 0 5vmin;}}
  h1 .n{{color:#b7e528;font-size:1.35em;vertical-align:-.08em;}}
  .grid{{display:grid;grid-template-columns:repeat(2,minmax(140px,300px));gap:5vmin 4vmin;
    justify-content:center;}}
  .scene{{aspect-ratio:2/3;perspective:1800px;cursor:pointer;-webkit-tap-highlight-color:transparent;}}
  .scene:focus-visible{{outline:3px solid #b7e528;outline-offset:6px;border-radius:26px;}}
  .spinner{{position:relative;width:100%;height:100%;transform-style:preserve-3d;
    transition:transform .9s cubic-bezier(.45,.05,.3,1.05);}}
  .scene.flipped .spinner{{transform:rotateY(180deg);}}
  .spinner .card{{position:absolute;inset:0;width:100%;height:100%;aspect-ratio:auto;
    -webkit-backface-visibility:hidden;backface-visibility:hidden;}}
  .spinner .card .inner{{min-height:0;}}
  /* Face-down first: the back sits at 0°, the front waits at 180°. */
  .spinner .card.back{{transform:none;}}
  .spinner .card:not(.back){{transform:rotateY(180deg);}}
  a.cta{{text-decoration:none;text-align:center;}}
  @media(prefers-reduced-motion:reduce){{.spinner{{transition:none;}}}}
</style></head><body>
<h1>{head}</h1>
<div class="grid">
{deck}
</div>
<script>
  document.querySelectorAll('.scene').forEach(function (s) {{
    function flip() {{ s.classList.toggle('flipped'); }}
    s.addEventListener('click', flip);
    s.addEventListener('keydown', function (e) {{
      if (e.key === 'Enter' || e.key === ' ') {{ e.preventDefault(); flip(); }}
    }});
  }});
</script>
</body></html>"""
