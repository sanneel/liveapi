"""Slot-card configurator admin page.

  GET  /admin/slot-cards            → redirects to the Optimization page's
                                       Slot Cards tab (/admin/promotions?tab=slot_cards),
                                       where the drop-a-photo UI actually lives
                                       (partials/_slot_cards_panel.html)
  POST /admin/slot-cards/generate   → multipart image + suit + free-spins,
                                       returns the rendered flip GIF + front PNG
                                       (base64 data URIs) with the photo in the
                                       card's artwork well.

The heavy lifting (headless Chromium render of the card + flip GIF) lives in
app/services/slot_card_runner.py, which reuses the email_cards/ code.
"""

from __future__ import annotations

import base64
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from fastapi.responses import JSONResponse, RedirectResponse

from ..auth.dependencies import require_role
from ..logging_config import get_logger
from ..models import User
from ..services import slot_card_runner as runner
from .public_slot_gif import _store_image

BASE_DIR = Path(__file__).resolve().parent.parent
logger = get_logger("app.routes.admin_slot_cards")

router = APIRouter()


@router.get("/admin/slot-cards")
def slot_cards_page(
    request: Request,
    user: User = Depends(require_role("editor")),
) -> RedirectResponse:
    """Slot Cards moved into the Optimization hub as a tab — keep the old URL
    working for bookmarks/links instead of 404ing."""
    return RedirectResponse(url="/admin/promotions?tab=slot_cards", status_code=307)


def _uri(raw: bytes, ct: str) -> str:
    return f"data:{ct};base64," + base64.b64encode(raw).decode("ascii")


@router.post("/admin/slot-cards/generate")
async def slot_cards_generate(
    image: UploadFile = File(...),
    free_spins: str = Form("50"),
    total_width: int = Form(560),
    # Per-tier spin values (index-aligned with the four suits). Blank -> default.
    bet_hearts: str = Form(""),
    bet_diamonds: str = Form(""),
    bet_clubs: str = Form(""),
    bet_spades: str = Form(""),
    user: User = Depends(require_role("editor")),
) -> JSONResponse:
    """Render ONE transparent GIF with all four tiers in a 2x2 grid, plus the
    four transparent front PNGs, from a single uploaded slot image."""
    data = await image.read()
    mime = (image.content_type or "").lower().split(";")[0].strip()
    bets = [bet_hearts, bet_diamonds, bet_clubs, bet_spades]
    try:
        out = runner.render_grid(data, mime, free_spins, bets, total_width)
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
    except Exception as exc:  # surface the real reason (e.g. missing Chromium)
        logger.exception("slot-card render failed")
        return JSONResponse({"error": f"Render failed: {exc}"}, status_code=500)

    # Store image temporarily so public URL can use it
    img_id = _store_image(data, mime)

    return JSONResponse({
        "gif": _uri(out["gif"], "image/gif"),
        "gif_name": out["gif_name"],
        "img_id": img_id,
        "cards": [
            {
                "suit": c["suit"], "label": c["label"], "deposit": c["deposit"],
                "bet": c["bet"], "png": _uri(c["png"], "image/png"),
            }
            for c in out["cards"]
        ],
    })
