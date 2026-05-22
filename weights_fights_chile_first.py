#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

# =========================================================
# Fight sports weights for Chile / LATAM-oriented HOT scoring
# Covers: UFC, MMA, Boxing
# =========================================================

FORCED_TIMEZONE = "America/Santiago"


# -------------------------
# Hard exclude
# -------------------------
# Drop hypothetical / fake / non-real fights entirely.
HARD_EXCLUDE_TOURNAMENT_PATTERNS = [
    "posibles peleas",
    "posibles",
]

# Optional hard exclude by market name if junk appears in feed.
HARD_EXCLUDE_MARKET_NAME_PATTERNS = [
    "total de asaltos",
    "total asaltos",
    "total rounds",
    "round total",
]

# Keep only clean moneyline-style fight winner markets.
ALLOWED_MARKET_TYPES = {"winner"}


# -------------------------
# Promotion / tournament tiers
# -------------------------
# UFC in your current feed is mostly under generic "Mundo. Pelea",
# so promotion detection should primarily rely on sport == "ufc".
# For generic MMA feeds, tournament name is useful.

TIER1_TOURNAMENT_PATTERNS = [
    "ufc",
    "one championship",
]

TIER2_TOURNAMENT_PATTERNS = [
    "ksw",
    "cage warriors",
    "legacy fighting alliance",
    "lfa",
    "cage fury fc",
    "cffc",
    "bare knuckle fc",
]

TIER3_TOURNAMENT_PATTERNS = [
    "mundo. pelea",
]

# Optional spotlight label seen in boxing feed.
FEATURED_TOURNAMENT_PATTERNS = [
    "luchas destacadas",
]


# -------------------------
# Chile / LATAM / Global stars
# -------------------------
# Keep normalized plain lowercase strings.
# These are helper signals, not the whole ranking system.

CHILE_FIGHTERS = [
    "ignacio bahamondes",
    "vicente luque",
]

LATAM_FIGHTERS = [
    # MMA / UFC
    "brandon moreno",
    "yair rodriguez",
    "alexa grasso",
    "irene aldana",
    "diego lopes",
    "raul rosas",
    "manuel torres",
    "daniel zellhuber",
    "alexandre pantoja",
    "deiveson figueiredo",

    # Boxing
    "canelo",
    "canelo alvarez",
    "jaime munguia",
    "isaac cruz",
    "julio cesar martinez",
    "oscar valdez",
    "leo santa cruz",
    "luis nery",
    "emanuel navarrete",
]

GLOBAL_FIGHT_STARS = [
    "conor mcgregor",
    "jon jones",
    "israel adesanya",
    "alex pereira",
    "khamzat chimaev",
    "islam makhachev",
    "charles oliveira",
    "max holloway",
    "alexander volkanovski",
    "sean omalley",
    "justin gaethje",
    "dustin poirier",
    "tony ferguson",
    "kamaru usman",
    "colby covington",
    "michael chandler",
    "petr yan",
    "tom aspinall",
    "merab dvalishvili",
    "ilia topuria",
    "ciryl gane",
    "francis ngannou",
    "alex pereira",
    "khamzat chimaev",
    "sean strickland",
    "alex pereira",
    "weili zhang",
    "valentina shevchenko",
    "nate diaz",
    "nick diaz",
    "stipe miocic",
    "alexander usyk",  # harmless if ever seen malformed; scorer can ignore
    # Boxing
    "tyson fury",
    "oleksandr usyk",
    "anthony joshua",
    "deontay wilder",
    "terence crawford",
    "errol spence",
    "gervonta davis",
    "ryan garcia",
    "naoya inoue",
    "vasyl lomachenko",
    "shakur stevenson",
    "devin haney",
    "teofimo lopez",
    "artur beterbiev",
    "dmitry bivol",
]


# -------------------------
# Sport-specific baseline preference
# -------------------------
# UFC should usually rank above generic MMA / boxing for Chile-facing HOT,
# unless other signals strongly disagree.

SPORT_BASE_WEIGHTS = {
    "ufc": 95,
    "mma": 75,
    "boxing": 70,
    "other": 60,
}

# Independent of tournament-name tiers. Jugabet labels real UFC events
# `Mundo. Pelea`, which falls into Tier-3 (+0), so the tournament path alone
# leaves UFC only +20 above generic MMA. A dedicated promotion bonus keyed
# on sport=="ufc" guarantees UFC sits above no-name MMA cards.
UFC_PROMOTION_BONUS = 60


# -------------------------
# Numeric weights / bonuses / penalties
# -------------------------

BASE_SCORE = 100

# Promotion quality
TOURNAMENT_TIER1_BONUS = 70
TOURNAMENT_TIER2_BONUS = 35
TOURNAMENT_TIER3_BONUS = 0
FEATURED_TOURNAMENT_BONUS = 35

# Fighter popularity
CHILE_FIGHTER_BONUS = 120
LATAM_FIGHTER_BONUS = 65
GLOBAL_FIGHT_STAR_BONUS = 50

# Extra boost if both sides are relevant.
BOTH_CHILE_FIGHTERS_BONUS = 80
BOTH_LATAM_FIGHTERS_BONUS = 45
BOTH_GLOBAL_STARS_BONUS = 35
CROSSOVER_BIG_FIGHT_BONUS = 25  # both sides matched in any non-empty star bucket

# Event timing
STARTS_TODAY_BONUS = 45
STARTS_TOMORROW_BONUS = 25
STARTS_WITHIN_2_DAYS_BONUS = 10
STARTS_WITHIN_4_DAYS_BONUS = 0

# Live handling
# Right now your live feeds can still return prematch items,
# so scorer should trust event.status first.
LIVE_BONUS = 40

# Odds / competitiveness
ODDS_COINFLIP_BONUS = 35       # abs diff <= 0.15
ODDS_CLOSE_BONUS = 22          # abs diff <= 0.35
ODDS_DECENT_BONUS = 10         # abs diff <= 0.60

ODDS_HEAVY_FAVORITE_PENALTY = 0    # best odd <= 1.25
ODDS_EXTREME_FAVORITE_PENALTY = 0  # best odd <= 1.15
ODDS_ABSURD_FAVORITE_PENALTY = 0   # best odd <= 1.08

# Additional longshot mismatch guard based on bigger price.
LONGSHOT_5_PLUS_PENALTY = 0
LONGSHOT_8_PLUS_PENALTY = 0
LONGSHOT_10_PLUS_PENALTY = 0


# -------------------------
# Anti-spam constraints
# -------------------------
MAX_PER_FIGHTER = 1
MAX_PER_TOURNAMENT = 3
MAX_PER_SPORT = 3