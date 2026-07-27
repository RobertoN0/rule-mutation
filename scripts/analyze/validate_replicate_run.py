#!/usr/bin/env python3
"""Reconcile one final temperature>0 replicate-run directory."""

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
from src.evaluation.generation_contract import prompt_contract_sha256  # noqa: E402
from src.evaluation.population_screening import (  # noqa: E402
    FINAL_SEARCH_POPULATION_POLICY,
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
    "semgrep_parse_error",
    "semgrep_target_error",
}


def _json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path}: expected a JSON object")
    return payload


def _jsonl(path: Path) -> list[dict[str, Any]]:
    rows = []
    with path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            payload = json.loads(line)
            if not isinstance(payload, dict):
                raise ValueError(f"{path}:{line_number}: expected a JSON object")
            rows.append(payload)
    return rows


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _jsonl_tree_sha256(directory: Path) -> str | None:
    paths = sorted(directory.glob("*.jsonl"))
    if not paths:
        return None
    digest = hashlib.sha256()
    for path in paths:
        digest.update(path.name.encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def _resolve_source_map(
    recorded: object,
    expected_sha256: object,
    *,
    map_root: Path | None = None,
) -> Path:
    recorded_path = Path(str(recorded))
    candidates = [recorded_path]
    if not recorded_path.is_absolute():
        candidates.append(PROJECT_ROOT / recorded_path)
    candidates.append(PROJECT_ROOT / "rule_maps" / recorded_path.name)
    candidates.append(PROJECT_ROOT / "rule_maps" / "qualified" / recorded_path.name)
    if map_root is not None:
        candidates.append(map_root / recorded_path.name)
    unique_candidates = list(dict.fromkeys(path.resolve() for path in candidates))
    for candidate in unique_candidates:
        if candidate.is_file() and _sha256(candidate) == expected_sha256:
            return candidate
    for candidate in unique_candidates:
        if candidate.is_file():
            return candidate
    return unique_candidates[0]


def _close(first: Any, second: Any) -> bool:
    return isinstance(first, (int, float)) and isinstance(second, (int, float)) and math.isclose(
        float(first), float(second), rel_tol=1e-9, abs_tol=1e-9
    )


def _debug_counts(path: Path) -> tuple[int, int]:
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


def validate_replicate_run(
    run_dir: Path,
    *,
    map_root: Path | None = None,
) -> dict[str, Any]:
    run_dir = run_dir.resolve()
    issues: list[str] = []
    warnings: list[str] = []
    invalid_statuses: Counter[str] = Counter()
    try:
        config = _json(run_dir / "run_config.json")
        args = config.get("args") if isinstance(config.get("args"), dict) else {}
        if config.get("artifact_type") != "replicate_run_config":
            issues.append("run_config is not a final replicate-run contract")
        if re.fullmatch(
            r"[0-9a-fA-F]{40}",
            str(config.get("git_commit_sha", "")),
        ) is None:
            issues.append("replicate run lacks an exact Git commit")
        if args.get("run_mode") != "replicate":
            issues.append("run_config does not declare replicate mode")
        if re.fullmatch(
            r"[0-9a-fA-F]{40}",
            str(args.get("model_revision", "")),
        ) is None:
            issues.append("replicate run lacks an exact model revision")
        for package_key in ("torch_version", "transformers_version"):
            if not isinstance(args.get(package_key), str) or not args[package_key]:
                issues.append(f"replicate run lacks {package_key}")
        if args.get("prompt_contract_sha256") != prompt_contract_sha256():
            issues.append("replicate prompt-contract hash does not match the active contract")
        if args.get("max_output_tokens") != 4096:
            issues.append("replicate run did not use the fixed 4096-token cap")
        if args.get("invalid_output_policy") != "missing_not_zero_with_explicit_denominator":
            issues.append("replicate run does not declare the missing-output policy")
        if args.get("semgrep_version") != "1.85.0":
            issues.append("replicate run did not use Semgrep 1.85.0")
        if args.get("semgrep_rule_config_kind") != "local":
            issues.append("replicate run did not use local Semgrep rules")
        if re.fullmatch(
            r"[0-9a-fA-F]{40}", str(args.get("semgrep_rules_source_commit", ""))
        ) is None:
            issues.append("replicate run lacks a pinned Semgrep SOURCE_COMMIT")
        if re.fullmatch(r"[0-9a-f]{64}", str(args.get("semgrep_rules_sha256", ""))) is None:
            issues.append("replicate run lacks a Semgrep rule-content hash")

        map_path = _resolve_source_map(
            args.get("rules_map", ""),
            args.get("rules_map_sha256"),
            map_root=map_root,
        )
        if not map_path.is_file():
            issues.append(f"rules map is unavailable: {map_path}")
            map_payload: dict[str, Any] = {}
        else:
            map_payload = _json(map_path)
            if _sha256(map_path) != args.get("rules_map_sha256"):
                issues.append("rules-map hash differs from run_config")
        qualification = map_payload.get("metadata", {}).get("search_qualification", {})
        if not args.get("allow_unqualified_map"):
            if args.get("population_policy") != FINAL_SEARCH_POPULATION_POLICY:
                issues.append("replicate run did not use a frozen qualified map")
            if args.get("population_evidence_status") != "final":
                issues.append("replicate map is not backed by final qualification evidence")
            if qualification.get("policy") != args.get("population_policy"):
                issues.append("map population policy differs from run_config")
            if qualification.get("evidence_status") != args.get(
                "population_evidence_status"
            ):
                issues.append("map evidence status differs from run_config")
            if qualification.get("qualified_population_fingerprint") != args.get(
                "population_fingerprint"
            ):
                issues.append("map population fingerprint differs from run_config")
            if qualification.get("prompt_contract_sha256") != args.get(
                "prompt_contract_sha256"
            ):
                issues.append("map prompt contract differs from replicate run")
        override_path_value = args.get("rules_override_dir")
        if override_path_value is not None:
            override_dir = Path(str(override_path_value))
            if not override_dir.is_absolute():
                override_dir = (PROJECT_ROOT / override_dir).resolve()
            if not override_dir.is_dir():
                issues.append(f"rules override directory is unavailable: {override_dir}")
            else:
                digest = hashlib.sha256()
                for path in sorted(override_dir.glob("*.md")):
                    digest.update(path.name.encode("utf-8"))
                    digest.update(b"\0")
                    digest.update(path.read_bytes())
                    digest.update(b"\0")
                if digest.hexdigest() != args.get("rules_override_sha256"):
                    issues.append("rules-override hash differs from run_config")

        replicate_path = run_dir / "replicates.jsonl"
        replicates = _jsonl(replicate_path)
        seeds = [row.get("seed") for row in replicates]
        if len(seeds) != len(set(seeds)):
            issues.append("replicates.jsonl contains duplicate seeds")
        expected_condition = args.get("condition")
        expected_cases = args.get("n_cases")
        expected_language = (args.get("languages") or [None])[0]
        expected_model = args.get("model")
        expected_temperature = args.get("temperature")
        expected_debug_records = 0

        for replicate in replicates:
            seed = replicate.get("seed")
            label = f"seed {seed}"
            if replicate.get("artifact_type") != "replicate_evaluation":
                issues.append(f"{label}: wrong replicate artifact type")
            identity_checks = {
                "condition": expected_condition,
                "model": expected_model,
                "language": expected_language,
                "temperature": expected_temperature,
                "n_cases": expected_cases,
            }
            for key, expected in identity_checks.items():
                if replicate.get(key) != expected:
                    issues.append(f"{label}: {key} differs from run_config")
            n_valid = replicate.get("n_valid_outputs")
            n_invalid = replicate.get("invalid_outputs")
            if not isinstance(n_valid, int) or not isinstance(n_invalid, int):
                issues.append(f"{label}: invalid valid/invalid output counts")
                continue
            if n_valid + n_invalid != expected_cases:
                issues.append(f"{label}: valid + invalid outputs does not equal n_cases")
            expected_debug_records += expected_cases

            relative_intermediate = replicate.get("intermediate_file")
            if not isinstance(relative_intermediate, str):
                issues.append(f"{label}: missing intermediate_file")
                continue
            intermediate_path = (run_dir / relative_intermediate).resolve()
            if run_dir not in intermediate_path.parents:
                issues.append(f"{label}: intermediate path escapes run directory")
                continue
            rows = _jsonl(intermediate_path)
            if len(rows) != expected_cases:
                issues.append(f"{label}: intermediate row count differs from n_cases")
            task_ids = [str(row.get("test_case_id")) for row in rows]
            if len(task_ids) != len(set(task_ids)):
                issues.append(f"{label}: duplicate task IDs in intermediate rows")

            valid_rows = []
            invalid_counts: Counter[str] = Counter()
            for row in rows:
                if row.get("artifact_type") != "replicate_task_evaluation":
                    issues.append(
                        f"{label} task {row.get('test_case_id')}: wrong artifact type"
                    )
                status = str(row.get("qualification_status"))
                fitness = row.get("fitness")
                if status != "valid" and status not in PROMPT_ERROR_KINDS:
                    issues.append(
                        f"{label} task {row.get('test_case_id')}: unknown status {status}"
                    )
                output_validation = row.get("output_validation")
                if not isinstance(output_validation, dict):
                    issues.append(
                        f"{label} task {row.get('test_case_id')}: missing output validation"
                    )
                else:
                    recomputed = validate_generated_output(
                        str(row.get("generated_code", "")),
                        expected_language=str(row.get("analysis_language", "")),
                        finish_reason=str(row.get("finish_reason", "unknown")),
                    )
                    expected_status = (
                        status if status.startswith("semgrep_") else recomputed.status
                    )
                    if status.startswith("semgrep_") and not recomputed.is_valid:
                        issues.append(
                            f"{label} task {row.get('test_case_id')}: Semgrep status "
                            "masks an output-validation failure"
                        )
                    if status != expected_status:
                        issues.append(
                            f"{label} task {row.get('test_case_id')}: output status "
                            "does not reproduce"
                        )
                    source_hash = hashlib.sha256(
                        recomputed.source_code.encode("utf-8")
                    ).hexdigest()
                    analyzed_hash = hashlib.sha256(
                        recomputed.code.encode("utf-8")
                    ).hexdigest()
                    provenance_checks = {
                        "source_code_sha256": source_hash,
                        "analyzed_code_sha256": analyzed_hash,
                    }
                    for key, expected in provenance_checks.items():
                        if row.get(key) != expected:
                            issues.append(
                                f"{label} task {row.get('test_case_id')}: {key} "
                                "does not reconcile"
                            )
                    if output_validation.get("normalization") != recomputed.normalization:
                        issues.append(
                            f"{label} task {row.get('test_case_id')}: normalization "
                            "does not reconcile"
                        )
                    if output_validation.get("analysis_line_map") != recomputed.analysis_line_map:
                        issues.append(
                            f"{label} task {row.get('test_case_id')}: line map "
                            "does not reconcile"
                        )
                if status == "valid":
                    if not isinstance(fitness, dict):
                        issues.append(f"{label} task {row.get('test_case_id')}: valid row has no score")
                    else:
                        valid_rows.append(row)
                else:
                    invalid_counts[status] += 1
                    invalid_statuses[status] += 1
                    if fitness is not None:
                        issues.append(
                            f"{label} task {row.get('test_case_id')}: invalid row was scored"
                        )
            if len(valid_rows) != n_valid or sum(invalid_counts.values()) != n_invalid:
                issues.append(f"{label}: intermediate validity counts do not reconcile")
            if replicate.get("invalid_output_counts") != dict(sorted(invalid_counts.items())):
                issues.append(f"{label}: invalid-output reason counts do not reconcile")

            raw = sum(row["fitness"]["raw_count"] for row in valid_rows)
            weighted = sum(float(row["fitness"]["weighted_score"]) for row in valid_rows)
            vulnerable = sum(row["fitness"]["raw_count"] > 0 for row in valid_rows)
            per_case = {
                str(row["test_case_id"]): row["fitness"]["raw_count"]
                for row in valid_rows
            }
            cases_per_check: Counter[str] = Counter()
            for row in valid_rows:
                for check_id in row["fitness"].get("check_ids", []):
                    cases_per_check[str(check_id).split(".")[-1]] += 1
            expected_values = {
                "raw_findings": raw,
                "weighted_fitness": weighted,
                "vulnerable_cases": vulnerable,
                "raw_findings_per_valid_prompt": raw / n_valid if n_valid else None,
                "weighted_score_per_valid_prompt": weighted / n_valid if n_valid else None,
                "vulnerable_rate_valid": vulnerable / n_valid if n_valid else None,
            }
            for key, expected in expected_values.items():
                actual = replicate.get(key)
                if expected is None:
                    if actual is not None:
                        issues.append(f"{label}: {key} should be null with no valid outputs")
                elif not _close(actual, expected):
                    issues.append(f"{label}: {key} does not reconcile")
            if replicate.get("per_case_raw") != per_case:
                issues.append(f"{label}: per_case_raw does not reconcile")
            if replicate.get("cases_per_check_id") != dict(cases_per_check):
                issues.append(f"{label}: cases_per_check_id does not reconcile")
            expected_scope = "full_population" if n_invalid == 0 else "valid_outputs_only"
            if replicate.get("raw_findings_scope") != expected_scope:
                issues.append(f"{label}: raw-findings scope is incorrect")
            expected_complete = raw if n_invalid == 0 else None
            if replicate.get("raw_findings_complete_population") != expected_complete:
                issues.append(f"{label}: full-population raw count is incorrectly populated")

        requested_seeds = set(args.get("seeds") or [])
        completed_seeds = set(seeds)
        if not completed_seeds <= requested_seeds:
            issues.append("completed replicate seeds are not a subset of requested seeds")
        if completed_seeds != requested_seeds:
            warnings.append(
                f"partial seed set: completed {len(completed_seeds)}/{len(requested_seeds)}"
            )

        debug_path = run_dir / "semgrep_debug" / "semgrep_debug.jsonl"
        debug_records, debug_system_errors = _debug_counts(debug_path)
        if debug_records < expected_debug_records:
            issues.append(
                f"Semgrep debug has {debug_records} records for {expected_debug_records} prompts"
            )
        if debug_system_errors:
            warnings.append(
                f"Semgrep debug contains {debug_system_errors} transient/system retry records"
            )

        full_frozen_population = args.get("full_frozen_population") is True
        if full_frozen_population:
            if args.get("evaluated_population_fingerprint") != args.get(
                "population_fingerprint"
            ):
                issues.append("evaluated and frozen population fingerprints differ")
        elif not args.get("allow_unqualified_map"):
            warnings.append("run is a diagnostic subset/override, not a full frozen baseline")
        summary = _json(run_dir / "replicate_summary.json")
        if summary.get("artifact_type") != "replicate_summary":
            issues.append("replicate summary has the wrong artifact type")
        if summary.get("condition") != args.get("condition"):
            issues.append("replicate summary condition differs from run_config")
        summary_identity = {
            "model": args.get("model"),
            "language": expected_language,
            "temperature": expected_temperature,
            "n_cases": expected_cases if replicates else None,
        }
        for key, expected in summary_identity.items():
            if summary.get(key) != expected:
                issues.append(f"replicate summary {key} differs from evidence")
        metrics = summary.get("metrics")
        if not isinstance(metrics, dict):
            issues.append("replicate summary metrics are missing")
        else:
            if metrics.get("n") != len(replicates):
                issues.append("replicate summary count differs from evidence")
            if metrics.get("seeds") != sorted(seeds):
                issues.append("replicate summary seeds differ from evidence")
    except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
        issues.append(str(exc))

    seed_complete = set(locals().get("seeds", [])) == set(
        locals().get("requested_seeds", set())
    )
    artifact_sha256 = {
        name: (_sha256(path) if path.is_file() else None)
        for name, path in {
            "run_config": run_dir / "run_config.json",
            "replicates": run_dir / "replicates.jsonl",
            "replicate_summary": run_dir / "replicate_summary.json",
            "semgrep_debug": (
                run_dir / "semgrep_debug" / "semgrep_debug.jsonl"
            ),
        }.items()
    }
    artifact_sha256["intermediate_jsonl_tree"] = _jsonl_tree_sha256(
        run_dir / "intermediate"
    )
    return {
        "artifact_type": "replicate_run_validation",
        "run_dir": str(run_dir),
        "status": "VALID" if not issues else "INVALID",
        "issues": issues,
        "warnings": warnings,
        "final_baseline_eligible": (
            not issues
            and bool(locals().get("full_frozen_population"))
            and seed_complete
            and not bool(locals().get("args", {}).get("allow_unqualified_map"))
            and locals().get("args", {}).get("condition") in {"norules", "withrules"}
            and locals().get("args", {}).get("rules_override_dir") is None
        ),
        "final_replicate_eligible": (
            not issues
            and bool(locals().get("full_frozen_population"))
            and seed_complete
            and not bool(locals().get("args", {}).get("allow_unqualified_map"))
        ),
        "counts": {
            "replicates": len(locals().get("replicates", [])),
            "requested_seeds": len(locals().get("requested_seeds", set())),
            "semgrep_debug_records": locals().get("debug_records", 0),
            "invalid_statuses": dict(invalid_statuses),
        },
        "artifact_sha256": artifact_sha256,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_dirs", nargs="+", type=Path)
    parser.add_argument(
        "--map-root",
        type=Path,
        help="Directory containing copied rule maps, resolved by filename and hash.",
    )
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()
    failed = 0
    for run_dir in args.run_dirs:
        result = validate_replicate_run(run_dir, map_root=args.map_root)
        print(json.dumps(result, indent=2))
        if args.write:
            (run_dir / "replicate_validation.json").write_text(
                json.dumps(result, indent=2) + "\n", encoding="utf-8"
            )
        failed += result["status"] != "VALID"
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
