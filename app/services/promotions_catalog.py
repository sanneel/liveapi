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
    "sport_wof": None,
    "casino_scratch_card": None,
    "casino_wof": None,
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
        "templates/sport/sport_wof_randomizer.json",
        "templates/sport/wof_visual/content-en.json",
        "templates/sport/wof_visual/content-es.json",
        "templates/sport/wof_visual/settings.json",
        "templates/sport/wof_visual/manifest.json",
    ],
    "casino_scratch_card": [
        "templates/casino/raspaygana_scratchcard.json",
    ],
    "casino_wof": [
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
