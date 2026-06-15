"""Season string helpers (pure, no DB)."""
from datetime import date

import pytest

from core.seasons import current_season, recent_seasons, validate_season


def test_current_season_before_october():
    assert current_season(date(2025, 1, 15)) == "2024-25"


def test_current_season_on_october_start():
    assert current_season(date(2025, 10, 1)) == "2025-26"


def test_recent_seasons_ascending():
    assert recent_seasons(3, date(2025, 11, 1)) == ["2023-24", "2024-25", "2025-26"]


def test_recent_seasons_century_rollover():
    assert recent_seasons(2, date(2001, 11, 1)) == ["2000-01", "2001-02"]


def test_validate_season_ok():
    assert validate_season("1984-85") == "1984-85"


@pytest.mark.parametrize("bad", ["1984", "84-85", "1984-1985", "abcd-ef", ""])
def test_validate_season_rejects_malformed(bad):
    with pytest.raises(ValueError):
        validate_season(bad)
