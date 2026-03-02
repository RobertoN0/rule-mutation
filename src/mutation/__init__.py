"""
Mutation strategies for natural language security instructions.

Provides various ways to perturb CodeGuard rules while preserving semantic intent.
"""

from .base import Mutator, MutationResult
from .rule_based import (
    FluffMutator,
    VerbWeakeningMutator,
    StructuralMutator,
    CompositeMutator,
)

__all__ = [
    "Mutator",
    "MutationResult",
    "FluffMutator",
    "VerbWeakeningMutator",
    "StructuralMutator",
    "CompositeMutator",
]
