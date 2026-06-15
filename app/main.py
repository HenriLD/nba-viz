"""FastAPI app: chat endpoint + static frontend.

Run locally:  uvicorn app.main:app --reload
"""
import logging
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from app.agent import run_agent

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("app")

app = FastAPI(title="Court Vision")
STATIC = Path(__file__).parent / "static"


class ChatRequest(BaseModel):
    # Single-turn by design: every question is independent, no conversation
    # history. Each request stands alone.
    message: str = Field(min_length=1, max_length=500)
    theme: str | None = None   # chart color scheme id (see app.theme.THEMES)


@app.post("/api/chat")
def chat(req: ChatRequest):
    try:
        result = run_agent(req.message, theme=req.theme)
    except Exception as e:  # surface a friendly error, log the real one
        log.exception("chat failed")
        raise HTTPException(status_code=500, detail=str(e))
    # Decorative entity side-cards (players/teams shown on the rendered charts).
    # Resolved from the output, not the question, so every plotted entity gets a
    # card and stray question words can't conjure one. No LLM and never fatal —
    # a failure here must not sink an otherwise-good answer.
    try:
        from app.cards import cards_for
        result["entities"] = cards_for(result.get("figures") or [])
    except Exception:
        log.warning("entity cards failed", exc_info=True)
    return result


@app.get("/api/themes")
def themes():
    from app.theme import theme_options
    return {"themes": theme_options()}


@app.get("/api/health")
def health():
    return {"ok": True}


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")


@app.get("/gallery")
def gallery():
    """Dev-only visual QA: render every template with canned params on one
    page. Hits the DB but never the LLM."""
    from fastapi.responses import HTMLResponse

    from app.charts import run_query_chart
    from app.templates import run_template
    from app.theme import set_theme

    set_theme(None)  # gallery always renders in the default theme

    template_cases = [
        ("player_stat_trend", {"player": "stephen curry", "stat": "pts",
                               "rolling_window": 10}),
        ("player_comparison", {"players": ["jokic", "embiid", "luka doncic"],
                               "stat": "pts"}),
        ("player_comparison", {"players": ["jokic", "embiid"], "stat": "pts",
                               "season": "2023-24"}),
        ("shot_chart", {"player": "stephen curry"}),
        ("shot_heatmap", {"player": "jayson tatum"}),
        ("defender_distance_efficiency", {"player": "shai gilgeous-alexander"}),
        ("league_leaders", {"stat": "ast", "top_n": 10}),
        ("standings", {}),
        ("team_stat_trend", {"team": "warriors", "stat": "fg3_pct",
                             "rolling_window": 10}),
        ("shot_zone_breakdown", {"player": "stephen curry"}),
        ("player_split", {"player": "luka doncic", "stat": "pts", "split": "win_loss"}),
        ("player_split", {"player": "nikola jokic", "stat": "reb", "split": "rest"}),
        ("stat_distribution", {"player": "nikola jokic", "stat": "pts", "split": "win_loss"}),
        ("stat_distribution", {"players": ["nikola jokic", "joel embiid", "luka doncic"], "stat": "pts"}),
        ("stat_distribution", {"teams": ["lakers", "celtics"], "stat": "pts"}),
    ]
    query_cases = [
        ("Curry: home vs away 3P% this season", {
            "sql": "SELECT CASE WHEN is_home THEN 'Home' ELSE 'Away' END AS loc, "
                   "sum(fg3m)::numeric/nullif(sum(fg3a),0) AS fg3_pct "
                   "FROM v_player_games WHERE name_key LIKE '%curry%' "
                   "AND season='2025-26' AND season_type='Regular Season' GROUP BY 1",
            "chart_type": "bar", "x": "loc", "y": "fg3_pct",
            "title": "Curry — 3P% home vs away"}),
        ("Lakers margin vs each opponent", {
            "sql": "SELECT opponent, avg(margin) AS avg_margin FROM v_team_games "
                   "WHERE team='LAL' AND season='2025-26' "
                   "AND season_type='Regular Season' GROUP BY opponent "
                   "ORDER BY avg_margin DESC",
            "chart_type": "horizontal_bar", "x": "opponent", "y": "avg_margin",
            "title": "Lakers — average margin by opponent, 2025-26"}),
    ]
    blocks = []
    for tid, params in template_cases:
        try:
            fig = run_template(tid, params).figure
            blocks.append(f"<div class='chart'>{fig.to_html(full_html=False, include_plotlyjs=False, config={'responsive': True, 'displaylogo': False})}</div>")
        except Exception as e:  # noqa: BLE001 — QA page shows failures inline
            blocks.append(f"<div class='chart err'><b>{tid}</b> failed: {e}</div>")
    for name, args in query_cases:
        try:
            fig = run_query_chart(args).figure
            blocks.append(f"<div class='chart'>{fig.to_html(full_html=False, include_plotlyjs=False, config={'responsive': True, 'displaylogo': False})}</div>")
        except Exception as e:  # noqa: BLE001
            blocks.append(f"<div class='chart err'><b>query: {name}</b> failed: {e}</div>")
    return HTMLResponse(f"""<!DOCTYPE html><html><head>
<script src="https://cdn.plot.ly/plotly-3.6.0.min.js"></script>
<style>body{{background:#12161b;margin:0;padding:24px;font-family:Georgia,serif}}
.chart{{max-width:880px;margin:0 auto 28px;border-radius:14px;overflow:hidden;
border:1px solid #232b34}}
.err{{color:#e0654f;padding:20px;background:#161c23}}</style>
</head><body>{''.join(blocks)}</body></html>""")
