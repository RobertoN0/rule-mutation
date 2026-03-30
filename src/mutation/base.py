"""
Abstract base class for mutation operators.

Defines the interface that all mutation strategies must implement.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from typing import Any
import random


@dataclass
class MutationResult:
    """Result of applying a mutation to a rule text."""
    
    original: str
    """Original rule text before mutation."""
    
    mutated: str
    """Mutated rule text."""
    
    mutation_type: str
    """Name/type of mutation applied."""
    
    changes: list[str] = field(default_factory=list)
    """Description of specific changes made."""
    
    metadata: dict[str, Any] = field(default_factory=dict)
    """Additional metadata about the mutation."""
    
    @property
    def changed(self) -> bool:
        """Whether the mutation actually changed the text."""
        return self.original != self.mutated
    
    @property
    def change_ratio(self) -> float:
        """Fraction of the text that changed (0.0 = identical, 1.0 = completely different).

        Uses word-level sequence matching so that reworded or reordered
        passages produce meaningful nonzero values.  The previous
        character-*set* Jaccard was always ≈0 for any two English texts
        because they share the same ~70 characters.
        """
        if not self.original:
            return 1.0 if self.mutated else 0.0
        if self.original == self.mutated:
            return 0.0

        orig_words = self.original.split()
        mut_words = self.mutated.split()
        similarity = SequenceMatcher(None, orig_words, mut_words).ratio()
        return round(1.0 - similarity, 6)


class Mutator(ABC):
    """Abstract base class for mutation operators.
    
    Mutation operators transform security rule text to test robustness.
    They should preserve the semantic intent while varying the surface form.
    
    Example:
        mutator = FluffMutator(seed=42)
        result = mutator.mutate(rule_text)
        print(result.mutated)
    """
    
    def __init__(self, seed: int | None = None):
        """Initialize the mutator.
        
        Args:
            seed: Random seed for reproducibility.
        """
        self.seed = seed
        self.rng = random.Random(seed)
    
    @property
    @abstractmethod
    def name(self) -> str:
        """Human-readable name of this mutation strategy."""
        pass
    
    @abstractmethod
    def mutate(self, text: str) -> MutationResult:
        """Apply mutation to the input text.
        
        Args:
            text: Original rule text to mutate.
            
        Returns:
            MutationResult containing original and mutated text.
        """
        pass
    
    def mutate_batch(self, texts: list[str]) -> list[MutationResult]:
        """Apply mutation to multiple texts.
        
        Args:
            texts: List of texts to mutate.
            
        Returns:
            List of MutationResult objects.
        """
        return [self.mutate(text) for text in texts]
    
    def reset_seed(self, seed: int | None = None) -> None:
        """Reset the random number generator.
        
        Args:
            seed: New seed (uses original seed if None).
        """
        self.rng = random.Random(seed if seed is not None else self.seed)
