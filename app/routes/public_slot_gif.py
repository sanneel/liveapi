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
from fastapi.responses import FileResponse
from PIL import Image

from ..logging_config import get_logger
from ..middleware import limiter
from ..services import slot_card_runner as runner

logger = get_logger("app.routes.public_slot_gif")

router = APIRouter()

# Pre-rendered JugaBet slot-machine story GIF (spin -> boom -> 777 -> win),
# served as a static asset at /r/slotmachine.gif. Regenerate with
# fix_gif_texts.py and copy the result to app/static/slotmachine.gif.
# __file__ is app/routes/public_slot_gif.py, so parents[1] is the app dir.
SLOTMACHINE_GIF = Path(__file__).resolve().parents[1] / "static" / "slotmachine.gif"
SLOTMACHINE1_GIF = Path(__file__).resolve().parents[1] / "static" / "slotmachine1.gif"
SLOTMACHINE_FINAL_PLAYONCE_GIF = Path(__file__).resolve().parents[1] / "static" / "slotmachine_final_playonce.gif"
SLOTMACHINE_3SPINS_SMOOTH_GIF = Path(__file__).resolve().parents[1] / "static" / "slotmachine_3spins_smooth.gif"


@router.get("/r/slotmachine.gif")
def slotmachine_gif() -> Response:
    """Serve the pre-rendered slot-machine story GIF."""
    if not SLOTMACHINE_GIF.is_file():
        raise HTTPException(404, "slotmachine.gif not found")
    return FileResponse(
        SLOTMACHINE_GIF,
        media_type="image/gif",
        headers={"Cache-Control": "public, max-age=86400"},
    )


@router.get("/r/slotmachine1.gif")
def slotmachine1_gif() -> Response:
    """Serve the alternative slot-machine story GIF variant."""
    if not SLOTMACHINE1_GIF.is_file():
        raise HTTPException(404, "slotmachine1.gif not found")
    return FileResponse(
        SLOTMACHINE1_GIF,
        media_type="image/gif",
        headers={"Cache-Control": "public, max-age=86400"},
    )


@router.get("/r/slotmachine_final_playonce.gif")
def slotmachine_final_playonce_gif() -> Response:
    """Serve the final slot-machine story GIF (plays once)."""
    if not SLOTMACHINE_FINAL_PLAYONCE_GIF.is_file():
        raise HTTPException(404, "slotmachine_final_playonce.gif not found")
    return FileResponse(
        SLOTMACHINE_FINAL_PLAYONCE_GIF,
        media_type="image/gif",
        headers={"Cache-Control": "public, max-age=86400"},
    )


@router.get("/r/slotmachine_3spins_smooth.gif")
def slotmachine_3spins_smooth_gif() -> Response:
    """Serve the 3-spins smooth slot-machine story GIF."""
    if not SLOTMACHINE_3SPINS_SMOOTH_GIF.is_file():
        raise HTTPException(404, "slotmachine_3spins_smooth.gif not found")
    return FileResponse(
        SLOTMACHINE_3SPINS_SMOOTH_GIF,
        media_type="image/gif",
        headers={"Cache-Control": "public, max-age=86400"},
    )

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


def _store_image(image_bytes: bytes, mime: str) -> str:
    """Store image temporarily and return a key."""
    import uuid
    key = str(uuid.uuid4())[:8]
    with _image_store_lock:
        if len(_image_store) >= IMAGE_STORE_MAX_ENTRIES:
            oldest_key = min(_image_store, key=lambda k: _image_store[k][0])
            _image_store.pop(oldest_key, None)
        _image_store[key] = (time.time(), image_bytes, mime)
    return key


def _get_stored_image(key: str) -> Optional[Tuple[bytes, str]]:
    """Retrieve stored image if not expired."""
    with _image_store_lock:
        entry = _image_store.get(key)
        if entry and (time.time() - entry[0]) < IMAGE_STORE_TTL_SECONDS:
            return entry[1], entry[2]
        elif entry:
            _image_store.pop(key, None)
    return None


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
