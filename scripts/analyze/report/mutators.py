"""
Mutator-effectiveness (RQ2 / bd-03k.1) report assembly: per-run and pooled
(multi-seed) CSV + Markdown + plots. The only mutator layer that writes files.
"""

from __future__ import annotations

from pathlib import Path

import loaders as L
from metrics import mutators as MUT
from report.tables import md_table, write_csv
from viz import mutators as VM


def _position_matrix(position_rows: list[list]):
    """position_table rows -> (mutators, positions, matrix[mut][pos] mean delta)."""
    mutators = sorted({r[0] for r in position_rows})
    positions = sorted({r[1] for r in position_rows})
    index = {(r[0], r[1]): r[3] for r in position_rows}
    matrix = [[index.get((m, p), float("nan")) for p in positions] for m in mutators]
    return mutators, positions, matrix


def _write_step_derived(steps, out_dir: Path, label: str, *, with_plots: bool,
                        direction: str = "maximize") -> list[str]:
    """Shared per-mutator / position / composition outputs for a set of steps."""
    t = L.direction_terms(direction)
    per_mut = MUT.per_mutator_delta(steps)
    position = MUT.position_table(steps)
    composition = MUT.composition_compare(steps)

    write_csv(out_dir / "per_mutator_delta.csv", MUT.PER_MUTATOR_HEADER, per_mut)
    write_csv(out_dir / "position_table.csv", MUT.POSITION_HEADER, position)
    write_csv(out_dir / "composition_compare.csv", MUT.COMPOSITION_HEADER, composition)

    lines = [f"# Mutator effectiveness - {label}\n"]
    lines.append(f"- lineage steps: {len(steps)}")
    lines.append("_A step credits the last mutator in the chain with `delta = f1 - parent_f1` (how much it "
                 f"moved f1 that step; {t['pos_delta_label']}). `mean_delta_first`/`_later` split by whether the "
                 "mutator opened the chain (depth 1) or was stacked deeper (order sensitivity)._\n")
    lines.append(f"## Per-mutator step-delta (delta = f1 - parent_f1; {t['pos_delta_label']})")
    lines.append(md_table(MUT.PER_MUTATOR_HEADER, per_mut))
    lines.append("\n## LLM vs structural vs mixed chains")
    lines.append(md_table(MUT.COMPOSITION_HEADER, composition))
    lines.append("\n## Position sensitivity (mutator x chain depth)")
    lines.append(md_table(MUT.POSITION_HEADER, position))

    if with_plots:
        VM.per_mutator_delta_bar(
            [(r[0], r[3]) for r in per_mut], out_dir / "per_mutator_delta.png",
            f"Per-mutator mean step-delta - {label}", direction=direction,
        )
        mutators, positions, matrix = _position_matrix(position)
        if mutators and positions:
            VM.position_heatmap(
                mutators, positions, matrix, out_dir / "position_heatmap.png",
                f"Mean step-delta by position - {label}",
            )
        lines.append("\n![per-mutator delta](per_mutator_delta.png)\n")
        lines.append("![position heatmap](position_heatmap.png)\n")
    return lines


def write_run_report(run: L.RunData, out_dir: Path) -> int:
    out_dir.mkdir(parents=True, exist_ok=True)
    steps = MUT.lineage_steps(run)
    label = run.run_dir.name

    write_csv(out_dir / "lineage_steps.csv", MUT.STEPS_HEADER, MUT.step_rows(steps))
    write_csv(out_dir / "insert_rates.csv", MUT.INSERT_RATE_HEADER, MUT.insert_rate_rows(run))
    write_csv(out_dir / "combinations.csv", MUT.COMBINATION_HEADER, MUT.combination_counts(run))
    write_csv(out_dir / "per_rule_best_path.csv", MUT.BEST_PATH_HEADER, MUT.per_rule_best_path(run))
    write_csv(out_dir / "per_rule_safest_path.csv", MUT.SAFEST_PATH_HEADER, MUT.per_rule_safest_path(run))

    lines = _write_step_derived(steps, out_dir, label, with_plots=True,
                                direction=run.objective_direction)
    lines.append("\n## Archive insertion rates (from summary)")
    lines.append(md_table(MUT.INSERT_RATE_HEADER, MUT.insert_rate_rows(run)))
    lines.append("\n## Recurring high-fitness combinations (surviving front)")
    lines.append(md_table(MUT.COMBINATION_HEADER, MUT.combination_counts(run)) or "(none)")
    lines.append("\n## Per-rule best path (most adversarial, max f1)")
    lines.append(md_table(MUT.BEST_PATH_HEADER, MUT.per_rule_best_path(run)) or "(none)")
    lines.append("\n## Per-rule safest path (most defensive, min / negative f1)")
    lines.append(md_table(MUT.SAFEST_PATH_HEADER, MUT.per_rule_safest_path(run)) or "(none)")
    (out_dir / "mutators.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return len(steps)


def write_pooled_report(runs: list[L.RunData], out_dir: Path) -> int:
    out_dir.mkdir(parents=True, exist_ok=True)
    steps = [s for run in runs for s in MUT.lineage_steps(run)]
    lines = _write_step_derived(steps, out_dir, f"pooled ({len(runs)} runs)", with_plots=True,
                                direction=(runs[0].objective_direction if runs else "maximize"))
    (out_dir / "mutators_pooled.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return len(steps)
