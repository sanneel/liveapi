#!/usr/bin/env python3
"""Render a planner MODE 1 journey design into PNG boards.

The planner's MODE 1 reply carries a `{"diagram": {...}}` JSON block alongside
its outline. This script turns that block into pictures: one card per activity
with an icon, arrows for the flow, a lane per branch, and the flags printed
under each journey. The model never sees the images — it only emits the data,
the operator looks at the PNGs.

Usage:
    python render_journey_design.py design.json --out out/ --per-image 2
    cat design.json | python render_journey_design.py - --out out/

Writes <name>_1.png … and prints a JSON manifest on stdout:
    {"ok": true, "images": [{"file": "...", "journeys": ["..."], "w":…, "h":…}]}

Input shape (extra keys are ignored, so the whole planner reply can be piped
in — the `diagram` object is picked out of it):

    {"diagram": {
       "campaign": "Spin the Wheel — 3 Years",
       "brand": "JBCL", "window": "01–31 Jul 2025",
       "journeys": [
         {"name": "Wheel prize — Free Spins",
          "note": "one line of context",
          "flags": ["⚠ empty prize added", "❓ bet amount assumed"],
          "nodes": [
            {"type": "wheel",     "label": "Fortune Wheel", "detail": "1 spin"},
            {"type": "promotion", "label": "Promotion",     "detail": "PromoLobby"},
            {"type": "freespins", "label": "100 free spins",
             "detail": "La Gran Copa · 20 CLP",
             "branches": {"Declined": [{"type": "end", "label": "Drop"}]}},
            {"type": "end", "label": "End"}]}]}}

Icons: an activity type draws its built-in glyph. Drop a PNG at
journey-planner/icons/<type>.png (square, transparent) and that file is used
instead — that is how hand-made icons get added without touching this file.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError:                                          # pragma: no cover
    sys.exit("pillow is required: pip install pillow")


class BoardWriteError(OSError):
    """The boards could not be written (permissions, full disk, bad path)."""


SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
ICON_DIR = SCRIPT_DIR / "icons"
FONT_DIR = REPO_ROOT / "fonts"

# ── canvas geometry ────────────────────────────────────────────────────────
SCALE = 2                    # draw at 2x and downsample — cheap antialiasing
WIDTH = 1560                 # logical board width
PAD = 44                     # board margin
NODE_W, NODE_H = 196, 132
GAP_X, GAP_Y = 46, 30        # gap between cards (arrows live in GAP_X)
BRANCH_INDENT = 34
MIN_COLS = 6                 # narrowest board — keeps short journeys looking like boards
HEADER_H = 96
TITLE_H = 52
FLAG_H = 26

# ── palette ────────────────────────────────────────────────────────────────
BG = (244, 246, 250)
INK = (23, 28, 38)
MUTED = (108, 118, 135)
FAINT = (150, 159, 175)
CARD = (255, 255, 255)
BORDER = (222, 227, 236)
HEADER_BG = (23, 28, 38)
ARROW = (166, 175, 190)
LANE_BG = (238, 241, 247)

FLAG_COLORS = {
    "warn": ((183, 121, 31), (255, 247, 229)),
    "ask": ((43, 108, 176), (235, 244, 255)),
    "block": ((192, 57, 43), (253, 235, 233)),
    "info": (MUTED, (240, 242, 246)),
}

# Every composable activity family, its accent colour and the glyph it draws.
# `aliases` maps what the planner (or a brief) may call it onto the family, so
# the renderer never falls back to a blank chip for a known activity.
FAMILIES: dict[str, dict] = {
    "source":       {"color": (91, 103, 128),  "glyph": "people",  "title": "Entry"},
    "segment":      {"color": (91, 103, 128),  "glyph": "people",  "title": "Segment"},
    "api":          {"color": (91, 103, 128),  "glyph": "cloud",   "title": "API entry"},
    "csv":          {"color": (91, 103, 128),  "glyph": "sheet",   "title": "CSV"},
    "registration": {"color": (91, 103, 128),  "glyph": "person_plus", "title": "Registration"},
    "promocode":    {"color": (124, 92, 196),  "glyph": "tag",     "title": "Promo code"},
    "promotion":    {"color": (233, 116, 40),  "glyph": "gift",    "title": "Promotion"},
    "promo_page":   {"color": (233, 116, 40),  "glyph": "window",  "title": "Promo page"},
    "wheel":        {"color": (214, 62, 122),  "glyph": "wheel",   "title": "Fortune wheel"},
    "scratch":      {"color": (214, 62, 122),  "glyph": "scratch", "title": "Scratch card"},
    "deposit":      {"color": (32, 148, 122),  "glyph": "wallet",  "title": "Deposit"},
    "freespins":    {"color": (52, 120, 214),  "glyph": "spin",    "title": "Free spins"},
    "casino_bonus": {"color": (52, 120, 214),  "glyph": "coins",   "title": "Casino bonus"},
    "freebet":      {"color": (26, 152, 92),   "glyph": "ticket",  "title": "Free bet"},
    "sport":        {"color": (26, 152, 92),   "glyph": "ball",    "title": "Sport"},
    "gift":         {"color": (196, 88, 152),  "glyph": "box",     "title": "Physical gift"},
    "wait":         {"color": (140, 148, 165), "glyph": "clock",   "title": "Wait"},
    "notification": {"color": (222, 168, 42),  "glyph": "bell",    "title": "Notification"},
    "email":        {"color": (222, 168, 42),  "glyph": "mail",    "title": "Email"},
    "sms":          {"color": (222, 168, 42),  "glyph": "chat",    "title": "SMS"},
    "comms":        {"color": (222, 168, 42),  "glyph": "bell",    "title": "Comms"},
    "drip":         {"color": (124, 92, 196),  "glyph": "fork",    "title": "Choosable flow"},
    "split":        {"color": (124, 92, 196),  "glyph": "fork",    "title": "Split"},
    "connector":    {"color": (91, 103, 128),  "glyph": "link",    "title": "Connector"},
    "end":          {"color": (120, 128, 145), "glyph": "flag",    "title": "End"},
    "unknown":      {"color": (150, 159, 175), "glyph": "dot",     "title": "Activity"},
}

ALIASES = {
    "external_system_source": "api", "external_source": "api", "entry": "source",
    "segment_source": "segment", "player_segment": "segment", "csv_source": "csv",
    "registration_source": "registration", "signup": "registration",
    "promo_code": "promocode", "promocode_source": "promocode", "code": "promocode",
    "promotion_activity": "promotion", "promo": "promotion", "offer": "promotion",
    "promopage": "promo_page", "page": "promo_page", "landing": "promo_page",
    "randomizer": "wheel", "fortune_wheel": "wheel", "fortunewheel": "wheel",
    "wof": "wheel", "scratch_card": "scratch", "scratchcard": "scratch",
    "deposit_activity": "deposit", "deposit_condition": "deposit",
    "freespin": "freespins", "freespin_bonus": "freespins", "free_spins": "freespins",
    "spins": "freespins", "fs": "freespins",
    "casino_bonus_v2": "casino_bonus", "bonus": "casino_bonus",
    "deposit_match": "casino_bonus", "casinobonus": "casino_bonus",
    "free_bet": "freebet", "sport_freebet": "freebet", "sportfreebet": "freebet",
    "sport_bonus": "sport", "sportsbook": "sport",
    "physical_gift": "gift", "hamper": "gift", "prize": "gift",
    "wait_interval": "wait", "wait_date": "wait", "delay": "wait", "timer": "wait",
    "notification_center": "notification", "nc": "notification", "popup": "notification",
    "pop_up": "notification", "push": "notification", "onsite": "notification",
    "email_message": "email", "mail": "email", "sms_message": "sms",
    "campaign_connector": "connector", "connector_activity": "connector",
    "choosable": "drip", "choosable_flow": "drip", "drip_flow": "drip",
    "ab_split": "split", "branch": "split",
    "end_of_journey": "end", "terminal": "end", "finish": "end", "exit": "end",
}


def family(node_type: str) -> tuple[str, dict]:
    """Resolve a node `type` to (family key, family spec). Unknown types get the
    neutral chip rather than crashing — a picture with one grey card still tells
    the operator more than a traceback."""
    key = re.sub(r"[^a-z0-9]+", "_", str(node_type or "").strip().lower()).strip("_")
    if key in FAMILIES:
        return key, FAMILIES[key]
    if key in ALIASES:
        return ALIASES[key], FAMILIES[ALIASES[key]]
    # Last chance: match what the name STARTS with ("wait_for_deposit" is a wait,
    # not a deposit), then any substring ("dextra_email", "send_notification").
    # Longest candidate first either way, so "casino_bonus_x" beats "bonus".
    candidates = sorted((c for c in (*FAMILIES, *ALIASES) if c), key=len, reverse=True)
    for test in (str.startswith, str.__contains__):
        for cand in candidates:
            if test(key, cand):
                resolved = ALIASES.get(cand, cand)
                return resolved, FAMILIES[resolved]
    return "unknown", FAMILIES["unknown"]


# ── fonts ──────────────────────────────────────────────────────────────────
def _font(*names: str):
    for name in names:
        for base in (FONT_DIR, Path("/usr/share/fonts/truetype/dejavu"),
                     Path("/usr/share/fonts/truetype/noto")):
            path = base / name
            if path.exists():
                return str(path)
    return None


_REG = _font("RobotoCondensed-Regular.ttf", "DejaVuSans.ttf")
_BOLD = _font("RobotoCondensed-ExtraBold.ttf", "DejaVuSans-Bold.ttf")


def load_font(size: int, bold: bool = False):
    path = _BOLD if bold else _REG
    try:
        return ImageFont.truetype(path, size * SCALE) if path else ImageFont.load_default()
    except OSError:                                           # pragma: no cover
        return ImageFont.load_default()


FONTS = {}


def f(size: int, bold: bool = False):
    key = (size, bold)
    if key not in FONTS:
        FONTS[key] = load_font(size, bold)
    return FONTS[key]


# ── low-level drawing helpers (all in logical px; SCALE applied here) ──────
def S(v):
    if isinstance(v, (tuple, list)):
        return tuple(int(round(x * SCALE)) for x in v)
    return int(round(v * SCALE))


def rrect(d, box, radius, fill=None, outline=None, width=1):
    d.rounded_rectangle(S(box), radius=S(radius), fill=fill, outline=outline,
                        width=max(1, S(width)))


# Roboto Condensed has no glyph for the arrows and emoji a planner reply is full
# of — they render as tofu boxes. Swap them for shapes the font does have.
_SUBS = {
    "→": "->", "⟶": "->", "⇒": "=>", "←": "<-", "↳": "->", "⤷": "->",
    "•": "·", "―": "—", "✓": "ok", "✔": "ok", "✗": "x", "×": "x",
    "⚠": "!", "❓": "?", "⛔": "x", "🎁": "", "🎡": "", "💰": "", "🎰": "",
}


def sanitize(s) -> str:
    out = str(s if s is not None else "")
    for bad, good in _SUBS.items():
        if bad in out:
            out = out.replace(bad, good)
    return out


def text(d, xy, s, size=13, bold=False, fill=INK, anchor="la"):
    d.text(S(xy), sanitize(s), font=f(size, bold), fill=fill, anchor=anchor)


def text_w(s, size=13, bold=False) -> float:
    """Logical width of a string."""
    return f(size, bold).getlength(sanitize(s)) / SCALE


def ellipsize(s, max_w, size=13, bold=False) -> str:
    s = sanitize(s)
    if text_w(s, size, bold) <= max_w:
        return s
    while s and text_w(s + "…", size, bold) > max_w:
        s = s[:-1]
    return (s.rstrip() + "…") if s else ""


def wrap(s, max_w, size=13, bold=False, max_lines=2) -> list[str]:
    s = sanitize(s)
    words, lines, cur = s.split(), [], ""
    for word in words:
        probe = f"{cur} {word}".strip()
        if text_w(probe, size, bold) <= max_w or not cur:
            cur = probe
        else:
            lines.append(cur)
            cur = word
            if len(lines) == max_lines:
                break
    if cur and len(lines) < max_lines:
        lines.append(cur)
    if len(lines) == max_lines and words:
        joined = " ".join(lines)
        if text_w(joined, size, bold) < text_w(str(s), size, bold):
            lines[-1] = ellipsize(lines[-1] + " …", max_w, size, bold)
    return lines or [""]


def arrow_right(d, x1, x2, y, color=ARROW):
    """Horizontal connector with a solid head at x2."""
    head = 9
    d.line([S((x1, y)), S((x2 - head + 2, y))], fill=color, width=max(1, S(1.6)))
    d.polygon([S((x2, y)), S((x2 - head, y - 5)), S((x2 - head, y + 5))], fill=color)


def arrow_down(d, x, y1, y2, color=ARROW):
    head = 9
    d.line([S((x, y1)), S((x, y2 - head + 2))], fill=color, width=max(1, S(1.6)))
    d.polygon([S((x, y2)), S((x - 5, y2 - head)), S((x + 5, y2 - head))], fill=color)


def elbow_down(d, x, y1, y2, x2, color=ARROW):
    """Down out of a card, then right into a branch lane's first card."""
    d.line([S((x, y1)), S((x, y2))], fill=color, width=max(1, S(1.6)))
    arrow_right(d, x, x2, y2, color)


# ── icon glyphs ────────────────────────────────────────────────────────────
def _icon_file(fam: str) -> Path | None:
    for ext in (".png", ".webp"):
        path = ICON_DIR / f"{fam}{ext}"
        if path.exists():
            return path
    return None


_ICON_CACHE: dict[tuple[str, int], Image.Image] = {}


def paste_icon_file(img, path: Path, box_x, box_y, size, fam):
    key = (str(path), S(size))
    if key not in _ICON_CACHE:
        icon = Image.open(path).convert("RGBA")
        icon.thumbnail((S(size), S(size)), Image.LANCZOS)
        _ICON_CACHE[key] = icon
    icon = _ICON_CACHE[key]
    x = S(box_x) + (S(size) - icon.width) // 2
    y = S(box_y) + (S(size) - icon.height) // 2
    img.alpha_composite(icon, (x, y))


def draw_glyph(d, glyph, cx, cy, r, color, bg=CARD):
    """Built-in vector glyph, centred on (cx, cy) inside radius r. Deliberately
    simple line art: it reads at 40px and stays recognisable next to a label."""
    lw = max(1, S(2.0))
    c = color

    def box(x1, y1, x2, y2, radius=2, fill=None, outline=c, w=2.0):
        d.rounded_rectangle(S((cx + x1, cy + y1, cx + x2, cy + y2)), radius=S(radius),
                            fill=fill, outline=outline, width=max(1, S(w)))

    def line(x1, y1, x2, y2, w=2.0):
        d.line([S((cx + x1, cy + y1)), S((cx + x2, cy + y2))], fill=c, width=max(1, S(w)))

    def circle(x, y, rad, fill=None, outline=c, w=2.0):
        d.ellipse(S((cx + x - rad, cy + y - rad, cx + x + rad, cy + y + rad)),
                  fill=fill, outline=outline, width=max(1, S(w)))

    def poly(points, fill=c):
        d.polygon([S((cx + px, cy + py)) for px, py in points], fill=fill)

    if glyph == "gift":                     # promotion — wrapped gift
        box(-r, -r * .25, r, r * .85, radius=2)
        box(-r * 1.1, -r * .62, r * 1.1, -r * .22, radius=2)
        line(0, -r * .62, 0, r * .85)
        circle(-r * .42, -r * .78, r * .3, w=2.0)
        circle(r * .42, -r * .78, r * .3, w=2.0)
    elif glyph == "spin":                   # free spins — spinning arrow + star
        d.arc(S((cx - r, cy - r, cx + r, cy + r)), start=35, end=320, fill=c, width=lw)
        poly([(r * .92, -r * .5), (r * .34, -r * .34), (r * .74, r * .12)])
        poly([(0, -r * .42), (r * .16, -r * .06), (r * .5, -r * .02),
              (r * .22, r * .2), (r * .3, r * .55), (0, r * .34),
              (-r * .3, r * .55), (-r * .22, r * .2), (-r * .5, -r * .02),
              (-r * .16, -r * .06)])
    elif glyph == "wheel":                  # randomizer — wheel with spokes
        circle(0, 0, r, w=2.2)
        for i in range(8):
            import math
            a = math.pi / 4 * i
            line(math.cos(a) * r * .18, math.sin(a) * r * .18,
                 math.cos(a) * r * .94, math.sin(a) * r * .94, 1.6)
        circle(0, 0, r * .2, fill=c, outline=c)
        poly([(0, -r * 1.15), (-r * .22, -r * .78), (r * .22, -r * .78)])
    elif glyph == "scratch":                # scratch card — card + scratch marks
        box(-r, -r * .78, r, r * .78, radius=3)
        for i in (-1, 0, 1):
            line(-r * .55 + i * r * .1, r * .3 + i * r * .12,
                 r * .55 + i * .1, -r * .35 + i * r * .12, 1.6)
    elif glyph == "wallet":                 # deposit — wallet with a coin
        box(-r, -r * .62, r, r * .72, radius=3)
        line(-r, -r * .18, r, -r * .18)
        circle(r * .48, r * .26, r * .22, fill=c, outline=c)
    elif glyph == "coins":                  # casino bonus — coin stack with %
        for i, y in enumerate((r * .55, r * .1, -r * .35)):
            d.ellipse(S((cx - r * .82, cy + y - r * .26, cx + r * .82, cy + y + r * .26)),
                      fill=None, outline=c, width=lw)
        circle(-r * .3, -r * .38, r * .12, fill=c, outline=c)
        circle(r * .3, -r * .34, r * .12, fill=c, outline=c)
    elif glyph == "ticket":                 # freebet — ticket with a notch
        box(-r, -r * .55, r, r * .55, radius=3)
        circle(-r, 0, r * .2, fill=bg, outline=c, w=1.6)
        circle(r, 0, r * .2, fill=bg, outline=c, w=1.6)
        line(-r * .3, -r * .2, r * .45, -r * .2, 1.6)
        line(-r * .3, r * .18, r * .2, r * .18, 1.6)
    elif glyph == "ball":                   # sport — football
        circle(0, 0, r, w=2.2)
        poly([(0, -r * .5), (r * .48, -r * .16), (r * .3, r * .42),
              (-r * .3, r * .42), (-r * .48, -r * .16)])
    elif glyph == "box":                    # physical gift — parcel
        box(-r, -r * .5, r, r * .8, radius=2)
        line(-r, -r * .12, r, -r * .12)
        line(0, -r * .5, 0, -r * .12)
        poly([(-r * .2, -r * .95), (r * .2, -r * .95), (0, -r * .5)])
    elif glyph == "clock":                  # wait
        circle(0, 0, r, w=2.2)
        line(0, 0, 0, -r * .55, 2.2)
        line(0, 0, r * .42, r * .12, 2.2)
    elif glyph == "bell":                   # notification centre / pop-up
        d.pieslice(S((cx - r * .62, cy - r * .95, cx + r * .62, cy + r * .25)),
                   start=180, end=360, fill=None, outline=c, width=lw)
        line(-r * .62, -r * .2, -r * .62, r * .3)
        line(r * .62, -r * .2, r * .62, r * .3)
        line(-r * .95, r * .34, r * .95, r * .34, 2.2)   # flared rim
        line(-r * .95, r * .34, -r * .62, r * .3, 1.6)
        line(r * .95, r * .34, r * .62, r * .3, 1.6)
        circle(0, r * .66, r * .18, fill=c, outline=c)   # clapper
    elif glyph == "mail":                   # email
        box(-r, -r * .62, r, r * .62, radius=2)
        line(-r, -r * .62, 0, r * .02)
        line(r, -r * .62, 0, r * .02)
    elif glyph == "chat":                   # SMS
        box(-r, -r * .7, r, r * .38, radius=4)
        poly([(-r * .5, r * .38), (-r * .12, r * .38), (-r * .5, r * .86)])
    elif glyph == "people":                 # segment
        circle(-r * .38, -r * .3, r * .3, w=2.0)
        d.pieslice(S((cx - r * .92, cy - r * .04, cx + r * .16, cy + r * .95)),
                   start=180, end=360, fill=None, outline=c, width=lw)
        circle(r * .5, -r * .16, r * .24, w=1.8)
        d.pieslice(S((cx + r * .06, cy + r * .1, cx + r * .96, cy + r * .9)),
                   start=180, end=360, fill=None, outline=c, width=max(1, S(1.6)))
    elif glyph == "person_plus":            # registration
        circle(-r * .2, -r * .38, r * .3, w=2.0)
        d.pieslice(S((cx - r * .82, cy - r * .06, cx + r * .42, cy + r * .95)),
                   start=180, end=360, fill=None, outline=c, width=lw)
        line(r * .45, -r * .5, r * .95, -r * .5)
        line(r * .7, -r * .78, r * .7, -r * .22)
    elif glyph == "cloud":                  # api / external system entry
        circle(-r * .48, r * .1, r * .42, w=2.0)
        circle(r * .12, -r * .22, r * .56, w=2.0)
        circle(r * .62, r * .14, r * .38, w=2.0)
        d.rectangle(S((cx - r * .5, cy + r * .06, cx + r * .62, cy + r * .5)), fill=bg)
        line(-r * .88, r * .5, r * .95, r * .5, 2.2)
    elif glyph == "sheet":                  # csv
        box(-r * .8, -r * .9, r * .8, r * .9, radius=2)
        line(-r * .8, -r * .3, r * .8, -r * .3, 1.6)
        line(-r * .8, r * .2, r * .8, r * .2, 1.6)
        line(0, -r * .9, 0, r * .9, 1.6)
    elif glyph == "tag":                    # promo code
        poly([(-r * .95, -r * .2), (r * .1, -r * .95), (r * .95, -r * .1),
              (-r * .1, r * .9)])
        circle(r * .35, -r * .35, r * .16, fill=bg, outline=bg)
    elif glyph == "window":                 # promo page
        box(-r, -r * .78, r, r * .78, radius=3)
        line(-r, -r * .4, r, -r * .4)
        circle(-r * .72, -r * .59, r * .1, fill=c, outline=c)
        circle(-r * .42, -r * .59, r * .1, fill=c, outline=c)
    elif glyph == "fork":                   # choosable flow / split
        circle(-r * .7, 0, r * .22, fill=c, outline=c)
        line(-r * .5, 0, r * .1, -r * .55)
        line(-r * .5, 0, r * .1, r * .55)
        circle(r * .38, -r * .62, r * .22, fill=c, outline=c)
        circle(r * .38, r * .62, r * .22, fill=c, outline=c)
    elif glyph == "link":                   # connector
        d.arc(S((cx - r, cy - r * .5, cx, cy + r * .5)), start=90, end=270, fill=c, width=lw)
        d.arc(S((cx, cy - r * .5, cx + r, cy + r * .5)), start=270, end=90, fill=c, width=lw)
        line(-r * .35, 0, r * .35, 0)
    elif glyph == "flag":                   # end of journey
        line(-r * .6, -r * .9, -r * .6, r * .9, 2.2)
        poly([(-r * .6, -r * .9), (r * .85, -r * .45), (-r * .6, 0)])
    else:                                   # unknown
        circle(0, 0, r * .7, w=2.2)
        circle(0, 0, r * .2, fill=c, outline=c)


def draw_icon(img, d, fam, cx, cy, r, color, bg=CARD):
    path = _icon_file(fam)
    if path:
        size = r * 2.2
        paste_icon_file(img, path, cx - size / 2, cy - size / 2, size, fam)
    else:
        draw_glyph(d, FAMILIES[fam]["glyph"], cx, cy, r, color, bg)


# ── node card ──────────────────────────────────────────────────────────────
def draw_node(img, d, node, x, y, index=None):
    fam, spec = family(node.get("type"))
    color = spec["color"]
    tint = tuple(int(ch + (255 - ch) * 0.90) for ch in color)

    rrect(d, (x, y, x + NODE_W, y + NODE_H), 14, fill=CARD, outline=BORDER, width=1)
    # accent rail down the left edge — the family colour, readable at a glance
    d.rounded_rectangle(S((x, y, x + 5, y + NODE_H)), radius=S(3), fill=color)

    # icon plate
    plate = 46
    rrect(d, (x + 16, y + 15, x + 16 + plate, y + 15 + plate), 12, fill=tint)
    draw_icon(img, d, fam, x + 16 + plate / 2, y + 15 + plate / 2, 14, color, tint)

    # step number, top-right
    if index is not None:
        text(d, (x + NODE_W - 14, y + 18), str(index), size=12, bold=True,
             fill=FAINT, anchor="ra")

    # family title, then the label, then the detail line(s)
    text(d, (x + 16, y + 68), spec["title"].upper(), size=9.5, bold=True, fill=color)
    label = node.get("label") or node.get("name") or spec["title"]
    inner = NODE_W - 32
    for i, line in enumerate(wrap(label, inner, 14, True, max_lines=2)):
        text(d, (x + 16, y + 81 + i * 16), line, size=14, bold=True, fill=INK)
    detail = node.get("detail") or node.get("settings") or ""
    if isinstance(detail, dict):
        detail = " · ".join(f"{k} {v}" for k, v in detail.items())
    if detail:
        lines = wrap(detail, inner, 11.5, False, max_lines=2)
        base = y + 81 + len(wrap(label, inner, 14, True, max_lines=2)) * 16 + 2
        for i, line in enumerate(lines):
            if base + i * 13 > y + NODE_H - 12:
                break
            text(d, (x + 16, base + i * 13), line, size=11.5, fill=MUTED)


# ── layout ─────────────────────────────────────────────────────────────────
def cols_for(width) -> int:
    usable = width - 2 * PAD
    return max(1, int((usable + GAP_X) // (NODE_W + GAP_X)))


def width_for(width_of_cols: int) -> int:
    return int(2 * PAD + width_of_cols * (NODE_W + GAP_X) - GAP_X)


def longest_lane(nodes, depth=0) -> int:
    """Widest lane in a journey, counting branch lanes at their indent. Used to
    size the board so a 10-activity journey draws as one straight row instead of
    wrapping — wide boards read far better than snaked ones."""
    longest = len(nodes)
    for node in nodes:
        for branch_nodes in (node.get("branches") or {}).values():
            if depth >= 2:
                continue
            longest = max(longest, 1 + longest_lane(list(branch_nodes), depth + 1))
    return longest


def lane_rows(nodes, cols) -> list[list]:
    return [nodes[i:i + cols] for i in range(0, len(nodes), cols)] or [[]]


def measure_lane(nodes, cols, depth=0) -> float:
    """Height a lane (plus every branch lane hanging off it) will occupy."""
    if not nodes:
        return 0.0
    height = 0.0
    for row in lane_rows(nodes, cols):
        height += NODE_H + GAP_Y
        for node in row:
            for branch_nodes in (node.get("branches") or {}).values():
                if depth >= 2:                     # deeper forks are summarised
                    continue
                height += 22 + measure_lane(list(branch_nodes),
                                            max(1, cols - 1), depth + 1)
    return height


def measure_journey(journey, cols) -> float:
    nodes = list(journey.get("nodes") or journey.get("chain") or [])
    height = TITLE_H
    if journey.get("note"):
        height += 20
    height += measure_lane(nodes, cols)
    flags = [x for x in (journey.get("flags") or []) if str(x).strip()]
    if flags:
        # two-line flags are allowed, so budget for the worst case
        height += 8 + len(flags) * (FLAG_H + 14)
    return height + 18


def flag_kind(s: str) -> str:
    s = str(s)
    if "⛔" in s or s.strip().upper().startswith(("BLOCK", "UNCAPTURED")):
        return "block"
    if "❓" in s or "?" == s.strip()[:1]:
        return "ask"
    if "⚠" in s:
        return "warn"
    return "info"


_FLAG_FALLBACK = {"warn": "brief-invisible rule applied",
                  "ask": "assumption made", "block": "uncaptured",
                  "info": "note"}


def clean_flag(s: str, kind: str = "info") -> str:
    """The flag text without its leading symbol — the badge draws that.

    A model sometimes emits the bare symbol with no words (`"flags": ["⚠"]`).
    Stripping it would leave an empty chip, so fall back to what the symbol
    means; the operator still sees that something was flagged."""
    body = re.sub(r"^[\s⚠❓⛔!?*·•\-]+", "", str(s)).strip()
    return body or _FLAG_FALLBACK.get(kind, "note")


def draw_flag(d, s, x, y, max_w):
    """Draw one flag chip. Returns the height used.

    Long flags used to be ellipsized to a single line, which silently dropped
    most of a 300-character ⛔ — exactly the flag worth reading. Two lines are
    allowed now, and only past that does it clip.
    """
    kind = flag_kind(s)
    fg, bg = FLAG_COLORS[kind]
    body = clean_flag(s, kind)
    badge = 18
    inner = max_w - badge - 30
    lines = wrap(body, inner, 11.5, False, max_lines=2)
    h = (FLAG_H - 6) if len(lines) == 1 else (FLAG_H - 6) + 14
    w = badge + 10 + max(text_w(line, 11.5) for line in lines) + 12
    rrect(d, (x, y, x + w, y + h), min(h / 2, 11), fill=bg)
    # drawn badge instead of the emoji — Roboto has no glyph for ⚠/❓/⛔
    cx, cy, r = x + badge / 2 + 4, y + min(h, FLAG_H - 6) / 2, 6.5
    if kind == "warn":
        d.polygon([S((cx, cy - r)), S((cx - r, cy + r * .75)), S((cx + r, cy + r * .75))], fill=fg)
    elif kind == "block":
        d.ellipse(S((cx - r, cy - r, cx + r, cy + r)), fill=fg)
        d.line([S((cx - r * .5, cy)), S((cx + r * .5, cy))], fill=bg, width=max(1, S(1.8)))
    elif kind == "ask":
        d.ellipse(S((cx - r, cy - r, cx + r, cy + r)), outline=fg, width=max(1, S(1.6)))
        text(d, (cx, cy - 6.5), "?", size=11, bold=True, fill=fg, anchor="ma")
    else:
        d.ellipse(S((cx - r * .5, cy - r * .5, cx + r * .5, cy + r * .5)), fill=fg)
    top = y + (h / 2 - 7) if len(lines) == 1 else y + 5
    for i, line in enumerate(lines):
        text(d, (x + badge + 10, top + i * 14), line, size=11.5, fill=fg)
    return h


def draw_lane(img, d, nodes, x, y, cols, width, depth=0, start_index=1) -> float:
    """Draw a chain left→right, wrapping to the next row when it runs out of
    width. Returns the y after the lane (and its branch lanes)."""
    if not nodes:
        return y
    idx = start_index
    cursor = y
    for row_i, row in enumerate(lane_rows(nodes, cols)):
        for col_i, node in enumerate(row):
            nx = x + col_i * (NODE_W + GAP_X)
            draw_node(img, d, node, nx, cursor, index=idx if depth == 0 else None)
            # `alt` nodes are alternatives sharing one row (wheel prizes), not a
            # sequence — no arrow from the card on their left.
            if col_i and not node.get("alt"):
                arrow_right(d, nx - GAP_X + 5, nx - 5, cursor + NODE_H / 2)
            elif row_i:
                # Wrapped row: a long vertical arrow back across the board reads
                # worse than saying it — the step numbers carry the order.
                text(d, (nx, cursor - 15), "…continues", size=10.5, bold=True, fill=FAINT)
                arrow_right(d, nx - 26, nx - 5, cursor + NODE_H / 2)
            idx += 1
        below = cursor + NODE_H + GAP_Y
        for col_i, node in enumerate(row):
            branches = node.get("branches") or {}
            if not isinstance(branches, dict):
                continue
            nx = x + col_i * (NODE_W + GAP_X)
            for event, branch_nodes in branches.items():
                branch_nodes = list(branch_nodes or [])
                if not branch_nodes:
                    continue
                if depth >= 2:
                    text(d, (nx + 8, below), f"↳ {event} → …", size=11, fill=FAINT)
                    below += 18
                    continue
                bx = nx + BRANCH_INDENT
                bcols = max(1, cols - 1)
                bh = measure_lane(branch_nodes, bcols, depth + 1)
                rrect(d, (bx - 14, below - 4, min(x + width, bx - 14 + (NODE_W + GAP_X) *
                                                  min(bcols, len(branch_nodes)) + 14),
                          below + bh + 6), 12, fill=LANE_BG)
                text(d, (bx, below + 3), f"↳ on {event}", size=11, bold=True, fill=MUTED)
                elbow_down(d, nx + 28, cursor + NODE_H, below + 30, bx - 4)
                draw_lane(img, d, branch_nodes, bx, below + 22, bcols,
                          width, depth + 1)
                below += 22 + bh
        cursor = below
    return cursor


def draw_journey(img, d, journey, x, y, cols, width, number=None) -> float:
    name = journey.get("name") or journey.get("journey_name") or "Journey"
    badge = f"{number}" if number else None
    top = y
    # title strip
    rrect(d, (x - 14, y, x + width - 2 * PAD + 14, y + 38), 10, fill=(233, 237, 244))
    tx = x
    if badge:
        d.ellipse(S((tx, y + 8, tx + 22, y + 30)), fill=(23, 28, 38))
        text(d, (tx + 11, y + 12), badge, size=12, bold=True, fill=(255, 255, 255), anchor="ma")
        tx += 32
    text(d, (tx, y + 11), ellipsize(name, width - 2 * PAD - 60, 15.5, True),
         size=15.5, bold=True, fill=INK)
    y += TITLE_H
    if journey.get("note"):
        text(d, (x, y - 12), ellipsize(journey["note"], width - 2 * PAD, 12), size=12, fill=MUTED)
        y += 20
    nodes = list(journey.get("nodes") or journey.get("chain") or [])
    y = draw_lane(img, d, nodes, x, y, cols, width - 2 * PAD)
    flags = [str(x2) for x2 in (journey.get("flags") or []) if str(x2).strip()]
    if flags:
        y += 4
        for flag in flags:
            used = draw_flag(d, flag, x, y, width - 2 * PAD)
            y += (used or (FLAG_H - 6)) + 6
    return max(y + 14, top + TITLE_H + NODE_H)


def draw_board(diagram, journeys, page, pages, out_path, width=WIDTH) -> dict:
    cols = cols_for(width)
    # The estimate only has to be generous — the board is cropped to what was
    # actually drawn, so no journey gets clipped and no board carries dead space.
    body = sum(measure_journey(j, cols) + 26 for j in journeys)
    height = int(HEADER_H + 16 + body + 120)

    img = Image.new("RGBA", (S(width), S(height)), BG + (255,))
    d = ImageDraw.Draw(img)

    # header
    d.rectangle(S((0, 0, width, HEADER_H)), fill=HEADER_BG)
    campaign = diagram.get("campaign") or diagram.get("name") or "Campaign design"
    text(d, (PAD, 22), ellipsize(campaign, width - 2 * PAD - 220, 24, True),
         size=24, bold=True, fill=(255, 255, 255))
    meta = " · ".join(str(v) for v in (diagram.get("brand"), diagram.get("window"),
                                       diagram.get("trigger")) if v)
    if meta:
        text(d, (PAD, 58), ellipsize(meta, width - 2 * PAD - 220, 13), size=13,
             fill=(168, 178, 196))
    if pages > 1:
        text(d, (width - PAD, 30), f"BOARD {page} / {pages}", size=12, bold=True,
             fill=(140, 152, 174), anchor="ra")
    text(d, (width - PAD, 52), "REA Journey Planner", size=11, fill=(96, 108, 128), anchor="ra")

    y = HEADER_H + 22
    first = diagram.get("_number_from", 1)
    for i, journey in enumerate(journeys):
        y = draw_journey(img, d, journey, PAD, y, cols, width,
                         number=first + i) + 26

    height = min(height, int(y + 14))
    img = img.crop((0, 0, S(width), S(height)))
    img = img.convert("RGB").resize((width, height), Image.LANCZOS)
    try:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        img.save(out_path, "PNG", optimize=True)
    except OSError as exc:
        # A traceback on stdout reaches the operator as a wall of Python. Say what
        # cannot be written and let main() report it as a clean refusal.
        raise BoardWriteError(f"cannot write {out_path}: {exc}") from exc
    return {"file": out_path.name, "path": str(out_path), "w": width, "h": height,
            "journeys": [j.get("name") or j.get("journey_name") or "Journey"
                         for j in journeys]}


# ── input parsing ──────────────────────────────────────────────────────────
def extract_diagram(blob: str) -> dict:
    """Pull the diagram object out of a raw planner reply.

    Accepts the bare object, a ```json fence, or prose with the block embedded —
    the same tolerance compose.py gives specs, so the operator never hand-cleans
    a reply.
    """
    blob = (blob or "").strip()
    candidates: list[str] = []
    candidates += [m.strip() for m in re.findall(r"```(?:json|JSON)?\s*(.*?)```", blob, re.S)]
    candidates.append(blob)
    depth, start = 0, None
    for i, ch in enumerate(blob):
        if ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}" and depth:
            depth -= 1
            if depth == 0 and start is not None:
                candidates.append(blob[start:i + 1])
                start = None
    for candidate in candidates:
        try:
            data = json.loads(candidate)
        except ValueError:
            continue
        if not isinstance(data, dict):
            continue
        diagram = data.get("diagram") if isinstance(data.get("diagram"), dict) else data
        if isinstance(diagram.get("journeys"), list) and diagram["journeys"]:
            # A wheel is often emitted as a sibling of `diagram` rather than
            # inside it — carry it in so it still gets a board.
            for key in ("randomizer", "randomizers"):
                if key in data and key not in diagram:
                    diagram = dict(diagram, **{key: data[key]})
            return diagram

    # Nothing parsed. A big campaign's design block can still arrive cut off mid
    # journey (the model's output cap), and half a plan drawn beats no plan at
    # all — so salvage every whole journey and say how many were lost.
    salvaged = _salvage(blob)
    if salvaged:
        return salvaged
    raise ValueError(
        "no diagram found — expected a JSON object with "
        '{"diagram": {"journeys": [...]}}')


def _salvage(blob: str) -> dict | None:
    """Recover the whole journeys from a truncated diagram block.

    Cuts the JSON back to the last position that can be legally closed and
    parses that. `_truncated` is set so the caller can report the loss instead of
    quietly drawing a short campaign.
    """
    start = blob.find('"diagram"')
    if start < 0:
        return None
    start = blob.rfind("{", 0, start)
    if start < 0:
        return None
    text = blob[start:]

    def closers_for(chunk: str) -> str | None:
        stack: list[str] = []
        in_string = escape = False
        for ch in chunk:
            if in_string:
                if escape:
                    escape = False
                elif ch == "\\":
                    escape = True
                elif ch == '"':
                    in_string = False
                continue
            if ch == '"':
                in_string = True
            elif ch in "{[":
                stack.append("}" if ch == "{" else "]")
            elif ch in "}]":
                if not stack or stack[-1] != ch:
                    return None
                stack.pop()
        if in_string:
            return None
        return "".join(reversed(stack))

    cuts = [i for i, ch in enumerate(text) if ch == "}"]
    for cut in reversed(cuts[-800:]):            # newest complete object first
        chunk = text[:cut + 1]
        tail = closers_for(chunk)
        if tail is None:
            continue
        try:
            data = json.loads(chunk + tail)
        except ValueError:
            continue
        if not isinstance(data, dict):
            continue
        diagram = data.get("diagram") if isinstance(data.get("diagram"), dict) else data
        journeys = diagram.get("journeys")
        if isinstance(journeys, list) and journeys:
            # The last entry may itself be a fragment (a journey with no nodes).
            if isinstance(journeys[-1], dict) and not journeys[-1].get("nodes"):
                journeys = journeys[:-1]
                if not journeys:
                    continue
                diagram = dict(diagram, journeys=journeys)
            diagram = dict(diagram, _truncated=True)
            for key in ("randomizer", "randomizers"):
                if key in data and key not in diagram:
                    diagram[key] = data[key]
            return diagram
    return None


def normalise(diagram: dict) -> dict:
    """Tolerate the shapes a model actually emits: a journey's chain under
    `nodes`/`chain`/`activities`, a node given as a bare string, a flag list
    given as one string."""
    journeys = []
    for raw in diagram.get("journeys") or []:
        if isinstance(raw, str):
            raw = {"name": raw, "nodes": []}
        journey = dict(raw)
        nodes = (journey.get("nodes") or journey.get("chain")
                 or journey.get("activities") or journey.get("flow") or [])
        if isinstance(nodes, str):
            # "promotion → freespin_bonus → end_of_journey"
            nodes = [n.strip() for n in re.split(r"→|->|,", nodes) if n.strip()]
        journey["nodes"] = [_node(n) for n in nodes]
        flags = journey.get("flags")
        if isinstance(flags, str):
            journey["flags"] = [flags]
        elif isinstance(flags, dict):
            journey["flags"] = [f"{k} {v}" for k, v in flags.items()]
        journeys.append(journey)
    journeys += _randomizer_journeys(diagram)
    out = dict(diagram)
    out["journeys"] = journeys
    return out


def _signature(nodes: list[dict]) -> tuple:
    """The SHAPE of a chain: activity families in order, branches included.

    Two journeys with this signature differ only in values, which is exactly the
    tier-matrix case: "10 FS at bet 50" and "40 FS at bet 300" are the same
    picture with different numbers.
    """
    out = []
    for node in nodes or []:
        fam, _ = family(node.get("type"))
        branches = tuple(sorted((event, _signature(list(kids)))
                                for event, kids in (node.get("branches") or {}).items()))
        out.append((fam, branches))
    return tuple(out)


def _merge_values(members: list[dict], index: int, key: str, limit: int = 3) -> str:
    """One card's text across a group: identical values collapse, differing ones
    are listed. Nothing is invented and nothing is hidden — a reviewer needs to
    see that the bet is 50/100/200 by tier."""
    seen: list[str] = []
    for journey in members:
        nodes = journey.get("nodes") or []
        if index >= len(nodes):
            continue
        value = str((nodes[index] or {}).get(key) or "").strip()
        if value and value not in seen:
            seen.append(value)
    if not seen:
        return ""
    if len(seen) == 1:
        return seen[0]
    # Values in a matrix share a shape ("Deposit ≥ 2500 CLP" … "Deposit ≥ 20000
    # CLP"), so vary only the middle: "Deposit ≥ 2500 / 5000 / 20000 CLP" reads on
    # a card where five whole phrases would not fit.
    # WHOLE WORDS only: "2.500 CLP" and "20.000 CLP" share the characters
    # "00 CLP", and stripping that turns 2.500 into "2.5".
    head = os.path.commonprefix(seen)
    head = head[:head.rfind(" ") + 1] if " " in head else ""
    tail = os.path.commonprefix([v[::-1] for v in seen])[::-1]
    tail = tail[tail.find(" "):] if " " in tail else ""
    if len(head) + len(tail) >= min(len(v) for v in seen):
        tail = ""                              # overlapping; keep it simple
    middles = [v[len(head):len(v) - len(tail)].strip() for v in seen]
    if head.strip() and all(middles):
        joined = " / ".join(middles[:limit + 2])
        if len(middles) > limit + 2:
            joined += f" … (+{len(middles) - limit - 2})"
        return f"{head}{joined}{tail}".replace("  ", " ").strip()
    shown = " / ".join(seen[:limit])
    return shown + (f" … (+{len(seen) - limit})" if len(seen) > limit else "")


def collapse_variants(journeys: list[dict], min_group: int = 3) -> tuple[list[dict], int]:
    """Draw one board per SHAPE, not one per journey.

    A 5-tier x 6-prize brief is 30 journeys that are one picture with different
    numbers. MODE 1 is told to group them, and does — in the outline. The design
    block then enumerated all 30 anyway often enough to matter (11 and 27 boards
    against a 5-line outline, measured), which hands the reviewer the wall of
    near-identical pictures that grouping exists to prevent.

    So the grouping is enforced here instead of asked for: journeys sharing an
    activity signature become one board whose cards list the values that vary and
    whose note names every journey it stands for. Returns (journeys, collapsed).
    """
    groups: dict[tuple, list[dict]] = {}
    order: list[tuple] = []
    for journey in journeys:
        sig = _signature(journey.get("nodes") or [])
        if sig not in groups:
            groups[sig] = []
            order.append(sig)
        groups[sig].append(journey)

    out: list[dict] = []
    collapsed = 0
    for sig in order:
        members = groups[sig]
        if len(members) < min_group or not sig:
            out.extend(members)
            continue
        # Collapse ONE axis, not everything. A 6-prize x 5-tier group has the same
        # shape throughout, and folding it into a single board would print
        # "10/20/30 FS" beside "bet 50/100/200" — losing which spin count pairs
        # with which bet. Fold the NARROWER axis (fewest distinct values) and keep
        # the wider one as separate boards, which is how the outline reads it too:
        # one line per prize level, "bet 50/100/200/300/400 by tier".
        for sub in _split_on_narrowest_axis(members, min_group):
            out.append(_one_board(sub) if len(sub) > 1 else sub[0])
            collapsed += len(sub) - 1
    return out, collapsed


def _label_axes(members: list[dict]) -> dict[int, int]:
    """Distinct label count per node position across a same-shape group."""
    axes: dict[int, set] = {}
    for journey in members:
        for i, node in enumerate(journey.get("nodes") or []):
            axes.setdefault(i, set()).add(str((node or {}).get("label") or ""))
    return {i: len(v) for i, v in axes.items()}


def _split_on_narrowest_axis(members: list[dict], min_group: int) -> list[list[dict]]:
    """Sub-group a same-shape set so exactly one dimension is folded."""
    axes = {i: n for i, n in _label_axes(members).items() if n > 1}
    if not axes:
        return [members]                       # identical labels: one board
    fold = min(axes, key=lambda i: (axes[i], i))
    buckets: dict[tuple, list[dict]] = {}
    order: list[tuple] = []
    for journey in members:
        nodes = journey.get("nodes") or []
        key = tuple(str((n or {}).get("label") or "")
                    for i, n in enumerate(nodes) if i != fold)
        if key not in buckets:
            buckets[key] = []
            order.append(key)
        buckets[key].append(journey)
    # A bucket too small to be worth folding is left as individual boards.
    result = []
    for key in order:
        bucket = buckets[key]
        result.append(bucket if len(bucket) >= 2 else bucket)
    return result


def _one_board(members: list[dict]) -> dict:
    """Fold a set of same-shape journeys into a single board."""
    if True:
        first = dict(members[0])
        nodes = []
        for i, node in enumerate(first.get("nodes") or []):
            merged = dict(node)
            label = _merge_values(members, i, "label")
            detail = _merge_values(members, i, "detail")
            if label:
                merged["label"] = label
            if detail:
                merged["detail"] = detail
            else:
                merged.pop("detail", None)
            nodes.append(merged)
        names = [str(m.get("name") or "journey") for m in members]
        prefix = os.path.commonprefix(names).rstrip(" |-—")
        first["nodes"] = nodes
        first["name"] = f"{prefix} — {len(members)} variants" if prefix else \
                        f"{len(members)} journeys, same shape"
        listed = ", ".join(n[len(prefix):].strip(" |-—") or n for n in names[:6])
        first["note"] = (f"{len(members)} journeys on one board: {listed}"
                         + (" …" if len(names) > 6 else ""))
        # A flag on any member belongs to the group's board.
        flags: list[str] = []
        for m in members:
            for f in (m.get("flags") or []):
                if f not in flags:
                    flags.append(str(f))
        first["flags"] = flags
        return first


def _randomizer_journeys(diagram: dict) -> list[dict]:
    """Boards for wheels the planner listed alongside the journeys.

    A randomizer is one of the objects in the outline, so it belongs on a board
    even when the model puts it in a sibling `randomizer` key instead of giving
    it a journey entry. Its prizes are drawn as branch lanes — they are
    alternatives, not a sequence."""
    raw = diagram.get("randomizer") or diagram.get("randomizers") or []
    if isinstance(raw, dict):
        raw = [raw]
    boards = []
    for wheel in raw:
        if not isinstance(wheel, dict):
            continue
        kind = wheel.get("kind") or "randomizer"
        weights = list(wheel.get("weights") or [])
        targets = list(wheel.get("journeys") or [])
        when = " · ".join(str(v) for v in (
            wheel.get("date") or " ".join(map(str, wheel.get("dates") or [])) or None,
            f"{wheel['days']} days" if wheel.get("days") else None) if v)
        prizes = []
        for i in range(max(len(weights), len(targets))):
            weight = weights[i] if i < len(weights) else "?"
            target = targets[i] if i < len(targets) else "journey TBD"
            prizes.append({"type": "connector", "label": f"Prize {i + 1} · {weight}%",
                           "detail": str(target), "alt": True})
        node = {"type": "scratch" if "scratch" in str(kind) else "wheel",
                "label": wheel.get("internal_name") or str(kind),
                "detail": when or None}
        if prizes:
            # One lane, no arrows between the cards: the slices are alternatives.
            node["branches"] = {f"{len(prizes)} prize slices, each routing to a journey": prizes}
        boards.append({"name": f"Randomizer — {kind}",
                       "note": wheel.get("note") or "prizes route winners into the journeys above",
                       "flags": wheel.get("flags") or [],
                       "nodes": [node]})
    return boards


def _node(node) -> dict:
    if isinstance(node, str):
        return {"type": node}
    if not isinstance(node, dict):
        return {"type": "unknown", "label": str(node)}
    out = dict(node)
    if "type" not in out:
        out["type"] = out.get("activity") or out.get("kind") or "unknown"
    branches = out.get("branches")
    if isinstance(branches, dict):
        out["branches"] = {k: [_node(n) for n in (v or [])] for k, v in branches.items()}
    else:
        out.pop("branches", None)
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="Render a MODE 1 journey design to PNG boards")
    ap.add_argument("input", help="JSON/reply file, or - for stdin")
    ap.add_argument("--out", default=str(REPO_ROOT / "data" / "journey_designs"),
                    help="output directory")
    ap.add_argument("--name", default="design", help="output filename prefix")
    ap.add_argument("--per-image", type=int, default=2,
                    help="journeys per board (0 = all on one board)")
    ap.add_argument("--width", type=int, default=0,
                    help="board width in px (default: fit the longest journey)")
    ap.add_argument("--max-cols", type=int, default=12,
                    help="most activities on one row before the chain wraps")
    ap.add_argument("--collapse-at", type=int, default=3,
                    help="journeys of identical shape drawn as one board (0/1 = off)")
    ap.add_argument("--no-collapse", action="store_true",
                    help="one board per journey, however many near-identical ones")
    args = ap.parse_args()

    blob = sys.stdin.read() if args.input == "-" else Path(args.input).read_text(encoding="utf-8")
    try:
        diagram = normalise(extract_diagram(blob))
    except ValueError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}))
        return 3

    journeys = diagram["journeys"]
    if not args.no_collapse:
        journeys, collapsed = collapse_variants(journeys, min_group=args.collapse_at)
        if collapsed:
            diagram = dict(diagram, journeys=journeys)
    else:
        collapsed = 0
    per = len(journeys) if args.per_image <= 0 else max(1, args.per_image)
    groups = [journeys[i:i + per] for i in range(0, len(journeys), per)]

    # Each board is as wide as its own longest journey, with a floor so short
    # journeys still draw as a board rather than a strip — a 4-card journey on a
    # canvas sized for a 10-card one is mostly empty space.
    max_cols = max(1, args.max_cols)

    def board_width(group) -> int:
        if args.width > 0:
            return max(760, args.width)
        needed = max((longest_lane(j["nodes"]) for j in group), default=1)
        return width_for(min(max(needed, MIN_COLS), max_cols))

    out_dir = Path(args.out)
    images = []
    try:
        for i, group in enumerate(groups, 1):
            page = dict(diagram, _number_from=(i - 1) * per + 1)
            suffix = f"_{i}" if len(groups) > 1 else ""
            images.append(draw_board(page, group, i, len(groups),
                                     out_dir / f"{args.name}{suffix}.png",
                                     width=board_width(group)))
    except BoardWriteError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}))
        return 4
    print(json.dumps({"ok": True, "count": len(images), "images": images,
                      "campaign": diagram.get("campaign") or "",
                      "journeys": len(journeys),
                      # how many near-identical journeys share a board, so the UI
                      # can say "30 journeys on 8 boards" instead of implying 8
                      "collapsed": collapsed,
                      "truncated": bool(diagram.get("_truncated"))},
                     ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
