"""
Security-effect plots: a diverging check-flip bar (added findings to the right,
removed to the left) and a per-CWE degraded/safer stacked bar. Consumes prepared
rows; computes nothing.
"""

from __future__ import annotations

from pathlib import Path

from viz import style
from viz.style import plt


def check_flip_bar(rows: list[list], out_path: Path, title: str, top_n: int = 15) -> Path:
    """rows = metrics.security check_flip_rows; diverging added(+) / removed(-)."""
    rows = rows[:top_n]
    labels = [r[0] for r in rows][::-1]
    added = [r[2] for r in rows][::-1]
    removed = [-r[3] for r in rows][::-1]

    fig, ax = plt.subplots(figsize=(8, 0.42 * len(labels) + 1.5))
    ax.barh(labels, added, color=style.OUTCOME_COLORS["degraded"], label="added (new finding)")
    ax.barh(labels, removed, color=style.OUTCOME_COLORS["safer"], label="removed")
    ax.axvline(0, color="#333333", linewidth=0.8)
    ax.set_xlabel("prompts (added right / removed left)", fontsize=9)
    ax.set_title(title, fontsize=11)
    ax.tick_params(labelsize=7)
    ax.legend(fontsize=7, loc="lower right")
    ax.grid(True, axis="x", alpha=0.25, linewidth=0.4)
    return style.savefig(fig, out_path)


def cwe_outcome_bar(rows: list[list], out_path: Path, title: str, top_n: int = 15) -> Path:
    """rows = metrics.security cwe_rows; stacked degraded/unchanged/safer per CWE."""
    rows = [r for r in rows if r[1] > 0][:top_n]
    labels = [r[0] for r in rows]
    degraded = [r[2] for r in rows]
    safer = [r[3] for r in rows]
    unchanged = [r[4] for r in rows]

    fig, ax = plt.subplots(figsize=(8, 0.42 * len(labels) + 1.5))
    ax.barh(labels, degraded, color=style.OUTCOME_COLORS["degraded"], label="degraded")
    ax.barh(labels, unchanged, left=degraded, color=style.OUTCOME_COLORS["unchanged"], label="unchanged")
    left2 = [degraded[i] + unchanged[i] for i in range(len(labels))]
    ax.barh(labels, safer, left=left2, color=style.OUTCOME_COLORS["safer"], label="safer")
    ax.set_xlabel("prompts", fontsize=9)
    ax.set_title(title, fontsize=11)
    ax.tick_params(labelsize=7)
    ax.legend(fontsize=7, loc="lower right")
    return style.savefig(fig, out_path)
