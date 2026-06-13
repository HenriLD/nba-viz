"""Daily sync: refresh the current season. Idempotent — safe to re-run.

Usage:  python -m ingest.sync
        python -m ingest.sync --full   (re-pull the whole current season)
"""
import argparse
import logging
import sys

import pandas as pd

from core.db import query_df, upsert_df
from core.seasons import current_season
from ingest import endpoints as ep

log = logging.getLogger("sync")

SEASON_TYPES = ["Regular Season", "Playoffs"]


def sync_static() -> None:
    n = upsert_df("players", ep.fetch_static_players(), ["player_id"])
    log.info("players upserted: %s", n)
    n = upsert_df("teams", ep.fetch_static_teams(), ["team_id"])
    log.info("teams upserted: %s", n)


# Tables that support incremental pulls, keyed by where to read the high-water mark.
_INCREMENTAL_TABLES = {"player_game_logs", "team_game_logs", "shots"}


def _date_from(season: str, table: str) -> str | None:
    """Re-pull from 3 days before the latest stored game to catch stat
    corrections. Each table tracks its own high-water mark so a partial
    failure in one sync step can't create a gap in another."""
    assert table in _INCREMENTAL_TABLES  # table name is never user input
    df = query_df(
        f"SELECT max(game_date) AS d FROM {table} WHERE season = :s",
        {"s": season})
    if df.empty or pd.isna(df.loc[0, "d"]):
        return None
    d = pd.Timestamp(df.loc[0, "d"]) - pd.Timedelta(days=3)
    return d.strftime("%m/%d/%Y")


def sync_game_logs(season: str, full: bool = False) -> None:
    for st in SEASON_TYPES:
        try:
            date_from = None if full else _date_from(season, "player_game_logs")
            pgl = ep.fetch_player_game_logs(season, st, date_from=date_from)
            log.info("player logs %s %s (from %s): %s rows", season, st, date_from, len(pgl))
            upsert_df("player_game_logs", pgl, ["player_id", "game_id"])

            date_from = None if full else _date_from(season, "team_game_logs")
            tgl = ep.fetch_team_game_logs(season, st, date_from=date_from)
            log.info("team logs %s %s (from %s): %s rows", season, st, date_from, len(tgl))
            upsert_df("team_game_logs", tgl, ["team_id", "game_id"])
        except Exception:
            # Playoffs endpoint 200s with empty data pre-playoffs; other errors should surface.
            if st == "Playoffs":
                log.info("no playoff data for %s yet", season)
            else:
                raise


def sync_shots(season: str, full: bool = False) -> None:
    for st in SEASON_TYPES:
        date_from = None if full else _date_from(season, "shots")
        df = ep.fetch_shots(season, st, date_from=date_from)
        log.info("shots %s %s (from %s): %s rows", season, st, date_from, len(df))
        upsert_df("shots", df, ["game_id", "game_event_id"])


def sync_defender_shooting(season: str) -> None:
    df = ep.fetch_defender_shooting(season)
    log.info("defender shooting %s: %s rows", season, len(df))
    upsert_df("defender_shooting", df, ["season", "player_id", "def_dist_range"])


def sync_standings(season: str) -> None:
    df = ep.fetch_standings(season)
    upsert_df("standings", df, ["season", "team_id"])
    log.info("standings %s: %s rows", season, len(df))


def sync_enrich(season: str) -> None:
    """Cheap per-player-per-season aggregates: clutch, hustle, defense."""
    n = upsert_df("clutch_stats", ep.fetch_clutch(season), ["season", "player_id"])
    log.info("clutch %s: %s rows", season, n)
    n = upsert_df("hustle_stats", ep.fetch_hustle(season), ["season", "player_id"])
    log.info("hustle %s: %s rows", season, n)
    n = upsert_df("defense_tracking", ep.fetch_defense_tracking(season),
                  ["season", "player_id"])
    log.info("defense %s: %s rows", season, n)


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    parser = argparse.ArgumentParser()
    parser.add_argument("--full", action="store_true",
                        help="re-pull the entire current season instead of incremental")
    parser.add_argument("--season", default=None, help="override season, e.g. 2024-25")
    args = parser.parse_args()

    season = args.season or current_season()
    log.info("syncing season %s", season)

    sync_static()
    sync_game_logs(season, full=args.full)
    sync_shots(season, full=args.full)
    sync_defender_shooting(season)
    sync_standings(season)
    sync_enrich(season)
    log.info("done")
    return 0


if __name__ == "__main__":
    sys.exit(main())
