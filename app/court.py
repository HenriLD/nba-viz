"""Plotly half-court drawing in stats.nba.com shot coordinates.

Units are tenths of feet. Hoop center is (0, 0); baseline is y = -47.5;
the court is 500 wide (x in [-250, 250]); half-court line at y = 422.5.
"""
import numpy as np
import plotly.graph_objects as go

LINE = dict(color="#777777", width=1.5)


def _arc(cx, cy, r, theta1, theta2, n=60):
    t = np.linspace(np.radians(theta1), np.radians(theta2), n)
    return cx + r * np.cos(t), cy + r * np.sin(t)


def court_traces() -> list[go.Scatter]:
    """Return line traces for a half court. Add these to any shot figure."""
    segments: list[tuple[list[float], list[float]]] = []

    # Court boundary (baseline, sidelines, half-court line)
    segments.append(([-250, 250, 250, -250, -250],
                     [-47.5, -47.5, 422.5, 422.5, -47.5]))
    # Backboard
    segments.append(([-30, 30], [-7.5, -7.5]))
    # Paint (outer and inner boxes)
    segments.append(([-80, 80, 80, -80, -80], [-47.5, -47.5, 142.5, 142.5, -47.5]))
    segments.append(([-60, 60, 60, -60, -60], [-47.5, -47.5, 142.5, 142.5, -47.5]))
    # Hoop
    x, y = _arc(0, 0, 7.5, 0, 360)
    segments.append((list(x), list(y)))
    # Restricted area
    x, y = _arc(0, 0, 40, 0, 180)
    segments.append((list(x), list(y)))
    # Free-throw circle
    x, y = _arc(0, 142.5, 60, 0, 360)
    segments.append((list(x), list(y)))
    # Three-point line: corners + arc (r = 237.5, corner lines at x = +/-220)
    theta = np.degrees(np.arccos(220 / 237.5))
    x, y = _arc(0, 0, 237.5, theta, 180 - theta)
    segments.append(([220] + list(x[::-1]) + [-220],
                     [92.5] + list(y[::-1]) + [92.5]))
    segments.append(([220, 220], [-47.5, 92.5]))
    segments.append(([-220, -220], [-47.5, 92.5]))

    return [go.Scatter(x=xs, y=ys, mode="lines", line=LINE,
                       hoverinfo="skip", showlegend=False)
            for xs, ys in segments]


def court_layout(title: str) -> go.Layout:
    return go.Layout(
        title=title,
        xaxis=dict(range=[-260, 260], visible=False, fixedrange=True),
        yaxis=dict(range=[-60, 430], visible=False, fixedrange=True,
                   scaleanchor="x", scaleratio=1),
        plot_bgcolor="white",
        margin=dict(l=10, r=10, t=50, b=10),
        height=560,
    )
