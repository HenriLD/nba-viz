"""Plotly half-court in stats.nba.com shot coordinates, broadcast styling.

Units are tenths of feet. Hoop center is (0, 0). Key reference points:
  baseline          y = -47.5
  half-court line   y =  422.5
  sidelines         x = +/-250
  corner-3 lines    x = +/-220 (22 ft), meeting the arc at y = sqrt(237.5^2-220^2)
  3pt arc           r = 237.5 (23.75 ft), centered on the hoop
"""
import math

import numpy as np
import plotly.graph_objects as go

from app import theme
from app.theme import PALETTE, SERIES

LINE_W = 2.0
# Exact y where the corner-three line meets the arc (~89.5, NOT 92.5 — using
# a rounded value leaves a visible kink where the segments meet).
CORNER_Y = math.sqrt(237.5**2 - 220.0**2)
CORNER_DEG = math.degrees(math.acos(220.0 / 237.5))


def _arc(cx, cy, r, deg1, deg2, n=80):
    t = np.linspace(np.radians(deg1), np.radians(deg2), n)
    return (cx + r * np.cos(t)).tolist(), (cy + r * np.sin(t)).tolist()


def _line(xs, ys, color=None, width=LINE_W, dash=None):
    return go.Scatter(
        x=xs, y=ys, mode="lines",
        line=dict(color=color or PALETTE["line"], width=width, dash=dash),
        hoverinfo="skip", showlegend=False)


def court_traces() -> list[go.Scatter]:
    """Court line traces. Add AFTER data traces you want underneath the heat,
    or BEFORE scatter points you want on top of the lines."""
    t: list[go.Scatter] = []

    # Painted area fill (subtle warm tint under everything else)
    t.append(go.Scatter(
        x=[-80, 80, 80, -80, -80], y=[-47.5, -47.5, 142.5, 142.5, -47.5],
        mode="lines", fill="toself", fillcolor=PALETTE["paint"],
        line=dict(width=0), hoverinfo="skip", showlegend=False))

    # Boundary: baseline, sidelines, half-court line
    t.append(_line([-250, 250, 250, -250, -250],
                   [-47.5, -47.5, 422.5, 422.5, -47.5]))

    # Lane: outer box, inner box
    t.append(_line([-80, 80, 80, -80, -80], [-47.5, -47.5, 142.5, 142.5, -47.5]))
    t.append(_line([-60, 60, 60, -60, -60], [-47.5, -47.5, 142.5, 142.5, -47.5]))

    # Free-throw circle: solid top half, dashed bottom half (rulebook style)
    x, y = _arc(0, 142.5, 60, 0, 180)
    t.append(_line(x, y))
    x, y = _arc(0, 142.5, 60, 180, 360)
    t.append(_line(x, y, dash="4px,5px"))

    # Restricted area
    x, y = _arc(0, 0, 40, 0, 180)
    t.append(_line(x, y))

    # Three-point line: one continuous path so corner and arc join exactly
    ax, ay = _arc(0, 0, 237.5, CORNER_DEG, 180 - CORNER_DEG)
    t.append(_line([220, 220] + ax[::-1] + [-220, -220],
                   [-47.5, CORNER_Y] + ay[::-1] + [CORNER_Y, -47.5]))

    # Center circle (bottom half pokes into our half court)
    x, y = _arc(0, 422.5, 60, 180, 360)
    t.append(_line(x, y))

    # Backboard and rim — rim in accent so the eye anchors to the basket
    t.append(_line([-30, 30], [-7.5, -7.5], width=2.6))
    x, y = _arc(0, 0, 7.5, 0, 360, n=40)
    t.append(_line(x, y, color=PALETTE["accent"], width=2.2))

    return t


# Court data aspect (plot-area height / width) = y-range / x-range = 495 / 520.
# The frontend reads layout.meta.square to size a court card to this aspect so
# the square court fills its width instead of letterboxing in a fixed-height box.
COURT_ASPECT = 495 / 520


def court_layout(height: int = 620) -> dict:
    """Axis/scale settings for a court figure. Pair with theme.style()."""
    return dict(
        height=height,
        meta=dict(square=COURT_ASPECT),
        xaxis=dict(range=[-260, 260], visible=False, fixedrange=True),
        yaxis=dict(range=[-60, 435], visible=False, fixedrange=True,
                   scaleanchor="x", scaleratio=1),
    )


# ----- shared shot-visualization builders (used by both the templates and the
# flexible SQL path, so a model-driven shot chart looks identical to the
# templated one). Callers add their own title/subtitle via theme.style().

def shot_chart_figure(made_x, made_y, missed_x, missed_y,
                      made_text=None, missed_text=None) -> go.Figure:
    """Half-court scatter: makes filled, misses as faint x's."""
    fig = go.Figure(court_traces())
    fig.add_trace(go.Scatter(
        x=missed_x, y=missed_y, mode="markers", name="Missed",
        marker=dict(color=PALETTE["missed"], size=5, symbol="x-thin",
                    line=dict(width=1.2, color=PALETTE["missed"]), opacity=0.45),
        text=missed_text,
        hovertemplate=("%{text}<extra>missed</extra>" if missed_text is not None
                       else "<extra>missed</extra>")))
    fig.add_trace(go.Scatter(
        x=made_x, y=made_y, mode="markers", name="Made",
        marker=dict(color=PALETTE["made"], size=5.5, opacity=0.75, line=dict(width=0)),
        text=made_text,
        hovertemplate=("%{text}<extra>made</extra>" if made_text is not None
                       else "<extra>made</extra>")))
    fig.update_layout(**court_layout())
    return fig


def shot_chart_by_category(df, x, y, cat) -> go.Figure:
    """Half-court scatter colored by a category column (quarter, zone, opponent…),
    one trace + legend entry per distinct value — for comparing where shots come
    from across that dimension."""
    fig = go.Figure(court_traces())
    for i, (key, grp) in enumerate(df.groupby(cat, sort=True)):
        fig.add_trace(go.Scatter(
            x=grp[x], y=grp[y], mode="markers", name=str(key),
            marker=dict(color=SERIES[i % len(SERIES)], size=5.5, opacity=0.7,
                        line=dict(width=0)),
            hovertemplate=str(key) + "<extra></extra>"))
    fig.update_layout(**court_layout())
    return fig


def shot_heatmap_figure(x, y) -> go.Figure:
    """Half-court shot-density contour (brighter = more volume)."""
    fig = go.Figure()
    fig.add_trace(go.Histogram2dContour(
        x=x, y=y, colorscale=theme.HEAT_SCALE, ncontours=16, showscale=False,
        line=dict(width=0), contours=dict(coloring="heatmap"), hoverinfo="skip"))
    for tr in court_traces():
        fig.add_trace(tr)
    fig.update_layout(**court_layout())
    return fig
