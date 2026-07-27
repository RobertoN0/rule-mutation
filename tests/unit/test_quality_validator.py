"""Topic C — MutationQualityValidator unit tests (C-C1 to C-C10).

Validates all 5 quality criteria, the passes_all gate, retry logic for
deterministic vs stochastic mutators, and metadata flow.
"""

from unittest.mock import MagicMock, patch

from src.mutation.base import MutationResult
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
    "sbert_step",
    "perplexity_ratio",
    "inline_code_retention", "keyword_retention",
    "security_intent_preserved",
    "passes_all", "changed",
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
        """C-C3: with use_sbert=False, sbert_step is None and doesn't gate."""
        v = _validator(use_sbert=False)
        result = v.validate(_make_result())
        quality = result.metadata["quality"]
        assert quality["sbert_step"] is None
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
        assert quality["sbert_step"] == 0.90
        assert quality["passes_all"] is True

    def test_sbert_fail(self):
        """C-C3: mocked SBERT returning 0.70 → fails threshold (0.75)."""
        v = _validator(use_sbert=True)

        with patch.object(v, "_compute_sbert_similarity", return_value=0.70):
            result = v.validate(_make_result())

        quality = result.metadata["quality"]
        assert quality["sbert_step"] == 0.70
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
        # Strip 8 words; 'side' is no longer in the hardcoded lexicon so only 7
        # of the 8 affect the score: 7/18 present → retention ≈ 0.61 < 0.70.
        stripped = SAMPLE_RULE_TEXT
        for kw in ["injection", "prevent", "privilege", "safe",
                   "server", "input", "avoid", "side"]:
            stripped = stripped.replace(kw, "removed")
            stripped = stripped.replace(kw.title(), "Removed")

        result = v.validate(_make_result(mutated=stripped))
        quality = result.metadata["quality"]
        assert quality["keyword_retention"] < 0.70
        assert quality["security_intent_preserved"] is False
        assert quality["passes_all"] is False


# ═══════════════════════════════════════════════════════════════════════════════
# C-C6  Readability delta criterion — REMOVED 2026-06-11 (was informational-only)
# ═══════════════════════════════════════════════════════════════════════════════

# (No tests — the readability criterion was removed from the validator on 2026-06-11.)


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
        quality = result.metadata["quality"]
        assert isinstance(quality, dict)
        assert "passes_all" in quality
        assert "sbert_step" in quality
        assert "mutation_type" not in quality
