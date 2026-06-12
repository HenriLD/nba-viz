---
title: nba-viz
emoji: 🏀
colorFrom: gray
colorTo: yellow
sdk: docker
app_port: 7860
pinned: false
---

# nba-viz

Ask for NBA charts in plain English. A small LLM (via OpenRouter) maps your
question onto a catalog of pre-built chart templates; the server runs
parameterized SQL against a Postgres database that syncs daily from
stats.nba.com, and renders Plotly charts in a chat UI.

```
question ──> small model picks template + params ──> validated SQL ──> Plotly chart
                 (OpenRouter tool call)              (Postgres, Neon free tier)
```

The model never writes SQL or chart code — it makes exactly one tool call
(`render_chart`) with an enum-constrained template ID and slot-filled params.
Player/team names are fuzzy-matched server-side so the model doesn't need
exact spellings. This is what makes cheap models (Kimi, Qwen, Mistral) viable.

## Stack (free-tier-only, except model tokens)

| Layer | Choice |
|---|---|
| Data source | stats.nba.com via [`nba_api`](https://github.com/swar/nba_api) |
| Database | Postgres — [Neon](https://neon.tech) free tier (~0.5 GB, 5 seasons fits) |
| Daily sync | GitHub Actions cron (`.github/workflows/daily-sync.yml`), local fallback |
| Backend + agent | FastAPI + OpenRouter (OpenAI-compatible tool calling) |
| Charts | Plotly (server builds figure JSON, browser renders with Plotly.js) |
| Hosting | Hugging Face Spaces (Docker) or Render free tier |

## Setup

1. **Database** — create a free Neon project, then:
   ```sh
   psql "$DATABASE_URL" -f db/schema.sql
   ```
2. **Environment** — copy `.env.example` to `.env` and fill in
   `DATABASE_URL`, `OPENROUTER_API_KEY`, `OPENROUTER_MODEL`.
3. **Install**:
   ```sh
   python -m venv .venv && .venv\Scripts\activate   # Windows
   pip install -r requirements.txt
   ```
4. **Backfill** (one-time, ~10–20 min for 5 seasons — run from a home
   connection, see "Where to run ingest" below):
   ```sh
   python -m ingest.backfill --n 5
   ```
5. **Run**:
   ```sh
   uvicorn app.main:app --reload
   ```
   Open http://localhost:8000 and ask: *"Show me Curry's shot chart this season"*.

## Where to run ingest (important)

**stats.nba.com blocks many cloud/datacenter IPs.** The GitHub Actions cron
is configured as the primary daily sync, but if it fails with persistent
timeouts, run the identical script from a residential IP instead — e.g.
Windows Task Scheduler running `python -m ingest.sync` daily at 7am, pointed
at the same cloud `DATABASE_URL`. Everything downstream stays cloud-hosted;
only the scraper needs a friendly IP.

## Data scope and honest limitations

- **Stored**: ~5 seasons of player/team game logs, league-wide shot-level
  x/y coordinates (~220k shots/season), standings, and shooting splits by
  closest-defender distance.
- **Defender data is aggregate-only.** Raw player-movement tracking has not
  been public since 2016. "How does X shoot against tight defense" works
  (0–2ft / 2–4ft / 4–6ft / 6+ft buckets); "show possessions where two
  defenders collapsed" does not and cannot.
- No play-by-play (would blow the free Postgres tier); add later via
  parquet-on-R2 + DuckDB if wanted.

## Picking the model

```sh
python -m eval.run_eval --models moonshotai/kimi-k2 qwen/qwen-2.5-72b-instruct mistralai/mistral-small-3.1-24b-instruct
```

Scores each model on 16 canned questions (template + param accuracy, no DB
needed). Set the winner as `OPENROUTER_MODEL`. A typical chat query is 2
model calls over ~1.5k tokens — fractions of a cent on any of these.

## Deploy (Hugging Face Spaces)

1. Create a Space → Docker SDK.
2. Push this repo to the Space (the `Dockerfile` serves on port 7860).
3. Add `DATABASE_URL`, `OPENROUTER_API_KEY`, `OPENROUTER_MODEL` as Space secrets.

GitHub repo secrets needed for the cron: `DATABASE_URL`.

## Project layout

```
core/        shared: db engine + upserts, stat whitelist, season helpers
db/          schema.sql
ingest/      nba_api wrappers, daily sync, one-time backfill
app/         FastAPI, agent loop, template catalog, court drawing, chat UI
eval/        model comparison harness (16 questions)
```

## Adding a chart template

1. Write a `_my_template(params) -> ChartResult` function in
   `app/templates.py` (SQL + Plotly builder).
2. Register it in `CATALOG` with a description written *for the model* —
   say when to use it, not just what it is.
3. Add an eval question to `eval/questions.json` and re-run the eval.
