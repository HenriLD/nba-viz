"""Stat whitelist (pure)."""
import pytest

from core.stats import stat_label, validate_stat


def test_validate_known_stats():
    assert validate_stat("pts") == "pts"
    assert validate_stat("fg_pct") == "fg_pct"


@pytest.mark.parametrize("bad", ["dunks", "PTS", "points", "", "drop"])
def test_validate_unknown_stat_raises(bad):
    with pytest.raises(ValueError):
        validate_stat(bad)


def test_stat_labels():
    assert stat_label("pts") == "Points"
    assert stat_label("fg3_pct") == "3-Point %"


def test_stat_label_unknown_raises():
    with pytest.raises(ValueError):
        stat_label("nope")
