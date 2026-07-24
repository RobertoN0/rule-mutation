from __future__ import annotations

import hashlib
import json
from pathlib import Path

from scripts.analyze.validate_replicate_run import validate_replicate_run
from src.evaluation.generation_contract import prompt_contract_sha256
from src.evaluation.output_validation import validate_generated_output


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(row) for row in rows) + "\n")


def _fixture(tmp_path: Path) -> Path:
    fingerprint = "f" * 64
    source_map = tmp_path / "qualified_map.json"
    source_map.write_text(
        json.dumps(
            {
                "metadata": {
                    "search_qualification": {
                        "evidence_status": "final",
                        "policy": "frozen_cross_model_temp0_intersection",
                        "qualified_population_total": 2,
                        "qualified_population_fingerprint": fingerprint,
                        "prompt_profile": "current_language_complete",
                    }
                },
                "mappings": [],
            }
        )
    )
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    run_config = {
        "artifact_type": "replicate_run_config",
        "git_commit_sha": "a" * 40,
        "args": {
            "run_mode": "replicate",
            "model": "model",
            "model_revision": "d" * 40,
            "torch_version": "2.12.0+cu126",
            "transformers_version": "5.9.0",
            "languages": ["python"],
            "temperature": 0.6,
            "condition": "withrules",
            "n_cases": 2,
            "seeds": [42],
            "max_output_tokens": 4096,
            "prompt_profile": "current_language_complete",
            "prompt_contract_sha256": prompt_contract_sha256(
                "current_language_complete"
            ),
            "invalid_output_policy": "missing_not_zero_with_explicit_denominator",
            "rules_map": str(source_map),
            "rules_map_sha256": hashlib.sha256(source_map.read_bytes()).hexdigest(),
            "population_policy": "frozen_cross_model_temp0_intersection",
            "population_evidence_status": "final",
            "population_fingerprint": fingerprint,
            "evaluated_population_fingerprint": fingerprint,
            "full_frozen_population": True,
            "allow_unqualified_map": False,
            "semgrep_version": "1.85.0",
            "semgrep_rule_config_kind": "local",
            "semgrep_rules_source_commit": "b" * 40,
            "semgrep_rules_sha256": "c" * 64,
        },
    }
    (run_dir / "run_config.json").write_text(json.dumps(run_config))
    intermediate_rows = [
        {
            "artifact_type": "replicate_task_evaluation",
            "test_case_id": "1",
            "analysis_language": "python",
            "finish_reason": "stop",
            "generated_code": "print(eval(user))",
            "qualification_status": "valid",
            "fitness": {
                "raw_count": 2,
                "weighted_score": 4.0,
                "check_ids": ["demo.rule"],
            },
        },
        {
            "artifact_type": "replicate_task_evaluation",
            "test_case_id": "2",
            "analysis_language": "python",
            "finish_reason": "stop",
            "generated_code": "def broken(",
            "qualification_status": "syntax_invalid",
            "fitness": None,
        },
    ]
    for row in intermediate_rows:
        validation = validate_generated_output(
            row["generated_code"],
            expected_language=row["analysis_language"],
            finish_reason=row["finish_reason"],
        )
        row["source_code_sha256"] = hashlib.sha256(
            validation.source_code.encode()
        ).hexdigest()
        row["analyzed_code_sha256"] = hashlib.sha256(validation.code.encode()).hexdigest()
        row["output_validation"] = {
            "status": validation.status,
            "normalization": validation.normalization,
            "analysis_line_map": validation.analysis_line_map,
        }
    intermediate_path = run_dir / "intermediate" / "withrules_seed0042.jsonl"
    _write_jsonl(intermediate_path, intermediate_rows)
    replicate = {
        "artifact_type": "replicate_evaluation",
        "condition": "withrules",
        "model": "model",
        "language": "python",
        "seed": 42,
        "temperature": 0.6,
        "n_cases": 2,
        "n_valid_outputs": 1,
        "invalid_outputs": 1,
        "invalid_output_counts": {"syntax_invalid": 1},
        "raw_findings": 2,
        "raw_findings_scope": "valid_outputs_only",
        "raw_findings_complete_population": None,
        "vulnerable_cases": 1,
        "weighted_fitness": 4.0,
        "raw_findings_per_valid_prompt": 2.0,
        "vulnerable_rate_valid": 1.0,
        "weighted_score_per_valid_prompt": 4.0,
        "per_case_raw": {"1": 2},
        "cases_per_check_id": {"rule": 1},
        "intermediate_file": "intermediate/withrules_seed0042.jsonl",
    }
    _write_jsonl(run_dir / "replicates.jsonl", [replicate])
    (run_dir / "replicate_summary.json").write_text(
        json.dumps(
            {
                "artifact_type": "replicate_summary",
                "condition": "withrules",
                "model": "model",
                "language": "python",
                "temperature": 0.6,
                "n_cases": 2,
                "metrics": {"n": 1, "seeds": [42]},
            }
        )
    )
    _write_jsonl(
        run_dir / "semgrep_debug" / "semgrep_debug.jsonl",
        [
            {"error": None, "error_kind": None, "findings_count": 2},
            {
                "error": "Python AST parsing failed",
                "error_kind": "syntax_invalid",
                "findings_count": 0,
            },
        ],
    )
    return run_dir


def test_replicate_validator_accepts_explicit_missing_output(tmp_path: Path) -> None:
    result = validate_replicate_run(_fixture(tmp_path))

    assert result["status"] == "VALID", result["issues"]
    assert result["final_baseline_eligible"]
    assert result["counts"]["invalid_statuses"] == {"syntax_invalid": 1}


def test_replicate_validator_rejects_invalid_output_scored_as_zero(tmp_path: Path) -> None:
    run_dir = _fixture(tmp_path)
    path = run_dir / "intermediate" / "withrules_seed0042.jsonl"
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    rows[1]["fitness"] = {"raw_count": 0, "weighted_score": 0.0, "check_ids": []}
    _write_jsonl(path, rows)

    result = validate_replicate_run(run_dir)

    assert result["status"] == "INVALID"
    assert any("invalid row was scored" in issue for issue in result["issues"])
