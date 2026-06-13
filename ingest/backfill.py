"""One-time historical backfill for recent seasons.

Usage:  python -m ingest.backfill            # last 5 seasons
        python -m ingest.backfill --n 3
        python -m ingest.backfill --seasons 2021-22 2022-23

Run this from a residential IP (your own machine) — cloud hosts are often
blocked by stats.nba.com. Expect ~10-20 minutes for 5 seasons.
"""
import argparse
import logging
import sys

from core.seasons import recent_seasons
from ingest.sync import (sync_defender_shooting, sync_enrich, sync_game_logs,
                         sync_shots, sync_standings, sync_static)

log = logging.getLogger("backfill")


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    parser = argparse.ArgumentParser()
    parser.add_argument("--n", type=int, default=5, help="number of recent seasons")
    parser.add_argument("--seasons", nargs="*", default=None)
    args = parser.parse_args()

    seasons = args.seasons or recent_seasons(args.n)
    log.info("backfilling: %s", seasons)

    sync_static()
    for season in seasons:
        log.info("=== %s ===", season)
        sync_game_logs(season, full=True)
        sync_shots(season, full=True)
        sync_defender_shooting(season)
        sync_standings(season)
        sync_enrich(season)
    log.info("backfill complete")
    return 0


if __name__ == "__main__":
    sys.exit(main())
