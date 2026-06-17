#!/usr/bin/env python3
"""
Security-effect detail (G1) for schema_version 2 runs: per-CWE outcome rates,
per-Semgrep-check flip counts (which checks a rephrasing made appear/disappear),
and prompt-level severity shifts — with a diverging check-flip bar and a per-CWE
outcome bar.

Usage:
    python scripts/analyze/analyze_security.py <run_or_parent> [...]
      [--out analysis_output/security] [--code-divergence-threshold 0.0]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import loaders as L
from report.security import write_run_report


def main() -> int:
    parser = argparse.ArgumentParser(description="Security-effect detail (per-CWE / check flips / severity)")
    parser.add_argument("paths", nargs="+", type=Path, help="Run dirs or parent dirs")
    parser.add_argument("--out", type=Path, default=Path("analysis_output/security"))
    parser.add_argument("--code-divergence-threshold", type=float, default=0.0)
    args = parser.parse_args()

    runs = L.discover_runs(args.paths)
    if not runs:
        print("No runs found.", file=sys.stderr)
        return 1

    for run in runs:
        run_out = args.out / run.run_dir.name
        write_run_report(run, run_out, args.code_divergence_threshold)
        print(f"wrote {run_out}")

    print(f"\nSecurity analysis written to {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
