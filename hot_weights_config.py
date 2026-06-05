# hot_weights_config.py
#
# Central tunable weights for the football hot scorer (/hot/football.png + cubes).
# Edit any number here, restart the server, and the next parser cycle will
# re-rank every match using the new weights.
#
# DO NOT put pattern lists here — those live in `weights_chile_first.py`.
# This file is ONLY the dial-tunable numeric constants the scorer uses.

from __future__ import annotations


# ─── Time horizon ────────────────────────────────────────────────────────
# Prematch matches starting more than this many days in the future are
# dropped before scoring. Increase to 7 if you want a week-ahead view.
HORIZON_DAYS: int = 4


# ─── Time-to-match boost ─────────────────────────────────────────────────
# The closer kickoff is, the higher the boost. Set any of these to 0 to
# disable a bucket; nothing else needs to change.
TIME_BOOST_WITHIN_6H:  int = 60
TIME_BOOST_WITHIN_24H: int = 55
TIME_BOOST_WITHIN_48H: int = 50
TIME_BOOST_WITHIN_72H: int = 45
TIME_BOOST_WITHIN_96H: int = 35


# ─── Live boost ──────────────────────────────────────────────────────────
# Bonus added to a match's score when it's currently being played.
# Set to 0 by operator request: a live match should NOT auto-pin above
# prematch — ranking is driven by league/team/word relevance, not by the
# match merely being in-play. Raise this if you want live games to surface.
LIVE_BOOST: int = 0

# When True, the LIVE_BOOST is only applied if the match already earned
# points from a league or team boost. This prevents a random Estonian
# 3rd-division game from outranking a Real Madrid prematch just because
# it happens to be live right now.
LIVE_BOOST_REQUIRES_PRIORITY: bool = True


# ─── Diversity caps (applied AFTER scoring, during top-N pick) ───────────
# Max number of LIVE matches allowed in the top-N result.
MAX_LIVE: int = 2

# Max matches from the same tournament. Stops 5 games of the same league
# from monopolising the leaderboard.
MAX_PER_TOURNAMENT: int = 2

# Max times the same team can appear (across home/away). Usually 1.
MAX_PER_TEAM: int = 1

# Force at least N prematch matches in the result. If after scoring there
# are too few, the picker swaps the weakest live match for the best
# unselected prematch.
REQUIRE_MIN_PREMATCH: int = 2


# ─── Exclusions ──────────────────────────────────────────────────────────
# When True, U19/U20/U21/U23/sub/juvenil matches are dropped.
EXCLUDE_YOUTH: bool = True

# NOTE: Per-league / per-team point weights (including TEMPORARY, time-limited
# boosts) are no longer configured here. They live in the DB `hot_weight`
# table and are managed from the admin "Weights" page (/admin/weights), which
# supports an optional start/end window so a boost expires on its own.
