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
from typing import Dict, List, Tuple

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


def render_card(
    image_bytes: bytes,
    mime: str,
    suit: str,
    free_spins: str,
    gif_width: int = 300,
) -> Dict[str, bytes]:
    """Render one card's front PNG and flip GIF with `image_bytes` in the well.

    Returns {'png': bytes, 'gif': bytes, 'gif_name': str}. Raises ValueError on
    bad input so the route can turn it into a 400.
    """
    if suit not in SUIT_NAMES:
        raise ValueError(f"Unknown suit: {suit!r}")
    if not image_bytes:
        raise ValueError("No image supplied.")
    if len(image_bytes) > MAX_IMAGE_BYTES:
        raise ValueError("Image is too large (max 18 MB).")
    if mime not in ALLOWED_MIME:
        raise ValueError("Image must be PNG, JPG, WEBP or GIF.")
    gif_width = max(120, min(500, int(gif_width or 300)))
    fs = (free_spins or "50").strip() or "50"

    R = _load("render_cards")
    G = _load("make_gif")
    # make_gif imported its own copy of render_cards; keep them in sync so both
    # share the exact same geometry/helpers.
    G.R = R

    import base64
    import tempfile

    ext = {"image/jpeg": "png", "image/jpg": "png"}.get(mime, mime.split("/")[-1])
    data_uri = f"data:{mime};base64," + base64.b64encode(image_bytes).decode("ascii")
    idx = SUIT_NAMES.index(suit)

    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        png_path = tmp / "front.png"
        R.render_png(R.single_html(idx, fs, data_uri), png_path, scale=2)
        gif_path = G.make_one(idx, fs, gif_width, tmp, data_uri)
        return {
            "png": png_path.read_bytes(),
            "gif": gif_path.read_bytes(),
            "gif_name": gif_path.name,
        }
