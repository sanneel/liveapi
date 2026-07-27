#weights_cybersport_chile.py
#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

# =========================================================
# Cybersport weights for Chile / LATAM-oriented HOT scoring
# =========================================================

FORCED_TIMEZONE = "America/Santiago"


# -------------------------
# Hard exclude
# -------------------------
# These should be dropped entirely, not penalized.
HARD_EXCLUDE_TOURNAMENT_PATTERNS = [
    "duelo de jugadores",
    "asesinatos",
    "kills",
    "jugador",
    "player",
    "players",
    "player props",
    "headshots",
    "first blood",
    "first kill",
    "total mapa",
    "total. mapa",
    "map kills",
    "mapa kills",
]

HARD_EXCLUDE_MARKET_NAME_PATTERNS = [
    "total",
    "total mapa",
    "total. mapa",
    "kills",
    "asesinatos",
    "más de",
    "mas de",
    "menos de",
    "over",
    "under",
]

# Keep only proper match-winner markets in scorer.
ALLOWED_MARKET_TYPES = {"winner"}


# -------------------------
# Penalty patterns
# -------------------------
ACADEMY_PATTERNS = [
    "academy",
    "junior",
    "juniors",
    "nxt",
    "prodigy",
    "youth",
    "u18",
    "u19",
    "u20",
    "u21",
]

QUALIFIER_PATTERNS = [
    "qualifier",
    "qualifiers",
    "closed qualifier",
    "open qualifier",
    "play-in",
    "play in",
    "relegation",
]

LOW_SIGNAL_FORMAT_PATTERNS = [
    "2x2",
    "1x1",
]

MOBILE_LOW_PRIORITY_PATTERNS = [
    "honor of kings",
    "mobile legends",
    "free fire",
    "wild rift",
]


# -------------------------
# Game detection
# -------------------------
GAME_NAME_PATTERNS = {
    "cs": [
        "counter-strike",
        "cs2",
        "cs go",
        "cs:go",
    ],
    "lol": [
        "league of legends",
        "lol",
    ],
    "valorant": [
        "valorant",
    ],
    "dota": [
        "dota 2",
        "dota2",
        "dota",
    ],
    "mobile": [
        "honor of kings",
        "mobile legends",
        "free fire",
        "wild rift",
    ],
}

GAME_WEIGHTS = {
    "cs": 80,
    "lol": 75,
    "valorant": 70,
    "dota": 65,
    "mobile": 30,
    "other": 40,
}


# -------------------------
# Tournament tiers
# -------------------------
# Tier 1 = strong global / flagship events
TIER1_TOURNAMENT_PATTERNS = [
    # CS
    "major",
    "iem",
    "blast",
    "esl pro league",
    "thunderpick world championship",

    # LoL
    "worlds",
    "world championship",
    "msi",
    "lck",
    "lec",
    "lpl",
    "lta",
    "lcs",

    # Valorant
    "vct champions",
    "vct masters",
    "champions",
    "masters",

    # Dota
    "the international",
    "dreamleague",
    "riyadh masters",
]

TIER2_TOURNAMENT_PATTERNS = [
    # CS
    "cct",
    "esl challenger",
    "yalla compass",
    "res regional",
    "res showdown",

    # LoL
    "emea masters",
    "challengers",
    "superliga",
    "prime league",
    "liga regional",

    # Valorant
    "challengers las",
    "challengers lan",
    "challengers latam",
    "valorant challengers",

    # Dota
    "pgl",
    "esl one",
    "cct",
]

TIER3_TOURNAMENT_PATTERNS = [
    "roman imperium",
    "aorus",
    "bb storm",
    "exort",
    "bcg masters",
    "wildcard lan",
    "united21",
    "winners series",
    "epl world series",
    "cis lan championship",
    "dfrag",
]


# -------------------------
# Team popularity
# -------------------------
# Global brands / high recognition
POPULAR_TEAMS = [
    # CS / multi-title
    "natus vincere",
    "navi",
    "g2",
    "team liquid",
    "liquid",
    "faze",
    "vitality",
    "fnatic",
    "cloud9",
    "heroic",
    "spirit",
    "aurora",
    "the mongolz",
    "mongolz",
    "nip",
    "eyeballers",
    "saw",

    # LoL
    "t1",
    "gen g",
    "geng",
    "g2 esports",
    "karmine corp",
    "los heretics",

    # Dota
    "tundra",
    "team falcons",
    "falcons",
    "team spirit",

    # Valorant / multi-title
    "sentinels",
    "paper rex",
    "drx",
]

# LATAM / Iberia-adjacent teams that can matter more for Chile-facing interest
LATAM_TEAMS = [
    "9z",
    "furia",
    "loud",
    "mibr",
    "krü",
    "kru",
    "leviatan",
    "leviatán",
    "bestia",
    "keyd stars",
    "fluxo",
    "pain",
    "paiN",
    "imperial",
    "isurus",
]


# -------------------------
# Numeric weights / penalties
# -------------------------
TOURNAMENT_TIER1_BONUS = 80
TOURNAMENT_TIER2_BONUS = 40
TOURNAMENT_TIER3_PENALTY = -50

POPULAR_TEAM_BONUS = 50
LATAM_TEAM_BONUS = 60

ACADEMY_PENALTY = -45
QUALIFIER_PENALTY = -20
LOW_SIGNAL_FORMAT_PENALTY = -40
MOBILE_LOW_PRIORITY_PENALTY = -50

LIVE_BONUS = 50
LIVE_GENERIC_STAGE_BONUS = 20

MAP_STAGE_BONUS = {
    1: 10,
    2: 25,
    3: 40,
    4: 50,
    5: 50,
}

ODDS_COINFLIP_BONUS = 20       # abs diff < 0.30
ODDS_CLOSE_BONUS = 10          # abs diff < 0.50
ODDS_HEAVY_FAVORITE_PENALTY = -30   # <= 1.20
ODDS_EXTREME_FAVORITE_PENALTY = -55 # <= 1.15


# -------------------------
# Anti-spam constraints
# -------------------------
MAX_PER_TEAM = 1
MAX_PER_TOURNAMENT = 2
BASE_SCORE = 100