"""Topic C — MutationQualityValidator unit tests (C-C1 to C-C10).

Validates the recorded, non-gating quality measurements and metadata flow.
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


def _validator(use_sbert: bool = False, **kw) -> MutationQualityValidator:
    """Validator with SBERT disabled by default (fast tests)."""
    return MutationQualityValidator(use_sbert=use_sbert, **kw)


EXPECTED_QUALITY_KEYS = {
    "instruction_adherent",
    "sbert_step",
    "inline_code_retention", "keyword_retention",
    "changed",
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
        """C-C3: with use_sbert=False, sbert_step is None."""
        v = _validator(use_sbert=False)
        result = v.validate(_make_result())
        quality = result.metadata["quality"]
        assert quality["sbert_step"] is None

    def test_sbert_pass(self):
        """C-C3: mocked SBERT returning 0.90 is recorded unchanged."""
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

    def test_sbert_fail(self):
        """C-C3: mocked SBERT returning 0.70 is recorded without classification."""
        v = _validator(use_sbert=True)

        with patch.object(v, "_compute_sbert_similarity", return_value=0.70):
            result = v.validate(_make_result())

        quality = result.metadata["quality"]
        assert quality["sbert_step"] == 0.70


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
        """C-C5: removing inline code records retention below 1.0."""
        v = _validator()
        mutated = SAMPLE_RULE_TEXT.replace("`PreparedStatement`", "PreparedStatement")
        result = v.validate(_make_result(mutated=mutated))
        quality = result.metadata["quality"]
        assert quality["inline_code_retention"] < 1.0

    def test_keyword_retention_high(self):
        """Keywords mostly preserved produce a high retention fraction."""
        v = _validator()
        result = v.validate(_make_result())
        assert result.metadata["quality"]["keyword_retention"] >= 0.70

    def test_keyword_retention_low(self):
        """C-C5: dropping security keywords records a low retention fraction."""
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


# ═══════════════════════════════════════════════════════════════════════════════
# C-C6  Readability delta criterion — REMOVED 2026-06-11 (was informational-only)
# ═══════════════════════════════════════════════════════════════════════════════

# (No tests — the readability criterion was removed from the validator on 2026-06-11.)


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
        assert "instruction_adherent" in quality
        assert "sbert_step" in quality
        assert "mutation_type" not in quality
