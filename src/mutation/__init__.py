"""
Mutation strategies for natural language security instructions.

Provides various ways to perturb CodeGuard rules while preserving semantic intent.
"""

from .base import Mutator, MutationResult
from .rule_parser import ParsedRule, Section, Block, mask_inline_code, unmask_inline_code
from .rule_based import (
    VerbWeakeningMutator,
    SynonymReplacementMutator,
    AddRandomWordMutator,
    SectionReorderMutator,
    create_research_battery,
)
from .llm_based import (
    NegationInjectionMutator,
    VoiceChangeMutator,
    ParaphraseMutator,
)
from .pool import MutatorPool
from .quality import MutationQualityValidator
from .security_lexicon import get_security_lexicon, build_security_lexicon
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..llm_backends.base import LLMBackend


def create_mutator_pool(
    names: list[str],
    seed: int | None = None,
    backend: "LLMBackend | None" = None,
) -> MutatorPool:
    """Create a :class:`MutatorPool` from a list of mutator names.

    Parameters
    ----------
    names : list[str]
        Mutator names (same keys accepted by :func:`create_mutator`).
    seed, backend
        Forwarded to :func:`create_mutator` / :class:`MutatorPool`.
    """
    mutators = [create_mutator(n, seed=seed, backend=backend) for n in names]
    return MutatorPool(mutators, seed=seed)


def create_mutator(
    name: str,
    seed: int | None = None,
    backend: "LLMBackend | None" = None,
) -> "Mutator":
    """Instantiate a mutator by name.

    LLM-based mutators (negation_injection, voice_change, paraphrase) require
    ``backend`` to be provided; a ``ValueError`` is raised if it is not.
    """
    _LLM_MUTATORS = {"negation_injection", "voice_change", "paraphrase"}
    if name in _LLM_MUTATORS and backend is None:
        raise ValueError(f"'{name}' requires a backend argument")

    factories = {
        "verb_weakening":           lambda: VerbWeakeningMutator(seed=seed),
        "synonym_replacement":      lambda: SynonymReplacementMutator(seed=seed),
        "add_random_word":          lambda: AddRandomWordMutator(seed=seed),
        "section_reorder_shuffle":  lambda: SectionReorderMutator(seed=seed, mode="shuffle"),
        "section_reorder_degrade":  lambda: SectionReorderMutator(seed=seed, mode="degrade"),
        "negation_injection":       lambda: NegationInjectionMutator(backend=backend, seed=seed),
        "voice_change":             lambda: VoiceChangeMutator(backend=backend, seed=seed),
        "paraphrase":               lambda: ParaphraseMutator(backend=backend, seed=seed),
    }
    if name not in factories:
        raise ValueError(
            f"Unknown mutator '{name}'. Available: {sorted(factories)}"
        )
    return factories[name]()


__all__ = [
    # Base
    "Mutator",
    "MutationResult",
    # Parser
    "ParsedRule",
    "Section",
    "Block",
    "mask_inline_code",
    "unmask_inline_code",
    # Rule-based mutators
    "VerbWeakeningMutator",
    "SynonymReplacementMutator",
    "AddRandomWordMutator",
    "SectionReorderMutator",
    # LLM-based mutators (live LLM)
    "NegationInjectionMutator",
    "VoiceChangeMutator",
    "ParaphraseMutator",
    # Quality validation
    "MutationQualityValidator",
    # Pool
    "MutatorPool",
    # Security lexicon
    "get_security_lexicon",
    "build_security_lexicon",
    # Factories
    "create_research_battery",
    "create_mutator",
    "create_mutator_pool",
]
