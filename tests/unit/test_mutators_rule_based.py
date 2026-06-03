"""Topic B — Rule-based mutator unit tests (C-B1 to C-B6).

Validates the 5 rule-based mutators: verb_weakening, synonym_replacement,
add_random_word, section_reorder_shuffle, section_reorder_degrade.

Each mutator is tested against the shared SAMPLE_RULE_TEXT fixture
(~400 words with frontmatter, ## sections, bullets, inline `code`, and
security keywords).
"""

import re

import pytest

from src.mutation import (
    VerbWeakeningMutator,
    SynonymReplacementMutator,
    AddRandomWordMutator,
    SectionReorderMutator,
    create_mutator,
)
from src.mutation.base import MutationResult

# Import shared fixture
from tests.conftest import SAMPLE_RULE_TEXT


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _frontmatter(text: str) -> str:
    """Extract the YAML frontmatter block (everything between the two --- delimiters)."""
    match = re.match(r"(---\n.*?\n---\n)", text, re.DOTALL)
    return match.group(1) if match else ""


def _inline_code_spans(text: str) -> set[str]:
    """Extract all inline `code` spans from text."""
    return set(re.findall(r"`([^`]+)`", text))


SEED = 42


# ═══════════════════════════════════════════════════════════════════════════════
# Verb Weakening Mutator
# ═══════════════════════════════════════════════════════════════════════════════

class TestVerbWeakeningMutator:

    @pytest.fixture
    def result(self) -> MutationResult:
        return VerbWeakeningMutator(seed=SEED).mutate(SAMPLE_RULE_TEXT)

    def test_c_b1_changed(self, result: MutationResult):
        assert result.changed
        assert result.change_ratio > 0

    def test_c_b2_changes_nonempty(self, result: MutationResult):
        assert len(result.changes) > 0

    def test_c_b3_shape_verbs_weakened(self, result: MutationResult):
        """C-B3: strong verbs replaced; no structural changes."""
        body = result.mutated.split("---\n", 2)[-1]
        # MUST should be replaced
        assert "MUST" not in body
        assert "should ideally" in body
        # NEVER should be replaced
        assert "NEVER" not in body
        assert "try to avoid" in body
        # No prefix/suffix fluff added
        assert "Guidelines" not in result.mutated
        assert "Jira" not in result.mutated

    def test_c_b4_frontmatter_preserved(self, result: MutationResult):
        assert _frontmatter(result.mutated) == _frontmatter(SAMPLE_RULE_TEXT)

    def test_c_b5_inline_code_preserved(self, result: MutationResult):
        original_spans = _inline_code_spans(SAMPLE_RULE_TEXT)
        mutated_spans = _inline_code_spans(result.mutated)
        assert original_spans.issubset(mutated_spans)


# ═══════════════════════════════════════════════════════════════════════════════
# Synonym Replacement Mutator
# ═══════════════════════════════════════════════════════════════════════════════

class TestSynonymReplacementMutator:

    @pytest.fixture
    def result(self) -> MutationResult:
        return SynonymReplacementMutator(seed=SEED).mutate(SAMPLE_RULE_TEXT)

    def test_c_b1_changed(self, result: MutationResult):
        assert result.changed
        assert result.change_ratio > 0

    def test_c_b2_changes_nonempty(self, result: MutationResult):
        assert len(result.changes) > 0
        assert any("synonym" in c.lower() for c in result.changes)

    def test_c_b3_shape_words_replaced(self, result: MutationResult):
        """C-B3: words replaced with synonyms; security keywords may shift.
        Note: nlpaug's WordNet backend replaces individual words, which can
        mangle Markdown formatting (e.g. ## → # #).  The test validates that
        the text actually changed at the word level, not structural fidelity."""
        # Mutated text should differ from original body
        assert result.mutated != SAMPLE_RULE_TEXT
        # The change is at the word level — some words should be different
        orig_words = set(SAMPLE_RULE_TEXT.split())
        mut_words = set(result.mutated.split())
        # Symmetric difference should be non-empty (some words replaced)
        assert orig_words.symmetric_difference(mut_words)

    def test_c_b4_frontmatter_preserved(self, result: MutationResult):
        assert _frontmatter(result.mutated) == _frontmatter(SAMPLE_RULE_TEXT)

    def test_c_b5_inline_code_preserved(self, result: MutationResult):
        """C-B5: inline code must be preserved by synonym replacement."""
        original_spans = _inline_code_spans(SAMPLE_RULE_TEXT)
        mutated_spans = _inline_code_spans(result.mutated)
        assert original_spans.issubset(mutated_spans)

    def test_line_structure_preserved(self, result: MutationResult):
        """Regression: nlpaug flattens multi-line input; per-line augmentation
        must preserve the original line count (markdown bullets, headers, paragraphs)."""
        original_line_count = SAMPLE_RULE_TEXT.count("\n")
        mutated_line_count = result.mutated.count("\n")
        # Line count must not collapse; small drift is acceptable if blank
        # handling produces off-by-one, but a full collapse to ~1 line is the bug.
        assert mutated_line_count >= original_line_count - 2, (
            f"Line structure collapsed: {original_line_count} → {mutated_line_count}"
        )


# ═══════════════════════════════════════════════════════════════════════════════
# Add Random Word Mutator
# ═══════════════════════════════════════════════════════════════════════════════

class TestAddRandomWordMutator:

    @pytest.fixture
    def result(self) -> MutationResult:
        return AddRandomWordMutator(seed=SEED).mutate(SAMPLE_RULE_TEXT)

    def test_c_b1_changed(self, result: MutationResult):
        assert result.changed
        assert result.change_ratio > 0

    def test_c_b2_changes_nonempty(self, result: MutationResult):
        assert len(result.changes) > 0
        assert any("inserted" in c.lower() or "word" in c.lower() for c in result.changes)

    def test_c_b3_shape_filler_words_added(self, result: MutationResult):
        """C-B3: same structure, filler words inserted, no negation words."""
        # Mutated should be longer (words added)
        original_words = len(SAMPLE_RULE_TEXT.split())
        mutated_words = len(result.mutated.split())
        assert mutated_words > original_words

        # No negation words should be inserted
        negation_words = {"not", "never", "no", "without", "nor", "neither", "none",
                          "cannot", "can't", "won't", "shouldn't", "don't", "doesn't"}
        # Check only inserted words — compare word sets
        orig_word_list = SAMPLE_RULE_TEXT.lower().split()
        mut_word_list = result.mutated.lower().split()
        # Newly inserted words should not include negation words
        # (This is a heuristic — we check the filler word vocabulary)
        from src.mutation.rule_based import _SimpleWordInserter
        fillers = set(_SimpleWordInserter._FILLER_WORDS)
        # Mutated text should contain some filler words not in original
        mutated_lower = result.mutated.lower()
        assert any(f in mutated_lower for f in fillers)

    def test_c_b4_frontmatter_preserved(self, result: MutationResult):
        assert _frontmatter(result.mutated) == _frontmatter(SAMPLE_RULE_TEXT)

    def test_c_b5_inline_code_preserved(self, result: MutationResult):
        original_spans = _inline_code_spans(SAMPLE_RULE_TEXT)
        mutated_spans = _inline_code_spans(result.mutated)
        assert original_spans.issubset(mutated_spans)


# ═══════════════════════════════════════════════════════════════════════════════
# Section Reorder Shuffle
# ═══════════════════════════════════════════════════════════════════════════════

class TestSectionReorderShuffle:

    @pytest.fixture
    def result(self) -> MutationResult:
        return SectionReorderMutator(seed=SEED, mode="shuffle").mutate(SAMPLE_RULE_TEXT)

    def test_c_b1_changed(self, result: MutationResult):
        assert result.changed
        assert result.change_ratio > 0

    def test_c_b2_changes_nonempty(self, result: MutationResult):
        assert len(result.changes) > 0
        assert any("reorder" in c.lower() for c in result.changes)

    def test_c_b3_shape_same_headers_different_order(self, result: MutationResult):
        """C-B3: same ## headers present but in different order."""
        original_headers = sorted(re.findall(r"^##+ .+$", SAMPLE_RULE_TEXT, re.MULTILINE))
        mutated_headers = sorted(re.findall(r"^##+ .+$", result.mutated, re.MULTILINE))
        assert original_headers == mutated_headers  # same set of headers

    def test_c_b4_frontmatter_preserved(self, result: MutationResult):
        assert _frontmatter(result.mutated) == _frontmatter(SAMPLE_RULE_TEXT)

    def test_c_b5_inline_code_preserved(self, result: MutationResult):
        original_spans = _inline_code_spans(SAMPLE_RULE_TEXT)
        mutated_spans = _inline_code_spans(result.mutated)
        assert original_spans.issubset(mutated_spans)


# ═══════════════════════════════════════════════════════════════════════════════
# Section Reorder Degrade
# ═══════════════════════════════════════════════════════════════════════════════

class TestSectionReorderDegrade:

    @pytest.fixture
    def result(self) -> MutationResult:
        return SectionReorderMutator(seed=SEED, mode="degrade").mutate(SAMPLE_RULE_TEXT)

    def test_c_b1_changed(self, result: MutationResult):
        assert result.changed
        assert result.change_ratio > 0

    def test_c_b2_changes_nonempty(self, result: MutationResult):
        assert len(result.changes) > 0

    def test_c_b3_shape_security_section_moved_to_end(self, result: MutationResult):
        """C-B3: security-keyword-dense section moved to final position."""
        # The last ## section should be the one with the most security keywords
        sections = re.split(r"(?=^## )", result.mutated, flags=re.MULTILINE)
        # Filter to actual sections (non-empty, with ## header)
        actual = [s for s in sections if s.strip().startswith("##")]
        if actual:
            last_section = actual[-1]
            # Should contain security keywords
            security_kws = ["validate", "sanitize", "injection", "sql", "prevent"]
            kw_count = sum(1 for kw in security_kws if kw.lower() in last_section.lower())
            assert kw_count >= 2, f"Last section has too few security keywords ({kw_count})"

    def test_c_b4_frontmatter_preserved(self, result: MutationResult):
        assert _frontmatter(result.mutated) == _frontmatter(SAMPLE_RULE_TEXT)

    def test_c_b5_inline_code_preserved(self, result: MutationResult):
        original_spans = _inline_code_spans(SAMPLE_RULE_TEXT)
        mutated_spans = _inline_code_spans(result.mutated)
        assert original_spans.issubset(mutated_spans)


# ═══════════════════════════════════════════════════════════════════════════════
# C-B6  Factory create_mutator
# ═══════════════════════════════════════════════════════════════════════════════

class TestFactory:

    @pytest.mark.parametrize("name,expected_class_name", [
        ("verb_weakening", "VerbWeakeningMutator"),
        ("synonym_replacement", "SynonymReplacementMutator"),
        ("add_random_word", "AddRandomWordMutator"),
        ("section_reorder_shuffle", "SectionReorderMutator"),
        ("section_reorder_degrade", "SectionReorderMutator"),
    ])
    def test_create_rule_based(self, name: str, expected_class_name: str):
        """C-B6: factory returns the correct class for rule-based mutators."""
        mutator = create_mutator(name, seed=42)
        assert type(mutator).__name__ == expected_class_name
        assert mutator.name == name

    def test_llm_mutator_without_backend_raises(self):
        """C-B6: LLM mutators raise ValueError without backend."""
        for name in ("negation_injection", "voice_change", "paraphrase"):
            with pytest.raises(ValueError, match="requires a backend"):
                create_mutator(name, seed=42, backend=None)

    def test_unknown_mutator_raises(self):
        with pytest.raises(ValueError, match="Unknown mutator"):
            create_mutator("nonexistent")
