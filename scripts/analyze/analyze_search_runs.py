#!/usr/bin/env python3
"""Analyse validated EA/random-search runs under the primary wall-time budget."""

from __future__ import annotations

import argparse
import json
import math
import random
import statistics
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from scripts.analyze.stats import sign_test, wilcoxon_paired  # noqa: E402
from scripts.analyze.validate_search_run import validate_run  # noqa: E402


def _json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path}: expected a JSON object")
    return payload


def _jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            row = json.loads(line)
            if not isinstance(row, dict):
                raise ValueError(f"{path}:{line_number}: expected a JSON object")
            rows.append(row)
    return rows


def _bootstrap_ci(
    values: list[float],
    *,
    seed: int,
    samples: int,
) -> list[float] | None:
    if not values:
        return None
    if len(values) == 1:
        return [values[0], values[0]]
    rng = random.Random(seed)
    means = sorted(
        statistics.fmean(rng.choice(values) for _ in values)
        for _ in range(samples)
    )
    lo = means[math.floor(0.025 * (samples - 1))]
    hi = means[math.ceil(0.975 * (samples - 1))]
    return [lo, hi]


def _summarize(
    values: list[float],
    *,
    seed: int,
    samples: int,
) -> dict[str, Any]:
    return {
        "n": len(values),
        "mean": statistics.fmean(values) if values else None,
        "median": statistics.median(values) if values else None,
        "min": min(values) if values else None,
        "max": max(values) if values else None,
        "mean_bootstrap_95_ci": _bootstrap_ci(
            values,
            seed=seed,
            samples=samples,
        ),
        "values": values,
    }


def _incumbent_points(
    rows: list[dict[str, Any]],
) -> tuple[float, float, list[dict[str, float | int]]]:
    evaluated = [
        row
        for row in rows
        if row.get("evaluation_consumed") is True
        and isinstance(row.get("f1"), (int, float))
    ]
    initialization_incumbent = max(
        [0.0] + [float(row["f1"]) for row in evaluated[:5]]
    )
    incumbent = initialization_incumbent
    points: list[dict[str, float | int]] = []
    for row in evaluated[5:]:
        incumbent = max(incumbent, float(row["f1"]))
        points.append(
            {
                "main_loop_evaluation": int(row["main_loop_iteration"]),
                "elapsed_main_loop_seconds": float(
                    row["elapsed_main_loop_seconds"]
                ),
                "incumbent_f1": incumbent,
            }
        )
    final_incumbent = (
        initialization_incumbent
        if not points
        else float(points[-1]["incumbent_f1"])
    )
    return initialization_incumbent, final_incumbent, points


def _load_run(run_dir: Path, *, allow_diagnostic: bool) -> dict[str, Any]:
    run_dir = run_dir.resolve()
    validation = validate_run(run_dir)
    if validation["status"] != "VALID":
        raise ValueError(
            f"{run_dir}: validation failed: {'; '.join(validation['issues'])}"
        )
    if not allow_diagnostic and not validation["final_search_eligible"]:
        raise ValueError(
            f"{run_dir}: run is valid but not eligible for the final "
            "equal-wall-time full-population comparison"
        )
    config = _json(run_dir / "run_config.json")
    args = config["args"]
    summary = _json(run_dir / "search_summary.json")
    rows = _jsonl(run_dir / "evaluations.jsonl")
    initialization_incumbent, final_incumbent, points = _incumbent_points(rows)
    language_values = args.get("languages")
    language = (
        language_values[0]
        if isinstance(language_values, list) and len(language_values) == 1
        else "all"
    )
    condition_contract = {
        "git_commit_sha": config.get("git_commit_sha"),
        "model": args.get("model"),
        "model_revision": args.get("model_revision"),
        "torch_version": args.get("torch_version"),
        "transformers_version": args.get("transformers_version"),
        "quantization": args.get("quantization"),
        "bnb_compute_dtype": args.get("bnb_compute_dtype"),
        "language": language,
        "temperature": args.get("temperature"),
        "prompt_contract_sha256": args.get("prompt_contract_sha256"),
        "rules_map_sha256": args.get("rules_map_sha256"),
        "population_fingerprint": args.get("population_fingerprint"),
        "evaluation_population_fingerprint": args.get(
            "evaluation_population_fingerprint"
        ),
        "rule_corpus_sha256": args.get("rule_corpus_sha256"),
        "n_cases": args.get("n_cases"),
        "selection": args.get("selection"),
        "mutators": args.get("mutators"),
        "objective_direction": args.get("objective_direction"),
        "fitness_strategy": args.get("fitness_strategy"),
        "max_output_tokens": args.get("max_output_tokens"),
        "main_loop_budget": args.get("main_loop_budget"),
        "wall_time_budget_seconds": args.get("wall_time_budget_seconds"),
        "pretimeout_lead_seconds": args.get("pretimeout_lead_seconds"),
        "archive_cap": args.get("archive_cap"),
        "max_depth": args.get("max_depth"),
        "random_max_changes": args.get("random_max_changes"),
        "ea_injection_every": args.get("ea_injection_every"),
        "order_move_weight": args.get("order_move_weight"),
        "enable_validation": args.get("enable_validation"),
        "enable_eval_cache": args.get("enable_eval_cache"),
        "semgrep_version": args.get("semgrep_version"),
        "semgrep_rule_config_kind": args.get("semgrep_rule_config_kind"),
        "semgrep_rules_sha256": args.get("semgrep_rules_sha256"),
        "semgrep_rule_file_count": args.get("semgrep_rule_file_count"),
        "semgrep_rules_source_commit": args.get(
            "semgrep_rules_source_commit"
        ),
    }
    return {
        "run_dir": str(run_dir),
        "model": args["model"],
        "language": language,
        "seed": int(args["seed"]),
        "optimizer": args["optimizer"],
        "temperature": float(args["temperature"]),
        "rules_map_sha256": args["rules_map_sha256"],
        "evaluation_population_fingerprint": args[
            "evaluation_population_fingerprint"
        ],
        "initialization_bundle_content_sha256": args.get(
            "initialization_bundle_content_sha256"
        ),
        "wall_time_budget_seconds": args.get("wall_time_budget_seconds"),
        "condition_contract": condition_contract,
        "termination_reason": summary["termination_reason"],
        "completed_evaluations": int(summary["num_evaluations_completed"]),
        "completed_main_loop_evaluations": int(
            summary["main_loop_evaluations_completed"]
        ),
        "main_loop_time_seconds": float(summary["main_loop_time_seconds"]),
        "best_f1": final_incumbent,
        "initialization_best_f1": initialization_incumbent,
        "best_raw_findings": int(summary["best_raw_findings"]),
        "original_raw_findings": int(summary["original_raw_findings"]),
        "best_invalid_prompts": int(summary["best_num_invalid_prompts"]),
        "points": points,
    }


def _pair_contract(run: dict[str, Any]) -> tuple[Any, ...]:
    return (
        run["model"],
        run["language"],
        run["seed"],
        json.dumps(run["condition_contract"], sort_keys=True),
        run["initialization_bundle_content_sha256"],
    )


def _condition_contract(run: dict[str, Any]) -> tuple[Any, ...]:
    """Return the experimental condition shared by seeds within a stratum."""
    return (json.dumps(run["condition_contract"], sort_keys=True),)


def _test_result(result: Any) -> dict[str, Any]:
    return {
        "name": result.name,
        "statistic": result.statistic,
        "p": result.p,
        "n": result.n,
        "note": result.note,
    }


def _curves(
    runs: list[dict[str, Any]],
    *,
    time_step_seconds: int,
    seed: int,
    samples: int,
) -> dict[str, Any]:
    by_optimizer: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for run in runs:
        by_optimizer[run["optimizer"]].append(run)
    result: dict[str, Any] = {}
    for optimizer, arm_runs in sorted(by_optimizer.items()):
        max_evaluation = max(
            (run["completed_main_loop_evaluations"] for run in arm_runs),
            default=0,
        )
        evaluation_curve = []
        for index in range(1, max_evaluation + 1):
            values = [
                float(run["points"][index - 1]["incumbent_f1"])
                for run in arm_runs
                if len(run["points"]) >= index
            ]
            evaluation_curve.append(
                {
                    "main_loop_evaluation": index,
                    **_summarize(
                        values,
                        seed=seed + index,
                        samples=samples,
                    ),
                }
            )
        time_budget = max(
            int(run.get("wall_time_budget_seconds") or 0)
            for run in arm_runs
        )
        time_curve = []
        for second in range(0, time_budget + 1, time_step_seconds):
            values = []
            for run in arm_runs:
                incumbent = max(
                    [float(run["initialization_best_f1"])]
                    + [
                        float(point["incumbent_f1"])
                        for point in run["points"]
                        if float(point["elapsed_main_loop_seconds"]) <= second
                    ]
                )
                values.append(incumbent)
            time_curve.append(
                {
                    "elapsed_main_loop_seconds": second,
                    **_summarize(
                        values,
                        seed=seed + second,
                        samples=samples,
                    ),
                }
            )
        result[optimizer] = {
            "evaluation_curve": evaluation_curve,
            "time_curve": time_curve,
        }
    return result


def _arm_summary(
    runs: list[dict[str, Any]],
    *,
    bootstrap_seed: int,
    bootstrap_samples: int,
) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for optimizer in sorted({run["optimizer"] for run in runs}):
        arm = [run for run in runs if run["optimizer"] == optimizer]
        result[optimizer] = {
            metric: _summarize(
                [float(run[metric]) for run in arm],
                seed=bootstrap_seed + offset,
                samples=bootstrap_samples,
            )
            for offset, metric in enumerate(
                (
                    "best_f1",
                    "best_raw_findings",
                    "completed_main_loop_evaluations",
                    "main_loop_time_seconds",
                    "best_invalid_prompts",
                )
            )
        }
    return result


def _paired_row(
    contract: tuple[Any, ...],
    arms: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    ea = arms["ea"]
    random_run = arms["random_search"]
    return {
        "model": contract[0],
        "language": contract[1],
        "seed": contract[2],
        "ea_run_dir": ea["run_dir"],
        "random_run_dir": random_run["run_dir"],
        "best_f1_difference_ea_minus_random": (
            ea["best_f1"] - random_run["best_f1"]
        ),
        "best_raw_findings_difference_ea_minus_random": (
            ea["best_raw_findings"] - random_run["best_raw_findings"]
        ),
        "completed_main_loop_evaluations_difference_ea_minus_random": (
            ea["completed_main_loop_evaluations"]
            - random_run["completed_main_loop_evaluations"]
        ),
    }


def analyze(
    run_dirs: list[Path],
    *,
    allow_diagnostic: bool,
    bootstrap_samples: int,
    bootstrap_seed: int,
    time_step_seconds: int,
) -> dict[str, Any]:
    runs = [_load_run(path, allow_diagnostic=allow_diagnostic) for path in run_dirs]
    wall_time_budgets = sorted(
        {
            int(run["wall_time_budget_seconds"])
            for run in runs
            if isinstance(run.get("wall_time_budget_seconds"), int)
            and not isinstance(run.get("wall_time_budget_seconds"), bool)
            and int(run["wall_time_budget_seconds"]) > 0
        }
    )
    if not allow_diagnostic and (
        len(wall_time_budgets) != 1 or len(wall_time_budgets) != len(
            {
                run.get("wall_time_budget_seconds")
                for run in runs
            }
        )
    ):
        raise ValueError(
            "final analysis requires one common positive scheduler wall-time "
            "budget across every run"
        )
    identities = [(run["run_dir"], _pair_contract(run)) for run in runs]
    seen: set[tuple[tuple[Any, ...], str]] = set()
    for run_dir, contract in identities:
        optimizer = next(
            run["optimizer"] for run in runs if run["run_dir"] == run_dir
        )
        key = (contract, optimizer)
        if key in seen:
            raise ValueError(f"duplicate optimizer/contract run: {run_dir}")
        seen.add(key)

    grouped: dict[tuple[Any, ...], dict[str, dict[str, Any]]] = defaultdict(dict)
    for run in runs:
        grouped[_pair_contract(run)][run["optimizer"]] = run
    incomplete_pairs: list[dict[str, Any]] = []
    paired_rows: list[dict[str, Any]] = []
    for contract, arms in grouped.items():
        if set(arms) != {"ea", "random_search"}:
            incomplete_pairs.append(
                {
                    "model": contract[0],
                    "language": contract[1],
                    "seed": contract[2],
                    "present_optimizers": sorted(arms),
                    "missing_optimizers": sorted(
                        {"ea", "random_search"} - set(arms)
                    ),
                }
            )
            continue
        paired_rows.append(_paired_row(contract, arms))
    if incomplete_pairs and not allow_diagnostic:
        descriptions = [
            f"{row['model']}/{row['language']}/seed={row['seed']} "
            f"missing {','.join(row['missing_optimizers'])}"
            for row in incomplete_pairs
        ]
        raise ValueError(
            "final analysis requires complete EA/random-search pairs: "
            + "; ".join(descriptions)
        )

    by_stratum: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for run in runs:
        by_stratum[(run["model"], run["language"])].append(run)
    strata: list[dict[str, Any]] = []
    for stratum_index, ((model, language), stratum_runs) in enumerate(
        sorted(by_stratum.items())
    ):
        condition_contracts = {
            _condition_contract(run) for run in stratum_runs
        }
        if len(condition_contracts) != 1:
            raise ValueError(
                f"{model}/{language}: mixed experimental conditions cannot "
                "be pooled in one model/language stratum"
            )
        stratum_pairs = [
            row
            for row in paired_rows
            if row["model"] == model and row["language"] == language
        ]
        pair_seeds = [int(row["seed"]) for row in stratum_pairs]
        if len(pair_seeds) != len(set(pair_seeds)):
            raise ValueError(
                f"{model}/{language}: a seed appears in more than one matched pair"
            )
        deltas = [
            float(row["best_f1_difference_ea_minus_random"])
            for row in stratum_pairs
        ]
        runs_by_arm_seed = {
            (str(run["optimizer"]), int(run["seed"])): run
            for run in stratum_runs
        }
        random_values = [
            float(runs_by_arm_seed[("random_search", int(row["seed"]))]["best_f1"])
            for row in stratum_pairs
        ]
        ea_values = [
            float(runs_by_arm_seed[("ea", int(row["seed"]))]["best_f1"])
            for row in stratum_pairs
        ]
        stratum_seed = bootstrap_seed + (stratum_index + 1) * 10_000
        strata.append(
            {
                "model": model,
                "language": language,
                "condition_contract": stratum_runs[0]["condition_contract"],
                "paired_runs": stratum_pairs,
                "arm_summary": _arm_summary(
                    stratum_runs,
                    bootstrap_seed=stratum_seed,
                    bootstrap_samples=bootstrap_samples,
                ),
                "paired_best_f1_difference": _summarize(
                    deltas,
                    seed=stratum_seed + 1_000,
                    samples=bootstrap_samples,
                ),
                "paired_tests": {
                    "sign_test": _test_result(sign_test(deltas)),
                    "wilcoxon_signed_rank": _test_result(
                        wilcoxon_paired(random_values, ea_values)
                    ),
                },
                "curves": _curves(
                    stratum_runs,
                    time_step_seconds=time_step_seconds,
                    seed=stratum_seed,
                    samples=bootstrap_samples,
                ),
            }
        )

    return {
        "artifact_type": "search_analysis",
        "analysis_policy": {
            "primary_budget": "equal_scheduler_wall_time",
            "wall_time_budget_seconds": (
                wall_time_budgets[0]
                if len(wall_time_budgets) == 1
                else wall_time_budgets
            ),
            "primary_endpoint": "best_f1_at_termination",
            "secondary_axes": [
                "completed_main_loop_evaluations",
                "elapsed_main_loop_seconds",
            ],
            "initialization": "five shared precomputed candidates outside main loop",
            "inference_unit": "matched seed within model/language",
            "stratification": "model x language",
            "pooled_results": "descriptive only; no pooled inferential claim",
            "incomplete_pair_policy": (
                "reported for diagnostics"
                if allow_diagnostic
                else "rejected"
            ),
            "bootstrap_samples": bootstrap_samples,
            "bootstrap_seed": bootstrap_seed,
            "time_curve_step_seconds": time_step_seconds,
            "diagnostic_runs_allowed": allow_diagnostic,
        },
        "runs": [{key: value for key, value in run.items() if key != "points"} for run in runs],
        "descriptive_overall_arm_summary": _arm_summary(
            runs,
            bootstrap_seed=bootstrap_seed,
            bootstrap_samples=bootstrap_samples,
        ),
        "paired_runs": paired_rows,
        "incomplete_pairs": incomplete_pairs,
        "strata": strata,
    }


def _write_markdown(result: dict[str, Any], path: Path) -> None:
    wall_time = result["analysis_policy"]["wall_time_budget_seconds"]
    wall_time_text = (
        f"{wall_time:,} seconds"
        if isinstance(wall_time, int)
        else f"the recorded diagnostic allocations {wall_time}"
    )
    lines = [
        "# Search analysis",
        "",
        "Primary comparison: best raw-finding reduction (f1) after an equal "
        f"scheduler allocation of {wall_time_text}. Evaluation-count and elapsed-search "
        "curves are secondary diagnostics.",
        "",
        "Inferential comparisons use matched seeds and are reported separately "
        "for each model and language.",
        "",
        "## Descriptive overall summary",
        "",
        "The following values pool models and languages for orientation only; "
        "they are not an inferential comparison.",
        "",
        "| Optimizer | Runs | Mean best f1 | Median best f1 | "
        "Mean main-loop evaluations |",
        "|---|---:|---:|---:|---:|",
    ]
    for optimizer, summary in result["descriptive_overall_arm_summary"].items():
        best = summary["best_f1"]
        evaluations = summary["completed_main_loop_evaluations"]
        lines.append(
            f"| {optimizer} | {best['n']} | {best['mean']:.3f} | "
            f"{best['median']:.3f} | {evaluations['mean']:.1f} |"
        )
    for stratum in result["strata"]:
        paired = stratum["paired_best_f1_difference"]
        sign = stratum["paired_tests"]["sign_test"]
        wilcoxon = stratum["paired_tests"]["wilcoxon_signed_rank"]
        lines.extend(
            [
                "",
                f"## {stratum['model']} — {stratum['language']}",
                "",
                "Paired EA − random-search best-f1 difference: "
                f"n={paired['n']}, mean={paired['mean']}, "
                f"95% bootstrap CI={paired['mean_bootstrap_95_ci']}.",
                "",
                f"Sign test: statistic={sign['statistic']}, p={sign['p']}"
                + (f" ({sign['note']})" if sign["note"] else "")
                + ".",
                "",
                "Wilcoxon signed-rank: "
                f"statistic={wilcoxon['statistic']}, p={wilcoxon['p']}"
                + (f" ({wilcoxon['note']})" if wilcoxon["note"] else "")
                + ".",
            ]
        )
    if result["incomplete_pairs"]:
        lines.extend(
            [
                "",
                "## Diagnostic incomplete pairs",
                "",
                f"{len(result['incomplete_pairs'])} unmatched run(s) were "
                "excluded from paired inference.",
            ]
        )
    lines.extend(
        [
            "",
            "Machine-readable stratified curves and run-level provenance are "
            "in `search_analysis.json`.",
            "",
        ]
    )
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_dirs", nargs="+", type=Path)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--allow-diagnostic", action="store_true")
    parser.add_argument("--bootstrap-samples", type=int, default=5_000)
    parser.add_argument("--bootstrap-seed", type=int, default=42)
    parser.add_argument("--time-step-seconds", type=int, default=3_600)
    args = parser.parse_args()
    if args.bootstrap_samples < 1 or args.time_step_seconds < 1:
        parser.error("bootstrap samples and time step must be positive")
    try:
        result = analyze(
            args.run_dirs,
            allow_diagnostic=args.allow_diagnostic,
            bootstrap_samples=args.bootstrap_samples,
            bootstrap_seed=args.bootstrap_seed,
            time_step_seconds=args.time_step_seconds,
        )
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
        print(f"analysis failed: {exc}", file=sys.stderr)
        return 1
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "search_analysis.json").write_text(
        json.dumps(result, indent=2) + "\n",
        encoding="utf-8",
    )
    _write_markdown(result, args.output_dir / "search_analysis.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
