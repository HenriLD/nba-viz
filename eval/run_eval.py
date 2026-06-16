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


def score(model: str) -> tuple[int, int, list[str]]:
    """Run the full agent on every case; return (figure_correct, total, notes)."""
    import json as _json
    import os
    os.environ["OPENROUTER_MODEL"] = model

    # Capture which tool/template each answer used, for the soft routing check.
    used: list[str] = []
    orig_dispatch = agent._dispatch

    def spy(name, args):
        used.append(args.get("template_id") if name == "render_chart" else "query_chart")
        return orig_dispatch(name, args)

    agent._dispatch = spy
    correct, notes = 0, []
    try:
        for case in CASES:
            used.clear()
            try:
                r = agent.run_agent(case["q"])
            except Exception as e:  # noqa: BLE001
                notes.append(f"  ERROR  {case['q']!r}: {e}")
                continue
            got_fig = len(r["figures"]) > 0
            if got_fig == case["expect_figure"]:
                correct += 1
            else:
                want = "a chart" if case["expect_figure"] else "a decline"
                notes.append(f"  WRONG  {case['q']!r}\n"
                             f"         expected {want}, got "
                             f"{'chart' if got_fig else 'decline'}: {r['reply'][:90]}")
            if not got_fig:
                continue
            # Soft: did a superlative land on a rate/efficiency/uplift metric?
            wm = case.get("want_metric")
            if wm:
                blob = _json.dumps(r["figures"]).lower()
                if not any(k in blob for k in wm):
                    notes.append(f"  BASIC  {case['q']!r}\n"
                                 f"         figure shows no {wm} metric "
                                 "(likely a raw-total leaderboard)")
            # Soft: did a template-route question use the expected template?
            tmpl = case.get("template")
            if tmpl and tmpl not in used:
                notes.append(f"  ROUTE  {case['q']!r}\n"
                             f"         expected template {tmpl}, used {used}")
    finally:
        agent._dispatch = orig_dispatch
    return correct, len(CASES), notes


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


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--models", nargs="+", required=True,
                        help="OpenRouter model slugs to compare")
    parser.add_argument("--runs", type=int, default=1,
                        help="repeat the whole eval N times (free models vary)")
    args = parser.parse_args()

    agent.reset_call_log()
    n_tmpl = sum(1 for c in CASES if c.get("template"))
    n_dec = sum(1 for c in CASES if not c["expect_figure"])
    print(f"{len(CASES)} questions "
          f"({len(CASES) - n_dec} answerable, {n_dec} declines, "
          f"{n_tmpl} template-routed)")

    tallies: dict = {m: [] for m in args.models}
    for run in range(1, args.runs + 1):
        for model in args.models:
            print(f"\n=== {model} — run {run}/{args.runs} ===")
            correct, total, notes = score(model)
            tallies[model].append((correct, total))
            print(f"score: {correct}/{total} ({correct / total:.0%})")
            for n in notes:
                print(n)

    if args.runs > 1:
        print("\n=== score summary (per run) ===")
        for model, runs in tallies.items():
            line = ", ".join(f"{c}/{t}" for c, t in runs)
            avg = sum(c for c, _ in runs) / sum(t for _, t in runs)
            print(f"{model}: {line}  (avg {avg:.0%})")

    _print_provider_stats(agent.call_log())
    return 0


if __name__ == "__main__":
    sys.exit(main())
