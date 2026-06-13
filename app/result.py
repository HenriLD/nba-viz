"""Shared result type for both curated templates and flexible queries."""
from dataclasses import dataclass

import plotly.graph_objects as go


@dataclass
class ChartResult:
    figure: go.Figure
    summary: str  # short text fed back to the model (never the full data table)
