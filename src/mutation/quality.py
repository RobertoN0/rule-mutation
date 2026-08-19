"""
Mutation quality validation for rule mutations.

Implements the quality-checking pipeline from Chataigner et al. 2025 (AUGMENT),
extended with a project-specific security-domain preservation criterion.

The validator is **informational only** — it never refuses a mutation and never
affects archive admission (which is Pareto dominance over f1/f2/f3).  When
``--enable-validation`` is set it runs once per mutation inside the loop (no
retry; identity mutations are skipped before code-gen); otherwise it is unused.
It populates ``MutationResult.metadata['quality']`` for analysis/reporting.

Three recorded signals
----------------------
1. Instruction adherence  — did the mutation actually perform its intended
   transformation?  (difflib, stdlib only)
2. Semantic similarity    — is the meaning preserved?  (sentence-transformers
   ``all-mpnet-base-v2``, continuous cosine similarity)
3. Security-domain retention — what fraction of inline code tokens and security
   vocabulary remains?  (ParsedRule + curated word list)

Usage
-----
>>> from src.mutation.quality import MutationQualityValidator
>>> validator = MutationQualityValidator()
>>> result = mutator.mutate(rule_text)
>>> result = validator.validate(result)
>>> result.metadata["quality"]["instruction_adherent"]  # bool
>>> result.metadata["quality"]["sbert_step"]             # float | None
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any

from .base import MutationResult
from .rule_parser import ParsedRule
from .security_lexicon import get_security_lexicon

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Instruction-adherence check specs (per mutator name)
# ---------------------------------------------------------------------------

# Each spec is a callable that takes (original_prose, mutated_prose) → bool
def _adherence_synonym(orig: str, mut: str) -> bool:
    """Synonym replacement: text changed; word count may grow slightly.

    WordNet synonyms are sometimes multi-word phrases (e.g. "verify" →
    "make certain"), so the mutated word count can exceed the original.
    We allow up to a 50% increase to accommodate multi-word substitutions
    while rejecting wholesale insertions.
    """
    if orig == mut:
        return False
    orig_n = len(orig.split())
    mut_n = len(mut.split())
    # Allow multi-word synonyms (up to +50% words), disallow word deletions
    return mut_n >= orig_n and mut_n <= orig_n * 1.5


def _adherence_add_word(orig: str, mut: str) -> bool:
    """AddRandomWord: mutated text must have more words than original."""
    return len(mut.split()) > len(orig.split())


def _adherence_section_reorder(orig: str, mut: str) -> bool:
    """SectionReorder: same sections, different order.

    Two paths depending on rule structure:

    Section-level path (rule has ##/### headers):
        The set of header lines is unchanged but their order differs.

    Paragraph-fallback path (rule has no ##/### headers):
        SectionReorderMutator falls back to reordering double-newline-separated
        prose paragraphs.  We verify that the paragraph sequence changed while
        the paragraph set is identical.
    """
    orig_headers = re.findall(r"^#{2,4}\s+.+", orig, re.MULTILINE)
    mut_headers = re.findall(r"^#{2,4}\s+.+", mut, re.MULTILINE)

    # Section-level path: mirrors the mutator's condition (len(actual_sections) >= 2).
    # A rule with exactly 1 header has only 1 section — the mutator falls back to
    # paragraph reordering, so adherence must also use the paragraph path.
    if len(orig_headers) >= 2 and len(mut_headers) >= 2:
        return sorted(orig_headers) == sorted(mut_headers) and orig_headers != mut_headers

    # Paragraph-fallback path: < 2 headers → mutator reordered prose paragraphs
    orig_paras = [p.strip() for p in re.split(r"\n\n+", orig) if p.strip()]
    mut_paras = [p.strip() for p in re.split(r"\n\n+", mut) if p.strip()]
    return sorted(orig_paras) == sorted(mut_paras) and orig_paras != mut_paras


def _adherence_negation(orig: str, mut: str) -> bool:
    """NegationInjection: at least one negation marker present in mutated.

    Covers both the soft advisory patterns the prompt targets and the direct
    negation forms ("do not", "never") that the LLM naturally produces.
    """
    markers = [
        # soft / advisory forms
        "not required", "while not", "not always", "not strictly",
        "optional", "not necessary", "advisory",
        # direct negation forms the LLM commonly uses
        "do not", "don't", "never", "must not", "should not",
        "shouldn't", "avoid", "do not fail",
    ]
    lower = mut.lower()
    return any(m in lower for m in markers)


def _adherence_voice(orig: str, mut: str) -> bool:
    """VoiceChange: passive construction present in mutated."""
    markers = [
        "should be", "is recommended", "ought to be",
        "is advised", "are recommended", "must be",
    ]
    lower = mut.lower()
    return any(m in lower for m in markers)


def _adherence_paraphrase(orig: str, mut: str) -> bool:
    """Paraphrase: word-level Jaccard in (0.15, 0.995) — changed but not destroyed.

    Word-level (not character-set) Jaccard: char-set Jaccard is ≈1.0 for any
    two English texts (same ~70-char alphabet) and can't detect paraphrase.
    Word-level Jaccard correctly detects both identical texts (J≈1) and
    completely unrelated outputs (J≈0), while accepting valid paraphrases
    that reuse some vocabulary.

    The upper bound is 0.995 (not 0.98) because short security rules have
    limited synonymisable vocabulary — a valid paraphrase of a 50-word rule
    may change only 1-2 words, keeping Jaccard near 0.98.  The only case we
    want to reject above 0.995 is a pure copy with no lexical change at all,
    which is already caught by the ``result.changed`` check upstream.
    The lower bound 0.15 guards against completely hallucinated outputs.
    """
    orig_words = set(orig.lower().split())
    mut_words = set(mut.lower().split())
    if not orig_words and not mut_words:
        return False
    j = len(orig_words & mut_words) / len(orig_words | mut_words)
    return 0.15 < j < 0.995  # changed but not destroyed


_ADHERENCE_FUNCS: dict[str, Any] = {
    "synonym_replacement": _adherence_synonym,
    "add_random_word":     _adherence_add_word,
    "section_reorder_shuffle": _adherence_section_reorder,
    "section_reorder_degrade": _adherence_section_reorder,
    "negation_injection":  _adherence_negation,
    "voice_change":        _adherence_voice,
    "paraphrase":          _adherence_paraphrase,
    "verb_weakening":      lambda o, m: m != o,
}


# ---------------------------------------------------------------------------
# Main validator class
# ---------------------------------------------------------------------------

@dataclass
class MutationQualityValidator:
    """Compute and store quality metrics for a MutationResult.

    Parameters
    ----------
    use_sbert:
        Load and use ``sentence-transformers/all-mpnet-base-v2`` for semantic
        similarity.  Requires the model to be pre-downloaded to HF cache.
        Skipped gracefully if ``sentence-transformers`` is not installed.
    sbert_model:
        HuggingFace model name for the sentence encoder.
    """

    use_sbert: bool = True
    sbert_model: str = "sentence-transformers/all-mpnet-base-v2"

    # Lazy-loaded SBERT handle.
    _sbert: Any = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "_sbert", None)

    # ------------------------------------------------------------------
    # Lazy model loaders
    # ------------------------------------------------------------------

    def _get_sbert(self):
        if self._sbert is not None:
            return self._sbert
        try:
            from sentence_transformers import SentenceTransformer  # type: ignore
            log.info("Loading SBERT model %s …", self.sbert_model)
            model = SentenceTransformer(self.sbert_model)
            object.__setattr__(self, "_sbert", model)
            return model
        except ImportError:
            log.warning(
                "sentence-transformers not installed; SBERT similarity will be None. "
                "Install with: pip install sentence-transformers"
            )
            return None
        except Exception as exc:
            log.warning("Failed to load SBERT model %s: %s", self.sbert_model, exc)
            return None

    # ------------------------------------------------------------------
    # Metric helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_prose_text(text: str) -> str:
        """Return concatenated mutable prose blocks (no frontmatter, no code).

        Blocks are joined with a newline so that headers at the start of a
        block (e.g. ``## Section``) remain at the beginning of a line in the
        concatenated string, allowing multiline regex patterns to match them.
        """
        parsed = ParsedRule.parse(text)
        parts = [block_text for _, block_text in parsed.get_mutable_prose()]
        return "\n".join(parts)

    @staticmethod
    def _compute_keyword_retention(original: str, mutated: str) -> float:
        """Fraction of security keywords from original still present in mutated."""
        orig_lower = original.lower()
        mut_lower = mutated.lower()
        present_in_orig = [kw for kw in get_security_lexicon() if kw in orig_lower]
        if not present_in_orig:
            return 1.0  # no keywords → trivially retained
        still_present = [kw for kw in present_in_orig if kw in mut_lower]
        return len(still_present) / len(present_in_orig)

    @staticmethod
    def _compute_inline_code_retention(original: str, mutated: str) -> float:
        """Fraction of backtick-wrapped tokens from original still verbatim in mutated."""
        orig_tokens = ParsedRule.get_inline_code_tokens(original)
        if not orig_tokens:
            return 1.0
        still_present = [t for t in orig_tokens if t in mutated]
        return len(still_present) / len(orig_tokens)

    def _compute_sbert_similarity(self, orig_prose: str, mut_prose: str) -> float | None:
        """Cosine similarity between sentence-embedded document vectors."""
        sbert = self._get_sbert()
        if sbert is None:
            return None
        try:
            from sklearn.metrics.pairwise import cosine_similarity  # type: ignore

            orig_emb = sbert.encode([orig_prose])
            mut_emb = sbert.encode([mut_prose])
            sim = float(cosine_similarity(orig_emb, mut_emb)[0][0])
            return round(sim, 4)
        except Exception as exc:
            log.warning("SBERT similarity computation failed: %s", exc)
            return None

    # ------------------------------------------------------------------
    # Instruction adherence
    # ------------------------------------------------------------------

    @staticmethod
    def _check_instruction_adherence(result: MutationResult) -> bool:
        """Verify the mutation actually performed its intended transformation."""
        func = _ADHERENCE_FUNCS.get(result.mutation_type)
        if func is None:
            # Unknown mutator type: pass if text changed at all
            return result.changed

        # section_reorder adherence must operate on the raw body, not prose-extracted
        # text.  _extract_prose_text joins blocks with a single "\n", destroying the
        # "\n\n" separators that the paragraph-fallback branch of
        # _adherence_section_reorder needs to split paragraphs correctly.
        _SECTION_REORDER_MUTATORS = {"section_reorder_shuffle", "section_reorder_degrade"}
        if result.mutation_type in _SECTION_REORDER_MUTATORS:
            orig_text = ParsedRule.parse(result.original).body_raw
            mut_text = ParsedRule.parse(result.mutated).body_raw
        else:
            orig_text = MutationQualityValidator._extract_prose_text(result.original)
            mut_text = MutationQualityValidator._extract_prose_text(result.mutated)

        return func(orig_text, mut_text)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def validate(self, result: MutationResult) -> MutationResult:
        """Compute all quality metrics and store them in result.metadata['quality'].

        Parameters
        ----------
        result:
            A MutationResult from any mutator.

        Returns
        -------
        The same MutationResult object with ``metadata['quality']`` populated.
        """
        orig_prose = self._extract_prose_text(result.original)
        mut_prose = self._extract_prose_text(result.mutated)

        # 1. Instruction adherence
        instruction_adherent = self._check_instruction_adherence(result)

        # 2. Semantic similarity
        sbert_similarity: float | None = None
        if self.use_sbert and result.changed:
            sbert_similarity = self._compute_sbert_similarity(orig_prose, mut_prose)

        # 3. Security-domain preservation
        inline_code_retention = self._compute_inline_code_retention(
            result.original, result.mutated
        )
        keyword_retention = self._compute_keyword_retention(orig_prose, mut_prose)
        result.metadata["quality"] = {
            # Criterion 1
            "instruction_adherent": instruction_adherent,
            # Criterion 2: sbert_step = sim vs parent (single-step drift)
            "sbert_step": sbert_similarity,
            # Criterion 3
            "inline_code_retention": round(inline_code_retention, 4),
            "keyword_retention": round(keyword_retention, 4),
            "changed": result.changed,
        }

        return result

    def validate_batch(
        self, results: list[MutationResult]
    ) -> list[MutationResult]:
        """Validate a list of MutationResults (loads models once, reuses)."""
        return [self.validate(r) for r in results]

    def to_csv_row(self, result: MutationResult) -> dict[str, Any]:
        """Flatten quality metrics to a dict suitable for CSV export."""
        q = result.metadata.get("quality", {})
        return {
            "mutation_type": result.mutation_type,
            "changed": result.changed,
            "change_ratio": round(result.change_ratio, 4),
            "instruction_adherent": q.get("instruction_adherent"),
            "sbert_step": q.get("sbert_step"),
            "inline_code_retention": q.get("inline_code_retention"),
            "keyword_retention": q.get("keyword_retention"),
        }
