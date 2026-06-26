"""
Search-behaviour (G3 / RQ3) report assembly: per-run efficiency / restart /
Pareto-front CSV + Markdown + plots, and a cross-run efficiency comparison
(EA vs random) with an overlaid convergence figure.
"""

from __future__ import annotations

import statistics
from pathlib import Path

import loaders as L
import stats as S
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

    terms = L.direction_terms(run.objective_direction)
    lines = [f"# Search behaviour - {run.run_dir.name}",
             f"_objective: **{terms['goal']}** — within this run higher f1 = {terms['high_label']}._\n"]
    lines.append("## Efficiency")
    lines.append(f"_`positive_iteration_rate` = share of iterations that {terms['positive_iter_label']}; "
                 "`acceptance_rate` = share accepted into an archive; `iter_to_first_best` = time-to-best._")
    lines.append(md_table(SR.EFFICIENCY_HEADER, [SR.efficiency_row(run)]))
    lines.append("\n## Restart reasons (stagnation==0 is the bd-qfm finding)")
    lines.append(md_table(SR.RESTART_HEADER, restart))
    lines.append("\n![restart reasons](restart_reasons.png)\n")
    lines.append("## Final Pareto front per rule")
    lines.append(f"_Per rule's surviving front: `max_f1` = {terms['high_label']} kept, "
                 f"`min_f1` = {terms['low_label']} kept, "
                 "`max_depth` = deepest chain, plus insertion/rejection counts._")
    lines.append(md_table(SR.FRONT_HEADER, front) if front else "(no archive — random baseline)")
    (out_dir / "search.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_comparison(runs: list[L.RunData], out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    rows = [SR.efficiency_row(run) for run in runs]
    write_csv(out_dir / "efficiency_comparison.csv", SR.EFFICIENCY_HEADER, rows)

    by_strat: dict[str, list[L.RunData]] = {}
    for r in runs:
        by_strat.setdefault(r.strategy, []).append(r)

    lines = ["# Search efficiency comparison\n", f"Runs: {len(runs)}\n"]
    lines.append(md_table(SR.EFFICIENCY_HEADER, rows))

    # ---- RQ3: EA vs random on best_f1 — independent samples (Arcuri & Briand) ----
    ea, rand = by_strat.get("ea", []), by_strat.get("random_baseline", [])
    if ea and rand:
        terms = L.direction_terms(ea[0].objective_direction)
        ea_bf = [L.best_f1(r) for r in ea]
        rd_bf = [L.best_f1(r) for r in rand]
        lines.append("\n## RQ3 — EA vs random (best f1)")
        lines.append(f"_best_f1 = {terms['best_f1_label']}. Per-seed runs at a fixed prompt set are "
                     "**independent samples**, so this is an **unpaired Mann-Whitney U** + "
                     "**Vargha-Delaney Â₁₂** (Â₁₂ > 0.5 favours EA), not a paired test._")
        lines.append(md_table(
            ["arm", "n", "best_f1 (sorted)", "median"],
            [["ea", len(ea_bf), ", ".join(f"{v:+.1f}" for v in sorted(ea_bf, reverse=True)),
              f"{statistics.median(ea_bf):+.2f}"],
             ["random", len(rd_bf), ", ".join(f"{v:+.1f}" for v in sorted(rd_bf, reverse=True)),
              f"{statistics.median(rd_bf):+.2f}"]],
        ))
        mw = S.mann_whitney_u(ea_bf, rd_bf)
        a12, mag = S.vargha_delaney_a12(ea_bf, rd_bf)
        lines.append(f"\n- {mw}")
        lines.append(f"- Vargha-Delaney Â₁₂ = **{a12:.3f}** ({mag}) — P(an EA run beats a random run)")
        if min(len(ea_bf), len(rd_bf)) < 4:
            lines.append("- ⚠️ n < 4 per arm: Mann-Whitney U cannot reach p < 0.05 (small-n floor) — "
                         "read Â₁₂ and the raw values, not the p-value.")

    VSR.convergence_band(by_strat, out_dir / "convergence_band.png",
                         f"Convergence — median + IQR ({len(runs)} runs)")
    lines.append("\n![convergence band](convergence_band.png)\n")
    (out_dir / "efficiency_comparison.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
