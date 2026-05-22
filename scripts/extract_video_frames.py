"""Extract a few frames from a video file using whatever library is available."""

import sys
from pathlib import Path


def main(src: str, out_dir: str, n_frames: int = 6) -> None:
    src_path = Path(src)
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)

    # Prefer imageio if installed
    try:
        import imageio.v3 as iio
    except ImportError:
        try:
            import imageio as iio
        except ImportError:
            print("no imageio", file=sys.stderr)
            sys.exit(2)

    try:
        meta = iio.immeta(src_path)
        print("meta:", meta)
    except Exception as e:
        print(f"meta failed: {e}")

    frames = []
    try:
        for i, frame in enumerate(iio.imiter(src_path)):
            frames.append(frame)
    except Exception as e:
        print(f"iter failed: {e}", file=sys.stderr)
        sys.exit(3)

    total = len(frames)
    if total == 0:
        print("no frames", file=sys.stderr)
        sys.exit(4)
    print(f"total frames: {total}")

    step = max(1, total // n_frames)
    saved = 0
    for i in range(0, total, step):
        if saved >= n_frames:
            break
        path = out / f"frame_{saved:02d}.png"
        iio.imwrite(path, frames[i])
        print(f"wrote {path} (source idx {i})")
        saved += 1


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2], int(sys.argv[3]) if len(sys.argv) > 3 else 6)
