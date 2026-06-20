# Experiments

A log of benchmark-driven investigations behind Court Vision's design. The features
they exercise live in the codebase but are **off by default** in production
(env-gated) — e.g. the SQL-only mode below is `AGENT_SQL_ONLY=1`, unset in normal
operation.

---

## SQL-only backend — how far down the model-size curve does it hold?

**Question.** Court Vision ships two tools: `render_chart` (curated templates) and
`query_chart` (model-written SQL). If we *remove the templates entirely* and force the
model to express every question as SQL + a chart_type — keeping only the
**visualization** layer templated (`app/charts.py` renderers) — how much do we lose,
and how small a model can still drive it?

**Setup.** `AGENT_SQL_ONLY=1` (env, or `run_eval --sql-only`) drops `render_chart` and
swaps the prompt's tool-decision block for a single-tool "SQL for everything" brief. The
127-question benchmark (`eval/flexible_questions.json`) is scored end-to-end: a figure
when expected, or a correct decline.

**Headline:** removing the entire template catalog costs **~2 points** on the free
router (94% → 92%), and the gap was a single cause — the `defender_shooting` table (the
data behind the defender-distance template) was **never documented in the prompt schema**.
The template silently encapsulated that knowledge; the SQL path couldn't see the table
and declined. Documenting it closed the gap.

### Per-model results (SQL-only, capability-adjusted)

"Capability" excludes questions where every retry hit a rate-limit (429) — i.e. the model
never got to answer. Raw scores understate models that ran while the free-tier daily cap
was tight.

| Model | Size | Capability | Notes |
|---|---|---|---|
| openai/gpt-oss-20b | 20B | **96%** | clean |
| nvidia/nemotron-3-nano-30b-a3b | 30B / 3B active (MoE) | **94%** | clean |
| openai/gpt-oss-120b | 120B | **94%** | clean |
| cohere/north-mini-code | 30B / 3B active (MoE) | **93%** | clean |
| nex-agi/nex-n2-pro | 397B / 17B active (MoE) | **93%** | clean |
| nvidia/nemotron-nano-9b-v2 | 9B | **90%** | clean |
| google/gemma-4-31b-it | 31B | **89%** | raw 71%; 26 questions rate-limited out |
| poolside/laguna-xs.2 | 33B / 3B active (MoE) | **89%** | clean |
| **liquid/lfm-2.5-1.2b-thinking** | **1.2B** | **11%** | **floor — tool-calling, not SQL** |

### Findings

1. **SQL-only ≈ curated templates.** 89–96% across a 9B→120B range, dense and MoE,
   instruct and code-tuned. A fully-liberated SQL backend matches the templated path
   given *complete schema docs*. Templates' measurable value here was niche-table
   knowledge, not small-model hand-holding.
2. **The floor is tool-calling, not reasoning.** It only collapses at 1.2B — and there the
   model writes *fine* SQL; it just emits it as prose instead of a structured tool call, so
   the agent reads it as a decline (all 113 failures were healthy completions, zero
   rate-limiting). A sub-~9B path would need to *parse SQL from text* rather than rely on
   function-calling.
3. **gemma's "71%" was a rate-limit artifact**, not weakness — 26 of its 37 misses were
   all-429 questions it never answered. Its real capability is ~89%, in the pack.

### Reproduce

```sh
# one model / the free router
python -m eval.run_eval --sql-only --models openrouter/free

# small-model sweep, paced under the free 16/min cap, resume-safe + checkpointed
python -m eval.run_eval --sql-only --max-rpm 16 --checkpoint-every 10 \
  --out eval/results/sqlonly_smallmodels.json --models <slug> <slug> ...
```

Free-tier gotchas this surfaced (all handled in the harness): a global **16 req/min** cap
and a **daily** cap (~22 h lockout) — `--max-rpm` throttles globally (retries included);
`--out` + `--checkpoint-every` make a run resume-safe at the *question* level (this machine
interrupted mid-run repeatedly); per-question generation ids are logged on every failure
(`trace:` lines) for OpenRouter reasoning-trace lookup. Raw per-question results +
traces land in the git-ignored `eval/results/`.

### Open threads

- Bake rate-limit-aware scoring (capability vs availability) into `run_eval` instead of
  post-hoc.
- A sub-9B "SQL-from-text" path (no tool calls) to test whether the *reasoning* floor is
  lower than the *tool-calling* floor.

The tool-feedback loop this surfaced (clearer SQLSTATE-translated errors, chart-type-aware
data summaries) shipped to production — see `core/db.py` / `app/charts.py`.
