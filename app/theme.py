"""Shared chart theme system.

Multiple NBA-grounded color schemes. The active theme is held in a context
variable set per request (app.theme.set_theme), so PALETTE / SERIES /
HEAT_SCALE resolve to the chosen scheme at figure-build time without threading
a palette argument through every chart builder. Default is "broadcast".

The chat UI's own colors stay fixed (index.html); only chart colors change.
"""
import contextvars

import plotly.graph_objects as go

# Data / axis / legend text — a clean, legible sans (loaded in index.html).
FONT = "'IBM Plex Sans', system-ui, -apple-system, sans-serif"
# Chart titles — a characterful display serif, matching the UI wordmark.
TITLE_FONT = "'Fraunces', Georgia, serif"

MAX_TITLE = 40  # chars; longer titles are clipped at a word boundary with …


# Each theme defines the same keys. card = figure background; ink = primary
# text; series = categorical colors; heat = shot-density colorscale.
THEMES: dict[str, dict] = {
    "broadcast": {
        "label": "Broadcast",
        "palette": {
            "card": "#161c23", "ink": "#ece7dd", "muted": "#8d97a1",
            "accent": "#e8833a", "accent2": "#45b8a4",
            "made": "#45b8a4", "missed": "#e0654f",
            "grid": "rgba(141,151,161,0.14)", "line": "rgba(236,231,221,0.55)",
        },
        "series": ["#e8833a", "#45b8a4", "#c9b458", "#9d8cd6", "#d96c8a", "#6aa9d8"],
        "heat": [[0.00, "rgba(22,28,35,0)"], [0.08, "rgba(58,42,77,0.55)"],
                 [0.30, "#71395c"], [0.55, "#c75146"], [0.80, "#f2a65a"],
                 [1.00, "#ffe9c4"]],
    },
    "hardwood": {
        "label": "Hardwood",
        "palette": {
            "card": "#efe2c8", "ink": "#2a2118", "muted": "#7a6a52",
            "accent": "#cf6a1f", "accent2": "#1d3f6e",
            "made": "#1d6b3a", "missed": "#b23b2e",
            "grid": "rgba(80,60,30,0.16)", "line": "rgba(60,45,25,0.55)",
        },
        "series": ["#cf6a1f", "#1d3f6e", "#3a7d44", "#8a5a2b", "#9c3848", "#5b7fa6"],
        "heat": [[0.00, "rgba(239,226,200,0)"], [0.10, "rgba(214,158,90,0.5)"],
                 [0.40, "#cf6a1f"], [0.70, "#b23b2e"], [1.00, "#6b2418"]],
    },
    "arena": {
        "label": "Arena (City)",
        "palette": {
            "card": "#0c0f1a", "ink": "#e8ecff", "muted": "#7d84a8",
            "accent": "#b14dff", "accent2": "#1fd6e0",
            "made": "#28e0a8", "missed": "#ff5d8f",
            "grid": "rgba(125,132,168,0.16)", "line": "rgba(232,236,255,0.5)",
        },
        "series": ["#b14dff", "#1fd6e0", "#ffd23f", "#ff5d8f", "#56e39f", "#5b8cff"],
        "heat": [[0.00, "rgba(12,15,26,0)"], [0.10, "rgba(80,40,140,0.55)"],
                 [0.40, "#7b2fd0"], [0.70, "#c0397e"], [0.90, "#f06bb0"],
                 [1.00, "#9ef0ff"]],
    },
    "press": {
        "label": "Press (Red/Blue)",
        "palette": {
            "card": "#f7f7f4", "ink": "#1a1c20", "muted": "#6b7178",
            "accent": "#c8102e", "accent2": "#1d428a",
            "made": "#1d428a", "missed": "#c8102e",
            "grid": "rgba(26,28,32,0.10)", "line": "rgba(26,28,32,0.45)",
        },
        "series": ["#c8102e", "#1d428a", "#f0a202", "#2a7d4f", "#6a4c93", "#5b8aa6"],
        "heat": [[0.00, "rgba(247,247,244,0)"], [0.15, "rgba(29,66,138,0.4)"],
                 [0.50, "#3b6fb0"], [0.80, "#c8102e"], [1.00, "#7a0c1e"]],
    },
    "flame": {
        "label": "Playoffs",
        "palette": {
            "card": "#1a1210", "ink": "#f6e9dc", "muted": "#a08a7a",
            "accent": "#ff7a18", "accent2": "#ffd23f",
            "made": "#ffb347", "missed": "#c0392b",
            "grid": "rgba(160,138,122,0.15)", "line": "rgba(246,233,220,0.5)",
        },
        "series": ["#ff7a18", "#ffd23f", "#e23b2e", "#f29e7a", "#a8d08d", "#6aa9d8"],
        "heat": [[0.00, "rgba(26,18,16,0)"], [0.10, "rgba(120,30,20,0.55)"],
                 [0.40, "#c0392b"], [0.70, "#ff7a18"], [0.90, "#ffd23f"],
                 [1.00, "#fff1c4"]],
    },
}

def _rgba(hex_str: str, alpha: float) -> str:
    h = hex_str.lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return f"rgba({r},{g},{b},{alpha})"


# Page-level UI colors per theme (the chat shell, not just charts), so the
# whole app re-skins. card/ink/muted/accent/accent2 are shared with charts above.
_UI = {
    "broadcast": {"bg": "#12161b", "panel": "#181f26", "border": "#232b34", "on_accent": "#16100a"},
    "hardwood":  {"bg": "#e4d6ba", "panel": "#f6eed9", "border": "#cdbc97", "on_accent": "#2a1606"},
    "arena":     {"bg": "#080a14", "panel": "#141829", "border": "#242b42", "on_accent": "#ffffff"},
    "press":     {"bg": "#eceae6", "panel": "#ffffff", "border": "#d8d8d2", "on_accent": "#ffffff"},
    "flame":     {"bg": "#140d0b", "panel": "#221813", "border": "#38271f", "on_accent": "#1a1006"},
}

# Derive translucent accents per theme so every chart color follows the scheme
# (and lands in the client-side recolor map, since they're palette keys).
for _id, _t in THEMES.items():
    _p = _t["palette"]
    _p.update(_UI[_id])
    _p["accent_dim"] = _rgba(_p["accent"], 0.55)   # secondary bars
    _p["paint"] = _rgba(_p["accent"], 0.06)         # court paint tint

DEFAULT_THEME = "broadcast"
_active = contextvars.ContextVar("nba_viz_theme", default=DEFAULT_THEME)


def set_theme(name: str | None) -> None:
    _active.set(name if name in THEMES else DEFAULT_THEME)


def theme_options() -> list[dict]:
    """For the UI: id, label, full palette/series/heat so the client can both
    show a swatch and recolor a displayed chart instantly on theme change."""
    return [{"id": tid, "label": t["label"], "palette": t["palette"],
             "series": t["series"], "heat": t["heat"]}
            for tid, t in THEMES.items()]


class _Palette:
    def __getitem__(self, k):
        return THEMES[_active.get()]["palette"][k]

    def get(self, k, default=None):
        return THEMES[_active.get()]["palette"].get(k, default)


class _Series:
    def _list(self):
        return THEMES[_active.get()]["series"]

    def __getitem__(self, i):
        return self._list()[i]

    def __len__(self):
        return len(self._list())

    def __iter__(self):
        return iter(self._list())


PALETTE = _Palette()
SERIES = _Series()


def __getattr__(name):
    # HEAT_SCALE resolves to the active theme's shot-density colorscale.
    if name == "HEAT_SCALE":
        return THEMES[_active.get()]["heat"]
    raise AttributeError(name)


def _clip_title(text: str) -> str:
    if len(text) <= MAX_TITLE:
        return text
    cut = text[:MAX_TITLE - 1]
    sp = cut.rfind(" ")
    if sp >= MAX_TITLE - 16:  # prefer a word boundary if it's not too far back
        cut = cut[:sp]
    return cut.rstrip(" —·-") + "…"


def style(fig: go.Figure, title: str, subtitle: str | None = None,
          height: int = 480, source: bool = True) -> go.Figure:
    """Apply the house style with the active theme. Call once per figure."""
    # Vertical bar charts get auto-rotated (diagonal) x tick labels that reach
    # down toward the source caption; give them extra bottom room so the labels
    # and the caption don't collide.
    has_vbar = any(getattr(t, "type", "") == "bar"
                   and (getattr(t, "orientation", None) or "v") == "v"
                   for t in fig.data)
    b_margin = 92 if has_vbar else 64
    fig.update_layout(
        height=height,
        autosize=True,
        paper_bgcolor=PALETTE["card"],
        plot_bgcolor=PALETTE["card"],
        font=dict(family=FONT, color=PALETTE["ink"], size=13),
        title=dict(
            text=f"<b>{_clip_title(title)}</b>",
            font=dict(size=21, family=TITLE_FONT, color=PALETTE["ink"]),
            subtitle=dict(
                text=subtitle or "",
                font=dict(size=12.5, color=PALETTE["muted"], family=FONT),
            ),
            x=0.04, xanchor="left", y=0.97, yref="container", yanchor="top",
            pad=dict(b=8),
        ),
        margin=dict(l=58, r=30, t=92 if subtitle else 60, b=b_margin),
        legend=dict(
            orientation="h", x=1, y=1.0, xanchor="right", yanchor="bottom",
            bgcolor="rgba(0,0,0,0)", font=dict(size=12, color=PALETTE["muted"]),
            itemsizing="constant",
        ),
        hoverlabel=dict(
            bgcolor=PALETTE["card"], bordercolor=PALETTE["grid"],
            font=dict(family=FONT, color=PALETTE["ink"], size=13),
        ),
        colorway=list(SERIES),
    )
    fig.update_xaxes(
        gridcolor=PALETTE["grid"], zeroline=False, linecolor="rgba(0,0,0,0)",
        tickfont=dict(color=PALETTE["muted"], size=12),
        title_font=dict(color=PALETTE["muted"], size=12),
    )
    fig.update_yaxes(
        gridcolor=PALETTE["grid"], zeroline=False, linecolor="rgba(0,0,0,0)",
        tickfont=dict(color=PALETTE["muted"], size=12),
        title_font=dict(color=PALETTE["muted"], size=12),
    )
    if source:
        # Pin the caption near the figure's bottom edge (a fixed pixel drop from
        # the plot area) so it stays below the rotated x labels regardless of
        # chart height. Anchor by its BOTTOM with a ~10px gap so descenders
        # don't get clipped off the edge — but no higher, to stay clear of the
        # top legend.
        fig.add_annotation(
            text="Court Vision · data: stats.nba.com",
            xref="paper", yref="paper", x=1, y=0,
            xanchor="right", yanchor="bottom", yshift=-(b_margin - 10),
            showarrow=False,
            font=dict(size=10, color=PALETTE["muted"], family=FONT),
        )
    return fig
