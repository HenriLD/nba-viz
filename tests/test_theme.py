"""Theme system: title clipping, vertical-bar margin, palette consistency."""
import plotly.graph_objects as go

from app import theme
from app.theme import MAX_TITLE, THEMES, _clip_title, set_theme


def test_clip_title_short_unchanged():
    assert _clip_title("Short title") == "Short title"


def test_clip_title_long_clipped_at_word_boundary():
    out = _clip_title("Field goal percentage by shot zone this season for Steph")
    assert len(out) <= MAX_TITLE
    assert out.endswith("…")
    assert "  " not in out


def test_all_themes_share_palette_keys():
    key_sets = {tid: set(t["palette"]) for tid, t in THEMES.items()}
    base = key_sets["broadcast"]
    for tid, keys in key_sets.items():
        assert keys == base, f"{tid} palette keys differ from broadcast"


def test_distribution_and_ui_colors_present():
    for tid, t in THEMES.items():
        for key in ("made", "missed", "accent", "accent2", "bg", "panel", "on_accent"):
            assert key in t["palette"], f"{tid} missing palette['{key}']"
        assert len(t["series"]) >= 6


def test_series_colors_are_hex_strings():
    # The client recolor maps exact color strings; series colors must be plain hex.
    for tid, t in THEMES.items():
        for c in t["series"]:
            assert isinstance(c, str) and c.startswith("#")


def test_vertical_bar_gets_extra_bottom_margin_and_pinned_caption():
    set_theme(None)
    fig = go.Figure(go.Bar(x=["a", "b"], y=[1, 2], orientation="v"))
    theme.style(fig, "title")
    assert fig.layout.margin.b == 92
    assert fig.layout.annotations[-1].yshift == -78


def test_non_bar_keeps_default_margin():
    set_theme(None)
    fig = go.Figure(go.Scatter(x=[1, 2], y=[1, 2]))
    theme.style(fig, "title")
    assert fig.layout.margin.b == 64


def test_horizontal_bar_is_not_treated_as_vertical():
    set_theme(None)
    fig = go.Figure(go.Bar(x=[1, 2], y=["a", "b"], orientation="h"))
    theme.style(fig, "title")
    assert fig.layout.margin.b == 64
