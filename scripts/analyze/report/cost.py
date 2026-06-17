"""
Cost / operational (G5) report assembly: a cross-run cost + latency table and a
budget-matched best-f1 table. CSV + Markdown (no plots — token-over-iteration
curves are covered by fitness_trajectories with --fields input_tokens_total).
"""

from __future__ import annotations

from pathlib import Path

import loaders as L
from metrics import cost as CST
from report.tables import md_table, write_csv


def write_comparison(runs: list[L.RunData], out_dir: Path, budgets: list[int] | None = None) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    cost_rows = [CST.cost_row(run) for run in runs]
    latency_rows = [CST.latency_row(run) for run in runs]
    if not budgets:
        budgets = CST.matched_budgets(runs)
    budget_header, budget_rows = CST.budget_rows(runs, budgets)

    write_csv(out_dir / "cost.csv", CST.COST_HEADER, cost_rows)
    write_csv(out_dir / "latency.csv", CST.LATENCY_HEADER, latency_rows)
    write_csv(out_dir / "budget_matched.csv", budget_header, budget_rows)

    lines = ["# Cost / operational summary\n", f"Runs: {len(runs)}\n"]
    lines.append("## Cost")
    lines.append(md_table(CST.COST_HEADER, cost_rows))
    lines.append("\n## Per-prompt latency (baseline pass)")
    lines.append(md_table(CST.LATENCY_HEADER, latency_rows))
    lines.append("\n## Budget-matched best f1 (compare runs only at equal iteration budgets)")
    lines.append(md_table(budget_header, budget_rows))
    (out_dir / "cost.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
