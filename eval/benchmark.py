"""Multi-model benchmark for the chart agent.

Measures, per model:
  - template selection accuracy   (one forced render_chart call per question)
  - flexible end-to-end accuracy  (full agent: writes SQL, executes, renders)
  - latency (avg + p50) for each path
  - prompt/completion tokens for the template path

Writes eval/results/benchmark.{json,md} and prints a compact table.

Usage:
    python -m eval.benchmark --models a b c
    python -m eval.benchmark --models a b c --skip-availability
    python -m eval.benchmark --check-only --models a b c   # availability only
"""
import argparse
import json
import os
import statistics as stats
import time
from pathlib import Path

import requests
from openai import OpenAI

from app.agent import (QUERY_CHART_TOOL, RENDER_CHART_TOOL, run_agent,
                       system_prompt)
from eval.run_eval import _param_ok

_DIR = Path(__file__).parent
_RESULTS = _DIR / "results"

TEMPLATE_Q = (json.loads((_DIR / "questions.json").read_text())
              + json.loads((_DIR / "hard_questions.json").read_text()))
FLEX_Q = (json.loads((_DIR / "flexible_questions.json").read_text())
          + json.loads((_DIR / "hard_flexible.json").read_text()))


def _client() -> OpenAI:
    return OpenAI(base_url="https://openrouter.ai/api/v1",
                  api_key=os.environ["OPENROUTER_API_KEY"])


def check_availability(models: list[str]) -> dict[str, bool]:
    try:
        data = requests.get("https://openrouter.ai/api/v1/models",
                            headers={"Authorization": f"Bearer {os.environ['OPENROUTER_API_KEY']}"},
                            timeout=30).json()
        ids = {m["id"] for m in data.get("data", [])}
        return {m: (m in ids) for m in models}
    except Exception as e:  # noqa: BLE001
        print(f"availability check failed ({e}); will attempt all models")
        return {m: True for m in models}


def _timed_template(model: str, question: str):
    """One forced render_chart call. Returns (parsed_or_None, latency, tokens, err)."""
    t = time.monotonic()
    try:
        # auto tool_choice (not forced function) — forced choice is rejected by
        # several providers. Offering only render_chart still measures template
        # selection: the model calls it when a template fits.
        resp = _client().chat.completions.create(
            model=model,
            messages=[{"role": "system", "content": system_prompt()},
                      {"role": "user", "content": question}],
            tools=[RENDER_CHART_TOOL], tool_choice="auto",
            temperature=0.0, max_tokens=600)
        dt = time.monotonic() - t
        tcs = resp.choices[0].message.tool_calls
        toks = resp.usage.total_tokens if resp.usage else 0
        if not tcs:
            return None, dt, toks, "no_tool_call"
        args = json.loads(tcs[0].function.arguments)
        return args, dt, toks, None
    except Exception as e:  # noqa: BLE001
        return None, time.monotonic() - t, 0, type(e).__name__


def bench_template(model: str) -> dict:
    times, toks, correct, errors = [], [], 0, 0
    for case in TEMPLATE_Q:
        got, dt, tk, err = _timed_template(model, case["q"])
        times.append(dt)
        toks.append(tk)
        if err:
            errors += 1
            continue
        ok = got.get("template_id") == case["template_id"] and all(
            _param_ok(k, v, (got.get("params") or {}).get(k))
            for k, v in case["params"].items())
        correct += ok
    n = len(TEMPLATE_Q)
    return dict(n=n, correct=correct, acc=correct / n, errors=errors,
                avg_latency=stats.mean(times), p50_latency=stats.median(times),
                avg_tokens=stats.mean(toks))


def bench_flexible(model: str) -> dict:
    os.environ["OPENROUTER_MODEL"] = model
    times, correct, errors = [], 0, 0
    for case in FLEX_Q:
        t = time.monotonic()
        try:
            r = run_agent(case["q"])
            times.append(time.monotonic() - t)
            if (r["figure"] is not None) == case["expect_figure"]:
                correct += 1
        except Exception:  # noqa: BLE001
            times.append(time.monotonic() - t)
            errors += 1
    n = len(FLEX_Q)
    return dict(n=n, correct=correct, acc=correct / n, errors=errors,
                avg_latency=stats.mean(times), p50_latency=stats.median(times))


def run(models: list[str], check: bool = True) -> dict:
    avail = check_availability(models) if check else {m: True for m in models}
    # Merge into existing results so single-model runs don't clobber prior data.
    path = _RESULTS / "benchmark.json"
    results = json.loads(path.read_text()) if path.exists() else {}
    for model in models:
        if not avail.get(model, True):
            print(f"[skip] {model} — not on OpenRouter")
            results[model] = {"available": False}
            continue
        print(f"[run ] {model} …", flush=True)
        try:
            t = bench_template(model)
            f = bench_flexible(model)
            results[model] = {"available": True, "template": t, "flexible": f}
            print(f"       template {t['acc']:.0%} ({t['avg_latency']:.1f}s) | "
                  f"flexible {f['acc']:.0%} ({f['avg_latency']:.1f}s) | "
                  f"errors t{t['errors']}/f{f['errors']}", flush=True)
        except Exception as e:  # noqa: BLE001
            print(f"       FAILED: {type(e).__name__}: {e}", flush=True)
            results[model] = {"available": True, "error": f"{type(e).__name__}: {e}"}
    return results


def write_reports(results: dict) -> None:
    _RESULTS.mkdir(exist_ok=True)
    (_RESULTS / "benchmark.json").write_text(json.dumps(results, indent=2))

    rows = []
    for model, r in results.items():
        if not r.get("available"):
            rows.append((model, "—", "—", "—", "—", "unavailable"))
        elif "error" in r:
            rows.append((model, "—", "—", "—", "—", r["error"][:30]))
        else:
            t, f = r["template"], r["flexible"]
            rows.append((
                model, f"{t['acc']:.0%}", f"{f['acc']:.0%}",
                f"{t['avg_latency']:.1f}s", f"{f['avg_latency']:.1f}s",
                f"{int(t['avg_tokens'])} tok"))
    # sort: available first, then by template acc desc then flexible acc desc
    def sort_key(row):
        m = results[row[0]]
        if not m.get("available") or "error" in m:
            return (1, 0, 0)
        return (0, -m["template"]["acc"], -m["flexible"]["acc"])
    rows.sort(key=sort_key)

    hdr = "| Model | Template | Flexible | T-lat | F-lat | T-tokens |"
    sep = "|---|---|---|---|---|---|"
    lines = [hdr, sep] + [f"| {a} | {b} | {c} | {d} | {e} | {g} |"
                          for a, b, c, d, e, g in rows]
    md = ("# Model benchmark\n\n"
          f"Template questions: {len(TEMPLATE_Q)} · Flexible questions: {len(FLEX_Q)}\n\n"
          + "\n".join(lines) + "\n")
    (_RESULTS / "benchmark.md").write_text(md)
    print("\n" + md)


def run_template_only(models: list[str]) -> dict:
    """Re-measure only the template path, merging into existing results so the
    (still-valid) flexible numbers are preserved."""
    path = _RESULTS / "benchmark.json"
    results = json.loads(path.read_text()) if path.exists() else {}
    for model in models:
        print(f"[tmpl] {model} …", flush=True)
        try:
            t = bench_template(model)
            entry = results.get(model) or {"available": True}
            entry["available"] = True
            entry["template"] = t
            entry.pop("error", None)
            results[model] = entry
            print(f"       template {t['acc']:.0%} ({t['avg_latency']:.1f}s) "
                  f"errors {t['errors']}", flush=True)
        except Exception as e:  # noqa: BLE001
            print(f"       FAILED: {type(e).__name__}: {e}", flush=True)
    return results


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--models", nargs="+", required=True)
    ap.add_argument("--skip-availability", action="store_true")
    ap.add_argument("--check-only", action="store_true")
    ap.add_argument("--template-only", action="store_true",
                    help="re-run only the template path; merge with existing results")
    args = ap.parse_args()

    if args.check_only:
        avail = check_availability(args.models)
        for m, ok in avail.items():
            print(f"{'OK  ' if ok else 'MISS'}  {m}")
        return 0

    if args.template_only:
        results = run_template_only(args.models)
    else:
        results = run(args.models, check=not args.skip_availability)
    write_reports(results)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
