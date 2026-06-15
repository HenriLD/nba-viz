"""Backfill season-range generation (pure)."""
from ingest.backfill import _season_range


def test_season_range_basic():
    assert _season_range(1980, 1982) == ["1980-81", "1981-82", "1982-83"]


def test_season_range_single():
    assert _season_range(1999, 1999) == ["1999-00"]


def test_season_range_century_rollover():
    assert _season_range(1999, 2001) == ["1999-00", "2000-01", "2001-02"]
