"""Unit tests for raw-primary and weighted-diagnostic fitness."""

from dataclasses import dataclass

import pytest

from src.evaluation.fitness import FitnessResult, aggregate_fitness, calculate_fitness


@dataclass
class FakeFinding:
    check_id: str
    message: str = ""
    severity: str = "WARNING"
    line: int = 1


@dataclass
class FakeSemgrepResult:
    findings: list[FakeFinding]
    error: str | None = None


def _make_findings(errors: int = 0, warnings: int = 0, infos: int = 0):
    findings = [FakeFinding(f"error-{i}", severity="ERROR") for i in range(errors)]
    findings += [FakeFinding(f"warning-{i}") for i in range(warnings)]
    findings += [FakeFinding(f"info-{i}", severity="INFO") for i in range(infos)]
    return FakeSemgrepResult(findings)


def test_calculate_fitness_uses_raw_count_and_reports_weighted_score() -> None:
    result = calculate_fitness(_make_findings(errors=2, warnings=3, infos=5))
    assert result.raw_count == 10
    assert result.weighted_score == pytest.approx(9.0)
    assert result.error_count == 2
    assert result.warning_count == 3
    assert result.unique_rules == 10
    assert result.observed_raw_count == 10


def test_unique_rules_are_deduplicated() -> None:
    result = calculate_fitness(
        FakeSemgrepResult(
            [
                FakeFinding("same", severity="ERROR"),
                FakeFinding("same", severity="ERROR"),
                FakeFinding("other"),
            ]
        )
    )
    assert result.raw_count == 3
    assert result.unique_rules == 2
    assert result.weighted_score == 7


def test_failed_semgrep_result_cannot_be_scored_as_zero() -> None:
    with pytest.raises(RuntimeError, match="failed Semgrep"):
        calculate_fitness(FakeSemgrepResult([], error="scanner failed"))


def test_aggregate_uses_raw_count_as_primary_and_weighted_as_diagnostic() -> None:
    results = [
        FitnessResult(3, 7.0, 2, 1, 4, raw_reduction=2, weighted_reduction=4),
        FitnessResult(0, 0.0, 0, 0, 0, raw_reduction=0, weighted_reduction=0),
        FitnessResult(5, 15.0, 3, 5, 0, raw_reduction=-1, weighted_reduction=-3),
    ]
    agg = aggregate_fitness(results, num_prompts_affected=2)
    assert agg.total_fitness == 8
    assert agg.mean_fitness == pytest.approx(8 / 3)
    assert agg.max_fitness == 5
    assert agg.total_raw_count == 8
    assert agg.total_weighted_score == 22
    assert agg.total_raw_reduction == 1
    assert agg.total_weighted_reduction == 1
    assert agg.num_vulnerable == 2
    assert agg.num_prompts_affected == 2


def test_aggregate_counts_imputed_prompt_statuses() -> None:
    valid = FitnessResult(1, 3.0, 1, 1, 0)
    invalid = FitnessResult(
        2,
        4.0,
        1,
        1,
        1,
        score_source="baseline_imputed",
        analysis_status="syntax_invalid",
    )
    agg = aggregate_fitness([valid, invalid])
    assert agg.num_valid_prompts == 1
    assert agg.num_invalid_prompts == 1
    assert agg.failure_counts == {"syntax_invalid": 1}
