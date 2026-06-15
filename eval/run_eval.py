"""Compare candidate models on the chart agent.

Two modes:
  (default) template selection + slot filling — one model call per question,
            no DB or execution needed. Fast and cheap.
  --flexible  end-to-end: runs the full agent (writes SQL, executes it,
            renders) and checks a figure is produced — or correctly declined.
            Needs DATABASE_URL and costs more tokens.

Usage:
    python -m eval.run_eval --models moonshotai/kimi-k2 qwen/qwen-2.5-72b-instruct
    python -m eval.run_eval --flexible --models moonshotai/kimi-k2
"""
import argparse
import json
import sys
from pathlib import Path

from app.agent import propose_tool_call, run_agent

_DIR = Path(__file__).parent
QUESTIONS = json.loads((_DIR / "questions.json").read_text())
FLEXIBLE = json.loads((_DIR / "flexible_questions.json").read_text())


def _param_ok(key: str, expected, actual) -> bool:
    if actual is None:
        return False
    if key in ("player", "team"):
        return str(expected).lower() in str(actual).lower() or \
               str(actual).lower() in str(expected).lower()
    if key == "players":
        return isinstance(actual, list) and len(actual) >= 2
    return str(actual).lower() == str(expected).lower()


def score_model(model: str) -> tuple[int, int, list[str]]:
    correct, failures = 0, []
    for case in QUESTIONS:
        try:
            got = propose_tool_call(case["q"], model=model)
        except Exception as e:  # noqa: BLE001
            failures.append(f"  ERROR  {case['q']!r}: {e}")
            continue
        if not got:
            failures.append(f"  NOTOOL {case['q']!r}")
            continue
        ok = got["template_id"] == case["template_id"] and all(
            _param_ok(k, v, got["params"].get(k))
            for k, v in case["params"].items())
        if ok:
            correct += 1
        else:
            failures.append(f"  WRONG  {case['q']!r}\n"
                            f"         want {case['template_id']} {case['params']}\n"
                            f"         got  {got['template_id']} {got['params']}")
    return correct, len(QUESTIONS), failures


def score_flexible(model: str) -> tuple[int, int, list[str]]:
    """End-to-end: run the agent and check figure-present matches expectation.
    Note: uses the OPENROUTER_MODEL env var's model via run_agent (does not
    override per-model), so set OPENROUTER_MODEL to compare, or run one model."""
    import os
    os.environ["OPENROUTER_MODEL"] = model
    correct, notes = 0, []
    for case in FLEXIBLE:
        try:
            r = run_agent(case["q"])
            got_fig = len(r["figures"]) > 0
            ok = got_fig == case["expect_figure"]
            if ok:
                correct += 1
            else:
                want = "a chart" if case["expect_figure"] else "a decline"
                notes.append(f"  WRONG  {case['q']!r}\n"
                             f"         expected {want}, got "
                             f"{'chart' if got_fig else 'decline'}: {r['reply'][:90]}")
        except Exception as e:  # noqa: BLE001
            notes.append(f"  ERROR  {case['q']!r}: {e}")
    return correct, len(FLEXIBLE), notes


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
    parser.add_argument("--flexible", action="store_true",
                        help="run the end-to-end SQL/agent eval instead")
    parser.add_argument("--runs", type=int, default=1,
                        help="repeat the whole eval N times (free models vary)")
    args = parser.parse_args()

    from app import agent
    agent.reset_call_log()
    scorer = score_flexible if args.flexible else score_model
    mode = "flexible" if args.flexible else "template"
    tallies: dict = {m: [] for m in args.models}
    for run in range(1, args.runs + 1):
        for model in args.models:
            print(f"\n=== {model} ({mode}) — run {run}/{args.runs} ===")
            correct, total, failures = scorer(model)
            tallies[model].append((correct, total))
            print(f"score: {correct}/{total} ({correct / total:.0%})")
            for f in failures:
                print(f)

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
