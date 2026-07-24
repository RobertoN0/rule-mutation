#!/usr/bin/env python3
"""Create a reusable shared-prefix bundle from a completed five-evaluation run."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from src.optimizer.initialization import materialize_initialization_bundle  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "source_run",
        type=Path,
        help="search run created with --main-loop-budget 0",
    )
    parser.add_argument("output_dir", type=Path, help="new bundle directory")
    args = parser.parse_args()
    path = materialize_initialization_bundle(args.source_run, args.output_dir)
    print(f"Initialization bundle written to {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
