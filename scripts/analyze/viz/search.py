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


def convergence_band(runs_by_strategy: dict[str, list[L.RunData]], out_path: Path,
                     title: str) -> Path:
    """Median best-so-far f1 + IQR band across seeds, one band per strategy.

    The multi-seed RQ3 view: each strategy's convergence as a median curve with a
    p25–p75 shaded envelope, so EA and random are compared as distributions, not
    single lines. Curves are forward-filled to the longest run before aggregating.
    """
    import numpy as np

    fig, ax = plt.subplots(figsize=(8, 4.5))
    plotted = False
    for strat, runs in sorted(runs_by_strategy.items()):
        curves = [[y for _, y in L.convergence(r)] for r in runs]
        curves = [c for c in curves if c]
        if not curves:
            continue
        T = max(len(c) for c in curves)
        arr = np.array([c + [c[-1]] * (T - len(c)) for c in curves], dtype=float)
        med = np.median(arr, axis=0)
        lo = np.quantile(arr, 0.25, axis=0)
        hi = np.quantile(arr, 0.75, axis=0)
        xs = range(1, T + 1)
        ax.plot(xs, med, linewidth=1.7, label=f"{strat} (median, n={len(curves)})")
        ax.fill_between(xs, lo, hi, alpha=0.2)
        plotted = True
    if not plotted:
        plt.close(fig)
        return out_path
    ax.set_xlabel("iteration", fontsize=9)
    ax.set_ylabel("best-so-far f1", fontsize=9)
    ax.set_title(title, fontsize=11)
    ax.grid(True, alpha=0.25, linewidth=0.4)
    ax.legend(fontsize=8)
    return style.savefig(fig, out_path)


def best_f1_box(runs_by_strategy: dict[str, list[L.RunData]], out_path: Path,
                title: str) -> Path:
    """Box of per-run best_f1 per strategy, with the individual seed points overlaid.

    The canonical RQ3 figure (Arcuri & Briand): are the EA bests distributed above
    the random bests? With a single strategy it just shows that arm's spread across
    seeds — useful even before the random arm lands. Points are overlaid because n is
    small, so the raw values must stay visible.
    """
    import numpy as np

    order = [s for s in ("ea", "random_baseline") if runs_by_strategy.get(s)]
    order += [s for s in sorted(runs_by_strategy) if s not in order and runs_by_strategy.get(s)]
    data = [[L.best_f1(r) for r in runs_by_strategy[s]] for s in order]
    if not any(data):
        return out_path

    fig, ax = plt.subplots(figsize=(1.8 * len(order) + 2.0, 4.5))
    ax.boxplot(data, widths=0.5, showmeans=True)
    ax.set_xticks(range(1, len(order) + 1))
    ax.set_xticklabels([f"{s.replace('_baseline', '')}\n(n={len(d)})" for s, d in zip(order, data)])
    rng = np.random.default_rng(0)
    for i, d in enumerate(data, start=1):
        ax.scatter(rng.normal(i, 0.05, len(d)), d, s=26, color="#333333", alpha=0.8, zorder=3)
    ax.set_ylabel("best_f1 (per run)", fontsize=9)
    ax.set_title(title, fontsize=11)
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
