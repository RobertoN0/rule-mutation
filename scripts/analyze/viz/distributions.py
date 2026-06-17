"""
Outcome-distribution plots. Consumes a ``metrics.outcomes.RunOutcome``;
computes nothing of its own beyond the per-scope fractions for the bars.
"""

from __future__ import annotations

from pathlib import Path

from metrics import outcomes as OC
from viz import style
from viz.style import plt


def outcome_distribution_figure(outcome: OC.RunOutcome, out_dir: Path) -> Path:
    labels = ["prompt", "applicable", "all prompt-rules"]
    scope_values = ["prompt", "applicable", "all_prompt_rules"]
    data = []
    for scope in scope_values:
        states = OC.states_for_scope(outcome, scope)
        n = len(states)
        counts = OC.distribution(states)
        data.append([counts[name] / n if n else 0.0 for name in OC.OUTCOMES])

    fig, ax = plt.subplots(figsize=(7, 4))
    bottoms = [0.0] * len(labels)
    for idx, name in enumerate(OC.OUTCOMES):
        values = [row[idx] for row in data]
        ax.bar(labels, values, bottom=bottoms, label=name, color=style.OUTCOME_COLORS[name])
        bottoms = [bottoms[i] + values[i] for i in range(len(values))]
    ax.set_ylim(0, 1)
    ax.set_ylabel("fraction of units")
    ax.set_title(f"Outcome distribution - {OC.run_label(outcome.run)}")
    ax.legend(loc="upper right", fontsize=8)
    return style.savefig(fig, out_dir / "outcome_distribution.png")
