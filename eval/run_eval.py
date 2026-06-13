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


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--models", nargs="+", required=True,
                        help="OpenRouter model slugs to compare")
    parser.add_argument("--flexible", action="store_true",
                        help="run the end-to-end SQL/agent eval instead")
    args = parser.parse_args()

    scorer = score_flexible if args.flexible else score_model
    for model in args.models:
        print(f"\n=== {model} {'(flexible)' if args.flexible else ''} ===")
        correct, total, failures = scorer(model)
        print(f"score: {correct}/{total} ({correct / total:.0%})")
        for f in failures:
            print(f)
    return 0


if __name__ == "__main__":
    sys.exit(main())
