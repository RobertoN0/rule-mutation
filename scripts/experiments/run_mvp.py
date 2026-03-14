#!/usr/bin/env python3
"""
MVP Runner: Minimal end-to-end hill climbing experiment.

This script demonstrates the SBST framework with:
- A single CodeGuard rule (input-validation-injection)
- Test prompts selected from CyberSecEval dataset
- Groq free tier (Llama 3.1 8B)
- Fluff mutation strategy

Test Prompt Selection:
    - Default: 5 random injection prompts from CyberSecEval (Python)
    - With --prompts-file: Use interesting_cases JSON or custom prompts
    - With --n-prompts: Specify how many prompts to select
    - With --language: Filter by language

Usage:
    # Default: 5 random Python injection prompts
    python scripts/experiments/run_mvp.py

    # More prompts:
    python scripts/experiments/run_mvp.py --n-prompts 10

    # Specific language:
    python scripts/experiments/run_mvp.py --language c --n-prompts 8

    # From interesting_cases.json:
    python scripts/experiments/run_mvp.py --prompts-file path/to/interesting_cases.json

    # Dry run (no API calls):
    python scripts/experiments/run_mvp.py --dry-run

Requirements:
    pip install openai datasets
    # Semgrep must be installed:
    pip install semgrep
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

from src.llm_backends import GroqBackend, LLMConfig
from src.llm_backends.base import LLMError
from src.mutation import FluffMutator
from src.optimizer import HillClimber, HillClimbConfig, TestPrompt
from src.evaluation.fitness import FitnessStrategy
from src.evaluation import (
    TestCaseSelector,
    SelectionCriteria,
    select_from_interesting_cases,
)


# ═══════════════════════════════════════════════════════════════════════════════
# CONFIGURATION
# ═══════════════════════════════════════════════════════════════════════════════

# Default CodeGuard rule to test
DEFAULT_RULE = "codeguard-0-input-validation-injection"

# Path to CodeGuard rules
RULES_DIR = PROJECT_ROOT / "project-codeguard" / "skills" / "software-security" / "rules"


def load_rule(rule_id: str) -> str:
    """Load a CodeGuard rule from the rules directory."""
    rule_path = RULES_DIR / f"{rule_id}.md"
    if not rule_path.exists():
        raise FileNotFoundError(f"Rule not found: {rule_path}")
    return rule_path.read_text(encoding="utf-8")


def load_test_prompts(
    prompts_file: Path | None,
    n_prompts: int,
    language: str,
    cwe_category: str,
    seed: int,
) -> list[TestPrompt]:
    """Load test prompts from dataset or file.
    
    Always uses CyberSecEval as the source of truth:
    - If prompts_file is provided: Load from JSON (interesting_cases, etc.)
    - Otherwise: Select randomly from CyberSecEval dataset
    
    Args:
        prompts_file: Optional JSON file with test case selection
        n_prompts: Number of prompts to select (if not using file)
        language: Target language
        cwe_category: CWE category filter ("injection", "crypto", "memory")
        seed: Random seed for reproducibility
        
    Returns:
        List of TestPrompt objects
    """
    if prompts_file:
        # Load from JSON file (interesting_cases format or others)
        print(f"📝 Loading prompts from: {prompts_file}")
        prompts = select_from_interesting_cases(
            json_path=prompts_file,
            shuffle=True,
            seed=seed,
        )
        print(f"   Loaded {len(prompts)} prompts from file")
        return prompts # type: ignore
    
    # Select from CyberSecEval dataset
    print(f"📝 Selecting {n_prompts} {language} prompts from CyberSecEval ({cwe_category})")
    selector = TestCaseSelector()
    
    prompts = selector.select_mvp(
        language=language,
        n_prompts=n_prompts,
        cwe_category=cwe_category,
        seed=seed,
    )
    print(f"   Selected {len(prompts)} prompts (seed={seed})")
    
    # Show what was selected
    cwe_counts: dict[str, int] = {}
    for p in prompts:
        cwe = p.cwe_id or "unknown"
        cwe_counts[cwe] = cwe_counts.get(cwe, 0) + 1
    print(f"   CWEs: {', '.join(f'{k}({v})' for k, v in sorted(cwe_counts.items()))}")
    
    return prompts # type: ignore


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
        description="Run MVP hill climbing experiment"
    )
    parser.add_argument(
        "--rule", "-r",
        default=DEFAULT_RULE,
        help=f"CodeGuard rule ID to test (default: {DEFAULT_RULE})"
    )
    parser.add_argument(
        "--iterations", "-i",
        type=int,
        default=5,
        help="Number of hill climbing iterations (default: 5)"
    )
    parser.add_argument(
        "--model", "-m",
        default="llama-3.1-8b-instant",
        help="Groq model to use (default: llama-3.1-8b-instant)"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Test pipeline without API calls"
    )
    parser.add_argument(
        "--prompts-file",
        type=Path,
        help="JSON file with test prompts (selects from CyberSecEval if not specified)"
    )
    parser.add_argument(
        "--n-prompts",
        type=int,
        default=5,
        help="Number of prompts to select from dataset (default: 5)"
    )
    parser.add_argument(
        "--language",
        default="python",
        help="Target language for prompts (default: python)"
    )
    parser.add_argument(
        "--cwe-category",
        default="injection",
        choices=["injection", "crypto", "memory", "all"],
        help="CWE category to filter (default: injection)"
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
    
    args = parser.parse_args()
    
    print("=" * 60)
    print("🚀 SBST MVP: Hill Climbing for Security Rule Robustness")
    print("=" * 60)
    
    # Load rule
    print(f"\n📜 Loading rule: {args.rule}")
    try:
        rule_text = load_rule(args.rule)
        print(f"   Rule size: {len(rule_text):,} characters")
    except FileNotFoundError as e:
        print(f"❌ Error: {e}")
        sys.exit(1)
    
    # Load test prompts (always from dataset or selector JSON)
    print()
    test_prompts = load_test_prompts(
        prompts_file=args.prompts_file,
        n_prompts=args.n_prompts,
        language=args.language,
        cwe_category=args.cwe_category,
        seed=args.seed,
    )
    
    if not test_prompts:
        print("❌ Error: No test prompts loaded")
        sys.exit(1)
    
    # Create LLM backend
    if args.dry_run:
        print("\n🔧 DRY RUN MODE: Using mock backend")
        backend = create_mock_backend()
    else:
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
            max_tokens=2048,
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
    
    # Create mutator
    print(f"\n🧬 Initializing FluffMutator (seed={args.seed})")
    mutator = FluffMutator(seed=args.seed)
    
    # Configure hill climber
    hc_config = HillClimbConfig(
        max_iterations=args.iterations,
        fitness_strategy=FitnessStrategy.SEVERITY_WEIGHTED,
        early_stop_no_improvement=3,
        save_intermediate=True,
        output_dir=args.output_dir,
        verbose=True,
    )
    
    print(f"\n⚙️  Hill Climbing Configuration:")
    print(f"   Max iterations: {hc_config.max_iterations}")
    print(f"   Fitness strategy: {hc_config.fitness_strategy.name}")
    print(f"   Early stop: {hc_config.early_stop_no_improvement} iterations without improvement")
    print(f"   Output dir: {args.output_dir}")
    
    # Create hill climber
    climber = HillClimber(backend, mutator, hc_config)
    
    # Run optimization
    print("\n" + "=" * 60)
    print("🏔️  Starting Hill Climbing Optimization")
    print("=" * 60)
    
    try:
        result = climber.optimize(
            rule_text=rule_text,
            test_prompts=test_prompts,
        )
    except LLMError as e:
        print(f"\n❌ LLM Error: {e}")
        sys.exit(1)
    except KeyboardInterrupt:
        print("\n\n⚠️  Interrupted by user")
        sys.exit(130)
    
    # Print results summary
    print("\n" + "=" * 60)
    print("📊 RESULTS SUMMARY")
    print("=" * 60)
    print(f"Rule tested: {args.rule}")
    print(f"Test prompts: {len(test_prompts)}")
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
    
    # Save final results
    if args.output_dir:
        args.output_dir.mkdir(parents=True, exist_ok=True)
        results_file = args.output_dir / "mvp_results.json"
        
        # Serialize results (simplified for JSON)
        serializable = {
            "rule_id": args.rule,
            "model": args.model,
            "num_prompts": len(test_prompts),
            "num_iterations": len(result.iterations),
            "original_fitness": result.original_fitness.total_fitness,
            "best_fitness": result.best_fitness.total_fitness,
            "fitness_increase": result.fitness_increase,
            "improvement_ratio": result.improvement_ratio,
            "total_time_seconds": result.total_time_seconds,
            "total_llm_calls": result.total_llm_calls,
        }
        
        with open(results_file, "w") as f:
            json.dump(serializable, f, indent=2)
        
        print(f"\n📁 Results saved to: {results_file}")
    
    print("\n✅ MVP experiment complete!")
    return 0


if __name__ == "__main__":
    sys.exit(main())
