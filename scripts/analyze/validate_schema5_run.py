#!/usr/bin/env python3
"""Strict health/reconciliation audit for one or more schema-5 search runs."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
from collections import Counter
from pathlib import Path
from typing import Any


PROMPT_ERROR_KINDS = {
    "input_validation",
    "target_parse",
    "target_analysis",
    "empty_code",
    "empty_output",
    "generation_incomplete",
    "malformed_output",
    "language_drift",
    "multiple_target_blocks",
    "syntax_invalid",
    "vacuous_output",
}


def _json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path}: expected a JSON object")
    return value


def _jsonl(path: Path) -> list[dict[str, Any]]:
    rows = []
    with path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            value = json.loads(line)
            if not isinstance(value, dict):
                raise ValueError(f"{path}:{line_number}: expected a JSON object")
            rows.append(value)
    return rows


def _close(first: float, second: float) -> bool:
    return math.isclose(float(first), float(second), rel_tol=1e-9, abs_tol=1e-6)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _scan_debug(path: Path) -> tuple[int, int]:
    """Count debug records/system errors without loading a multi-GB file."""
    records = 0
    system_errors = 0
    with path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            row = json.loads(line)
            if not isinstance(row, dict):
                raise ValueError(f"{path}:{line_number}: expected a JSON object")
            records += 1
            if row.get("error") and row.get("error_kind") not in PROMPT_ERROR_KINDS:
                system_errors += 1
    return records, system_errors


def _prompt_scores(rows: list[dict[str, Any]], source: Path) -> dict[str, dict[str, Any]]:
    scores: dict[str, dict[str, Any]] = {}
    for row in rows:
        task_id = str(row.get("test_case_id", ""))
        fitness = row.get("fitness")
        if not task_id or not isinstance(fitness, dict):
            raise ValueError(f"{source}: missing task ID or fitness object")
        if task_id in scores:
            raise ValueError(f"{source}: duplicate test_case_id={task_id}")
        raw = fitness.get("raw_count")
        weighted = fitness.get("weighted_score")
        if not isinstance(raw, int) or isinstance(raw, bool) or raw < 0:
            raise ValueError(f"{source}: invalid raw_count for task {task_id}")
        if not isinstance(weighted, (int, float)) or float(weighted) < 0:
            raise ValueError(f"{source}: invalid weighted_score for task {task_id}")
        scores[task_id] = row
    return scores


def validate_run(run_dir: Path) -> dict[str, Any]:
    issues: list[str] = []
    warnings: list[str] = []
    status_counts: Counter[str] = Counter()
    run_dir = run_dir.resolve()

    try:
        config = _json(run_dir / "run_config.json")
        args = config.get("args") if isinstance(config.get("args"), dict) else {}
        if config.get("schema_version") != 5:
            issues.append(f"schema_version={config.get('schema_version')!r}, expected 5")
        if args.get("fitness_strategy") != "raw_count":
            issues.append("run_config does not declare raw_count fitness")
        if args.get("max_output_tokens") != 4096:
            issues.append("run_config does not declare the fixed 4096-token cap")
        if args.get("objective_direction") != "minimize":
            issues.append("only repair-direction runs are supported")
        map_path = Path(str(args.get("rules_map", "")))
        if not map_path.is_absolute():
            map_path = (Path.cwd() / map_path).resolve()
        map_hash = args.get("rules_map_sha256")
        if not isinstance(map_hash, str) or len(map_hash) != 64:
            issues.append("run_config is missing an exact rules-map SHA-256")
        elif map_path.is_file() and _sha256(map_path) != map_hash:
            warnings.append("current rules-map file differs from the map used by this run")
        if args.get("semgrep_version") != "1.85.0":
            issues.append("run_config does not declare the pinned Semgrep 1.85.0")
        if args.get("semgrep_rule_config_kind") != "local":
            issues.append("mutable remote Semgrep rules are not valid for a comparative run")
        rules_hash = args.get("semgrep_rules_sha256")
        if not isinstance(rules_hash, str) or len(rules_hash) != 64:
            issues.append("run_config is missing an exact local Semgrep-rule SHA-256")
        if not isinstance(args.get("semgrep_rule_file_count"), int):
            issues.append("run_config is missing the local Semgrep-rule file count")
        source_commit = args.get("semgrep_rules_source_commit")
        if not isinstance(source_commit, str) or re.fullmatch(
            r"[0-9a-fA-F]{40,64}", source_commit
        ) is None:
            warnings.append(
                "run_config lacks the upstream Semgrep-rules commit; the exact "
                "content SHA-256 still qualifies the run"
            )

        summaries = sorted(run_dir.glob("hillclimb_summary_*.json"))
        if len(summaries) != 1:
            issues.append(f"expected exactly one summary, found {len(summaries)}")
            summary = {}
        else:
            summary = _json(summaries[0])

        baseline_path = run_dir / "intermediate" / "baseline.jsonl"
        baseline_rows = _jsonl(baseline_path)
        baseline = _prompt_scores(baseline_rows, baseline_path)
        if args.get("n_cases") != len(baseline):
            issues.append(
                f"run_config n_cases={args.get('n_cases')!r}, baseline has {len(baseline)}"
            )
        for task_id, row in baseline.items():
            fitness = row["fitness"]
            validation = row.get("output_validation")
            if fitness.get("analysis_status") != "valid" or fitness.get("score_source") != "semgrep":
                issues.append(f"baseline task {task_id} is not a valid direct Semgrep score")
            if not isinstance(validation, dict) or validation.get("status") != "valid":
                issues.append(f"baseline task {task_id} failed output validation")
            if not _close(fitness.get("raw_reduction", float("nan")), 0):
                issues.append(f"baseline task {task_id} raw_reduction is not zero")

        manifest_path = run_dir / "evaluation_manifest.json"
        manifest = _json(manifest_path)
        manifest_rows = manifest.get("prompts") or []
        manifest_ids = {
            str(row.get("test_case_id")) for row in manifest_rows if isinstance(row, dict)
        }
        if manifest_ids != set(baseline):
            issues.append("evaluation_manifest task set differs from baseline")

        baseline_raw = sum(row["fitness"]["raw_count"] for row in baseline.values())
        baseline_weighted = sum(
            float(row["fitness"]["weighted_score"]) for row in baseline.values()
        )
        iterations_path = run_dir / "iterations.jsonl"
        iteration_rows = _jsonl(iterations_path)
        evaluated = [
            row for row in iteration_rows
            if row.get("budget_consumed") is True and isinstance(row.get("f1"), (int, float))
        ]
        fresh_prompt_rows = sum(row.get("eval_cache_hit") is not True for row in baseline_rows)
        candidate_totals: dict[int, tuple[int, float, int]] = {}

        for iteration in evaluated:
            number = iteration.get("iter")
            prefix = "ea" if iteration.get("strategy") == "ea" else "rand"
            path = run_dir / "intermediate" / f"{prefix}_iter{number:04d}.jsonl"
            candidate_rows = _jsonl(path)
            candidate = _prompt_scores(candidate_rows, path)
            if set(candidate) != set(baseline):
                issues.append(f"{path.name}: task set differs from baseline")
                continue
            fresh_prompt_rows += sum(row.get("eval_cache_hit") is not True for row in candidate_rows)
            raw_total = 0
            weighted_total = 0.0
            invalid = 0
            failures: Counter[str] = Counter()
            for task_id, row in candidate.items():
                fitness = row["fitness"]
                status = str(fitness.get("analysis_status") or "")
                status_counts[status] += 1
                raw_total += fitness["raw_count"]
                weighted_total += float(fitness["weighted_score"])
                base_fitness = baseline[task_id]["fitness"]
                expected_prompt_reduction = base_fitness["raw_count"] - fitness["raw_count"]
                if not _close(fitness.get("raw_reduction", float("nan")), expected_prompt_reduction):
                    issues.append(f"{path.name} task {task_id}: raw_reduction does not reconcile")
                if status != "valid":
                    invalid += 1
                    failures[status] += 1
                    if fitness.get("score_source") != "baseline_imputed":
                        issues.append(f"{path.name} task {task_id}: invalid score is not imputed")
                    if (
                        fitness["raw_count"] != base_fitness["raw_count"]
                        or not _close(fitness["weighted_score"], base_fitness["weighted_score"])
                    ):
                        issues.append(f"{path.name} task {task_id}: imputation differs from baseline")
                elif fitness.get("score_source") != "semgrep":
                    issues.append(f"{path.name} task {task_id}: valid score is not direct")

            expected_f1 = baseline_raw - raw_total
            expected_weighted = baseline_weighted - weighted_total
            checks = (
                ("f1", expected_f1),
                ("total_raw_findings", raw_total),
                ("total_weighted_score", weighted_total),
                ("weighted_reduction", expected_weighted),
                ("num_invalid_prompts", invalid),
            )
            for key, expected in checks:
                value = iteration.get(key)
                if not isinstance(value, (int, float)) or not _close(value, expected):
                    issues.append(
                        f"{path.name}: {key}={value!r}, recomputed {expected!r}"
                    )
            if iteration.get("failure_counts") != dict(failures):
                issues.append(f"{path.name}: failure_counts do not reconcile")
            if isinstance(number, int):
                candidate_totals[number] = (raw_total, weighted_total, invalid)

        debug_path = run_dir / "semgrep_debug" / "semgrep_debug.jsonl"
        debug_records, debug_system_errors = _scan_debug(debug_path)
        if debug_records < fresh_prompt_rows:
            issues.append(
                f"Semgrep debug has {debug_records} records for {fresh_prompt_rows} fresh prompts"
            )
        if debug_system_errors:
            warnings.append(
                f"debug contains {debug_system_errors} transient/system error record(s); "
                "completed outputs reconciled, inspect retry history"
            )

        failure_path = run_dir / "evaluation_failures.jsonl"
        if failure_path.exists() and failure_path.stat().st_size:
            issues.append("completed run contains evaluation_failures.jsonl")

        if summary:
            best_f1 = max([0.0] + [float(row["f1"]) for row in evaluated])
            summary_stats = summary.get("pool_arm_stats")
            best_record = (
                summary_stats.get("best_chromosome", {})
                if isinstance(summary_stats, dict)
                else {}
            )
            recorded_best_f1 = best_record.get("f1")
            best_iteration = best_record.get("evaluation_iteration")
            if not isinstance(recorded_best_f1, (int, float)) or not _close(
                recorded_best_f1, best_f1
            ):
                issues.append("persistent best chromosome does not equal maximum evaluated raw f1")
            if best_iteration == 0:
                best_raw, best_weighted, best_invalid = baseline_raw, baseline_weighted, 0
            elif isinstance(best_iteration, int) and best_iteration in candidate_totals:
                best_raw, best_weighted, best_invalid = candidate_totals[best_iteration]
            else:
                best_raw, best_weighted, best_invalid = baseline_raw - best_f1, float("nan"), -1
                issues.append("persistent best chromosome iteration has no candidate artifact")
            summary_checks = (
                ("primary_f1_metric", "raw_semgrep_finding_count"),
                ("original_raw_findings", baseline_raw),
                ("best_raw_findings", best_raw),
                ("raw_findings_reduction", best_f1),
                ("original_weighted_score", baseline_weighted),
                ("best_weighted_score", best_weighted),
                ("weighted_score_reduction", baseline_weighted - best_weighted),
                ("best_num_invalid_prompts", best_invalid),
            )
            for key, expected in summary_checks:
                actual = summary.get(key)
                matches = (
                    _close(actual, expected)
                    if isinstance(expected, (int, float))
                    and isinstance(actual, (int, float))
                    else actual == expected
                )
                if not matches:
                    issues.append(f"summary {key}={summary.get(key)!r}, expected {expected!r}")
            if summary.get("num_iterations_run") != len(evaluated):
                issues.append("summary iteration count does not reconcile")

    except (OSError, ValueError, json.JSONDecodeError, TypeError, KeyError) as exc:
        issues.append(str(exc))

    return {
        "schema_version": 1,
        "run_dir": str(run_dir),
        "status": "VALID" if not issues else "INVALID",
        "issues": issues,
        "warnings": warnings,
        "counts": {
            "baseline_prompts": len(locals().get("baseline", {})),
            "evaluated_candidates": len(locals().get("evaluated", [])),
            "fresh_prompt_evaluations": locals().get("fresh_prompt_rows", 0),
            "semgrep_debug_records": locals().get("debug_records", 0),
            "analysis_statuses": dict(status_counts),
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_dirs", nargs="+", type=Path)
    parser.add_argument(
        "--write",
        action="store_true",
        help="write schema5_validation.json inside each run directory",
    )
    args = parser.parse_args()

    failed = 0
    for run_dir in args.run_dirs:
        result = validate_run(run_dir)
        print(json.dumps(result, indent=2))
        if args.write:
            (run_dir / "schema5_validation.json").write_text(
                json.dumps(result, indent=2), encoding="utf-8"
            )
        failed += result["status"] != "VALID"
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
