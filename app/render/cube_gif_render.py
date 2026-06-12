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

from PIL import Image, ImageDraw

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
GIF_SIZE = 360        # square px; sharp enough for the odds text
GIF_PALETTE_COLORS = 256  # max GIF palette — best fidelity on the trophy/gradient

# Route-level clamps so a hand-edited URL can't request a 4000px GIF.
GIF_SIZE_MIN, GIF_SIZE_MAX = 160, 512

# "Showcase" rotation: the cube PAUSES with each face front-on (so the odds are
# big and readable), then smoothly turns 90° to the next. Constant spinning at
# email size leaves the odds skewed/tiny and unreadable; the dwell is what makes
# them legible while still reading as a rotating 3D cube.
GIF_DWELL_DEFAULT = 1.6   # seconds each face is held front-on
GIF_DWELL_MIN, GIF_DWELL_MAX = 0.3, 5.0
GIF_TURN_DEFAULT = 0.6    # seconds to rotate 90° between faces
GIF_TURN_MIN, GIF_TURN_MAX = 0.2, 2.0
GIF_TURN_STEPS = 8        # frames per 90° turn (smoothness of the motion)

# Camera/geometry constants. World units: half-width = 1.0 (square cross-section
# so it's a true cube; height is scaled to the face aspect so the side artwork
# isn't distorted).
_FACE_HALF_W = 1.0
_FACE_HALF_H = _FACE_HALF_W * (FACE_H / FACE_W)
_CAM_DISTANCE = 3.4  # ~3× cube width, mirrors the widget's CSS perspective
# Pixel scale leaving margin for the tilt (which makes the silhouette taller)
# and the side faces that swing toward the edges mid-spin.
_FIT = 0.66
# Supersample factor: render each frame this many times larger, then downscale
# with LANCZOS before quantizing. Antialiases the perspective-warped edges and
# odds text — the single biggest perceived-quality win. File size is unchanged
# (final pixels are the same); only render time grows (~SS²).
_SUPERSAMPLE = 2
# Look slightly DOWN at the cube so its top is always visible. This is the key
# to "always looks 3D" — a face is never a perfectly flat rectangle, so the
# spin reads as a rotating solid instead of flipping between flat pages. Kept
# modest so the faces stay large/legible and the top doesn't dominate.
GIF_TILT_DEFAULT = 16.0
GIF_TILT_MIN, GIF_TILT_MAX = 0.0, 40.0
# Cull faces whose normal points away from the camera (small epsilon so a face
# exactly edge-on doesn't flicker on/off).
_BACKFACE_EPS = 1e-4


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


Point3 = Tuple[float, float, float]


def _cube_faces_model() -> List[Tuple[int, List[Point3]]]:
    """The cube as 5 visible faces (4 sides + top), each a list of 3D corners
    ordered [top-left, top-right, bottom-right, bottom-left] in the source
    image's own orientation. y is up. Returns (image_index, corners); image
    indices 0–3 are the four sides in spin order, 4 is the top texture.
    """
    a = _FACE_HALF_W
    hh = _FACE_HALF_H
    # 8 cube vertices: 0–3 top ring (y=+hh), 4–7 bottom ring (y=-hh).
    v = [
        (-a, hh, -a), (a, hh, -a), (a, hh, a), (-a, hh, a),
        (-a, -hh, -a), (a, -hh, -a), (a, -hh, a), (-a, -hh, a),
    ]
    return [
        (0, [v[3], v[2], v[6], v[7]]),  # front (+z)
        (1, [v[2], v[1], v[5], v[6]]),  # right (+x)
        (2, [v[1], v[0], v[4], v[5]]),  # back  (-z)
        (3, [v[0], v[3], v[7], v[4]]),  # left  (-x)
        (4, [v[0], v[1], v[2], v[3]]),  # top   (+y)
    ]


def _render_frame(
    images: Sequence[Image.Image],
    background: Image.Image,
    theta: float,
    size: int,
    tilt: float,
) -> Image.Image:
    """Composite all camera-facing cube faces for one rotation angle (radians),
    viewed with a downward `tilt` (radians) so the top stays visible."""
    frame = background.copy().convert("RGBA")
    cx = cy = size / 2.0
    scale = _FIT * size
    st, ct = math.sin(theta), math.cos(theta)
    sp, cp = math.sin(tilt), math.cos(tilt)

    def rotate(p: Point3) -> Point3:
        x, y, z = p
        # Spin about the vertical (Y) axis…
        xr = x * ct + z * st
        zr = -x * st + z * ct
        # …then tilt about X so the top tips toward the camera.
        yr = y * cp - zr * sp
        zr2 = y * sp + zr * cp
        return xr, yr, zr2

    def project(p: Point3) -> Tuple[float, float]:
        x, y, z = p
        den = _CAM_DISTANCE - z
        return cx + scale * x / den, cy - scale * y / den

    src_side = [(0.0, 0.0), (float(FACE_W), 0.0),
                (float(FACE_W), float(FACE_H)), (0.0, float(FACE_H))]

    visible: List[Tuple[float, int, List[Tuple[float, float]]]] = []
    for img_idx, corners in _cube_faces_model():
        r = [rotate(c) for c in corners]
        # Every cube face is centered on its own outward normal (the cube is at
        # the origin), so the rotated face-center depth IS the outward normal's
        # z. Positive → the face points toward the camera and is visible.
        avg_z = sum(p[2] for p in r) / 4.0
        if avg_z <= _BACKFACE_EPS:
            continue
        dst = [project(p) for p in r]
        visible.append((avg_z, img_idx, dst))

    # Painter's algorithm: draw far faces (smaller z) first.
    visible.sort(key=lambda item: item[0])

    for _avg_z, img_idx, dst in visible:
        img = images[img_idx]
        src = src_side if img_idx < 4 else [
            (0.0, 0.0), (float(img.width), 0.0),
            (float(img.width), float(img.height)), (0.0, float(img.height)),
        ]
        coeffs = _perspective_coeffs(dst, src)
        warped = img.transform(
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


def _smoothstep(x: float) -> float:
    """Ease-in-out so each 90° turn accelerates then decelerates."""
    return x * x * (3.0 - 2.0 * x)


def _rotation_schedule(
    dwell_ms: float, turn_ms: float, turn_steps: int
) -> Tuple[List[float], List[int]]:
    """Build (angles, per-frame durations) for one full revolution: hold each
    of the 4 faces front-on, then ease 90° to the next. A hold is a single
    long-duration frame (cheap); the turn is several short frames (smooth)."""
    angles: List[float] = []
    durations: List[int] = []
    quarter = math.pi / 2.0
    step_ms = max(20, int(round(turn_ms / turn_steps / 10)) * 10)
    for i in range(4):
        base = i * quarter
        angles.append(base)
        durations.append(max(20, int(round(dwell_ms / 10)) * 10))
        # Intermediate turn frames only (exclude the endpoint — it equals the
        # NEXT face's hold angle, which would dedupe and misalign durations).
        for k in range(1, turn_steps):
            angles.append(base + quarter * _smoothstep(k / turn_steps))
            durations.append(step_ms)
    return angles, durations


def render_cube_gif(
    theme: CubeTheme,
    faces: Sequence[Image.Image],
    *,
    size: int = GIF_SIZE,
    dwell_ms: float = GIF_DWELL_DEFAULT * 1000,
    turn_ms: float = GIF_TURN_DEFAULT * 1000,
    turn_steps: int = GIF_TURN_STEPS,
    palette_colors: int = GIF_PALETTE_COLORS,
    transparent: bool = False,
    tilt_deg: float = GIF_TILT_DEFAULT,
) -> bytes:
    """Render a looping animated GIF of the spinning 3D cube.

    `faces` must hold exactly four images (one per cube side, in spin order).
    They are normalized to the canonical face size internally. The cube's top
    is generated from the theme so a tilted view always reads as a solid.

    When `transparent` is True the branded gradient background is dropped and
    the area around the cube is made see-through (1-bit GIF transparency, so
    edges are hard rather than feathered).
    """
    if len(faces) != 4:
        raise ValueError(f"render_cube_gif expects 4 faces, got {len(faces)}")

    tilt = math.radians(max(GIF_TILT_MIN, min(tilt_deg, GIF_TILT_MAX)))
    sides = [_prepare_face(f) for f in faces]
    # 4 sides + generated top, indexed to match _cube_faces_model(). The top
    # borrows the promo face's frame color so the lid stays on-brand.
    prepared = sides + [_top_texture(sides[0])]

    # Supersample: render large, then downscale with LANCZOS for clean edges.
    rsize = size * _SUPERSAMPLE
    if transparent:
        background: Image.Image = Image.new("RGBA", (rsize, rsize), (0, 0, 0, 0))
    else:
        background = _vertical_gradient((rsize, rsize), theme.bg_top, theme.bg_bottom)

    # Showcase rotation: pause front-on on each face, then ease 90° to the next.
    angles, durations = _rotation_schedule(dwell_ms, turn_ms, turn_steps)
    rendered = [
        _render_frame(prepared, background, ang, rsize, tilt)
        .resize((size, size), Image.LANCZOS)
        for ang in angles
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
        duration=durations,
        loop=0,
        optimize=True,
        **save_kwargs,
    )
    data = buf.getvalue()
    logger.info(
        "cube gif rendered theme=%s size=%d frames=%d transparent=%s bytes=%d",
        theme.slug, size, len(rendered), transparent, len(data),
    )
    return data


def _border_color(face: Image.Image) -> Tuple[int, int, int]:
    """Average color of a face's outer frame, so the top lid matches the
    cube's own branded border instead of clashing with the theme background."""
    w, h = face.size
    strip = face.convert("RGB").crop((0, 0, w, max(1, h // 12)))
    small = strip.resize((1, 1), Image.BILINEAR)
    return small.getpixel((0, 0))


def _top_texture(promo_face: Image.Image) -> Image.Image:
    """Square texture for the cube's top face: a solid panel in the cube's own
    border color, slightly darkened so it reads as a distinct top plane, with a
    thin inner line. Sampling the face border keeps the lid on-brand."""
    side = FACE_W
    r, g, b = _border_color(promo_face)
    base = (int(r * 0.82), int(g * 0.82), int(b * 0.82))
    top = Image.new("RGBA", (side, side), base + (255,))
    draw = ImageDraw.Draw(top)
    inset = max(2, side // 22)
    inner = (int(r * 0.62), int(g * 0.62), int(b * 0.62), 255)
    draw.rectangle(
        [inset, inset, side - inset - 1, side - inset - 1],
        outline=inner,
        width=max(2, side // 110),
    )
    return top
