"""
Fitness function for the SBST rule-set search.

Defines how to score Semgrep findings in generated code, which the search maps
to f1 (repair by default: fewer findings than baseline is better).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .semgrep_runner import SemgrepResult


# Severity weights for weighted fitness calculation
SEVERITY_WEIGHTS: dict[str, int] = {
    "ERROR": 3,
    "WARNING": 1,
    "INFO": 0,
}


@dataclass
class FitnessResult:
    """Result of fitness calculation for a single code sample."""
    
    raw_count: int
    """Total number of findings."""
    
    weighted_score: float
    """Severity-weighted score."""
    
    unique_rules: int
    """Number of unique rules triggered."""
    
    error_count: int
    """Number of ERROR severity findings."""
    
    warning_count: int
    """Number of WARNING severity findings."""
    
    details: dict = field(default_factory=dict)
    """Additional details (e.g., specific rule IDs)."""

    score_source: str = "semgrep"
    """``semgrep`` for a valid scan or ``baseline_imputed`` when a prompt-local
    generation/parse failure is conservatively assigned its baseline score."""

    analysis_status: str = "valid"
    """Prompt-level validation/scanner status used for qualification reports."""

    observed_raw_count: int | None = None
    """Raw findings actually observed, if a trustworthy scan completed."""

    observed_weighted_score: float | None = None
    """Weighted findings actually observed, if a trustworthy scan completed."""

    raw_reduction: float | None = None
    """Baseline minus candidate raw findings; positive means repair."""

    weighted_reduction: float | None = None
    """Baseline minus candidate severity-weighted score; diagnostic only."""


@dataclass 
class AggregatedFitness:
    """Aggregated fitness across multiple test prompts."""
    
    total_fitness: float
    """Sum of fitness across all prompts."""
    
    mean_fitness: float
    """Mean fitness per prompt."""
    
    max_fitness: float
    """Maximum fitness from any single prompt."""
    
    num_prompts: int
    """Number of prompts evaluated."""
    
    num_vulnerable: int
    """Number of prompts that produced at least one vulnerability."""
    
    individual_results: list[FitnessResult] = field(default_factory=list)
    """Per-prompt fitness results."""

    total_raw_reduction: float = 0.0
    """Sum of baseline-minus-candidate raw findings across prompts (f1)."""

    total_raw_count: int = 0
    """Effective raw findings after prompt-local baseline imputation."""

    total_weighted_score: float = 0.0
    """Effective severity-weighted score, reported as a diagnostic."""

    total_weighted_reduction: float = 0.0
    """Baseline-minus-candidate weighted score, diagnostic only."""

    num_valid_prompts: int = 0
    """Prompts with a valid generation and completed Semgrep analysis."""

    num_invalid_prompts: int = 0
    """Prompt-local failures scored by conservative baseline imputation."""

    failure_counts: dict[str, int] = field(default_factory=dict)
    """Counts by prompt-level analysis status."""

    num_prompts_affected: int = 0
    """Prompts touching a mutated or reordered rule; reporting only."""

    # ---- Chromosome-level conservative objectives (attached by
    # _evaluate_chromosome, not computed here — they need the alleles + SBERT
    # validator, not per-prompt results). --------------------------------------
    rule_fidelity: float = 1.0
    """Mean SBERT similarity of the chromosome's MUTATED rules vs their originals
    (1.0 when nothing is mutated). Conservative f2 axis — maximized."""

    parsimony: int = 0
    """Number of mutated rules in the chromosome. Conservative f3 axis — minimized
    (stored negated when routed to an objective, so the maximizing archive works)."""


def calculate_fitness(
    semgrep_result: "SemgrepResult",
) -> FitnessResult:
    """Calculate fitness from Semgrep results.
    
    Args:
        semgrep_result: Result from run_semgrep().
    Returns:
        FitnessResult with various metrics.
    """
    if getattr(semgrep_result, "error", None):
        raise RuntimeError(
            "Cannot calculate fitness from a failed Semgrep result: "
            f"{semgrep_result.error}"
        )
    findings = semgrep_result.findings
    
    raw_count = len(findings)
    error_count = sum(1 for f in findings if f.severity == "ERROR")
    warning_count = sum(1 for f in findings if f.severity == "WARNING")
    
    # Weighted score
    weighted_score = sum(
        SEVERITY_WEIGHTS.get(f.severity, 0)
        for f in findings
    )
    
    # Unique rules
    unique_rules = len(set(f.check_id for f in findings))
    
    return FitnessResult(
        raw_count=raw_count,
        weighted_score=float(weighted_score),
        unique_rules=unique_rules,
        error_count=error_count,
        warning_count=warning_count,
        details={
            "check_ids": sorted({f.check_id for f in findings}),
        },
        observed_raw_count=raw_count,
        observed_weighted_score=float(weighted_score),
    )


def aggregate_fitness(
    results: list[FitnessResult],
    *,
    num_prompts_affected: int = 0,
) -> AggregatedFitness:
    """Aggregate fitness results across multiple test prompts.

    Args:
        results: List of FitnessResult from individual prompts.
        num_prompts_affected: Prompts whose rendered rule set can differ from
            the origin. This is a reporting field, not an objective.

    Returns:
        AggregatedFitness with summary statistics.
    """
    if not results:
        return AggregatedFitness(
            total_fitness=0.0,
            mean_fitness=0.0,
            max_fitness=0.0,
            num_prompts=0,
            num_vulnerable=0,
            individual_results=[],
        )

    n = len(results)
    raw_counts = [float(result.raw_count) for result in results]
    total_raw_reduction = sum(
        result.raw_reduction for result in results if result.raw_reduction is not None
    )
    total_weighted_reduction = sum(
        result.weighted_reduction
        for result in results
        if result.weighted_reduction is not None
    )
    failure_counts: dict[str, int] = {}
    for result in results:
        if result.analysis_status != "valid":
            failure_counts[result.analysis_status] = failure_counts.get(result.analysis_status, 0) + 1
    return AggregatedFitness(
        total_fitness=sum(raw_counts),
        mean_fitness=sum(raw_counts) / n,
        max_fitness=max(raw_counts),
        num_prompts=n,
        num_vulnerable=sum(1 for value in raw_counts if value > 0),
        individual_results=results,
        total_raw_reduction=total_raw_reduction,
        total_raw_count=sum(result.raw_count for result in results),
        total_weighted_score=sum(result.weighted_score for result in results),
        total_weighted_reduction=total_weighted_reduction,
        num_valid_prompts=n - sum(failure_counts.values()),
        num_invalid_prompts=sum(failure_counts.values()),
        failure_counts=failure_counts,
        num_prompts_affected=num_prompts_affected,
    )
