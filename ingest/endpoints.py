"""Thin wrappers around nba_api endpoints with retries and polite pacing.

stats.nba.com is rate-limit sensitive and blocks many cloud datacenter IPs.
Every call here sleeps briefly and retries with backoff; if you see persistent
timeouts from a cloud host, run the ingest from a residential IP instead
(see README: "Where to run ingest").
"""
import logging
import time

import pandas as pd
from nba_api.stats.endpoints import (
    leaguedashplayerptshot,
    leaguegamelog,
    leaguestandingsv3,
    playergamelogs,
    shotchartdetail,
)
from nba_api.stats.static import players as static_players
from nba_api.stats.static import teams as static_teams
from tenacity import retry, stop_after_attempt, wait_exponential

log = logging.getLogger(__name__)

PACE_SECONDS = 1.5   # pause between requests
TIMEOUT = 90

DEF_DIST_RANGES = [
    "0-2 Feet - Very Tight",
    "2-4 Feet - Tight",
    "4-6 Feet - Open",
    "6+ Feet - Wide Open",
]


def _pace():
    time.sleep(PACE_SECONDS)


def _norm(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df.columns = [c.lower() for c in df.columns]
    return df


_retry = retry(stop=stop_after_attempt(4),
               wait=wait_exponential(multiplier=2, min=2, max=60),
               reraise=True)


def fetch_static_players() -> pd.DataFrame:
    rows = static_players.get_players()
    df = pd.DataFrame(rows).rename(columns={"id": "player_id"})
    return df[["player_id", "full_name", "first_name", "last_name", "is_active"]]


def fetch_static_teams() -> pd.DataFrame:
    rows = static_teams.get_teams()
    df = pd.DataFrame(rows).rename(columns={"id": "team_id"})
    return df[["team_id", "abbreviation", "nickname", "city", "full_name"]]


@_retry
def fetch_team_game_logs(season: str, season_type: str = "Regular Season") -> pd.DataFrame:
    _pace()
    df = _norm(leaguegamelog.LeagueGameLog(
        season=season, season_type_all_star=season_type,
        timeout=TIMEOUT).get_data_frames()[0])
    df["season"] = season
    df["season_type"] = season_type
    df["game_date"] = pd.to_datetime(df["game_date"]).dt.date
    return df


@_retry
def fetch_player_game_logs(season: str, season_type: str = "Regular Season",
                           date_from: str | None = None) -> pd.DataFrame:
    """date_from format: MM/DD/YYYY (stats.nba.com convention)."""
    _pace()
    df = _norm(playergamelogs.PlayerGameLogs(
        season_nullable=season, season_type_nullable=season_type,
        date_from_nullable=date_from, timeout=TIMEOUT).get_data_frames()[0])
    df["season"] = season
    df["season_type"] = season_type
    df["game_date"] = pd.to_datetime(df["game_date"]).dt.date
    return df


@_retry
def _fetch_team_shots(team_id: int, season: str, season_type: str) -> pd.DataFrame:
    _pace()
    return _norm(shotchartdetail.ShotChartDetail(
        team_id=team_id, player_id=0,
        season_nullable=season, season_type_all_star=season_type,
        context_measure_simple="FGA", timeout=TIMEOUT).get_data_frames()[0])


def fetch_shots(season: str, season_type: str = "Regular Season") -> pd.DataFrame:
    """Shot chart detail, fetched per team.

    A league-wide call (team_id=0, player_id=0) silently truncates at 102,400
    rows — roughly half a regular season — so we make 30 team-scoped calls
    (~7k rows each) instead.
    """
    frames = []
    for t in static_teams.get_teams():
        log.info("shots %s %s %s", season, season_type, t["abbreviation"])
        frames.append(_fetch_team_shots(t["id"], season, season_type))
    df = pd.concat(frames, ignore_index=True)
    df["season"] = season
    df["season_type"] = season_type
    df["game_date"] = pd.to_datetime(df["game_date"], format="%Y%m%d").dt.date
    return df


@_retry
def _fetch_defender_bucket(season: str, bucket: str) -> pd.DataFrame:
    _pace()
    df = _norm(leaguedashplayerptshot.LeagueDashPlayerPtShot(
        season=season, season_type_all_star="Regular Season",
        close_def_dist_range_nullable=bucket, timeout=TIMEOUT).get_data_frames()[0])
    df["season"] = season
    df["def_dist_range"] = bucket
    return df


def fetch_defender_shooting(season: str) -> pd.DataFrame:
    frames = []
    for bucket in DEF_DIST_RANGES:
        log.info("defender bucket %s %s", season, bucket)
        frames.append(_fetch_defender_bucket(season, bucket))
    return pd.concat(frames, ignore_index=True)


@_retry
def fetch_standings(season: str) -> pd.DataFrame:
    _pace()
    df = _norm(leaguestandingsv3.LeagueStandingsV3(
        season=season, timeout=TIMEOUT).get_data_frames()[0])
    df = df.rename(columns={"teamid": "team_id", "teamcity": "team_city",
                            "teamname": "team_name", "playoffrank": "playoff_rank",
                            "winpct": "win_pct"})
    df["season"] = season
    return df
