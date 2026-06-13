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

from app.theme import PALETTE

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
