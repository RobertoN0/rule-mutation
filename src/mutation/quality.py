"""
Mutation quality validation — AUGMENT three-criteria framework.

Implements the quality-checking pipeline from Chataigner et al. 2025 (AUGMENT),
extended with a project-specific security-domain preservation criterion.

The validator is **post-hoc only** — it is never called inside the
hill-climbing inner loop.  It populates ``MutationResult.metadata['quality']``
and is used for analysis, reporting, and (for ParaphraseMutator) selecting the
best candidate from a set of generated options.

Five criteria
-------------
1. Instruction adherence  — did the mutation actually perform its intended
   transformation?  (difflib, stdlib only)
2. Semantic similarity    — is the meaning preserved?  (sentence-transformers
   ``all-mpnet-base-v2``, cosine similarity ≥ 0.75)
3. Realism (perplexity ratio) — is the mutated text linguistically natural?
   (perplexity ratio ≤ 2.0, computed with the caller-supplied LM handle)
4. Security-domain preservation — are all inline code tokens and core security
   vocabulary still present?  (ParsedRule + curated word list)
5. Readability delta      — Flesch-Kincaid grade level change (informational
   only, no pass/fail gate; requires ``textstat``)

Usage
-----
>>> from src.mutation.quality import MutationQualityValidator
>>> validator = MutationQualityValidator()                       # SBERT on, perplexity off
>>> validator = MutationQualityValidator(                        # perplexity on, shared model
...     use_perplexity=True,
...     ppl_model_handle=backend_model,
...     ppl_tokenizer_handle=backend_tokenizer,
... )
>>> result = mutator.mutate(rule_text)
>>> result = validator.validate(result)
>>> result.metadata["quality"]["passes_all"]        # bool
>>> result.metadata["quality"]["sbert_similarity"]  # float | None
"""

from __future__ import annotations

import difflib
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from .base import MutationResult
from .rule_parser import ParsedRule

if TYPE_CHECKING:
    from .base import Mutator

log = logging.getLogger(__name__)

from .security_lexicon import get_security_lexicon

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

    Character-set Jaccard was used previously but is always ≈1.0 for any two
    English texts (same ~70-char alphabet), making the check meaningless.
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
    use_perplexity:
        Enable the perplexity ratio gate.  Requires ``ppl_model_handle`` and
        ``ppl_tokenizer_handle`` to be set; if they are ``None`` a warning is
        logged and the gate is skipped.  Disabled by default.
    sbert_model:
        HuggingFace model name for the sentence encoder.
    ppl_model_handle:
        A pre-loaded ``transformers`` causal-LM model used to compute
        perplexity.  Pass the generation model (e.g. the 32B instance from
        ``DelftBlueLocalBackend``) so no second model is loaded.
    ppl_tokenizer_handle:
        The tokenizer paired with ``ppl_model_handle``.
    sbert_threshold:
        Minimum cosine similarity to pass the semantic similarity gate (0.75,
        AUGMENT default; Paper 6 LAP shows perplexity ratio ≤ 2.0 ↔
        SBERT ≥ 0.80 in >90% of cases — 0.75 is the AUGMENT-calibrated
        operating point).
    perplexity_threshold:
        Maximum perplexity ratio to pass the realism gate (2.0, from AUGMENT).
    keyword_threshold:
        Minimum security-keyword retention fraction (0.70).
    """

    use_sbert: bool = True
    use_perplexity: bool = False
    sbert_model: str = "sentence-transformers/all-mpnet-base-v2"
    ppl_model_handle: Any = field(default=None, repr=False, compare=False)
    ppl_tokenizer_handle: Any = field(default=None, repr=False, compare=False)
    sbert_threshold: float = 0.75
    perplexity_threshold: float = 2.0
    keyword_threshold: float = 0.70

    # Lazy-loaded SBERT handle; ppl handles are seeded from constructor args
    _sbert: Any = None
    _ppl_model: Any = None
    _ppl_tokenizer: Any = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "_sbert", None)
        object.__setattr__(self, "_ppl_model", self.ppl_model_handle)
        object.__setattr__(self, "_ppl_tokenizer", self.ppl_tokenizer_handle)

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

    def _get_ppl_model(self):
        """Return (model, tokenizer) for perplexity scoring, or (None, None).

        No model loading is performed here.  The handles must be supplied at
        construction via ``ppl_model_handle`` / ``ppl_tokenizer_handle``
        (typically the generation model shared from the hill-climber backend).
        If ``use_perplexity=True`` but no handle was provided, a warning is
        emitted and perplexity scoring is skipped for this run.
        """
        if self._ppl_model is None:
            log.warning(
                "use_perplexity=True but no ppl_model_handle was supplied; "
                "perplexity gate disabled for this run."
            )
        return self._ppl_model, self._ppl_tokenizer

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

    def _compute_perplexity_ratio(
        self, orig_prose: str, mut_prose: str
    ) -> float | None:
        """perplexity(mutated) / perplexity(original) using Qwen2.5-7B."""
        model, tokenizer = self._get_ppl_model()
        if model is None:
            return None
        try:
            import math
            import torch  # type: ignore

            def _ppl(text: str) -> float:
                inputs = tokenizer(
                    text,
                    return_tensors="pt",
                    truncation=True,
                    max_length=1024,
                ).to(model.device) # type: ignore
                with torch.no_grad():
                    loss = model(**inputs, labels=inputs["input_ids"]).loss
                return math.exp(float(loss))

            orig_ppl = _ppl(orig_prose)
            mut_ppl = _ppl(mut_prose)
            if orig_ppl == 0:
                return None
            return round(mut_ppl / orig_ppl, 4)
        except Exception as exc:
            log.warning("Perplexity computation failed: %s", exc)
            return None

    @staticmethod
    def _compute_readability(prose: str) -> float | None:
        """Flesch-Kincaid Grade Level (informational only)."""
        try:
            import textstat  # type: ignore
            return round(textstat.flesch_kincaid_grade(prose), 2) # type: ignore
        except ImportError:
            return None
        except Exception:
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

        # 3. Perplexity ratio
        perplexity_ratio: float | None = None
        if self.use_perplexity and result.changed:
            perplexity_ratio = self._compute_perplexity_ratio(orig_prose, mut_prose)

        # 4. Security-domain preservation
        inline_code_retention = self._compute_inline_code_retention(
            result.original, result.mutated
        )
        keyword_retention = self._compute_keyword_retention(orig_prose, mut_prose)
        security_intent_preserved = (
            inline_code_retention == 1.0
            and keyword_retention >= self.keyword_threshold
        )

        # 5. Readability (informational only)
        readability_orig = self._compute_readability(orig_prose)
        readability_mut = self._compute_readability(mut_prose)

        # Combined gate
        passes_all = (
            instruction_adherent
            and (sbert_similarity is None or sbert_similarity >= self.sbert_threshold)
            and (perplexity_ratio is None or perplexity_ratio <= self.perplexity_threshold)
            and inline_code_retention == 1.0
            and keyword_retention >= self.keyword_threshold
        )

        result.metadata["quality"] = {
            # Criterion 1
            "instruction_adherent": instruction_adherent,
            # Criterion 2: sbert_step = sim vs parent (single-step drift)
            "sbert_step": sbert_similarity,
            # Criterion 3
            "perplexity_ratio": perplexity_ratio,
            # Criterion 4
            "inline_code_retention": round(inline_code_retention, 4),
            "keyword_retention": round(keyword_retention, 4),
            "security_intent_preserved": security_intent_preserved,
            # Criterion 5 (informational)
            "readability_grade_original": readability_orig,
            "readability_grade_mutated": readability_mut,
            "readability_grade_delta": (
                round(readability_mut - readability_orig, 2)
                if readability_orig is not None and readability_mut is not None
                else None
            ),
            # Summary
            "passes_all": passes_all,
            "changed": result.changed,
        }

        return result

    def validate_batch(
        self, results: list[MutationResult]
    ) -> list[MutationResult]:
        """Validate a list of MutationResults (loads models once, reuses)."""
        return [self.validate(r) for r in results]

    def select_best_candidate(
        self, candidates: list[MutationResult]
    ) -> MutationResult:
        """Return the first candidate that passes all quality criteria.

        Used by ParaphraseMutator when multiple candidates are available.
        Falls back to the first candidate if none pass.

        Parameters
        ----------
        candidates:
            List of MutationResult objects.  They are validated in-place if
            not already validated.
        """
        for c in candidates:
            if "quality" not in c.metadata:
                self.validate(c)
            if c.metadata["quality"].get("passes_all", False):
                return c
        log.warning(
            "select_best_candidate: no candidate passed all criteria; "
            "returning first candidate."
        )
        return candidates[0]

    def to_csv_row(self, result: MutationResult) -> dict[str, Any]:
        """Flatten quality metrics to a dict suitable for CSV export."""
        q = result.metadata.get("quality", {})
        return {
            "mutation_type": result.mutation_type,
            "changed": result.changed,
            "change_ratio": round(result.change_ratio, 4),
            "instruction_adherent": q.get("instruction_adherent"),
            "sbert_similarity": q.get("sbert_similarity"),
            "perplexity_ratio": q.get("perplexity_ratio"),
            "inline_code_retention": q.get("inline_code_retention"),
            "keyword_retention": q.get("keyword_retention"),
            "security_intent_preserved": q.get("security_intent_preserved"),
            "readability_grade_original": q.get("readability_grade_original"),
            "readability_grade_mutated": q.get("readability_grade_mutated"),
            "readability_grade_delta": q.get("readability_grade_delta"),
            "passes_all": q.get("passes_all"),
        }

    def validate_with_retry(
        self,
        mutator: "Mutator",
        text: str,
        max_retries: int = 2,
    ) -> MutationResult:
        """Mutate + validate in-loop, with retry on failure.

        Designed for use inside the hill-climbing loop: call this instead of
        ``mutator.mutate()`` when in-loop validation is enabled.

        For **deterministic** mutators (``_temperature == 0.0``), only 1 attempt
        is made — retrying with the same input produces the same output (the
        ``DelftBlueLocalBackend`` uses ``do_sample=False`` when temperature≤0).

        For **non-deterministic** mutators (e.g. ``ParaphraseMutator``,
        temperature=0.3), each retry calls the LLM again and gets a genuinely
        different candidate.

        Parameters
        ----------
        mutator:
            The mutator to call.
        text:
            Original rule text to mutate.
        max_retries:
            Maximum number of attempts.  Ignored for deterministic mutators
            (capped at 1).

        Returns
        -------
        MutationResult
            The first result that passes all criteria.  If all retries fail,
            returns the best attempt (by SBERT similarity).  If even that is
            an identity (unchanged), returns a clean identity ``MutationResult``
            so the hill-climber treats this iteration as "no mutation".
        """
        is_deterministic = getattr(mutator, "_temperature", None) == 0.0
        effective_retries = 1 if is_deterministic else max_retries

        best_result: MutationResult | None = None
        best_sim: float = -1.0

        for attempt in range(effective_retries):
            result = mutator.mutate(text)

            if not result.changed:
                log.warning(
                    "validate_with_retry: attempt %d/%d produced identity "
                    "(mutator=%s)", attempt + 1, effective_retries, mutator.name,
                )
                if best_result is None:
                    best_result = result
                continue

            self.validate(result)
            quality = result.metadata.get("quality", {})

            if quality.get("passes_all", False):
                log.info(
                    "validate_with_retry: attempt %d/%d passed all criteria "
                    "(mutator=%s)", attempt + 1, effective_retries, mutator.name,
                )
                return result  # early exit on first passing candidate

            # Track best-so-far by SBERT similarity (step vs parent)
            sim = quality.get("sbert_step") or 0.0
            if sim > best_sim:
                best_sim = sim
                best_result = result

            log.warning(
                "validate_with_retry: attempt %d/%d failed validation "
                "(mutator=%s, passes_all=False, sbert=%.3f)",
                attempt + 1, effective_retries, mutator.name, sim,
            )

        # All retries exhausted ------------------------------------------------
        if best_result is None or not best_result.changed:
            log.warning(
                "validate_with_retry: all %d attempt(s) failed or were identity; "
                "returning identity (mutator=%s)",
                effective_retries, mutator.name,
            )
            return MutationResult(
                original=text, mutated=text,
                mutation_type=mutator.name,
                changes=["all validation retries failed; identity returned"],
                metadata={"quality": {
                    "passes_all": False,
                    "retries_exhausted": True,
                }},
            )

        # Return best attempt even though it failed validation (graceful degradation)
        log.warning(
            "validate_with_retry: returning best failed attempt "
            "(mutator=%s, sbert=%.3f)", mutator.name, best_sim,
        )
        return best_result
