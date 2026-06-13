---
title: nba-viz
emoji: 🏀
colorFrom: gray
colorTo: yellow
sdk: docker
app_port: 7860
pinned: false
---

# 🏀 nba-viz — ask for NBA charts in plain English

**[Try it live →](https://henrild-nba-viz.hf.space)**

Type a basketball question, get an interactive chart. No dropdowns, no query
builder — just ask:

- *"Show me Steph Curry's shot chart this season"*
- *"Jokic vs Embiid scoring by season"*
- *"Who leads the league in assists?"*
- *"How does SGA shoot against tight defense compared to wide open?"*
- *"Where does Tatum like to shoot from?"*
- *"Warriors three-point shooting trend with a 10-game rolling average"*

## What it can show

| Ask about... | You get |
|---|---|
| A player's scoring, rebounds, assists... over a season | Game-by-game trend line with rolling average |
| Two or more players head-to-head | Season-average comparison (one season or career arc) |
| Shot selection | Make/miss shot chart on a drawn court |
| Hot zones | Shot-density heatmap |
| Shooting vs. defensive pressure | FG% / eFG% split by closest-defender distance |
| League leaders in any stat | Top-N leaderboard (min. 20 games) |
| The playoff race | Standings by conference |
| Team form | Team stat trend with rolling average |

Charts are fully interactive (hover for game details, zoom, pan) and the data
covers the **last 5 NBA seasons** — regular season and playoffs — refreshed daily.

## How it works

```
your question ──> small LLM picks a chart template + fills slots
                        │  (one strict-schema tool call — the model never
                        │   writes SQL or chart code)
                        ▼
              validated, parameterized SQL ──> Postgres (5 seasons of
                        │                      game logs + 1.1M shot locations)
                        ▼
                  Plotly figure ──> rendered in your browser
```

The interesting design constraint: this runs on a *cheap* model (Kimi K2 via
OpenRouter — fractions of a cent per question). Small models are unreliable at
writing SQL, but very good at picking one of 8 templates and filling in slots.
Player names are fuzzy-matched server-side ("steph", "curry", "Stephen Curry"
all work), stats come from a fixed whitelist, and every parameter is validated
before any query runs.

Data is pulled daily from stats.nba.com (via [`nba_api`](https://github.com/swar/nba_api))
into a free-tier Neon Postgres database. The whole stack runs on free hosting —
the only operating cost is model tokens.

## Honest limitations

- **No raw player-tracking data.** The NBA stopped publishing raw movement
  coordinates in 2016. Defender questions are answered from official aggregate
  splits (shooting by closest-defender distance: 0–2 ft / 2–4 ft / 4–6 ft /
  6+ ft) — you can't ask for things like "possessions where two defenders
  collapsed."
- **5-season window.** Career-arc questions reach back ~5 years, not to 1996.
- **8 chart types.** If your question doesn't map to a template, the bot says
  so and suggests what it *can* show instead of inventing data.

## Run your own

You need: Python 3.12+, a free [Neon](https://neon.tech) Postgres database,
and an [OpenRouter](https://openrouter.ai) API key (~any cheap tool-calling
model works).

```sh
git clone https://github.com/HenriLD/nba-viz && cd nba-viz
python -m venv .venv && .venv\Scripts\activate    # Windows; use bin/activate on Unix
pip install -r requirements.txt

# create the schema
psql "$DATABASE_URL" -f db/schema.sql
```

Create a `.env` in the repo root:

```ini
DATABASE_URL=postgresql+psycopg://user:pass@host/db?sslmode=require
OPENROUTER_API_KEY=sk-or-v1-...
OPENROUTER_MODEL=moonshotai/kimi-k2
```

Then backfill and run:

```sh
python -m ingest.backfill --n 5      # one-time, ~10-20 min for 5 seasons
uvicorn app.main:app --reload        # open http://localhost:8000
```

> **⚠️ Run the backfill from a home connection.** stats.nba.com blocks most
> cloud/datacenter IPs. The daily incremental sync (`python -m ingest.sync`,
> ~11 requests) is scheduled via GitHub Actions
> (`.github/workflows/daily-sync.yml`, needs a `DATABASE_URL` repo secret) —
> if Actions runners get blocked too, run the same command from any home
> machine on a scheduler.

To deploy the app itself, any Docker host works — the included `Dockerfile`
serves on port 7860 (Hugging Face Spaces' default). Set the same three
environment variables as secrets on the host.

## Picking a model

The agent is provider-agnostic (any OpenRouter slug with tool calling). An
eval harness scores candidates on 16 questions for template + parameter
accuracy, no database required:

```sh
python -m eval.run_eval --models moonshotai/kimi-k2 qwen/qwen-2.5-72b-instruct
```

## Project layout

```
core/        db engine + idempotent upserts, stat whitelist, season helpers
db/          schema.sql
ingest/      nba_api wrappers, incremental daily sync, one-time backfill
app/         FastAPI, agent loop, chart templates, court drawing, chat UI
eval/        model comparison harness
```

### Adding a chart template

1. Write a `_my_template(params) -> ChartResult` function in
   [`app/templates.py`](app/templates.py) (parameterized SQL + Plotly builder).
2. Register it in `CATALOG` with a description written *for the model* — say
   when to use it, not just what it is.
3. Add a case to [`eval/questions.json`](eval/questions.json) and re-run the eval.

PRs welcome — more templates, better court drawing, more seasons.
