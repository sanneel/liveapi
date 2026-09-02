#!/usr/bin/env python3
"""
Wrap a content-page blob in a doctype shell so it opens in a browser.

The blob in this folder is what gets PASTED into the backoffice rich-text
field: style + div + script, no <html>/<head>. That pastes correctly but
opens in quirks mode as a file, which changes box sizing. This adds the
shell for local viewing and nothing else -- the blob stays the source of
truth, so the preview can never drift from what ships.

  python preview.py giro_ganador_diario.html            # as configured
  python preview.py giro_ganador_diario.html --mock     # force simulation
  python preview.py giro_ganador_diario.html -o /tmp/p.html
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

SHELL = """<!doctype html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="theme-color" content="#08090B">
<title>{title}</title>
<style>html,body{{margin:0;background:#08090B}}
body{{padding:24px 16px;display:grid;place-items:start center}}
.wrap{{width:100%;max-width:1120px}}</style>
</head>
<body>
<div class="wrap">
{blob}
</div>
</body>
</html>
"""


def main() -> int:
    ap = argparse.ArgumentParser(description="Wrap a content blob for local preview.")
    ap.add_argument("blob", help="content page HTML blob in this folder")
    ap.add_argument("--mock", action="store_true", help='force data-mock="1"')
    ap.add_argument("-o", "--out", help="output path (default: <blob>.preview.html)")
    args = ap.parse_args()

    src = Path(args.blob)
    if not src.is_file():
        print(f"No such file: {src}", file=sys.stderr)
        return 1
    blob = src.read_text(encoding="utf-8")

    if args.mock:
        new, n = re.subn(r'data-mock="0"', 'data-mock="1"', blob, count=1)
        if n == 0:
            print('Could not find data-mock="0" to flip.', file=sys.stderr)
            return 1
        blob = new

    title = "Preview"
    m = re.search(r"<h1[^>]*>(.*?)</h1>", blob, re.S)
    if m:
        title = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", m.group(1))).strip() or title

    out = Path(args.out) if args.out else src.with_suffix(".preview.html")
    out.write_text(SHELL.format(title=title, blob=blob), encoding="utf-8")
    print(f"{out}  ({'mock forced' if args.mock else 'as configured'})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
