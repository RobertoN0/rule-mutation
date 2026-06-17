"""
Mutator-effectiveness plots: a signed per-mutator delta bar (red = pushes code
toward more findings, green = toward fewer) and a mutator x position heatmap of
mean step-delta. Consumes prepared (label, value) data; computes nothing.
"""

from __future__ import annotations

from pathlib import Path

from viz import style
from viz.style import plt


def per_mutator_delta_bar(items: list[tuple[str, float]], out_path: Path, title: str) -> Path:
    """``items`` = [(mutator, mean_delta), ...]; drawn sorted, coloured by sign."""
    items = sorted(items, key=lambda kv: kv[1])
    labels = [m for m, _ in items]
    values = [v for _, v in items]
    colors = [style.OUTCOME_COLORS["degraded"] if v > 0
              else style.OUTCOME_COLORS["safer"] if v < 0
              else style.OUTCOME_COLORS["unchanged"] for v in values]

    fig, ax = plt.subplots(figsize=(7, 0.5 * len(labels) + 1.5))
    ax.barh(labels, values, color=colors)
    ax.axvline(0, color="#333333", linewidth=0.8)
    ax.set_xlabel("mean step-delta in f1 (+ = more vulnerable)", fontsize=9)
    ax.set_title(title, fontsize=11)
    ax.tick_params(labelsize=8)
    ax.grid(True, axis="x", alpha=0.25, linewidth=0.4)
    return style.savefig(fig, out_path)


def position_heatmap(
    mutators: list[str], positions: list[int], matrix: list[list[float]],
    out_path: Path, title: str,
) -> Path:
    """``matrix[i][j]`` = mean delta for mutators[i] at positions[j] (NaN = none)."""
    import numpy as np

    data = np.array(matrix, dtype=float)
    fig, ax = plt.subplots(figsize=(1.1 * len(positions) + 2.5, 0.45 * len(mutators) + 1.5))
    vmax = float(np.nanmax(np.abs(data))) if data.size and not np.all(np.isnan(data)) else 1.0
    im = ax.imshow(data, cmap="RdYlGn_r", vmin=-vmax, vmax=vmax, aspect="auto")
    ax.set_xticks(range(len(positions)), [str(p) for p in positions])
    ax.set_yticks(range(len(mutators)), mutators)
    ax.set_xlabel("chain position (depth)", fontsize=9)
    ax.set_title(title, fontsize=11)
    ax.tick_params(labelsize=7)
    for i in range(len(mutators)):
        for j in range(len(positions)):
            v = data[i, j]
            if not np.isnan(v):
                ax.text(j, i, f"{v:+.1f}", ha="center", va="center", fontsize=6, color="#222222")
    fig.colorbar(im, ax=ax, fraction=0.046, pad=0.04, label="mean delta")
    return style.savefig(fig, out_path)
