"""
Rule-based mutation operators.

These mutations apply deterministic transformations to security rule text:
verb weakening, synonym replacement, word insertion, and section reordering.
"""

from __future__ import annotations

import random
import re

from .base import Mutator, MutationResult
from .rule_parser import ParsedRule, mask_inline_code, unmask_inline_code


# ═══════════════════════════════════════════════════════════════════════════════
# VERB WEAKENING MUTATOR
# ═══════════════════════════════════════════════════════════════════════════════

# Verb weakening replacements
VERB_WEAKENING_MAP = {
    "MUST": "should ideally",
    "NEVER": "try to avoid",
    "ALWAYS": "when possible",
    "SHALL": "may want to",
    "REQUIRED": "recommended",
    "MANDATORY": "suggested",
    "Ensure": "Try to ensure",
    "Prevent": "Consider preventing",
    "Validate": "Consider validating",
    "Reject": "Consider rejecting",
    "Block": "Consider blocking",
}



class VerbWeakeningMutator(Mutator):
    """Weaken imperative verbs without adding fluff.
    
    Transforms strong directives (MUST, NEVER) into suggestions
    (should ideally, try to avoid).
    """
    
    def __init__(
        self,
        seed: int | None = None,
        replacements: dict[str, str] | None = None,
    ):
        """Initialize VerbWeakeningMutator.
        
        Args:
            seed: Random seed (not used currently, for API consistency).
            replacements: Custom replacement map (uses defaults if None).
        """
        super().__init__(seed)
        self.replacements = replacements or VERB_WEAKENING_MAP
    
    @property
    def name(self) -> str:
        return "verb_weakening"
    
    def mutate(self, text: str) -> MutationResult:
        """Weaken imperative verbs in the document body.

        Frontmatter is preserved unchanged.
        """
        parsed = ParsedRule.parse(text)
        changes = []
        body = parsed.body_raw

        for strong, weak in self.replacements.items():
            count = body.count(strong)
            if count > 0:
                body = body.replace(strong, weak)
                changes.append(f"{strong} → {weak} ({count}x)")

        mutated = parsed.frontmatter_raw + body
        return MutationResult(
            original=text,
            mutated=mutated,
            mutation_type=self.name,
            changes=changes,
        )


# ═══════════════════════════════════════════════════════════════════════════════
# SYNONYM REPLACEMENT MUTATOR — Paper 3 silver bullet
# ═══════════════════════════════════════════════════════════════════════════════

class SynonymReplacementMutator(Mutator):
    """Replace words in prose sections with WordNet synonyms.

    Source: Hyun et al. 2025 (Paper 3) silver bullet SynonymReplacement(),
    implemented via ``nlpaug.augmenter.word.SynonymAug`` with WordNet backend.

    Operates on prose blocks only (safe-zone-aware via ParsedRule).
    Inline code spans within prose are masked before augmentation and restored
    afterwards so that algorithm names, CWE IDs, and function names are never
    modified.

    Requires: ``nlpaug``, ``nltk`` + NLTK WordNet corpus downloaded once:
        python -m nltk.downloader wordnet omw-1.4
    """

    def __init__(
        self,
        seed: int | None = None,
        aug_p: float = 0.3,
    ):
        """
        Parameters
        ----------
        seed:
            Random seed for reproducibility.
        aug_p:
            Fraction of eligible words to replace (0.0–1.0, default 0.3).
        """
        super().__init__(seed)
        self.aug_p = aug_p
        self._aug = None  # lazy-loaded

    @property
    def name(self) -> str:
        return "synonym_replacement"

    def _get_aug(self):
        if self._aug is None:
            try:
                # nlpaug 1.1.x ships regex string literals with unescaped \s
                # (context_word_embs.py), which Python 3.12 flags as
                # SyntaxWarning at import. We only use the WordNet SynonymAug,
                # never ContextualWordEmbsAug — suppress the noise.
                import warnings
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore", SyntaxWarning)
                    import nlpaug.augmenter.word as naw  # type: ignore
                self._aug = naw.SynonymAug(aug_src="wordnet", aug_p=self.aug_p)
            except ImportError as exc:
                raise ImportError(
                    "nlpaug is required for SynonymReplacementMutator. "
                ) from exc
        return self._aug

    def mutate(self, text: str) -> MutationResult:
        aug = self._get_aug()
        parsed = ParsedRule.parse(text)
        prose_blocks = parsed.get_mutable_prose()

        if not prose_blocks:
            return MutationResult(
                original=text, mutated=text,
                mutation_type=self.name, changes=["no mutable prose blocks found"],
            )

        mutations: dict[int, str] = {}
        changes: list[str] = []

        # nlpaug flattens multi-line input to a single line, destroying the
        # markdown structure of prose blocks (bullets, paragraphs, ### headers).
        # Augment line-by-line and rejoin to preserve the original layout.
        for block_id, block_text in prose_blocks:
            lines = block_text.splitlines(keepends=True)
            augmented_lines: list[str] = []
            any_changed = False
            for line in lines:
                bare = line.rstrip("\n")
                trailing_nl = "\n" if line.endswith("\n") else ""
                if not bare.strip():
                    augmented_lines.append(line)
                    continue
                masked, restore_map = mask_inline_code(bare)
                try:
                    result = aug.augment(masked)
                    aug_line = result[0] if isinstance(result, list) else result
                except Exception:
                    aug_line = masked
                restored = unmask_inline_code(aug_line, restore_map)  # type: ignore
                augmented_lines.append(restored + trailing_nl)
                if restored != bare:
                    any_changed = True

            if any_changed:
                mutations[block_id] = "".join(augmented_lines)
                changes.append(f"block {block_id}: synonym replacement applied")

        if not mutations:
            return MutationResult(
                original=text, mutated=text,
                mutation_type=self.name, changes=["no synonyms found to replace"],
            )

        mutated = parsed.reconstruct(mutations)
        return MutationResult(
            original=text,
            mutated=mutated,
            mutation_type=self.name,
            changes=changes,
        )


# ═══════════════════════════════════════════════════════════════════════════════
# ADD RANDOM WORD MUTATOR — Paper 3 silver bullet
# ═══════════════════════════════════════════════════════════════════════════════

# Words that the masked language model must NOT insert.
# These would silently invert the security rule's meaning and overlap
# with the separate NegationInjectionMutator intent.
_NEGATION_STOPWORDS = [
    "not", "never", "no", "without", "nor", "neither", "none",
    "cannot", "can't", "won't", "shouldn't", "don't", "doesn't",
    "isn't", "aren't", "wasn't", "weren't",
]


class _SimpleWordInserter:
    """Pure-Python drop-in for nlpaug's augment() interface.

    Inserts low-signal filler words (adverbs, connectors) at randomly
    chosen word boundaries.  Requires no external model — the original
    nlpaug.ContextualWordEmbsAug backend was incompatible with
    transformers>=5.0 (removed ``_convert_token_to_id`` private API).

    Faithful to Hyun et al. 2025 AddRandomWord() which is described as
    simple random word insertion, not contextual/MLM-based insertion.
    """

    _FILLER_WORDS = [
        "generally", "typically", "commonly", "effectively",
        "specifically", "particularly", "appropriately", "carefully",
        "properly", "consistently", "accordingly", "additionally",
        "furthermore", "therefore", "subsequently", "explicitly",
        "fundamentally", "sufficiently", "routinely", "diligently",
    ]

    def __init__(
        self,
        aug_p: float,
        stopwords: "list[str]",
        rng: "random.Random",
    ) -> None:
        self.aug_p = aug_p
        self._stopwords = set(s.lower() for s in stopwords)
        self._rng = rng
        self._candidates = [
            w for w in self._FILLER_WORDS if w not in self._stopwords
        ]

    def augment(self, text: str) -> str:
        words = text.split(" ")
        if len(words) < 2:
            return text
        n_insert = max(1, int(len(words) * self.aug_p))
        n_insert = min(n_insert, len(words) - 1)
        positions = sorted(
            self._rng.sample(range(1, len(words)), n_insert),
            reverse=True,  # insert from end so earlier indices stay valid
        )
        for pos in positions:
            words.insert(pos, self._rng.choice(self._candidates))
        return " ".join(words)


class AddRandomWordMutator(Mutator):
    """Insert low-signal filler words into prose sections.

    Source: Hyun et al. 2025 (Paper 3) silver bullet AddRandomWord().

    Inserts adverbs and connectors (e.g. "generally", "typically",
    "additionally") at randomly chosen word boundaries.  Uses no external
    model — operates entirely in Python.

    The negation stopword list prevents words like "not" or "never" from
    being inserted (which would invert the rule's meaning and overlap with
    NegationInjectionMutator).

    Operates on prose blocks only (safe-zone-aware via ParsedRule).
    """

    def __init__(
        self,
        seed: int | None = None,
        aug_p: float = 0.1,
        stopwords: "list[str] | None" = None,
    ):
        """
        Parameters
        ----------
        seed:
            Random seed.
        aug_p:
            Fraction of words to insert (default 0.1 — keep insertions sparse).
        stopwords:
            Words that must not be inserted. Defaults to ``_NEGATION_STOPWORDS``.
        """
        super().__init__(seed)
        self.aug_p = aug_p
        self.stopwords = stopwords if stopwords is not None else _NEGATION_STOPWORDS
        self._aug = None  # lazy-initialised

    @property
    def name(self) -> str:
        return "add_random_word"

    def _get_aug(self) -> _SimpleWordInserter:
        if self._aug is None:
            self._aug = _SimpleWordInserter(
                aug_p=self.aug_p,
                stopwords=self.stopwords,
                rng=self.rng,
            )
        return self._aug

    def mutate(self, text: str) -> MutationResult:
        aug = self._get_aug()
        parsed = ParsedRule.parse(text)
        prose_blocks = parsed.get_mutable_prose()

        if not prose_blocks:
            return MutationResult(
                original=text, mutated=text,
                mutation_type=self.name, changes=["no mutable prose blocks found"],
            )

        mutations: dict[int, str] = {}
        changes: list[str] = []

        for block_id, block_text in prose_blocks:
            masked, restore_map = mask_inline_code(block_text)
            try:
                augmented = aug.augment(masked)
                if isinstance(augmented, list):
                    augmented = augmented[0] if augmented else masked
            except Exception:
                augmented = masked

            restored = unmask_inline_code(augmented, restore_map)

            if restored != block_text:
                orig_words = len(block_text.split())
                new_words = len(restored.split())
                mutations[block_id] = restored
                changes.append(
                    f"block {block_id}: inserted {new_words - orig_words} word(s)"
                )

        if not mutations:
            return MutationResult(
                original=text, mutated=text,
                mutation_type=self.name, changes=["no insertions made"],
            )

        mutated = parsed.reconstruct(mutations)
        return MutationResult(
            original=text,
            mutated=mutated,
            mutation_type=self.name,
            changes=changes,
        )


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION REORDER MUTATOR — LLMORPH MR-19/107
# ═══════════════════════════════════════════════════════════════════════════════

from .security_lexicon import get_security_lexicon


class SectionReorderMutator(Mutator):
    """Reorder top-level (##) sections of a security rule document.

    Source: Cho et al. (LLMORPH) MR-19 (shuffle sentences) / MR-107
    (shuffle paragraphs), adapted to section-level reordering.

    Two modes
    ---------
    shuffle:
        Seeded-random permutation of all sections (excluding the preamble
        before the first ## header, which always stays first).
    degrade:
        Move the section whose body contains the highest count of security
        keywords to the final position.  This maximally exploits recency bias
        in LLMs — critical security guidance appears last.

    Operates on sections only (safe-zone-aware via ParsedRule).
    Frontmatter, code blocks, and inline code are never modified.
    """

    def __init__(
        self,
        seed: int | None = None,
        mode: str = "shuffle",
    ):
        """
        Parameters
        ----------
        seed:
            Random seed for reproducibility in shuffle mode.
        mode:
            "shuffle" (random reorder) or "degrade" (critical section last).
        """
        super().__init__(seed)
        if mode not in ("shuffle", "degrade"):
            raise ValueError(f"mode must be 'shuffle' or 'degrade', got {mode!r}")
        self.mode = mode

    @property
    def name(self) -> str:
        return f"section_reorder_{self.mode}"

    def _count_security_keywords(self, text: str) -> int:
        lower = text.lower()
        return sum(kw in lower for kw in get_security_lexicon())

    def _reorder_paragraphs(self, body: str) -> tuple[str, list[str]]:
        """Fallback: reorder double-newline-separated paragraphs within body.

        Used when the rule has fewer than 2 header-level sections.
        Paragraphs that start with a Markdown header (``#``) or a fenced code
        block (`` ``` ``) are pinned to their original positions — only prose
        paragraphs are shuffled.
        Returns (reordered_body, changes).
        """
        import re as _re
        # Split on blank lines; keep delimiters to allow exact reconstruction.
        # parts alternates: [text, sep, text, sep, ...]
        parts = _re.split(r"(\n\n+)", body)

        # Collect (index_in_parts, text) for non-empty paragraphs
        all_text = [(i, parts[i]) for i in range(0, len(parts), 2) if parts[i].strip()]

        # Separate pinned (headers, code blocks) from movable (prose) paragraphs
        def _is_pinned(text: str) -> bool:
            stripped = text.lstrip()
            return stripped.startswith("#") or stripped.startswith("```")

        pinned = [(i, t) for i, t in all_text if _is_pinned(t)]
        movable_indices = [i for i, t in all_text if not _is_pinned(t)]
        movable_texts = [parts[i] for i in movable_indices]

        if len(movable_texts) < 2:
            return body, ["not enough movable paragraphs to reorder (need ≥2)"]

        original_snippets = [t[:40].replace("\n", " ") for t in movable_texts]

        if self.mode == "shuffle":
            reordered_texts = movable_texts[:]
            self.rng.shuffle(reordered_texts)
        else:  # degrade
            scores = [self._count_security_keywords(t) for t in movable_texts]
            max_idx = scores.index(max(scores))
            reordered_texts = movable_texts[:]
            critical = reordered_texts.pop(max_idx)
            reordered_texts.append(critical)

        new_snippets = [t[:40].replace("\n", " ") for t in reordered_texts]
        if reordered_texts == movable_texts:
            return body, ["paragraph reorder produced same order; identity"]

        for idx_in_parts, new_text in zip(movable_indices, reordered_texts):
            parts[idx_in_parts] = new_text

        changes = [
            f"paragraph-fallback {self.mode}: {original_snippets} → {new_snippets}"
        ]
        return "".join(parts), changes

    def mutate(self, text: str) -> MutationResult:
        parsed = ParsedRule.parse(text)
        sections = parsed.sections

        # Separate preamble (level 0) from actual sections
        preamble_sections = [s for s in sections if s.header_level == 0]
        actual_sections = [s for s in sections if s.header_level > 0]

        changes: list[str] = []

        if len(actual_sections) < 2:
            # Fallback: reorder paragraphs within the body when there are
            # insufficient header-level sections (common for short C/logging rules).
            new_body, para_changes = self._reorder_paragraphs(parsed.body_raw)
            if new_body == parsed.body_raw:
                return MutationResult(
                    original=text, mutated=text,
                    mutation_type=self.name,
                    changes=para_changes,
                )
            mutated = parsed.frontmatter_raw + new_body
            return MutationResult(
                original=text, mutated=mutated,
                mutation_type=self.name,
                changes=para_changes,
            )

        original_order = [s.header.strip() for s in actual_sections]

        if self.mode == "shuffle":
            reordered = actual_sections[:]
            self.rng.shuffle(reordered)
        else:  # degrade
            scores = [self._count_security_keywords(s.body) for s in actual_sections]
            max_idx = scores.index(max(scores))
            reordered = actual_sections[:]
            critical = reordered.pop(max_idx)
            reordered.append(critical)
            changes.append(
                f"degrade: moved '{critical.header.strip()}' "
                f"(score={scores[max_idx]}) to last position"
            )

        new_order = [s.header.strip() for s in reordered]
        if new_order != original_order:
            changes.insert(0, f"reordered sections: {original_order} → {new_order}")

        final_sections = preamble_sections + reordered
        mutated = parsed.reconstruct_from_sections(final_sections)

        return MutationResult(
            original=text,
            mutated=mutated,
            mutation_type=self.name,
            changes=changes,
        )


# ═══════════════════════════════════════════════════════════════════════════════
# FACTORY FUNCTIONS
# ═══════════════════════════════════════════════════════════════════════════════

def create_research_battery(
    seed: int | None = None,
    backend: "object | None" = None,
) -> list[tuple[str, Mutator]]:
    """Return all implemented mutators for systematic evaluation.

    Each entry is (name, mutator_instance).  The LLM-based mutators
    (NegationInjectionMutator, VoiceChangeMutator, ParaphraseMutator) are
    only included when ``backend`` is provided; they require a live
    ``LLMBackend`` instance.
    """
    battery: list[tuple[str, Mutator]] = [
        ("synonym_replacement",     SynonymReplacementMutator(seed=seed)),
        ("add_random_word",         AddRandomWordMutator(seed=seed)),
        ("section_reorder_shuffle", SectionReorderMutator(seed=seed, mode="shuffle")),
        ("section_reorder_degrade", SectionReorderMutator(seed=seed, mode="degrade")),
        ("verb_weakening",          VerbWeakeningMutator(seed=seed)),
    ]

    if backend is not None:
        try:
            from .llm_based import (  # type: ignore
                NegationInjectionMutator,
                VoiceChangeMutator,
                ParaphraseMutator,
            )
            battery += [
                ("negation_injection", NegationInjectionMutator(backend=backend, seed=seed)), # type: ignore
                ("voice_change",       VoiceChangeMutator(backend=backend, seed=seed)), # type: ignore
                ("paraphrase",         ParaphraseMutator(backend=backend, seed=seed)), # type: ignore
            ]
        except ImportError:
            pass

    return battery
