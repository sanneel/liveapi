# weights_basketball_chile_first.py
# Chile-first basketball weights (patterns are matched via: normalized_pattern in normalized_text)

FORCED_TIMEZONE = "America/Santiago"

# -------------------------
# Hard exclude (non-real / noisy categories)
# -------------------------
EXCLUDE_TOURNAMENT_PATTERNS = [
    # Non-real / virtual / esports
    "virtual",
    "baloncesto virtual",
    "e-baloncesto",
    "e baloncesto",
    "e-basketball",
    "e basketball",
    "esportsbattle",
    "esports",
    "e-sports",
    "cyber",
    "battle",

    # Replay / delayed content
    "replay",
    "replays",
    "match replay",

    # Contests / special events that pollute feed
    "concurso",
    "concurso de triples",
    "tiro de 3 puntos",
    "tiros de 3 puntos",
    "tiro de tres",
    "tiros de tres",

    # Generic prop-style / skills markets often encoded as tournaments
    "3 puntos",
    "triples",
]

# Optional exclude patterns for youth/reserves style (kept for parity with football file)
EXCLUDE_TOURNAMENT_YOUTH_PATTERNS = [
    "u16", "u18", "u20", "u21", "u23",
    "junior", "juniors",
    "sub ", "sub-",
    "reserva", "reservas",
]

# -------------------------
# Tournament / league boosts (order matters: more specific first)
# Matched against tournament.name (and any other concatenated text you use)
# Focus A: premium feed for Chile (NBA + Chile/LatAm top + Euro top), avoid zoo.
# -------------------------
LEAGUE_BOOST_PATTERNS = [
    # ========== NBA (always top) ==========
    ("nba finals", 520),
    ("nba. finals", 520),
    ("finals", 260),                 # small catch (safe, but lower than explicit nba finals)
    ("nba. playoffs", 470),
    ("nba playoffs", 470),
    ("play-in", 360),
    ("play in", 360),
    ("nba. all-star", 220),
    ("nba all-star", 220),
    ("nba. temporada regular", 420),
    ("nba. regular season", 420),
    ("nba", 400),

    # NBA G League is NOT premium; keep low so it doesn't dominate
    ("nba g league", 45),
    ("g league", 35),

    # ========== Chile (brand relevance) ==========
    ("jugabet", 280),
    ("copa jugabet", 280),
    ("liga jugabet", 280),

    # ========== Chile (local relevance) ==========
    # Keep high so it can compete with Euro/LatAm when present.
    ("chile", 220),
    ("liga nacional", 220),
    ("lnb chile", 220),
    ("copa chile", 210),
    ("supercopa", 190),
    ("playoffs chile", 240),

    # ========== LatAm top ==========
    ("bcl americas", 190),
    ("champions league americas", 190),
    ("liga sudamericana", 160),
    ("sudamericana", 160),

    ("argentina. lnb", 170),
    ("argentina lnb", 170),
    ("brasil. nbb", 165),
    ("brasil nbb", 165),

    # ========== Euro top ==========
    ("euroleague", 185),
    ("euroliga", 185),

    ("eurocup", 150),
    ("basketball champions league", 145),
    ("champions league", 120),       # careful: generic, but fine at moderate value
    ("fiba", 80),

    # Big domestic leagues (top tier only)
    ("liga acb", 140),
    ("liga endesa", 140),
    ("acb", 115),

    ("lega a", 130),
    ("serie a", 110),

    ("pro a", 125),
    ("lnb", 70),                      # generic; keep low to avoid Argentina LNB collision

    ("bbl", 110),                     # Germany
    ("bsl", 115),                     # Turkey top league (NOT TBL)

    # ========== NCAA (limit elsewhere; still premium-ish, but capped) ==========
    ("ncaa", 105),

    # ========== De-prioritize common non-premium leagues (keep them surfacing only when needed) ==========
    ("australia. nbl", 35),
    ("australia nbl", 35),

    ("japon. b1", 25),
    ("japon. b2", 20),
    ("japon. b3", 15),
    ("b1-league", 25),
    ("b2-league", 20),
    ("b3-league", 15),

    ("israel. superliga", 30),
    ("israel. liga leumit", 15),

    ("turquía. tbl", 15),
    ("turquia. tbl", 15),
    ("turkey tbl", 15),

    # Friendlies / exhibitions
    ("amistosos", -120),
    ("friendly", -120),
    ("exhibition", -120),

    # Women (premium feed A: keep low, not excluded)
    ("femenino", -70),
    ("women", -70),
    ("wkbl", -70),
    ("wnba", -90),  # if it appears, it's premium-ish, but still less central for Chile-first than NBA
]

# -------------------------
# Team boosts (brands)
# NOTE: Keep the variable name TEAM_BOOST_PATTERNS for compatibility if your scorer expects it.
# These patterns are matched against competitors' names (and any concatenated text you use).
# -------------------------
TEAM_BOOST_PATTERNS = [
    # ========= NBA super-brands =========
    ("los angeles lakers", 90),
    ("golden state warriors", 85),
    ("boston celtics", 80),
    ("chicago bulls", 70),
    ("miami heat", 65),
    ("new york knicks", 60),

    # ========= NBA popular / contenders =========
    ("los angeles clippers", 55),
    ("phoenix suns", 55),
    ("denver nuggets", 55),
    ("milwaukee bucks", 55),
    ("dallas mavericks", 50),
    ("philadelphia 76ers", 50),
    ("brooklyn nets", 45),

    # ========= Euro / LatAm recognizable clubs (light boosts) =========
    ("real madrid", 35),
    ("barcelona", 32),
    ("olympiacos", 30),
    ("panathinaikos", 28),
    ("fenerbahce", 28),
    ("anadolu efes", 26),
    ("maccabi", 22),
    ("partizan", 22),
    ("crvena zvezda", 22),

    ("flamengo", 22),
    ("boca", 18),
    ("river", 18),

    # ========= NCAA flagship programs (small, because NCAA is capped elsewhere) =========
    ("duke", 28),
    ("north carolina", 26),
    ("kentucky", 26),
    ("kansas", 26),
    ("gonzaga", 24),
    ("ucla", 22),
    ("arizona", 22),
    ("purdue", 20),
    ("indiana", 20),
    ("tennessee", 18),

    # ========= Anti-noise: gamer-tag / virtual markers (as team text) =========
    # If your pipeline checks exclude only tournament, these help push them down anyway.
    ("(v)", -200),
    ("(f)", -100),
    ("(virtual)", -200),
    ("(replay)", -200),
]
