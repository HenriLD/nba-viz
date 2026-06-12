"""Whitelisted stat names. The agent only ever passes these keys, never raw SQL.

SIMPLE_STATS map directly to numeric columns on *_game_logs and can be averaged.
RATIO_STATS must be computed as sum(numerator)/sum(denominator) when aggregating.
"""

SIMPLE_STATS = {
    "pts": "Points",
    "reb": "Rebounds",
    "ast": "Assists",
    "stl": "Steals",
    "blk": "Blocks",
    "tov": "Turnovers",
    "min": "Minutes",
    "fg3m": "3-Pointers Made",
    "plus_minus": "Plus/Minus",
}

RATIO_STATS = {
    "fg_pct":  ("fgm", "fga", "Field Goal %"),
    "fg3_pct": ("fg3m", "fg3a", "3-Point %"),
    "ft_pct":  ("ftm", "fta", "Free Throw %"),
}

ALL_STATS = list(SIMPLE_STATS) + list(RATIO_STATS)


def stat_label(stat: str) -> str:
    if stat in SIMPLE_STATS:
        return SIMPLE_STATS[stat]
    if stat in RATIO_STATS:
        return RATIO_STATS[stat][2]
    raise ValueError(f"Unknown stat: {stat}")


def validate_stat(stat: str) -> str:
    if stat not in SIMPLE_STATS and stat not in RATIO_STATS:
        raise ValueError(f"Unknown stat '{stat}'. Valid: {', '.join(ALL_STATS)}")
    return stat
