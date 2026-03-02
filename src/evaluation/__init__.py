"""
Semgrep-based security evaluation for generated code.

Provides run_semgrep() and fitness calculation for the SBST optimizer.
Also includes CyberSecEval dataset loading utilities.

Test Prompt Selection:
    The recommended way to select test prompts is via the unified
    TestCaseSelector which always uses CyberSecEval (or other datasets)
    as the source of truth. This replaces hardcoded prompts.
    
    Example:
        from src.evaluation import TestCaseSelector, SelectionCriteria
        
        # Create selector
        selector = TestCaseSelector()
        
        # Select MVP prompts (deterministic, from dataset)
        prompts = selector.select_mvp(language="python", n_prompts=5)
        
        # Select from interesting_cases.json
        prompts = selector.select(SelectionCriteria(
            selector_json="path/to/interesting_cases.json",
        ))
"""

from .semgrep_runner import run_semgrep, strip_markdown_fences, LANG_EXTENSIONS
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
    # Interesting cases support
    InterestingCase,
    InterestingCasesDataset,
    load_interesting_cases,
)
from .dataset_config import (
    # Configuration
    DatasetConfig,
    DatasetBackend,
    SelectionCriteria,
    # Provider interface
    DatasetProvider,
    CyberSecEvalProvider,
    # Main selector
    TestCaseSelector,
    # Convenience functions
    create_selector,
    select_from_interesting_cases,
    select_mvp_prompts,
)
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
    "strip_markdown_fences",
    "LANG_EXTENSIONS",
    "calculate_fitness",
    "FitnessResult",
    # Dataset loading (legacy, still supported)
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
    # Interesting cases
    "InterestingCase",
    "InterestingCasesDataset",
    "load_interesting_cases",
    # Unified dataset system (recommended)
    "DatasetConfig",
    "DatasetBackend",
    "SelectionCriteria",
    "DatasetProvider",
    "CyberSecEvalProvider",
    "TestCaseSelector",
    "create_selector",
    "select_from_interesting_cases",
    "select_mvp_prompts",
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
