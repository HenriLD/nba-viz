"""One-time historical backfill.

Usage:
  python -m ingest.backfill                       # last 5 seasons (full: box + shots + enrich)
  python -m ingest.backfill --n 3
  python -m ingest.backfill --seasons 2021-22 2022-23
  python -m ingest.backfill --start 1980 --end 2020 --box-only   # historical box scores

Run from a residential IP (your own machine) — cloud hosts are often blocked
by stats.nba.com. Expect ~10-20 minutes for 5 full seasons; the historical
box-only range is lighter per season (no 30-call shot pulls).

--box-only pulls only game logs + standings, for seasons that predate
shot-chart and player-tracking data (shots start 1996-97; tracking/hustle/
clutch are 2013-14+). Per-season errors are logged and skipped so one bad
season can't abort a long run; re-running resumes (every write is an upsert).
"""
import argparse
import logging
import sys

from core.seasons import current_season, recent_seasons
from ingest.sync import (sync_defender_shooting, sync_enrich, sync_game_logs,
                         sync_shots, sync_standings, sync_static)

log = logging.getLogger("backfill")


def _season_range(start_year: int, end_year: int) -> list[str]:
    return [f"{y}-{str(y + 1)[-2:]}" for y in range(start_year, end_year + 1)]


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    parser = argparse.ArgumentParser()
    parser.add_argument("--n", type=int, default=5, help="number of recent seasons")
    parser.add_argument("--seasons", nargs="*", default=None,
                        help="explicit season list, e.g. 2021-22 2022-23")
    parser.add_argument("--start", type=int,
                        help="start year for a range, e.g. 1980 (= 1980-81)")
    parser.add_argument("--end", type=int,
                        help="end year for a range, inclusive (default: current)")
    parser.add_argument("--box-only", action="store_true",
                        help="game logs + standings only; skip shots/tracking/enrich "
                             "(for historical seasons that lack that data)")
    args = parser.parse_args()

    if args.start is not None:
        end = args.end if args.end is not None else int(current_season()[:4])
        seasons = _season_range(args.start, end)
    elif args.seasons:
        seasons = args.seasons
    else:
        seasons = recent_seasons(args.n)
    log.info("backfilling %d seasons%s: %s … %s",
             len(seasons), " (box-only)" if args.box_only else "",
             seasons[0], seasons[-1])

    sync_static()
    failed: list[str] = []
    for season in seasons:
        log.info("=== %s ===", season)
        try:
            sync_game_logs(season, full=True)
            if args.box_only:
                # Standings aren't guaranteed for old seasons — best effort.
                try:
                    sync_standings(season)
                except Exception as e:  # noqa: BLE001
                    log.warning("standings unavailable for %s: %s", season, e)
            else:
                sync_shots(season, full=True)
                sync_defender_shooting(season)
                sync_standings(season)
                sync_enrich(season)
        except Exception as e:  # noqa: BLE001 — keep going; resume on re-run
            log.error("season %s failed, skipping: %s", season, e)
            failed.append(season)

    if failed:
        log.warning("backfill done with %d failed seasons: %s", len(failed), failed)
    else:
        log.info("backfill complete (%d seasons)", len(seasons))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
