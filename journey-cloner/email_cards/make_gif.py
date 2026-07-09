#!/usr/bin/env python3
"""Render the card flip (front offer -> JUGABET back) to animated GIFs for email.

CSS 3D doesn't run in email, so this bakes the Y-axis flip into a looping GIF.
Both faces are rendered flat (the layout that works), then the rotation is
composed in Pillow: a Y-axis flip is just each face scaled horizontally by
|cos(angle)| — full width face-on, zero at the 90 deg edge. One GIF per tier.

Usage:
  python make_gif.py --free-spins 50            # 4 GIFs into out/
  python make_gif.py --free-spins 50 --only spades --width 360
"""
from __future__ import annotations

import argparse
import math
import subprocess
import sys
import tempfile
from pathlib import Path

from PIL import Image

import render_cards as R

TRANSP_IDX = 255      # palette index reserved for transparency


def _smooth(t: float) -> float:
    return t * t * (3 - 2 * t)


def flip_frames() -> list[tuple[float, int]]:
    """(rotateY angle deg, duration ms) — hold each face, ease the turns."""
    out: list[tuple[float, int]] = [(0.0, 1100)]
    n = 11
    for k in range(1, n + 1):
        out.append((180 * _smooth(k / (n + 1)), 45))
    out.append((180.0, 1100))
    for k in range(1, n + 1):
        out.append((180 + 180 * _smooth(k / (n + 1)), 45))
    return out


def render_face(html: str, scale: int = 2) -> Image.Image:
    # Same viewport as the PNG path so front and back come out identical in size
    # (the flip compositor requires it) and nothing is clipped.
    W, H = R.CARD_W + R.CARD_MARGIN * 2, R.CARD_H + R.CARD_MARGIN * 2
    with tempfile.NamedTemporaryFile("w", suffix=".html", delete=False, encoding="utf-8") as f:
        f.write(html)
        tmp = f.name
    out = Path(tempfile.mktemp(suffix=".png"))
    try:
        subprocess.run(
            [R.chrome_bin(), "--headless=new", "--no-sandbox", "--disable-gpu", "--hide-scrollbars",
             "--force-color-profile=srgb", f"--force-device-scale-factor={scale}",
             "--default-background-color=00000000", f"--window-size={W},{H}",
             f"--screenshot={out}", f"file://{tmp}"],
            capture_output=True, timeout=120,
        )
        if not out.exists():
            sys.exit("Chromium did not render a face.")
        return Image.open(out).convert("RGBA")
    finally:
        Path(tmp).unlink(missing_ok=True)
        out.unlink(missing_ok=True)


def _quant(rgb: Image.Image, palette: Image.Image) -> Image.Image:
    return rgb.quantize(palette=palette, dither=Image.NONE)


def _content_bbox(*imgs: Image.Image):
    """Union of the opaque bounding boxes of the given RGBA images."""
    boxes = [im.getchannel("A").getbbox() for im in imgs]
    boxes = [b for b in boxes if b]
    if not boxes:
        return None
    return (min(b[0] for b in boxes), min(b[1] for b in boxes),
            max(b[2] for b in boxes), max(b[3] for b in boxes))


def _flip_rgba(front: Image.Image, back: Image.Image):
    """The front<->back Y-flip as a list of (RGBA canvas, duration_ms). Both
    faces must be the same size; the canvas is that size."""
    from PIL import ImageEnhance
    W, H = front.size
    out = []
    for angle, dur in flip_frames():
        c = math.cos(math.radians(angle))
        face = front if c >= 0 else back
        w = max(2, int(round(W * abs(c))))
        scaled = face.resize((w, H), Image.LANCZOS)
        if abs(c) < 0.999:  # dim slightly as it turns edge-on
            r, g, b, a = scaled.split()
            scaled = Image.merge("RGBA", (*ImageEnhance.Brightness(Image.merge("RGB", (r, g, b))).enhance(0.72 + 0.28 * abs(c)).split(), a))
        canvas = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        canvas.paste(scaled, ((W - w) // 2, 0), scaled)
        out.append((canvas, dur))
    return out


def _save_transparent_gif(rgba_frames, durs, out_path: Path, out_w: int, disposal: int = 2) -> None:
    """Quantise RGBA frames to one shared palette (index 255 = transparent) and
    write a looping transparent GIF scaled to out_w.

    disposal=2 (restore to background) is right for frames whose transparent
    region changes, but Pillow's writer can corrupt such GIFs for large frames;
    callers whose transparent region is CONSTANT across frames (e.g. a
    crossfade) pass disposal=1, which is stable."""
    ow = out_w
    oh = int(round(ow * rgba_frames[0].height / rgba_frames[0].width))
    scaled = [f.resize((ow, oh), Image.LANCZOS) for f in rgba_frames]
    # Shared palette sampled from a front frame and a back frame so both faces
    # are represented (a single global colour table keeps the GIF clean).
    mid = len(scaled) // 2
    combo = Image.new("RGB", (ow, oh * 2))
    combo.paste(scaled[0].convert("RGB"), (0, 0))
    combo.paste(scaled[mid].convert("RGB"), (0, oh))
    palette = combo.quantize(colors=255, method=Image.FASTOCTREE)
    out_frames = []
    for f in scaled:
        p = _quant(f.convert("RGB"), palette)
        transp = f.getchannel("A").point(lambda v: 255 if v < 128 else 0).convert("1")
        p.paste(TRANSP_IDX, (0, 0), transp)
        p.info["transparency"] = TRANSP_IDX
        out_frames.append(p)
    out_frames[0].save(out_path, save_all=True, append_images=out_frames[1:],
                       duration=durs, loop=0, transparency=TRANSP_IDX, disposal=disposal)


def _crossfade_rgba(front: Image.Image, back: Image.Image, fade: int = 5):
    """front<->back as a crossfade: (RGBA, duration). Both faces share the same
    card silhouette, so the transparent border is identical in every frame — no
    ghosting under disposal=1. Holds are single long-duration frames to keep the
    GIF small."""
    frames = [(front, 1500)]
    for k in range(1, fade + 1):
        frames.append((Image.blend(front, back, k / (fade + 1)), 70))
    frames.append((back, 1500))
    for k in range(1, fade + 1):
        frames.append((Image.blend(back, front, k / (fade + 1)), 70))
    return frames


def make_one(idx: int, free_spins: str, width: int, out_dir: Path, game_uri: str = "", bet: str = "") -> Path:
    front = render_face(R.single_html(idx, free_spins, game_uri, bet))
    back = render_face(R.single_back_html(idx))
    bbox = _content_bbox(front, back)
    if bbox:
        front, back = front.crop(bbox), back.crop(bbox)
    frames = _flip_rgba(front, back)
    name, _, deposit, _ = R.SUITS[idx]
    dep = deposit.replace("$", "").replace(".", "")
    path = out_dir / f"card_{name}_{dep}_flip.gif"
    _save_transparent_gif([f for f, _ in frames], [d for _, d in frames], path, width)
    return path


def make_grid(cards, free_spins: str, cell_width: int, out_path: Path, cols: int = 2,
              gap: int | None = None, margin: int | None = None) -> Path:
    """Render one transparent GIF with every card in a grid, all flipping in
    sync. `cards` is a list of (idx, game_uri, bet). Each card is cropped to its
    full content first so nothing is ever clipped, and a small margin/gap keeps
    every card off the canvas edges."""
    per_card = []  # list of frame lists (RGBA), one per card
    durs = None
    for idx, game_uri, bet in cards:
        front = render_face(R.single_html(idx, free_spins, game_uri, bet))
        back = render_face(R.single_back_html(idx))
        bbox = _content_bbox(front, back)
        if bbox:
            front, back = front.crop(bbox), back.crop(bbox)
        seq = _crossfade_rgba(front, back)
        per_card.append([f for f, _ in seq])
        if durs is None:
            durs = [d for _, d in seq]

    n_frames = len(per_card[0])
    cw = cell_width
    ch = int(round(cw * per_card[0][0].height / per_card[0][0].width))
    if gap is None:
        gap = max(6, round(cw * 0.04))
    if margin is None:
        margin = gap
    rows = (len(cards) + cols - 1) // cols
    grid_w = cols * cw + gap * (cols - 1) + margin * 2
    grid_h = rows * ch + gap * (rows - 1) + margin * 2

    grid_frames = []
    for fi in range(n_frames):
        canvas = Image.new("RGBA", (grid_w, grid_h), (0, 0, 0, 0))
        for ci in range(len(cards)):
            cell = per_card[ci][fi].resize((cw, ch), Image.LANCZOS)
            r, col = divmod(ci, cols)
            canvas.alpha_composite(cell, (margin + col * (cw + gap), margin + r * (ch + gap)))
        grid_frames.append(canvas)

    # disposal=1: the transparent border is constant across crossfade frames,
    # so leaving previous pixels is correct and avoids Pillow's disposal=2 bug.
    _save_transparent_gif(grid_frames, durs, out_path, grid_w, disposal=1)
    return out_path
    return path


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--free-spins", default="{{FREE_SPINS}}")
    ap.add_argument("--width", type=int, default=300, help="GIF width in px (default 300)")
    ap.add_argument("--only", help="one suit only (hearts/diamonds/clubs/spades)")
    ap.add_argument("--game", default="", help="path to a slot-game image to drop into the card well")
    ap.add_argument("--out", default=str(R.HERE / "out"))
    a = ap.parse_args()
    out_dir = Path(a.out); out_dir.mkdir(parents=True, exist_ok=True)
    game_uri = R.img_data_uri(a.game) if a.game else ""
    if a.game and not game_uri:
        sys.exit(f"could not read --game image: {a.game}")
    names = [s[0] for s in R.SUITS]
    todo = [names.index(a.only)] if a.only else range(len(R.SUITS))
    for idx in todo:
        p = make_one(idx, a.free_spins, a.width, out_dir, game_uri)
        print(f"  {p.name}  ({p.stat().st_size // 1024} KB, {len(flip_frames())} frames)")
    print(f"\nDone. Free spins = {a.free_spins!r}, width {a.width}px.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
