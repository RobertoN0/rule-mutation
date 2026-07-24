from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from scripts.analyze import validate_qualification_run
from scripts.analyze.validate_qualification_run import validate_qualification
from src.evaluation.generation_contract import (
    CURRENT_LANGUAGE_COMPLETE,
    prompt_contract_sha256,
)
from src.evaluation.output_validation import validate_generated_output
from src.evaluation.qualification import population_fingerprint, qualify_search_population
from src.evaluation.rule_mapping import PromptWithRules
from src.evaluation.semgrep_runner import SemgrepFinding, SemgrepResult


class _Backend:
    provider_name = "fake"
    model_name = "fake/model"

    def __init__(self):
        self.outputs = iter(["print(eval(user))", "def broken("])

    def generate(self, **_kwargs):
        return SimpleNamespace(
            content=next(self.outputs),
            input_tokens=1,
            output_tokens=1,
            latency_ms=1.0,
            finish_reason="stop",
        )


def test_source_map_resolution_falls_back_to_local_hashed_copy(
    tmp_path: Path,
) -> None:
    project_root = tmp_path / "checkout"
    local_map = project_root / "rule_maps" / "source_map.json"
    local_map.parent.mkdir(parents=True)
    local_map.write_text('{"mappings": []}')
    digest = hashlib.sha256(local_map.read_bytes()).hexdigest()

    with patch.object(validate_qualification_run, "PROJECT_ROOT", project_root):
        resolved = validate_qualification_run._resolve_source_map(
            "/remote/worktree/rule_maps/source_map.json",
            digest,
        )

    assert resolved == local_map


def _prompt(task_id: str) -> PromptWithRules:
    return PromptWithRules(
        prompt=f"task {task_id}",
        language="python",
        cwe_id="CWE-1",
        rule_ids=["r"],
        combined_rules="RULE",
        individual_rules={"r": "RULE"},
        metadata={"test_case_id": task_id, "prompt_hash": f"hash-{task_id}"},
    )


def test_qualification_validator_reconciles_valid_and_excluded_rows(tmp_path: Path) -> None:
    prompts = [_prompt("1"), _prompt("2")]

    def semgrep(samples, **_kwargs):
        return [
            SemgrepResult(
                findings=[SemgrepFinding("demo", "demo", "ERROR", 1)]
            ),
            SemgrepResult(
                error=samples[1].precheck_error,
                error_kind=samples[1].precheck_error_kind,
            ),
        ]

    with patch("src.evaluation.qualification.run_semgrep_batch_dir", side_effect=semgrep):
        qualify_search_population(
            _Backend(),
            prompts,
            output_dir=tmp_path,
            prompt_profile=CURRENT_LANGUAGE_COMPLETE,
        )

    source_map = tmp_path / "source_map.json"
    source_map.write_text(
        json.dumps(
            {
                "metadata": {},
                "mappings": [
                    {
                        "index": int(task_id),
                        "language": "python",
                        "prompt_hash": f"hash-{task_id}",
                    }
                    for task_id in ("1", "2")
                ],
            }
        )
    )
    run_config = {
        "artifact_type": "qualification_run_config",
        "git_commit_sha": "c" * 40,
        "args": {
            "run_mode": "qualification",
            "torch_version": "2.0",
            "transformers_version": "5.0",
            "prompt_profile": CURRENT_LANGUAGE_COMPLETE,
            "prompt_contract_sha256": prompt_contract_sha256(
                CURRENT_LANGUAGE_COMPLETE
            ),
            "temperature": 0.0,
            "max_output_tokens": 4096,
            "n_cases_requested": None,
            "n_cases": 2,
            "selection": "first",
            "languages": ["python"],
            "model": "fake/model",
            "semgrep_rule_config_kind": "local",
            "semgrep_version": "1.85.0",
            "semgrep_rules_source_commit": "a" * 40,
            "semgrep_rules_sha256": "b" * 64,
            "rules_map": str(source_map),
            "rules_map_sha256": hashlib.sha256(source_map.read_bytes()).hexdigest(),
        },
    }
    (tmp_path / "run_config.json").write_text(json.dumps(run_config))

    intermediate = [
        json.loads(line)
        for line in (tmp_path / "intermediate" / "qualification_tasks.jsonl")
        .read_text()
        .splitlines()
    ]
    debug_dir = tmp_path / "semgrep_debug"
    debug_dir.mkdir()
    with (debug_dir / "semgrep_debug.jsonl").open("w") as handle:
        for row in intermediate:
            recomputed = validate_generated_output(
                row["generated_code"],
                expected_language=row["analysis_language"],
                finish_reason=row["finish_reason"],
            )
            handle.write(
                json.dumps(
                    {
                        "code_analyzed": recomputed.code,
                        "findings_count": (
                            row["fitness"]["raw_count"] if row["fitness"] else 0
                        ),
                        "error": row["exclusion_reason"],
                        "error_kind": (
                            row["qualification_status"]
                            if row["qualification_status"] != "valid" else None
                        ),
                    }
                )
                + "\n"
            )

    result = validate_qualification(tmp_path)

    assert result["status"] == "VALID", result["issues"]
    assert result["counts"] == {
        "prompts": 2,
        "valid": 1,
        "excluded": 1,
        "statuses": {"valid": 1, "syntax_invalid": 1},
    }

    prior_attempt = {
        "error": "transient batch timeout",
        "error_kind": "timeout",
        "findings_count": 0,
    }
    debug_path = debug_dir / "semgrep_debug.jsonl"
    debug_path.write_text(
        "\n".join(json.dumps(prior_attempt) for _ in prompts)
        + "\n"
        + debug_path.read_text()
    )
    retried_result = validate_qualification(tmp_path)
    assert retried_result["status"] == "VALID", retried_result["issues"]
    assert any("retry history" in warning for warning in retried_result["warnings"])


def test_qualification_validator_uses_each_rows_normalization(tmp_path: Path) -> None:
    generated = [
        "public void run() { Runtime.getRuntime().exec(cmd); }",
        "class Demo { void run() { Runtime.getRuntime().exec(cmd); } }",
    ]
    rows = []
    debug_rows = []
    for idx, code in enumerate(generated, 1):
        validation = validate_generated_output(
            code,
            expected_language="java",
            finish_reason="stop",
        )
        assert validation.is_valid
        row = {
            "artifact_type": "qualification_task_evaluation",
            "test_case_id": str(idx),
            "analysis_language": "java",
            "prompt_hash": f"hash-{idx}",
            "prompt_profile": CURRENT_LANGUAGE_COMPLETE,
            "system_prompt_sha256": hashlib.sha256(
                f"system-{idx}".encode()
            ).hexdigest(),
            "finish_reason": "stop",
            "generated_code": code,
            "source_code_sha256": hashlib.sha256(
                validation.source_code.encode()
            ).hexdigest(),
            "analyzed_code_sha256": hashlib.sha256(
                validation.code.encode()
            ).hexdigest(),
            "output_validation": {
                "normalization": validation.normalization,
                "target_block_count": validation.target_block_count,
                "analysis_line_map": validation.analysis_line_map,
            },
            "qualification_status": "valid",
            "fitness": {"raw_count": 1},
        }
        rows.append(row)
        debug_rows.append(
            {
                "code_analyzed": validation.code,
                "findings_count": 1,
                "normalization": validation.normalization,
                "analysis_line_map": validation.analysis_line_map,
            }
        )

    source_map = tmp_path / "source_map.json"
    source_map.write_text(
        json.dumps(
            {
                "metadata": {},
                "mappings": [
                    {
                        "index": idx,
                        "language": "java",
                        "prompt_hash": f"hash-{idx}",
                    }
                    for idx in (1, 2)
                ],
            }
        )
    )
    run_config = {
        "artifact_type": "qualification_run_config",
        "git_commit_sha": "c" * 40,
        "args": {
            "run_mode": "qualification",
            "torch_version": "2.0",
            "transformers_version": "5.0",
            "prompt_profile": CURRENT_LANGUAGE_COMPLETE,
            "prompt_contract_sha256": prompt_contract_sha256(
                CURRENT_LANGUAGE_COMPLETE
            ),
            "temperature": 0.0,
            "max_output_tokens": 4096,
            "n_cases_requested": None,
            "n_cases": 2,
            "selection": "first",
            "languages": ["java"],
            "model": "fake/model",
            "semgrep_rule_config_kind": "local",
            "semgrep_version": "1.85.0",
            "semgrep_rules_source_commit": "a" * 40,
            "semgrep_rules_sha256": "b" * 64,
            "rules_map": str(source_map),
            "rules_map_sha256": hashlib.sha256(source_map.read_bytes()).hexdigest(),
        },
    }
    (tmp_path / "run_config.json").write_text(json.dumps(run_config))
    (tmp_path / "qualification_manifest.json").write_text(
        json.dumps(
            {
                "artifact_type": "qualification_manifest",
                "mode": "qualification",
                "status": "COMPLETE",
                "temperature": 0.0,
                "model": "fake/model",
                "analysis_languages": ["java"],
                "prompt_profile": CURRENT_LANGUAGE_COMPLETE,
                "prompt_contract_sha256": prompt_contract_sha256(
                    CURRENT_LANGUAGE_COMPLETE
                ),
                "total_prompts": 2,
                "valid_prompts": 2,
                "excluded_prompts": 0,
                "valid_task_ids": ["1", "2"],
                "qualified_population_fingerprint": population_fingerprint(rows),
            }
        )
    )
    intermediate_dir = tmp_path / "intermediate"
    intermediate_dir.mkdir()
    serialized_rows = "".join(json.dumps(row) + "\n" for row in rows)
    (intermediate_dir / "qualification_tasks.jsonl").write_text(serialized_rows)
    generations = [
        {**row, "artifact_type": "qualification_generation"} for row in rows
    ]
    (tmp_path / "qualification_generations.jsonl").write_text(
        "".join(json.dumps(row) + "\n" for row in generations)
    )
    debug_dir = tmp_path / "semgrep_debug"
    debug_dir.mkdir()
    (debug_dir / "semgrep_debug.jsonl").write_text(
        "".join(json.dumps(row) + "\n" for row in debug_rows)
    )

    result = validate_qualification(tmp_path)

    assert [row["output_validation"]["normalization"] for row in rows] == [
        "java_class_wrapper",
        "none",
    ]
    assert result["status"] == "VALID", result["issues"]
