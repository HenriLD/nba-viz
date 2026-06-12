"""NL -> chart agent. One tool, strict schema, OpenRouter-compatible.

The model's entire job is to pick a template_id and fill params. Entity names
are resolved server-side, stats and seasons are validated, and errors are fed
back so the model can self-correct once or twice.
"""
import json
import logging
import os

from dotenv import load_dotenv
from openai import OpenAI

from app.templates import CATALOG, catalog_prompt, run_template
from core.seasons import current_season
from core.stats import ALL_STATS

load_dotenv()
log = logging.getLogger("agent")

MAX_TURNS = 4  # model calls per user message (1 normal + retries)


def _client() -> OpenAI:
    return OpenAI(base_url="https://openrouter.ai/api/v1",
                  api_key=os.environ["OPENROUTER_API_KEY"])


def _model() -> str:
    return os.environ.get("OPENROUTER_MODEL", "moonshotai/kimi-k2")


RENDER_CHART_TOOL = {
    "type": "function",
    "function": {
        "name": "render_chart",
        "description": "Render one chart from the template catalog.",
        "parameters": {
            "type": "object",
            "properties": {
                "template_id": {
                    "type": "string",
                    "enum": list(CATALOG.keys()),
                },
                "params": {
                    "type": "object",
                    "properties": {
                        "player": {"type": "string",
                                   "description": "Player name, as the user said it"},
                        "players": {"type": "array", "items": {"type": "string"},
                                    "description": "2+ player names for comparisons"},
                        "team": {"type": "string", "description": "Team name"},
                        "season": {"type": "string",
                                   "description": "e.g. '2024-25'. Omit for current season."},
                        "stat": {"type": "string", "enum": ALL_STATS},
                        "top_n": {"type": "integer", "minimum": 3, "maximum": 30},
                        "rolling_window": {"type": "integer", "minimum": 2, "maximum": 20},
                        "conference": {"type": "string", "enum": ["East", "West"]},
                    },
                    "additionalProperties": False,
                },
            },
            "required": ["template_id", "params"],
        },
    },
}


def system_prompt() -> str:
    return f"""You are an NBA data visualization assistant. You answer questions by \
rendering charts with the render_chart tool, then giving a one-or-two-sentence takeaway.

Current NBA season: {current_season()}. The database covers roughly the last 5 seasons \
(regular season + playoffs for game logs and shots; defender-distance data is regular \
season only). There is NO raw player-movement/positional data — for anything about \
defenders, use defender_distance_efficiency.

Chart templates:
{catalog_prompt()}

Rules:
- Pass player/team names exactly as the user said them; the server fuzzy-matches.
- If the user doesn't specify a season, omit it (defaults to the current season).
- Stats must be one of: {", ".join(ALL_STATS)}.
- If a tool call returns an error, fix the params and try once more, or explain \
the limitation plainly.
- If the question can't be answered by any template, say so and list 2-3 things \
you can show instead. Do not invent data.
- After a successful chart, reply with a brief insight based on the tool result \
summary — the user already sees the chart, don't describe it visually."""


def run_agent(message: str, history: list[dict] | None = None) -> dict:
    """Returns {"reply": str, "figure": dict | None}."""
    client = _client()
    messages = [{"role": "system", "content": system_prompt()}]
    for h in (history or [])[-10:]:  # text-only history, capped
        if h.get("role") in ("user", "assistant") and h.get("content"):
            messages.append({"role": h["role"], "content": str(h["content"])})
    messages.append({"role": "user", "content": message})

    figure = None
    for _ in range(MAX_TURNS):
        resp = client.chat.completions.create(
            model=_model(), messages=messages,
            tools=[RENDER_CHART_TOOL], temperature=0.1, max_tokens=700)
        choice = resp.choices[0].message

        if not choice.tool_calls:
            return {"reply": choice.content or "", "figure": figure}

        messages.append({"role": "assistant", "content": choice.content,
                         "tool_calls": [tc.model_dump() for tc in choice.tool_calls]})
        for tc in choice.tool_calls:
            try:
                args = json.loads(tc.function.arguments)
                result = run_template(args["template_id"], args.get("params") or {})
                figure = json.loads(result.figure.to_json())
                feedback = f"Chart rendered. Data summary: {result.summary}"
            except Exception as e:  # noqa: BLE001 — error text goes back to the model
                log.warning("tool error: %s", e)
                feedback = f"ERROR: {e}"
            messages.append({"role": "tool", "tool_call_id": tc.id,
                             "content": feedback})

    return {"reply": "Sorry, I couldn't build that chart after a few attempts.",
            "figure": figure}


def propose_tool_call(message: str, model: str | None = None) -> dict | None:
    """Single model call, no execution — used by the eval harness."""
    client = _client()
    resp = client.chat.completions.create(
        model=model or _model(),
        messages=[{"role": "system", "content": system_prompt()},
                  {"role": "user", "content": message}],
        tools=[RENDER_CHART_TOOL],
        tool_choice={"type": "function", "function": {"name": "render_chart"}},
        temperature=0.0, max_tokens=400)
    tcs = resp.choices[0].message.tool_calls
    if not tcs:
        return None
    args = json.loads(tcs[0].function.arguments)
    return {"template_id": args.get("template_id"), "params": args.get("params") or {}}
