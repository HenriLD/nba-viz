"""Benchmark the chart agent end-to-end on the single consolidated question
set, eval/flexible_questions.json.

Each case: {q, expect_figure, want_metric?, template?, params?}. The harness
runs the FULL agent (the model writes SQL or picks a template, executes, and
renders) and scores one thing: a figure is produced when expected, or the model
correctly declines. Two soft signals are reported but don't change the score:
  - want_metric: an interpretive question should land on a quality metric
                 (TS%, rating, delta…), not a raw total.
  - template:    a template-route question should use that template (routing).

Usage:
    python -m eval.run_eval --models openrouter/free
    python -m eval.run_eval --models openrouter/free --runs 3
"""
import argparse
import json
import sys
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from app import agent

_DIR = Path(__file__).parent
CASES = json.loads((_DIR / "flexible_questions.json").read_text())


def _param_ok(key: str, expected, actual) -> bool:
    """Loose param match for the template-routing path (also used by
    eval/benchmark.py). Names match on substring (the model may expand 'sga');
    a players list just needs 2+ entries; everything else matches exactly."""
    if actual is None:
        return False
    if key in ("player", "team"):
        return str(expected).lower() in str(actual).lower() or \
               str(actual).lower() in str(expected).lower()
    if key == "players":
        return isinstance(actual, list) and len(actual) >= 2
    return str(actual).lower() == str(expected).lower()


def _grade(case: dict, figures: list, reply: str, used: list[str],
           check_routing: bool = True) -> tuple[bool, list[str]]:
    """Score one finished answer: (figure_correct, soft_notes)."""
    notes = []
    got_fig = len(figures) > 0
    correct = got_fig == case["expect_figure"]
    if not correct:
        want = "a chart" if case["expect_figure"] else "a decline"
        notes.append(f"  WRONG  {case['q']!r}\n"
                     f"         expected {want}, got "
                     f"{'chart' if got_fig else 'decline'}: {reply[:90]}")
    if got_fig:
        # Soft: did a superlative land on a rate/efficiency/uplift metric?
        wm = case.get("want_metric")
        if wm:
            blob = json.dumps(figures).lower()
            if not any(k in blob for k in wm):
                notes.append(f"  BASIC  {case['q']!r}\n"
                             f"         figure shows no {wm} metric "
                             "(likely a raw-total leaderboard)")
        # Soft: did a template-route question use the expected template?
        # (Skipped in SQL-only mode — there are no templates to route to.)
        tmpl = case.get("template")
        if check_routing and tmpl and tmpl not in used:
            notes.append(f"  ROUTE  {case['q']!r}\n"
                         f"         expected template {tmpl}, used {used}")
    return correct, notes


def score(model: str, workers: int = 8, check_routing: bool = True,
          prior: dict | None = None, on_checkpoint=None,
          checkpoint_every: int = 10) -> tuple[int, int, list[str], dict]:
    """Run the full agent on every case (in a thread pool — the work is network
    I/O). Returns (figure_correct, total, notes, results). The dispatch spy
    records the template per question into thread-local storage so parallel
    workers don't clobber each other.

    Question-level resume: questions whose str(index) is already in `prior` are
    skipped; on_checkpoint(results) fires every `checkpoint_every` completions so
    an interrupted model resumes mid-stream rather than restarting from zero."""
    import os
    os.environ["OPENROUTER_MODEL"] = model

    tl = threading.local()
    orig_dispatch = agent._dispatch

    def spy(name, args):
        u = getattr(tl, "used", None)
        if u is not None:
            u.append(args.get("template_id") if name == "render_chart" else "query_chart")
        return orig_dispatch(name, args)

    def run_one(i: int, case: dict):
        tl.used = []
        agent.begin_gen_capture()
        try:
            r = agent.run_agent(case["q"])
        except Exception as e:  # noqa: BLE001
            return i, False, [f"  ERROR  {case['q']!r}: {e}",
                              f"         trace: {agent.take_gen_ids()}"]
        gen_ids = agent.take_gen_ids()
        ok, notes = _grade(case, r["figures"], r.get("reply", ""), list(tl.used),
                           check_routing=check_routing)
        if notes:  # attach the question's generation ids for trace lookup
            notes.append(f"         trace: {gen_ids}")
        return i, ok, notes

    agent._dispatch = spy
    results: dict = dict(prior or {})  # str(idx) -> {"ok": bool, "notes": [...]}
    todo = [i for i in range(len(CASES)) if str(i) not in results]
    done_n = 0
    try:
        with ThreadPoolExecutor(max_workers=workers) as ex:
            futs = [ex.submit(run_one, i, CASES[i]) for i in todo]
            for f in as_completed(futs):
                i, ok, notes = f.result()
                results[str(i)] = {"ok": ok, "notes": notes}
                done_n += 1
                if on_checkpoint and done_n % checkpoint_every == 0:
                    on_checkpoint(results)
    finally:
        agent._dispatch = orig_dispatch
    if on_checkpoint:
        on_checkpoint(results)  # flush the remainder

    correct = sum(1 for r in results.values() if r["ok"])
    notes = [n for i in range(len(CASES)) if str(i) in results
             for n in results[str(i)]["notes"]]  # in case order
    return correct, len(CASES), notes, results


def _print_provider_stats(entries: list[dict]) -> None:
    """Aggregate per-provider call health so we can spot empty-response
    providers to blacklist (env OPENROUTER_IGNORE_PROVIDERS)."""
    from collections import defaultdict
    agg: dict = defaultdict(lambda: {"calls": 0, "empty": 0, "models": set()})
    for e in entries:
        p = e.get("provider") or "?"
        agg[p]["calls"] += 1
        agg[p]["empty"] += 0 if e.get("healthy") else 1
        if e.get("model"):
            agg[p]["models"].add(e["model"])
    if not agg:
        return
    print(f"\n=== provider health ({len(entries)} calls across all runs) ===")
    print(f"{'provider':18} {'calls':>5} {'empty':>5} {'empty%':>7}   models served")
    for p, s in sorted(agg.items(), key=lambda kv: -kv[1]['empty'] / max(kv[1]['calls'], 1)):
        pct = s["empty"] / max(s["calls"], 1)
        flag = "  <-- BLACKLIST?" if pct >= 0.34 and s["calls"] >= 3 else ""
        models = ", ".join(sorted(m.split("/")[-1] for m in s["models"]))[:48]
        print(f"{p:18} {s['calls']:>5} {s['empty']:>5} {pct:>6.0%}   {models}{flag}")


def _print_model_stats(entries: list[dict]) -> None:
    """Per-underlying-model call health. The free router fans out across many
    models, so this shows which actual models the empties came from."""
    from collections import defaultdict
    agg: dict = defaultdict(lambda: {"calls": 0, "empty": 0, "providers": set()})
    for e in entries:
        m = e.get("model") or "?"
        agg[m]["calls"] += 1
        agg[m]["empty"] += 0 if e.get("healthy") else 1
        if e.get("provider"):
            agg[m]["providers"].add(e["provider"])
    if not agg:
        return
    print(f"\n=== model health ({len(agg)} distinct models) ===")
    print(f"{'model':42} {'calls':>5} {'empty':>5} {'empty%':>7}   providers")
    for m, s in sorted(agg.items(), key=lambda kv: -kv[1]['calls']):
        pct = s["empty"] / max(s["calls"], 1)
        flag = "  <-- flaky" if pct >= 0.34 and s["calls"] >= 3 else ""
        provs = ", ".join(sorted(s["providers"]))[:30]
        print(f"{m[:42]:42} {s['calls']:>5} {s['empty']:>5} {pct:>6.0%}   {provs}{flag}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--models", nargs="+", required=True,
                        help="OpenRouter model slugs to compare")
    parser.add_argument("--runs", type=int, default=1,
                        help="repeat the whole eval N times (free models vary)")
    parser.add_argument("--workers", type=int, default=8,
                        help="parallel questions in flight (network I/O bound)")
    parser.add_argument("--sql-only", action="store_true",
                        help="EXPERIMENT: drop render_chart, force SQL for everything "
                             "(sets AGENT_SQL_ONLY; skips the template routing check)")
    parser.add_argument("--max-rpm", type=float, default=0,
                        help="global cap on outgoing model calls/min (sets "
                             "AGENT_MAX_RPM) — stay under OpenRouter's free 16/min")
    parser.add_argument("--out", default=None,
                        help="persist results to this JSON; resume-safe at the "
                             "QUESTION level — completed models are skipped and a "
                             "half-done model resumes mid-stream on restart")
    parser.add_argument("--checkpoint-every", type=int, default=10,
                        help="with --out, save partial progress every N questions")
    args = parser.parse_args()

    import os
    if args.sql_only:
        os.environ["AGENT_SQL_ONLY"] = "1"
    if args.max_rpm and args.max_rpm > 0:
        os.environ["AGENT_MAX_RPM"] = str(args.max_rpm)

    agent.reset_call_log()
    n_tmpl = sum(1 for c in CASES if c.get("template"))
    n_dec = sum(1 for c in CASES if not c["expect_figure"])
    mode = "SQL-ONLY (no templates)" if args.sql_only else "templates + SQL"
    print(f"mode: {mode}")
    print(f"{len(CASES)} questions "
          f"({len(CASES) - n_dec} answerable, {n_dec} declines, "
          f"{n_tmpl} template-routed)")

    done: dict = {}
    if args.out and Path(args.out).exists():
        done = json.loads(Path(args.out).read_text())
        n_complete = sum(1 for v in done.values() if "correct" in v)
        print(f"resuming from {args.out}: {n_complete} model(s) complete, "
              f"{len(done) - n_complete} partially done")

    def _save():
        Path(args.out).write_text(json.dumps(done, indent=1))

    tallies: dict = {m: [] for m in args.models}
    for run in range(1, args.runs + 1):
        for model in args.models:
            entry = done.get(model) if args.out else None
            if entry and "correct" in entry:  # fully complete — skip
                c, t = entry["correct"], entry["total"]
                print(f"\n=== {model} — cached {c}/{t} ({c / t:.0%}) ===")
                tallies[model].append((c, t))
                continue
            prior = (entry or {}).get("results", {})
            tag = (f"resume {len(prior)}/{len(CASES)}" if prior
                   else f"run {run}/{args.runs}")
            print(f"\n=== {model} — {tag} ({args.workers} workers) ===", flush=True)

            def _checkpoint(results, model=model):  # save partial progress
                done[model] = {"results": results, "total": len(CASES)}
                _save()

            correct, total, notes, _ = score(
                model, workers=args.workers, check_routing=not args.sql_only,
                prior=prior, on_checkpoint=_checkpoint if args.out else None,
                checkpoint_every=args.checkpoint_every)
            tallies[model].append((correct, total))
            print(f"score: {correct}/{total} ({correct / total:.0%})")
            for n in notes:
                print(n)
            if args.out:  # finalize: replace the partial 'results' with the score
                done[model] = {"correct": correct, "total": total, "notes": notes}
                _save()

    if args.runs > 1:
        print("\n=== score summary (per run) ===")
        for model, runs in tallies.items():
            line = ", ".join(f"{c}/{t}" for c, t in runs)
            avg = sum(c for c, _ in runs) / sum(t for _, t in runs)
            print(f"{model}: {line}  (avg {avg:.0%})")

    _print_provider_stats(agent.call_log())
    _print_model_stats(agent.call_log())
    return 0


if __name__ == "__main__":
    sys.exit(main())
