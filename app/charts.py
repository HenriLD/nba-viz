"""Generic, themed chart renderers for the flexible query path.

The model writes SQL that returns tidy rows, then maps result columns onto a
chart type. Presentation stays templated (house theme, fixed chart grammar);
only data selection is open-ended. A small set of safe declarative transforms
covers the reshaping that's awkward to express in SQL.
"""
import pandas as pd
import plotly.graph_objects as go

from app import court, theme
from app.labels import prettify
from app.result import ChartResult
from app.theme import PALETTE, SERIES
from core.db import safe_select

CHART_TYPES = ["bar", "grouped_bar", "line", "scatter", "horizontal_bar",
               "box", "violin", "histogram", "shot_chart", "shot_heatmap", "table"]
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
    """Validate the required encoding columns exist. Flags BOTH an unset arg
    (None/"" — the model forgot to pass x or y) and a wrong name, with an
    actionable message — otherwise a missing arg became df[None] -> a bare
    KeyError(None) that surfaced as the uninterpretable 'ERROR: None', which the
    model couldn't fix and wrongly rationalized as missing data."""
    unset = any(c is None or c == "" for c in cols)
    badname = [c for c in cols if c and c not in df.columns]
    if not unset and not badname:
        return
    problems = []
    if unset:
        problems.append("a required x/y encoding field was left unset (null)")
    if badname:
        problems.append(f"column(s) {badname} are not in the query result")
    raise ValueError(
        f"Can't render the chart: {'; '.join(problems)}. "
        f"Available columns: {list(df.columns)}. Set x/y (and series) to column "
        "names from your SELECT — for a bar/horizontal_bar, x is the category "
        "(e.g. player_name) and y is the value (e.g. ts_pct).")


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


def _distribution(df, x, y, series, kind):
    """Box or violin of raw values (one row per observation). The value goes on
    y; an optional category (series, else x) splits it into side-by-side
    distributions. Violins carry an inner box + mean line; both show every
    observation as a jittered dot, so the spread and outliers are visible."""
    val = y if (y and y in df.columns) else None
    if val is None:
        raise ValueError(
            "box/violin needs a numeric 'y' column of raw (un-aggregated) "
            f"values, one row per observation. Got columns {list(df.columns)}.")
    cat = series if (series and series in df.columns) else (
        x if (x and x in df.columns and x != val) else None)

    def add(values, name, color, show_legend):
        # Solid theme color + trace opacity (not an rgba fill) so the client-side
        # theme recolor — which maps exact palette/series color strings — can
        # recolor the fill too when the user switches themes.
        if kind == "violin":
            fig.add_trace(go.Violin(
                y=values, name=name, line_color=color, fillcolor=color,
                opacity=0.55, box_visible=False, meanline_visible=False, points=False,
                scalemode="width", showlegend=show_legend, hoveron="violins"))
        else:
            fig.add_trace(go.Box(
                y=values, name=name, line=dict(color=color), fillcolor=color,
                opacity=0.5, boxpoints="all", jitter=0.3, pointpos=0,
                showlegend=show_legend, marker=dict(color=color, size=4, opacity=0.6),
                hovertemplate="%{y}<extra>" + name + "</extra>"))

    fig = go.Figure()
    if cat:
        for i, (key, grp) in enumerate(df.groupby(cat, sort=False)):
            add(grp[val], str(key), SERIES[i % len(SERIES)], True)
    else:
        add(df[val], "", PALETTE["accent"], False)
    return fig


def _histogram(df, val, series):
    fig = go.Figure()
    if series and series in df.columns:
        for i, (key, grp) in enumerate(df.groupby(series, sort=False)):
            fig.add_trace(go.Histogram(
                x=grp[val], name=str(key), marker_color=SERIES[i % len(SERIES)],
                opacity=0.6))
        fig.update_layout(barmode="overlay")
    else:
        fig.add_trace(go.Histogram(
            x=df[val], marker_color=PALETTE["accent"], opacity=0.88))
    return fig


def _as_made(s: pd.Series) -> pd.Series:
    """Coerce a 'made' column to boolean — accepts bool, 0/1, or text."""
    if pd.api.types.is_bool_dtype(s) or pd.api.types.is_numeric_dtype(s):
        return s.fillna(0).astype(bool)
    return s.astype(str).str.strip().str.lower().isin(
        {"true", "t", "1", "made", "make", "yes", "y"})


_MADE_COLS = {"made", "make", "shot_made", "shot_made_flag", "is_made"}


def _shot_chart(df, x, y, series):
    if series and series in df.columns:
        if series.strip().lower() in _MADE_COLS:   # color makes vs misses
            mask = _as_made(df[series])
            made, missed = df[mask], df[~mask]
            return court.shot_chart_figure(made[x], made[y], missed[x], missed[y])
        # any other column → color the shots by that category (quarter, zone…)
        return court.shot_chart_by_category(df, x, y, series)
    # no series → plot everything as makes
    return court.shot_chart_figure(df[x], df[y], df.iloc[0:0][x], df.iloc[0:0][y])


def _table(df):
    head = dict(values=[f"<b>{prettify(c)}</b>" for c in df.columns],
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

    # Court visualizations — same renderers the shot templates use, but fed by
    # the model's own SQL so any filter is possible (period, opponent, wins...).
    # Shots are virtually always SELECT loc_x, loc_y[, color] from v_shots, so
    # default the coordinates (and treat any third column as the color series)
    # when the model omits the x/y/series args — otherwise df[None] raised an
    # opaque KeyError the model couldn't recover from.
    if chart_type in ("shot_chart", "shot_heatmap"):
        if not x and "loc_x" in df.columns:
            x = "loc_x"
        if not y and "loc_y" in df.columns:
            y = "loc_y"
        if not x or not y:
            raise ValueError(
                "shot_chart/shot_heatmap need x and y coordinate columns — "
                "SELECT loc_x, loc_y from v_shots (optionally a third column to "
                f"color by). Got columns {list(df.columns)}.")
        _need(df, x, y)
    if chart_type == "shot_chart":
        if not series:  # any extra selected column is the intended color dimension
            extra = [c for c in df.columns if c not in (x, y)]
            series = extra[0] if extra else None
        fig = _shot_chart(df, x, y, series)
        theme.style(fig, title, subtitle=subtitle, height=640)
        return fig
    if chart_type == "shot_heatmap":
        fig = court.shot_heatmap_figure(df[x], df[y])
        theme.style(fig, title, subtitle=subtitle, height=640)
        return fig

    # Distribution charts consume raw rows and have their own column needs:
    # box/violin need the value (y); histogram needs the value (x).
    if chart_type in ("box", "violin"):
        _need(df, y)
        fig = _distribution(df, x, y, series, chart_type)
        theme.style(fig, title, subtitle=subtitle)
        cat = series if (series and series in df.columns) else x
        if cat and cat in df.columns and cat != y:
            fig.update_xaxes(title_text=prettify(cat))
        fig.update_yaxes(title_text=prettify(y))
        return fig
    if chart_type == "histogram":
        val = x if (x and x in df.columns) else y
        _need(df, val)
        fig = _histogram(df, val, series)
        theme.style(fig, title, subtitle=subtitle)
        fig.update_xaxes(title_text=prettify(val))
        fig.update_yaxes(title_text="Games")
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
        fig.update_xaxes(title_text=prettify(x))
        fig.update_yaxes(title_text=prettify(y))
    else:
        fig.update_xaxes(title_text=prettify(y))
        fig.update_yaxes(title_text=prettify(x))
    return fig


def _fmt_num(v) -> str:
    try:
        return f"{float(v):.3g}"
    except (TypeError, ValueError):
        return str(v)


def _summarize(df: pd.DataFrame, chart_type: str, x: str | None, y: str | None,
               series: str | None) -> str:
    """A takeaway-ready summary keyed off the chart type — the headline numbers
    the model needs to write an insight, not a raw 6-row dict dump."""
    n = len(df)
    cols = list(df.columns)
    val = y if (y and y in df.columns) else None
    cat = x if (x and x in df.columns) else None
    has_series = bool(series and series in df.columns)

    # Shot charts: makes / attempts / FG%.
    if chart_type in ("shot_chart", "shot_heatmap"):
        mcol = next((c for c in ("made", "shot_made", "shot_made_flag", "is_made")
                     if c in df.columns), None)
        if mcol is not None:
            made = int(_as_made(df[mcol]).sum())
            return f"{n} shots, {made} made ({made / n:.0%} FG)." if n else "no shots."
        return f"{n} shots plotted on the court."

    # Distributions: per-group median + spread.
    if chart_type in ("box", "violin", "histogram"):
        v = val or cat
        grp = series if has_series else (cat if (cat and cat != v) else None)
        if not v:
            return f"{n} rows, columns {cols}."
        if grp and grp in df.columns:
            parts = []
            for k, g in df.groupby(grp, sort=False):
                gv = pd.to_numeric(g[v], errors="coerce").dropna()
                if len(gv):
                    parts.append(f"{k}: median {_fmt_num(gv.median())} "
                                 f"(n={len(gv)}, {_fmt_num(gv.min())}–{_fmt_num(gv.max())})")
            return f"{n} rows. Distribution of {v} — " + "; ".join(parts[:6]) + "."
        gv = pd.to_numeric(df[v], errors="coerce").dropna()
        if len(gv):
            return (f"{n} rows. {v}: median {_fmt_num(gv.median())}, "
                    f"range {_fmt_num(gv.min())}–{_fmt_num(gv.max())}.")
        return f"{n} rows, columns {cols}."

    # Trends: first → last (+ direction) and peak, per series.
    if chart_type == "line" and cat and val:
        def trend(g):
            gv = pd.to_numeric(g[val], errors="coerce").dropna()
            return (gv.iloc[0], gv.iloc[-1], gv.max()) if len(gv) else None
        if has_series:
            parts = []
            for k, g in df.groupby(series, sort=False):
                t = trend(g)
                if t:
                    parts.append(f"{k}: {_fmt_num(t[0])}→{_fmt_num(t[1])} (peak {_fmt_num(t[2])})")
            return f"{n} points. " + "; ".join(parts[:6]) + "."
        t = trend(df)
        if t:
            arrow = "up" if t[1] > t[0] else "down" if t[1] < t[0] else "flat"
            return (f"{n} points: {val} {_fmt_num(t[0])}→{_fmt_num(t[1])} "
                    f"({arrow}), peak {_fmt_num(t[2])}.")

    # Leaderboards / categorical bars: top items, the #1→#2 gap, the range.
    if chart_type in ("bar", "horizontal_bar", "grouped_bar") and cat and val and not has_series:
        d = df[[cat, val]].copy()
        d[val] = pd.to_numeric(d[val], errors="coerce")
        d = d.dropna(subset=[val]).sort_values(val, ascending=False)
        if len(d):
            top = ", ".join(f"{r[cat]} {_fmt_num(r[val])}" for _, r in d.head(5).iterrows())
            gap = (f"; #1 leads #2 by {_fmt_num(d[val].iloc[0] - d[val].iloc[1])}"
                   if len(d) >= 2 else "")
            rng = (f"; range {_fmt_num(d[val].min())}–{_fmt_num(d[val].max())}"
                   if len(d) > 1 else "")
            return f"{n} rows. Top by {val}: {top}{gap}{rng}."

    # Grouped/series charts and anything else: compact note + a trimmed preview.
    if has_series:
        return (f"{n} rows across {df[series].nunique()} {series} groups. "
                f"First rows: {df.head(5).to_dict('records')}")
    return f"{n} rows, columns {cols}. First rows: {df.head(5).to_dict('records')}"


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

    summary = _summarize(df, chart_type, args.get("x"), args.get("y"),
                         args.get("series"))
    return ChartResult(fig, summary)
