"""Promotions hub — surface every promo automation + its scripts in the admin.

Reads journey-cloner/catalog.json (the machine-readable automation catalog built
by build_catalog.py) and augments each automation with:
  * a link to its live generator page in this admin (where one exists), and
  * the list of repo files (generators + captured templates) that implement it.

It also enumerates *every* script/template/doc under journey-cloner/ so the page
can offer all of them for download in one place. resolve_script() keeps the
download route inside journey-cloner/ (no path traversal).
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List, Optional

from ..config import BASE_DIR

CLONER_DIR = BASE_DIR / "journey-cloner"
CATALOG_PATH = CLONER_DIR / "catalog.json"

# In-page tab that generates each automation (None -> template-only today).
# The promo page is produced by the GOW run, so both point at the GOW tab.
AUTOMATION_TABS: Dict[str, Optional[str]] = {
    "promo_page": "gow",
    "gow": "gow",
    "sport_wof": "randomizers",
    "casino_scratch_card": "randomizers",
    "casino_wof": "randomizers",
}

# Files (repo-relative to journey-cloner/) that implement each automation.
AUTOMATION_SCRIPTS: Dict[str, List[str]] = {
    "promo_page": [
        "gow_campaign.py",
        "templates/casino/gow.json",
    ],
    "gow": [
        "gow_combined.py",
        "gow_campaign.py",
        "comms_campaign.py",
        "email_content.py",
        "casino_journey.py",
        "spec_parser.py",
        "create_journeys.py",
        "generate_console_script.py",
        "figma_export.py",
        "templates/casino/gow.json",
        "templates/casino/gow_comms.json",
        "templates/casino/gow_email.json",
        "templates/casino/segment_cs_301.json",
    ],
    "sport_wof": [
        "randomizer_campaign.py",
        "templates/sport/sport_wof_randomizer.json",
        "templates/sport/wof_visual/content-en.json",
        "templates/sport/wof_visual/content-es.json",
        "templates/sport/wof_visual/settings.json",
        "templates/sport/wof_visual/manifest.json",
    ],
    "casino_scratch_card": [
        "randomizer_campaign.py",
        "templates/casino/raspaygana_scratchcard.json",
    ],
    "casino_wof": [
        "randomizer_campaign.py",
        "templates/casino/casino_wof_randomizer.json",
    ],
}

# Extensions we expose in the "all scripts" download list.
_LISTED_SUFFIXES = {".py", ".json", ".md", ".js", ".txt", ".flow"}
# Directories under journey-cloner/ we never list (caches, venvs, byproducts).
_SKIP_DIRS = {"__pycache__", ".venv", "figma_cache", "figma_out", "raw_fetches", "out", "console_scripts"}


def load_catalog() -> dict:
    if not CATALOG_PATH.exists():
        return {}
    return json.loads(CATALOG_PATH.read_text(encoding="utf-8"))


def _file_meta(rel: str) -> Optional[dict]:
    p = (CLONER_DIR / rel)
    if not p.exists() or not p.is_file():
        return None
    return {"path": rel, "name": p.name, "bytes": p.stat().st_size}


def automations() -> List[dict]:
    """Each catalog automation enriched with link + resolved script files."""
    cat = load_catalog()
    out: List[dict] = []
    for a in cat.get("automations", []):
        key = a.get("key", "")
        scripts = [m for rel in AUTOMATION_SCRIPTS.get(key, []) if (m := _file_meta(rel))]
        out.append({**a, "tab": AUTOMATION_TABS.get(key), "scripts": scripts})
    return out


def all_scripts() -> List[dict]:
    """Every script/template/doc under journey-cloner/, grouped by top folder."""
    items: List[dict] = []
    for p in sorted(CLONER_DIR.rglob("*")):
        if not p.is_file() or p.suffix.lower() not in _LISTED_SUFFIXES:
            continue
        rel_parts = p.relative_to(CLONER_DIR).parts
        if any(part in _SKIP_DIRS for part in rel_parts):
            continue
        rel = str(p.relative_to(CLONER_DIR))
        group = rel_parts[0] if len(rel_parts) > 1 else "(root)"
        items.append({"path": rel, "name": p.name, "bytes": p.stat().st_size, "group": group})
    return items


def resolve_script(rel_path: str) -> Optional[Path]:
    """Resolve a repo-relative path to an absolute file inside journey-cloner/.

    Returns None on traversal attempts or missing files so the route can 404."""
    if not rel_path:
        return None
    candidate = (CLONER_DIR / rel_path).resolve()
    root = CLONER_DIR.resolve()
    try:
        candidate.relative_to(root)
    except ValueError:
        return None
    if not candidate.is_file():
        return None
    if any(part in _SKIP_DIRS for part in candidate.relative_to(root).parts):
        return None
    return candidate

# ── generator registry ─────────────────────────────────────────────────────
# The ONE place that says what campaign generators exist and where each is
# driven from. catalog.json describes five automations, the page has ten tabs and
# journey-cloner/ holds twenty-odd scripts, so "what can this thing build?" had
# three partial answers and no complete one. That is how PMCL Bet & Get looked
# missing when it had shipped, and how casino_journey.py has sat with no UI.
#
# `tab` is the Optimization tab that drives it, `route` a page of its own, and
# None means script-only (run it from a shell). GENERATORS is checked against the
# filesystem by unlisted_generators(), so a new script shows up as unregistered
# instead of quietly not existing.
GENERATORS: List[dict] = [
    # ── Casino ────────────────────────────────────────────────────────────
    {"key": "gow", "group": "Casino", "brand": "JBCL",
     "label": "Game of the Week",
     "what": "Free-spin journey + promo page + comms, one paste",
     "script": "gow_combined.py", "tab": "gow"},
    {"key": "casino_gow_clone", "group": "Casino", "brand": "JBCL",
     "label": "Casino GOW clone",
     "what": "Older path: clone GOW with new game/bets. Prefer the composer recipes",
     "script": "casino_journey.py", "tab": None, "legacy": True},
    {"key": "instant_freespin", "group": "Casino", "brand": "JBCL/PMCL",
     "label": "Instant free spins",
     "what": "Promotion → free spins, no deposit gate (composer recipe)",
     "script": "compose.py", "route": "/admin/ai"},
    {"key": "comms_builder", "group": "Comms", "brand": "JBCL",
     "label": "Comms builder",
     "what": "THE JBCL comms entry point: pick channels/splits/waits, paste the sheet. "
             "--variant gow / scratch_card / nc_only / tournament covers the shapes that "
             "used to be a script each. No model involved",
     "script": "comms_builder.py", "tab": "comms_builder"},
    {"key": "nc_discount", "group": "Casino", "brand": "JBCL",
     "label": "Discount NC",
     "what": "One notification journey per game/day from the calendar. Superseded by "
             "Comms builder --variant nc_only; kept for the baked calendar",
     "script": "nc_discount_campaign.py", "tab": "nc_discount",
     "superseded_by": "comms_builder"},
    {"key": "nc_discount_pmcl", "group": "Casino", "brand": "PMCL",
     "label": "Discount NC — PMCL",
     "what": "The fortunazo.cl variant, same shape",
     "script": "nc_discount_pmcl_campaign.py", "tab": "nc_discount"},
    {"key": "bet_and_get", "group": "Casino", "brand": "PMCL",
     "label": "Bet & Get",
     "what": "Journey + promo page + email from the captured PMCL flow",
     "script": "bet_and_get_pmcl_campaign.py", "tab": "bet_and_get"},

    # ── Sport ─────────────────────────────────────────────────────────────
    {"key": "promo_codes", "group": "Sport", "brand": "JBCL",
     "label": "Promo Codes",
     "what": "Four match journeys per fixture (UDCH, Colo Colo)",
     "script": "create_journeys.py", "tab": "journey_cloner"},
    {"key": "prediction", "group": "Sport", "brand": "JBCL",
     "label": "Prediction",
     "what": "Multi-number prediction promo from a pasted sheet",
     "script": "prediction_campaign.py", "tab": "prediction"},
    {"key": "sport_comms", "group": "Sport", "brand": "JBCL",
     "label": "Scratch Card Comms",
     "what": "SMS + notification + pop-up + email for a liveapi campaign. Superseded by "
             "Comms builder --variant scratch_card, except the liveapi card fetch",
     "script": "sport_comms_campaign.py", "tab": "sport_comms",
     "superseded_by": "comms_builder"},

    # ── Wheels & cards ────────────────────────────────────────────────────
    {"key": "randomizers", "group": "Wheels & cards", "brand": "JBCL/PMCL",
     "label": "Randomizers",
     "what": "Fortune wheels and scratch cards (sport_wof, casino_wof, scratch)",
     "script": "randomizer_campaign.py", "tab": "randomizers"},

    # ── Comms ─────────────────────────────────────────────────────────────
    {"key": "tournament_pmcl", "group": "Comms", "brand": "PMCL",
     "label": "PMCL Tournament",
     "what": "NC + pop-up + SMS wired to the Smartico deeplink",
     "script": "tournament_pmcl_campaign.py", "tab": "tournament_pmcl"},
    {"key": "comms_chain", "group": "Comms", "brand": "JBCL/PMCL",
     "label": "Comms journey from content",
     "what": "NC + pop-up + SMS + email with your copy, one journey per date",
     "script": "journey_composer.py", "route": "/admin/ai"},
    {"key": "gow_comms", "group": "Comms", "brand": "JBCL",
     "label": "GOW comms",
     "what": "The comms half of a GOW campaign (built with it by default). Superseded "
             "for standalone use by Comms builder --variant gow",
     "script": "comms_campaign.py", "tab": "gow",
     "superseded_by": "comms_builder"},

    # ── Assets ────────────────────────────────────────────────────────────
    {"key": "slot_cards", "group": "Assets", "brand": "JBCL",
     "label": "Slot Cards",
     "what": "Reveal cards / GIFs for email and on-site",
     "script": None, "tab": "slot_cards"},
    {"key": "figma_export", "group": "Assets", "brand": "JBCL",
     "label": "Figma export",
     "what": "Pull GOW image slots straight out of Figma",
     "script": "figma_export.py", "tab": "gow"},

    # ── Tools ─────────────────────────────────────────────────────────────
    {"key": "games_registry", "group": "Tools", "brand": "—",
     "label": "Games registry",
     "what": "Rebuild library/games.json from the backoffice catalog",
     "script": "build_games_registry.py", "tab": None},
    {"key": "catalog", "group": "Tools", "brand": "—",
     "label": "Automation catalog",
     "what": "Rebuild catalog.json (what the Overview graph reads)",
     "script": "build_catalog.py", "tab": None},
    {"key": "planner", "group": "Tools", "brand": "JBCL/PMCL",
     "label": "AI planner",
     "what": "Brief → plan → design boards → console scripts",
     "script": "compose.py", "route": "/admin/ai"},
]

# Scripts that are library/tooling, not campaign generators — excluded from the
# "unregistered" warning so it only fires on something genuinely new.
_NOT_GENERATORS = {
    "__init__.py", "spec_parser.py", "email_content.py", "media_library.py",
    "har_analyse.py",
    "journey_composer.py", "compose.py", "plan_lint.py", "extract_fragments.py",
    "extract_knobs.py", "extract_templates.py", "mine_flows.py", "web_ui.py",
    "generate_console_script.py", "ai_campaign_builder.py", "casino_journey.py",
    "gow_campaign.py", "comms_campaign.py", "build_catalog.py",
    "build_games_registry.py", "nc_discount_campaign.py",
    "nc_discount_pmcl_campaign.py", "tournament_pmcl_email.py",
}


# Reading order for the Overview. Jinja's groupby sorts alphabetically, which put
# Assets and Tools above the thing most people came for.
GROUP_ORDER = ["Casino", "Sport", "Wheels & cards", "Comms", "Assets", "Tools"]


def generators() -> List[dict]:
    """Every generator, with its file resolved and where it is driven from,
    ordered so a groupby in the template reads Casino-first."""
    out: List[dict] = []
    for g in GENERATORS:
        meta = _file_meta(g["script"]) if g.get("script") else None
        out.append({**g, "file": meta,
                    "where": ("tab" if g.get("tab") else
                              "route" if g.get("route") else "script-only")})
    rank = {name: i for i, name in enumerate(GROUP_ORDER)}
    out.sort(key=lambda g: (rank.get(g["group"], len(rank)), g["label"]))
    return out


def generator_groups() -> List[tuple]:
    """[(group, [generators]), ...] in GROUP_ORDER.

    Grouped here rather than with Jinja's `groupby`, which sorts alphabetically
    and has no `sort=False` on this Jinja version — Assets ended up above Casino.
    """
    grouped: dict = {}
    for g in generators():
        grouped.setdefault(g["group"], []).append(g)
    rank = {name: i for i, name in enumerate(GROUP_ORDER)}
    return sorted(grouped.items(), key=lambda kv: rank.get(kv[0], len(rank)))


def unlisted_generators() -> List[str]:
    """Generator-looking scripts in journey-cloner/ that GENERATORS does not name.

    This is the drift alarm: without it, a new campaign script is invisible in
    the admin and nobody notices until someone asks where it went.
    """
    named = {g.get("script") for g in GENERATORS if g.get("script")}
    found = []
    for p in sorted(CLONER_DIR.glob("*.py")):
        if p.name in named or p.name in _NOT_GENERATORS:
            continue
        found.append(p.name)
    return found
