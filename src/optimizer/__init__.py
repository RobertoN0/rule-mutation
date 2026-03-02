"""
Optimizer module for SBST hill climbing.

Implements search algorithms to find worst-case rule mutations.
"""

from .hill_climber import (
    HillClimber,
    HillClimbResult,
    HillClimbConfig,
    TestPrompt,
    EvaluationResult,
    IterationResult,
)

# Re-export PromptWithRules for convenience
from ..evaluation.rule_mapping import PromptWithRules

__all__ = [
    "HillClimber",
    "HillClimbResult",
    "HillClimbConfig",
    "TestPrompt",
    "EvaluationResult",
    "IterationResult",
    "PromptWithRules",
]
