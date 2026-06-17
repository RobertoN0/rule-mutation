#!/usr/bin/env python3
"""
Per-rule fitness-variation trajectories (schema_version 2).

For every run, plots how a field evolves over the search for each rule's archive
(~21 curves) as both a small-multiples grid and an overlay with a bold global
aggregate, and dumps the underlying series as a tidy long CSV.

Source of the curve:
  --source iterations  dense, every iteration (default; supports --agg)
  --source archive     sparse, the authoritative Pareto-front state per snapshot

Usage:
    python scripts/analyze/fitness_trajectories.py <run_or_parent> [...]
      [--out analysis_output/trajectories] [--fields f1,f2,f3]
      [--source iterations|archive] [--agg best_so_far|value|running_mean]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import loaders as L
from metrics import series as SER
from report.tables import md_table, write_csv
from viz import trajectories as TRJ


def _run_label(run: L.RunData) -> str:
    if run.run_dir.name == "schema2" and run.run_dir.parent.name:
        return f"{run.run_dir.parent.name}__schema2"
    return run.name


def _best_series(run: L.RunData, field: str, source: str, agg: str):
    if source == "archive":
        return SER.archive_series(run, field, reduce="max"), None
    per_rule = SER.iteration_series(run, field, by="rule", agg=agg)
    glob = SER.iteration_series(run, field, by="global", agg=agg)[0]
    return per_rule, glob


def _worst_series(run: L.RunData, field: str, source: str):
    if source == "archive":
        return SER.archive_series(run, field, reduce="min")
    return SER.iteration_series(run, field, by="rule", agg="worst_so_far")


def write_run_trajectories(
    run: L.RunData, out_dir: Path, fields: list[str], source: str, agg: str,
    direction: str | None = None, drop_flat: bool = True,
) -> list[str]:
    out_dir.mkdir(parents=True, exist_ok=True)
    label = _run_label(run)
    long_rows: list[list] = []
    made: list[tuple[str, list[str]]] = []

    for field in fields:
        # Auto default (direction=None): envelope for f1 (the safer/negative
        # direction matters), best for the non-negative f2/f3.
        eff = direction if direction is not None else ("envelope" if field == "f1" else "best")
        ylabel = SER.field_label(field, source=source)
        title = f"{label} - {ylabel}"

        if eff == "envelope":
            best = SER.archive_series(run, field, reduce="max") if source == "archive" \
                else SER.iteration_series(run, field, by="rule", agg="best_so_far")
            worst = _worst_series(run, field, source)
            if not best and not worst:
                continue
            tag = f"{source}_{field}_envelope"
            TRJ.envelope_grid(best, worst, out_dir / f"grid_{tag}.png", title, ylabel)
            TRJ.envelope_overlay(best, worst, out_dir / f"overlay_{tag}.png", title, ylabel, drop_flat=drop_flat)
            made.append((tag, []))
            for bound, series_list in (("max", best), ("min", worst)):
                for s in series_list:
                    for x, y in zip(s.xs, s.ys):
                        long_rows.append([source, field, bound, s.key, x, y])
            continue

        if eff == "worst":
            per_rule, glob = _worst_series(run, field, source), None
            bound = "worst_so_far" if source == "iterations" else "min"
            tag = f"{source}_{field}_worst"
        else:  # best
            per_rule, glob = _best_series(run, field, source, agg)
            bound = agg if source == "iterations" else "max"
            tag = f"{source}_{field}" + ("" if source == "archive" else f"_{agg}")
        if not per_rule:
            continue

        TRJ.small_multiples(per_rule, out_dir / f"grid_{tag}.png", title, ylabel)
        TRJ.overlay(per_rule, out_dir / f"overlay_{tag}.png", title, ylabel, glob, drop_flat=drop_flat)
        flat_labels = [s.label for s in per_rule if s.is_flat()] if drop_flat else []
        made.append((tag, flat_labels))
        for s in per_rule:
            for x, y in zip(s.xs, s.ys):
                long_rows.append([source, field, bound, s.key, x, y])
        if glob is not None:
            for x, y in zip(glob.xs, glob.ys):
                long_rows.append([source, field, bound, SER.GLOBAL_KEY, x, y])

    write_csv(
        out_dir / "series_long.csv",
        ["source", "field", "bound", "rule", "iter", "value"],
        long_rows,
    )

    has_envelope = any(tag.endswith("_envelope") for tag, _ in made)
    lines = [f"# Trajectories - {label}\n"]
    lines.append(f"- source: **{source}** | direction: {direction or 'auto (envelope f1, best f2/f3)'} | agg: {agg} | fields: {', '.join(fields)}")
    lines.append(
        f"- reproduce: `.venv/bin/python scripts/analyze/fitness_trajectories.py "
        f"{run.run_dir} --source {source}`"
        + (f" --direction {direction}" if direction else "")
        + (f" --agg {agg}" if source == "iterations" and agg != "best_so_far" else "")
    )
    if has_envelope:
        lines.append(
            "\n**How to read the f1 envelope.** One panel per rule (grid) and all rules overlaid. "
            "For each rule, the **red** line is the *most-vulnerable* f1 the search reached so far, the "
            "**green** line is the *safest* (most-negative) f1, and the grey band between them is the full "
            "range explored. The **0 line** is the original, unmutated rule. A band sitting mostly **below 0** "
            "means that rule's rephrasings overwhelmingly made the model write *safer* code; a band rising "
            "**above 0** means the search found genuinely more-vulnerable rephrasings.\n")
    lines.append(f"- rules with a curve: {len({r[3] for r in long_rows if r[3] != SER.GLOBAL_KEY})}\n")
    for tag, flat_labels in made:
        lines.append(f"## {tag}")
        lines.append(f"![grid](grid_{tag}.png)\n")
        lines.append(f"![overlay](overlay_{tag}.png)\n")
        if flat_labels:
            lines.append(f"Flat rules omitted from the overlay ({len(flat_labels)}): {', '.join(flat_labels)}\n")
    (out_dir / "trajectories.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return [tag for tag, _ in made]


def main() -> int:
    parser = argparse.ArgumentParser(description="Per-rule fitness-variation trajectories")
    parser.add_argument("paths", nargs="+", type=Path, help="Run dirs or parent dirs")
    parser.add_argument("--out", type=Path, default=Path("analysis_output/trajectories"))
    parser.add_argument("--fields", default="f1,f2,f3", help="comma-separated field names")
    parser.add_argument("--source", choices=["iterations", "archive"], default="iterations")
    parser.add_argument("--agg", choices=list(SER.AGGREGATIONS), default="best_so_far")
    parser.add_argument(
        "--direction", choices=["best", "worst", "envelope"], default=None,
        help="default: auto (envelope for f1, best for f2/f3). best=max f1; worst=min f1; envelope=both",
    )
    parser.add_argument(
        "--keep-flat", action="store_true",
        help="keep never-changing rules in the overlay (default: drop + list them)",
    )
    args = parser.parse_args()

    fields = [f.strip() for f in args.fields.split(",") if f.strip()]
    runs = L.discover_runs(args.paths)
    if not runs:
        print("No runs found.", file=sys.stderr)
        return 1

    for run in runs:
        run_out = args.out / _run_label(run)
        made = write_run_trajectories(
            run, run_out, fields, args.source, args.agg,
            direction=args.direction, drop_flat=not args.keep_flat,
        )
        print(f"wrote {run_out} ({len(made)} field(s))")

    print(f"\nTrajectories written to {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
