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

app = FastAPI(title="nba-viz")
STATIC = Path(__file__).parent / "static"


class ChatTurn(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=500)
    history: list[ChatTurn] = []


@app.post("/api/chat")
def chat(req: ChatRequest):
    try:
        result = run_agent(req.message, [t.model_dump() for t in req.history])
        return result
    except Exception as e:  # surface a friendly error, log the real one
        log.exception("chat failed")
        raise HTTPException(status_code=500, detail=str(e))


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

    from app.templates import run_template

    cases = [
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
    ]
    blocks = []
    for tid, params in cases:
        try:
            fig = run_template(tid, params).figure
            blocks.append(f"<div class='chart'>{fig.to_html(full_html=False, include_plotlyjs=False, config={'responsive': True, 'displaylogo': False})}</div>")
        except Exception as e:  # noqa: BLE001 — QA page shows failures inline
            blocks.append(f"<div class='chart err'><b>{tid}</b> failed: {e}</div>")
    return HTMLResponse(f"""<!DOCTYPE html><html><head>
<script src="https://cdn.plot.ly/plotly-3.6.0.min.js"></script>
<style>body{{background:#12161b;margin:0;padding:24px;font-family:Georgia,serif}}
.chart{{max-width:880px;margin:0 auto 28px;border-radius:14px;overflow:hidden;
border:1px solid #232b34}}
.err{{color:#e0654f;padding:20px;background:#161c23}}</style>
</head><body>{''.join(blocks)}</body></html>""")
