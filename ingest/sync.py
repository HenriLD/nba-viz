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


def _date_from(season: str) -> str | None:
    """Re-pull from 3 days before the latest stored game to catch stat corrections."""
    df = query_df(
        "SELECT max(game_date) AS d FROM player_game_logs WHERE season = :s",
        {"s": season})
    if df.empty or pd.isna(df.loc[0, "d"]):
        return None
    d = pd.Timestamp(df.loc[0, "d"]) - pd.Timedelta(days=3)
    return d.strftime("%m/%d/%Y")


def sync_game_logs(season: str, full: bool = False) -> None:
    date_from = None if full else _date_from(season)
    for st in SEASON_TYPES:
        try:
            pgl = ep.fetch_player_game_logs(season, st, date_from=date_from)
            log.info("player logs %s %s (from %s): %s rows", season, st, date_from, len(pgl))
            upsert_df("player_game_logs", pgl, ["player_id", "game_id"])

            tgl = ep.fetch_team_game_logs(season, st)
            log.info("team logs %s %s: %s rows", season, st, len(tgl))
            upsert_df("team_game_logs", tgl, ["team_id", "game_id"])
        except Exception:
            # Playoffs endpoint 200s with empty data pre-playoffs; other errors should surface.
            if st == "Playoffs":
                log.info("no playoff data for %s yet", season)
            else:
                raise


def sync_shots(season: str) -> None:
    for st in SEASON_TYPES:
        df = ep.fetch_shots(season, st)
        log.info("shots %s %s: %s rows", season, st, len(df))
        upsert_df("shots", df, ["game_id", "game_event_id"])


def sync_defender_shooting(season: str) -> None:
    df = ep.fetch_defender_shooting(season)
    log.info("defender shooting %s: %s rows", season, len(df))
    upsert_df("defender_shooting", df, ["season", "player_id", "def_dist_range"])


def sync_standings(season: str) -> None:
    df = ep.fetch_standings(season)
    upsert_df("standings", df, ["season", "team_id"])
    log.info("standings %s: %s rows", season, len(df))


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
    sync_shots(season)            # full-season pull; upsert dedupes
    sync_defender_shooting(season)
    sync_standings(season)
    log.info("done")
    return 0


if __name__ == "__main__":
    sys.exit(main())
