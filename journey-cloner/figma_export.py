#!/usr/bin/env python3
"""Export the GOW image slots for one game straight out of Figma.

Run this where api.figma.com is reachable (your machine / the admin host) — NOT
the sandbox, whose network policy blocks Figma. Stdlib only.

Layout assumed (from the GOW Figma): a month column with a game band, and below
each game a row of slot images sized:
    474x256 -> popup background
    360x330 -> NC icon  (also reused for promo + GOW campaign photo)
    600x400 -> email hero
The optional "slider" card is captured too when present.

Auth:  export FIGMA_TOKEN=figd_...   (read-only File-content scope)

Inspect the file tree (do this first if matching misbehaves):
    python figma_export.py --key <FILE_KEY> --inspect [--page "GAME OF THE WEEK (JULY)"]

Export one game's slots as PNG into ./figma_out/<game>/:
    python figma_export.py --key <FILE_KEY> --game "SPIN & SCORE MEGAWAYS" \
        [--page "..."] [--scale 1] [--out figma_out]
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.request
from pathlib import Path

API = "https://api.figma.com/v1"

# (w, h) -> slot name.  360x330 is exported once as 'campaign' and reused for
# nc_icon + promo by the GOW generator (same image, three uses).
SLOT_SIZES = {
    (474, 256): "popup_bg",
    (360, 330): "campaign",   # == nc_icon == promo image
    (600, 400): "email_hero",
}
TOL = 3  # px tolerance on slot size matching


def _get(url: str) -> bytes:
    tok = os.environ.get("FIGMA_TOKEN", "").strip()
    if not tok:
        sys.exit("FIGMA_TOKEN env var is not set (read-only File-content PAT).")
    req = urllib.request.Request(url, headers={"X-Figma-Token": tok})
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read()


def get_json(url: str) -> dict:
    return json.loads(_get(url))


def walk(node, page=None, acc=None):
    """Yield (node, page_name) for every node with a bounding box."""
    acc = [] if acc is None else acc
    bb = node.get("absoluteBoundingBox")
    if bb:
        acc.append((node, page))
    for ch in node.get("children", []) or []:
        walk(ch, page, acc)
    return acc


def load_nodes(key: str, page_filter: str | None):
    doc = get_json(f"{API}/files/{key}")["document"]
    nodes = []
    for pg in doc.get("children", []):
        if page_filter and page_filter.lower() not in (pg.get("name", "").lower()):
            continue
        nodes.extend(walk(pg, pg.get("name")))
    return nodes


def slot_of(node):
    bb = node["absoluteBoundingBox"]
    w, h = round(bb["width"]), round(bb["height"])
    for (sw, sh), name in SLOT_SIZES.items():
        if abs(w - sw) <= TOL and abs(h - sh) <= TOL:
            return name
    return None


def text_value(node):
    return (node.get("characters") or node.get("name") or "").strip()


def cmd_inspect(key, page):
    nodes = load_nodes(key, page)
    print(f"{len(nodes)} nodes with bounds")
    for n, pg in nodes:
        bb = n["absoluteBoundingBox"]
        w, h = round(bb["width"]), round(bb["height"])
        slot = slot_of(n)
        tag = f"  <{slot}>" if slot else ""
        t = n.get("type")
        label = text_value(n)[:40]
        if slot or t == "TEXT":
            print(f"  [{pg}] {t:<9} {w}x{h:<5} y={round(bb['y'])}  {label!r}{tag}  id={n['id']}")
    return 0


def cmd_export(key, page, game, scale, out):
    nodes = load_nodes(key, page)
    # game bands = TEXT nodes; sort by vertical position
    texts = sorted([(n, pg) for n, pg in nodes if n.get("type") == "TEXT"],
                   key=lambda x: x[0]["absoluteBoundingBox"]["y"])
    gi = next((i for i, (n, _) in enumerate(texts)
               if game.lower() in text_value(n).lower()), None)
    if gi is None:
        sys.exit(f"game {game!r} not found as a text node. Run --inspect to see names.")
    gnode, gpage = texts[gi]
    g_y = gnode["absoluteBoundingBox"]["y"]
    # next text band on the same page that sits below this one -> window end
    next_y = min([t["absoluteBoundingBox"]["y"] for t, pg in texts[gi + 1:]
                  if pg == gpage and t["absoluteBoundingBox"]["y"] > g_y + 5] or [1e9])

    picks = {}
    for n, pg in nodes:
        if pg != gpage:
            continue
        slot = slot_of(n)
        if not slot:
            continue
        y = n["absoluteBoundingBox"]["y"]
        if g_y < y < next_y and slot not in picks:
            picks[slot] = n["id"]
    if not picks:
        sys.exit("no slot-sized images found under that game. Run --inspect.")

    ids = ",".join(picks.values())
    imgs = get_json(f"{API}/images/{key}?ids={ids}&format=png&scale={scale}")["images"]
    slug = re.sub(r"[^a-z0-9]+", "_", game.lower()).strip("_")
    dest = Path(out) / slug
    dest.mkdir(parents=True, exist_ok=True)
    for slot, nid in picks.items():
        url = imgs.get(nid)
        if not url:
            print(f"  WARN no render url for {slot}"); continue
        (dest / f"{slot}.png").write_bytes(urllib.request.urlopen(url, timeout=60).read())
        print(f"  saved {dest/slot}.png")
    print(f"\nDone: {game}  -> {dest}")
    print("  (campaign.png is the 360x330 image — reuse it for nc_icon + promo too)")
    missing = set(SLOT_SIZES.values()) - set(picks)
    if missing:
        print(f"  NOTE missing slots: {sorted(missing)} — check sizes in --inspect")
    return 0


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--key", required=True, help="Figma file key (figma.com/design/<KEY>/...)")
    p.add_argument("--page", default=None, help="restrict to a page whose name contains this")
    p.add_argument("--game", default=None, help="game name to export (text band)")
    p.add_argument("--scale", default="1")
    p.add_argument("--out", default="figma_out")
    p.add_argument("--inspect", action="store_true")
    a = p.parse_args()
    if a.inspect:
        return cmd_inspect(a.key, a.page)
    if not a.game:
        sys.exit("pass --game \"NAME\" to export, or --inspect to see the tree.")
    return cmd_export(a.key, a.page, a.game, a.scale, a.out)


if __name__ == "__main__":
    raise SystemExit(main())
