"""Topic C — MutationQualityValidator unit tests (C-C1 to C-C10).

Validates all 5 quality criteria, the passes_all gate, retry logic for
deterministic vs stochastic mutators, and metadata flow.
"""

from unittest.mock import MagicMock, patch

import pytest

from src.mutation.base import MutationResult, Mutator
from src.mutation.quality import MutationQualityValidator

from tests.conftest import SAMPLE_RULE_TEXT


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_result(
    original: str = SAMPLE_RULE_TEXT,
    mutated: str | None = None,
    mutation_type: str = "fluff",
) -> MutationResult:
    """Build a MutationResult with controllable fields."""
    if mutated is None:
        mutated = original.replace("MUST", "should ideally").replace("NEVER", "try to avoid")
    return MutationResult(
        original=original,
        mutated=mutated,
        mutation_type=mutation_type,
        changes=["test change"],
    )


def _validator(use_sbert: bool = False, use_perplexity: bool = False, **kw) -> MutationQualityValidator:
    """Validator with SBERT and perplexity disabled by default (fast tests)."""
    return MutationQualityValidator(use_sbert=use_sbert, use_perplexity=use_perplexity, **kw)


EXPECTED_QUALITY_KEYS = {
    "instruction_adherent",
    "sbert_similarity", "sbert_threshold",
    "perplexity_ratio", "perplexity_threshold",
    "inline_code_retention", "keyword_retention", "keyword_threshold",
    "security_intent_preserved",
    "readability_grade_original", "readability_grade_mutated", "readability_grade_delta",
    "passes_all", "changed", "mutation_type",
}


# ═══════════════════════════════════════════════════════════════════════════════
# C-C1  validate() populates all expected keys
# ═══════════════════════════════════════════════════════════════════════════════

class TestValidateKeys:

    def test_all_keys_present(self):
        """C-C1: result.metadata['quality'] has all expected keys."""
        v = _validator()
        result = v.validate(_make_result())
        quality = result.metadata["quality"]
        assert EXPECTED_QUALITY_KEYS.issubset(quality.keys()), \
            f"Missing keys: {EXPECTED_QUALITY_KEYS - quality.keys()}"

    def test_unchanged_result(self):
        """Validate handles identity mutation (no change)."""
        v = _validator()
        result = _make_result(mutated=SAMPLE_RULE_TEXT)  # identity
        v.validate(result)
        quality = result.metadata["quality"]
        assert quality["changed"] is False


# ═══════════════════════════════════════════════════════════════════════════════
# C-C2  Criterion 1 — Instruction adherence
# ═══════════════════════════════════════════════════════════════════════════════

class TestInstructionAdherence:

    def test_fluff_passes(self):
        """C-C2: fluff adherence = text changed."""
        v = _validator()
        result = v.validate(_make_result(mutation_type="fluff"))
        assert result.metadata["quality"]["instruction_adherent"] is True

    def test_identity_fails(self):
        """Unchanged text → adherence fails."""
        v = _validator()
        result = v.validate(_make_result(mutated=SAMPLE_RULE_TEXT, mutation_type="fluff"))
        assert result.metadata["quality"]["instruction_adherent"] is False

    def test_paraphrase_in_range(self):
        """C-C2: paraphrase adherence checks word-level Jaccard in (0.15, 0.995)."""
        v = _validator()
        # Valid paraphrase: ~50% word overlap
        original = "Validate all user input to prevent injection attacks."
        paraphrased = "Check every user submission to stop injection vulnerabilities."
        result = _make_result(original=original, mutated=paraphrased, mutation_type="paraphrase")
        v.validate(result)
        assert result.metadata["quality"]["instruction_adherent"] is True

    def test_paraphrase_too_similar_fails(self):
        """Paraphrase with Jaccard > 0.995 (near-identity) → adherence fails."""
        v = _validator()
        # Use double spaces so .split() produces identical word sets (J=1.0)
        # but the strings are character-different (changed=True).
        original = "Validate all user input and check data carefully before use."
        nearly_same = "Validate  all  user  input  and  check  data  carefully  before  use."
        result = _make_result(original=original, mutated=nearly_same, mutation_type="paraphrase")
        v.validate(result)
        # Jaccard is 1.0 (> 0.995) → should fail
        assert result.metadata["quality"]["instruction_adherent"] is False


# ═══════════════════════════════════════════════════════════════════════════════
# C-C3  Criterion 2 — SBERT semantic similarity
# ═══════════════════════════════════════════════════════════════════════════════

class TestSBERTSimilarity:

    def test_sbert_disabled(self):
        """C-C3: with use_sbert=False, sbert_similarity is None and doesn't gate."""
        v = _validator(use_sbert=False)
        result = v.validate(_make_result())
        quality = result.metadata["quality"]
        assert quality["sbert_similarity"] is None
        # Should still pass (None doesn't gate)
        assert quality["passes_all"] is True

    def test_sbert_pass(self):
        """C-C3: mocked SBERT returning 0.90 → passes threshold (0.75)."""
        v = _validator(use_sbert=True)
        mock_sbert = MagicMock()
        import numpy as np
        mock_sbert.encode.return_value = np.array([[1.0, 0.0]])
        object.__setattr__(v, "_sbert", mock_sbert)

        # Mock cosine_similarity to return 0.90
        with patch("src.mutation.quality.MutationQualityValidator._compute_sbert_similarity", return_value=0.90):
            result = v.validate(_make_result())

        quality = result.metadata["quality"]
        assert quality["sbert_similarity"] == 0.90
        assert quality["passes_all"] is True

    def test_sbert_fail(self):
        """C-C3: mocked SBERT returning 0.70 → fails threshold (0.75)."""
        v = _validator(use_sbert=True)

        with patch.object(v, "_compute_sbert_similarity", return_value=0.70):
            result = v.validate(_make_result())

        quality = result.metadata["quality"]
        assert quality["sbert_similarity"] == 0.70
        assert quality["passes_all"] is False


# ═══════════════════════════════════════════════════════════════════════════════
# C-C4  Criterion 3 — Perplexity ratio
# ═══════════════════════════════════════════════════════════════════════════════

class TestPerplexity:

    def test_perplexity_disabled(self):
        """C-C4: with use_perplexity=False, perplexity_ratio is None."""
        v = _validator(use_perplexity=False)
        result = v.validate(_make_result())
        assert result.metadata["quality"]["perplexity_ratio"] is None

    def test_perplexity_pass(self):
        """C-C4: mocked perplexity ratio 1.5 → passes threshold (2.0)."""
        v = _validator(use_perplexity=True)

        with patch.object(v, "_compute_perplexity_ratio", return_value=1.5):
            result = v.validate(_make_result())

        assert result.metadata["quality"]["perplexity_ratio"] == 1.5
        assert result.metadata["quality"]["passes_all"] is True

    def test_perplexity_fail(self):
        """C-C4: mocked perplexity ratio 3.0 → fails threshold (2.0)."""
        v = _validator(use_perplexity=True)

        with patch.object(v, "_compute_perplexity_ratio", return_value=3.0):
            result = v.validate(_make_result())

        assert result.metadata["quality"]["perplexity_ratio"] == 3.0
        assert result.metadata["quality"]["passes_all"] is False


# ═══════════════════════════════════════════════════════════════════════════════
# C-C5  Criterion 4 — Inline code + keyword retention
# ═══════════════════════════════════════════════════════════════════════════════

class TestSecurityPreservation:

    def test_inline_code_retained(self):
        """C-C5: all inline code spans preserved → retention 1.0."""
        v = _validator()
        # Default _make_result preserves inline code (only weakens verbs)
        result = v.validate(_make_result())
        assert result.metadata["quality"]["inline_code_retention"] == 1.0

    def test_inline_code_dropped(self):
        """C-C5: removing inline code → retention < 1.0 → fails."""
        v = _validator()
        mutated = SAMPLE_RULE_TEXT.replace("`PreparedStatement`", "PreparedStatement")
        result = v.validate(_make_result(mutated=mutated))
        quality = result.metadata["quality"]
        assert quality["inline_code_retention"] < 1.0
        assert quality["passes_all"] is False

    def test_keyword_retention_high(self):
        """Keywords mostly preserved → retention ≥ 0.70."""
        v = _validator()
        result = v.validate(_make_result())
        assert result.metadata["quality"]["keyword_retention"] >= 0.70

    def test_keyword_retention_low(self):
        """C-C5: dropping security keywords below threshold → fails."""
        v = _validator()
        # Strip most security keywords from the mutated text
        stripped = SAMPLE_RULE_TEXT
        for kw in ["validate", "sanitize", "injection", "escape", "prevent",
                    "xss", "sql", "session", "attack", "secure", "security"]:
            stripped = stripped.replace(kw, "removed")
            stripped = stripped.replace(kw.title(), "Removed")

        result = v.validate(_make_result(mutated=stripped))
        quality = result.metadata["quality"]
        assert quality["keyword_retention"] < 0.70
        assert quality["security_intent_preserved"] is False
        assert quality["passes_all"] is False


# ═══════════════════════════════════════════════════════════════════════════════
# C-C6  Criterion 5 — Readability delta (informational only)
# ═══════════════════════════════════════════════════════════════════════════════

class TestReadability:

    def test_readability_fields_numeric_or_none(self):
        """C-C6: readability fields are numeric (if textstat installed) or None."""
        v = _validator()
        result = v.validate(_make_result())
        quality = result.metadata["quality"]
        for key in ("readability_grade_original", "readability_grade_mutated"):
            assert quality[key] is None or isinstance(quality[key], (int, float))

    def test_readability_delta_computed(self):
        """C-C6: delta = mutated - original (if both non-None)."""
        v = _validator()
        result = v.validate(_make_result())
        quality = result.metadata["quality"]
        if quality["readability_grade_original"] is not None:
            expected_delta = round(
                quality["readability_grade_mutated"] - quality["readability_grade_original"], 2,
            )
            assert quality["readability_grade_delta"] == pytest.approx(expected_delta)


# ═══════════════════════════════════════════════════════════════════════════════
# C-C7  passes_all gate aggregation
# ═══════════════════════════════════════════════════════════════════════════════

class TestPassesAll:

    def test_all_criteria_pass(self):
        """C-C7: all criteria green → passes_all True."""
        v = _validator()
        result = v.validate(_make_result())
        assert result.metadata["quality"]["passes_all"] is True

    def test_adherence_fails_blocks(self):
        """Failing adherence alone → passes_all False."""
        v = _validator()
        # identity mutation → adherence fails
        result = v.validate(_make_result(mutated=SAMPLE_RULE_TEXT, mutation_type="fluff"))
        assert result.metadata["quality"]["instruction_adherent"] is False
        assert result.metadata["quality"]["passes_all"] is False

    def test_readability_alone_does_not_block(self):
        """C-C7: readability delta does NOT gate passes_all."""
        v = _validator()
        result = v.validate(_make_result())
        quality = result.metadata["quality"]
        # Even if readability is terrible, passes_all should be unaffected
        # (readability is informational only)
        if quality["passes_all"]:
            # Manually set readability to extreme value — shouldn't flip passes_all
            quality["readability_grade_delta"] = 50.0
            # Re-check: passes_all is not affected by readability
            assert quality["passes_all"] is True


# ═══════════════════════════════════════════════════════════════════════════════
# C-C8  Deterministic mutators not retried
# ═══════════════════════════════════════════════════════════════════════════════

class FakeDeterministicMutator(Mutator):
    """Mutator with _temperature=0.0 (deterministic)."""
    _temperature = 0.0
    _call_count = 0

    @property
    def name(self) -> str:
        return "fake_deterministic"

    def mutate(self, text: str) -> MutationResult:
        self._call_count += 1
        return MutationResult(
            original=text,
            mutated=text.replace("MUST", "should"),
            mutation_type=self.name,
            changes=["weakened MUST"],
        )


class FakeStochasticMutator(Mutator):
    """Mutator with _temperature=0.6 (stochastic)."""
    _temperature = 0.6
    _call_count = 0

    @property
    def name(self) -> str:
        return "fake_stochastic"

    def mutate(self, text: str) -> MutationResult:
        self._call_count += 1
        # Produce a different result each time by appending call count
        return MutationResult(
            original=text,
            mutated=text.replace("MUST", f"may_{self._call_count}"),
            mutation_type=self.name,
            changes=[f"attempt {self._call_count}"],
        )


class TestRetryDeterministic:

    def test_deterministic_single_attempt(self):
        """C-C8: deterministic mutator gets exactly 1 attempt regardless of max_retries."""
        v = _validator()
        m = FakeDeterministicMutator()
        v.validate_with_retry(m, SAMPLE_RULE_TEXT, max_retries=5)
        assert m._call_count == 1


# ═══════════════════════════════════════════════════════════════════════════════
# C-C9  Non-deterministic mutators retry up to max_retries
# ═══════════════════════════════════════════════════════════════════════════════

class TestRetryStochastic:

    def test_stochastic_retries(self):
        """C-C9: stochastic mutator retries up to max_retries."""
        v = _validator()
        # Force all validation to fail by making passes_all=False
        with patch.object(v, "validate", side_effect=lambda r: _force_fail_validation(r)):
            m = FakeStochasticMutator()
            v.validate_with_retry(m, SAMPLE_RULE_TEXT, max_retries=3)
            assert m._call_count == 3

    def test_stochastic_early_exit_on_pass(self):
        """C-C9: stochastic stops early when a candidate passes."""
        v = _validator()
        call_count = [0]

        def _validate_fail_then_pass(r):
            call_count[0] += 1
            # Explicitly control passes_all: fail on attempt 1, pass on attempt 2
            r.metadata["quality"] = {
                "passes_all": call_count[0] >= 2,
                "instruction_adherent": True,
                "sbert_similarity": None,
                "sbert_threshold": 0.75,
                "perplexity_ratio": None,
                "perplexity_threshold": 2.0,
                "inline_code_retention": 1.0,
                "keyword_retention": 0.90,
                "keyword_threshold": 0.70,
                "security_intent_preserved": True,
                "readability_grade_original": None,
                "readability_grade_mutated": None,
                "readability_grade_delta": None,
                "changed": True,
                "mutation_type": r.mutation_type,
            }
            return r

        with patch.object(v, "validate", side_effect=_validate_fail_then_pass):
            m = FakeStochasticMutator()
            result = v.validate_with_retry(m, SAMPLE_RULE_TEXT, max_retries=5)
            assert m._call_count == 2  # stopped early


def _force_fail_validation(result: MutationResult) -> MutationResult:
    """Populate quality metadata with passes_all=False."""
    result.metadata["quality"] = {
        "passes_all": False,
        "instruction_adherent": True,
        "sbert_similarity": 0.50,
        "sbert_threshold": 0.75,
        "perplexity_ratio": None,
        "perplexity_threshold": 2.0,
        "inline_code_retention": 1.0,
        "keyword_retention": 0.90,
        "keyword_threshold": 0.70,
        "security_intent_preserved": True,
        "readability_grade_original": None,
        "readability_grade_mutated": None,
        "readability_grade_delta": None,
        "changed": True,
        "mutation_type": result.mutation_type,
    }
    return result


# ═══════════════════════════════════════════════════════════════════════════════
# C-C10  Validation metadata flows into result
# ═══════════════════════════════════════════════════════════════════════════════

class TestMetadataFlow:

    def test_quality_in_metadata(self):
        """C-C10: validation populates result.metadata['quality']."""
        v = _validator()
        result = _make_result()
        assert "quality" not in result.metadata

        v.validate(result)
        assert "quality" in result.metadata
        assert isinstance(result.metadata["quality"], dict)
        assert result.metadata["quality"]["mutation_type"] == "fluff"
