"""Entity-card tokenizer: possessive stripping + folding (pure, no DB)."""
from app.cards import _tokens


def test_strip_singular_possessive():
    assert _tokens("Jokic's points in wins") == ["jokic", "points", "in", "wins"]


def test_strip_plural_possessive():
    assert _tokens("the Lakers' defense") == ["the", "lakers", "defense"]


def test_keeps_name_internal_apostrophe():
    assert _tokens("D'Angelo Russell assists") == ["d'angelo", "russell", "assists"]


def test_folds_diacritics():
    assert _tokens("Dončić scoring") == ["doncic", "scoring"]


def test_splits_on_punctuation():
    # '.' is kept in tokens (harmless — no entity key contains it), commas split.
    assert _tokens("Curry vs. Tatum, shot chart") == [
        "curry", "vs.", "tatum", "shot", "chart"]
