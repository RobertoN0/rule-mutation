#!/usr/bin/env python3
"""Strict final-results analysis for schema-4 whole-chromosome repair runs.

Without ``--manifest`` this writes the required ``[PENDING: final runs]``
skeleton. With a manifest, it health-checks every expected cell and aggregates
only healthy schema-4 runs.
"""

from __future__ import annotations

import argparse
import csv
import sys
from collections import defaultdict
from pathlib import Path

_ANALYZE_DIR = Path(__file__).resolve().parent
if str(_ANALYZE_DIR) not in sys.path:
    sys.path.insert(0, str(_ANALYZE_DIR))

from final_schema4.core import (  # noqa: E402
    AnalysisBundle,
    analyze_manifest,
    expected_manifest_entries,
    load_manifest,
    parse_seed_spec,
)
from final_schema4.report import write_analysis, write_pending  # noqa: E402


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Analyze the user-confirmed schema-4 final repair manifest"
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        help=(
            "CSV with model,language,optimizer,seed and either run_dir or job_id. "
            "Omit to generate pending skeletons."
        ),
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=Path("analysis_output/final_schema4"),
    )
    parser.add_argument(
        "--expected-run-root",
        type=Path,
        default=Path("experiments/final"),
        help=(
            "Root used to prefill <model>/<language>/<optimizer>/seed<seed> run_dir "
            "containers when --manifest is omitted."
        ),
    )
    parser.add_argument(
        "--expected-models",
        default="qwen,llama",
        help=(
            "Comma-separated final model families (default: qwen,llama). Used to "
            "generate the template and audit whole-family omissions."
        ),
    )
    parser.add_argument(
        "--expected-seeds",
        default="1-10",
        help=(
            "Explicit final seed list/ranges (default: 1-10). Used both to generate "
            "the template and to check a supplied manifest."
        ),
    )
    parser.add_argument(
        "--expected-languages",
        default="python,java",
        help=(
            "Comma-separated language scope (default: python,java). Narrow this only "
            "when the supplied manifest is intentionally a declared study slice."
        ),
    )
    parser.add_argument(
        "--expected-optimizers",
        default="ea,random_search",
        help=(
            "Comma-separated optimizer scope (default: ea,random_search). Narrow this "
            "only when the supplied manifest intentionally excludes an optimizer."
        ),
    )
    parser.add_argument(
        "--allow-missing-semgrep-debug",
        action="store_true",
        help=(
            "Keep otherwise internally consistent runs eligible when the transferred "
            "snapshot omits semgrep_debug/semgrep_debug.jsonl. This is a qualified "
            "override: reports remain ANALYZED_WITH_CAUTION because independent "
            "Semgrep process-error auditing is unavailable."
        ),
    )
    parser.add_argument(
        "--results-root",
        action="append",
        type=Path,
        default=[],
        help="Root searched recursively when manifest rows provide only job_id; repeatable.",
    )
    parser.add_argument(
        "--logs-root",
        type=Path,
        default=Path("logs"),
        help="SLURM log directory used to resolve <jobid>_*.out.",
    )
    parser.add_argument(
        "--subset-dir",
        type=Path,
        default=Path("experiments/analysis/bl40_final_full_analysis"),
        help="Directory containing baseline_common_{python,java}.csv.",
    )
    parser.add_argument(
        "--rules-map-root",
        action="append",
        type=Path,
        default=[],
        help=(
            "Directory containing local copies of rules maps named in cluster-absolute "
            "run configs; repeatable. Defaults to <repo-root>/rule_maps."
        ),
    )
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=Path(__file__).resolve().parents[2],
    )
    return parser


def _parse_models(raw: str) -> list[str]:
    models = [value.strip().lower() for value in raw.split(",") if value.strip()]
    if not models:
        raise ValueError("at least one model family is required")
    if len(set(models)) != len(models):
        raise ValueError("model families contain duplicates")
    invalid = sorted(set(models) - {"qwen", "llama"})
    if invalid:
        raise ValueError(f"unsupported model families: {invalid}")
    return models


def _parse_choices(raw: str, *, name: str, allowed: set[str]) -> list[str]:
    values = [value.strip().lower() for value in raw.split(",") if value.strip()]
    if not values:
        raise ValueError(f"at least one {name} is required")
    if len(set(values)) != len(values):
        raise ValueError(f"{name} contains duplicates")
    invalid = sorted(set(values) - allowed)
    if invalid:
        raise ValueError(f"unsupported {name}: {invalid}")
    return values


def _write_model_index(
    out: Path,
    *,
    expected_models: list[str],
    bundles: dict[str, AnalysisBundle],
    missing_models: list[str],
) -> None:
    out.mkdir(parents=True, exist_ok=True)
    rows = []
    for model in expected_models:
        bundle = bundles.get(model)
        rows.append(
            {
                "model": model,
                "status": "OMITTED" if bundle is None else "ANALYZED",
                "manifest_runs": 0 if bundle is None else len(bundle.healths),
                "analyzed_runs": 0 if bundle is None else len(bundle.runs),
                "warnings": 0 if bundle is None else len(bundle.analysis_warnings),
                "output_dir": "" if bundle is None else model,
            }
        )
    with (out / "model_index.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    links = "\n".join(
        f"- `{model}`: [{model}/REPORT.md]({model}/REPORT.md)"
        for model in expected_models
        if model in bundles
    )
    omission = (
        "\n\nMissing expected model families: "
        + ", ".join(f"`{model}`" for model in missing_models)
        + "."
        if missing_models
        else ""
    )
    (out / "REPORT.md").write_text(
        "# Final schema-4 analysis by model\n\n"
        "Material Passport: " + ("ANALYZED_WITH_CAUTION" if missing_models else "ANALYZED") + "\n\n"
        "Qwen and Llama are kept in separate analysis bundles; no outcome is "
        "implicitly pooled across models.\n\n" + links + omission + "\n",
        encoding="utf-8",
    )


def main() -> int:
    args = _parser().parse_args()
    repo_root = args.repo_root.resolve()
    out = args.out if args.out.is_absolute() else repo_root / args.out
    try:
        expected_seeds = parse_seed_spec(args.expected_seeds)
        expected_models = _parse_models(args.expected_models)
        expected_languages = _parse_choices(
            args.expected_languages,
            name="language",
            allowed={"python", "java"},
        )
        expected_optimizers = _parse_choices(
            args.expected_optimizers,
            name="optimizer",
            allowed={"ea", "random_search"},
        )
    except ValueError as exc:
        raise SystemExit(f"invalid expected matrix: {exc}") from exc
    if args.manifest is None:
        expected_entries = expected_manifest_entries(
            args.expected_run_root,
            models=expected_models,
            languages=expected_languages,
            optimizers=expected_optimizers,
            seeds=expected_seeds,
        )
        write_pending(
            out,
            reason=(
                "No user-confirmed final manifest was supplied. Historical, diagnostic, "
                "and active partial-run trees are intentionally excluded."
            ),
            expected_entries=expected_entries,
        )
        print(
            f"Pending schema-4 analysis scaffold written to {out}: "
            f"{len(expected_entries)} expected cells under {args.expected_run_root}"
        )
        return 0

    manifest_path = (
        args.manifest if args.manifest.is_absolute() else (Path.cwd() / args.manifest)
    ).resolve()
    result_roots = args.results_root or [
        repo_root / "experiments" / "results",
        repo_root / "experiments",
    ]
    result_roots = [root if root.is_absolute() else repo_root / root for root in result_roots]
    logs_root = args.logs_root if args.logs_root.is_absolute() else repo_root / args.logs_root
    subset_dir = args.subset_dir if args.subset_dir.is_absolute() else repo_root / args.subset_dir
    rules_map_roots = args.rules_map_root or [repo_root / "rule_maps"]
    rules_map_roots = [root if root.is_absolute() else repo_root / root for root in rules_map_roots]
    entries = load_manifest(
        manifest_path,
        repo_root=repo_root,
        results_roots=result_roots,
        logs_root=logs_root,
    )
    grouped: dict[str, list] = defaultdict(list)
    for entry in entries:
        grouped[entry.model].append(entry)
    unexpected_models = sorted(set(grouped) - set(expected_models))
    if unexpected_models:
        raise SystemExit(
            "manifest contains model families outside --expected-models: "
            + ", ".join(unexpected_models)
        )

    bundles = {
        model: analyze_manifest(
            model_entries,
            subset_dir=subset_dir,
            expected_seeds=expected_seeds,
            expected_languages=expected_languages,
            expected_optimizers=expected_optimizers,
            allow_missing_semgrep_debug=args.allow_missing_semgrep_debug,
            rules_map_roots=rules_map_roots,
        )
        for model, model_entries in sorted(grouped.items())
    }
    missing_models = sorted(set(expected_models) - set(bundles))
    if len(bundles) == 1 and len(expected_models) == 1:
        bundle = next(iter(bundles.values()))
        write_analysis(
            out,
            bundle,
            manifest_path=manifest_path,
            repo_root=repo_root,
        )
    else:
        for model, bundle in bundles.items():
            write_analysis(
                out / model,
                bundle,
                manifest_path=manifest_path,
                repo_root=repo_root,
            )
        _write_model_index(
            out,
            expected_models=expected_models,
            bundles=bundles,
            missing_models=missing_models,
        )
    analyzed_n = sum(len(bundle.runs) for bundle in bundles.values())
    supplied_n = sum(len(bundle.healths) for bundle in bundles.values())
    warning_n = sum(len(bundle.analysis_warnings) for bundle in bundles.values())
    excluded_n = sum(
        sum(not health.healthy for health in bundle.healths) for bundle in bundles.values()
    )
    has_cautions = bool(missing_models) or any(bundle.has_cautions for bundle in bundles.values())
    print(
        f"Schema-4 analysis written to {out}: "
        f"{analyzed_n}/{supplied_n} healthy runs analyzed across "
        f"{len(bundles)} model bundle(s); "
        f"{warning_n} warning(s), {excluded_n} excluded run(s), "
        f"{len(missing_models)} omitted expected model family/families"
    )
    if not analyzed_n:
        return 2
    return 0 if not has_cautions else 3


if __name__ == "__main__":
    raise SystemExit(main())
