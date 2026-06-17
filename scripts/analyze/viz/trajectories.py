"""
Per-rule trajectory plots: a small-multiples grid (one panel per archive/rule)
and an overlay (all rules on one axis with a bold global aggregate). Consumes
``metrics.series.Series`` objects; computes nothing itself.
"""

from __future__ import annotations

from pathlib import Path

from matplotlib.lines import Line2D

from metrics.series import Series
from viz import style
from viz.style import plt

_ADVERSARIAL = style.OUTCOME_COLORS["degraded"]  # max / more vulnerable
_DEFENSIVE = style.OUTCOME_COLORS["safer"]        # min / safer (negative f1)


def small_multiples(
    series: list[Series],
    out_path: Path,
    title: str,
    ylabel: str,
    color: str = style.SERIES_COLOR,
) -> Path:
    """One mini-panel per series (rule), sharing axes for comparison."""
    n = len(series)
    rows, cols = style.grid_dims(n)
    fig, axes = plt.subplots(
        rows, cols, figsize=(2.6 * cols, 2.1 * rows),
        sharex=True, sharey=True, squeeze=False,
    )
    flat = [ax for row in axes for ax in row]
    for ax, s in zip(flat, series):
        ax.plot(s.xs, s.ys, color=color, linewidth=1.4, marker="o", markersize=2)
        ax.set_title(s.label, fontsize=7)
        ax.tick_params(labelsize=6)
        ax.grid(True, alpha=0.25, linewidth=0.4)
    for ax in flat[n:]:
        ax.set_visible(False)
    fig.suptitle(title, fontsize=11)
    fig.supxlabel("iteration", fontsize=8)
    fig.supylabel(ylabel, fontsize=8)
    return style.savefig(fig, out_path)


def overlay(
    series: list[Series],
    out_path: Path,
    title: str,
    ylabel: str,
    global_series: Series | None = None,
    drop_flat: bool = True,
    flat_eps: float = 0.0,
) -> Path:
    """All series on one axis, one distinct colour each, plus an optional bold
    global aggregate. Flat (never-changing) rules are dropped to reduce clutter
    and listed in a caption below the axes."""
    flat = [s for s in series if s.is_flat(flat_eps)]
    plotted = [s for s in series if not s.is_flat(flat_eps)] if drop_flat else list(series)
    colors = style.distinct_colors(len(plotted))

    fig, ax = plt.subplots(figsize=(9, 4.5))
    for s, c in zip(plotted, colors):
        ax.plot(s.xs, s.ys, color=c, linewidth=1.3, alpha=0.9, label=s.label)
    if global_series is not None and len(global_series):
        ax.plot(
            global_series.xs, global_series.ys,
            color=style.GLOBAL_COLOR, linewidth=2.6, zorder=5,
            label=global_series.label or "global",
        )
    ax.set_xlabel("iteration", fontsize=9)
    ax.set_ylabel(ylabel, fontsize=9)
    ax.set_title(title, fontsize=11)
    ax.grid(True, alpha=0.25, linewidth=0.4)
    if plotted or (global_series is not None and len(global_series)):
        ax.legend(loc="center left", bbox_to_anchor=(1.01, 0.5), fontsize=6, ncol=1, frameon=False)

    if drop_flat and flat:
        fig.subplots_adjust(bottom=0.22)
        names = ", ".join(s.label for s in flat)
        fig.text(
            0.01, 0.04,
            f"Flat (no change over the run, {len(flat)} omitted): {names}",
            fontsize=6, color="#555555", wrap=True,
        )
    return style.savefig(fig, out_path, tight=False, bbox_inches="tight")


def envelope_grid(
    best: list[Series], worst: list[Series], out_path: Path, title: str, ylabel: str,
) -> Path:
    """Per-rule panels showing BOTH search extremes: max f1 (adversarial, red)
    and min f1 (safer / negative, green), shaded between, with a zero line."""
    bmap = {s.key: s for s in best}
    wmap = {s.key: s for s in worst}
    keys = sorted(set(bmap) | set(wmap))
    rows, cols = style.grid_dims(len(keys))
    fig, axes = plt.subplots(
        rows, cols, figsize=(2.6 * cols, 2.1 * rows),
        sharex=True, sharey=True, squeeze=False,
    )
    flat = [ax for row in axes for ax in row]
    for ax, key in zip(flat, keys):
        b, w = bmap.get(key), wmap.get(key)
        if b and w and b.xs == w.xs:
            ax.fill_between(b.xs, w.ys, b.ys, color="#d9d9d9", alpha=0.6)
        if w:
            ax.plot(w.xs, w.ys, color=_DEFENSIVE, linewidth=1.2, marker="o", markersize=2)
        if b:
            ax.plot(b.xs, b.ys, color=_ADVERSARIAL, linewidth=1.2, marker="o", markersize=2)
        ax.axhline(0, color="#333333", linewidth=0.6)
        ax.set_title((b or w).label, fontsize=7)
        ax.tick_params(labelsize=6)
        ax.grid(True, alpha=0.25, linewidth=0.4)
    for ax in flat[len(keys):]:
        ax.set_visible(False)
    fig.suptitle(title, fontsize=11)
    fig.supxlabel("iteration", fontsize=8)
    fig.supylabel(ylabel, fontsize=8)
    return style.savefig(fig, out_path)


def envelope_overlay(
    best: list[Series], worst: list[Series], out_path: Path, title: str, ylabel: str,
    drop_flat: bool = True,
) -> Path:
    """All rules' adversarial (max, red) and safer (min, green) trajectories on
    one axis, around a zero line — the full up/down spread the search explored."""
    fig, ax = plt.subplots(figsize=(9, 4.5))
    for s in worst:
        if not (drop_flat and s.is_flat()):
            ax.plot(s.xs, s.ys, color=_DEFENSIVE, linewidth=0.9, alpha=0.7)
    for s in best:
        if not (drop_flat and s.is_flat()):
            ax.plot(s.xs, s.ys, color=_ADVERSARIAL, linewidth=0.9, alpha=0.7)
    ax.axhline(0, color="#333333", linewidth=0.8)
    ax.set_xlabel("iteration", fontsize=9)
    ax.set_ylabel(ylabel, fontsize=9)
    ax.set_title(title, fontsize=11)
    ax.grid(True, alpha=0.25, linewidth=0.4)
    ax.legend(handles=[
        Line2D([0], [0], color=_ADVERSARIAL, label="max f1 per rule (more vulnerable)"),
        Line2D([0], [0], color=_DEFENSIVE, label="min f1 per rule (safer / negative)"),
    ], loc="best", fontsize=7, frameon=False)
    return style.savefig(fig, out_path)
