# weights_chile_first.py football
# Chile-first weights (patterns are matched via: normalized_pattern in normalized_text)

FORCED_TIMEZONE = "America/Santiago"

# Hard exclude (virtual/esports/replays etc.)
EXCLUDE_TOURNAMENT_PATTERNS = [
    "e-futbol",
    "futbol virtual",
    "virtual ecomp",
    "esportsbattle",
    "e-sports",
    "esports",
    "vsl",
    "replays",
    "virtual",
    "simulated",
    "cyber",
    "battle",
]

# Optional exclude for youth/reserves (enable if you want to be strict)
EXCLUDE_TOURNAMENT_YOUTH_PATTERNS = [
    "u19", "u20", "u21", "u23",
    "sub ", "sub-", "juvenil", "juveniles", "res.",
]

# League boosts (order matters: more specific first)
LEAGUE_BOOST_PATTERNS = [
    # Chile FIRST
    ("chile primera division", 320),
    ("chile copa", 230),

    # LatAm important for Chile audience
    ("america del sur copa libertadores", 280),
    ("copa libertadores", 280),
    ("conmebol libertadores", 280),

    ("conmebol sudamericana", 270),
    ("copa sudamericana", 270),
    ("america del sur copa sudamericana", 270),

    #Copa del Mundo FIFA
    ("copa del mundo fifa", 250),
    ("fifa copa del mundo", 250),

    # UEFA Champions League:
    # In your prematch it appears as "Europa. Femenino. UEFA Champions League"
    ("femenino uefa champions league", 130),
    ("uefa champions league", 240),  # keep for men's UCL when it appears

    ("argentina liga profesional", 170),
    ("brasil serie a", 160),
    ("brasil campeonato paulista a1", 155),
    ("peru liga 1", 130),
    ("uruguay primera division", 130),

    # Europe top (below Chile in this model)
    ("inglaterra premier league", 200),
    ("premier league", 200),

    ("espana laliga", 210),
    ("laliga", 210),

    ("italia serie a", 170),
    ("alemania bundesliga", 160),
    ("francia ligue 1", 140),
    ("portugal primeira liga", 120),

    # Cups seen in prematch.json
    ("espana copa del rey", 180),
    ("copa del rey", 180),
    ("inglaterra copa fa", 140),
    ("copa fa", 140),

    # UEFA Europa League:
    ("uefa europa league", 170),
    ("femenino uefa europa league", 70),

    #UEFA Conference League:
    ("uefa conference league", 140),
    ("femenino uefa conference league", 40),

]

# Team boosts (Chile first + selected worldwide)
TEAM_BOOST_PATTERNS = [
    # Chile big
    ("colo colo", 320),
    ("csd colo colo", 320),
    ("universidad de chile", 280),
    ("universidad catolica", 220),

    # Chile (seen in prematch.json)
    ("cd palestino", 120),
    ("palestino", 100),
    ("o'higgins", 90),
    ("ohiggins", 90),

    # Worldwide giants (seen in prematch.json)
    ("real madrid", 160),
    ("barcelona", 150),

    ("arsenal", 120),
    ("man city", 120),
    ("manchester city", 120),
    ("liverpool", 120),
    ("chelsea", 110),

    ("juventus", 110),
    ("ac milan", 105),
    ("inter milan", 105),

    ("psg", 105),
    ("paris saint germain", 105),

    ("bayern munchen", 105),
    ("bayern", 105),

    ("atletico madrid", 100),
]
