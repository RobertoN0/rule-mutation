"""
Vulnerability-repair plots (minimize direction): the supervisor's per-data-point
before/after views (a per-task difference waterfall and a before-vs-after scatter)
plus an EA-vs-random aggregate-repair box. Consumes prepared TaskRow lists / dicts.
"""

from __future__ import annotations

from pathlib import Path

from viz import style
from viz.style import plt

_REPAIRED = style.OUTCOME_COLORS["safer"]      # green: driven to zero findings
_PARTIAL = "#86c79b"                            # light green: reduced, not to zero
_FLAT = style.OUTCOME_COLORS["unchanged"]       # grey: no reduction found
_WORSE = style.OUTCOME_COLORS["degraded"]       # red: envelope never reaches baseline (n/a here)


def per_task_diff_waterfall(rows, out_path: Path, title: str) -> Path:
    """Sorted per-task finding reduction (before - after) over movable tasks.

    Each bar is one coding task; height = weighted findings removed by the best
    repair found. Green = driven to zero, light green = partial, grey = no repair.
    """
    movable = [r for r in rows if r.before_raw > 0]
    movable.sort(key=lambda r: r.delta_score, reverse=True)
    deltas = [r.delta_score for r in movable]
    colors = [
        _REPAIRED if r.repaired else (_PARTIAL if r.delta_raw > 0 else _FLAT)
        for r in movable
    ]
    fig, ax = plt.subplots(figsize=(7, 3.0))
    ax.bar(range(len(deltas)), deltas, color=colors, width=1.0)
    ax.axhline(0, color=style.GLOBAL_COLOR, linewidth=0.6)
    ax.set_xlabel(f"coding task (n={len(movable)} with baseline findings, sorted)", fontsize=14)
    ax.set_ylabel("weighted findings\nremoved (before - after)", fontsize=14)
    ax.set_title(title, fontsize=15)
    ax.tick_params(axis="both", labelsize=12)
    n_rep = sum(1 for r in movable if r.repaired)
    n_par = sum(1 for r in movable if r.delta_raw > 0 and not r.repaired)
    handles = [
        plt.Rectangle((0, 0), 1, 1, color=_REPAIRED, label=f"to zero ({n_rep})"),
        plt.Rectangle((0, 0), 1, 1, color=_PARTIAL, label=f"reduced ({n_par})"),
        plt.Rectangle((0, 0), 1, 1, color=_FLAT, label=f"no repair ({len(movable) - n_rep - n_par})"),
    ]
    ax.legend(handles=handles, fontsize=13, loc="upper right", framealpha=0.9)
    ax.grid(True, axis="y", alpha=0.25, linewidth=0.4)
    return style.savefig(fig, out_path)


def before_after_scatter(rows, out_path: Path, title: str) -> Path:
    """Per-task baseline vs safest-observed weighted findings; below the diagonal = safer."""
    movable = [r for r in rows if r.before_raw > 0]
    bx = [r.before_score for r in movable]
    ay = [r.after_score for r in movable]
    colors = [
        _REPAIRED if r.repaired else (_PARTIAL if r.delta_raw > 0 else _FLAT)
        for r in movable
    ]
    fig, ax = plt.subplots(figsize=(5, 5))
    lim = max([1.0] + bx + ay) * 1.05
    ax.plot([0, lim], [0, lim], color=_FLAT, linewidth=0.8, linestyle="--", zorder=1)
    ax.scatter(bx, ay, c=colors, s=22, alpha=0.8, edgecolors="none", zorder=2)
    ax.set_xlim(0, lim)
    ax.set_ylim(0, lim)
    ax.set_xlabel("baseline weighted findings (before)", fontsize=9)
    ax.set_ylabel("safest observed (after)", fontsize=9)
    ax.set_title(title, fontsize=11)
    ax.grid(True, alpha=0.25, linewidth=0.4)
    return style.savefig(fig, out_path)


def repaired_box(by_strategy: dict[str, list[float]], out_path: Path, title: str,
                 ylabel: str = "tasks repaired to zero (per seed)") -> Path:
    """Box of a per-seed aggregate-repair statistic, one box per strategy (EA vs random)."""
    order = [k for k in ("ea", "rand") if k in by_strategy] or list(by_strategy)
    data = [by_strategy[k] for k in order]
    labels = {"ea": "EA", "rand": "random"}
    fig, ax = plt.subplots(figsize=(4.2, 3.8))
    bp = ax.boxplot(data, labels=[labels.get(k, k) for k in order],
                    patch_artist=True, widths=0.5)
    palette = {"ea": style.OBJECTIVE_COLORS["f2"], "rand": _FLAT}
    for patch, k in zip(bp["boxes"], order):
        patch.set_facecolor(palette.get(k, _FLAT))
        patch.set_alpha(0.65)
    for k, vals in zip(order, data):
        xs = [list(order).index(k) + 1] * len(vals)
        ax.scatter(xs, vals, color=style.GLOBAL_COLOR, s=14, zorder=3, alpha=0.8)
    ax.set_ylabel(ylabel, fontsize=9)
    ax.set_title(title, fontsize=11)
    ax.grid(True, axis="y", alpha=0.25, linewidth=0.4)
    return style.savefig(fig, out_path)
