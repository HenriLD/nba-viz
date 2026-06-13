"""Human-readable labels for db columns and model-chosen SQL aliases.

The curated templates already set nice axis titles; this mainly cleans up the
flexible query path, where axis/table labels come straight from SQL column
names (e.g. 'avg_point_margin' -> 'Avg Point Margin', 'fg3_pct' -> '3PT%').
"""
import re

# Exact matches win first — canonical db columns and common aliases.
FIELD_LABELS = {
    "pts": "Points", "reb": "Rebounds", "ast": "Assists", "stl": "Steals",
    "blk": "Blocks", "tov": "Turnovers", "pf": "Fouls", "min": "Minutes",
    "plus_minus": "Plus/Minus", "ppg": "PPG", "rpg": "RPG", "apg": "APG",
    "fg_pct": "FG%", "fg3_pct": "3PT%", "ft_pct": "FT%", "efg_pct": "eFG%",
    "fg2_pct": "2PT%",
    "fgm": "FG Made", "fga": "FG Att", "fg3m": "3PT Made", "fg3a": "3PT Att",
    "fg2m": "2PT Made", "fg2a": "2PT Att", "ftm": "FT Made", "fta": "FT Att",
    "oreb": "Off. Rebounds", "dreb": "Def. Rebounds",
    "opp_pts": "Opponent Points", "margin": "Point Margin",
    "win_pct": "Win %", "days_rest": "Days Rest", "game_no": "Game Number",
    "game_date": "Date", "opponent": "Opponent", "team": "Team",
    "season": "Season", "season_type": "Season Type", "is_home": "Home/Away",
    "won": "Won", "wl": "W/L", "player_name": "Player", "team_abbreviation": "Team",
    "wins": "Wins", "losses": "Losses", "gp": "Games", "matchup": "Matchup",
    "shot_distance": "Shot Distance (ft)", "shot_zone_basic": "Zone",
    "period": "Period", "made": "Made", "is_three": "Three?",
    "conference": "Conference", "playoff_rank": "Seed",
}

# Token-level expansions for prettifying arbitrary aliases.
_TOKENS = {
    "pct": "%", "fg3": "3PT", "fg2": "2PT", "fg": "FG", "ft": "FT",
    "3pt": "3PT", "2pt": "2PT", "3p": "3PT", "2p": "2PT",
    "pts": "Points", "reb": "Rebounds", "ast": "Assists", "stl": "Steals",
    "blk": "Blocks", "tov": "Turnovers", "ppg": "PPG", "rpg": "RPG", "apg": "APG",
    "avg": "Avg", "opp": "Opp", "def": "Def", "off": "Off", "pct.": "%",
    "min": "Min", "max": "Max", "num": "Number", "no": "Number", "diff": "Diff",
    "vs": "vs", "id": "ID", "ot": "OT", "efg": "eFG", "ts": "TS",
}


def prettify(name: str | None) -> str:
    if not name:
        return name or ""
    key = name.strip().lower()
    if key in FIELD_LABELS:
        return FIELD_LABELS[key]
    tokens = re.split(r"[_\s]+", key)
    out = [_TOKENS.get(t, t.capitalize()) for t in tokens if t]
    label = " ".join(out)
    # Tidy "3PT %" -> "3PT%", "FG %" -> "FG%"
    return re.sub(r"\b(FG|3PT|2PT|FT|eFG|TS)\s+%", r"\1%", label)
