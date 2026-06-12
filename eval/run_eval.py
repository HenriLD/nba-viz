"""Compare candidate models on template selection + slot filling.

No database needed — this only checks the tool call the model proposes,
not chart execution. Player-name params are compared by loose substring
(the server fuzzy-matches at runtime anyway).

Usage:
    python -m eval.run_eval --models moonshotai/kimi-k2 qwen/qwen-2.5-72b-instruct
"""
import argparse
import json
import sys
from pathlib import Path

from app.agent import propose_tool_call

QUESTIONS = json.loads((Path(__file__).parent / "questions.json").read_text())


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


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--models", nargs="+", required=True,
                        help="OpenRouter model slugs to compare")
    args = parser.parse_args()

    for model in args.models:
        print(f"\n=== {model} ===")
        correct, total, failures = score_model(model)
        print(f"score: {correct}/{total} ({correct / total:.0%})")
        for f in failures:
            print(f)
    return 0


if __name__ == "__main__":
    sys.exit(main())
