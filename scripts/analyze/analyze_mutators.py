#!/usr/bin/env python3
"""
Mutator-effectiveness analysis (RQ2 / bd-03k.1) for schema_version 2 runs.

For each run: lineage steps (rule, iter, mutator, position, f1_before/after,
delta), per-mutator step-delta, position sensitivity, LLM-vs-structural-vs-mixed
composition, archive insertion rates, recurring high-fitness chains, and the
per-rule best path — plus a signed delta bar and a position heatmap. With
multiple runs, also writes a pooled (multi-seed) view.

Usage:
    python scripts/analyze/analyze_mutators.py <run_or_parent> [...]
      [--out analysis_output/mutators] [--no-pooled]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import loaders as L
from report.mutators import write_pooled_report, write_run_report


def main() -> int:
    parser = argparse.ArgumentParser(description="Mutator effectiveness / lineage analysis (RQ2)")
    parser.add_argument("paths", nargs="+", type=Path, help="Run dirs or parent dirs")
    parser.add_argument("--out", type=Path, default=Path("analysis_output/mutators"))
    parser.add_argument("--no-pooled", action="store_true", help="skip the pooled multi-run view")
    args = parser.parse_args()

    runs = L.discover_runs(args.paths)
    if not runs:
        print("No runs found.", file=sys.stderr)
        return 1

    for run in runs:
        run_out = args.out / run.run_dir.name
        n = write_run_report(run, run_out)
        print(f"wrote {run_out} ({n} steps)")

    if len(runs) > 1 and not args.no_pooled:
        n = write_pooled_report(runs, args.out / "_pooled")
        print(f"wrote {args.out / '_pooled'} (pooled, {n} steps)")

    print(f"\nMutator analysis written to {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
