"""Flexible-path renderers, esp. the court chart types driven by model SQL.
Pure: synthetic DataFrames, no DB."""
import pandas as pd
import pytest

from app.charts import _as_made, build_figure


def _shots():
    return pd.DataFrame({"loc_x": [10, -50, 120, 0, 200],
                         "loc_y": [20, 80, 150, 5, 250],
                         "made": [True, False, True, False, True]})


def test_shot_chart_splits_made_and_missed_on_a_court():
    fig = build_figure(_shots(), "shot_chart", "loc_x", "loc_y", "made", "t")
    names = {t.name for t in fig.data if getattr(t, "name", None)}
    assert {"Made", "Missed"} <= names
    # court lines present (more than just the two data scatters)
    assert len(fig.data) > 3
    # client uses layout.meta.square to size the square court card
    assert fig.layout.meta["square"] is not None
    assert fig.layout.height == 640


def test_shot_chart_without_made_column_plots_all_as_makes():
    df = _shots().drop(columns=["made"])
    fig = build_figure(df, "shot_chart", "loc_x", "loc_y", None, "t")
    made = next(t for t in fig.data if getattr(t, "name", None) == "Made")
    missed = next(t for t in fig.data if getattr(t, "name", None) == "Missed")
    assert len(made.x) == 5 and len(missed.x) == 0


def test_shot_chart_colors_by_category():
    # a non-'made' series column (quarter) colors one trace per value, not made/missed
    df = pd.DataFrame({"loc_x": [1, 2, 3, 4], "loc_y": [5, 6, 7, 8],
                       "quarter": ["Q1", "Q1", "Q2", "Q3"]})
    fig = build_figure(df, "shot_chart", "loc_x", "loc_y", "quarter", "t")
    names = {t.name for t in fig.data if getattr(t, "name", None)}
    assert names == {"Q1", "Q2", "Q3"}
    assert "Made" not in names and "Missed" not in names


def test_shot_heatmap_has_density_contour():
    df = pd.DataFrame({"loc_x": [1, 2, 3] * 4, "loc_y": [4, 5, 6] * 4})
    fig = build_figure(df, "shot_heatmap", "loc_x", "loc_y", None, "t")
    assert any(t.type == "histogram2dcontour" for t in fig.data)
    assert fig.layout.meta["square"] is not None


@pytest.mark.parametrize("vals, expected", [
    ([True, False], [True, False]),
    ([1, 0], [True, False]),
    (["Made", "Missed"], [True, False]),
    (["true", "0"], [True, False]),
])
def test_made_coercion_accepts_bool_int_and_text(vals, expected):
    assert list(_as_made(pd.Series(vals))) == expected


def test_shot_chart_missing_coordinate_raises():
    df = pd.DataFrame({"loc_x": [1], "made": [True]})   # no y column
    with pytest.raises(ValueError):
        build_figure(df, "shot_chart", "loc_x", "loc_y", "made", "t")


@pytest.mark.parametrize("ct", ["box", "violin", "histogram"])
def test_distribution_chart_types_build(ct):
    df = pd.DataFrame({"grp": ["a", "a", "b", "b"], "val": [1.0, 2, 3, 4]})
    x = "val" if ct == "histogram" else "grp"
    fig = build_figure(df, ct, x, "val", "grp", "t")
    assert fig.data
