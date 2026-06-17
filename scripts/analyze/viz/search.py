"""
Search-behaviour plots: a restart-reason bar and a best-so-far f1 convergence
curve (optionally several runs overlaid). Consumes prepared data.
"""

from __future__ import annotations

from pathlib import Path

import loaders as L
from viz import style
from viz.style import plt


def restart_reason_bar(rows: list[list], out_path: Path, title: str) -> Path:
    labels = [r[0] for r in rows]
    counts = [r[1] for r in rows]
    fig, ax = plt.subplots(figsize=(6, 3.5))
    ax.bar(labels, counts, color=style.SERIES_COLOR)
    ax.set_ylabel("restart events", fontsize=9)
    ax.set_title(title, fontsize=11)
    ax.tick_params(axis="x", labelsize=8, rotation=20)
    ax.grid(True, axis="y", alpha=0.25, linewidth=0.4)
    return style.savefig(fig, out_path)


def convergence_overlay(runs: list[L.RunData], out_path: Path, title: str) -> Path:
    """Best-so-far f1 vs iteration, one line per run (labelled strategy/seed)."""
    colors = style.distinct_colors(len(runs))
    fig, ax = plt.subplots(figsize=(8, 4.5))
    for run, color in zip(runs, colors):
        curve = L.convergence(run)
        if not curve:
            continue
        xs = [x for x, _ in curve]
        ys = [y for _, y in curve]
        ax.plot(xs, ys, color=color, linewidth=1.4, label=f"{run.strategy}/s{run.seed}")
    ax.set_xlabel("iteration", fontsize=9)
    ax.set_ylabel("best-so-far f1", fontsize=9)
    ax.set_title(title, fontsize=11)
    ax.grid(True, alpha=0.25, linewidth=0.4)
    ax.legend(loc="center left", bbox_to_anchor=(1.01, 0.5), fontsize=7, frameon=False)
    return style.savefig(fig, out_path, tight=False, bbox_inches="tight")
