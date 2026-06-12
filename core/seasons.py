"""Season string helpers. NBA seasons are formatted '2024-25'."""
from datetime import date


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
