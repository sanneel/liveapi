"""Public slot card GIF endpoint.

  GET /r/slot.gif[?image=<data-uri|url>&bet_hearts=100&bet_diamonds=200&bet_clubs=500&bet_spades=800&free_spins=50&width=560]

Serves a transparent GIF with all four Ace cards (hearts/diamonds/clubs/spades)
flipping front<->JUGABET back in sync. Spin values default to tier defaults if not
specified. If no image is provided, renders with an empty well.
"""

from __future__ import annotations

import base64
import threading
import time
from io import BytesIO
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse

from fastapi import APIRouter, Query, Request, Response, HTTPException
from fastapi.responses import HTMLResponse
from PIL import Image

from ..config import BASE_DIR
from ..logging_config import get_logger
from ..middleware import limiter
from ..services import slot_card_runner as runner

logger = get_logger("app.routes.public_slot_gif")

router = APIRouter()

# Disk storage for generated card GIFs + uploaded artwork, so the URLs pasted
# into an email keep working long after the in-memory caches (and the process)
# are gone.
SLOT_ASSET_DIR = BASE_DIR / "data" / "slot_assets"
_EXT_BY_MIME = {"image/png": ".png", "image/jpeg": ".jpg", "image/jpg": ".jpg",
                "image/webp": ".webp", "image/gif": ".gif"}
_MIME_BY_EXT = {".png": "image/png", ".jpg": "image/jpeg",
                ".webp": "image/webp", ".gif": "image/gif"}

# GIF cache: (image_data_hash, bet_hearts, bet_diamonds, bet_clubs, bet_spades, free_spins, width) -> (ts, gif_bytes)
_gif_cache_lock = threading.Lock()
_gif_cache: Dict[str, Tuple[float, bytes]] = {}

# Image storage: temp_id -> (ts, image_bytes, mime)
_image_store_lock = threading.Lock()
_image_store: Dict[str, Tuple[float, bytes, str]] = {}

GIF_CACHE_TTL_SECONDS = 3600  # 1 hour
GIF_CACHE_MAX_ENTRIES = 100
IMAGE_STORE_TTL_SECONDS = 3600  # 1 hour
IMAGE_STORE_MAX_ENTRIES = 100


def _cache_key(image_hash: str, bets: List[str], free_spins: str, width: int) -> str:
    """Generate cache key from parameters."""
    bet_str = ",".join(bets)
    return f"{image_hash}:{bet_str}:{free_spins}:{width}"


def _cache_get(key: str) -> Optional[bytes]:
    """Get cached GIF if not expired."""
    with _gif_cache_lock:
        entry = _gif_cache.get(key)
        if entry and (time.time() - entry[0]) < GIF_CACHE_TTL_SECONDS:
            return entry[1]
        elif entry:
            _gif_cache.pop(key, None)
    return None


def _cache_put(key: str, gif_bytes: bytes) -> None:
    """Store GIF in cache, evicting oldest if at capacity."""
    with _gif_cache_lock:
        if len(_gif_cache) >= GIF_CACHE_MAX_ENTRIES:
            oldest_key = min(_gif_cache, key=lambda k: _gif_cache[k][0])
            _gif_cache.pop(oldest_key, None)
        _gif_cache[key] = (time.time(), gif_bytes)


def _hash_bytes(data: bytes) -> str:
    """Simple hash of image bytes."""
    import hashlib
    return hashlib.sha256(data).hexdigest()[:16]


def _safe_key(key: str) -> bool:
    """Only ids we minted (hex uuid fragments) — no path tricks."""
    return bool(key) and len(key) <= 32 and key.replace("-", "").isalnum()


def _store_image(image_bytes: bytes, mime: str) -> str:
    """Store the uploaded artwork on disk and return its id. Kept forever (the
    /r/cards page and /r/slot-img URLs go into emails, so they must not expire
    with an in-memory TTL or a restart)."""
    import uuid
    key = str(uuid.uuid4())[:8]
    ext = _EXT_BY_MIME.get(mime, ".png")
    SLOT_ASSET_DIR.mkdir(parents=True, exist_ok=True)
    (SLOT_ASSET_DIR / f"img_{key}{ext}").write_bytes(image_bytes)
    with _image_store_lock:
        if len(_image_store) >= IMAGE_STORE_MAX_ENTRIES:
            oldest_key = min(_image_store, key=lambda k: _image_store[k][0])
            _image_store.pop(oldest_key, None)
        _image_store[key] = (time.time(), image_bytes, mime)
    return key


def _get_stored_image(key: str) -> Optional[Tuple[bytes, str]]:
    """Retrieve stored image — memory first, then disk (survives restarts)."""
    with _image_store_lock:
        entry = _image_store.get(key)
        if entry:
            return entry[1], entry[2]
    if not _safe_key(key):
        return None
    for ext, mime in _MIME_BY_EXT.items():
        p = SLOT_ASSET_DIR / f"img_{key}{ext}"
        if p.exists():
            return p.read_bytes(), mime
    return None


def _store_card_gif(gif_bytes: bytes) -> str:
    """Persist one generated reveal GIF to disk; returns the id used by the
    public /r/card/{gif_id}.gif URL that goes into the email snippet."""
    import uuid
    key = str(uuid.uuid4())[:8]
    SLOT_ASSET_DIR.mkdir(parents=True, exist_ok=True)
    (SLOT_ASSET_DIR / f"gif_{key}.gif").write_bytes(gif_bytes)
    return key


def _load_image(image_param: Optional[str]) -> Optional[bytes]:
    """Load image from data URI, URL, or return None for empty well."""
    if not image_param:
        return None

    # Data URI: data:image/png;base64,...
    if image_param.startswith("data:"):
        try:
            _, data = image_param.split(",", 1)
            return base64.b64decode(data)
        except Exception as e:
            logger.warning(f"Failed to decode data URI: {e}")
            raise HTTPException(400, "Invalid image data URI")

    # URL: try to fetch
    if image_param.startswith("http://") or image_param.startswith("https://"):
        try:
            import requests
            r = requests.get(image_param, timeout=5)
            r.raise_for_status()
            if len(r.content) > 18 * 1024 * 1024:
                raise HTTPException(400, "Image too large (max 18 MB)")
            return r.content
        except Exception as e:
            logger.warning(f"Failed to fetch image from URL: {e}")
            raise HTTPException(400, f"Could not fetch image: {e}")

    raise HTTPException(400, "image must be a data URI or HTTP(S) URL")


@router.get("/r/slot.gif")
@limiter.limit("60/minute")
def slot_gif(
    request: Request,
    image: Optional[str] = Query(None, description="Image as data URI or URL"),
    img_id: Optional[str] = Query(None, description="Stored image ID"),
    bet_hearts: Optional[str] = Query(None),
    bet_diamonds: Optional[str] = Query(None),
    bet_clubs: Optional[str] = Query(None),
    bet_spades: Optional[str] = Query(None),
    free_spins: Optional[str] = Query("50"),
    width: Optional[int] = Query(560),
) -> Response:
    """Render a transparent GIF with all four slot cards in a 2x2 grid."""

    # Load image from storage, parameter, or use empty
    image_bytes = None
    mime = "image/png"
    image_hash = "empty"

    if img_id:
        # Retrieve from temporary storage
        stored = _get_stored_image(img_id)
        if stored:
            image_bytes, mime = stored
            image_hash = img_id
        else:
            logger.warning(f"Stored image not found or expired: {img_id}")
            # Fall through to empty
    elif image:
        # Load from data URI or URL
        try:
            image_bytes = _load_image(image)
            image_hash = _hash_bytes(image_bytes)
        except HTTPException:
            raise
        except Exception as e:
            logger.exception(f"Error loading image: {e}")
            raise HTTPException(400, "Invalid image")

    # Normalize parameters
    bets = [bet_hearts or "", bet_diamonds or "", bet_clubs or "", bet_spades or ""]
    free_spins = (free_spins or "50").strip() or "50"
    width = max(240, min(1000, width or 560))

    # Check cache
    cache_key = _cache_key(image_hash, bets, free_spins, width)
    cached_gif = _cache_get(cache_key)
    if cached_gif:
        return Response(content=cached_gif, media_type="image/gif", headers={
            "Cache-Control": "public, max-age=3600",
            "X-Cache": "HIT",
        })

    # Determine MIME type and render
    try:
        # If no image, render with empty well (transparent background in the well area)
        if image_bytes is None:
            # Create a minimal 1x1 transparent PNG to pass as placeholder
            placeholder = Image.new("RGBA", (1, 1), (0, 0, 0, 0))
            buf = BytesIO()
            placeholder.save(buf, format="PNG")
            image_bytes = buf.getvalue()
            mime = "image/png"
        else:
            # Detect MIME from image bytes (simple heuristic)
            if image_bytes.startswith(b"\x89PNG"):
                mime = "image/png"
            elif image_bytes.startswith(b"\xff\xd8"):
                mime = "image/jpeg"
            elif image_bytes.startswith(b"GIF"):
                mime = "image/gif"
            elif image_bytes.startswith(b"RIFF") and b"WEBP" in image_bytes[:20]:
                mime = "image/webp"
            else:
                mime = "image/png"  # assume PNG

        # Render the grid GIF
        out = runner.render_grid(image_bytes, mime, free_spins, bets, width)
        gif_bytes = out["gif"]

    except ValueError as exc:
        logger.warning(f"render_grid validation error: {exc}")
        raise HTTPException(400, str(exc))
    except Exception as exc:
        logger.exception(f"render_grid failed: {exc}")
        raise HTTPException(500, "Render failed")

    # Cache and return
    _cache_put(cache_key, gif_bytes)
    return Response(content=gif_bytes, media_type="image/gif", headers={
        "Cache-Control": "public, max-age=3600",
        "X-Cache": "MISS",
    })


@router.get("/r/card/{gif_id}.gif")
@limiter.limit("300/minute")
def slot_card_gif(request: Request, gif_id: str) -> Response:
    """Serve one stored reveal GIF (the <img src> the email snippet uses).
    Stored on disk at generate time, so these URLs are permanent."""
    if not _safe_key(gif_id):
        raise HTTPException(404, "GIF not found")
    p = SLOT_ASSET_DIR / f"gif_{gif_id}.gif"
    if not p.exists():
        raise HTTPException(404, "GIF not found")
    return Response(content=p.read_bytes(), media_type="image/gif",
                    headers={"Cache-Control": "public, max-age=31536000, immutable"})


@router.get("/r/slot-img/{img_id}")
@limiter.limit("120/minute")
def slot_img(request: Request, img_id: str) -> Response:
    """Serve a stored uploaded slot-game image (used by the /r/cards page's
    artwork wells)."""
    stored = _get_stored_image(img_id)
    if not stored:
        raise HTTPException(404, "Image not found or expired")
    data, mime = stored
    return Response(content=data, media_type=mime,
                    headers={"Cache-Control": "public, max-age=3600"})


@router.get("/r/cards", response_class=HTMLResponse)
@limiter.limit("60/minute")
def slot_cards_flip_page(
    request: Request,
    img_id: Optional[str] = Query(None, description="Stored image ID for the artwork well"),
    image: Optional[str] = Query(None, description="HTTP(S) image URL for the artwork well"),
    bet_hearts: Optional[str] = Query(None),
    bet_diamonds: Optional[str] = Query(None),
    bet_clubs: Optional[str] = Query(None),
    bet_spades: Optional[str] = Query(None),
    free_spins: Optional[str] = Query("50"),
    link: Optional[str] = Query(None, description="Play Now target for all cards"),
    link_hearts: Optional[str] = Query(None),
    link_diamonds: Optional[str] = Query(None),
    link_clubs: Optional[str] = Query(None),
    link_spades: Optional[str] = Query(None),
) -> HTMLResponse:
    """Interactive click-to-flip landing page: 4 cards face-down on the JUGABET
    back; clicking one turns THAT card around, each card independently. This is
    what email can't do — email GIFs autoplay their reveal instead, and this
    page is where their links should point."""
    game_url = ""
    if img_id and _get_stored_image(img_id):
        game_url = f"/r/slot-img/{img_id}"
    elif image and image.startswith(("http://", "https://")):
        game_url = image

    bets = [bet_hearts or "", bet_diamonds or "", bet_clubs or "", bet_spades or ""]
    links = [link_hearts or link or "", link_diamonds or link or "",
             link_clubs or link or "", link_spades or link or ""]
    html = runner.build_flip_page(game_url, free_spins or "50", bets, links)
    return HTMLResponse(html, headers={"Cache-Control": "public, max-age=300"})
