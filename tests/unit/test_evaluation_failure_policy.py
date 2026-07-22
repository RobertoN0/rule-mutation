from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from src.evaluation.output_validation import BaselineOutputError
from src.evaluation.rule_mapping import PromptWithRules
from src.evaluation.semgrep_runner import SemgrepFinding, SemgrepResult
from src.optimizer.chromosome import RuleSetSpace
from src.optimizer.engine import EvaluationInfrastructureError, ExperimentEngine, SearchConfig


class _Backend:
    provider_name = "fake"
    model_name = "fake"

    def generate(self, system, messages, **kwargs):
        task = messages[0]["content"]
        mutated = "BAD" in system
        if mutated and "may-fail" in task:
            content = "def broken("
        elif mutated:
            content = "print('candidate clean')"
        else:
            content = "print('baseline vulnerable')"
        return SimpleNamespace(
            content=content,
            input_tokens=10,
            output_tokens=5,
            latency_ms=1.0,
            finish_reason="stop",
        )


def _engine(tmp_path: Path) -> ExperimentEngine:
    mutator = MagicMock()
    mutator.name = "noop"
    mutator.seed = 0
    return ExperimentEngine(
        _Backend(),
        mutator,
        SearchConfig(
            max_iterations=0,
            output_dir=tmp_path,
            verbose=False,
            save_intermediate=True,
        ),
    )


def _prompt(task_id: str, text: str = "may-fail") -> PromptWithRules:
    return PromptWithRules(
        prompt=text,
        language="python",
        cwe_id="CWE-1",
        rule_ids=["r"],
        combined_rules="",
        individual_rules={"r": "RULE"},
        metadata={"test_case_id": task_id},
    )


def _semgrep(samples, **_kwargs):
    results = []
    for sample in samples:
        if sample.precheck_error:
            results.append(
                SemgrepResult(error=sample.precheck_error, error_kind="input_validation")
            )
        else:
            n = 0 if "candidate clean" in sample.code_analyzed else 1
            results.append(
                SemgrepResult(
                    findings=[
                        SemgrepFinding("demo", "demo", "WARNING", 1)
                        for _ in range(n)
                    ]
                )
            )
    return results


def test_invalid_prompt_is_baseline_imputed_without_gating_chromosome(tmp_path: Path) -> None:
    engine = _engine(tmp_path)
    space = RuleSetSpace(["r"], {"r": "RULE"})
    prompts = [_prompt("1", "may-fail"), _prompt("2", "stays-valid")]
    with patch("src.optimizer.engine.run_semgrep_batch_dir", side_effect=_semgrep):
        baseline, *_ = engine._evaluate_chromosome(
            space.origin(), space, prompts, iter_id="baseline"
        )
        child = space.stamp(space.origin().with_gene("r", "RULE BAD", "m"))
        candidate, results, *_ = engine._evaluate_chromosome(
            child, space, prompts, iter_id="candidate"
        )

    assert baseline.total_raw_count == 2
    assert candidate.total_raw_count == 1
    assert candidate.total_raw_reduction == 1
    assert candidate.num_invalid_prompts == 1
    assert candidate.failure_counts == {"syntax_invalid": 1}
    assert results[0].fitness.raw_count == 1
    assert results[0].fitness.score_source == "baseline_imputed"
    assert results[1].fitness.raw_count == 0


def test_map_language_is_fixed_and_candidate_drift_is_imputed(tmp_path: Path) -> None:
    engine = _engine(tmp_path)
    space = RuleSetSpace(["r"], {"r": "RULE"})
    prompt = _prompt("1296")

    outputs = iter([
        "```python\nprint(user)\n```",
        "```javascript\nconst x = eval(user);\n```",
    ])

    def generate(*_args, **_kwargs):
        return SimpleNamespace(
            content=next(outputs), input_tokens=1, output_tokens=1,
            latency_ms=1.0, finish_reason="stop",
        )

    engine.llm.generate = generate
    with patch("src.optimizer.engine.run_semgrep_batch_dir", side_effect=_semgrep):
        engine._evaluate_chromosome(space.origin(), space, [prompt], iter_id="baseline")
        child = space.stamp(space.origin().with_gene("r", "RULE BAD", "m"))
        candidate, results, *_ = engine._evaluate_chromosome(
            child, space, [prompt], iter_id="candidate"
        )

    assert results[0].validation.expected_language == "python"
    assert results[0].validation.status == "language_drift"
    assert candidate.num_invalid_prompts == 1
    assert candidate.total_raw_reduction == 0


def test_wrong_language_baseline_aborts_instead_of_switching_scanner(tmp_path: Path) -> None:
    engine = _engine(tmp_path)
    engine.llm.generate = lambda *_args, **_kwargs: SimpleNamespace(
        content="```javascript\nconst x = 1;\n```",
        input_tokens=1,
        output_tokens=1,
        latency_ms=1.0,
        finish_reason="stop",
    )
    space = RuleSetSpace(["r"], {"r": "RULE"})
    with pytest.raises(BaselineOutputError, match="language_drift"):
        engine._evaluate_chromosome(space.origin(), space, [_prompt("1")], iter_id="baseline")


def test_unsupported_map_language_aborts_before_model_calls(tmp_path: Path) -> None:
    engine = _engine(tmp_path)
    engine.llm.generate = MagicMock()
    prompt = _prompt("1")
    prompt.language = "javascript"
    space = RuleSetSpace(["r"], {"r": "RULE"})

    with pytest.raises(BaselineOutputError, match="no model calls were made"):
        engine._evaluate_chromosome(space.origin(), space, [prompt], iter_id="baseline")

    engine.llm.generate.assert_not_called()


def test_invalid_baseline_aborts_preflight(tmp_path: Path) -> None:
    engine = _engine(tmp_path)
    engine.llm.generate = lambda *_args, **_kwargs: SimpleNamespace(
        content="def broken(", input_tokens=1, output_tokens=1,
        latency_ms=1.0, finish_reason="stop",
    )
    space = RuleSetSpace(["r"], {"r": "RULE"})
    with pytest.raises(BaselineOutputError, match="Baseline preflight failed"):
        engine._evaluate_chromosome(space.origin(), space, [_prompt("1")], iter_id="baseline")
    failures = [
        json.loads(line)
        for line in (tmp_path / "evaluation_failures.jsonl").read_text().splitlines()
    ]
    assert failures[0]["stage"] == "baseline_output_validation"
    assert failures[0]["error_kind"] == "syntax_invalid"
    assert failures[0]["details"]["generated_code"] == "def broken("
    assert failures[-1]["stage"] == "baseline_preflight"
    assert failures[-1]["error_kind"] == "invalid_baseline_output"


def test_system_semgrep_failure_aborts_instead_of_scoring_zero(tmp_path: Path) -> None:
    engine = _engine(tmp_path)
    space = RuleSetSpace(["r"], {"r": "RULE"})
    with patch(
        "src.optimizer.engine.run_semgrep_batch_dir",
        return_value=[SemgrepResult(error="timeout", error_kind="timeout")],
    ):
        with pytest.raises(EvaluationInfrastructureError, match="timeout"):
            engine._evaluate_chromosome(
                space.origin(), space, [_prompt("1")], iter_id="baseline"
            )
    failures = [
        json.loads(line)
        for line in (tmp_path / "evaluation_failures.jsonl").read_text().splitlines()
    ]
    assert failures[-1]["stage"] == "semgrep"
    assert failures[-1]["error_kind"] == "timeout"


def test_raw_count_not_severity_weight_drives_f1(tmp_path: Path) -> None:
    engine = _engine(tmp_path)
    space = RuleSetSpace(["r"], {"r": "RULE"})

    def severity_changes_only(samples, **_kwargs):
        results = []
        for sample in samples:
            severity = "WARNING" if "candidate clean" in sample.code_analyzed else "ERROR"
            results.append(
                SemgrepResult(
                    findings=[SemgrepFinding("demo", "demo", severity, 1)]
                )
            )
        return results

    with patch(
        "src.optimizer.engine.run_semgrep_batch_dir", side_effect=severity_changes_only
    ):
        baseline, *_ = engine._evaluate_chromosome(
            space.origin(), space, [_prompt("1", "stays-valid")], iter_id="baseline"
        )
        child = space.stamp(space.origin().with_gene("r", "RULE BAD", "m"))
        candidate, *_ = engine._evaluate_chromosome(
            child, space, [_prompt("1", "stays-valid")], iter_id="candidate"
        )

    assert baseline.total_raw_count == candidate.total_raw_count == 1
    assert baseline.total_weighted_score == 3
    assert candidate.total_weighted_score == 1
    assert candidate.total_raw_reduction == 0
    assert candidate.total_weighted_reduction == 2


def test_system_prompt_requires_the_map_language(tmp_path: Path) -> None:
    engine = _engine(tmp_path)
    assert "required implementation language is Python" in engine._build_system_prompt("", "python")
    assert "required implementation language is Java" in engine._build_system_prompt("RULE", "java")
