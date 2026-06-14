"""The chart template catalog.

Each template is: a description (fed to the model's system prompt), a list of
expected params, and a run() that executes parameterized SQL and builds a
Plotly figure. The model never writes SQL or chart code — it only picks a
template_id and fills params; everything else is validated server-side.

All figures go through theme.style() so every chart shares the same
broadcast-dark look, typography, and source line.
"""
from dataclasses import dataclass, field
from typing import Callable

import plotly.graph_objects as go

from app import court, theme
from app.entities import resolve_player, resolve_team
from app.result import ChartResult
from app.theme import PALETTE, SERIES
from core.db import query_df
from core.seasons import latest_season, validate_season
from core.stats import RATIO_STATS, SIMPLE_STATS, stat_label, validate_stat


@dataclass
class Template:
    id: str
    description: str
    params: list[str]
    run: Callable[[dict], ChartResult]
    optional: list[str] = field(default_factory=list)


def _season(params: dict) -> str:
    return validate_season(params.get("season") or latest_season())


def _stat_select(stat: str, agg: bool) -> str:
    """SQL select expression for a whitelisted stat (column names are from a
    fixed dict, never user input)."""
    validate_stat(stat)
    if stat in SIMPLE_STATS:
        return f"avg({stat})" if agg else stat
    num, den, _ = RATIO_STATS[stat]
    if agg:
        return f"sum({num})::numeric / nullif(sum({den}), 0)"
    return stat  # per-game ratio column exists on the log tables


def _is_pct(stat: str) -> bool:
    return stat in RATIO_STATS


def _fmt(val: float, stat: str) -> str:
    return f"{val:.1%}" if _is_pct(stat) else f"{val:.1f}"


def _rgba(hex_str: str, alpha: float) -> str:
    h = hex_str.lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return f"rgba({r},{g},{b},{alpha})"


# ---------------------------------------------------------------- templates

def _player_stat_trend(params: dict) -> ChartResult:
    p = resolve_player(params["player"])
    season = _season(params)
    stat = validate_stat(params.get("stat", "pts"))
    window = int(params.get("rolling_window") or 10)

    df = query_df(f"""
        SELECT game_date, matchup, {_stat_select(stat, agg=False)} AS val
        FROM player_game_logs
        WHERE player_id = :pid AND season = :season
          AND season_type = 'Regular Season'
        ORDER BY game_date
    """, {"pid": p.player_id, "season": season})
    if df.empty:
        raise ValueError(f"No games found for {p.full_name} in {season}.")

    label = stat_label(stat)
    avg = df["val"].mean()
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=df["game_date"], y=df["val"], mode="markers", name="Per game",
        marker=dict(color=PALETTE["muted"], size=6, opacity=0.55),
        text=df["matchup"],
        hovertemplate="%{text} · %{x|%b %d}<br>%{y} " + label + "<extra></extra>"))
    if len(df) > window:
        fig.add_trace(go.Scatter(
            x=df["game_date"], y=df["val"].rolling(window).mean(),
            mode="lines", name=f"{window}-game average",
            line=dict(color=PALETTE["accent"], width=3.5, shape="spline",
                      smoothing=0.6)))
    fig.add_hline(y=avg, line=dict(color=PALETTE["accent2"], width=1.2,
                                   dash="3px,4px"),
                  annotation_text=f"season avg {_fmt(avg, stat)}",
                  annotation_font=dict(size=11, color=PALETTE["accent2"]))
    fig.update_yaxes(title_text=label, tickformat=".0%" if _is_pct(stat) else None)
    theme.style(fig, f"{p.full_name} — {label}",
                subtitle=f"{season} regular season, game by game")
    return ChartResult(fig, f"{len(df)} games; season avg {avg:.2f} {label}.")


def _player_comparison(params: dict) -> ChartResult:
    names = params.get("players") or []
    if len(names) < 2:
        raise ValueError("player_comparison needs at least 2 names in 'players'.")
    players = [resolve_player(n) for n in names]
    stat = validate_stat(params.get("stat", "pts"))
    label = stat_label(stat)
    season = params.get("season")

    ids = {f"p{i}": pl.player_id for i, pl in enumerate(players)}
    id_list = ", ".join(f":{k}" for k in ids)
    pctfmt = ".0%" if _is_pct(stat) else None

    if season:
        validate_season(season)
        df = query_df(f"""
            SELECT max(player_name) AS player_name,
                   {_stat_select(stat, agg=True)} AS val
            FROM player_game_logs
            WHERE player_id IN ({id_list}) AND season = :season
              AND season_type = 'Regular Season'
            GROUP BY player_id ORDER BY val DESC
        """, {**ids, "season": season})
        if df.empty:
            raise ValueError(f"No data for those players in {season}.")
        fig = go.Figure(go.Bar(
            x=df["player_name"], y=df["val"],
            marker=dict(color=SERIES[:len(df)], opacity=0.92),
            text=[_fmt(v, stat) for v in df["val"]],
            textposition="outside", textfont=dict(size=14, color=PALETTE["ink"]),
            cliponaxis=False,
            hovertemplate="%{x}: %{y}<extra></extra>"))
        fig.update_yaxes(title_text=f"{label} per game", tickformat=pctfmt,
                         range=[0, float(df["val"].max()) * 1.18])
        theme.style(fig, f"{label} — head to head",
                    subtitle=f"{season} regular season, per-game averages")
        return ChartResult(fig, "; ".join(
            f"{r.player_name}: {r.val:.2f}" for r in df.itertuples()))

    df = query_df(f"""
        SELECT player_id, max(player_name) AS player_name, season,
               {_stat_select(stat, agg=True)} AS val
        FROM player_game_logs
        WHERE player_id IN ({id_list}) AND season_type = 'Regular Season'
        GROUP BY player_id, season ORDER BY season
    """, ids)
    if df.empty:
        raise ValueError("No data found for those players.")
    fig = go.Figure()
    for i, (pid, grp) in enumerate(df.groupby("player_id")):
        name = grp["player_name"].iloc[0]
        fig.add_trace(go.Scatter(
            x=grp["season"], y=grp["val"], mode="lines+markers+text", name=name,
            line=dict(color=SERIES[i % len(SERIES)], width=3,
                      shape="spline", smoothing=0.6),
            marker=dict(size=8),
            text=[_fmt(v, stat) if j == len(grp) - 1 else ""
                  for j, v in enumerate(grp["val"])],
            textposition="middle right",
            textfont=dict(size=12, color=SERIES[i % len(SERIES)]),
            hovertemplate=name + " · %{x}: %{y}<extra></extra>"))
    fig.update_yaxes(title_text=f"{label} per game", tickformat=pctfmt)
    fig.update_xaxes(type="category")
    theme.style(fig, f"{label} — season by season",
                subtitle="Regular-season per-game averages")
    return ChartResult(fig, f"Compared {len(players)} players across "
                            f"{df['season'].nunique()} seasons.")


def _shot_chart(params: dict) -> ChartResult:
    p = resolve_player(params["player"])
    season = _season(params)
    df = query_df("""
        SELECT loc_x, loc_y, shot_made_flag, action_type, shot_distance
        FROM shots
        WHERE player_id = :pid AND season = :season
          AND season_type = 'Regular Season' AND loc_y < 420
    """, {"pid": p.player_id, "season": season})
    if df.empty:
        raise ValueError(f"No shots found for {p.full_name} in {season}.")

    made = df[df["shot_made_flag"] == 1]
    missed = df[df["shot_made_flag"] == 0]
    fig = go.Figure(court.court_traces())
    fig.add_trace(go.Scatter(
        x=missed["loc_x"], y=missed["loc_y"], mode="markers", name="Missed",
        marker=dict(color=PALETTE["missed"], size=5, symbol="x-thin",
                    line=dict(width=1.2, color=PALETTE["missed"]), opacity=0.45),
        text=missed["action_type"],
        hovertemplate="%{text}<extra>missed</extra>"))
    fig.add_trace(go.Scatter(
        x=made["loc_x"], y=made["loc_y"], mode="markers", name="Made",
        marker=dict(color=PALETTE["made"], size=5.5, opacity=0.75,
                    line=dict(width=0)),
        text=made["action_type"],
        hovertemplate="%{text}<extra>made</extra>"))
    fg = len(made) / len(df)
    fig.update_layout(**court.court_layout())
    theme.style(
        fig, f"{p.full_name} — shot chart",
        subtitle=f"{season} regular season · {len(df):,} attempts · {fg:.1%} FG",
        height=640)
    return ChartResult(fig, f"{len(df)} shots, {len(made)} made ({fg:.1%} FG).")


def _shot_heatmap(params: dict) -> ChartResult:
    p = resolve_player(params["player"])
    season = _season(params)
    df = query_df("""
        SELECT loc_x, loc_y FROM shots
        WHERE player_id = :pid AND season = :season
          AND season_type = 'Regular Season' AND loc_y < 420
    """, {"pid": p.player_id, "season": season})
    if df.empty:
        raise ValueError(f"No shots found for {p.full_name} in {season}.")

    fig = go.Figure()
    fig.add_trace(go.Histogram2dContour(
        x=df["loc_x"], y=df["loc_y"], colorscale=theme.HEAT_SCALE,
        ncontours=16, showscale=False, line=dict(width=0),
        contours=dict(coloring="heatmap"), hoverinfo="skip"))
    for tr in court.court_traces():
        fig.add_trace(tr)
    fig.update_layout(**court.court_layout())
    theme.style(
        fig, f"{p.full_name} — where the shots come from",
        subtitle=f"{season} regular season · {len(df):,} attempts · "
                 "brighter = more volume",
        height=640)
    return ChartResult(fig, f"Heatmap of {len(df)} shot attempts.")


def _defender_distance(params: dict) -> ChartResult:
    p = resolve_player(params["player"])
    season = _season(params)
    df = query_df("""
        SELECT def_dist_range, fgm, fga, fg_pct, efg_pct, fg3_pct
        FROM defender_shooting
        WHERE player_id = :pid AND season = :season
    """, {"pid": p.player_id, "season": season})
    if df.empty:
        raise ValueError(
            f"No defender-distance data for {p.full_name} in {season}. "
            "Note: this data exists for recent seasons only.")

    order = ["0-2 Feet - Very Tight", "2-4 Feet - Tight",
             "4-6 Feet - Open", "6+ Feet - Wide Open"]
    labels = ["Very tight<br>0–2 ft", "Tight<br>2–4 ft",
              "Open<br>4–6 ft", "Wide open<br>6+ ft"]
    df = df.set_index("def_dist_range").reindex(order).reset_index()

    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=labels, y=df["fg_pct"], name="FG%",
        marker=dict(color=PALETTE["accent"], opacity=0.92),
        text=[f"{v:.0%}" if v == v else "" for v in df["fg_pct"]],
        textposition="outside", textfont=dict(size=13, color=PALETTE["ink"]),
        cliponaxis=False,
        customdata=df["fga"],
        hovertemplate="%{x}: %{y:.1%} on %{customdata:.0f} FGA<extra>FG%</extra>"))
    fig.add_trace(go.Bar(
        x=labels, y=df["efg_pct"], name="eFG%",
        marker=dict(color=PALETTE["accent2"], opacity=0.85),
        hovertemplate="%{x}: %{y:.1%}<extra>eFG%</extra>"))
    fig.update_layout(barmode="group", bargap=0.32, bargroupgap=0.08)
    fig.update_yaxes(tickformat=".0%", rangemode="tozero")
    theme.style(
        fig, f"{p.full_name} — shooting vs. pressure",
        subtitle=f"{season} regular season, by closest defender at release")
    return ChartResult(fig, "; ".join(
        f"{r.def_dist_range}: {r.fg_pct:.1%} on {r.fga:.0f} FGA"
        for r in df.itertuples() if r.fga))


def _league_leaders(params: dict) -> ChartResult:
    season = _season(params)
    stat = validate_stat(params.get("stat", "pts"))
    label = stat_label(stat)
    top_n = min(int(params.get("top_n") or 10), 30)

    df = query_df(f"""
        SELECT max(player_name) AS player_name,
               {_stat_select(stat, agg=True)} AS val, count(*) AS gp
        FROM player_game_logs
        WHERE season = :season AND season_type = 'Regular Season'
        GROUP BY player_id
        HAVING count(*) >= 20
        ORDER BY val DESC NULLS LAST
        LIMIT :n
    """, {"season": season, "n": top_n})
    if df.empty:
        raise ValueError(f"No data for {season}.")

    df = df.iloc[::-1]
    colors = [PALETTE["accent"] if i == len(df) - 1 else PALETTE["accent_dim"]
              for i in range(len(df))]
    fig = go.Figure(go.Bar(
        x=df["val"], y=df["player_name"], orientation="h",
        marker=dict(color=colors),
        text=[_fmt(v, stat) for v in df["val"]],
        textposition="outside", textfont=dict(size=13, color=PALETTE["ink"]),
        cliponaxis=False,
        customdata=df["gp"],
        hovertemplate="%{y}: %{x} over %{customdata} games<extra></extra>"))
    fig.update_xaxes(tickformat=".0%" if _is_pct(stat) else None,
                     range=[0, df["val"].max() * 1.14])
    fig.update_yaxes(tickfont=dict(size=13, color=PALETTE["ink"]), gridcolor="rgba(0,0,0,0)")
    theme.style(fig, f"League leaders — {label}",
                subtitle=f"{season} regular season, per game (min. 20 GP)",
                height=max(440, 34 * top_n + 150))
    top = df.iloc[-1]
    return ChartResult(fig, f"Leader: {top['player_name']} ({top['val']:.2f}).")


def _standings(params: dict) -> ChartResult:
    season = _season(params)
    conf = params.get("conference")
    where = "AND conference = :conf" if conf else ""
    df = query_df(f"""
        SELECT team_city || ' ' || team_name AS team, conference,
               wins, losses, win_pct, playoff_rank
        FROM standings WHERE season = :season {where}
        ORDER BY win_pct DESC
    """, {"season": season, "conf": (conf or "").capitalize() or None})
    if df.empty:
        raise ValueError(f"No standings for {season}.")

    df = df.iloc[::-1]
    fig = go.Figure()
    for conference, color in (("East", PALETTE["accent2"]),
                              ("West", PALETTE["accent"])):
        sub = df[df["conference"] == conference]
        if sub.empty:
            continue
        fig.add_trace(go.Bar(
            x=sub["wins"], y=sub["team"], orientation="h", name=conference,
            marker=dict(color=color, opacity=0.9),
            text=[f"{w}–{l}" for w, l in zip(sub["wins"], sub["losses"])],
            textposition="outside", textfont=dict(size=12, color=PALETTE["ink"]),
            cliponaxis=False,
            customdata=sub["playoff_rank"],
            hovertemplate="%{y}: %{text} (seed %{customdata})<extra></extra>"))
    fig.update_xaxes(range=[0, df["wins"].max() * 1.15], title_text="Wins")
    fig.update_yaxes(tickfont=dict(size=12.5, color=PALETTE["ink"]),
                     gridcolor="rgba(0,0,0,0)",
                     categoryorder="array", categoryarray=df["team"].tolist())
    title = f"{conf.capitalize()}ern Conference" if conf else "NBA standings"
    theme.style(fig, title, subtitle=f"{season} regular season",
                height=max(520, 27 * len(df) + 150))
    best = df.iloc[-1]
    return ChartResult(fig, f"Best record: {best['team']} ({best['wins']}-{best['losses']}).")


def _team_stat_trend(params: dict) -> ChartResult:
    t = resolve_team(params["team"])
    season = _season(params)
    stat = validate_stat(params.get("stat", "pts"))
    label = stat_label(stat)
    window = int(params.get("rolling_window") or 5)

    df = query_df(f"""
        SELECT game_date, matchup, wl, {_stat_select(stat, agg=False)} AS val
        FROM team_game_logs
        WHERE team_id = :tid AND season = :season
          AND season_type = 'Regular Season'
        ORDER BY game_date
    """, {"tid": t.team_id, "season": season})
    if df.empty:
        raise ValueError(f"No games for {t.full_name} in {season}.")

    avg = df["val"].mean()
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=df["game_date"], y=df["val"], mode="markers", name="Per game",
        marker=dict(
            color=[PALETTE["made"] if wl == "W" else PALETTE["missed"]
                   for wl in df["wl"]],
            size=6.5, opacity=0.65),
        text=df["matchup"] + " (" + df["wl"] + ")",
        hovertemplate="%{text} · %{x|%b %d}<br>%{y} " + label + "<extra></extra>"))
    if len(df) > window:
        fig.add_trace(go.Scatter(
            x=df["game_date"], y=df["val"].rolling(window).mean(),
            mode="lines", name=f"{window}-game average",
            line=dict(color=PALETTE["accent"], width=3.5,
                      shape="spline", smoothing=0.6)))
    fig.update_yaxes(title_text=label, tickformat=".0%" if _is_pct(stat) else None)
    theme.style(fig, f"{t.full_name} — {label}",
                subtitle=f"{season} regular season · green dots wins, red losses")
    return ChartResult(fig, f"{len(df)} games; avg {avg:.2f} {label}.")


ZONE_ORDER = ["Restricted Area", "In The Paint (Non-RA)", "Mid-Range",
              "Left Corner 3", "Right Corner 3", "Above the Break 3"]


def _shot_zone_breakdown(params: dict) -> ChartResult:
    p = resolve_player(params["player"])
    season = _season(params)
    df = query_df("""
        SELECT shot_zone_basic AS zone,
               count(*) AS att,
               avg(shot_made_flag::float) AS fg_pct
        FROM shots
        WHERE player_id = :pid AND season = :season
          AND season_type = 'Regular Season' AND loc_y < 420
        GROUP BY shot_zone_basic
    """, {"pid": p.player_id, "season": season})
    if df.empty:
        raise ValueError(f"No shots found for {p.full_name} in {season}.")

    df = df.set_index("zone").reindex(ZONE_ORDER).dropna(how="all").reset_index()
    df["share"] = df["att"] / df["att"].sum()

    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=df["zone"], y=df["share"], name="Shot share",
        marker=dict(color=PALETTE["accent"], opacity=0.92),
        text=[f"{s:.0%}" for s in df["share"]], textposition="outside",
        textfont=dict(size=12, color=PALETTE["ink"]), cliponaxis=False,
        customdata=df["att"],
        hovertemplate="%{x}<br>%{y:.1%} of attempts (%{customdata:.0f} shots)"
                      "<extra></extra>"))
    fig.add_trace(go.Scatter(
        x=df["zone"], y=df["fg_pct"], name="FG% (right)", yaxis="y2",
        mode="lines+markers", line=dict(color=PALETTE["accent2"], width=3),
        marker=dict(size=9),
        hovertemplate="%{x}<br>%{y:.1%} FG%<extra></extra>"))
    fig.update_layout(
        yaxis=dict(title="Share of attempts", tickformat=".0%"),
        yaxis2=dict(title="FG%", tickformat=".0%", overlaying="y",
                    side="right", showgrid=False,
                    tickfont=dict(color=PALETTE["accent2"]),
                    title_font=dict(color=PALETTE["accent2"]), rangemode="tozero"))
    theme.style(fig, f"{p.full_name} — shot diet by zone",
                subtitle=f"{season} regular season · bars = volume, line = accuracy")
    return ChartResult(fig, "; ".join(
        f"{r.zone}: {r.share:.0%} of shots at {r.fg_pct:.1%}"
        for r in df.itertuples()))


SPLITS = {
    "home_away": ("CASE WHEN matchup LIKE '%vs.%' THEN 'Home' ELSE 'Away' END",
                  "home vs. away"),
    "win_loss": ("CASE WHEN wl = 'W' THEN 'In wins' ELSE 'In losses' END",
                 "in wins vs. losses"),
    "rest": ("CASE WHEN gap = 1 THEN 'Back-to-back' "
             "WHEN gap >= 3 THEN '3+ days rest' ELSE '1-2 days rest' END",
             "by days of rest"),
}


def _player_split(params: dict) -> ChartResult:
    p = resolve_player(params["player"])
    season = _season(params)
    stat = validate_stat(params.get("stat", "pts"))
    split = params.get("split", "home_away")
    if split not in SPLITS:
        raise ValueError(f"split must be one of {list(SPLITS)}.")
    label = stat_label(stat)
    case_expr, split_desc = SPLITS[split]

    df = query_df(f"""
        WITH g AS (
            SELECT *,
                   game_date - lag(game_date) OVER (ORDER BY game_date) AS gap
            FROM player_game_logs
            WHERE player_id = :pid AND season = :season
              AND season_type = 'Regular Season'
        )
        SELECT {case_expr} AS split, count(*) AS gp,
               {_stat_select(stat, agg=True)} AS val
        FROM g GROUP BY 1 ORDER BY val DESC
    """, {"pid": p.player_id, "season": season})
    if df.empty:
        raise ValueError(f"No games found for {p.full_name} in {season}.")

    fig = go.Figure(go.Bar(
        x=df["split"], y=df["val"],
        marker=dict(color=SERIES[:len(df)], opacity=0.92),
        text=[_fmt(v, stat) for v in df["val"]], textposition="outside",
        textfont=dict(size=15, color=PALETTE["ink"]), cliponaxis=False,
        customdata=df["gp"],
        hovertemplate="%{x}: %{y} (%{customdata} games)<extra></extra>"))
    fig.update_yaxes(title_text=f"{label} per game",
                     tickformat=".0%" if _is_pct(stat) else None,
                     range=[0, float(df["val"].max()) * 1.18])
    theme.style(fig, f"{p.full_name} — {label} {split_desc}",
                subtitle=f"{season} regular season")
    return ChartResult(fig, "; ".join(
        f"{r.split}: {_fmt(r.val, stat)} ({r.gp} games)" for r in df.itertuples()))


def _stat_distribution(params: dict) -> ChartResult:
    """The full game-by-game spread of a stat (violin + inner box + every game
    as a dot), optionally split into two distributions to compare — far more
    informative than a single average bar."""
    p = resolve_player(params["player"])
    season = _season(params)
    stat = validate_stat(params.get("stat", "pts"))
    split = params.get("split") or "none"
    if split not in ("none", "win_loss", "home_away"):
        raise ValueError("split must be 'none', 'win_loss', or 'home_away'.")
    label = stat_label(stat)
    pctfmt = ".0%" if _is_pct(stat) else None

    case = SPLITS[split][0] if split != "none" else None
    sel = f"{case} AS split, " if case else ""
    df = query_df(f"""
        SELECT {sel}{_stat_select(stat, agg=False)} AS val
        FROM player_game_logs
        WHERE player_id = :pid AND season = :season
          AND season_type = 'Regular Season'
    """, {"pid": p.player_id, "season": season}).dropna(subset=["val"])
    if df.empty:
        raise ValueError(f"No games found for {p.full_name} in {season}.")

    fig = go.Figure()

    def add(values, name, color, show_legend):
        # Few games → a violin's smoothed shape is misleading; fall back to a box.
        if len(values) < 8:
            fig.add_trace(go.Box(
                y=values, name=name, line=dict(color=color),
                fillcolor=_rgba(color, 0.22), opacity=0.92, boxpoints="all",
                jitter=0.3, pointpos=0, showlegend=show_legend,
                marker=dict(color=color, size=4, opacity=0.55),
                hovertemplate="%{y}<extra>" + name + "</extra>"))
        else:
            fig.add_trace(go.Violin(
                y=values, name=name, line_color=color, fillcolor=_rgba(color, 0.30),
                opacity=0.9, box_visible=False, meanline_visible=True, points=False,
                scalemode="width", showlegend=show_legend, hoveron="violins"))

    def describe(s) -> str:
        return (f"median {_fmt(s.median(), stat)}, mean {_fmt(s.mean(), stat)}, "
                f"spread {_fmt(s.std(), stat)} SD over {s.count()} games")

    if split == "none":
        add(df["val"], p.full_name.split()[-1], PALETTE["accent"], False)
        title = f"{p.full_name} — {label} distribution"
        subtitle = f"{season} regular season · game-by-game spread"
        summary = f"{label}: {describe(df['val'])}."
    else:
        order = (["In wins", "In losses"] if split == "win_loss"
                 else ["Home", "Away"])
        colors = {"In wins": PALETTE["made"], "In losses": PALETTE["missed"],
                  "Home": PALETTE["accent"], "Away": PALETTE["accent2"]}
        parts = []
        for name in order:
            g = df[df["split"] == name]["val"]
            if g.count():
                add(g, name, colors[name], True)
                parts.append(f"{name}: {describe(g)}")
        title = f"{p.full_name} — {label} {SPLITS[split][1]}"
        subtitle = f"{season} regular season · game-by-game spread"
        summary = "; ".join(parts)

    fig.update_yaxes(title_text=label, tickformat=pctfmt, zeroline=False)
    theme.style(fig, title, subtitle=subtitle)
    return ChartResult(fig, summary)


CATALOG: dict[str, Template] = {t.id: t for t in [
    Template("player_stat_trend",
             "Line chart of one player's stat game-by-game across a season, "
             "with rolling average. Use for 'how has X been scoring lately'.",
             ["player"], _player_stat_trend, ["season", "stat", "rolling_window"]),
    Template("player_comparison",
             "Compare 2+ players on one stat. With a season: bar chart of that "
             "season's averages. Without: line chart of per-season averages "
             "across all stored seasons. Use for 'X vs Y'.",
             ["players", "stat"], _player_comparison, ["season"]),
    Template("shot_chart",
             "Court scatter plot of a player's makes and misses for a season. "
             "Use for 'show me X's shots / shot selection'.",
             ["player"], _shot_chart, ["season"]),
    Template("shot_heatmap",
             "Court density heatmap of where a player shoots from. Use for "
             "'where does X like to shoot / hot zones'.",
             ["player"], _shot_heatmap, ["season"]),
    Template("defender_distance_efficiency",
             "Bar chart of a player's FG% and eFG% split by how closely they "
             "were defended (0-2ft / 2-4ft / 4-6ft / 6+ft). Use for any "
             "question about shooting against tight vs open defense.",
             ["player"], _defender_distance, ["season"]),
    Template("league_leaders",
             "Horizontal bar of the top N players by a per-game stat in a "
             "season (min 20 games). Use for 'who leads the league in X'.",
             ["stat"], _league_leaders, ["season", "top_n"]),
    Template("standings",
             "Bar chart of team records, optionally filtered to one "
             "conference ('East' or 'West').",
             [], _standings, ["season", "conference"]),
    Template("team_stat_trend",
             "Line chart of one team's stat game-by-game across a season "
             "with rolling average; dots colored by win/loss.",
             ["team"], _team_stat_trend, ["season", "stat", "rolling_window"]),
    Template("shot_zone_breakdown",
             "A player's shot diet: bar of attempt share per court zone "
             "(restricted area, paint, mid-range, corner 3s, above-break 3) "
             "with an FG% line. Use for 'shot distribution / where does X get "
             "shots / shot profile by zone'.",
             ["player"], _shot_zone_breakdown, ["season"]),
    Template("player_split",
             "Bar chart comparing one player's AVERAGE of a stat across a "
             "built-in split: 'home_away', 'win_loss', or 'rest' (back-to-back "
             "vs rested). Use for a quick 'X averages more in wins vs losses'. "
             "If the user wants the spread/distribution, use stat_distribution.",
             ["player"], _player_split, ["season", "stat", "split"]),
    Template("stat_distribution",
             "The full game-by-game DISTRIBUTION of one player's stat — a "
             "violin/box plot showing median, quartiles and every game as a dot, "
             "not just the average. Optionally split into two with 'win_loss' or "
             "'home_away' to compare shapes. Use whenever the question mentions a "
             "distribution, spread, consistency, range, or 'how often' for a "
             "player's per-game stat (e.g. 'distribution of X's points in wins "
             "vs losses', 'how consistent is X's scoring').",
             ["player"], _stat_distribution, ["season", "stat", "split"]),
]}


def run_template(template_id: str, params: dict) -> ChartResult:
    if template_id not in CATALOG:
        raise ValueError(
            f"Unknown template '{template_id}'. Valid: {', '.join(CATALOG)}")
    return CATALOG[template_id].run(params)


def catalog_prompt() -> str:
    lines = []
    for t in CATALOG.values():
        req = ", ".join(t.params) or "none"
        opt = ", ".join(t.optional) or "none"
        lines.append(f"- {t.id}: {t.description} Required: {req}. Optional: {opt}.")
    return "\n".join(lines)
