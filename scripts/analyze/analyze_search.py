#!/usr/bin/env python3
"""
Search-behaviour analysis (G3 / RQ3) for schema_version 2 runs: per-run
efficiency (best f1, time-to-best, positive/acceptance/identity rates), restart
reason breakdown (the bd-qfm gate), and the final Pareto front per rule. With
multiple runs, also writes an EA-vs-random efficiency comparison + convergence.

Usage:
    python scripts/analyze/analyze_search.py <run_or_parent> [...]
      [--out analysis_output/search] [--no-comparison]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import loaders as L
from report.search import write_comparison, write_run_report


def main() -> int:
    parser = argparse.ArgumentParser(description="Search-behaviour analysis (efficiency / restart / Pareto)")
    parser.add_argument("paths", nargs="+", type=Path, help="Run dirs or parent dirs")
    parser.add_argument("--out", type=Path, default=Path("analysis_output/search"))
    parser.add_argument("--no-comparison", action="store_true", help="skip the cross-run comparison")
    args = parser.parse_args()

    runs = L.discover_runs(args.paths)
    if not runs:
        print("No runs found.", file=sys.stderr)
        return 1

    for run in runs:
        run_out = args.out / run.run_dir.name
        write_run_report(run, run_out)
        print(f"wrote {run_out}")

    if len(runs) > 1 and not args.no_comparison:
        write_comparison(runs, args.out / "_comparison")
        print(f"wrote {args.out / '_comparison'} (comparison)")

    print(f"\nSearch analysis written to {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
