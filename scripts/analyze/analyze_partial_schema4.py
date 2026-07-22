#!/usr/bin/env python3
"""Analyze stable, completed prefixes from explicitly scoped schema-4 snapshots."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_ANALYZE_DIR = Path(__file__).resolve().parent
if str(_ANALYZE_DIR) not in sys.path:
    sys.path.insert(0, str(_ANALYZE_DIR))

from final_schema4.partial import (  # noqa: E402
    analyze_partial,
    discover_partial_entries,
    load_partial_manifest,
    write_partial_analysis,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Write explicitly provisional diagnostics for active/unfinalized schema-4 run snapshots"
        )
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        help=(
            "Optional CSV with model,language,optimizer,seed and run_dir/job_id. "
            "The declared model family is validated against run_config.json."
        ),
    )
    parser.add_argument(
        "--results-root",
        action="append",
        type=Path,
        default=[],
        help=(
            "Explicit partial-results root. Without --manifest, run_config.json "
            "leaves are discovered only below these roots. Repeatable."
        ),
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=Path("analysis_output/partial_schema4"),
    )
    parser.add_argument(
        "--logs-root",
        type=Path,
        default=Path("logs"),
        help="SLURM log root used only to resolve manifest job IDs.",
    )
    parser.add_argument(
        "--subset-dir",
        type=Path,
        default=Path("experiments/analysis/bl40_final_full_analysis"),
        help="Directory containing baseline_common_{python,java}.csv.",
    )
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=Path(__file__).resolve().parents[2],
    )
    return parser


def _resolve(path: Path, *, repo_root: Path) -> Path:
    return path if path.is_absolute() else repo_root / path


def main() -> int:
    args = _parser().parse_args()
    repo_root = args.repo_root.expanduser().resolve()
    out = _resolve(args.out, repo_root=repo_root).resolve()
    subset_dir = _resolve(args.subset_dir, repo_root=repo_root).resolve()
    logs_root = _resolve(args.logs_root, repo_root=repo_root).resolve()
    roots = [
        _resolve(path, repo_root=repo_root).expanduser().resolve() for path in args.results_root
    ]

    try:
        if args.manifest is not None:
            manifest = (
                (args.manifest if args.manifest.is_absolute() else (Path.cwd() / args.manifest))
                .expanduser()
                .resolve()
            )
            entries = load_partial_manifest(
                manifest,
                repo_root=repo_root,
                results_roots=roots,
                logs_root=logs_root,
            )
            source = f"manifest={manifest}"
        else:
            if not roots:
                roots = [(repo_root.parent / "partial_results" / "results").resolve()]
            entries = discover_partial_entries(roots)
            source = "discovery roots=" + ", ".join(str(root) for root in roots)
        bundle = analyze_partial(
            entries,
            subset_dir=subset_dir,
            repo_root=repo_root,
            source_description=source,
        )
        write_partial_analysis(out, bundle)
    except (OSError, ValueError) as exc:
        raise SystemExit(f"partial schema-4 analysis failed: {exc}") from exc

    excluded = sum(not status.eligible for status in bundle.statuses)
    print(
        f"Provisional schema-4 snapshot written to {out}: "
        f"{len(bundle.runs)}/{len(bundle.statuses)} completed prefixes analyzed; "
        f"{excluded} excluded"
    )
    if not bundle.runs:
        return 2
    return 3 if bundle.has_blockers else 0


if __name__ == "__main__":
    raise SystemExit(main())
