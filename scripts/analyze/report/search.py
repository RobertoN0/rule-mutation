"""
Search-behaviour (G3 / RQ3) report assembly: per-run efficiency / restart /
Pareto-front CSV + Markdown + plots, and a cross-run efficiency comparison
(EA vs random) with an overlaid convergence figure.
"""

from __future__ import annotations

from pathlib import Path

import loaders as L
from metrics import search as SR
from report.tables import md_table, write_csv
from viz import search as VSR


def write_run_report(run: L.RunData, out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    restart = SR.restart_rows(run)
    front = SR.final_front_rows(run)

    write_csv(out_dir / "efficiency.csv", SR.EFFICIENCY_HEADER, [SR.efficiency_row(run)])
    write_csv(out_dir / "restart_reasons.csv", SR.RESTART_HEADER, restart)
    write_csv(out_dir / "final_front.csv", SR.FRONT_HEADER, front)

    VSR.restart_reason_bar(restart, out_dir / "restart_reasons.png", f"Restart reasons - {run.run_dir.name}")

    lines = [f"# Search behaviour - {run.run_dir.name}\n"]
    lines.append("## Efficiency")
    lines.append("_`positive_iteration_rate` = share of iterations that found a more-vulnerable rephrasing; "
                 "`acceptance_rate` = share accepted into an archive; `iter_to_first_best` = time-to-best._")
    lines.append(md_table(SR.EFFICIENCY_HEADER, [SR.efficiency_row(run)]))
    lines.append("\n## Restart reasons (stagnation==0 is the bd-qfm finding)")
    lines.append(md_table(SR.RESTART_HEADER, restart))
    lines.append("\n![restart reasons](restart_reasons.png)\n")
    lines.append("## Final Pareto front per rule")
    lines.append("_Per rule's surviving front: `max_f1` = most-vulnerable kept, `min_f1` = safest kept, "
                 "`max_depth` = deepest chain, plus insertion/rejection counts._")
    lines.append(md_table(SR.FRONT_HEADER, front) if front else "(no archive — random baseline)")
    (out_dir / "search.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_comparison(runs: list[L.RunData], out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    rows = [SR.efficiency_row(run) for run in runs]
    write_csv(out_dir / "efficiency_comparison.csv", SR.EFFICIENCY_HEADER, rows)
    VSR.convergence_overlay(runs, out_dir / "convergence.png", f"Best-so-far f1 ({len(runs)} runs)")

    lines = ["# Search efficiency comparison\n", f"Runs: {len(runs)}\n"]
    lines.append(md_table(SR.EFFICIENCY_HEADER, rows))
    lines.append("\n![convergence](convergence.png)\n")
    (out_dir / "efficiency_comparison.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
