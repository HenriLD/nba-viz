"""NL -> chart agent. Two tools, OpenRouter-compatible.

1. render_chart   — curated templates (fast, polished; preferred for common asks)
2. query_chart    — model writes a read-only SELECT against analysis views and
                    maps the result onto a generic themed chart. The open-ended
                    path for comparisons across time/splits/constraints.

Names are resolved server-side (templates) or via unaccented name_key columns
(SQL); stats/seasons/chart types are validated; SQL is sandboxed read-only.
"""
import json
import logging
import os
import time

import openai
from dotenv import load_dotenv
from openai import OpenAI

from app.charts import CHART_TYPES, TRANSFORMS, run_query_chart
from app.templates import CATALOG, catalog_prompt, run_template
from core.seasons import available_seasons, current_season
from core.stats import ALL_STATS

load_dotenv()
log = logging.getLogger("agent")

MAX_TURNS = 5    # model calls per user message (1 normal + retries / SQL fixes)
MAX_FIGURES = 4  # charts rendered per answer (side-by-side cap)


def _client() -> OpenAI:
    return OpenAI(base_url="https://openrouter.ai/api/v1",
                  api_key=os.environ["OPENROUTER_API_KEY"])


def _model() -> str:
    return os.environ.get("OPENROUTER_MODEL", "openrouter/free")


def _complete(client: OpenAI, **kwargs):
    """Call the model with a few retries. openrouter/free routes across many
    free providers, some of which intermittently 429 or 400 on a given request;
    a retry usually lands on a healthy provider."""
    last = None
    for attempt in range(3):
        try:
            return client.chat.completions.create(**kwargs)
        except openai.APIError as e:
            last = e
            log.warning("model call failed (attempt %d): %s", attempt + 1, e)
            time.sleep(0.8 * (attempt + 1))
    raise last


RENDER_CHART_TOOL = {
    "type": "function",
    "function": {
        "name": "render_chart",
        "description": "Render one chart from the curated template catalog. "
                       "Prefer this whenever a template fits the question.",
        "parameters": {
            "type": "object",
            "properties": {
                "template_id": {"type": "string", "enum": list(CATALOG.keys())},
                "params": {
                    "type": "object",
                    "properties": {
                        "player": {"type": "string"},
                        "players": {"type": "array", "items": {"type": "string"}},
                        "team": {"type": "string"},
                        "season": {"type": "string",
                                   "description": "e.g. '2024-25'. Omit for current."},
                        "stat": {"type": "string", "enum": ALL_STATS},
                        "top_n": {"type": "integer", "minimum": 3, "maximum": 30},
                        "rolling_window": {"type": "integer", "minimum": 2, "maximum": 20},
                        "conference": {"type": "string", "enum": ["East", "West"]},
                        "split": {"type": "string",
                                  "enum": ["home_away", "win_loss", "rest"]},
                    },
                    "additionalProperties": False,
                },
            },
            "required": ["template_id", "params"],
        },
    },
}

QUERY_CHART_TOOL = {
    "type": "function",
    "function": {
        "name": "query_chart",
        "description": "Run a read-only SQL SELECT against the analysis views and "
                       "plot the result. Use ONLY when no template fits — e.g. "
                       "comparisons across custom time periods, opponents, or "
                       "constraints. The SQL must return tidy rows whose column "
                       "names match the x/y/series you specify.",
        "parameters": {
            "type": "object",
            "properties": {
                "sql": {"type": "string",
                        "description": "A single read-only SELECT against the v_* "
                                       "views. Alias output columns to clear names."},
                "chart_type": {"type": "string", "enum": CHART_TYPES},
                "x": {"type": "string", "description": "Result column for the x axis "
                                                       "(category axis for bars)."},
                "y": {"type": "string", "description": "Result column for the y axis "
                                                       "(numeric)."},
                "series": {"type": "string",
                           "description": "Optional column to split into multiple "
                                          "bars/lines (e.g. player name, split)."},
                "transform": {"type": "string", "enum": TRANSFORMS,
                              "description": "Optional post-query transform applied "
                                             "to y, per series."},
                "rolling_window": {"type": "integer", "minimum": 2, "maximum": 40},
                "title": {"type": "string",
                          "description": "Short, headline-style title — aim for "
                                         "≤ 6 words / ~40 chars, no trailing "
                                         "period. Keep season/filter qualifiers "
                                         "out of it (put them in subtitle)."},
                "subtitle": {"type": "string",
                             "description": "Optional one-line context: season, "
                                            "split, or filter the title omits."},
            },
            "required": ["sql", "chart_type", "title"],
        },
    },
}

VIEW_SCHEMA = """Analysis views you may query (read-only SELECT only):

v_player_games — one row per player per game
  player_name, name_key (lowercased, unaccented — filter players with
    name_key LIKE '%lastname%'), team (3-letter), opponent (3-letter),
  season ('2024-25'), season_type ('Regular Season' | 'Playoffs'),
  game_date (date), is_home (bool), won (bool),
  days_rest (int days since prev game, NULL on 1st; =1 means back-to-back),
  game_no (1..N within season),
  min, pts, reb, ast, stl, blk, tov, pf, oreb, dreb,
  fgm, fga, fg_pct, fg3m, fg3a, fg3_pct, ftm, fta, ft_pct, plus_minus

v_team_games — one row per team per game
  team (3-letter), opponent, season, season_type, game_date, is_home, won,
  days_rest, pts, opp_pts, margin (pts - opp_pts),
  reb, ast, stl, blk, tov, pf, fgm, fga, fg_pct, fg3m, fg3a, fg3_pct, plus_minus

v_shots — one row per shot attempt
  player_name, name_key, team_id, season, season_type, game_date,
  period (1-4; 5+ = OT), action_type, shot_type, is_three (bool),
  shot_zone_basic ('Restricted Area','In The Paint (Non-RA)','Mid-Range',
    'Left Corner 3','Right Corner 3','Above the Break 3'),
  shot_zone_range ('Less Than 8 ft.','8-16 ft.','16-24 ft.','24+ ft.'),
  shot_distance (ft), loc_x, loc_y, made (bool)

standings — season, team_city, team_name, conference, playoff_rank,
  wins, losses, win_pct

clutch_stats — one row per player per season; NBA "clutch" = last 5 minutes
  with the score within 5 points (a season aggregate, not per-game):
  player_name, team_abbreviation, season, gp, w, l, min,
  fgm, fga, fg_pct, fg3m, fg3a, fg3_pct, ftm, fta, ft_pct,
  reb, ast, tov, stl, blk, pts (total clutch points), plus_minus,
  dd2 (double-doubles), td3 (triple-doubles). Filter by player_name (ILIKE).

hustle_stats — one row per player per season:
  player_name, team_abbreviation, season, g, min, contested_shots,
  contested_shots_2pt, contested_shots_3pt, deflections, charges_drawn,
  screen_assists, screen_ast_pts, loose_balls_recovered, box_outs (season totals).

defense_tracking — one row per player per season (NBA tracking "defended" shots):
  player_name, player_position ('G','F','C','F-C',...), season, gp,
  freq (share of opponent shots they defended), d_fgm, d_fga,
  d_fg_pct (FG% allowed when defending), normal_fg_pct (those shooters' usual
  FG%), pct_plusminus (d_fg_pct - normal_fg_pct; NEGATIVE = good defense).

v_team_season — one row per team per season (derived):
  team (3-letter), season, gp, wins, losses, pts_pg (offense), opp_pts_pg
  (defense — lower is better), net_pg, fg3a_pg, fg3_pct. Use to rank teams or
  to define opponent-strength tiers (join v_*_games.opponent = v_team_season.team
  AND same season, then filter/rank by pts_pg or opp_pts_pg).

Derivable without extra tables:
- Double-double / triple-double GAMES: from v_player_games, e.g. count games
  where pts>=10 AND reb>=10 AND ast>=10. (clutch_stats.dd2/td3 are clutch-only.)
- Head-to-head: v_player_games / v_team_games already carry `opponent`; filter
  opponent = 'BOS' for "vs the Celtics". For two players facing each other,
  join v_player_games p1 and p2 on game_id where one's team = other's opponent.
- Games decided by N: filter v_team_games on abs(margin) <= N.

SQL rules:
- Percentages: aggregate as sum(fgm)::numeric/nullif(sum(fga),0), NOT avg(fg_pct).
- Booleans (won, is_home, made, is_three) can go in WHERE or in
  count(*) FILTER (WHERE ...). Cast made/shot_made for rates: avg(made::int).
- Filter players by name_key LIKE '%curry%' (lowercase, no accents). If the user
  uses a nickname, translate it to the real surname for name_key — e.g. SGA ->
  '%gilgeous%', CP3 -> '%paul%', Wemby -> '%wembanyama%', Greek Freak ->
  '%antetokounmpo%', the Joker -> '%jokic%', KD -> '%durant%'.
- Opponent is the 3-letter abbreviation (LAL, GSW, BOS, ...).
- When grouping by a CASE/computed column, use GROUP BY 1 (or repeat the full
  expression) and don't alias it to an existing column name like 'matchup'.
- Always GROUP appropriately and alias columns to match your x/y/series."""

CANNOT_ANSWER = """You CANNOT answer (no data) — say so plainly instead of guessing:
- Per-game or per-possession clutch timelines, score-margin-at-a-moment, or
  quarter-by-quarter timing (no play-by-play). NOTE: season-aggregate clutch
  IS available in clutch_stats (use it for "best clutch scorer/shooter"); only
  the per-moment timeline is missing.
- Lineup / on-off impact ("how does the team play with X on vs off the floor"),
  5-man lineup ratings, starter vs bench, who fouled out (no lineup data;
  pf is the game total).
- Play-type splits (pick-and-roll, transition, spot-up, post-up) — no Synergy data.
- Who defended a specific shot, OR filtering shots by how open the shooter was.
  Shot locations (v_shots loc_x/loc_y) and defender-distance data live in
  separate tables that can't be joined per shot: shot data has coordinates but
  no defender column, and defender data is season aggregates with no
  coordinates. So an "open shots only" shot chart or heatmap is impossible —
  the NBA stopped publishing per-shot defender tracking publicly in 2016.
  The defender_distance_efficiency template (FG%/eFG% by how tightly guarded)
  and defense_tracking (overall defended FG% per defender) are the defensive
  data available, both as season aggregates.
- Height, age, salary, injuries, draft — not stored (rough position IS in
  defense_tracking.player_position).
When a question needs data you don't have, decline cleanly, briefly say why
it's missing, and offer the closest thing you CAN show — e.g. for "where does
X shoot when open", offer defender_distance_efficiency (how X shoots by
defender distance) and/or the full shot_heatmap (where all X's shots come
from). Do NOT render an overall/unfiltered chart as a hedged substitute for
the filtered one the user asked for."""


def system_prompt() -> str:
    seasons = available_seasons()
    latest = seasons[-1] if seasons else current_season()
    season_list = ", ".join(seasons) if seasons else "the last ~5 seasons"
    return f"""You are an NBA data visualization assistant. Answer questions by \
rendering a chart, then give a one-or-two-sentence takeaway.

SEASONS — read carefully:
- The database holds exactly these seasons: {season_list} (regular season + playoffs).
- The CURRENT season is {latest}. When the user says "this season", "this year", \
"currently", "right now", "lately", or gives no season at all, use {latest} \
(in SQL: season = '{latest}'; for templates, omit the season param to default to it).
- "last season" / "last year" means {seasons[-2] if len(seasons) > 1 else latest}.
- Never use a season outside the list above — those have no data.

Decide which tool to use:
- render_chart — use whenever a curated template fits (it's faster and prettier).
  Templates:
{catalog_prompt()}
- query_chart — use for anything templates don't cover: comparisons across custom \
date ranges, specific opponents, home/away or win/loss splits on stats templates \
don't expose, multi-condition filters, league-wide aggregates, etc.

{VIEW_SCHEMA}

{CANNOT_ANSWER}

Rules:
- You may render UP TO 4 charts in one answer — call a chart tool once per
  chart and they'll be shown side by side. Do this when the question asks for
  charts "side by side", or naturally wants a few views (e.g. "compare Curry's
  and Tatum's shot charts" -> two shot_chart calls; "show LeBron's scoring and
  shooting trends" -> two player_stat_trend calls). Don't render multiple
  unless it clearly helps; one good chart beats several redundant ones.
- Pass player/team names as the user said them to render_chart (server fuzzy-matches).
- Keep chart titles short and punchy — a headline, not a sentence (aim for ≤ 6 \
words / ~40 chars). Don't restate the season or filters in the title; put those \
in the subtitle. Long titles get clipped.
- Omit season to default to the current one.
- If a tool returns an error, read it, fix your params or SQL, and try again \
(you have a couple of retries).
- After a chart renders, give a brief data-driven insight from the tool result \
summary — don't describe the chart visually."""


def _parse_args(raw: str) -> dict:
    """Parse tool-call arguments defensively. Small models sometimes
    double-encode the JSON (a string containing JSON) or return a bare value;
    normalize to a dict or raise a clear, model-actionable error."""
    try:
        val = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        raise ValueError("Your tool arguments were not valid JSON. "
                         "Return a JSON object with the documented fields.")
    if isinstance(val, str):  # double-encoded — unwrap once more
        try:
            val = json.loads(val)
        except (json.JSONDecodeError, TypeError):
            pass
    if not isinstance(val, dict):
        raise ValueError("Tool arguments must be a JSON object with the "
                         "documented fields, not a bare value.")
    return val


def _dispatch(name: str, args: dict):
    if name == "render_chart":
        tid = args.get("template_id")
        if not tid:
            raise ValueError(
                f"render_chart needs 'template_id' (one of: {', '.join(CATALOG)}).")
        return run_template(tid, args.get("params") or {})
    if name == "query_chart":
        return run_query_chart(args)
    raise ValueError(f"Unknown tool {name}")


def run_agent(message: str, theme: str | None = None) -> dict:
    """Answer one question. Single-turn by design — no conversation history;
    each question is independent.

    `theme` selects the chart color scheme (see app.theme.THEMES).

    Returns {"reply": str, "figures": list[dict]} — one entry per chart, in
    render order, so the UI can lay several out side by side."""
    from app.theme import set_theme
    set_theme(theme)
    client = _client()
    messages = [{"role": "system", "content": system_prompt()},
                {"role": "user", "content": message}]

    tools = [RENDER_CHART_TOOL, QUERY_CHART_TOOL]
    figures: list[dict] = []
    for _ in range(MAX_TURNS):
        try:
            resp = _complete(client, model=_model(), messages=messages,
                             tools=tools, temperature=0.1, max_tokens=1200)
        except openai.APIError as e:
            log.warning("model unavailable after retries: %s", e)
            note = ("The model is having trouble right now — the free router hit "
                    "a bad provider. Please try again in a moment.")
            return {"reply": note, "figures": figures}
        choice = resp.choices[0].message

        if not choice.tool_calls:
            return {"reply": choice.content or "", "figures": figures}

        messages.append({"role": "assistant", "content": choice.content,
                         "tool_calls": [tc.model_dump() for tc in choice.tool_calls]})
        for tc in choice.tool_calls:
            try:
                args = _parse_args(tc.function.arguments)
                result = _dispatch(tc.function.name, args)
                if len(figures) >= MAX_FIGURES:
                    feedback = (f"Chart not rendered: limit of {MAX_FIGURES} "
                                "charts per answer reached.")
                else:
                    figures.append(json.loads(result.figure.to_json()))
                    feedback = f"Chart rendered. Data summary: {result.summary}"
            except Exception as e:  # noqa: BLE001 — error text goes back to the model
                log.warning("tool error: %s", e)
                feedback = f"ERROR: {e}"
            messages.append({"role": "tool", "tool_call_id": tc.id,
                             "content": feedback})

    return {"reply": "Sorry, I couldn't build that chart after a few attempts.",
            "figures": figures}


def propose_tool_call(message: str, model: str | None = None,
                      force_template: bool = True) -> dict | None:
    """Single model call, no execution — used by the eval harness.

    force_template pins tool_choice to render_chart (template-selection eval).
    Set False to let the model freely choose render_chart vs query_chart.
    """
    client = _client()
    # Offer only render_chart and let the model choose to call it (auto). A
    # forced {"type":"function",...} tool_choice is rejected by several
    # OpenRouter providers, so auto is the portable way to measure template
    # selection across models.
    tools = [RENDER_CHART_TOOL] if force_template else [RENDER_CHART_TOOL, QUERY_CHART_TOOL]
    resp = client.chat.completions.create(
        model=model or _model(),
        messages=[{"role": "system", "content": system_prompt()},
                  {"role": "user", "content": message}],
        tools=tools, tool_choice="auto", temperature=0.0, max_tokens=600)
    tcs = resp.choices[0].message.tool_calls
    if not tcs:
        return None
    args = json.loads(tcs[0].function.arguments)
    return {"tool": tcs[0].function.name, **args}
