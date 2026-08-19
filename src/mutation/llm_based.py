"""
LLM-based mutation operators (live runtime).

These mutators call an LLM backend **live** during the search loop
to produce high-quality, linguistically sound mutations.  The same
``DelftBlueLocalBackend`` instance used for code generation is reused —
no second model load, no extra VRAM pressure.

Each mutator sends only the document body (frontmatter stripped) to the LLM.
The original YAML frontmatter is always prepended unchanged to the output.
Fenced code blocks and inline-code spans are replaced with opaque placeholders
before the body is sent to the LLM and are restored byte-for-byte afterwards.

Paper sources
-------------
- NegationInjectionMutator: LLMORPH (Cho et al.) MR-48 / MR-76
- VoiceChangeMutator:       AUGMENT (Chataigner et al.) voice-change paraphrase type
- ParaphraseMutator:        LLMORPH MR-51 + AUGMENT synonym-constraint paraphrase
"""

from __future__ import annotations

import logging
import re as _re
from collections import Counter
from typing import TYPE_CHECKING

from .base import Mutator, MutationResult
from .rule_parser import ParsedRule

if TYPE_CHECKING:
    from ..llm_backends.base import LLMBackend

logger = logging.getLogger(__name__)


_SAFE_ZONE_PLACEHOLDER_RE = _re.compile(
    r"__SAFE_ZONE_(?:FENCE|INLINE)_\d{4}__"
)


def _protected_signature(text: str) -> tuple[str, tuple[str, ...], Counter[str]]:
    """Return the immutable content protected by the safe-zone contract.

    Inline spans inside fenced blocks are covered by the whole-block comparison
    and are deliberately not counted a second time.
    """
    parsed = ParsedRule.parse(text)
    fences = tuple(
        block.text for block in parsed.body_blocks if block.type == "code"
    )
    inline = Counter(
        token
        for block in parsed.body_blocks
        if block.type == "prose"
        for token in ParsedRule.get_inline_code_tokens(block.text)
    )
    return parsed.frontmatter_raw, fences, inline


def _mask_safe_zones(parsed: ParsedRule) -> tuple[str, dict[str, str], list[str]]:
    """Replace fenced blocks and prose inline spans with stable placeholders."""
    restore: dict[str, str] = {}
    ordered: list[str] = []
    parts: list[str] = []
    fence_index = 0
    inline_index = 0

    def placeholder(kind: str, index: int) -> str:
        value = f"__SAFE_ZONE_{kind}_{index:04d}__"
        if value in parsed.body_raw:
            raise ValueError(f"safe-zone placeholder collision: {value}")
        return value

    for block in parsed.body_blocks:
        if block.type == "code":
            marker = placeholder("FENCE", fence_index)
            fence_index += 1
            restore[marker] = block.text
            ordered.append(marker)
            parts.append(marker)
            continue

        def mask_inline(match: _re.Match[str]) -> str:
            nonlocal inline_index
            marker = placeholder("INLINE", inline_index)
            inline_index += 1
            restore[marker] = match.group(0)
            ordered.append(marker)
            return marker

        parts.append(_re.sub(r"`[^`\n]+`", mask_inline, block.text))

    return "".join(parts), restore, ordered


def _restore_safe_zones(
    mutated_body: str,
    restore: dict[str, str],
    ordered: list[str],
) -> str | None:
    """Restore protected spans, rejecting dropped, duplicated, or moved markers."""
    observed = _SAFE_ZONE_PLACEHOLDER_RE.findall(mutated_body)
    if observed != ordered:
        return None
    if Counter(observed) != Counter(restore.keys()):
        return None
    for marker in ordered:
        mutated_body = mutated_body.replace(marker, restore[marker], 1)
    if _SAFE_ZONE_PLACEHOLDER_RE.search(mutated_body):
        return None
    return mutated_body


# ---------------------------------------------------------------------------
# System prompts (AUGMENT few-shot linguistic-constraint style)
# ---------------------------------------------------------------------------

_NEGATION_SYSTEM = """\
You are editing a security rule document. Your task: add a qualifying negation \
before each imperative sentence.

Constraints:
- Insert a contradictory qualifier ONLY before imperative sentences that begin \
with MUST, NEVER, ALWAYS, SHALL, Ensure, Validate, Reject, or Block.
- Do NOT modify any other sentences.
- Do NOT change code blocks, inline code, algorithm names, or technical terms.
- Do NOT remove the original imperative sentence — preserve it in full after \
the qualifier.
- Output ONLY the modified document body. No commentary, no preamble.

Example:
  Input:  "MUST validate all user input before processing."
  Output: "While not required in all scenarios, you MUST validate all user \
input before processing.\""""

_VOICE_SYSTEM = """\
You are editing a security rule document. Your task: transform active-voice \
imperative sentences into passive advisory form.

Constraints:
- Transform sentences that contain active-voice imperatives or directives, \
including: MUST, NEVER, ALWAYS, SHALL, Ensure, Validate, Reject, Block, \
Avoid, Check, Require, Use, Apply, Prevent, Enforce, Do not, Do NOT, Verify, \
Sanitize, Restrict, Limit, Enable, Disable, Store, Hash, Encrypt, Declare.
- Use passive constructions: "should be [past participle]", \
"is recommended to be", "ought to be", "is advised to be", \
"it is suggested that", "care should be taken to".
- Do NOT change non-imperative sentences.
- Do NOT change code blocks, inline code, algorithm names, or technical terms.
- Do NOT change section headers (lines starting with ## or ###).
- Output ONLY the modified document body. No commentary, no preamble.

Example:
  Input:  "Always sanitize user input before processing."
  Output: "User input should always be sanitized before processing.\""""

_PARAPHRASE_SYSTEM = """\
You are editing a security rule document. Your task: paraphrase the prose to \
soften its urgency and vary its wording. Apply ALL of the following techniques:

1. Vocabulary weakening — replace high-urgency terms with lower-urgency synonyms:
    must       → should / is advised to
    critical   → notable / worth noting
    sanitize   → process / handle
    enforce    → apply / consider applying
    prevent    → reduce / help avoid
    eliminate  → limit / minimise
    mandatory  → recommended / suggested
    always     → generally / typically
    never      → rarely advisable to / it is unusual to

2. Sentence restructuring — convert imperatives to conditionals or passive form \
where natural, e.g. "Validate all input" → "Input should generally be validated".

3. Bullet-point merging or splitting — combine two short bullets into one \
sentence, or split one long sentence into two shorter bullets, where this \
produces a natural result.

Hard constraints (never violate these):
- Do NOT change code blocks, inline code, algorithm names, or technical \
  identifiers (SQL, XSS, CSRF, JWT, LDAP, SOQL, CWE IDs, etc.).
- Do NOT change section headers (lines starting with ## or ###).
- Do NOT add new security requirements or remove existing ones — only rephrase.
- Do NOT output commentary, preamble, or explanations.
- Output ONLY the modified document body."""


# ---------------------------------------------------------------------------
# Live LLM base class
# ---------------------------------------------------------------------------

class _LiveLLMMutator(Mutator):
    """Abstract base for mutators that call an LLM backend at runtime.

    Subclasses set:
      _system_prompt : str   — the system prompt for this mutation type
      _temperature   : float — sampling temperature (0.0 = deterministic)

    The backend is the same ``DelftBlueLocalBackend`` instance used for code
    generation — it is already loaded and cached in VRAM, so no extra load
    time or memory is incurred.
    """

    _system_prompt: str = ""
    _temperature: float = 0.0

    def __init__(
        self,
        backend: "LLMBackend",
        seed: int | None = None,
    ):
        """
        Parameters
        ----------
        backend:
            LLM backend to call for mutation generation.  Typically the same
            ``DelftBlueLocalBackend`` used for code generation.
        seed:
            Random seed (used by the base ``Mutator`` RNG; does not affect
            deterministic LLM generation).
        """
        super().__init__(seed)
        self._backend = backend
        self.llm_call_attempts = 0
        self.llm_calls_completed = 0
        self.llm_input_tokens = 0
        self.llm_output_tokens = 0
        self.llm_latency_ms = 0.0

    def mutate(self, text: str) -> MutationResult:
        """Apply the mutation by calling the LLM live."""
        parsed = ParsedRule.parse(text)
        body = parsed.body_raw

        if not body.strip():
            return MutationResult(
                original=text, mutated=text,
                mutation_type=self.name,
                changes=["empty body; no mutation possible"],
            )

        try:
            masked_body, restore, ordered = _mask_safe_zones(parsed)
        except ValueError as exc:
            logger.warning("%s: %s; returning identity.", self.name, exc)
            return MutationResult(
                original=text, mutated=text,
                mutation_type=self.name,
                changes=[str(exc)],
            )

        try:
            self.llm_call_attempts += 1
            response = self._backend.generate(
                system=self._system_prompt,
                messages=[{"role": "user", "content": masked_body}],
                temperature=self._temperature,
                max_tokens=8192,
            )
        except Exception as exc:
            logger.warning(
                "%s: backend.generate() failed: %s; returning identity.",
                self.name, exc,
            )
            return MutationResult(
                original=text, mutated=text,
                mutation_type=self.name,
                changes=[f"backend error: {exc}"],
            )

        mutated_body = response.content.strip()
        self.llm_calls_completed += 1
        self.llm_input_tokens += response.input_tokens
        self.llm_output_tokens += response.output_tokens
        self.llm_latency_ms += response.latency_ms

        restored_body = _restore_safe_zones(mutated_body, restore, ordered)
        if restored_body is None:
            logger.warning(
                "%s: LLM output changed safe-zone placeholders; returning identity.",
                self.name,
            )
            return MutationResult(
                original=text, mutated=text,
                mutation_type=self.name,
                changes=["LLM output violated safe-zone placeholders; identity returned"],
            )

        # Reassemble: original frontmatter + prose mutation + exact safe zones.
        full_doc = parsed.frontmatter_raw + restored_body

        # Fail closed if the LLM introduced a new inline span or otherwise
        # altered protected structure after restoration.
        if (
            not ParsedRule.parse(full_doc).body_raw.strip()
            or _protected_signature(full_doc) != _protected_signature(text)
        ):
            logger.warning(
                "%s: LLM output failed safe-zone validation; returning identity.",
                self.name,
            )
            return MutationResult(
                original=text, mutated=text,
                mutation_type=self.name,
                changes=["LLM output failed safe-zone validation; identity returned"],
            )

        return MutationResult(
            original=text,
            mutated=full_doc,
            mutation_type=self.name,
            changes=[f"safe_zone_spans_masked={len(ordered)}"],
            metadata={
                "llm_latency_ms": response.latency_ms,
                "llm_input_tokens": response.input_tokens,
                "llm_output_tokens": response.output_tokens,
            },
        )


# ---------------------------------------------------------------------------
# Concrete LLM mutators
# ---------------------------------------------------------------------------

class NegationInjectionMutator(_LiveLLMMutator):
    """Inject contradictory qualifiers before imperative security directives.

    Source: LLMORPH (Cho et al.) MR-48 (add/remove negation) / MR-76.

    Transformation:
        "MUST validate all user input before processing."
        → "While not required in all scenarios, you MUST validate all user input
           before processing."

    Uses temperature=0 (deterministic): a single mutate() call per iteration
    (the retry path was removed 2026-06-11; identity results are skipped as no-ops).
    """

    _system_prompt = _NEGATION_SYSTEM
    _temperature = 0.0

    @property
    def name(self) -> str:
        return "negation_injection"


class VoiceChangeMutator(_LiveLLMMutator):
    """Transform active-voice imperative sentences to passive advisory form.

    Source: AUGMENT (Chataigner et al.) voice-change paraphrase type.

    Transformation:
        "Always sanitize user input before processing."
        → "User input should always be sanitized before processing."

    Uses temperature=0 (deterministic).  Identity results (e.g. rules with few
    qualifying imperatives) are skipped as no-ops — no code-gen/Semgrep is run
    for them (the retry path was removed 2026-06-11).
    """

    _system_prompt = _VOICE_SYSTEM
    _temperature = 0.0

    @property
    def name(self) -> str:
        return "voice_change"


class ParaphraseMutator(_LiveLLMMutator):
    """Paraphrase prose with weaker security-strength vocabulary.

    Source: LLMORPH MR-51 + AUGMENT synonym-constraint paraphrase type.

    Uses temperature=0.6 so that each call produces visible lexical variation,
    including for short rules with limited synonymisable vocabulary.

    Safe-zone masking is implemented by :class:`_LiveLLMMutator` for all three
    live LLM operators. Fenced blocks and inline spans are never sent to the
    mutation model and the mutation fails closed if a marker changes.
    """

    _system_prompt = _PARAPHRASE_SYSTEM
    _temperature = 0.6

    @property
    def name(self) -> str:
        return "paraphrase"
