# weights_tennis_chile_first.py
# Chile-first tennis weights (patterns are matched via: normalized_pattern in normalized_text)

FORCED_TIMEZONE = "America/Santiago"

# -------------------------
# Hard exclude (non-real / noisy categories)
# -------------------------
EXCLUDE_TOURNAMENT_PATTERNS = [
    # Non-real / virtual / esports
    "virtual",
    "e-tennis",
    "etennis",
    "simulated",
    "simulation",
    "esports",
    "e-sports",
    "cyber",
    "battle",

    # Exhibition / show
    "exhibition",
    "showmatch",
    "friendly",

    # Youth / juniors
    "junior",
    "juniors",
    "u16",
    "u18",
    "u20",

    # Optional: keep or remove depending on desired feed
    # "wheelchair",
]

# Optional exclude patterns for youth/reserves style (kept for parity with football file)
EXCLUDE_TOURNAMENT_YOUTH_PATTERNS = [
    "u16", "u18", "u20",
    "junior", "juniors",
]

# -------------------------
# Tournament / tour boosts (order matters: more specific first)
# Matched against tournament.name (and any other concatenated text you use)
# -------------------------
LEAGUE_BOOST_PATTERNS = [
    # ========== Top global events ==========
    ("juegos olimpicos", 430),
    ("olympics", 430),

    ("australian open", 420),
    ("roland garros", 420),
    ("french open", 420),
    ("wimbledon", 420),
    ("us open", 420),
    ("grand slam", 420),

    # Team competitions
    ("copa davis", 300),
    ("davis cup", 300),
    ("billie jean king cup", 290),
    ("fed cup", 290),

    # Tour Finals / big invitationals
    ("atp finals", 300),
    ("tour finals", 300),
    ("wta finals", 290),

    ("united cup", 160),
    ("laver cup", 160),
    ("hopman cup", 140),
    ("next gen", 160),

    # ========== Chile / LatAm geo boosts (small, additive) ==========
    # Not meant to replace tier, only to give local relevance bump
    ("santiago", 80),
    ("chile", 60),

    ("rio de janeiro", 35),
    ("buenos aires", 35),
    ("acapulco", 30),
    ("sao paulo", 25),
    ("sa o paulo", 25),
    ("lima", 25),
    ("bogota", 20),
    ("quito", 20),
    ("montevideo", 20),

    # ========== ATP tiers ==========
    ("atp masters", 280),
    ("masters 1000", 280),
    ("atp 1000", 280),

    ("atp 500", 240),
    ("atp 250", 210),

    # Catch-all ATP (covers: "ATP. Doha. Dura", "ATP. Río de Janeiro. Arcilla", etc.)
    ("atp.", 200),

    # ========== WTA tiers ==========
    ("wta 1000", 270),
    ("wta 500", 235),
    ("wta 250", 205),

    # Catch-all WTA (covers: "WTA. Dubái. Dura", etc.)
    ("wta.", 195),

    # ========== Challenger / 220K ==========
    ("atp challenger", 220),
    ("challenger", 190),
    ("atp.", 200),

    ("wta 125", 120),
    ("125k", 120),
    ("wta125", 120),

    # ========== ITF ==========
    # Keep low so it doesn't dominate; can still surface if odds are very close or Chile player involved
    ("itf. masculino", 40),
    ("itf. femenino", 40),
    ("itf.", 40),
    ("itf", 40),

    # ========== Doubles / Dobles modifier ==========
    # In your source it appears as "Dobles" inside tournament name
    ("dobles", -70),
    ("doubles", -70),
]

# -------------------------
# Player boosts (Chile first + LatAm + global stars)
# NOTE: Keep the variable name TEAM_BOOST_PATTERNS for compatibility if your scorer expects it.
# These patterns are matched against competitors' names (and any concatenated text you use).
# -------------------------
TEAM_BOOST_PATTERNS = [
    # ========= Chile BIG (strongest local relevance) =========
    ("nicolas jarry", 260),
    ("cristian garin", 230),
    ("alejandro tabilo", 230),
    ("tomas barrios", 170),
    ("barrios vera", 170),

    # (Optional) add more Chile players as they appear in your feed
    # ("gonzalo lama", 90),
    # ("guillermo nunez", 90),

    # ========= LatAm notable (moderate boost) =========
    # Argentina
    ("sebastian baez", 80),
    ("francisco cerundolo", 80),
    ("juan manuel cerundolo", 60),
    ("tomas martin etcheverry", 65),

    # Brazil
    ("thiago seyboth wild", 60),
    ("thiago monteiro", 55),
    ("joao fonseca", 65),

    # Others (add as needed)
    ("carlos sanchez jover", 35),   # appears in your sample (if you want)
    ("gonzalo villanueva", 35),     # appears in your sample (if you want)

    # ========= Global ATP stars (smaller than Chile BIG) =========
    ("novak djokovic", 90),
    ("carlos alcaraz", 90),
    ("jannik sinner", 85),
    ("daniil medvedev", 80),
    ("alexander zverev", 75),
    ("andrey rublev", 70),
    ("casper ruud", 70),
    ("taylor fritz", 65),
    ("matteo berrettini", 65),

    # ========= Global WTA stars =========
    ("iga swiatek", 90),
    ("aryna sabalenka", 85),
    ("cori gauff", 80),
    ("coco gauff", 80),
    ("elena rybakina", 75),
    ("jessica pegula", 70),
    ("elina svitolina", 65),
    ("amanda anisimova", 55),
]
