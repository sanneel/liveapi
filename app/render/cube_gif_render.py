"""
Animated-GIF renderer for the 3D cube — for email communications.

Email clients run no CSS 3D transforms or JavaScript, so the live spinning
cube widget (`app/templates/cube/widget.html`) can never display in an
inbox. This module bakes the same spinning-cube look into an animated GIF
that an email's `<img src>` can point at.

Like the rest of the cube pipeline this is deliberately PIL-only — no
Playwright, no Chromium. Each frame perspective-projects the four prism
faces (promo / odds, the same images the widget shows) around the vertical
axis using a numpy-solved homography, then the frames are assembled into a
looping GIF with a shared palette so colors don't flicker between frames.

The caller supplies the four face images already rendered (promo JPGs and
live odds PNGs); this module owns only the geometry and GIF assembly, so it
stays free of any DB or theme-resolution concerns.
"""

from __future__ import annotations

import math
from io import BytesIO
from typing import List, Sequence, Tuple

import numpy as np
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
GIF_SIZE = 320
GIF_FRAMES = 24       # 15° per step — smooth enough, keeps the file small
GIF_FRAME_MS = 80     # 24 × 80ms ≈ 1.9s per full revolution
GIF_PALETTE_COLORS = 192  # photographic faces survive 192 colors + dithering

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
    opaque gradient instead of shipping transparency."""
    w, h = size
    grad = np.zeros((h, w, 3), dtype=np.uint8)
    for c in range(3):
        col = np.linspace(top[c], bottom[c], h, dtype=np.float32)
        grad[:, :, c] = np.repeat(col[:, None], w, axis=1).astype(np.uint8)
    return Image.fromarray(grad, "RGB")


def _prepare_face(img: Image.Image) -> Image.Image:
    """Normalize any supplied face image to the canonical face size + RGBA."""
    rgba = img.convert("RGBA")
    if rgba.size != (FACE_W, FACE_H):
        rgba = rgba.resize((FACE_W, FACE_H), Image.LANCZOS)
    return rgba


def _perspective_coeffs(
    dst: Sequence[Tuple[float, float]],
    src: Sequence[Tuple[float, float]],
) -> Tuple[float, ...]:
    """Solve the 8 PIL PERSPECTIVE coefficients mapping each output (dst)
    point back to its input (src) point — the direction PIL.transform wants.
    """
    matrix = []
    for (dx, dy), (sx, sy) in zip(dst, src):
        matrix.append([dx, dy, 1, 0, 0, 0, -sx * dx, -sx * dy])
        matrix.append([0, 0, 0, dx, dy, 1, -sy * dx, -sy * dy])
    a = np.array(matrix, dtype=np.float64)
    b = np.array([c for pt in src for c in pt], dtype=np.float64)
    coeffs = np.linalg.solve(a, b)
    return tuple(coeffs)


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

    return frame.convert("RGB")


def render_cube_gif(
    theme: CubeTheme,
    faces: Sequence[Image.Image],
    *,
    size: int = GIF_SIZE,
    frames: int = GIF_FRAMES,
    frame_ms: int = GIF_FRAME_MS,
    palette_colors: int = GIF_PALETTE_COLORS,
) -> bytes:
    """Render a looping animated GIF of the spinning 3D cube.

    `faces` must hold exactly four images (one per prism face, in rotation
    order). They are normalized to the canonical face size internally.
    """
    if len(faces) != 4:
        raise ValueError(f"render_cube_gif expects 4 faces, got {len(faces)}")

    prepared = [_prepare_face(f) for f in faces]
    background = _vertical_gradient((size, size), theme.bg_top, theme.bg_bottom)

    rendered = [
        _render_frame(prepared, background, 2 * math.pi * (n / frames), size)
        for n in range(frames)
    ]

    # Shared palette across frames so colors stay stable (no per-frame
    # re-quantization flicker on the photographic faces).
    palette_src = rendered[0].quantize(colors=palette_colors, method=Image.FASTOCTREE)
    paletted = [
        img.quantize(palette=palette_src, dither=Image.FLOYDSTEINBERG)
        for img in rendered
    ]

    buf = BytesIO()
    paletted[0].save(
        buf,
        format="GIF",
        save_all=True,
        append_images=paletted[1:],
        duration=frame_ms,
        loop=0,
        disposal=2,
        optimize=True,
    )
    data = buf.getvalue()
    logger.info(
        "cube gif rendered theme=%s size=%d frames=%d bytes=%d",
        theme.slug, size, frames, len(data),
    )
    return data
