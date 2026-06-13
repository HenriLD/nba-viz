"""Generic, themed chart renderers for the flexible query path.

The model writes SQL that returns tidy rows, then maps result columns onto a
chart type. Presentation stays templated (house theme, fixed chart grammar);
only data selection is open-ended. A small set of safe declarative transforms
covers the reshaping that's awkward to express in SQL.
"""
import pandas as pd
import plotly.graph_objects as go

from app import theme
from app.result import ChartResult
from app.theme import PALETTE, SERIES
from core.db import safe_select

CHART_TYPES = ["bar", "grouped_bar", "line", "scatter", "horizontal_bar", "table"]
TRANSFORMS = ["none", "rolling_mean", "cumulative", "index_to_100", "rank"]


# ------------------------------------------------------------- transforms

def _apply_transform(df: pd.DataFrame, y: str, transform: str, series: str | None,
                     window: int) -> pd.DataFrame:
    if transform in (None, "none"):
        return df
    df = df.copy()

    def per_group(s: pd.Series) -> pd.Series:
        if transform == "rolling_mean":
            return s.rolling(max(2, window), min_periods=1).mean()
        if transform == "cumulative":
            return s.cumsum()
        if transform == "index_to_100":
            base = s.iloc[0] if len(s) and s.iloc[0] not in (0, None) else None
            return s / base * 100 if base else s
        if transform == "rank":
            return s.rank(ascending=False, method="min")
        return s

    if series and series in df.columns:
        df[y] = df.groupby(series, sort=False)[y].transform(per_group)
    else:
        df[y] = per_group(df[y])
    return df


# ------------------------------------------------------------- renderers

def _need(df: pd.DataFrame, *cols: str) -> None:
    missing = [c for c in cols if c and c not in df.columns]
    if missing:
        raise ValueError(
            f"Column(s) {missing} not in query result. "
            f"Available columns: {list(df.columns)}. "
            "Alias your SELECT columns to match the x/y/series you chose.")


def _bar(df, x, y, series, horizontal):
    """x = category column, y = value column. For horizontal, the category
    runs down the y axis and the value along x."""
    fig = go.Figure()

    def axes(cat_vals, val_vals):
        # go.Bar always takes x= and y=; orientation decides which is the value.
        return (dict(x=val_vals, y=cat_vals, orientation="h") if horizontal
                else dict(x=cat_vals, y=val_vals, orientation="v"))

    if series and series in df.columns:
        for i, (key, grp) in enumerate(df.groupby(series, sort=False)):
            fig.add_trace(go.Bar(
                **axes(grp[x], grp[y]), name=str(key),
                marker_color=SERIES[i % len(SERIES)]))
        fig.update_layout(barmode="group", bargap=0.28, bargroupgap=0.08)
    else:
        vals = df[y]
        labels = [f"{v:.3g}" if isinstance(v, (int, float)) else str(v)
                  for v in vals]
        fig.add_trace(go.Bar(
            **axes(df[x], vals), marker_color=PALETTE["accent"],
            text=labels, textposition="outside",
            textfont=dict(color=PALETTE["ink"], size=12), cliponaxis=False))
    return fig


def _line(df, x, y, series):
    fig = go.Figure()
    if series and series in df.columns:
        for i, (key, grp) in enumerate(df.groupby(series, sort=False)):
            fig.add_trace(go.Scatter(
                x=grp[x], y=grp[y], mode="lines+markers", name=str(key),
                line=dict(color=SERIES[i % len(SERIES)], width=3,
                          shape="spline", smoothing=0.5),
                marker=dict(size=6)))
    else:
        fig.add_trace(go.Scatter(
            x=df[x], y=df[y], mode="lines+markers",
            line=dict(color=PALETTE["accent"], width=3, shape="spline",
                      smoothing=0.5), marker=dict(size=6)))
    return fig


def _scatter(df, x, y, series):
    fig = go.Figure()
    if series and series in df.columns:
        for i, (key, grp) in enumerate(df.groupby(series, sort=False)):
            fig.add_trace(go.Scatter(
                x=grp[x], y=grp[y], mode="markers", name=str(key),
                marker=dict(size=10, color=SERIES[i % len(SERIES)], opacity=0.8)))
    else:
        fig.add_trace(go.Scatter(
            x=df[x], y=df[y], mode="markers",
            marker=dict(size=10, color=PALETTE["accent"], opacity=0.8),
            text=df.get(series)))
    return fig


def _table(df):
    head = dict(values=[f"<b>{c}</b>" for c in df.columns],
                fill_color="#1f2630", font=dict(color=PALETTE["ink"], size=13),
                align="left", height=30)
    cells = dict(values=[df[c].tolist() for c in df.columns],
                 fill_color=PALETTE["card"], font=dict(color=PALETTE["ink"], size=12),
                 align="left", height=26)
    return go.Figure(go.Table(header=head, cells=cells))


def build_figure(df: pd.DataFrame, chart_type: str, x: str | None, y: str | None,
                 series: str | None, title: str, subtitle: str | None = None,
                 transform: str = "none", rolling_window: int = 5) -> go.Figure:
    if chart_type == "table":
        fig = _table(df)
        theme.style(fig, title, subtitle=subtitle,
                    height=min(620, 90 + 28 * len(df)))
        return fig

    _need(df, x, y)
    if y and transform not in (None, "none"):
        df = _apply_transform(df, y, transform, series, rolling_window)

    if chart_type == "horizontal_bar":
        fig = _bar(df, x, y, series, horizontal=True)
    elif chart_type in ("bar", "grouped_bar"):
        fig = _bar(df, x, y, series, horizontal=False)
    elif chart_type == "line":
        fig = _line(df, x, y, series)
    elif chart_type == "scatter":
        fig = _scatter(df, x, y, series)
    else:
        raise ValueError(f"Unknown chart_type '{chart_type}'. "
                         f"Use one of: {', '.join(CHART_TYPES)}.")

    height = max(440, 30 * len(df) + 160) if chart_type == "horizontal_bar" else 480
    theme.style(fig, title, subtitle=subtitle, height=height)
    if chart_type != "horizontal_bar":
        fig.update_xaxes(title_text=x)
        fig.update_yaxes(title_text=y)
    else:
        fig.update_xaxes(title_text=y)
    return fig


def run_query_chart(args: dict) -> ChartResult:
    """Execute model SQL safely and render it. `args` carries sql + encoding."""
    sql = (args.get("sql") or "").strip()
    if not sql:
        raise ValueError("query_chart requires a 'sql' SELECT statement.")
    chart_type = args.get("chart_type", "bar")
    if chart_type not in CHART_TYPES:
        raise ValueError(f"chart_type must be one of {CHART_TYPES}.")

    df = safe_select(sql)
    if df.empty:
        raise ValueError("The query returned no rows. Loosen the filters, check "
                         "the season string (e.g. '2024-25'), or verify the "
                         "team/player abbreviation.")

    fig = build_figure(
        df, chart_type,
        x=args.get("x"), y=args.get("y"), series=args.get("series"),
        title=args.get("title") or "Custom query",
        subtitle=args.get("subtitle"),
        transform=args.get("transform", "none"),
        rolling_window=int(args.get("rolling_window") or 5))

    preview = df.head(6).to_dict("records")
    summary = (f"{len(df)} rows, columns {list(df.columns)}. "
               f"First rows: {preview}")
    return ChartResult(fig, summary)
