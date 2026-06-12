"""
Animated-GIF renderer for the 3D cube — for email communications.

Email clients run no CSS 3D transforms or JavaScript, so the live spinning
cube widget (`app/templates/cube/widget.html`) can never display in an
inbox. This module bakes the same spinning-cube look into an animated GIF
that an email's `<img src>` can point at.

Like the rest of the cube pipeline this is deliberately dependency-light —
PIL-only, no numpy, no Playwright, no Chromium. Each frame perspective-
projects the four prism faces (promo / odds, the same images the widget
shows) around the vertical axis using a homography solved with a small
pure-Python Gaussian elimination, then the frames are assembled into a
looping GIF with a shared palette so colors don't flicker between frames.

The caller supplies the four face images already rendered (promo JPGs and
live odds PNGs); this module owns only the geometry and GIF assembly, so it
stays free of any DB or theme-resolution concerns.
"""

from __future__ import annotations

import math
from io import BytesIO
from typing import List, Sequence, Tuple

from PIL import Image

from ..logging_config import get_logger
from ..services.cube_themes import CubeTheme

logger = get_logger("app.render.cube_gif_render")

# Source face aspect — matches the widget's 420×380 (= 1.105:1) faces.
FACE_W = 420
FACE_H = 380

# ── Email-friendly defaults ──────────────────────────────────────────────
# Square canvas so the GIF drops into email headers / social without
# re-cropping. Kept modest because animated GIFs of photographic faces grow
# fast; these defaults land a smooth full rotation around ~700KB, which most
# email clients accept inline without clipping.
GIF_SIZE = 360        # square px; sharp enough for the odds text, ~700-870KB
GIF_FRAMES = 24       # 15° per step — smooth enough, keeps the file small
GIF_FRAME_MS = 80     # 24 × 80ms ≈ 1.9s per full revolution
GIF_PALETTE_COLORS = 192  # photographic faces survive 192 colors + dithering

# Route-level clamps so a hand-edited URL can't request a 4000px, 200-frame GIF.
GIF_SIZE_MIN, GIF_SIZE_MAX = 160, 512
GIF_FRAMES_MIN, GIF_FRAMES_MAX = 8, 48

# Camera/geometry constants. World units: face half-width = 1.0.
_FACE_HALF_W = 1.0
_FACE_HALF_H = _FACE_HALF_W * (FACE_H / FACE_W)
_CAM_DISTANCE = 3.0  # ~3× face width, mirrors the widget's CSS perspective
# Pixel scale: front face (Z=+1, depth = CAM-1 = 2) spans ~0.72×canvas wide,
# leaving margin for the side faces that swing toward the edges mid-spin.
_FIT = 0.72
# Cull faces whose normal points away from the camera (with a small epsilon
# so a face exactly edge-on doesn't flicker on/off).
_BACKFACE_EPS = 0.02


def _vertical_gradient(
    size: Tuple[int, int],
    top: Tuple[int, int, int],
    bottom: Tuple[int, int, int],
) -> Image.Image:
    """Solid branded background. GIF 1-bit transparency looks bad on the
    colored email backgrounds these run on, so frames are composited onto an
    opaque gradient instead of shipping transparency.

    Built as a 1-pixel-wide vertical strip then stretched horizontally — each
    row is a flat color, so the cheap resize is exact and PIL-only (no numpy).
    """
    w, h = size
    strip = Image.new("RGB", (1, h))
    px = strip.load()
    denom = max(1, h - 1)
    for y in range(h):
        t = y / denom
        px[0, y] = (
            int(top[0] + (bottom[0] - top[0]) * t),
            int(top[1] + (bottom[1] - top[1]) * t),
            int(top[2] + (bottom[2] - top[2]) * t),
        )
    return strip.resize((w, h), Image.BILINEAR)


def _prepare_face(img: Image.Image) -> Image.Image:
    """Normalize any supplied face image to the canonical face size + RGBA."""
    rgba = img.convert("RGBA")
    if rgba.size != (FACE_W, FACE_H):
        rgba = rgba.resize((FACE_W, FACE_H), Image.LANCZOS)
    return rgba


def _solve_linear(matrix: List[List[float]], rhs: List[float]) -> List[float]:
    """Solve a square linear system via Gaussian elimination with partial
    pivoting. Small fixed size (8×8 here), so pure Python is plenty fast and
    keeps this module dependency-free."""
    n = len(rhs)
    # Augmented matrix [A | b].
    aug = [list(matrix[i]) + [rhs[i]] for i in range(n)]
    for col in range(n):
        # Partial pivot: swap in the row with the largest magnitude in `col`.
        pivot = max(range(col, n), key=lambda r: abs(aug[r][col]))
        if abs(aug[pivot][col]) < 1e-12:
            raise ValueError("Degenerate perspective system (collinear quad)")
        aug[col], aug[pivot] = aug[pivot], aug[col]
        pivot_val = aug[col][col]
        for r in range(n):
            if r == col:
                continue
            factor = aug[r][col] / pivot_val
            if factor:
                for c in range(col, n + 1):
                    aug[r][c] -= factor * aug[col][c]
    return [aug[i][n] / aug[i][i] for i in range(n)]


def _perspective_coeffs(
    dst: Sequence[Tuple[float, float]],
    src: Sequence[Tuple[float, float]],
) -> Tuple[float, ...]:
    """Solve the 8 PIL PERSPECTIVE coefficients mapping each output (dst)
    point back to its input (src) point — the direction PIL.transform wants.
    """
    matrix: List[List[float]] = []
    rhs: List[float] = []
    for (dx, dy), (sx, sy) in zip(dst, src):
        matrix.append([dx, dy, 1, 0, 0, 0, -sx * dx, -sx * dy])
        matrix.append([0, 0, 0, dx, dy, 1, -sy * dx, -sy * dy])
        rhs.append(sx)
        rhs.append(sy)
    return tuple(_solve_linear(matrix, rhs))


def _face_geometry(
    face_angle: float, size: int
) -> Tuple[float, List[Tuple[float, float]]]:
    """Project one vertical face at the given rotation angle (radians).

    Returns (average_depth_Z, dst_quad) where dst_quad is the four canvas
    corners [top-left, top-right, bottom-right, bottom-left]. The two side
    edges stay vertical (same Z along each edge), so the face is a trapezoid
    whose left/right heights differ with perspective depth.
    """
    a = _FACE_HALF_W
    hh = _FACE_HALF_H
    sin_p = math.sin(face_angle)
    cos_p = math.cos(face_angle)

    # Left edge (local u = -a) and right edge (u = +a) positions in X–Z.
    x_left = a * sin_p - a * cos_p
    z_left = a * cos_p + a * sin_p
    x_right = a * sin_p + a * cos_p
    z_right = a * cos_p - a * sin_p

    cx = size / 2.0
    cy = size / 2.0
    scale = _FIT * size

    den_l = _CAM_DISTANCE - z_left
    den_r = _CAM_DISTANCE - z_right

    xl = cx + scale * x_left / den_l
    xr = cx + scale * x_right / den_r
    yt_l = cy - scale * hh / den_l
    yb_l = cy + scale * hh / den_l
    yt_r = cy - scale * hh / den_r
    yb_r = cy + scale * hh / den_r

    dst = [(xl, yt_l), (xr, yt_r), (xr, yb_r), (xl, yb_l)]
    return (z_left + z_right) / 2.0, dst


def _render_frame(
    faces: Sequence[Image.Image],
    background: Image.Image,
    theta: float,
    size: int,
) -> Image.Image:
    """Composite all camera-facing faces for one rotation angle (radians)."""
    frame = background.copy().convert("RGBA")
    src_corners = [(0.0, 0.0), (float(FACE_W), 0.0),
                   (float(FACE_W), float(FACE_H)), (0.0, float(FACE_H))]

    visible: List[Tuple[float, int, List[Tuple[float, float]]]] = []
    for i, _face in enumerate(faces):
        face_angle = theta + i * (math.pi / 2.0)
        # Front-facing when the face normal (sin, cos) has cos > 0 toward camera.
        if math.cos(face_angle) <= _BACKFACE_EPS:
            continue
        avg_z, dst = _face_geometry(face_angle, size)
        visible.append((avg_z, i, dst))

    # Painter's algorithm: draw far faces first so nearer ones overlap them.
    visible.sort(key=lambda item: item[0])

    for _avg_z, i, dst in visible:
        coeffs = _perspective_coeffs(dst, src_corners)
        warped = faces[i].transform(
            (size, size),
            Image.PERSPECTIVE,
            coeffs,
            resample=Image.BICUBIC,
            fillcolor=(0, 0, 0, 0),
        )
        frame.alpha_composite(warped)

    # Caller decides whether to flatten (opaque GIF) or keep alpha (transparent).
    return frame


# GIF transparency is 1-bit: a pixel is fully opaque or fully see-through.
# Edge pixels from the perspective resample carry partial alpha; anything at
# or above this threshold becomes opaque, the rest transparent.
_ALPHA_THRESHOLD = 128
# Palette index reserved for the transparent color in the transparent path.
_TRANSPARENT_INDEX = 255


def _quantize_opaque(
    frames_rgba: List[Image.Image], palette_colors: int
) -> List[Image.Image]:
    """Flatten onto the (already-opaque) background and map to a shared
    palette so colors stay stable across frames."""
    rgb_frames = [f.convert("RGB") for f in frames_rgba]
    palette_src = rgb_frames[0].quantize(colors=palette_colors, method=Image.FASTOCTREE)
    return [f.quantize(palette=palette_src, dither=Image.FLOYDSTEINBERG) for f in rgb_frames]


def _quantize_transparent(frames_rgba: List[Image.Image]) -> List[Image.Image]:
    """Map frames to a shared ≤255-color palette and reserve one index for
    transparency, set from each frame's thresholded alpha channel."""
    # Build a shared palette from the opaque face pixels of every frame so the
    # palette covers all rotation angles, leaving index 255 free for transparency.
    rgb_frames = [f.convert("RGB") for f in frames_rgba]
    palette_src = rgb_frames[0].quantize(colors=_TRANSPARENT_INDEX, method=Image.FASTOCTREE)

    out: List[Image.Image] = []
    for rgba, rgb in zip(frames_rgba, rgb_frames):
        p = rgb.quantize(palette=palette_src, dither=Image.FLOYDSTEINBERG)
        # 1-bit mask: opaque where alpha ≥ threshold.
        mask = rgba.getchannel("A").point(lambda a: 255 if a >= _ALPHA_THRESHOLD else 0)
        # Paint transparent pixels with the reserved index.
        p.paste(_TRANSPARENT_INDEX, mask=Image.eval(mask, lambda v: 255 - v))
        p.info["transparency"] = _TRANSPARENT_INDEX
        out.append(p)
    return out


def render_cube_gif(
    theme: CubeTheme,
    faces: Sequence[Image.Image],
    *,
    size: int = GIF_SIZE,
    frames: int = GIF_FRAMES,
    frame_ms: int = GIF_FRAME_MS,
    palette_colors: int = GIF_PALETTE_COLORS,
    transparent: bool = False,
) -> bytes:
    """Render a looping animated GIF of the spinning 3D cube.

    `faces` must hold exactly four images (one per prism face, in rotation
    order). They are normalized to the canonical face size internally.

    When `transparent` is True the branded gradient background is dropped and
    the area around the cube is made see-through (1-bit GIF transparency, so
    edges are hard rather than feathered).
    """
    if len(faces) != 4:
        raise ValueError(f"render_cube_gif expects 4 faces, got {len(faces)}")

    prepared = [_prepare_face(f) for f in faces]
    if transparent:
        background: Image.Image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    else:
        background = _vertical_gradient((size, size), theme.bg_top, theme.bg_bottom)

    rendered = [
        _render_frame(prepared, background, 2 * math.pi * (n / frames), size)
        for n in range(frames)
    ]

    if transparent:
        paletted = _quantize_transparent(rendered)
        save_kwargs = {"transparency": _TRANSPARENT_INDEX, "disposal": 2}
    else:
        paletted = _quantize_opaque(rendered, palette_colors)
        save_kwargs = {"disposal": 2}

    buf = BytesIO()
    paletted[0].save(
        buf,
        format="GIF",
        save_all=True,
        append_images=paletted[1:],
        duration=frame_ms,
        loop=0,
        optimize=True,
        **save_kwargs,
    )
    data = buf.getvalue()
    logger.info(
        "cube gif rendered theme=%s size=%d frames=%d transparent=%s bytes=%d",
        theme.slug, size, frames, transparent, len(data),
    )
    return data
