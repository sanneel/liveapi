"""
Shared logo pipeline for all sport render servers.

Responsibilities:
- Download remote team logos and cache them on disk so renders survive
  process restarts without re-hitting the upstream CDN.
- Maintain an in-memory negative cache so we don't hammer the CDN with
  failing requests when a slug has been renamed/removed upstream.
- Generate an initials-based placeholder when no logo is available,
  so the renderer never produces an empty box.
- Emit structured logs on every fetch failure so QA can see exactly
  which URLs are broken.

Used in-process by `render_server.py`, `basketball_render_server.py`,
`tennis_render_server.py`, `cybersport_render_server.py`,
`fights_render_server.py`. Production runs a single uvicorn process,
so an in-process dict + on-disk cache is sufficient.
"""

from __future__ import annotations

import hashlib
import os
import re
import threading
import time
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

import requests
from PIL import Image, ImageDraw, ImageFont

from ..config import BASE_DIR
from ..logging_config import get_logger

logger = get_logger("app.render.logos")

# ── Layout ──────────────────────────────────────────────────────────
# Every render server normalises logos to LOGO_INNER × LOGO_INNER before
# pasting; keep that single canonical size here.
LOGO_INNER = 84
LOGO_TTL_SECONDS = 6 * 3600
LOGO_NEG_TTL_SECONDS = 30 * 60     # remember failures for 30 min
LOGO_MAX_MEM_CACHE = 500
REQUEST_TIMEOUT = 5.0

LOGO_CACHE_DIR = Path(os.environ.get("LOGO_CACHE_DIR", str(BASE_DIR / "data" / "logo_cache")))
LOGO_CACHE_DIR.mkdir(parents=True, exist_ok=True)

_LOGO_FONT_PATH = BASE_DIR / "fonts" / "RobotoCondensed-ExtraBold.ttf"

_lock = threading.Lock()
_mem_cache: Dict[str, Dict[str, Any]] = {}
# url -> {"ts": epoch, "png": bytes-or-None}

_PALETTE: Tuple[Tuple[int, int, int], ...] = (
    (33, 80, 119),
    (102, 51, 153),
    (140, 50, 60),
    (52, 110, 70),
    (140, 90, 30),
    (60, 80, 150),
    (110, 40, 100),
    (40, 110, 140),
)


@dataclass(frozen=True)
class LogoFetchResult:
    bytes_: Optional[bytes]
    source: str  # "mem", "disk", "remote", "fallback"


def _url_hash(url: str) -> str:
    return hashlib.sha256(url.encode("utf-8")).hexdigest()[:32]


def _disk_path(url: str) -> Path:
    return LOGO_CACHE_DIR / f"{_url_hash(url)}.png"


def _disk_neg_path(url: str) -> Path:
    return LOGO_CACHE_DIR / f"{_url_hash(url)}.404"


def _prune_locked() -> None:
    now = time.time()
    expired = [u for u, e in _mem_cache.items() if (now - e["ts"]) > LOGO_TTL_SECONDS]
    for u in expired:
        _mem_cache.pop(u, None)

    if len(_mem_cache) <= LOGO_MAX_MEM_CACHE:
        return

    items = sorted(_mem_cache.items(), key=lambda kv: kv[1]["ts"])
    for u, _ in items[: max(0, len(_mem_cache) - LOGO_MAX_MEM_CACHE)]:
        _mem_cache.pop(u, None)


def _resize_to_inner(raw: bytes) -> bytes:
    im = Image.open(BytesIO(raw)).convert("RGBA")
    im = im.resize((LOGO_INNER, LOGO_INNER), resample=Image.Resampling.LANCZOS)
    out = BytesIO()
    im.save(out, format="PNG", optimize=True)
    return out.getvalue()


def _download(url: str) -> Tuple[Optional[bytes], str]:
    """Return (png_bytes, reason). reason is a short tag for logging."""
    try:
        r = requests.get(
            url,
            timeout=REQUEST_TIMEOUT,
            headers={"User-Agent": "hot-render/1.0"},
        )
    except requests.RequestException as exc:
        return None, f"net:{type(exc).__name__}"

    if r.status_code != 200:
        return None, f"http:{r.status_code}"
    if not r.content:
        return None, "empty-body"

    try:
        return _resize_to_inner(r.content), "ok"
    except Exception as exc:  # PIL decode failure
        return None, f"decode:{type(exc).__name__}"


def get_logo_png_bytes(url: Optional[str]) -> Optional[bytes]:
    """Return PNG bytes (LOGO_INNER × LOGO_INNER) for the given URL.

    Returns None if the URL is empty or every cache layer / download fails.
    On every transition from "unknown" to "missing" the failure is logged.
    """
    if not url:
        return None
    u = url.strip()
    if not u:
        return None

    now = time.time()

    with _lock:
        entry = _mem_cache.get(u)
        if entry and (now - entry["ts"] <= LOGO_TTL_SECONDS):
            return entry.get("png")

    disk = _disk_path(u)
    neg = _disk_neg_path(u)

    if disk.exists():
        try:
            data = disk.read_bytes()
            with _lock:
                _mem_cache[u] = {"ts": now, "png": data}
                _prune_locked()
            return data
        except OSError as exc:
            logger.warning("logo disk read failed url=%s err=%s", u, exc)

    if neg.exists() and (now - neg.stat().st_mtime) <= LOGO_NEG_TTL_SECONDS:
        with _lock:
            _mem_cache[u] = {"ts": now, "png": None}
        return None

    png, reason = _download(u)
    if png is not None:
        try:
            disk.write_bytes(png)
        except OSError as exc:
            logger.warning("logo disk write failed url=%s err=%s", u, exc)
    else:
        logger.warning("logo fetch failed url=%s reason=%s", u, reason)
        try:
            neg.write_bytes(b"")
        except OSError:
            pass

    with _lock:
        _mem_cache[u] = {"ts": now, "png": png}
        _prune_locked()

    return png


# ── Initials fallback ───────────────────────────────────────────────

_initials_lock = threading.Lock()
_initials_cache: Dict[Tuple[str, int], bytes] = {}


def _initials_for_name(name: str) -> str:
    s = re.sub(r"[^\w\s\-]", "", (name or "").strip(), flags=re.UNICODE)
    if not s:
        return "?"
    parts = [p for p in re.split(r"[\s\-]+", s) if p]
    if not parts:
        return s[:1].upper() or "?"
    if len(parts) == 1:
        return parts[0][:2].upper()
    return (parts[0][:1] + parts[-1][:1]).upper()


def _color_for_name(name: str) -> Tuple[int, int, int]:
    idx = int(hashlib.md5((name or "?").encode("utf-8")).hexdigest()[:8], 16) % len(_PALETTE)
    return _PALETTE[idx]


def _load_font(size: int) -> ImageFont.ImageFont:
    if _LOGO_FONT_PATH.exists():
        try:
            return ImageFont.truetype(str(_LOGO_FONT_PATH), size=size)
        except OSError:
            pass
    return ImageFont.load_default()


def render_initials_png(name: str, size: int = LOGO_INNER) -> bytes:
    """Render a filled circle with initials, sized to fit the logo inner box."""
    key = ((name or "").lower(), int(size))
    with _initials_lock:
        cached = _initials_cache.get(key)
        if cached is not None:
            return cached

    initials = _initials_for_name(name)
    bg = _color_for_name(name)

    im = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(im)
    draw.ellipse((0, 0, size - 1, size - 1), fill=(*bg, 235))

    font_size = max(14, int(size * (0.46 if len(initials) >= 2 else 0.58)))
    font = _load_font(font_size)
    try:
        bbox = draw.textbbox((0, 0), initials, font=font)
        tw = bbox[2] - bbox[0]
        th = bbox[3] - bbox[1]
        tx = (size - tw) / 2 - bbox[0]
        ty = (size - th) / 2 - bbox[1]
    except Exception:
        tw = draw.textlength(initials, font=font)
        tx = (size - tw) / 2
        ty = size * 0.22

    draw.text((tx, ty), initials, fill=(255, 255, 255, 240), font=font)

    out = BytesIO()
    im.save(out, format="PNG", optimize=True)
    data = out.getvalue()

    with _initials_lock:
        _initials_cache[key] = data
    return data


def get_logo_bytes_for_team(team: Optional[Dict[str, Any]]) -> Optional[bytes]:
    """Resolve a team dict ({name, logo, ...}) to PNG bytes.

    Always returns bytes when a name is present: real logo if reachable,
    initials fallback otherwise. Returns None only when the team is empty,
    so the renderer can still draw an empty plate.
    """
    if not isinstance(team, dict):
        return None
    url = team.get("logo")
    if isinstance(url, str) and url.strip():
        png = get_logo_png_bytes(url)
        if png is not None:
            return png

    name = team.get("name")
    if isinstance(name, str) and name.strip():
        return render_initials_png(name)
    return None


def cache_stats() -> Dict[str, Any]:
    with _lock:
        size = len(_mem_cache)
        misses = sum(1 for e in _mem_cache.values() if e.get("png") is None)
    disk_files = 0
    neg_files = 0
    try:
        for p in LOGO_CACHE_DIR.iterdir():
            if p.suffix == ".png":
                disk_files += 1
            elif p.suffix == ".404":
                neg_files += 1
    except OSError:
        pass
    return {
        "mem_size": size,
        "mem_negative": misses,
        "disk_logos": disk_files,
        "disk_negative": neg_files,
        "disk_dir": str(LOGO_CACHE_DIR),
    }
