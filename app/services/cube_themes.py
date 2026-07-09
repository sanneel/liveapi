"""
Cube theme registry.

Themed cube endpoints (e.g. /cube/ucl, /cube/worldcup) all share the same
pipeline (HotEngine match selection → PIL render → png_cache) but differ in:
  * which tournaments count as "in scope" for the theme
  * the sport scope (always `football` for UCL/WorldCup, but kept generic)
  * the visual identity: colors, badge text, background image override

Adding a new theme is one entry in CUBE_THEMES below. No code changes
needed in the route or renderer for typical color/league swaps.

League filtering is pattern-based. We match against `Match.tournament_slug`
using `startswith` so the theme survives feed-side suffix drift
("uefa-champions-league" vs "uefa-champions-league-final" vs
"uefa-champions-league-quarterfinal").
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Literal, Optional, Tuple

from ..utils.slugify import slugify_league


# A "face" on the rotating widget cube. Two kinds:
#   - "brand": static promo (logo + tagline, color background)
#   - "match": dynamic match face (filled in from /cube/{theme}/data.json)
FaceKind = Literal["brand", "match", "image"]


@dataclass(frozen=True)
class CubeFace:
    kind: FaceKind
    # Brand face: large label across the middle (e.g. "JUGABET", "BETCHAMP").
    # Match face: ignored.
    label: str = ""
    # Brand face: small text below label (e.g. "APUESTAS DEPORTIVAS").
    # Match face: ignored.
    sublabel: str = ""
    # Background color (CSS hex). Match faces inherit theme bg if blank.
    bg: str = ""
    # Text color (CSS hex). Defaults to white when blank.
    fg: str = "#ffffff"
    # Accent color for the small underline / divider. Defaults to theme accent.
    accent: str = ""
    # Match face: which slot in resolve_for_theme(limit=N) to render.
    # 0 = top-ranked match. Brand faces ignore this.
    match_index: int = 0
    # Image face: URL of the static promo photo to display full-bleed.
    image_url: str = ""


@dataclass(frozen=True)
class CubeTheme:
    # Identifier used in URL: /cube/{slug}
    slug: str
    # Display name (shown in HTML preview, page title)
    display_name: str
    # Sport scope. For now always "football" for UCL/WorldCup themes; kept
    # generic so future themes (NBA Finals, ATP Finals, etc.) drop in cleanly.
    sport: str
    # Tournament filter. We match `Match.tournament_slug.startswith(p)` for
    # any pattern in this list. Patterns are pre-slugified at import time.
    league_patterns: Tuple[str, ...]
    # Free-text labels shown on the rendered cube.
    badge_text: str
    subtitle: str
    # Gradient colors for the procedural template background (top -> bottom).
    bg_top: Tuple[int, int, int]
    bg_bottom: Tuple[int, int, int]
    # Accent color used for the badge plaque and odds frames.
    accent: Tuple[int, int, int]
    # Text colors.
    text_primary: Tuple[int, int, int] = (255, 255, 255)
    text_muted: Tuple[int, int, int] = (220, 220, 220)
    # Optional override: if a real branded template asset exists on disk,
    # point at it (relative to repo root) and the renderer will composite
    # event text onto it instead of drawing the gradient programmatically.
    template_image_path: Optional[str] = None
    # URL of the static promo photo shown on the non-odds faces of the 3D cube.
    promo_image_url: str = ""
    # Optional animated slot-game GIF shown as an extra rotating face on the
    # 3D widget (browser animates the GIF natively inside the <img>). When set,
    # the widget rotation becomes promo -> odds -> slot -> odds. Leave blank to
    # keep the classic promo -> odds -> promo -> odds loop. Any /static/*.gif
    # sized ~420x380 drops in cleanly.
    slot_gif_url: str = ""
    # Rotating widget configuration. Each entry is a face on the cube; the
    # widget cycles through them on a Y-axis rotation. 4 faces fit a cube
    # (the front-rotating presentation in the reference video) — extra faces
    # are tolerated, they just rotate further. Defaults to a 4-face mix:
    # brand → match → brand → match for a familiar promo loop.
    faces: Tuple[CubeFace, ...] = field(default_factory=tuple)
    # If set, only matches where ALL strings appear (case-insensitive) in the
    # combined "home_name away_name" are kept. Use for one-off fixtures like
    # a specific final (e.g. PSG vs Arsenal).
    required_teams: Tuple[str, ...] = field(default_factory=tuple)
    # When True, the cube resolver promotes LIVE matches above prematch ones
    # in the final ordering — so a World Cup cube on match-day always shows
    # the live fixture instead of tomorrow's group-stage opener even if the
    # latter has a higher hot_score. Falls back to prematch when no live
    # in-scope match exists.
    prefer_live: bool = False
    # Optional admin notes (not rendered).
    notes: str = ""


def _slug_list(*names: str) -> Tuple[str, ...]:
    """Pre-slugify the league pattern list at module import time so the
    hot-path filter doesn't re-slugify on every request."""
    out: List[str] = []
    for n in names:
        s = slugify_league(n)
        if s:
            out.append(s)
    return tuple(out)


# ── Registered themes ────────────────────────────────────────────────────
# Add a new dataclass entry here and the route + renderer pick it up.
CUBE_THEMES: Dict[str, CubeTheme] = {
    "ucl": CubeTheme(
        slug="ucl",
        display_name="UEFA Champions League Final",
        sport="football",
        # The feed may name the UCL knockouts with various suffixes
        # (`UEFA Champions League`, `UEFA Champions League. Final`,
        # `Champions League`, etc.). `startswith` on slug catches all
        # variants that share the canonical root.
        league_patterns=_slug_list(
            "UEFA Champions League",
            "Champions League",
            "UCL",
        ),
        badge_text="UCL FINAL",
        subtitle="UEFA Champions League",
        # UCL palette: deep starry-night blue → royal blue, with gold accent.
        bg_top=(0, 18, 51),
        bg_bottom=(0, 79, 161),
        accent=(255, 199, 44),
        text_primary=(255, 255, 255),
        text_muted=(200, 215, 240),
        faces=(
            CubeFace(kind="image", image_url="/static/cube-ucl.jpg"),
            CubeFace(kind="match", match_index=0),
        ),
        required_teams=("arsenal",),
        promo_image_url="/static/cube-ucl.jpg",
        slot_gif_url="/static/slot-game.gif",
        notes="Locked to the PSG vs Arsenal final fixture.",
    ),
    "worldcup": CubeTheme(
        slug="worldcup",
        display_name="FIFA World Cup",
        sport="football",
        # Jugabet labels World Cup matches with many regional variants
        # ("Copa del Mundo", "Mundial de Clubes", "Clasificación · Eliminatorias
        # Mundial · ...", etc.). Cover every reasonable prefix so the cube
        # doesn't go dark just because the feed uses a Spanish variant.
        league_patterns=_slug_list(
            "FIFA World Cup",
            "World Cup",
            "Copa Mundial",
            "Copa del Mundo",
            "Mundial",
            "Eliminatorias Mundial",
            "Clasificación Mundial",
            "Mundial de Clubes",
            "Club World Cup",
            "Copa Mundial de Clubes",
        ),
        badge_text="WORLD CUP",
        subtitle="FIFA World Cup",
        # WC palette: deep maroon → warm gold (loosely the 2022 brand range).
        bg_top=(66, 0, 33),
        bg_bottom=(184, 30, 60),
        accent=(255, 184, 28),
        text_primary=(255, 255, 255),
        text_muted=(250, 230, 200),
        # Three match slots: the widget rotates through them every 20s so
        # the cube isn't stuck on a single fixture. Each slot is independently
        # pinnable from the admin (/admin/cube/worldcup), and an empty slot
        # is auto-filled by the next hot-ranked in-theme match.
        faces=(
            CubeFace(kind="image", image_url="/static/cube-worldcup.jpg"),
            CubeFace(kind="match", match_index=0),
            CubeFace(kind="match", match_index=1),
            CubeFace(kind="match", match_index=2),
        ),
        promo_image_url="/static/cube-worldcup.jpg",
        slot_gif_url="/static/slot-game.gif",
        prefer_live=True,
        notes=(
            "Filters football matches whose tournament_slug starts with any "
            "World Cup variant. Live matches surface above prematch. "
            "Widget rotates through 3 match slots."
        ),
    ),
}


def get_theme(slug: str) -> Optional[CubeTheme]:
    """Look up a theme by URL slug, case-insensitive. Returns None if missing."""
    if not slug:
        return None
    return CUBE_THEMES.get(slug.strip().lower())


def list_themes() -> List[CubeTheme]:
    return list(CUBE_THEMES.values())


def match_in_theme(tournament_slug: Optional[str], theme: CubeTheme) -> bool:
    """Return True if a Match's tournament_slug satisfies the theme filter."""
    if not tournament_slug:
        return False
    for pat in theme.league_patterns:
        if tournament_slug.startswith(pat):
            return True
    return False
