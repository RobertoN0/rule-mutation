"""
Semgrep-based security evaluation for generated code.

Provides run_semgrep() and fitness calculation for the SBST optimizer.
Also includes CyberSecEval dataset loading utilities.
"""

from .semgrep_runner import run_semgrep, run_semgrep_batch_dir, strip_markdown_fences, LANG_EXTENSIONS
from .fitness import calculate_fitness, FitnessResult
from .dataset import (
    CyberSecEvalDataset,
    TestPrompt,
    DatasetStats,
    INJECTION_CWES,
    CRYPTO_CWES,
    MEMORY_CWES,
    LANGUAGE_EXTENSIONS,
    load_injection_prompts,
    load_crypto_prompts,
    load_mvp_prompts,
)
from .composite_fitness import CompositeFitnessEvaluator, CompositeFitnessResult
from .rule_mapping import (
    # Rule mapping types
    RuleMapping,
    RuleMappingIndex,
    RuleLoader,
    PromptWithRules,
    # Functions
    compute_prompt_hash,
    load_rule_mapping,
    create_rule_loader,
    enrich_prompts_with_rules,
)

__all__ = [
    # Semgrep evaluation
    "run_semgrep",
    "run_semgrep_batch_dir",
    "strip_markdown_fences",
    "LANG_EXTENSIONS",
    "calculate_fitness",
    "FitnessResult",
    # Dataset loading
    "CyberSecEvalDataset",
    "TestPrompt",
    "DatasetStats",
    "INJECTION_CWES",
    "CRYPTO_CWES",
    "MEMORY_CWES",
    "LANGUAGE_EXTENSIONS",
    "load_injection_prompts",
    "load_crypto_prompts",
    "load_mvp_prompts",
    # Composite fitness
    "CompositeFitnessEvaluator",
    "CompositeFitnessResult",
    # Rule mapping system
    "RuleMapping",
    "RuleMappingIndex",
    "RuleLoader",
    "PromptWithRules",
    "compute_prompt_hash",
    "load_rule_mapping",
    "create_rule_loader",
    "enrich_prompts_with_rules",
]
