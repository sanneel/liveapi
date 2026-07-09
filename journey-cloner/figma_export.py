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
CACHE_DIR = Path(__file__).resolve().parent / "figma_cache"

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
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            return r.read()
    except urllib.error.HTTPError as e:
        if e.code == 429:
            ra = e.headers.get("Retry-After", "?")
            sys.exit(f"Figma rate-limited (429). The full-file fetch is heavy; wait ~{ra}s "
                     f"then run once with --refresh to rebuild the cache. After that, runs reuse "
                     f"figma_cache/ and won't refetch.")
        raise


def get_json(url: str) -> dict:
    return json.loads(_get(url))


def load_doc(key: str, refresh: bool = False) -> dict:
    """The /v1/files tree is huge (146k nodes) and rate-limited; cache it to
    disk and reuse it. Only --refresh (or a missing cache) re-fetches."""
    CACHE_DIR.mkdir(exist_ok=True)
    cf = CACHE_DIR / f"{key}.json"
    if cf.exists() and not refresh:
        return json.loads(cf.read_text(encoding="utf-8"))
    raw = _get(f"{API}/files/{key}")
    cf.write_bytes(raw)
    return json.loads(raw)


def walk(node, page=None, acc=None):
    """Yield (node, page_name) for every node with a bounding box."""
    acc = [] if acc is None else acc
    bb = node.get("absoluteBoundingBox")
    if bb:
        acc.append((node, page))
    for ch in node.get("children", []) or []:
        walk(ch, page, acc)
    return acc


def load_nodes(key: str, page_filter: str | None, refresh: bool = False):
    doc = load_doc(key, refresh)["document"]
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


def cmd_inspect(key, page, game="", refresh=False):
    nodes = load_nodes(key, page, refresh)
    if game.strip():  # restrict to the column+row vicinity of one game
        nodes = _near_game(nodes, game)
    print(f"{len(nodes)} nodes with bounds")
    try:
        for n, pg in nodes:
            bb = n["absoluteBoundingBox"]
            w, h = round(bb["width"]), round(bb["height"])
            slot = slot_of(n)
            t = n.get("type")
            if slot or t == "TEXT":
                tag = f"  <{slot}>" if slot else ""
                print(f"  [{pg}] {t:<9} {w}x{h:<6} y={round(bb['y'])} x={round(bb['x'])}  {text_value(n)[:38]!r}{tag}  id={n['id']}")
    except BrokenPipeError:
        pass
    return 0


def _near_game(nodes, game):
    """Keep only nodes in the same column+row as the named game band."""
    texts = [(n, pg) for n, pg in nodes if n.get("type") == "TEXT" and game.lower() in text_value(n).lower()]
    if not texts:
        return nodes
    g = texts[0][0]["absoluteBoundingBox"]
    gl, gr, gy = g["x"], g["x"] + g["width"], g["y"]
    out = []
    for n, pg in nodes:
        b = n["absoluteBoundingBox"]
        if b["x"] < gr and b["x"] + b["width"] > gl and gy - 20 < b["y"] < gy + 1200:
            out.append((n, pg))
    return out


def cmd_export(key, page, game, scale, out, refresh=False):
    # If we already know this game's slot node ids, render via /images only and
    # skip the rate-limited /files tree fetch entirely.
    cached = _load_all_slots(key).get(_slug(game))
    if cached and not refresh:
        print(f"  using cached slot ids for {game!r}: {cached}")
        return render_ids(key, cached, scale, out, game)
    nodes = load_nodes(key, page, refresh)
    # game bands = TEXT nodes; sort by vertical position
    texts = sorted([(n, pg) for n, pg in nodes if n.get("type") == "TEXT"],
                   key=lambda x: x[0]["absoluteBoundingBox"]["y"])
    gi = next((i for i, (n, _) in enumerate(texts)
               if game.lower() in text_value(n).lower()), None)
    if gi is None:
        sys.exit(f"game {game!r} not found as a text node. Run --inspect to see names.")
    gnode, gpage = texts[gi]
    gb = gnode["absoluteBoundingBox"]
    g_y, col_l, col_r = gb["y"], gb["x"], gb["x"] + gb["width"]

    def x_overlaps(n):  # same column as the game band (months are side-by-side)
        b = n["absoluteBoundingBox"]
        return b["x"] < col_r and b["x"] + b["width"] > col_l

    # next game band *in the same column* below this one bounds the row window.
    # Only band-sized TEXT counts (height >= 100) — ignore small labels like the
    # "nuevo" badge or "$500" tier chips that sit in the image row.
    later = [t["absoluteBoundingBox"]["y"] for t, pg in texts
             if pg == gpage and t is not gnode and x_overlaps(t)
             and t["absoluteBoundingBox"]["height"] >= 100
             and t["absoluteBoundingBox"]["y"] > g_y + 50]
    next_y = min(later) if later else g_y + 2000

    # slot images in this column+row, nearest-below first
    cands = sorted(
        [n for n, pg in nodes if pg == gpage and slot_of(n) and x_overlaps(n)
         and g_y < n["absoluteBoundingBox"]["y"] < next_y],
        key=lambda n: n["absoluteBoundingBox"]["y"])
    picks = {}
    for n in cands:
        slot = slot_of(n)
        picks.setdefault(slot, n["id"])
    print(f"  game band {gnode.get('id')} col x[{round(col_l)},{round(col_r)}] y[{round(g_y)},{round(next_y)}]")
    for slot, nid in picks.items():
        print(f"    slot {slot} <- {nid}")
    if not picks:
        sys.exit("no slot-sized images found under that game. Run --inspect.")
    _save_slots(key, game, picks)   # remember ids so we never need the tree again
    return render_ids(key, picks, scale, out, game)


def export_game(key, game, page=None, scale="1", out="figma_out", refresh=False):
    """Programmatic entry point: export one game's slots and return {slot: Path}.

    Used by the GOW generator to embed campaign.png into the console script.
    Raises SystemExit (with a friendly message) on the same failures the CLI hits
    — missing token, game not found, rate-limited /files, no slot images."""
    cmd_export(key, page, game, scale, out, refresh)
    dest = Path(out) / _slug(game)
    return {p.stem: p for p in sorted(dest.glob("*.png"))}


def _slug(game):
    return re.sub(r"[^a-z0-9]+", "_", game.lower()).strip("_")


def _slots_path(key):
    CACHE_DIR.mkdir(exist_ok=True)
    return CACHE_DIR / f"slots_{key}.json"


def _load_all_slots(key):
    p = _slots_path(key)
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


def _save_slots(key, game, picks):
    d = _load_all_slots(key)
    d[_slug(game)] = picks
    _slots_path(key).write_text(json.dumps(d, indent=1), encoding="utf-8")


def render_ids(key, picks, scale, out, game):
    """Render specific node ids to PNG via /v1/images (no /files call)."""
    ids = ",".join(picks.values())
    imgs = get_json(f"{API}/images/{key}?ids={ids}&format=png&scale={scale}")["images"]
    dest = Path(out) / _slug(game)
    dest.mkdir(parents=True, exist_ok=True)
    for slot, nid in picks.items():
        url = imgs.get(nid)
        if not url:
            print(f"  WARN no render url for {slot}"); continue
        (dest / f"{slot}.png").write_bytes(urllib.request.urlopen(url, timeout=60).read())
        print(f"  saved {dest/slot}.png")
    print(f"\nDone: {game}  -> {dest}")
    print("  (campaign.png is the 360x330 image — reuse it for nc_icon + promo too)")
    return 0


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--key", required=True, help="Figma file key (figma.com/design/<KEY>/...)")
    p.add_argument("--page", default=None, help="restrict to a page whose name contains this")
    p.add_argument("--game", default=None, help="game name to export (text band)")
    p.add_argument("--scale", default="1")
    p.add_argument("--out", default="figma_out")
    p.add_argument("--inspect", action="store_true")
    p.add_argument("--refresh", action="store_true", help="re-fetch the file tree (rebuild figma_cache)")
    p.add_argument("--ids", default=None,
                   help="render exact node ids, no /files call: 'popup_bg=1078:2286,email_hero=1078:2810,campaign=1078:2911'")
    a = p.parse_args()
    if a.ids:
        if not a.game:
            sys.exit("--ids needs --game NAME (used as the output folder + cache key).")
        picks = {}
        for kv in a.ids.split(","):
            if "=" not in kv:
                continue
            slot, nid = kv.split("=", 1)
            nid = nid.strip()
            # Figma layer URLs write node ids with a dash (node-id=1078-2286);
            # the API wants a colon (1078:2286). Accept either so ids can be
            # pasted straight from the browser URL.
            nid = re.sub(r"^(\d+)-(\d+)$", r"\1:\2", nid)
            picks[slot.strip()] = nid
        if not picks:
            sys.exit("could not parse --ids (use slot=nodeId,slot=nodeId)")
        _save_slots(a.key, a.game, picks)  # seed the cache so plain --game works next time
        return render_ids(a.key, picks, a.scale, a.out, a.game)
    if a.inspect:
        return cmd_inspect(a.key, a.page, a.game or "", a.refresh)
    if not a.game:
        sys.exit("pass --game \"NAME\" to export, or --inspect to see the tree.")
    return cmd_export(a.key, a.page, a.game, a.scale, a.out, a.refresh)


if __name__ == "__main__":
    raise SystemExit(main())
