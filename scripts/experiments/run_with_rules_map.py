#!/usr/bin/env python3
"""
Run Hill Climbing with Per-Prompt Rule Mapping.

This script runs hill climbing experiments using:
1. Interesting cases from previous batch experiments
2. Rule retrieval mapping (rules selected per-prompt by an AI agent)

This enables testing multiple rules per prompt based on empirical
rule selection rather than a single hardcoded rule.

Usage:
    # Run with 5 interesting cases, using per-prompt rules
    python scripts/experiments/run_with_rules_map.py \
        --interesting-cases pipeline_breakdown/generation_results/interesting_cases_96_sonnet_4_6.json \
        --rules-map pipeline_breakdown/rule_retrieval_output/retrieval_map_96_sonnet_4_6.json \
        --n-cases 5
    
    # Full run with specific model
    python scripts/experiments/run_with_rules_map.py \
        --interesting-cases interesting_cases.json \
        --rules-map retrieval_map.json \
        --model llama-3.3-70b-versatile \
        --iterations 10
    
    # Dry run (no API calls)
    python scripts/experiments/run_with_rules_map.py \
        --interesting-cases interesting_cases.json \
        --rules-map retrieval_map.json \
        --dry-run
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

# Add src to path for imports
def _resolve_project_root() -> Path:
    """Resolve repository root by searching upward for the src/ and scripts/ dirs."""
    this_file = Path(__file__).resolve()
    for parent in [this_file.parent, *this_file.parents]:
        if (parent / "src").is_dir() and (parent / "scripts").is_dir():
            return parent
    raise RuntimeError("Could not resolve project root from script location")


PROJECT_ROOT = _resolve_project_root()
sys.path.insert(0, str(PROJECT_ROOT))

from src.llm_backends import GroqBackend, LLMConfig, DelftBlueLocalBackend
from src.llm_backends.base import LLMError
from src.mutation import (
    FluffMutator,
    VerbWeakeningMutator,
    SynonymReplacementMutator,
    AddRandomWordMutator,
    SectionReorderMutator,
    NegationInjectionMutator,
    VoiceChangeMutator,
    ParaphraseMutator,
    MutationQualityValidator,
    create_mutator,
    create_mutator_pool,
)
from src.optimizer import HillClimber, HillClimbConfig
from src.evaluation import (
    load_interesting_cases,
    load_rule_mapping,
    create_rule_loader,
    RuleMappingIndex,
    RuleLoader,
    PromptWithRules,
)
from src.evaluation.fitness import FitnessStrategy
from src.evaluation.composite_fitness import CompositeFitnessEvaluator
from src.evaluation.semgrep_runner import (
    configure_semgrep,
    configure_semgrep_debug,
    get_semgrep_config,
)


# ═══════════════════════════════════════════════════════════════════════════════
# CONFIGURATION
# ═══════════════════════════════════════════════════════════════════════════════

# Default paths (relative to project root)
DEFAULT_INTERESTING_CASES = (
    PROJECT_ROOT / "pipeline_breakdown" / "generation_results" / 
    "interesting_cases_96_sonnet_4_6.json"
)
DEFAULT_RULES_MAP = (
    PROJECT_ROOT / "pipeline_breakdown" / "rule_retrieval_output" / 
    "retrieval_map_96_sonnet_4_6.json"
)
RULES_DIR = PROJECT_ROOT / "project-codeguard" / "skills" / "software-security" / "rules"


def load_prompts_with_rules(
    interesting_cases_path: Path,
    rules_map_path: Path,
    rule_loader: RuleLoader,
    n_cases: int | None = None,
    diff_types: list[str] | None = None,
    languages: list[str] | None = None,
    selection: str = "first",
    seed: int = 42,
) -> list[PromptWithRules]:
    """Load interesting cases and enrich with rules from mapping.
    
    Args:
        interesting_cases_path: Path to interesting_cases JSON
        rules_map_path: Path to rule retrieval mapping JSON
        rule_loader: Loader for rule content
        n_cases: Limit number of cases (None = all)
        diff_types: Filter by diff_type (None = all)
        
    Returns:
        List of PromptWithRules ready for optimization
    """
    # Load interesting cases
    cases = list(load_interesting_cases(interesting_cases_path)) # type: ignore
    print(f"📥 Loaded {len(cases)} interesting cases")
    
    # Filter by diff_type if specified
    if diff_types:
        cases = [c for c in cases if c.diff_type in diff_types]
        print(f"   Filtered to {len(cases)} cases with diff_types: {diff_types}")

    # Filter by language if specified
    if languages:
        languages_lower = [lang.lower() for lang in languages]
        cases = [c for c in cases if c.language.lower() in languages_lower]  # type: ignore
        print(f"   Filtered to {len(cases)} cases with languages: {languages_lower}")

    # Selection strategy (applied before n_cases limit)
    if selection == "random":
        import random
        rng = random.Random(seed)
        rng.shuffle(cases)  # type: ignore
        print(f"   Shuffled cases with seed={seed} (random selection)")

    # Limit number of cases
    if n_cases and len(cases) > n_cases:
        cases = cases[:n_cases]  # type: ignore
        print(f"   Selected {n_cases} cases ({selection} selection, seed={seed})")
    
    # Load rule mapping
    rule_mapping = load_rule_mapping(rules_map_path)
    print(f"📥 Loaded rule mapping with {len(rule_mapping)} entries")
    print(f"   Unique rules used: {len(rule_mapping.all_rules)}")
    
    # Enrich cases with rules
    prompts_with_rules: list[PromptWithRules] = []
    rules_found = 0
    rules_missing = 0
    
    for case in cases: # type: ignore
        # Look up rules for this prompt
        mapping = rule_mapping.get_by_prompt(case.prompt)
        
        if mapping:
            rule_ids = mapping.rules_retrieved
            rules_found += 1
        else:
            # Fallback: use a sensible default based on CWE
            rule_ids = _get_fallback_rules(case.cwe_id)
            rules_missing += 1
        
        # Load individual rule texts (needed for per-rule targeted mutation)
        individual = rule_loader.load_multiple(rule_ids)
        combined = "\n\n---\n\n".join(individual[rid] for rid in rule_ids if rid in individual)

        pwr = PromptWithRules(
            prompt=case.prompt,
            language=case.language,
            cwe_id=case.cwe_id,
            rule_ids=rule_ids,
            combined_rules=combined,
            individual_rules=individual,
            metadata={
                "test_case_id": case.test_case_id,
                "diff_type": case.diff_type,
                "baseline_vuln_count": case.baseline_vuln_count,
                "control_vuln_count": case.control_vuln_count,
                "mutant_vuln_count": case.mutant_vuln_count,
            },
        )
        prompts_with_rules.append(pwr)
    
    print(f"✅ Created {len(prompts_with_rules)} prompts with rules")
    print(f"   Rules from mapping: {rules_found}")
    print(f"   Fallback rules: {rules_missing}")
    
    # Show rule distribution
    rule_counts: dict[str, int] = {}
    for pwr in prompts_with_rules:
        for rid in pwr.rule_ids:
            rule_counts[rid] = rule_counts.get(rid, 0) + 1
    
    print(f"\n📊 Rule distribution:")
    for rid, count in sorted(rule_counts.items(), key=lambda x: -x[1])[:8]:
        print(f"   {rid}: {count}")
    
    return prompts_with_rules


def load_prompts_from_mapping_only(
    rules_map_path: Path,
    rule_loader: RuleLoader,
    n_cases: int | None = None,
    languages: list[str] | None = None,
    selection: str = "first",
    seed: int = 42,
) -> list[PromptWithRules]:
    """Load prompts directly from the retrieval mapping (no interesting_cases file needed).

    Uses all 96 entries in the retrieval map as test cases. Each RuleMapping entry
    provides: prompt, language, cwe_id, rules_retrieved. No control_code or vuln counts
    are available, so delta_composite code-divergence will be disabled (returns 0.0).

    Args:
        rules_map_path: Path to rule retrieval mapping JSON (retrieval_map_*.json)
        rule_loader: Loader for rule content
        n_cases: Limit number of cases (None = all)
        languages: Filter by language (case-insensitive). None = all.
        selection: "first" or "random"
        seed: RNG seed for random selection

    Returns:
        List of PromptWithRules ready for optimization
    """
    rule_mapping = load_rule_mapping(rules_map_path)
    mappings = list(rule_mapping.mappings)
    print(f"📥 Loaded {len(mappings)} entries from retrieval map (mapping-only mode)")
    print(f"   Unique rules used: {len(rule_mapping.all_rules)}")

    if languages:
        languages_lower = [lang.lower() for lang in languages]
        mappings = [m for m in mappings if m.language.lower() in languages_lower]
        print(f"   Filtered to {len(mappings)} entries with languages: {languages_lower}")

    if selection == "random":
        import random
        rng = random.Random(seed)
        rng.shuffle(mappings)
        print(f"   Shuffled entries with seed={seed} (random selection)")

    if n_cases and len(mappings) > n_cases:
        mappings = mappings[:n_cases]
        print(f"   Selected {n_cases} entries ({selection} selection, seed={seed})")

    prompts_with_rules: list[PromptWithRules] = []
    for m in mappings:
        individual = rule_loader.load_multiple(m.rules_retrieved)
        combined = "\n\n---\n\n".join(
            individual[rid] for rid in m.rules_retrieved if rid in individual
        )
        pwr = PromptWithRules(
            prompt=m.prompt,
            language=m.language,
            cwe_id=m.cwe_id,
            rule_ids=m.rules_retrieved,
            combined_rules=combined,
            individual_rules=individual,
            metadata={
                "test_case_id": str(m.index),
                "mapping_index": m.index,
                "source": "mapping_only",
            },
        )
        prompts_with_rules.append(pwr)

    print(f"✅ Created {len(prompts_with_rules)} prompts with rules (mapping-only)")

    rule_counts: dict[str, int] = {}
    for pwr in prompts_with_rules:
        for rid in pwr.rule_ids:
            rule_counts[rid] = rule_counts.get(rid, 0) + 1

    print(f"\n📊 Rule distribution:")
    for rid, count in sorted(rule_counts.items(), key=lambda x: -x[1])[:8]:
        print(f"   {rid}: {count}")

    return prompts_with_rules


def _get_fallback_rules(cwe_id: str | None) -> list[str]:
    """Get fallback rules for a CWE when not in mapping."""
    # Simple CWE-based fallback
    fallback_map = {
        "CWE-119": ["codeguard-0-safe-c-functions", "codeguard-0-input-validation-injection"],
        "CWE-120": ["codeguard-0-safe-c-functions"],
        "CWE-121": ["codeguard-0-safe-c-functions"],
        "CWE-89": ["codeguard-0-input-validation-injection", "codeguard-0-framework-and-languages"],
        "CWE-78": ["codeguard-0-input-validation-injection"],
        "CWE-79": ["codeguard-0-client-side-web-security"],
    }
    
    if cwe_id and cwe_id in fallback_map:
        return fallback_map[cwe_id]
    
    # Ultimate fallback
    return ["codeguard-0-input-validation-injection"]


def create_mock_backend():
    """Create a mock backend for dry-run testing."""
    from src.llm_backends.base import LLMBackend, LLMResponse, LLMConfig
    
    class MockBackend(LLMBackend):
        def __init__(self):
            super().__init__(LLMConfig(model="mock-model"))
        
        @property
        def provider_name(self) -> str:
            return "MockProvider"
        
        def is_available(self) -> bool:
            return True
        
        def generate(self, system, messages, **kwargs):
            # Return vulnerable-looking code for testing
            return LLMResponse(
                content='import os\nresult = os.system(f"ls {user_input}")\nprint(result)',
                model="mock-model",
                input_tokens=100,
                output_tokens=50,
                latency_ms=10.0,
            )
    
    return MockBackend()


def main():
    parser = argparse.ArgumentParser(
        description="Run hill climbing with per-prompt rule mapping"
    )
    parser.add_argument(
        "--use-mapping-only",
        action="store_true",
        help=(
            "Load prompts directly from the retrieval map (bypasses interesting_cases file). "
            "Supports up to 96 cases. Code-divergence in delta_composite will be 0.0 "
            "(no control_code available)."
        ),
    )
    parser.add_argument(
        "--interesting-cases", "-c",
        type=Path,
        default=DEFAULT_INTERESTING_CASES,
        help="Path to interesting_cases JSON (not required when --use-mapping-only is set)"
    )
    parser.add_argument(
        "--rules-map", "-r",
        type=Path,
        default=DEFAULT_RULES_MAP,
        help="Path to rule retrieval mapping JSON"
    )
    parser.add_argument(
        "--n-cases", "-n",
        type=int,
        default=None,
        help="Number of cases to use (default: all)"
    )
    parser.add_argument(
        "--diff-types",
        nargs="+",
        default=None,
        help="Filter by diff_type (e.g., rules_helped mutation_improved)"
    )
    parser.add_argument(
        "--languages",
        nargs="+",
        default=None,
        metavar="LANG",
        help="Filter by language (e.g., c python java javascript). Case-insensitive.",
    )
    parser.add_argument(
        "--selection",
        default="first",
        choices=["first", "random"],
        help=(
            "Case selection strategy: 'first' takes the first N cases in file "
            "order; 'random' shuffles with --seed before selecting N (default: first)"
        ),
    )
    parser.add_argument(
        "--iterations", "-i",
        type=int,
        default=5,
        help="Number of hill climbing iterations (default: 5)"
    )
    parser.add_argument(
        "--early-stop",
        type=int,
        default=0,
        help="Stop after N iterations without improvement. 0 = disabled (default: 0)"
    )
    parser.add_argument(
        "--model", "-m",
        default="llama-3.3-70b-versatile",
        help="Model to use (default: llama-3.3-70b-versatile for Groq, or HF model path for local)"
    )
    parser.add_argument(
        "--backend", "-b",
        default="groq",
        choices=["groq", "local", "delftblue"],
        help="LLM backend: groq (default), local/delftblue (HuggingFace local inference)"
    )
    parser.add_argument(
        "--quantization",
        default="fp16",
        choices=["fp16", "4bit"],
        help="Quantization for local backend: fp16 (default) or 4bit"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Test pipeline without API calls"
    )
    parser.add_argument(
        "--output-dir", "-o",
        type=Path,
        default=PROJECT_ROOT / "experiments" / "results",
        help="Directory to save results"
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=42,
        help="Random seed for reproducibility"
    )
    parser.add_argument(
        "--mutators",
        nargs="+",
        default=["fluff"],
        help=(
            "Space-separated list of mutation operators (default: fluff). "
            "LLM-based mutators (negation_injection, voice_change, paraphrase) "
            "require --backend local/delftblue. Single value works for backward compat."
        ),
    )
    parser.add_argument(
        "--mutator-strategy",
        default="round_robin",
        choices=["random", "round_robin", "ucb1", "greedy_batch"],
        help="Mutator/rule selection strategy (default: round_robin).",
    )
    parser.add_argument(
        "--ucb1-exploration",
        type=float,
        default=1.41,
        help="UCB1 exploration constant c (default: 1.41, only used with --mutator-strategy ucb1).",
    )
    parser.add_argument(
        "--max-mutation-depth",
        type=int,
        default=4,
        help="Max compounding mutations per rule before saturation (default: 4).",
    )
    parser.add_argument(
        "--fitness-strategy",
        default="severity_weighted",
        choices=["raw_count", "severity_weighted", "unique_rules", "delta_composite"],
        help=(
            "Fitness function for the hill climber (default: severity_weighted). "
            "delta_composite adds rule-divergence and code-divergence signals to "
            "smooth the landscape when Semgrep finds nothing."
        ),
    )
    parser.add_argument(
        "--fitness-weights",
        nargs=3,
        type=float,
        default=[1.0, 0.3, 0.2],
        metavar=("ALPHA", "BETA", "GAMMA"),
        help=(
            "Weights for delta_composite fitness: alpha (semgrep_delta), "
            "beta (rule_divergence), gamma (code_divergence). Default: 1.0 0.3 0.2."
        ),
    )
    parser.add_argument(
        "--enable-validation",
        action="store_true",
        help=(
            "Enable in-loop mutation quality validation using MutationQualityValidator "
            "(SBERT semantic similarity + structural criteria from AUGMENT paper)."
        ),
    )
    parser.add_argument(
        "--enable-perplexity",
        action="store_true",
        help=(
            "Add perplexity-ratio gate to the quality validator (ratio ≤ 2.5). "
            "Requires --enable-validation. Reuses the already-loaded generation "
            "model — no second model is loaded. No-op when --backend is not local/delftblue."
        ),
    )
    parser.add_argument(
        "--mutation-max-retries",
        type=int,
        default=2,
        help=(
            "Maximum validation retries per mutation when --enable-validation is set "
            "(only effective for non-deterministic mutators like paraphrase; default: 2)"
        ),
    )
    parser.add_argument(
        "--semgrep-config",
        default=os.getenv("SEMGREP_RULESET"),
        help=(
            "Semgrep rule config to use. Can be a registry shorthand like "
            "'p/security-audit' or a local rule file/directory. Defaults to "
            "SEMGREP_RULESET if set."
        ),
    )
    parser.add_argument(
        "--skip-seen",
        action="store_true",
        help=(
            "Skip (rule, mutator, input_text) triples that have already been "
            "evaluated. Avoids wasting iterations on deterministic mutator "
            "retries when the rule text hasn't changed. Terminates early when "
            "all novel combinations are exhausted."
        ),
    )
    parser.add_argument(
        "--semgrep-timeout-seconds",
        type=int,
        default=int(os.getenv("SEMGREP_TIMEOUT_SECONDS", "180")),
        help="Whole-process timeout for one Semgrep run (default: 180)",
    )
    parser.add_argument(
        "--semgrep-jobs",
        type=int,
        default=int(os.getenv("SEMGREP_JOBS", "1")),
        help="Semgrep parallel jobs per scan (default: 1)",
    )
    
    args = parser.parse_args()
    
    print("=" * 70)
    print("🚀 SBST: Hill Climbing with Per-Prompt Rule Mapping")
    print("=" * 70)
    
    # Validate input files
    if not args.use_mapping_only and not args.interesting_cases.exists():
        print(f"❌ Error: Interesting cases file not found: {args.interesting_cases}")
        sys.exit(1)

    if not args.rules_map.exists():
        print(f"❌ Error: Rules map file not found: {args.rules_map}")
        sys.exit(1)
    
    # Create rule loader
    rule_loader = create_rule_loader(RULES_DIR)
    print(f"📜 Rule loader initialized: {len(rule_loader.available_rules)} rules available")
    
    # Load prompts with rules
    print()
    if args.use_mapping_only:
        prompts_with_rules = load_prompts_from_mapping_only(
            rules_map_path=args.rules_map,
            rule_loader=rule_loader,
            n_cases=args.n_cases,
            languages=args.languages,
            selection=args.selection,
            seed=args.seed,
        )
    else:
        prompts_with_rules = load_prompts_with_rules(
            interesting_cases_path=args.interesting_cases,
            rules_map_path=args.rules_map,
            rule_loader=rule_loader,
            n_cases=args.n_cases,
            diff_types=args.diff_types,
            languages=args.languages,
            selection=args.selection,
            seed=args.seed,
        )
    
    if not prompts_with_rules:
        print("❌ Error: No prompts loaded")
        sys.exit(1)
    
    # Create LLM backend
    if args.dry_run:
        print("\n🔧 DRY RUN MODE: Using mock backend")
        backend = create_mock_backend()
    elif args.backend in ("local", "delftblue"):
        # Local HuggingFace backend for DelftBlue GPU nodes
        print(f"\n🤖 Initializing DelftBlue local backend: {args.model}")
        print(f"   Quantization: {args.quantization}")
        
        config = LLMConfig(
            model=args.model,
            temperature=0.0,
            max_tokens=4096,
            extra={
                "quantization": args.quantization,
                "local_files_only": True,
                "trust_remote_code": True,
            },
        )
        try:
            backend = DelftBlueLocalBackend(config)
            if backend.is_available():
                print("   ✅ Model found in local cache")
            else:
                print("   ⚠️  Model not found in local cache or CUDA unavailable")
                print("   Hint: Set HF_HOME and TRANSFORMERS_CACHE to your model directory")
                sys.exit(1)
        except LLMError as e:
            print(f"❌ Error initializing local backend: {e}")
            sys.exit(1)
    else:
        # Groq API backend
        api_key = os.getenv("GROQ_API_KEY")
        if not api_key:
            print("\n❌ Error: GROQ_API_KEY environment variable not set")
            print("   Get your key from: https://console.groq.com")
            sys.exit(1)
        
        print(f"\n🤖 Initializing Groq backend: {args.model}")
        config = LLMConfig(
            model=args.model,
            api_key=api_key,
            temperature=0.0,
            max_tokens=4096,
        )
        try:
            backend = GroqBackend(config)
            if backend.is_available():
                print("   ✅ Groq API connection verified")
            else:
                print("   ⚠️  Could not verify Groq API connection")
        except LLMError as e:
            print(f"❌ Error initializing Groq: {e}")
            sys.exit(1)
    
    # Create mutator pool
    _LLM_MUTATORS = {"negation_injection", "voice_change", "paraphrase"}
    has_llm_mutator = any(m in _LLM_MUTATORS for m in args.mutators)

    if has_llm_mutator and args.backend not in ("local", "delftblue"):
        llm_names = [m for m in args.mutators if m in _LLM_MUTATORS]
        print(
            f"\n❌ Error: LLM mutator(s) {llm_names} require --backend local or delftblue "
            f"(got: {args.backend}). LLM-based mutators share the code-gen backend."
        )
        sys.exit(1)

    print(f"\n🧬 Initializing mutator pool: {args.mutators} "
          f"(strategy={args.mutator_strategy}, seed={args.seed})")
    backend_for_mutator = backend if has_llm_mutator else None
    pool = create_mutator_pool(
        args.mutators,
        strategy=args.mutator_strategy,
        seed=args.seed,
        backend=backend_for_mutator,
        ucb1_exploration=args.ucb1_exploration,
    )

    if has_llm_mutator:
        print(f"   LLM mutator(s): share backend with code generation")

    # Create validator if enabled
    validator = None
    if args.enable_validation:
        use_ppl = getattr(args, "enable_perplexity", False) and args.backend in ("local", "delftblue")
        ppl_model_handle = None
        ppl_tokenizer_handle = None
        if use_ppl:
            print(f"\n🔬 Setting up MutationQualityValidator (perplexity gate ON)")
            print(f"   Force-loading generation model for perplexity scoring …")
            ppl_model_handle = backend._load_model()
            ppl_tokenizer_handle = backend._load_tokenizer()
            print(f"   Generation model loaded: {type(ppl_model_handle).__name__}")
        else:
            print(f"\n🔬 Setting up MutationQualityValidator")
        print(f"   SBERT semantic similarity (all-mpnet-base-v2, threshold=0.80)")
        print(f"   Structural criteria: inline code retention + security keyword retention")
        if use_ppl:
            print(f"   Perplexity ratio gate (threshold=2.5, model=32B shared)")
        print(f"   Max retries: {args.mutation_max_retries}")
        validator = MutationQualityValidator(
            use_sbert=True,
            use_perplexity=use_ppl,
            ppl_model_handle=ppl_model_handle,
            ppl_tokenizer_handle=ppl_tokenizer_handle,
        )

    # Map fitness strategy string to enum
    _STRATEGY_MAP = {
        "raw_count": FitnessStrategy.RAW_COUNT,
        "severity_weighted": FitnessStrategy.SEVERITY_WEIGHTED,
        "unique_rules": FitnessStrategy.UNIQUE_RULES,
        "delta_composite": FitnessStrategy.DELTA_COMPOSITE,
    }
    fitness_strategy = _STRATEGY_MAP[args.fitness_strategy]

    # Build composite evaluator if requested
    composite_evaluator = None
    if fitness_strategy == FitnessStrategy.DELTA_COMPOSITE:
        print(f"\n📐 Building CompositeFitnessEvaluator")
        print(f"   Weights: alpha={args.fitness_weights[0]}, beta={args.fitness_weights[1]}, gamma={args.fitness_weights[2]}")

        # Build reference code index from interesting_cases (not available in mapping-only mode)
        ref_codes: dict[str, str] = {}
        if not args.use_mapping_only:
            for ic in load_interesting_cases(args.interesting_cases):
                ref_codes[str(ic.test_case_id)] = ic.control_code
            print(f"   Reference codes loaded: {len(ref_codes)}")
        else:
            print(f"   Reference codes: unavailable in mapping-only mode (code_divergence=0.0)")

        # Share SBERT model with validator if already loaded, else evaluator lazy-loads its own
        sbert_source = validator._get_sbert() if validator is not None else None
        composite_evaluator = CompositeFitnessEvaluator(
            reference_codes=ref_codes,
            sbert_model=sbert_source,
            weights=tuple(args.fitness_weights),
        )
        if sbert_source is not None:
            print(f"   SBERT: shared from validator (no extra load)")
        else:
            print(f"   SBERT: will lazy-load on first use")

    # Configure hill climber
    hc_config = HillClimbConfig(
        max_iterations=args.iterations,
        fitness_strategy=fitness_strategy,
        early_stop_no_improvement=args.early_stop,
        save_intermediate=True,
        output_dir=args.output_dir,
        verbose=True,
        enable_validation=args.enable_validation,
        mutation_max_retries=args.mutation_max_retries,
        mutator_strategy=args.mutator_strategy,
        ucb1_exploration=args.ucb1_exploration,
        max_mutation_depth=args.max_mutation_depth,
        skip_seen_pairs=args.skip_seen,
    )

    early_stop_label = (
        f"{hc_config.early_stop_no_improvement} iterations without improvement"
        if hc_config.early_stop_no_improvement > 0
        else "disabled"
    )

    print(f"\n⚙️  Hill Climbing Configuration:")
    print(f"   Test cases: {len(prompts_with_rules)}")
    print(f"   Max iterations: {hc_config.max_iterations}")
    print(f"   Fitness strategy: {hc_config.fitness_strategy.name}")
    if fitness_strategy == FitnessStrategy.DELTA_COMPOSITE:
        print(f"   Fitness weights: α={args.fitness_weights[0]} β={args.fitness_weights[1]} γ={args.fitness_weights[2]}")
    print(f"   Early stop: {early_stop_label}")
    print(f"   Mutators: {args.mutators} ({args.mutator_strategy})")
    print(f"   Max mutation depth: {args.max_mutation_depth}")
    print(f"   Validation: {'enabled (SBERT + structural)' if args.enable_validation else 'disabled'}")
    print(f"   Skip seen pairs: {args.skip_seen}")
    print(f"   Output dir: {args.output_dir}")
    
    # Estimate LLM calls
    estimated_calls = len(prompts_with_rules) * (1 + args.iterations)  # baseline + iterations
    print(f"\n📊 Estimated LLM calls: ~{estimated_calls}")

    # Configure Semgrep execution
    configure_semgrep(
        rule_config=args.semgrep_config,
        subprocess_timeout_seconds=args.semgrep_timeout_seconds,
        jobs=args.semgrep_jobs,
    )
    semgrep_config = get_semgrep_config()

    # Configure Semgrep debug output (helps diagnose zero-fitness / fence issues)
    semgrep_debug_dir = args.output_dir / "semgrep_debug"
    configure_semgrep_debug(semgrep_debug_dir)
    print(f"🔎 Semgrep config: {semgrep_config['rule_config']}")
    print(f"   Semgrep timeout: {semgrep_config['subprocess_timeout_seconds']}s")
    print(f"   Semgrep jobs: {semgrep_config['jobs']}")
    print(f"\U0001f50d Semgrep inputs/outputs → {semgrep_debug_dir}/semgrep_debug.jsonl", flush=True)

    # Create hill climber
    climber = HillClimber(backend, pool, hc_config, validator=validator,
                          composite_evaluator=composite_evaluator)
    
    # Run optimization with per-prompt rules
    print("\n" + "=" * 70)
    print("🏔️  Starting Per-Prompt-Rules Hill Climbing Optimization")
    print("=" * 70)
    
    try:
        result = climber.optimize_per_prompt_rules(
            prompts_with_rules=prompts_with_rules,
        )
    except LLMError as e:
        print(f"\n❌ LLM Error: {e}")
        sys.exit(1)
    except KeyboardInterrupt:
        print("\n\n⚠️  Interrupted by user")
        sys.exit(130)
    
    # Print results summary
    print("\n" + "=" * 70)
    print("📊 RESULTS SUMMARY")
    print("=" * 70)
    print(f"Test cases: {len(prompts_with_rules)}")
    print(f"Iterations run: {len(result.iterations)}")
    print(f"Total time: {result.total_time_seconds:.1f}s")
    print(f"LLM calls: {result.total_llm_calls}")
    print()
    print(f"Original fitness: {result.original_fitness.total_fitness:.1f}")
    print(f"  - Vulnerable prompts: {result.original_fitness.num_vulnerable}/{result.original_fitness.num_prompts}")
    print(f"  - Mean fitness: {result.original_fitness.mean_fitness:.2f}")
    print()
    print(f"Best fitness: {result.best_fitness.total_fitness:.1f}")
    print(f"  - Vulnerable prompts: {result.best_fitness.num_vulnerable}/{result.best_fitness.num_prompts}")
    print(f"  - Mean fitness: {result.best_fitness.mean_fitness:.2f}")
    print()
    print(f"Fitness increase: {result.fitness_increase:+.1f}")
    print(f"Improvement ratio: {result.improvement_ratio:.2f}x")
    
    # Save detailed results
    if args.output_dir:
        args.output_dir.mkdir(parents=True, exist_ok=True)
        from datetime import datetime
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        results_file = args.output_dir / f"per_prompt_rules_results_{timestamp}.json"
        
        # Serialize results - COMPLETE DATA (no truncation)
        serializable = {
            "metadata": {
                "timestamp": timestamp,
                "backend": args.backend,
                "model": args.model,
                "quantization": args.quantization if args.backend in ("local", "delftblue") else None,
                "num_cases": len(prompts_with_rules),
                "num_iterations": len(result.iterations),
                "seed": args.seed,
                "mutators": args.mutators,
                "mutator_strategy": args.mutator_strategy,
                "max_mutation_depth": args.max_mutation_depth,
                "fitness_strategy": args.fitness_strategy,
                "fitness_weights": args.fitness_weights,
                "enable_validation": args.enable_validation,
                "skip_seen_pairs": args.skip_seen,
                "selection": args.selection,
                "languages_filter": args.languages,
                "semgrep_config": str(semgrep_config["rule_config"]),
                "semgrep_timeout_seconds": semgrep_config["subprocess_timeout_seconds"],
                "semgrep_jobs": semgrep_config["jobs"],
                "use_mapping_only": args.use_mapping_only,
                "interesting_cases_file": str(args.interesting_cases) if not args.use_mapping_only else None,
                "rules_map_file": str(args.rules_map),
                "diff_types_filter": args.diff_types if not args.use_mapping_only else None,
            },
            "summary": {
                "original_fitness": result.original_fitness.total_fitness,
                "best_fitness": result.best_fitness.total_fitness,
                "fitness_increase": result.fitness_increase,
                "improvement_ratio": result.improvement_ratio,
                "total_time_seconds": result.total_time_seconds,
                "total_llm_calls": result.total_llm_calls,
                "original_vulnerable": result.original_fitness.num_vulnerable,
                "best_vulnerable": result.best_fitness.num_vulnerable,
            },
            "prompts": [
                {
                    "index": idx,
                    "prompt": pwr.prompt,  # FULL prompt, no truncation
                    "language": pwr.language,
                    "cwe_id": pwr.cwe_id,
                    "rule_ids": pwr.rule_ids,
                    "num_rules": pwr.num_rules,
                    "combined_rules": pwr.combined_rules,  # FULL rules text
                    "metadata": pwr.metadata,
                }
                for idx, pwr in enumerate(prompts_with_rules)
            ],
            "iterations": [
                {
                    "iteration": it.iteration,
                    "is_improvement": it.is_improvement,
                    "mutation_changes": it.mutation_changes,
                    "validation_metadata": it.validation_metadata,
                    "aggregated_fitness": {
                        "total_fitness": it.aggregated_fitness.total_fitness,
                        "mean_fitness": it.aggregated_fitness.mean_fitness,
                        "num_vulnerable": it.aggregated_fitness.num_vulnerable,
                        "num_prompts": it.aggregated_fitness.num_prompts,
                    },
                    "individual_results": [
                        {
                            "prompt": ir.prompt.prompt,  # FULL prompt
                            "language": ir.prompt.language,
                            "cwe_id": ir.prompt.cwe_id,
                            "generated_code": ir.generated_code,  # FULL generated code
                            "fitness": {
                                "raw_count": ir.fitness.raw_count,
                                "weighted_score": ir.fitness.weighted_score,
                                "unique_rules": ir.fitness.unique_rules,
                                "error_count": ir.fitness.error_count,
                                "warning_count": ir.fitness.warning_count,
                                "check_ids": ir.fitness.details.get("check_ids", []),
                            },
                            "generation_latency_ms": ir.generation_latency_ms,
                            "analysis_latency_ms": ir.analysis_latency_ms,
                        }
                        for ir in it.individual_results
                    ],
                }
                for it in result.iterations
            ],
        }
        
        with open(results_file, "w") as f:
            json.dump(serializable, f, indent=2)
        
        print(f"\n📁 Complete results saved to: {results_file}")
        print(f"   • Full prompts: {len(prompts_with_rules)}")
        print(f"   • Full iterations: {len(result.iterations)}")
        print(f"   • Generated code samples: {sum(len(it.individual_results) for it in result.iterations)}")

        # ── Rerun artefacts ──────────────────────────────────────────────────
        # run_config.json — every CLI arg + derived runtime values
        import shlex, subprocess as _subprocess, sys as _sys
        try:
            _git_sha = _subprocess.check_output(
                ["git", "rev-parse", "HEAD"],
                cwd=PROJECT_ROOT,
                stderr=_subprocess.DEVNULL,
            ).decode().strip()
        except Exception:
            _git_sha = None

        run_config = {
            "argv": _sys.argv,
            "args": {
                "backend":                args.backend,
                "model":                  args.model,
                "quantization":           getattr(args, "quantization", None),
                "use_mapping_only":        args.use_mapping_only,
                "interesting_cases":      str(args.interesting_cases) if not args.use_mapping_only else None,
                "rules_map":              str(args.rules_map),
                "n_cases":                args.n_cases,
                "iterations":             args.iterations,
                "early_stop":             args.early_stop,
                "seed":                   args.seed,
                "selection":              args.selection,
                "languages":              args.languages,
                "mutators":               args.mutators,
                "mutator_strategy":       args.mutator_strategy,
                "max_mutation_depth":     args.max_mutation_depth,
                "ucb1_exploration":       args.ucb1_exploration,
                "fitness_strategy":       args.fitness_strategy,
                "fitness_weights":        args.fitness_weights,
                "enable_validation":      args.enable_validation,
                "skip_seen_pairs":       args.skip_seen,
                "mutation_max_retries":   args.mutation_max_retries,
                "semgrep_config":         str(semgrep_config["rule_config"]),
                "semgrep_timeout_seconds":semgrep_config["subprocess_timeout_seconds"],
                "semgrep_jobs":           semgrep_config["jobs"],
                "output_dir":             str(args.output_dir),
            },
            "timestamp": timestamp,
            "git_sha": _git_sha,
            "slurm_job_id": os.getenv("SLURM_JOB_ID"),
            "hostname": os.getenv("HOSTNAME") or __import__("socket").gethostname(),
        }
        config_file = args.output_dir / "run_config.json"
        with open(config_file, "w") as f:
            json.dump(run_config, f, indent=2)

        # rerun.sh — executable script that reproduces the Python command exactly
        lang_arg = f"--languages {shlex.quote(' '.join(args.languages))}" if args.languages else ""
        validation_flag = (
            f"--enable-validation --mutation-max-retries {args.mutation_max_retries}"
            if args.enable_validation else ""
        )
        quant_arg = (
            f"--quantization {shlex.quote(args.quantization)}"
            if getattr(args, "quantization", None) else ""
        )
        mapping_only_flag = "--use-mapping-only" if args.use_mapping_only else ""
        interesting_cases_arg = (
            "" if args.use_mapping_only
            else f"--interesting-cases {shlex.quote(str(args.interesting_cases))}"
        )
        rerun_lines = [
            "#!/bin/bash",
            "# Auto-generated rerun script — reproduces this experiment exactly.",
            f"# Original job: {run_config['slurm_job_id'] or 'local'}  host: {run_config['hostname']}",
            f"# Timestamp: {timestamp}",
            "#",
            "# Usage (from repo root):",
            f"#   bash {args.output_dir}/rerun.sh",
            "#   # or override output dir:",
            f"#   OUTPUT_DIR=experiments/results/rerun_{timestamp} bash {args.output_dir}/rerun.sh",
            "",
            f'OUTPUT_DIR="${{OUTPUT_DIR:-{shlex.quote(str(args.output_dir))}}}"',
            "",
            "python scripts/experiments/run_with_rules_map.py \\",
            f"    --backend {shlex.quote(args.backend)} \\",
            f"    --model {shlex.quote(args.model)} \\",
            *([ f"    {quant_arg} \\" ] if quant_arg else []),
            *([ f"    {mapping_only_flag} \\" ] if mapping_only_flag else []),
            *([ f"    {interesting_cases_arg} \\" ] if interesting_cases_arg else []),
            f"    --rules-map {shlex.quote(str(args.rules_map))} \\",
            f"    --n-cases {args.n_cases} \\",
            f"    --iterations {args.iterations} \\",
            f"    --early-stop {args.early_stop} \\",
            f"    --seed {args.seed} \\",
            f"    --selection {shlex.quote(args.selection)} \\",
            f"    --mutators {' '.join(shlex.quote(m) for m in args.mutators)} \\",
            f"    --mutator-strategy {shlex.quote(args.mutator_strategy)} \\",
            f"    --max-mutation-depth {args.max_mutation_depth} \\",
            f"    --fitness-strategy {shlex.quote(args.fitness_strategy)} \\",
            f"    --fitness-weights {args.fitness_weights[0]} {args.fitness_weights[1]} {args.fitness_weights[2]} \\",
            f"    --semgrep-config {shlex.quote(str(semgrep_config['rule_config']))} \\",
            f"    --semgrep-timeout-seconds {semgrep_config['subprocess_timeout_seconds']} \\",
            f"    --semgrep-jobs {semgrep_config['jobs']} \\",
            *([ f"    {lang_arg} \\" ] if lang_arg else []),
            *([ f"    {validation_flag} \\" ] if validation_flag else []),
            '    --output-dir "$OUTPUT_DIR"',
        ]
        rerun_file = args.output_dir / "rerun.sh"
        rerun_file.write_text("\n".join(rerun_lines) + "\n", encoding="utf-8")
        rerun_file.chmod(0o755)
        print(f"   • run_config.json + rerun.sh saved for easy reproduction")

    print("\n✅ Per-prompt-rules experiment complete!")
    return 0


if __name__ == "__main__":
    sys.exit(main())
