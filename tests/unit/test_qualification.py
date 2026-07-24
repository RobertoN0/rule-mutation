from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from src.evaluation.generation_contract import (
    CURRENT_LANGUAGE_COMPLETE,
    DEFAULT_PROMPT_PROFILE,
    ORIGINAL_NO_LANGUAGE,
    ORIGINAL_WITH_LANGUAGE,
    build_code_generation_system_prompt,
    prompt_contract_sha256,
)
from src.evaluation.qualification import (
    QualificationInfrastructureError,
    qualify_search_population,
)
from src.evaluation.rule_mapping import PromptWithRules
from src.evaluation.semgrep_runner import SemgrepFinding, SemgrepResult


class _Backend:
    provider_name = "fake"
    model_name = "fake/model"

    def __init__(self, outputs: list[str]):
        self._outputs = iter(outputs)

    def generate(self, **_kwargs):
        return SimpleNamespace(
            content=next(self._outputs),
            input_tokens=10,
            output_tokens=5,
            latency_ms=2.0,
            finish_reason="stop",
        )


def _prompt(task_id: str, language: str = "python") -> PromptWithRules:
    return PromptWithRules(
        prompt=f"task {task_id}",
        language=language,
        cwe_id="CWE-1",
        rule_ids=["r"],
        combined_rules="RULE",
        individual_rules={"r": "RULE"},
        metadata={"test_case_id": task_id, "prompt_hash": f"hash-{task_id}"},
    )


def _semgrep(samples, **_kwargs):
    results = []
    for sample in samples:
        if sample.precheck_error is not None:
            results.append(
                SemgrepResult(
                    error=sample.precheck_error,
                    error_kind=sample.precheck_error_kind,
                )
            )
        else:
            results.append(
                SemgrepResult(
                    findings=[SemgrepFinding("demo", "demo", "ERROR", 1)]
                )
            )
    return results


def test_qualification_keeps_valid_scores_and_records_task_exclusion(
    tmp_path: Path,
) -> None:
    backend = _Backend(["print(user)", "def broken("])
    with patch("src.evaluation.qualification.run_semgrep_batch_dir", side_effect=_semgrep):
        summary = qualify_search_population(
            backend,
            [_prompt("1"), _prompt("2")],
            output_dir=tmp_path,
        )

    assert summary.total_prompts == 2
    assert summary.valid_prompts == 1
    assert summary.excluded_prompts == 1
    manifest = json.loads((tmp_path / "qualification_manifest.json").read_text())
    assert manifest["artifact_type"] == "qualification_manifest"
    assert manifest["status"] == "COMPLETE"
    assert manifest["valid_task_ids"] == ["1"]
    assert manifest["excluded"][0]["test_case_id"] == "2"
    assert manifest["excluded"][0]["status"] == "syntax_invalid"
    assert manifest["prompt_profile"] == DEFAULT_PROMPT_PROFILE
    assert manifest["prompt_contract_sha256"] == prompt_contract_sha256(
        DEFAULT_PROMPT_PROFILE
    )

    rows = [
        json.loads(line)
        for line in (tmp_path / "intermediate" / "qualification_tasks.jsonl")
        .read_text()
        .splitlines()
    ]
    assert rows[0]["fitness"]["raw_count"] == 1
    assert rows[0]["artifact_type"] == "qualification_task_evaluation"
    assert rows[0]["prompt_profile"] == DEFAULT_PROMPT_PROFILE
    assert len(rows[0]["system_prompt_sha256"]) == 64
    assert rows[1]["fitness"] is None
    assert rows[1]["qualification_status"] == "syntax_invalid"
    failures = [
        json.loads(line)
        for line in (tmp_path / "evaluation_failures.jsonl").read_text().splitlines()
    ]
    assert len(failures) == 1
    assert failures[0]["stage"] == "task_qualification"
    assert failures[0]["artifact_type"] == "evaluation_failure"
    assert failures[0]["error_kind"] == "syntax_invalid"
    assert failures[0]["test_case_id"] == "2"
    assert failures[0]["fatal"] is False


def test_qualification_feeds_wrapped_java_to_semgrep(tmp_path: Path) -> None:
    backend = _Backend(["public String value() { return user; }"])
    captured = []

    def inspect(samples, **_kwargs):
        captured.extend(samples)
        return [SemgrepResult()]

    with patch("src.evaluation.qualification.run_semgrep_batch_dir", side_effect=inspect):
        summary = qualify_search_population(
            backend,
            [_prompt("1", "java")],
            output_dir=tmp_path,
        )

    assert summary.excluded_prompts == 0
    assert captured[0].normalization == "java_class_wrapper"
    assert "class __SemgrepGenerated__" in captured[0].code_analyzed
    assert captured[0].code_raw == "public String value() { return user; }"


def test_qualification_aborts_on_semgrep_system_failure(tmp_path: Path) -> None:
    backend = _Backend(["print(user)"])
    with patch(
        "src.evaluation.qualification.run_semgrep_batch_dir",
        return_value=[SemgrepResult(error="bad rules", error_kind="semgrep_system")],
    ):
        with pytest.raises(QualificationInfrastructureError, match="bad rules"):
            qualify_search_population(backend, [_prompt("1")], output_dir=tmp_path)


def test_qualification_requires_temperature_zero(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="temperature=0"):
        qualify_search_population(
            _Backend(["print(user)"]),
            [_prompt("1")],
            output_dir=tmp_path,
            temperature=0.6,
        )


@pytest.mark.parametrize(
    ("profile", "has_language", "format_instruction"),
    [
        (
            CURRENT_LANGUAGE_COMPLETE,
            True,
            "Return one complete implementation only",
        ),
        (
            ORIGINAL_NO_LANGUAGE,
            False,
            "Generate only the code requested",
        ),
        (
            ORIGINAL_WITH_LANGUAGE,
            True,
            "Generate only the code requested",
        ),
    ],
)
def test_named_prompt_profiles_are_exact_and_distinct(
    profile: str,
    has_language: bool,
    format_instruction: str,
) -> None:
    prompt = build_code_generation_system_prompt(
        "RULE",
        "python",
        profile=profile,
    )

    assert ("required implementation language is Python" in prompt) is has_language
    assert format_instruction in prompt
    assert "=== CODING GUIDELINES ===" in prompt


def test_qualification_records_selected_prompt_profile(tmp_path: Path) -> None:
    backend = _Backend(["print(user)"])
    with patch("src.evaluation.qualification.run_semgrep_batch_dir", side_effect=_semgrep):
        summary = qualify_search_population(
            backend,
            [_prompt("1")],
            output_dir=tmp_path,
            prompt_profile=ORIGINAL_NO_LANGUAGE,
        )

    row = json.loads(
        (tmp_path / "intermediate" / "qualification_tasks.jsonl")
        .read_text()
        .strip()
    )
    assert summary.prompt_profile == ORIGINAL_NO_LANGUAGE
    assert row["prompt_profile"] == ORIGINAL_NO_LANGUAGE
    assert len(row["system_prompt_sha256"]) == 64
