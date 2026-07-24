#!/usr/bin/env python3
"""Strict health and reconciliation audit for final search-run artifacts."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from src.evaluation.output_validation import validate_generated_output  # noqa: E402
from src.evaluation.generation_contract import (  # noqa: E402
    PROMPT_PROFILES,
    prompt_contract_sha256,
)
from src.optimizer.initialization import (  # noqa: E402
    build_initialization_identity,
    load_initialization_bundle,
)


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


def _completion_state(requested: Any, completed: int) -> str:
    if not isinstance(requested, int) or isinstance(requested, bool) or requested < 0:
        return "unknown"
    if completed == requested:
        return "complete"
    if completed < requested:
        return "partial"
    return "overrun"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _population_fingerprint(rows: list[dict[str, Any]]) -> str:
    identity = [
        {
            "test_case_id": str(row.get("test_case_id")),
            "analysis_language": row.get("analysis_language"),
            "prompt_hash": row.get("prompt_hash"),
        }
        for row in rows
    ]
    payload = json.dumps(identity, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


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


def _check_code_provenance(
    row: dict[str, Any],
    label: str,
    issues: list[str],
) -> None:
    validation = row.get("output_validation")
    if not isinstance(validation, dict):
        issues.append(f"{label}: missing output_validation")
        return
    normalization = validation.get("normalization")
    if normalization not in {"none", "java_class_wrapper", "java_method_wrapper"}:
        issues.append(f"{label}: unknown normalization")
    source_hash = row.get("source_code_sha256")
    analyzed_hash = row.get("analyzed_code_sha256")
    if not isinstance(source_hash, str) or len(source_hash) != 64:
        issues.append(f"{label}: missing source-code hash")
    if not isinstance(analyzed_hash, str) or len(analyzed_hash) != 64:
        issues.append(f"{label}: missing analyzed-code hash")
    if normalization == "none" and source_hash != analyzed_hash:
        issues.append(f"{label}: unnormalized source/analyzed hashes differ")
    try:
        recomputed = validate_generated_output(
            str(row.get("generated_code", "")),
            expected_language=str(
                validation.get("expected_language") or row.get("analysis_language", "")
            ),
            finish_reason=str(
                validation.get("finish_reason") or row.get("finish_reason", "unknown")
            ),
        )
    except (TypeError, ValueError, RuntimeError) as exc:
        issues.append(f"{label}: output validation cannot be reproduced ({exc})")
        return
    recorded_status = validation.get("status")
    if not str(recorded_status).startswith("semgrep_") and recorded_status != recomputed.status:
        issues.append(
            f"{label}: validation status {recorded_status!r} differs from "
            f"recomputed {recomputed.status!r}"
        )
    recomputed_source_hash = hashlib.sha256(
        recomputed.source_code.encode("utf-8")
    ).hexdigest()
    recomputed_analyzed_hash = hashlib.sha256(
        recomputed.code.encode("utf-8")
    ).hexdigest()
    if source_hash != recomputed_source_hash:
        issues.append(f"{label}: source-code hash does not reconcile")
    if analyzed_hash != recomputed_analyzed_hash:
        issues.append(f"{label}: analyzed-code hash does not reconcile")
    if normalization != recomputed.normalization:
        issues.append(f"{label}: normalization does not reconcile")
    if validation.get("target_block_count") != recomputed.target_block_count:
        issues.append(f"{label}: target-block count does not reconcile")
    if validation.get("analysis_line_map") != recomputed.analysis_line_map:
        issues.append(f"{label}: analysis-line map does not reconcile")


def validate_run(run_dir: Path) -> dict[str, Any]:
    issues: list[str] = []
    warnings: list[str] = []
    status_counts: Counter[str] = Counter()
    run_dir = run_dir.resolve()

    try:
        config = _json(run_dir / "run_config.json")
        args = config.get("args") if isinstance(config.get("args"), dict) else {}
        dry_run = bool(args.get("dry_run"))
        if config.get("artifact_type") != "search_run_config":
            issues.append("run_config is not the final search-run contract")
        if re.fullmatch(
            r"[0-9a-fA-F]{40}",
            str(config.get("git_commit_sha", "")),
        ) is None:
            issues.append("run_config lacks an exact Git commit")
        if args.get("run_mode") != "search":
            issues.append("run_config is not a search run")
        if not dry_run and args.get("backend") == "delftblue":
            if re.fullmatch(
                r"[0-9a-fA-F]{40}",
                str(args.get("model_revision", "")),
            ) is None:
                issues.append("run_config lacks an exact local model revision")
        if not isinstance(args.get("torch_version"), str) or not isinstance(
            args.get("transformers_version"),
            str,
        ):
            issues.append("run_config lacks generation-library versions")
        for digest_name in (
            "rule_corpus_sha256",
            "evaluation_population_fingerprint",
        ):
            if re.fullmatch(
                r"[0-9a-f]{64}",
                str(args.get(digest_name, "")),
            ) is None:
                issues.append(f"run_config lacks a valid {digest_name}")
        bundle_path_value = args.get("initialization_bundle")
        loaded_bundle = None
        if bundle_path_value:
            try:
                loaded_bundle = load_initialization_bundle(
                    Path(str(bundle_path_value)),
                    expected_identity=build_initialization_identity(config),
                )
            except (OSError, ValueError, json.JSONDecodeError) as exc:
                issues.append(f"initialization bundle cannot be reconciled: {exc}")
            else:
                if (
                    args.get("initialization_bundle_content_sha256")
                    != loaded_bundle.content_sha256
                ):
                    issues.append("run_config initialization-bundle hash differs")
        profile = args.get("prompt_profile")
        if profile not in PROMPT_PROFILES:
            issues.append("run_config has an unknown prompt profile")
        elif args.get("prompt_contract_sha256") != prompt_contract_sha256(profile):
            issues.append("run_config prompt-contract hash differs from its profile")
        if args.get("fitness_strategy") != "raw_count":
            issues.append("run_config does not declare raw_count fitness")
        if args.get("max_output_tokens") != 4096:
            issues.append("run_config does not declare the fixed 4096-token cap")
        if args.get("objective_direction") != "minimize":
            issues.append("only repair-direction runs are supported")
        wall_time_budget_seconds = args.get("wall_time_budget_seconds")
        pretimeout_lead_seconds = args.get("pretimeout_lead_seconds")
        if wall_time_budget_seconds is not None and (
            not isinstance(wall_time_budget_seconds, int)
            or isinstance(wall_time_budget_seconds, bool)
            or wall_time_budget_seconds < 1
        ):
            issues.append("run_config wall-time budget is invalid")
        if (
            not isinstance(pretimeout_lead_seconds, int)
            or isinstance(pretimeout_lead_seconds, bool)
            or pretimeout_lead_seconds < 1
        ):
            issues.append("run_config pretimeout lead is invalid")
        elif (
            isinstance(wall_time_budget_seconds, int)
            and pretimeout_lead_seconds >= wall_time_budget_seconds
        ):
            issues.append("pretimeout lead is not below the wall-time budget")
        map_path = Path(str(args.get("rules_map", "")))
        if not map_path.is_absolute():
            map_path = (PROJECT_ROOT / map_path).resolve()
        map_hash = args.get("rules_map_sha256")
        if not isinstance(map_hash, str) or len(map_hash) != 64:
            issues.append("run_config is missing an exact rules-map SHA-256")
        elif not map_path.is_file():
            issues.append(f"rules map is unavailable: {map_path}")
        elif map_path.is_file() and _sha256(map_path) != map_hash:
            warnings.append("current rules-map file differs from the map used by this run")
        map_payload = _json(map_path) if map_path.is_file() else {}
        map_qualification = (
            map_payload.get("metadata", {}).get("search_qualification", {})
            if isinstance(map_payload.get("metadata"), dict) else {}
        )
        population_policy = args.get("population_policy")
        population_evidence_status = args.get("population_evidence_status")
        diagnostic_map_override = bool(
            args.get("allow_unqualified_map") or args.get("dry_run")
        )
        if diagnostic_map_override:
            warnings.append("explicit non-final diagnostic used an unqualified map")
        elif population_policy != "frozen_cross_model_temp0_intersection":
            issues.append("search map is not the frozen cross-model temperature-zero population")
        elif population_evidence_status != "final":
            issues.append("search map is not backed by final qualification evidence")
        if isinstance(map_qualification, dict) and map_qualification:
            map_checks = (
                (
                    "population policy",
                    map_qualification.get("policy"),
                    population_policy,
                ),
                (
                    "population fingerprint",
                    map_qualification.get("qualified_population_fingerprint"),
                    args.get("population_fingerprint"),
                ),
                (
                    "population evidence status",
                    map_qualification.get("evidence_status"),
                    population_evidence_status,
                ),
                (
                    "prompt profile",
                    map_qualification.get("prompt_profile"),
                    profile,
                ),
            )
            for label, recorded, current in map_checks:
                if recorded == current:
                    continue
                message = f"run_config {label} differs from current map metadata"
                if diagnostic_map_override:
                    warnings.append(message)
                else:
                    issues.append(message)
        if args.get("semgrep_version") != "1.85.0":
            issues.append("run_config does not declare the pinned Semgrep 1.85.0")
        scanner_provenance_issues: list[str] = []
        if args.get("semgrep_rule_config_kind") != "local":
            scanner_provenance_issues.append(
                "mutable remote Semgrep rules are not valid for a comparative run"
            )
        rules_hash = args.get("semgrep_rules_sha256")
        if not isinstance(rules_hash, str) or len(rules_hash) != 64:
            scanner_provenance_issues.append(
                "run_config is missing an exact local Semgrep-rule SHA-256"
            )
        if not isinstance(args.get("semgrep_rule_file_count"), int):
            scanner_provenance_issues.append(
                "run_config is missing the local Semgrep-rule file count"
            )
        source_commit = args.get("semgrep_rules_source_commit")
        if not isinstance(source_commit, str) or re.fullmatch(
            r"[0-9a-fA-F]{40}", source_commit
        ) is None:
            scanner_provenance_issues.append(
                "run_config lacks the pinned upstream Semgrep-rules commit"
            )
        if dry_run:
            warnings.extend(
                f"dry-run scanner provenance: {message}"
                for message in scanner_provenance_issues
            )
        else:
            issues.extend(scanner_provenance_issues)

        summary_path = run_dir / "search_summary.json"
        if not summary_path.is_file():
            issues.append("search_summary.json is missing")
            summary = {}
        else:
            summary = _json(summary_path)
            if summary.get("artifact_type") != "search_summary":
                issues.append("search_summary has the wrong artifact type")

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
            _check_code_provenance(row, f"baseline task {task_id}", issues)

        manifest_path = run_dir / "evaluation_manifest.json"
        manifest = _json(manifest_path)
        manifest_rows = manifest.get("prompts") or []
        if manifest.get("artifact_type") != "evaluation_population_manifest":
            issues.append("evaluation_manifest has the wrong artifact type")
        if manifest.get("population_size") != len(manifest_rows):
            issues.append("evaluation_manifest population_size does not reconcile")
        manifest_fingerprint = _population_fingerprint(manifest_rows)
        if manifest.get("population_fingerprint") != manifest_fingerprint:
            issues.append("evaluation_manifest population fingerprint does not reconcile")
        if (
            manifest_fingerprint
            != args.get("evaluation_population_fingerprint")
        ):
            issues.append(
                "evaluation_manifest fingerprint differs from the selected run population"
            )
        manifest_ids = {
            str(row.get("test_case_id")) for row in manifest_rows if isinstance(row, dict)
        }
        if manifest_ids != set(baseline):
            issues.append("evaluation_manifest task set differs from baseline")
        map_population_total = (
            map_qualification.get("qualified_population_total")
            if isinstance(map_qualification, dict) else None
        )
        if args.get("n_cases") == map_population_total:
            if manifest_fingerprint != args.get("population_fingerprint"):
                issues.append("full-population evaluation fingerprint differs from frozen map")
        elif not diagnostic_map_override:
            warnings.append(
                "search uses a declared subset of the frozen map; it is diagnostic, not a "
                "full-population final replicate"
            )

        baseline_raw = sum(row["fitness"]["raw_count"] for row in baseline.values())
        baseline_weighted = sum(
            float(row["fitness"]["weighted_score"]) for row in baseline.values()
        )
        evaluations_path = run_dir / "evaluations.jsonl"
        evaluation_rows = _jsonl(evaluations_path)
        evaluated = [
            row for row in evaluation_rows
            if row.get("evaluation_consumed") is True
            and isinstance(row.get("f1"), (int, float))
        ]
        initialization_budget = args.get("initialization_evaluations")
        main_loop_budget = args.get("main_loop_budget")
        requested_candidates = args.get("total_evaluation_budget")
        if initialization_budget != 5:
            issues.append("run_config initialization budget is not five")
        if not isinstance(main_loop_budget, int) or isinstance(main_loop_budget, bool):
            issues.append("run_config main-loop budget is invalid")
        elif requested_candidates != initialization_budget + main_loop_budget:
            issues.append("total evaluation budget is not initialization plus main loop")
        completion_state = _completion_state(requested_candidates, len(evaluated))
        termination_reason = summary.get("termination_reason")
        if termination_reason not in {
            "evaluation_budget_complete",
            "wall_time_limit",
            "rate_limit",
        }:
            issues.append(f"unknown termination reason: {termination_reason!r}")
        if completion_state == "unknown":
            issues.append(f"invalid requested candidate budget: {requested_candidates!r}")
        elif completion_state == "partial":
            if termination_reason == "wall_time_limit":
                warnings.append(
                    f"wall-time run completed {len(evaluated)}/{requested_candidates} "
                    "evaluation-ceiling candidates"
                )
            else:
                warnings.append(
                    f"run completed {len(evaluated)}/{requested_candidates} requested "
                    "candidates without a wall-time termination"
                )
        elif completion_state == "overrun":
            issues.append(
                f"run completed {len(evaluated)} candidates, exceeding requested budget "
                f"{requested_candidates}"
            )
        initialization_state_path = run_dir / "initialization_random_state.json"
        if main_loop_budget == 0 and not bundle_path_value:
            initialization_state = _json(initialization_state_path)
            if initialization_state.get(
                "artifact_type"
            ) != "initialization_random_state":
                issues.append("initialization RNG checkpoint has the wrong artifact type")
            if (
                "runner" not in initialization_state
                or not isinstance(initialization_state.get("runtime"), dict)
            ):
                issues.append("initialization RNG checkpoint is incomplete")
        elif initialization_state_path.exists():
            warnings.append(
                "initialization RNG checkpoint is present outside a bundle-source run"
            )
        evaluation_indices = [row.get("evaluation_index") for row in evaluated]
        if evaluation_indices != list(range(1, len(evaluated) + 1)):
            issues.append("evaluated rows do not have contiguous evaluation indices")
        initialization_rows = [
            row for row in evaluated if row.get("phase") == "initialization"
        ]
        if len(initialization_rows) != min(len(evaluated), 5):
            issues.append("the first five completed evaluations are not initialization")
        for row in evaluated[:5]:
            if row.get("phase") != "initialization" or row.get("main_loop_iteration") is not None:
                issues.append("initialization phase/index contract is inconsistent")
                break
        expected_initialization_source = (
            "precomputed_bundle" if bundle_path_value else None
        )
        if any(
            row.get("initialization_source") != expected_initialization_source
            for row in evaluated[:5]
        ):
            issues.append("initialization-source records differ from run_config")
        main_rows = evaluated[5:]
        if [row.get("main_loop_iteration") for row in main_rows] != list(
            range(1, len(main_rows) + 1)
        ):
            issues.append("main-loop iteration indices are not contiguous after initialization")
        elapsed_main = [row.get("elapsed_main_loop_seconds") for row in main_rows]
        if any(
            not isinstance(value, (int, float)) or isinstance(value, bool)
            for value in elapsed_main
        ):
            issues.append("main-loop rows lack completion-time measurements")
        elif elapsed_main != sorted(elapsed_main):
            issues.append("main-loop completion times are not monotonic")
        fresh_prompt_rows = sum(
            row.get("eval_cache_hit") is not True for row in baseline_rows
        )
        candidate_totals: dict[int, tuple[int, float, int]] = {}

        for evaluation in evaluated:
            number = evaluation.get("evaluation_index")
            path = run_dir / "intermediate" / f"evaluation_{number:04d}.jsonl"
            candidate_rows = _jsonl(path)
            candidate = _prompt_scores(candidate_rows, path)
            if set(candidate) != set(baseline):
                issues.append(f"{path.name}: task set differs from baseline")
                continue
            fresh_prompt_rows += sum(
                row.get("eval_cache_hit") is not True
                and row.get("initialization_source") != "precomputed_bundle"
                for row in candidate_rows
            )
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
                _check_code_provenance(
                    row,
                    f"{path.name} task {task_id}",
                    issues,
                )

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
                value = evaluation.get(key)
                if not isinstance(value, (int, float)) or not _close(value, expected):
                    issues.append(
                        f"{path.name}: {key}={value!r}, recomputed {expected!r}"
                    )
            if evaluation.get("failure_counts") != dict(failures):
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
            if summary.get("initialization_evaluation_budget") != 5:
                issues.append("summary initialization budget differs from five")
            if summary.get("main_loop_evaluation_budget") != main_loop_budget:
                issues.append("summary main-loop budget differs from run_config")
            if summary.get("total_evaluation_budget") != requested_candidates:
                issues.append("summary total budget differs from run_config")
            best_f1 = max([0.0] + [float(row["f1"]) for row in evaluated])
            summary_stats = summary.get("pool_arm_stats")
            best_record = (
                summary_stats.get("best_chromosome", {})
                if isinstance(summary_stats, dict)
                else {}
            )
            recorded_best_f1 = best_record.get("f1")
            best_evaluation = best_record.get("evaluation_index")
            if not isinstance(recorded_best_f1, (int, float)) or not _close(
                recorded_best_f1, best_f1
            ):
                issues.append("persistent best chromosome does not equal maximum evaluated raw f1")
            if best_evaluation == 0:
                best_raw, best_weighted, best_invalid = baseline_raw, baseline_weighted, 0
            elif isinstance(best_evaluation, int) and best_evaluation in candidate_totals:
                best_raw, best_weighted, best_invalid = candidate_totals[best_evaluation]
            else:
                best_raw, best_weighted, best_invalid = baseline_raw - best_f1, float("nan"), -1
                issues.append(
                    "persistent best chromosome evaluation has no candidate artifact"
                )
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
            if summary.get("num_evaluations_completed") != len(evaluated):
                issues.append("summary evaluation count does not reconcile")
            if summary.get("initialization_evaluations_completed") != len(
                initialization_rows
            ):
                issues.append("summary initialization count does not reconcile")
            if summary.get("main_loop_evaluations_completed") != len(main_rows):
                issues.append("summary main-loop count does not reconcile")
            if (
                elapsed_main
                and isinstance(summary.get("main_loop_time_seconds"), (int, float))
                and summary["main_loop_time_seconds"] < elapsed_main[-1]
            ):
                issues.append("summary main-loop time precedes the last completed evaluation")
            summary_stats = summary.get("pool_arm_stats")
            expected_source = (
                "precomputed_bundle" if bundle_path_value else "evaluated_in_run"
            )
            if not isinstance(summary_stats, dict) or summary_stats.get(
                "initialization_source"
            ) != expected_source:
                issues.append("summary initialization source differs from run_config")
            if isinstance(summary_stats, dict) and summary_stats.get(
                "initialization_bundle_content_sha256"
            ) != (
                loaded_bundle.content_sha256
                if loaded_bundle is not None
                else None
            ):
                issues.append("summary initialization-bundle hash does not reconcile")
            code_calls = summary.get("code_generation_llm_calls_actual")
            code_input_tokens = summary.get(
                "code_generation_input_tokens_actual"
            )
            code_output_tokens = summary.get(
                "code_generation_output_tokens_actual"
            )
            for key, value in (
                ("code-generation calls", code_calls),
                ("code-generation input tokens", code_input_tokens),
                ("code-generation output tokens", code_output_tokens),
            ):
                if (
                    not isinstance(value, int)
                    or isinstance(value, bool)
                    or value < 0
                ):
                    issues.append(f"summary {key} is invalid")
            if isinstance(code_calls, int) and code_calls != fresh_prompt_rows:
                issues.append(
                    "actual code-generation call count differs from fresh "
                    "per-task evaluations"
                )
            mutation_usage = summary.get("mutation_llm_usage_actual")
            if not isinstance(mutation_usage, dict):
                issues.append("summary mutation-LLM usage is missing")
                mutation_attempts = 0
            else:
                mutation_attempts = mutation_usage.get("call_attempts")
                if (
                    not isinstance(mutation_attempts, int)
                    or isinstance(mutation_attempts, bool)
                    or mutation_attempts < 0
                ):
                    issues.append("summary mutation-LLM call count is invalid")
                    mutation_attempts = 0
            actual_total = summary.get("total_llm_call_attempts_actual")
            if (
                isinstance(code_calls, int)
                and actual_total != code_calls + mutation_attempts
            ):
                issues.append("summary actual total LLM calls do not reconcile")
            precomputed_usage = summary.get("precomputed_initialization_usage")
            expected_precomputed = (
                loaded_bundle.precomputed_usage
                if loaded_bundle is not None
                else {}
            )
            if precomputed_usage != expected_precomputed:
                issues.append(
                    "summary precomputed LLM usage differs from the "
                    "initialization source"
                )
            precomputed_mutation = (
                expected_precomputed.get("mutation_llm", {})
                if isinstance(expected_precomputed, dict)
                else {}
            )
            expected_logical = (
                actual_total
                + int(expected_precomputed.get("code_generation_calls", 0))
                + int(precomputed_mutation.get("call_attempts", 0))
                if isinstance(actual_total, int)
                and isinstance(expected_precomputed, dict)
                and isinstance(precomputed_mutation, dict)
                else None
            )
            if summary.get("total_llm_call_attempts_logical") != expected_logical:
                issues.append("summary logical total LLM calls do not reconcile")
            if termination_reason == "evaluation_budget_complete" and (
                completion_state != "complete"
            ):
                issues.append("budget-complete termination has a partial evaluation count")
            if termination_reason == "wall_time_limit" and (
                completion_state != "partial"
            ):
                issues.append("wall-time termination did not stop below the evaluation ceiling")
            if termination_reason == "rate_limit":
                issues.append("rate-limited run is not a healthy completed search run")

        snapshots = sorted(
            (run_dir / "archive_snapshots").glob("evaluation_*.json")
        )
        if args.get("optimizer") == "ea":
            if not snapshots:
                issues.append("EA run has no archive snapshot")
            else:
                final_snapshot = _json(snapshots[-1])
                if final_snapshot.get("artifact_type") != "pareto_archive_snapshot":
                    issues.append("final archive snapshot has the wrong artifact type")
                if not final_snapshot.get("chromosomes"):
                    issues.append("final EA archive is empty")

    except (OSError, ValueError, json.JSONDecodeError, TypeError, KeyError) as exc:
        issues.append(str(exc))

    return {
        "artifact_type": "search_run_validation",
        "run_dir": str(run_dir),
        "status": "VALID" if not issues else "INVALID",
        "issues": issues,
        "warnings": warnings,
        "artifact_sha256": {
            name: (_sha256(path) if path.is_file() else None)
            for name, path in {
                "run_config": run_dir / "run_config.json",
                "search_summary": run_dir / "search_summary.json",
                "evaluations": run_dir / "evaluations.jsonl",
                "evaluation_manifest": run_dir / "evaluation_manifest.json",
                "initialization_random_state": (
                    run_dir / "initialization_random_state.json"
                ),
            }.items()
        },
        "completion": {
            "status": locals().get("completion_state", "unknown"),
            "termination_reason": locals().get("termination_reason"),
            "requested_evaluations": locals().get("requested_candidates"),
            "completed_evaluations": len(locals().get("evaluated", [])),
            "fixed_budget_eligible": locals().get("completion_state") == "complete",
            "time_budget_eligible": (
                locals().get("termination_reason") == "wall_time_limit"
                and locals().get("completion_state") == "partial"
                and locals().get("wall_time_budget_seconds") == 86_400
            ),
        },
        "final_search_eligible": (
            not issues
            and not bool(locals().get("diagnostic_map_override", True))
            and locals().get("termination_reason") == "wall_time_limit"
            and locals().get("completion_state") == "partial"
            and len(locals().get("initialization_rows", [])) == 5
            and locals().get("wall_time_budget_seconds") == 86_400
            and locals().get("args", {}).get("n_cases")
            == locals().get("map_population_total")
        ),
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
        help="write search_validation.json inside each run directory",
    )
    args = parser.parse_args()

    failed = 0
    for run_dir in args.run_dirs:
        result = validate_run(run_dir)
        print(json.dumps(result, indent=2))
        if args.write:
            (run_dir / "search_validation.json").write_text(
                json.dumps(result, indent=2), encoding="utf-8"
            )
        failed += result["status"] != "VALID"
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
