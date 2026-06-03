"""Unit tests for the security keyword lexicon (Change 2 / Thread 5).

Covers:
  C-L1  Hardcoded lexicon has expected size and contains known CWE terms
  C-L2  get_security_lexicon() ignores rules_dir — always returns the pinned set
  C-L3  build_security_lexicon() reads actual corpus and returns a frozenset
  C-L4  Overlap between corpus-derived and hardcoded lexicons is substantial
"""

from pathlib import Path

import pytest

from src.mutation.security_lexicon import (
    _SECURITY_LEXICON,
    build_security_lexicon,
    get_security_lexicon,
)

# Path to the real CodeGuard rules directory (23 .md files)
_RULES_DIR = Path(__file__).parents[2] / "project-codeguard" / "skills" / "software-security" / "rules"


# ═══════════════════════════════════════════════════════════════════════════════
# C-L1  Hardcoded lexicon size and content
# ═══════════════════════════════════════════════════════════════════════════════

class TestHardcodedLexicon:

    def test_lexicon_size(self):
        """C-L1: hardcoded lexicon has at least 50 terms."""
        assert len(_SECURITY_LEXICON) >= 50

    def test_lexicon_is_frozenset(self):
        """C-L1: lexicon is an immutable frozenset."""
        assert isinstance(_SECURITY_LEXICON, frozenset)

    def test_contains_core_security_terms(self):
        """C-L1: key CWE/security terms are present."""
        required = {"injection", "authentication", "authorization", "validation",
                    "encryption", "credentials", "permissions", "secure"}
        missing = required - _SECURITY_LEXICON
        assert not missing, f"Missing core security terms: {missing}"

    def test_no_stopwords(self):
        """C-L1: common English stopwords are absent."""
        stopwords = {"the", "and", "or", "is", "in", "of", "to", "a", "an"}
        present = stopwords & _SECURITY_LEXICON
        assert not present, f"Stopwords found in lexicon: {present}"

    def test_lowercase_only(self):
        """C-L1: all terms are lowercase (no mixed-case artifacts)."""
        for term in _SECURITY_LEXICON:
            assert term == term.lower(), f"Non-lowercase term: {term!r}"

    def test_no_short_tokens(self):
        """C-L1: no tokens of length ≤ 2 (stopword-removal threshold)."""
        short = {t for t in _SECURITY_LEXICON if len(t) <= 2}
        assert not short, f"Short tokens found: {short}"


# ═══════════════════════════════════════════════════════════════════════════════
# C-L2  get_security_lexicon() ignores rules_dir
# ═══════════════════════════════════════════════════════════════════════════════

class TestGetSecurityLexicon:

    def test_returns_hardcoded_set(self):
        """C-L2: get_security_lexicon() returns the pinned _SECURITY_LEXICON."""
        result = get_security_lexicon()
        assert result is _SECURITY_LEXICON

    def test_ignores_rules_dir_argument(self):
        """C-L2: passing any Path (or None) returns the same hardcoded set."""
        result_none = get_security_lexicon(None)
        result_fake = get_security_lexicon(Path("/nonexistent/dir"))
        result_real = get_security_lexicon(_RULES_DIR)
        assert result_none is _SECURITY_LEXICON
        assert result_fake is _SECURITY_LEXICON
        assert result_real is _SECURITY_LEXICON


# ═══════════════════════════════════════════════════════════════════════════════
# C-L3  build_security_lexicon() reads actual corpus
# ═══════════════════════════════════════════════════════════════════════════════

class TestBuildSecurityLexicon:

    @pytest.fixture(scope="class")
    def corpus_lexicon(self):
        """Build once for all tests in this class."""
        if not _RULES_DIR.exists():
            pytest.skip(f"CodeGuard rules dir not found: {_RULES_DIR}")
        return build_security_lexicon(_RULES_DIR, top_n=60, min_doc_freq=2)

    def test_returns_frozenset(self, corpus_lexicon):
        """C-L3: build_security_lexicon returns a frozenset."""
        assert isinstance(corpus_lexicon, frozenset)

    def test_size_bounded_by_top_n(self, corpus_lexicon):
        """C-L3: result size ≤ top_n."""
        assert len(corpus_lexicon) <= 60

    def test_nonempty(self, corpus_lexicon):
        """C-L3: at least one term extracted from corpus."""
        assert len(corpus_lexicon) > 0

    def test_terms_are_lowercase(self, corpus_lexicon):
        """C-L3: all terms lowercase."""
        for term in corpus_lexicon:
            assert term == term.lower()

    def test_min_doc_freq_respected(self):
        """C-L3: with min_doc_freq=23 (all files), result is smaller."""
        if not _RULES_DIR.exists():
            pytest.skip(f"CodeGuard rules dir not found: {_RULES_DIR}")
        strict = build_security_lexicon(_RULES_DIR, top_n=60, min_doc_freq=23)
        loose = build_security_lexicon(_RULES_DIR, top_n=60, min_doc_freq=1)
        assert len(strict) <= len(loose)


# ═══════════════════════════════════════════════════════════════════════════════
# C-L4  Overlap between corpus-derived and hardcoded lexicons
# ═══════════════════════════════════════════════════════════════════════════════

class TestLexiconOverlap:

    def test_substantial_overlap_with_hardcoded(self):
        """C-L4: corpus-derived lexicon shares ≥ 50% of terms with the hardcoded set."""
        if not _RULES_DIR.exists():
            pytest.skip(f"CodeGuard rules dir not found: {_RULES_DIR}")
        corpus = build_security_lexicon(_RULES_DIR, top_n=60, min_doc_freq=2)
        overlap = corpus & _SECURITY_LEXICON
        overlap_ratio = len(overlap) / len(_SECURITY_LEXICON)
        assert overlap_ratio >= 0.5, (
            f"Only {overlap_ratio:.0%} overlap between corpus and hardcoded lexicon. "
            f"Shared: {sorted(overlap)}"
        )
