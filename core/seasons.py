"""Season string helpers. NBA seasons are formatted '2024-25'."""
from datetime import date
from functools import lru_cache


@lru_cache(maxsize=1)
def available_seasons() -> list[str]:
    """Seasons actually present in the database, ascending. Cached for the
    process lifetime (a new season only appears after a restart/redeploy)."""
    from core.db import query_df
    df = query_df("SELECT DISTINCT season FROM player_game_logs ORDER BY season")
    return df["season"].tolist()


def latest_season() -> str:
    """The current season grounded in the data: the newest season we actually
    hold rows for. Falls back to the calendar if the DB is empty/unreachable."""
    try:
        seas = available_seasons()
        if seas:
            return seas[-1]
    except Exception:  # noqa: BLE001 — DB not ready (e.g. unit context)
        pass
    return current_season()


def current_season(today: date | None = None) -> str:
    today = today or date.today()
    # New season starts in October.
    start_year = today.year if today.month >= 10 else today.year - 1
    return f"{start_year}-{str(start_year + 1)[-2:]}"


def recent_seasons(n: int = 5, today: date | None = None) -> list[str]:
    cur = current_season(today)
    start = int(cur[:4])
    return [f"{y}-{str(y + 1)[-2:]}" for y in range(start - n + 1, start + 1)]


def validate_season(season: str) -> str:
    import re
    if not re.fullmatch(r"\d{4}-\d{2}", season):
        raise ValueError(f"Season must look like '2024-25', got '{season}'")
    return season
