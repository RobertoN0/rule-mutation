#!/usr/bin/env python3
"""
Cost / operational analysis (G5) for schema_version 2 runs: wall time, LLM calls,
token burn, eval-cache hit rate, per-prompt latency, and budget-matched best-f1
(fair cross-run / cross-model comparison at equal iteration budgets).

Usage:
    python scripts/analyze/analyze_cost.py <run_or_parent> [...]
      [--out analysis_output/cost] [--budgets 33,78,136]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import loaders as L
from report.cost import write_comparison


def main() -> int:
    parser = argparse.ArgumentParser(description="Cost / operational analysis (tokens / cache / budget-matching)")
    parser.add_argument("paths", nargs="+", type=Path, help="Run dirs or parent dirs")
    parser.add_argument("--out", type=Path, default=Path("analysis_output/cost"))
    parser.add_argument("--budgets", default="", help="comma-separated iteration budgets (default: matched quartiles)")
    args = parser.parse_args()

    runs = L.discover_runs(args.paths)
    if not runs:
        print("No runs found.", file=sys.stderr)
        return 1

    budgets = [int(b) for b in args.budgets.split(",") if b.strip()] or None
    write_comparison(runs, args.out, budgets)
    print(f"Cost analysis written to {args.out} ({len(runs)} runs)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
