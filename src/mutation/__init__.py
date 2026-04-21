"""
Mutation strategies for natural language security instructions.

Provides various ways to perturb CodeGuard rules while preserving semantic intent.
"""

from .base import Mutator, MutationResult
from .rule_parser import ParsedRule, Section, Block, mask_inline_code, unmask_inline_code
from .rule_based import (
    FluffMutator,
    VerbWeakeningMutator,
    StructuralMutator,
    CompositeMutator,
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
from .pool import MutatorPool, MutatorSelectionStrategy
from .quality import MutationQualityValidator
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..llm_backends.base import LLMBackend


def create_mutator_pool(
    names: list[str],
    strategy: str = "round_robin",
    seed: int | None = None,
    backend: "LLMBackend | None" = None,
    ucb1_exploration: float = 1.41,
) -> MutatorPool:
    """Create a :class:`MutatorPool` from a list of mutator names.

    Parameters
    ----------
    names : list[str]
        Mutator names (same keys accepted by :func:`create_mutator`).
    strategy : str
        One of ``"random"``, ``"round_robin"``, ``"ucb1"``, ``"greedy_batch"``.
    seed, backend, ucb1_exploration
        Forwarded to :func:`create_mutator` / :class:`MutatorPool`.
    """
    strat = MutatorSelectionStrategy(strategy)
    mutators = [create_mutator(n, seed=seed, backend=backend) for n in names]
    return MutatorPool(mutators, strategy=strat, seed=seed, ucb1_exploration=ucb1_exploration)


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
        "fluff":                    lambda: FluffMutator(seed=seed),
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
    # Function-based mutators (original)
    "FluffMutator",
    "VerbWeakeningMutator",
    "StructuralMutator",
    "CompositeMutator",
    # Function-based mutators (research-grounded)
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
    "MutatorSelectionStrategy",
    # Factories
    "create_research_battery",
    "create_mutator",
    "create_mutator_pool",
]
