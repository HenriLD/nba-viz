---
title: Court Vision
emoji: 🏀
colorFrom: gray
colorTo: yellow
sdk: docker
app_port: 7860
pinned: false
---

<div align="center">

# 🏀 Court Vision

### Ask an NBA question in plain English — get a broadcast-quality, interactive chart back.

[**▶ Try it live**](https://henrild-nba-viz.hf.space) &nbsp;·&nbsp; [How it works](#how-it-works) &nbsp;·&nbsp; [Run it yourself](#run-it-yourself)

</div>

---

I got tired of clicking through stat-site dropdowns to answer simple basketball
questions, so I built a thing where you just *ask*. Type what you're curious
about — it works out the query, builds the chart, and draws it. No filters, no
menus, no query builder.

> *"Show me Steph Curry's shot chart this season"*
> <br> *"Jokić vs Embiid scoring by season"*
> <br> *"Who's been the most clutch this year?"*
> <br> *"How does SGA shoot against tight defense vs wide open?"*
> <br> *"Warriors' three-point trend, 10-game rolling average"*

## What it can show

| Ask about… | You get |
|---|---|
| A player's scoring, rebounds, assists… over a season | Game-by-game trend line with a rolling average |
| Two or more players head-to-head | Season-average comparison (one season or a whole career arc) |
| Shot selection | Make/miss shot chart on a drawn court |
| Hot zones | Shot-density heatmap |
| Shooting vs. defensive pressure | FG% / eFG% split by closest-defender distance |
| League leaders in any stat | Top-N leaderboard (min. 20 games) |
| The playoff race | Standings by conference |
| Team form | Team stat trend with a rolling average |
| Shot diet by zone | Volume + accuracy per court zone |
| Splits — home/away, wins/losses, rest | Side-by-side comparison |
| How consistent a player is | Violin + box of every game, optionally split by result or venue |
| Clutch, hustle, tracking defense | Best clutch scorers, deflections, screen assists, defended FG% |
| Efficiency — true shooting, per-36, points-per-shot | Rate leaderboards with a volume floor, not raw totals |
| Team strength — offense vs. defense, pace, four factors | Pace-adjusted ratings from a team-season rollup |
| Who broke out or fell off, year over year | Ranked by the change vs. last season |
| Situational shot charts — clutch, by quarter, vs. an opponent, in wins | Filtered/colored make-miss chart on the court |
| **Anything else** — odd date ranges, specific opponents, multi-condition filters | It writes a sandboxed SQL query and picks a chart for it |

Everything's interactive — hover for the box score, zoom, pan. Box scores reach
all the way back to **1980-81** (46 seasons); shot charts, heatmaps and tracking
splits cover the **last ~5 seasons**, where the NBA actually published that
detail. Regular season and playoffs, refreshed daily while games are on.

## How it works

```
your question ──> the model picks ONE of two tools:
                  │
                  ├─ render_chart  → a hand-tuned template + slot values
                  │                  (fast, polished; covers the common asks)
                  │
                  └─ query_chart   → a read-only SQL SELECT it writes itself,
                                     mapped onto a chart
                                     (odd date ranges, opponents, constraints)
                        ▼
              Postgres (46 seasons of box logs + recent shots, friendly views) ──>
                  Plotly figure ──> rendered in your browser
```

The fun constraint I set myself: run the whole thing on **free models**.
OpenRouter's free tier can hand you a different model from one minute to the
next, so the app is built not to care who's driving — two paths and a stack of
guardrails do the work:

- **Templates** for the common stuff — the model picks one of 11 hand-tuned
  charts and fills in the blanks. Fast, consistent, hard to get wrong.
- **Sandboxed SQL** for everything else — the model writes its own read-only
  `SELECT` against friendly views (home/away, opponent, win, rest, margin and a
  pile of advanced rate columns are precomputed) and maps the result onto one of
  11 chart types. It writes surprisingly good SQL and fixes its own mistakes
  straight from the error messages. The query runs read-only, single-statement,
  keyword-checked, row-capped and time-limited — it can only ever look, never
  touch.

I benchmarked this across nine models, from a 9B up to a 120B, and it lands
**~90%+** on a 127-question set either way — so even when the free router rolls
you something tiny, it holds up. (Full writeup, including where it breaks, in
[EXPERIMENTS.md](EXPERIMENTS.md).)

A few things keep it honest: names are fuzzy-matched and accent-folded ("steph",
"curry", "jokic" all land), stats come from a fixed whitelist, and I tell the
model up front what the data *can't* answer — lineups, on/off splits, play-types,
injuries — so it says "I can't show that" instead of inventing a number.

Data comes from stats.nba.com (via [`nba_api`](https://github.com/swar/nba_api))
into a Neon Postgres database, synced daily in season. Hosting is free on Hugging
Face Spaces; the only real bills are model tokens and a small database.

## What it can't do (yet)

- **No raw player-tracking.** The NBA stopped publishing raw movement coordinates
  in 2016, so defender questions lean on official aggregate splits (shooting by
  closest-defender distance: 0–2 / 2–4 / 4–6 / 6+ ft). You can't ask for "every
  possession where two defenders collapsed."
- **Box scores to 1980, shots to ~5 seasons.** Career arcs and history go back to
  1980-81; shot charts, heatmaps and tracking splits only exist for roughly the
  last five seasons.
- **No lineup or play-type data.** On/off splits, 5-man lineup ratings, and
  pick-and-roll / post-up / transition breakdowns aren't published in a form I
  ingest — so it declines rather than approximate.
- **Charts, not chat.** Eleven chart types. If a question doesn't map to one, it
  tells you and suggests what it *can* show instead of making something up.

## Run it yourself

You'll need Python 3.12+, a free [Neon](https://neon.tech) Postgres database, and
an [OpenRouter](https://openrouter.ai) key (any cheap tool-calling model works).

```sh
git clone https://github.com/HenriLD/nba-viz && cd nba-viz
python -m venv .venv && .venv\Scripts\activate    # Windows; use bin/activate on Unix
pip install -r requirements.txt

# schema, analysis views, and the advanced rollups
psql "$DATABASE_URL" -f db/schema.sql
psql "$DATABASE_URL" -f db/analysis_views.sql
psql "$DATABASE_URL" -f db/enrich.sql
```

Drop a `.env` in the repo root:

```ini
DATABASE_URL=postgresql+psycopg://user:pass@host/db?sslmode=require
OPENROUTER_API_KEY=sk-or-v1-...
OPENROUTER_MODEL=openrouter/free
```

`openrouter/free` routes to whatever free model is current — cheapest, but the
model underneath can change. Pin a named one (say `moonshotai/kimi-k2` or
`mistralai/mistral-medium-3-5`) if you want reproducible behavior.

Then backfill and run:

```sh
python -m ingest.backfill --n 5                              # recent seasons: box + shots + tracking
python -m ingest.backfill --start 1980 --end 2020 --box-only # deep history (box scores only)
uvicorn app.main:app --reload                               # open http://localhost:8000
```

> **⚠️ Run the backfill from a home connection.** stats.nba.com blocks most
> cloud/datacenter IPs. The daily incremental sync (`python -m ingest.sync`,
> ~11 requests) lives in GitHub Actions
> (`.github/workflows/daily-sync.yml`, needs a `DATABASE_URL` secret); the cron
> is commented out in the offseason and switched back on when games resume. If
> the Actions runners get blocked too, run the same command from any home
> machine on a scheduler.

To deploy the app, any Docker host works — the included `Dockerfile` serves on
port 7860 (Hugging Face Spaces' default). Set the same three env vars as secrets.

## Picking a model

The agent is provider-agnostic — any OpenRouter slug with tool calling. One
question set, [`eval/flexible_questions.json`](eval/flexible_questions.json),
drives the whole eval: it runs the full agent and checks a chart renders when it
should (or the model correctly declines), plus soft signals for whether a
"who's best" question reached for a quality metric and whether the right template
got picked.

```sh
# end-to-end: model writes SQL or picks a template, it runs, a chart renders
python -m eval.run_eval --models moonshotai/kimi-k2 --runs 3

# compare several models: accuracy, latency, tokens
python -m eval.benchmark --models moonshotai/kimi-k2 qwen/qwen-2.5-72b-instruct
```

The bigger benchmark-driven digs (like the templates-vs-pure-SQL study across
nine models) are written up in [`EXPERIMENTS.md`](EXPERIMENTS.md).

## Project layout

```
core/    db engine, idempotent upserts, the sandboxed safe_select, stat
         whitelist, season helpers
db/      schema.sql, analysis_views.sql (friendly views), enrich.sql
         (advanced rollups: efficiency, team ratings, improvement, clutch)
ingest/  nba_api wrappers, incremental daily sync, one-time backfill
app/     FastAPI, the agent loop (two tools), chart templates, the generic
         SQL renderers (charts.py), court drawing, theme, chat UI
eval/    the model-comparison harness (template + flexible/SQL modes)
```

Visit `/gallery` while the server's running to render every template and a couple
of query examples on one page — visual QA, no LLM calls.

### Adding a chart template

1. Write a `_my_template(params) -> ChartResult` in
   [`app/templates.py`](app/templates.py) (parameterized SQL + a Plotly builder).
2. Register it in `CATALOG` with a description written *for the model* — say
   *when* to use it, not just what it is.
3. Add a case to [`eval/flexible_questions.json`](eval/flexible_questions.json)
   (set `template`/`params` to pin the routing) and re-run the eval.

PRs welcome — more templates, nicer court drawing, more seasons. 🏀
