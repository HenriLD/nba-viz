"""Entity resolution core: folding + fuzzy/alias matching against a synthetic
index (so no DB is needed)."""
import pytest

from app.entities import EntityNotFound, Player, _fold, _resolve


def test_fold_strips_diacritics_and_case():
    assert _fold("Jokić") == "jokic"
    assert _fold("Dončić") == "doncic"
    assert _fold("  LeBron  ") == "lebron"


def _index():
    return {
        "stephen curry": Player(201939, "Stephen Curry", True),
        "seth curry": Player(212, "Seth Curry", True),
        "michael jordan": Player(23, "Michael Jordan", False),
    }


def test_resolve_exact_match():
    assert _resolve("stephen curry", _index(), "player").player_id == 201939


def test_resolve_fuzzy_match():
    assert _resolve("steph curry", _index(), "player").full_name == "Stephen Curry"


def test_resolve_alias_maps_to_canonical():
    aliases = {"steph": "stephen curry"}
    assert _resolve("steph", _index(), "player", aliases=aliases).player_id == 201939


def test_resolve_prefers_active_on_tie():
    idx = {
        "jordan clarkson": Player(203903, "Jordan Clarkson", True),
        "michael jordan": Player(23, "Michael Jordan", False),
    }
    # "jordan" alone is ambiguous; the active player should win the tiebreak.
    out = _resolve("jordan", idx, "player", prefer_active=True)
    assert out.is_active is True


def test_resolve_not_found_raises():
    with pytest.raises(EntityNotFound):
        _resolve("zzzqqq nobody", _index(), "player")
