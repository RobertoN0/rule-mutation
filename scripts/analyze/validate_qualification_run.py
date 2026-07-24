#!/usr/bin/env python3
"""Reconcile one completed temperature-zero qualification run."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from src.evaluation.output_validation import validate_generated_output  # noqa: E402
from src.evaluation.qualification import population_fingerprint  # noqa: E402
from src.evaluation.generation_contract import prompt_contract_sha256  # noqa: E402


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
            row = json.loads(line)
            if not isinstance(row, dict):
                raise ValueError(f"{path}:{line_number}: expected a JSON object")
            rows.append(row)
    return rows


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _text_sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _resolve_source_map(recorded: object, expected_sha256: object) -> Path:
    recorded_path = Path(str(recorded))
    candidates = [recorded_path]
    if not recorded_path.is_absolute():
        candidates.append(PROJECT_ROOT / recorded_path)
    candidates.append(PROJECT_ROOT / "rule_maps" / recorded_path.name)
    unique_candidates = list(dict.fromkeys(path.resolve() for path in candidates))
    for candidate in unique_candidates:
        if candidate.is_file() and _sha256(candidate) == expected_sha256:
            return candidate
    for candidate in unique_candidates:
        if candidate.is_file():
            return candidate
    return unique_candidates[0]


def validate_qualification(run_dir: Path) -> dict[str, Any]:
    run_dir = run_dir.resolve()
    issues: list[str] = []
    warnings: list[str] = []
    status_counts: Counter[str] = Counter()
    try:
        config = _json(run_dir / "run_config.json")
        args = config.get("args") if isinstance(config.get("args"), dict) else {}
        dry_run = bool(args.get("dry_run"))
        if config.get("artifact_type") != "qualification_run_config":
            issues.append("run_config has the wrong artifact_type")
        if re.fullmatch(
            r"[0-9a-fA-F]{40}",
            str(config.get("git_commit_sha", "")),
        ) is None:
            issues.append("qualification lacks an exact code commit")
        if args.get("run_mode") != "qualification":
            issues.append("run_config is not a qualification")
        if not isinstance(args.get("torch_version"), str):
            issues.append("qualification lacks a recorded PyTorch version")
        if not isinstance(args.get("transformers_version"), str):
            issues.append("qualification lacks a recorded Transformers version")
        if (
            args.get("backend") == "delftblue"
            and not args.get("dry_run")
            and re.fullmatch(
                r"[0-9a-fA-F]{40}",
                str(args.get("model_revision", "")),
            ) is None
        ):
            issues.append("DelftBlue qualification lacks an exact model revision")
        if args.get("temperature") != 0.0 or args.get("max_output_tokens") != 4096:
            issues.append("qualification did not use temperature=0 and max_output_tokens=4096")
        if args.get("prompt_contract_sha256") != prompt_contract_sha256():
            issues.append("run_config prompt-contract hash does not reconcile")
        if args.get("n_cases_requested") is not None or args.get("selection") != "first":
            issues.append("qualification did not use the full source map in deterministic order")
        languages = args.get("languages")
        if not isinstance(languages, list) or len(languages) != 1:
            issues.append("qualification must contain exactly one language")
        if args.get("semgrep_rule_config_kind") != "local":
            issues.append("qualification did not use local Semgrep rules")
        if args.get("semgrep_version") != "1.85.0":
            issues.append("qualification did not use Semgrep 1.85.0")
        if re.fullmatch(
            r"[0-9a-fA-F]{40}", str(args.get("semgrep_rules_source_commit", ""))
        ) is None:
            target = warnings if dry_run else issues
            target.append("qualification lacks a pinned Semgrep SOURCE_COMMIT")
        if re.fullmatch(r"[0-9a-f]{64}", str(args.get("semgrep_rules_sha256", ""))) is None:
            target = warnings if dry_run else issues
            target.append("qualification lacks a Semgrep rule-content hash")

        map_path = _resolve_source_map(
            args.get("rules_map", ""),
            args.get("rules_map_sha256"),
        )
        if not map_path.is_file():
            issues.append(f"source map is unavailable: {map_path}")
            source_map = {}
        else:
            source_map = _json(map_path)
            if _sha256(map_path) != args.get("rules_map_sha256"):
                issues.append("source-map hash differs from run_config")

        manifest_path = run_dir / "qualification_manifest.json"
        manifest = _json(manifest_path)
        if manifest.get("artifact_type") != "qualification_manifest":
            issues.append("qualification manifest has the wrong artifact_type")
        if manifest.get("mode") != "qualification":
            issues.append("qualification manifest has the wrong mode")
        if manifest.get("status") != "COMPLETE":
            issues.append("qualification manifest is not COMPLETE")
        if manifest.get("temperature") != 0.0:
            issues.append("qualification manifest temperature is not zero")
        if manifest.get("model") != args.get("model"):
            issues.append("manifest model differs from run_config")
        if manifest.get("analysis_languages") != languages:
            issues.append("manifest language differs from run_config")
        if manifest.get("prompt_contract_sha256") != args.get(
            "prompt_contract_sha256"
        ):
            issues.append("manifest prompt-contract hash differs from run_config")

        rows_path = run_dir / "intermediate" / "qualification_tasks.jsonl"
        rows = _jsonl(rows_path)
        if args.get("n_cases") != len(rows) or manifest.get("total_prompts") != len(rows):
            issues.append("qualification prompt counts do not reconcile")
        source_ids = {
            str(row.get("index")) for row in source_map.get("mappings", [])
        }
        row_ids = [str(row.get("test_case_id")) for row in rows]
        if len(row_ids) != len(set(row_ids)) or set(row_ids) != source_ids:
            issues.append("qualification task IDs do not exactly cover the source map")

        generations_path = run_dir / "qualification_generations.jsonl"
        generations = _jsonl(generations_path)
        if len(generations) != len(rows):
            issues.append("incremental generation log count differs from intermediate rows")
        for idx, (generation, row) in enumerate(zip(generations, rows)):
            if generation.get("artifact_type") != "qualification_generation":
                issues.append(f"generation log record {idx} has the wrong artifact_type")
            if row.get("artifact_type") != "qualification_task_evaluation":
                issues.append(f"qualification row {idx} has the wrong artifact_type")
            comparable = (
                "test_case_id",
                "analysis_language",
                "prompt_hash",
                "system_prompt_sha256",
                "finish_reason",
                "generated_code",
                "source_code_sha256",
                "analyzed_code_sha256",
            )
            if any(generation.get(key) != row.get(key) for key in comparable):
                issues.append(f"generation log record {idx} differs from intermediate row")

        valid_rows = []
        for row in rows:
            task_id = str(row.get("test_case_id"))
            output_validation = row.get("output_validation")
            if not isinstance(output_validation, dict):
                issues.append(f"task {task_id}: missing output_validation")
                continue
            if re.fullmatch(
                r"[0-9a-f]{64}",
                str(row.get("system_prompt_sha256", "")),
            ) is None:
                issues.append(f"task {task_id}: invalid system-prompt hash")
            recomputed = validate_generated_output(
                str(row.get("generated_code", "")),
                expected_language=str(row.get("analysis_language", "")),
                finish_reason=str(row.get("finish_reason", "unknown")),
            )
            status = str(row.get("qualification_status"))
            status_counts[status] += 1
            expected_status = recomputed.status
            if status.startswith("semgrep_"):
                expected_status = status
                if not recomputed.is_valid:
                    issues.append(
                        f"task {task_id}: Semgrep status masks output-validation failure"
                    )
            elif status != expected_status:
                issues.append(
                    f"task {task_id}: recorded status {status} differs from {expected_status}"
                )
            if _text_sha256(recomputed.source_code) != row.get("source_code_sha256"):
                issues.append(f"task {task_id}: source-code hash does not reconcile")
            if _text_sha256(recomputed.code) != row.get("analyzed_code_sha256"):
                issues.append(f"task {task_id}: analyzed-code hash does not reconcile")
            if output_validation.get("normalization") != recomputed.normalization:
                issues.append(f"task {task_id}: normalization does not reconcile")
            if output_validation.get("target_block_count") != recomputed.target_block_count:
                issues.append(f"task {task_id}: target-block count does not reconcile")
            if output_validation.get("analysis_line_map") != recomputed.analysis_line_map:
                issues.append(f"task {task_id}: analysis-line map does not reconcile")
            fitness = row.get("fitness")
            if status == "valid":
                valid_rows.append(row)
                if not isinstance(fitness, dict) or not isinstance(fitness.get("raw_count"), int):
                    issues.append(f"task {task_id}: valid output lacks a direct score")
            elif fitness is not None:
                issues.append(f"task {task_id}: excluded output was assigned a score")

        if manifest.get("valid_prompts") != len(valid_rows):
            issues.append("manifest valid prompt count does not reconcile")
        if manifest.get("excluded_prompts") != len(rows) - len(valid_rows):
            issues.append("manifest excluded prompt count does not reconcile")
        if manifest.get("valid_task_ids") != [row["test_case_id"] for row in valid_rows]:
            issues.append("manifest valid task order differs from intermediate rows")
        fingerprint = population_fingerprint(valid_rows)
        if manifest.get("qualified_population_fingerprint") != fingerprint:
            issues.append("manifest population fingerprint does not reconcile")

        debug_path = run_dir / "semgrep_debug" / "semgrep_debug.jsonl"
        debug_rows = _jsonl(debug_path)
        if len(debug_rows) < len(rows):
            issues.append("Semgrep debug has fewer records than the prompt count")
        elif len(debug_rows) > len(rows):
            warnings.append(
                "Semgrep debug contains retry history; the final complete batch was reconciled"
            )
        final_debug_rows = debug_rows[-len(rows):] if rows else []
        for idx, debug in enumerate(final_debug_rows):
            row = rows[idx]
            output_validation = row.get("output_validation")
            if not isinstance(output_validation, dict):
                issues.append(f"debug record {idx}: output row lacks validation metadata")
                continue
            if debug.get("error") and debug.get("error_kind") not in {
                row.get("qualification_status"),
                "target_parse",
                "target_analysis",
            }:
                issues.append(f"debug record {idx}: unexpected Semgrep error")
            analyzed = debug.get("code_analyzed")
            if isinstance(analyzed, str) and _text_sha256(analyzed) != row.get(
                "analyzed_code_sha256"
            ):
                issues.append(f"debug record {idx}: scanner input hash mismatch")
            if debug.get("normalization") not in {None, output_validation.get("normalization")}:
                issues.append(f"debug record {idx}: normalization differs from output row")
            debug_line_map = debug.get("analysis_line_map")
            if (
                debug_line_map is not None
                and debug_line_map != output_validation.get("analysis_line_map")
            ):
                issues.append(f"debug record {idx}: line map differs from output row")
            if row.get("qualification_status") == "valid" and debug.get(
                "findings_count"
            ) != row.get("fitness", {}).get("raw_count"):
                issues.append(f"debug record {idx}: finding count differs from fitness")

        failure_path = run_dir / "evaluation_failures.jsonl"
        failures = _jsonl(failure_path) if failure_path.exists() else []
        if any(row.get("fatal") is not False for row in failures):
            issues.append("completed qualification contains a fatal evaluation failure")
        nonfatal_ids = {
            str(row.get("test_case_id")) for row in failures if row.get("fatal") is False
        }
        excluded_ids = {
            str(row.get("test_case_id")) for row in rows
            if row.get("qualification_status") != "valid"
        }
        if nonfatal_ids != excluded_ids:
            issues.append("nonfatal failure records differ from excluded prompt IDs")
    except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
        issues.append(str(exc))

    return {
        "artifact_type": "qualification_validation",
        "run_dir": str(run_dir),
        "status": "VALID" if not issues else "INVALID",
        "issues": issues,
        "warnings": warnings,
        "manifest_sha256": (
            _sha256(locals()["manifest_path"])
            if "manifest_path" in locals() and locals()["manifest_path"].is_file()
            else None
        ),
        "artifact_sha256": {
            name: (_sha256(path) if path.is_file() else None)
            for name, path in {
                "run_config": run_dir / "run_config.json",
                "qualification_manifest": run_dir / "qualification_manifest.json",
                "qualification_generations": run_dir / "qualification_generations.jsonl",
                "qualification_tasks": (
                    run_dir / "intermediate" / "qualification_tasks.jsonl"
                ),
                "semgrep_debug": run_dir / "semgrep_debug" / "semgrep_debug.jsonl",
                "evaluation_failures": run_dir / "evaluation_failures.jsonl",
            }.items()
        },
        "counts": {
            "prompts": len(locals().get("rows", [])),
            "valid": len(locals().get("valid_rows", [])),
            "excluded": len(locals().get("rows", [])) - len(locals().get("valid_rows", [])),
            "statuses": dict(status_counts),
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_dirs", nargs="+", type=Path)
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()
    failed = 0
    for run_dir in args.run_dirs:
        result = validate_qualification(run_dir)
        print(json.dumps(result, indent=2))
        if args.write:
            (run_dir / "qualification_validation.json").write_text(
                json.dumps(result, indent=2) + "\n", encoding="utf-8"
            )
        failed += result["status"] != "VALID"
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
