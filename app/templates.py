"""The chart template catalog.

Each template is: a description (fed to the model's system prompt), a list of
expected params, and a run() that executes parameterized SQL and builds a
Plotly figure. The model never writes SQL or chart code — it only picks a
template_id and fills params; everything else is validated server-side.
"""
from dataclasses import dataclass, field
from typing import Callable

import plotly.graph_objects as go

from app import court
from app.entities import resolve_player, resolve_team
from core.db import query_df
from core.seasons import current_season, validate_season
from core.stats import RATIO_STATS, SIMPLE_STATS, stat_label, validate_stat


@dataclass
class ChartResult:
    figure: go.Figure
    summary: str  # short text fed back to the model (never the full data)


@dataclass
class Template:
    id: str
    description: str
    params: list[str]
    run: Callable[[dict], ChartResult]
    optional: list[str] = field(default_factory=list)


def _season(params: dict) -> str:
    return validate_season(params.get("season") or current_season())


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


# ---------------------------------------------------------------- templates

def _player_stat_trend(params: dict) -> ChartResult:
    p = resolve_player(params["player"])
    season = _season(params)
    stat = validate_stat(params.get("stat", "pts"))
    window = int(params.get("rolling_window") or 0)

    df = query_df(f"""
        SELECT game_date, matchup, {_stat_select(stat, agg=False)} AS val
        FROM player_game_logs
        WHERE player_id = :pid AND season = :season
          AND season_type = 'Regular Season'
        ORDER BY game_date
    """, {"pid": p.player_id, "season": season})
    if df.empty:
        raise ValueError(f"No games found for {p.full_name} in {season}.")

    fig = go.Figure()
    fig.add_trace(go.Scatter(x=df["game_date"], y=df["val"], mode="lines+markers",
                             name="Per game", text=df["matchup"]))
    if window > 1:
        fig.add_trace(go.Scatter(x=df["game_date"],
                                 y=df["val"].rolling(window).mean(),
                                 mode="lines", name=f"{window}-game avg",
                                 line=dict(width=3)))
    label = stat_label(stat)
    fig.update_layout(title=f"{p.full_name} — {label}, {season}",
                      xaxis_title="Game date", yaxis_title=label)
    return ChartResult(fig, f"{len(df)} games; season avg {df['val'].mean():.2f} {label}.")


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

    if season:
        validate_season(season)
        df = query_df(f"""
            SELECT max(player_name) AS player_name,
                   {_stat_select(stat, agg=True)} AS val
            FROM player_game_logs
            WHERE player_id IN ({id_list}) AND season = :season
              AND season_type = 'Regular Season'
            GROUP BY player_id
        """, {**ids, "season": season})
        if df.empty:
            raise ValueError(f"No data for those players in {season}.")
        fig = go.Figure(go.Bar(x=df["player_name"], y=df["val"],
                               text=df["val"].round(2), textposition="outside"))
        fig.update_layout(title=f"{label} per game, {season}", yaxis_title=label)
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
    for pid, grp in df.groupby("player_id"):
        fig.add_trace(go.Scatter(x=grp["season"], y=grp["val"],
                                 mode="lines+markers",
                                 name=grp["player_name"].iloc[0]))
    fig.update_layout(title=f"{label} per game by season",
                      xaxis_title="Season", yaxis_title=label)
    return ChartResult(fig, f"Compared {len(players)} players across "
                            f"{df['season'].nunique()} seasons.")


def _shot_chart(params: dict) -> ChartResult:
    p = resolve_player(params["player"])
    season = _season(params)
    df = query_df("""
        SELECT loc_x, loc_y, shot_made_flag, action_type, shot_distance
        FROM shots
        WHERE player_id = :pid AND season = :season
          AND season_type = 'Regular Season'
    """, {"pid": p.player_id, "season": season})
    if df.empty:
        raise ValueError(f"No shots found for {p.full_name} in {season}.")

    made = df[df["shot_made_flag"] == 1]
    missed = df[df["shot_made_flag"] == 0]
    fig = go.Figure(court.court_traces())
    fig.add_trace(go.Scatter(x=missed["loc_x"], y=missed["loc_y"], mode="markers",
                             name="Missed", marker=dict(color="#d62728", size=4,
                             symbol="x", opacity=0.5),
                             text=missed["action_type"]))
    fig.add_trace(go.Scatter(x=made["loc_x"], y=made["loc_y"], mode="markers",
                             name="Made", marker=dict(color="#2ca02c", size=4,
                             opacity=0.6),
                             text=made["action_type"]))
    fig.update_layout(court.court_layout(
        f"{p.full_name} shot chart, {season}"))
    fg = len(made) / len(df)
    return ChartResult(fig, f"{len(df)} shots, {len(made)} made ({fg:.1%} FG).")


def _shot_heatmap(params: dict) -> ChartResult:
    p = resolve_player(params["player"])
    season = _season(params)
    df = query_df("""
        SELECT loc_x, loc_y FROM shots
        WHERE player_id = :pid AND season = :season
          AND season_type = 'Regular Season'
    """, {"pid": p.player_id, "season": season})
    if df.empty:
        raise ValueError(f"No shots found for {p.full_name} in {season}.")

    fig = go.Figure()
    fig.add_trace(go.Histogram2dContour(
        x=df["loc_x"], y=df["loc_y"], colorscale="YlOrRd",
        ncontours=12, showscale=False,
        contours=dict(coloring="heatmap"), opacity=0.85))
    for tr in court.court_traces():
        fig.add_trace(tr)
    fig.update_layout(court.court_layout(
        f"{p.full_name} shot density, {season}"))
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
    df["def_dist_range"] = df["def_dist_range"].astype("category")
    df = df.set_index("def_dist_range").reindex(order).reset_index()

    fig = go.Figure()
    fig.add_trace(go.Bar(x=df["def_dist_range"], y=df["fg_pct"], name="FG%",
                         text=(df["fg_pct"] * 100).round(1), textposition="outside"))
    fig.add_trace(go.Bar(x=df["def_dist_range"], y=df["efg_pct"], name="eFG%"))
    fig.update_layout(
        title=f"{p.full_name} shooting by closest defender distance, {season}",
        yaxis_title="Percentage", yaxis_tickformat=".0%", barmode="group")
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

    df = df.iloc[::-1]  # horizontal bar: leader on top
    fig = go.Figure(go.Bar(x=df["val"], y=df["player_name"], orientation="h",
                           text=df["val"].round(2), textposition="outside"))
    fig.update_layout(title=f"Top {top_n} — {label} per game, {season} (min 20 GP)",
                      xaxis_title=label, height=max(420, 30 * top_n))
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
    fig = go.Figure(go.Bar(
        x=df["wins"], y=df["team"], orientation="h", name="Wins",
        marker_color=["#1f77b4" if c == "East" else "#ff7f0e"
                      for c in df["conference"]],
        text=[f"{w}-{l}" for w, l in zip(df["wins"], df["losses"])],
        textposition="outside"))
    title = f"{conf.capitalize()} standings" if conf else "NBA standings (East blue / West orange)"
    fig.update_layout(title=f"{title}, {season}", xaxis_title="Wins",
                      height=max(500, 26 * len(df)))
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

    fig = go.Figure()
    fig.add_trace(go.Scatter(x=df["game_date"], y=df["val"], mode="markers",
                             name="Per game", text=df["matchup"] + " (" + df["wl"] + ")"))
    fig.add_trace(go.Scatter(x=df["game_date"], y=df["val"].rolling(window).mean(),
                             mode="lines", name=f"{window}-game avg",
                             line=dict(width=3)))
    fig.update_layout(title=f"{t.full_name} — {label}, {season}",
                      xaxis_title="Game date", yaxis_title=label)
    return ChartResult(fig, f"{len(df)} games; avg {df['val'].mean():.2f} {label}.")


CATALOG: dict[str, Template] = {t.id: t for t in [
    Template("player_stat_trend",
             "Line chart of one player's stat game-by-game across a season, "
             "optional rolling average. Use for 'how has X been scoring lately'.",
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
             "with rolling average.",
             ["team"], _team_stat_trend, ["season", "stat", "rolling_window"]),
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
