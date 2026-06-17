#!/usr/bin/env python3
"""
Rule-aware outcome-distribution analysis (schema_version 2) — the bd-7kr metric.

Cisco-style paired static-analysis intuition adapted to this experiment:
  1. Prompt headline: per prompt, collapse over every observed rephrasing of every
     retrieved rule (degraded / unchanged / safer + code_changed).
  2. Rule-prompt backing view: per (rule, prompt) exposure, two denominators —
     applicable (rule-faithful) and all_prompt_rules (conservative, memo-compatible).

Thin CLI: discovers runs, builds outcomes (metrics.outcomes), writes per-run and
cross-run reports (report.outcomes). The compute / plot / report layers live in
the metrics / viz / report packages.

Usage:
    python scripts/analyze/outcome_distribution.py <run_dir_or_parent> [...]
      [--out analysis_output/outcomes] [--code-divergence-threshold 0.0]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import loaders as L
from metrics import outcomes as OC
from report.outcomes import write_cross_run_report, write_run_report


def main() -> int:
    parser = argparse.ArgumentParser(description="Prompt and rule-prompt outcome distribution analysis")
    parser.add_argument("paths", nargs="+", type=Path, help="Run dirs or parent dirs")
    parser.add_argument("--out", type=Path, default=Path("analysis_output/outcomes"))
    parser.add_argument("--code-divergence-threshold", type=float, default=0.0)
    args = parser.parse_args()

    runs = L.discover_runs(args.paths)
    if not runs:
        print("No runs found.", file=sys.stderr)
        return 1

    outcomes = []
    for run in runs:
        outcome = OC.build_run_outcome(run, args.code_divergence_threshold)
        outcomes.append(outcome)
        run_out = args.out / OC.run_label(run)
        write_run_report(outcome, run_out)
        print(f"wrote {run_out}")

    write_cross_run_report(outcomes, args.out)
    print(f"\nOutcome distribution written to {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
