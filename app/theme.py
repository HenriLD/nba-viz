"""Shared broadcast-style chart theme.

One dark palette used by every figure AND the chat UI (index.html mirrors
these hex values), so charts look native to the page and screenshot well.
"""
import plotly.graph_objects as go

PALETTE = {
    "bg":      "#12161b",   # page background
    "card":    "#161c23",   # chart card / figure background
    "ink":     "#ece7dd",   # primary text (warm cream)
    "muted":   "#8d97a1",   # secondary text
    "accent":  "#e8833a",   # terracotta — primary series / West
    "accent2": "#45b8a4",   # teal — secondary series / East
    "made":    "#45b8a4",
    "missed":  "#e0654f",
    "grid":    "rgba(141,151,161,0.14)",
    "line":    "rgba(236,231,221,0.55)",  # court lines
}

# Categorical series order for multi-line/bar charts.
SERIES = ["#e8833a", "#45b8a4", "#c9b458", "#9d8cd6", "#d96c8a", "#6aa9d8"]

# Data / axis / legend text — a clean, legible sans (loaded in index.html).
FONT = "'IBM Plex Sans', system-ui, -apple-system, sans-serif"
# Chart titles — a characterful display serif, matching the UI wordmark.
TITLE_FONT = "'Fraunces', Georgia, serif"

# Sequential scale for shot-density heatmaps: transparent floor so the court
# shows through where nothing happened, warming up to cream at the peak.
HEAT_SCALE = [
    [0.00, "rgba(22,28,35,0)"],
    [0.08, "rgba(58,42,77,0.55)"],
    [0.30, "#71395c"],
    [0.55, "#c75146"],
    [0.80, "#f2a65a"],
    [1.00, "#ffe9c4"],
]


def style(fig: go.Figure, title: str, subtitle: str | None = None,
          height: int = 480, source: bool = True) -> go.Figure:
    """Apply the house style. Call once per figure, after traces are added."""
    fig.update_layout(
        height=height,
        autosize=True,
        paper_bgcolor=PALETTE["card"],
        plot_bgcolor=PALETTE["card"],
        font=dict(family=FONT, color=PALETTE["ink"], size=13),
        title=dict(
            text=f"<b>{title}</b>",
            font=dict(size=21, family=TITLE_FONT, color=PALETTE["ink"]),
            subtitle=dict(
                text=subtitle or "",
                font=dict(size=12.5, color=PALETTE["muted"], family=FONT),
            ),
            x=0.04, xanchor="left", yanchor="top", pad=dict(b=12),
        ),
        # Roomy top band so the title/subtitle (left) and legend (right) never
        # crowd each other or the plot.
        margin=dict(l=58, r=30, t=112 if subtitle else 78, b=64),
        legend=dict(
            orientation="h", x=1, y=1.0, xanchor="right", yanchor="bottom",
            bgcolor="rgba(0,0,0,0)", font=dict(size=12, color=PALETTE["muted"]),
            itemsizing="constant",
        ),
        hoverlabel=dict(
            bgcolor="#1f2630", bordercolor="rgba(141,151,161,0.3)",
            font=dict(family=FONT, color=PALETTE["ink"], size=13),
        ),
        colorway=SERIES,
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
        fig.add_annotation(
            text="nba-viz · data: stats.nba.com",
            xref="paper", yref="paper", x=1, y=-0.125,
            xanchor="right", yanchor="top", showarrow=False,
            font=dict(size=10, color="rgba(141,151,161,0.6)", family=FONT),
        )
    return fig
