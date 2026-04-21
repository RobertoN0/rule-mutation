"""Topic E — Fitness strategy unit tests (C-E1, C-E2, C-E8).

Validates calculate_fitness, FitnessResult.fitness(strategy), and
aggregate_fitness for all four strategies.
"""

from dataclasses import dataclass

import pytest

from src.evaluation.fitness import (
    AggregatedFitness,
    FitnessResult,
    FitnessStrategy,
    aggregate_fitness,
    calculate_fitness,
)


# ---------------------------------------------------------------------------
# Helpers — lightweight SemgrepFinding / SemgrepResult stand-ins
# ---------------------------------------------------------------------------

@dataclass
class FakeFinding:
    check_id: str
    message: str = ""
    severity: str = "WARNING"
    line: int = 1


@dataclass
class FakeSemgrepResult:
    findings: list[FakeFinding]


def _make_findings(errors: int = 0, warnings: int = 0, infos: int = 0) -> FakeSemgrepResult:
    """Build a fake SemgrepResult with known severity distribution."""
    findings = []
    for i in range(errors):
        findings.append(FakeFinding(check_id=f"error-rule-{i}", severity="ERROR", line=i + 1))
    for i in range(warnings):
        findings.append(FakeFinding(check_id=f"warn-rule-{i}", severity="WARNING", line=100 + i))
    for i in range(infos):
        findings.append(FakeFinding(check_id=f"info-rule-{i}", severity="INFO", line=200 + i))
    return FakeSemgrepResult(findings=findings)


# ═══════════════════════════════════════════════════════════════════════════════
# C-E1  calculate_fitness computes metrics correctly
# ═══════════════════════════════════════════════════════════════════════════════

class TestCalculateFitness:

    def test_empty_findings(self):
        """Zero findings → all metrics zero."""
        result = calculate_fitness(_make_findings())
        assert result.raw_count == 0
        assert result.weighted_score == 0.0
        assert result.unique_rules == 0
        assert result.error_count == 0
        assert result.warning_count == 0

    def test_severity_weights(self):
        """C-E1: ERROR=3, WARNING=1, INFO=0."""
        result = calculate_fitness(_make_findings(errors=2, warnings=3, infos=5))

        assert result.raw_count == 10
        assert result.error_count == 2
        assert result.warning_count == 3
        assert result.weighted_score == pytest.approx(2 * 3 + 3 * 1 + 5 * 0)  # 9.0
        assert result.unique_rules == 10  # all distinct check_ids

    def test_unique_rules_deduplication(self):
        """Duplicate check_ids are counted once for unique_rules."""
        findings = [
            FakeFinding(check_id="rule-1", severity="ERROR", line=1),
            FakeFinding(check_id="rule-1", severity="ERROR", line=2),  # same rule
            FakeFinding(check_id="rule-2", severity="WARNING", line=3),
        ]
        result = calculate_fitness(FakeSemgrepResult(findings=findings))

        assert result.raw_count == 3
        assert result.unique_rules == 2
        assert result.weighted_score == pytest.approx(3 + 3 + 1)  # 7.0

    def test_details_contains_check_ids(self):
        result = calculate_fitness(_make_findings(errors=1, warnings=1))
        assert "check_ids" in result.details
        assert len(result.details["check_ids"]) == 2


# ═══════════════════════════════════════════════════════════════════════════════
# C-E2  FitnessResult.fitness(strategy) returns the right scalar
# ═══════════════════════════════════════════════════════════════════════════════

class TestFitnessStrategy:

    @pytest.fixture
    def result(self) -> FitnessResult:
        return FitnessResult(
            raw_count=5,
            weighted_score=11.0,
            unique_rules=3,
            error_count=2,
            warning_count=3,
            composite_score=7.5,
        )

    def test_raw_count(self, result: FitnessResult):
        assert result.fitness(FitnessStrategy.RAW_COUNT) == 5.0

    def test_severity_weighted(self, result: FitnessResult):
        assert result.fitness(FitnessStrategy.SEVERITY_WEIGHTED) == 11.0

    def test_unique_rules(self, result: FitnessResult):
        assert result.fitness(FitnessStrategy.UNIQUE_RULES) == 3.0

    def test_delta_composite(self, result: FitnessResult):
        assert result.fitness(FitnessStrategy.DELTA_COMPOSITE) == 7.5

    def test_delta_composite_fallback(self):
        """C-E2: DELTA_COMPOSITE falls back to weighted_score when composite_score is None."""
        result = FitnessResult(
            raw_count=5, weighted_score=11.0, unique_rules=3,
            error_count=2, warning_count=3,
            composite_score=None,
        )
        assert result.fitness(FitnessStrategy.DELTA_COMPOSITE) == 11.0


# ═══════════════════════════════════════════════════════════════════════════════
# C-E8  aggregate_fitness sums fitness(strategy), not weighted_score
# ═══════════════════════════════════════════════════════════════════════════════

class TestAggregateFitness:

    def test_empty_results(self):
        agg = aggregate_fitness([])
        assert agg.total_fitness == 0.0
        assert agg.num_prompts == 0
        assert agg.num_vulnerable == 0

    def test_aggregation_with_severity_weighted(self):
        """C-E8: aggregate_fitness uses fitness(strategy) per result."""
        results = [
            FitnessResult(raw_count=3, weighted_score=7.0, unique_rules=2,
                          error_count=1, warning_count=4),
            FitnessResult(raw_count=0, weighted_score=0.0, unique_rules=0,
                          error_count=0, warning_count=0),
            FitnessResult(raw_count=5, weighted_score=15.0, unique_rules=3,
                          error_count=5, warning_count=0),
        ]

        agg = aggregate_fitness(results, strategy=FitnessStrategy.SEVERITY_WEIGHTED)
        assert agg.total_fitness == pytest.approx(22.0)
        assert agg.mean_fitness == pytest.approx(22.0 / 3)
        assert agg.max_fitness == pytest.approx(15.0)
        assert agg.num_prompts == 3
        assert agg.num_vulnerable == 2  # 2 results with fitness > 0

    def test_aggregation_with_raw_count(self):
        """Aggregation respects the strategy parameter."""
        results = [
            FitnessResult(raw_count=10, weighted_score=20.0, unique_rules=5,
                          error_count=5, warning_count=5),
        ]
        agg = aggregate_fitness(results, strategy=FitnessStrategy.RAW_COUNT)
        assert agg.total_fitness == pytest.approx(10.0)  # raw_count, not weighted

    def test_aggregation_with_composite(self):
        """C-E8: aggregate_fitness uses composite_score for DELTA_COMPOSITE."""
        results = [
            FitnessResult(raw_count=3, weighted_score=7.0, unique_rules=2,
                          error_count=1, warning_count=4, composite_score=2.5),
            FitnessResult(raw_count=1, weighted_score=3.0, unique_rules=1,
                          error_count=1, warning_count=0, composite_score=1.0),
        ]
        agg = aggregate_fitness(results, strategy=FitnessStrategy.DELTA_COMPOSITE)
        assert agg.total_fitness == pytest.approx(3.5)  # 2.5 + 1.0
