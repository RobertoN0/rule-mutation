"""Topic E — CompositeFitnessEvaluator unit tests (C-E3 to C-E7).

Validates the delta composite formula, weight application, SBERT disable
path, baseline caching semantics, and the display confusion documented
as E-E-display.
"""

from unittest.mock import MagicMock, patch

import pytest

from src.evaluation.composite_fitness import (
    CompositeFitnessEvaluator,
    CompositeFitnessResult,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_evaluator(
    reference_codes: dict[str, str] | None = None,
    sbert_model=None,
    weights: tuple[float, float, float] = (1.0, 0.3, 0.2),
) -> CompositeFitnessEvaluator:
    return CompositeFitnessEvaluator(
        reference_codes=reference_codes or {},
        sbert_model=sbert_model,
        weights=weights,
    )


# ═══════════════════════════════════════════════════════════════════════════════
# C-E3  evaluate() computes the three components correctly
# ═══════════════════════════════════════════════════════════════════════════════

class TestEvaluateComponents:

    def test_semgrep_delta(self):
        """C-E3: semgrep_delta = alpha * (candidate - baseline)."""
        ev = _make_evaluator(weights=(1.0, 0.0, 0.0))
        r = ev.evaluate(
            semgrep_score=8.0,
            baseline_score=5.0,
            generated_code="code",
            test_case_id="tc0",
        )
        assert r.semgrep_delta == pytest.approx(3.0)
        assert r.composite == pytest.approx(3.0)

    def test_semgrep_delta_negative(self):
        """Negative delta when mutation improved security."""
        ev = _make_evaluator(weights=(1.0, 0.0, 0.0))
        r = ev.evaluate(
            semgrep_score=2.0,
            baseline_score=5.0,
            generated_code="code",
            test_case_id="tc0",
        )
        assert r.semgrep_delta == pytest.approx(-3.0)

    def test_rule_divergence(self):
        """C-E3: rule_divergence = beta * (1 - sbert_similarity)."""
        ev = _make_evaluator(weights=(0.0, 1.0, 0.0))
        r = ev.evaluate(
            semgrep_score=5.0,
            baseline_score=5.0,
            generated_code="code",
            test_case_id="tc0",
            sbert_rule_similarity=0.85,
        )
        assert r.rule_divergence == pytest.approx(0.15)
        assert r.composite == pytest.approx(0.15)

    def test_rule_divergence_none(self):
        """Rule divergence is 0.0 when sbert_rule_similarity is None."""
        ev = _make_evaluator(weights=(0.0, 1.0, 0.0))
        r = ev.evaluate(
            semgrep_score=5.0,
            baseline_score=5.0,
            generated_code="code",
            test_case_id="tc0",
            sbert_rule_similarity=None,
        )
        assert r.rule_divergence == pytest.approx(0.0)


# ═══════════════════════════════════════════════════════════════════════════════
# C-E4  Weight application: composite == a*sd + b*rd + g*cd
# ═══════════════════════════════════════════════════════════════════════════════

class TestWeightApplication:

    def test_full_composite_manual(self):
        """C-E4: manual calculation with all three components."""
        # Mock SBERT for code_divergence
        mock_sbert = MagicMock()
        import numpy as np
        # code embedding similarity = 0.9 → divergence = 0.1
        mock_sbert.encode.side_effect = [
            np.array([[1.0, 0.0]]),  # generated code
            np.array([[0.9, 0.436]]),  # reference code (cosine sim ≈ 0.9)
        ]

        ev = _make_evaluator(
            reference_codes={"tc0": "reference code"},
            sbert_model=mock_sbert,
            weights=(1.0, 0.3, 0.2),
        )

        r = ev.evaluate(
            semgrep_score=8.0,
            baseline_score=5.0,
            generated_code="generated code",
            test_case_id="tc0",
            sbert_rule_similarity=0.85,
        )

        # semgrep_delta = 1.0 * (8.0 - 5.0) = 3.0
        assert r.semgrep_delta == pytest.approx(3.0)
        # rule_divergence = 0.3 * (1 - 0.85) = 0.045
        assert r.rule_divergence == pytest.approx(0.045)
        # code_divergence = 0.2 * (1 - cosine_sim)
        # The actual value depends on sklearn cosine_similarity
        # composite = semgrep_delta + rule_divergence + code_divergence
        assert r.composite == pytest.approx(r.semgrep_delta + r.rule_divergence + r.code_divergence)

    def test_weights_tuple_stored(self):
        ev = _make_evaluator(weights=(2.0, 0.5, 0.1))
        r = ev.evaluate(
            semgrep_score=10.0, baseline_score=5.0,
            generated_code="", test_case_id="tc0",
        )
        assert r.weights == (2.0, 0.5, 0.1)
        # semgrep_delta = 2.0 * 5.0 = 10.0
        assert r.semgrep_delta == pytest.approx(10.0)


# ═══════════════════════════════════════════════════════════════════════════════
# C-E5  sbert_model=None disables SBERT → code_divergence = 0.0
# ═══════════════════════════════════════════════════════════════════════════════

class TestSBERTDisabled:

    def test_no_sbert_no_code_divergence(self):
        """C-E5: with sbert_model=None, code_divergence is always 0.0."""
        ev = _make_evaluator(
            reference_codes={"tc0": "reference code"},
            sbert_model=None,
            weights=(1.0, 0.3, 0.2),
        )
        r = ev.evaluate(
            semgrep_score=8.0, baseline_score=5.0,
            generated_code="generated code", test_case_id="tc0",
            sbert_rule_similarity=0.85,
        )
        assert r.code_divergence == pytest.approx(0.0)
        assert r.components["has_reference_code"] is True

    def test_no_reference_code(self):
        """Code divergence is 0.0 when test_case_id has no reference code."""
        mock_sbert = MagicMock()
        ev = _make_evaluator(
            reference_codes={},  # empty — no reference code for tc0
            sbert_model=mock_sbert,
            weights=(1.0, 0.3, 0.2),
        )
        r = ev.evaluate(
            semgrep_score=8.0, baseline_score=5.0,
            generated_code="generated code", test_case_id="tc0",
        )
        assert r.code_divergence == pytest.approx(0.0)
        assert r.components["has_reference_code"] is False
        # SBERT should NOT have been called
        mock_sbert.encode.assert_not_called()


# ═══════════════════════════════════════════════════════════════════════════════
# C-E6  Baseline caching — verified at the evaluator level
# ═══════════════════════════════════════════════════════════════════════════════

class TestBaselineCaching:

    def test_baseline_zero_gives_full_semgrep_delta(self):
        """C-E6: when baseline=0 (cache empty), composite ≈ weighted_score."""
        ev = _make_evaluator(weights=(1.0, 0.0, 0.0))
        r = ev.evaluate(
            semgrep_score=5.0,
            baseline_score=0.0,  # simulate empty cache
            generated_code="code",
            test_case_id="tc0",
        )
        assert r.semgrep_delta == pytest.approx(5.0)

    def test_baseline_populated_gives_small_delta(self):
        """C-E6: when baseline matches candidate, delta ≈ 0."""
        ev = _make_evaluator(weights=(1.0, 0.0, 0.0))
        r = ev.evaluate(
            semgrep_score=5.0,
            baseline_score=5.0,  # same as candidate
            generated_code="code",
            test_case_id="tc0",
        )
        assert r.semgrep_delta == pytest.approx(0.0)


# ═══════════════════════════════════════════════════════════════════════════════
# C-E7  "Original fitness" display vs composite — the known confusion
# ═══════════════════════════════════════════════════════════════════════════════

class TestDisplayConfusion:

    def test_e_e_display_documented(self):
        """C-E7: document that baseline pass produces composite ≈ weighted_score
        because baseline_score defaults to 0 on first pass, while subsequent
        iterations produce composite ≈ 0 when no improvement."""
        ev = _make_evaluator(weights=(1.0, 0.3, 0.0))

        # Baseline pass: baseline_score=0 → composite ≈ weighted_score
        baseline = ev.evaluate(
            semgrep_score=5.0, baseline_score=0.0,
            generated_code="code", test_case_id="tc0",
            sbert_rule_similarity=None,
        )
        assert baseline.composite == pytest.approx(5.0)

        # Subsequent iteration with populated cache: baseline_score=5.0
        iteration = ev.evaluate(
            semgrep_score=5.0, baseline_score=5.0,
            generated_code="code", test_case_id="tc0",
            sbert_rule_similarity=0.95,  # small divergence
        )
        # semgrep_delta = 0.0, rule_div = 0.3 * 0.05 = 0.015
        assert iteration.composite == pytest.approx(0.015)

        # This is the documented "Fitness=0.000 vs Original fitness=5.0" confusion
        assert baseline.composite > 1.0
        assert iteration.composite < 0.1


# ═══════════════════════════════════════════════════════════════════════════════
# CompositeFitnessResult structure
# ═══════════════════════════════════════════════════════════════════════════════

class TestCompositeFitnessResult:

    def test_result_has_components(self):
        ev = _make_evaluator(weights=(1.0, 0.3, 0.2))
        r = ev.evaluate(
            semgrep_score=8.0, baseline_score=5.0,
            generated_code="code", test_case_id="tc0",
            sbert_rule_similarity=0.90,
        )
        assert "raw_semgrep_delta" in r.components
        assert "raw_rule_divergence" in r.components
        assert "raw_code_divergence" in r.components
        assert "sbert_rule_similarity" in r.components
        assert r.components["raw_semgrep_delta"] == pytest.approx(3.0)
        assert r.components["raw_rule_divergence"] == pytest.approx(0.1)
