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
    W, H = 400, 584
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


def make_one(idx: int, free_spins: str, width: int, out_dir: Path) -> Path:
    from PIL import ImageEnhance
    front = render_face(R.single_html(idx, free_spins))
    back = render_face(R.single_back_html(idx))
    W, H = front.size
    th = int(round(width * H / W))
    # one shared 255-colour palette (index 255 reserved for transparency) so the
    # GIF has a single global colour table (avoids malformed per-frame palettes).
    both = Image.new("RGB", (W, H * 2))
    both.paste(front.convert("RGB"), (0, 0)); both.paste(back.convert("RGB"), (0, H))
    palette = both.resize((width, th * 2)).quantize(colors=255, method=Image.FASTOCTREE)

    frames, durs = [], []
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
        canvas = canvas.resize((width, th), Image.LANCZOS)
        p = _quant(canvas.convert("RGB"), palette)
        transparent = canvas.getchannel("A").point(lambda v: 255 if v < 128 else 0).convert("1")
        p.paste(TRANSP_IDX, (0, 0), transparent)
        frames.append(p)
        durs.append(dur)
    name, _, deposit, _ = R.SUITS[idx]
    dep = deposit.replace("$", "").replace(".", "")
    path = out_dir / f"card_{name}_{dep}_flip.gif"
    for fr in frames:
        fr.info["transparency"] = TRANSP_IDX
    frames[0].save(path, save_all=True, append_images=frames[1:], duration=durs, loop=0,
                   transparency=TRANSP_IDX, disposal=2)
    return path


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--free-spins", default="{{FREE_SPINS}}")
    ap.add_argument("--width", type=int, default=300, help="GIF width in px (default 300)")
    ap.add_argument("--only", help="one suit only (hearts/diamonds/clubs/spades)")
    ap.add_argument("--out", default=str(R.HERE / "out"))
    a = ap.parse_args()
    out_dir = Path(a.out); out_dir.mkdir(parents=True, exist_ok=True)
    names = [s[0] for s in R.SUITS]
    todo = [names.index(a.only)] if a.only else range(len(R.SUITS))
    for idx in todo:
        p = make_one(idx, a.free_spins, a.width, out_dir)
        print(f"  {p.name}  ({p.stat().st_size // 1024} KB, {len(flip_frames())} frames)")
    print(f"\nDone. Free spins = {a.free_spins!r}, width {a.width}px.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
