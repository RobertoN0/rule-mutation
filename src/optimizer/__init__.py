"""
Search over rule-set chromosomes.

* ``search``     — the algorithms: archive EA (random init + periodic injection)
                   and the i.i.d. random-search baseline, over one shared
                   random-chromosome sampler.
* ``engine``     — the experiment engine around them: baseline evaluation, the
                   chromosome-evaluation seam (LLM + Semgrep + cache), and
                   result persistence.
* ``chromosome`` — the representation: rule-text alleles + global rule order,
                   and the single Pareto archive (conservative objectives).
"""

from .engine import (
    ExperimentEngine,
    SearchResult,
    SearchConfig,
    TestPrompt,
    EvaluationResult,
    IterationResult,
)

# Re-export PromptWithRules for convenience
from ..evaluation.rule_mapping import PromptWithRules

__all__ = [
    "ExperimentEngine",
    "SearchResult",
    "SearchConfig",
    "TestPrompt",
    "EvaluationResult",
    "IterationResult",
    "PromptWithRules",
]
