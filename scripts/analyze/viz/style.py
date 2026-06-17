"""
Shared matplotlib styling and figure helpers. The only place that configures
the backend and owns the palette, so individual plot modules never repeat
``plt.subplots`` boilerplate or hard-code colours.
"""

from __future__ import annotations

import math
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

# Outcome palette, shared with the distribution plots.
OUTCOME_COLORS = {
    "degraded": "#c73e3a",
    "unchanged": "#9aa1a8",
    "safer": "#3d8f5f",
}

# Objective palette for fitness trajectories.
OBJECTIVE_COLORS = {
    "f1": "#c73e3a",  # security delta
    "f2": "#2f6db3",  # proportion divergent
    "f3": "#8a5fb0",  # conditional mean divergence
}

GLOBAL_COLOR = "#111111"
SERIES_COLOR = "#7aa6c2"


def grid_dims(n: int, max_cols: int = 5) -> tuple[int, int]:
    """Rows, cols for an ~square small-multiples grid of ``n`` panels."""
    if n <= 0:
        return (1, 1)
    cols = min(max_cols, n)
    rows = math.ceil(n / cols)
    return rows, cols


def distinct_colors(n: int) -> list:
    """``n`` visually distinct colours for overlaying many per-rule curves.

    Draws from the qualitative tab20* maps (60 distinct colours); falls back to
    sampling a continuous map only if more are needed.
    """
    if n <= 0:
        return []
    base: list = []
    for name in ("tab20", "tab20b", "tab20c"):
        base.extend(plt.get_cmap(name).colors)
    if n <= len(base):
        return list(base[:n])
    cmap = plt.get_cmap("hsv")
    return [cmap(i / n) for i in range(n)]


def savefig(fig, path: Path, dpi: int = 120, *, tight: bool = True, bbox_inches=None) -> Path:
    """Save and close. Use ``tight=False, bbox_inches="tight"`` to keep an
    outside legend / below-axes caption in frame."""
    if bbox_inches is None and tight:
        fig.tight_layout()
    kwargs = {"dpi": dpi}
    if bbox_inches is not None:
        kwargs["bbox_inches"] = bbox_inches
    fig.savefig(path, **kwargs)
    plt.close(fig)
    return path
