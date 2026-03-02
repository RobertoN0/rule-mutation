#!/usr/bin/env python3
"""
Batched Experiment Runner

Runs hill climbing experiments using batches of test cases.
Supports two modes:
1. From interesting_cases JSON file (--cases)
2. From CyberSecEval dataset directly (--from-dataset)

Usage:
    # From interesting_cases file:
    python scripts/run_batched_experiment.py \
        --cases pipeline_breakdown/generation_results/interesting_cases_96_sonnet_4_6.json \
        --batch-size 4 \
        --iterations 5 \
        --dry-run

    # From CyberSecEval dataset (no pre-screened cases):
    python scripts/run_batched_experiment.py \
        --from-dataset \
        --language python \
        --n-prompts 20 \
        --batch-size 5 \
        --iterations 10

    # For real execution:
    python scripts/run_batched_experiment.py \
        --cases interesting_cases.json \
        --batch-size 8 \
        --iterations 10
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path

# Add src to path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.evaluation import (
    load_interesting_cases,
    TestPrompt,
    TestCaseSelector,
    SelectionCriteria,
    select_from_interesting_cases,
)
from src.llm_backends import GroqBackend, LLMConfig
from src.llm_backends.base import LLMError
from src.mutation import FluffMutator
from src.optimizer import HillClimber, HillClimbConfig
from src.evaluation.fitness import FitnessStrategy


# ═══════════════════════════════════════════════════════════════════════════════
# CONFIGURATION
# ═══════════════════════════════════════════════════════════════════════════════

DEFAULT_RULE = "codeguard-0-input-validation-injection"
RULES_DIR = PROJECT_ROOT / "project-codeguard" / "skills" / "software-security" / "rules"


def load_rule(rule_id: str) -> str:
    """Load a CodeGuard rule from the rules directory."""
    rule_path = RULES_DIR / f"{rule_id}.md"
    if not rule_path.exists():
        raise FileNotFoundError(f"Rule not found: {rule_path}")
    return rule_path.read_text(encoding="utf-8")


def load_prompts_for_batching(args) -> tuple[list[TestPrompt], str]:
    """Load test prompts based on command line arguments.
    
    Returns:
        Tuple of (prompts, source_description)
    """
    if args.cases:
        # Load from interesting_cases JSON
        prompts = select_from_interesting_cases(
            json_path=args.cases,
            languages=[args.filter_language] if args.filter_language else None,
            diff_types=[args.filter_diff_type] if args.filter_diff_type else None,
            shuffle=args.shuffle,
            seed=args.seed,
        )
        return prompts, f"interesting_cases ({args.cases.name})"
    
    elif args.from_dataset:
        # Load directly from CyberSecEval
        selector = TestCaseSelector()
        prompts = selector.select_mvp(
            language=args.language,
            n_prompts=args.n_prompts,
            cwe_category=args.cwe_category,
            seed=args.seed,
        )
        return prompts, f"CyberSecEval ({args.language}, {args.cwe_category})"
    
    else:
        raise ValueError("Must specify --cases or --from-dataset")


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
            # Return simple code for testing
            return LLMResponse(
                content='print("hello world")',
                model="mock-model",
                input_tokens=100,
                output_tokens=50,
                latency_ms=10.0,
            )
    
    return MockBackend()


def run_batch_experiment(
    batch_num: int,
    prompts: list[TestPrompt],
    rule_text: str,
    backend,
    mutator: FluffMutator,
    config: HillClimbConfig,
) -> dict:
    """Run a single batch experiment."""
    print(f"\n{'='*60}")
    print(f"🔬 BATCH {batch_num}: Running with {len(prompts)} test cases")
    print(f"{'='*60}")
    
    climber = HillClimber(backend, mutator, config)
    
    try:
        result = climber.optimize(
            rule_text=rule_text,
            test_prompts=prompts, # type: ignore
        )
        
        return {
            "batch_num": batch_num,
            "num_prompts": len(prompts),
            "iterations": len(result.iterations),
            "original_fitness": result.original_fitness.total_fitness,
            "best_fitness": result.best_fitness.total_fitness,
            "fitness_increase": result.fitness_increase,
            "improvement_ratio": result.improvement_ratio,
            "total_time_seconds": result.total_time_seconds,
            "total_llm_calls": result.total_llm_calls,
            "prompts": [
                {
                    "language": p.language,
                    "cwe_id": p.cwe_id,
                    "metadata": p.metadata,
                }
                for p in prompts
            ],
        }
    except LLMError as e:
        print(f"❌ Batch {batch_num} failed: {e}")
        return {
            "batch_num": batch_num,
            "error": str(e),
            "num_prompts": len(prompts),
        }


def main():
    parser = argparse.ArgumentParser(
        description="Run batched hill climbing experiments"
    )
    
    # Source selection (mutually exclusive group)
    source_group = parser.add_mutually_exclusive_group(required=True)
    source_group.add_argument(
        "--cases", "-c",
        type=Path,
        help="Path to interesting_cases JSON file"
    )
    source_group.add_argument(
        "--from-dataset",
        action="store_true",
        help="Select prompts directly from CyberSecEval dataset"
    )
    
    # Dataset options (used with --from-dataset)
    parser.add_argument(
        "--n-prompts",
        type=int,
        default=20,
        help="Number of prompts to select from dataset (default: 20)"
    )
    parser.add_argument(
        "--language",
        default="python",
        help="Language for dataset selection (default: python)"
    )
    parser.add_argument(
        "--cwe-category",
        default="injection",
        choices=["injection", "crypto", "memory", "all"],
        help="CWE category for dataset selection (default: injection)"
    )
    
    # Batching options
    parser.add_argument(
        "--batch-size", "-b",
        type=int,
        default=4,
        help="Number of test cases per batch (default: 4)"
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
        help="Number of hill climbing iterations per batch (default: 5)"
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
        "--filter-language",
        type=str,
        help="Filter to specific language (e.g., 'python', 'c')"
    )
    parser.add_argument(
        "--filter-diff-type",
        type=str,
        help="Filter to specific diff_type (e.g., 'rules_helped')"
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
        "--shuffle",
        action="store_true",
        help="Shuffle cases before batching"
    )
    
    args = parser.parse_args()
    
    print("=" * 60)
    print("🧪 SBST Batched Experiment Runner")
    print("=" * 60)
    
    # Load test prompts
    print(f"\n📂 Loading test prompts...")
    prompts, source_desc = load_prompts_for_batching(args)
    print(f"   Source: {source_desc}")
    print(f"   Total prompts: {len(prompts)}")
    
    # Show language/CWE distribution
    lang_counts: dict[str, int] = {}
    cwe_counts: dict[str, int] = {}
    for p in prompts:
        lang_counts[p.language] = lang_counts.get(p.language, 0) + 1
        cwe = p.cwe_id or "unknown"
        cwe_counts[cwe] = cwe_counts.get(cwe, 0) + 1
    print(f"   Languages: {', '.join(f'{k}({v})' for k, v in sorted(lang_counts.items()))}")
    print(f"   CWEs ({len(cwe_counts)}): {', '.join(list(cwe_counts.keys())[:5])}{'...' if len(cwe_counts) > 5 else ''}")
    
    if len(prompts) == 0:
        print("❌ No prompts loaded!")
        return 1
    
    # Create batches
    batch_size = args.batch_size
    batches: list[list[TestPrompt]] = []
    
    # Shuffle if requested
    if args.shuffle:
        import random
        rng = random.Random(args.seed)
        prompts = list(prompts)
        rng.shuffle(prompts)
    
    # Create batches
    for i in range(0, len(prompts), batch_size):
        batches.append(prompts[i:i + batch_size])
    
    print(f"\n📦 Created {len(batches)} batches of ~{batch_size} prompts each")
    
    # Load rule
    print(f"\n📜 Loading rule: {args.rule}")
    rule_text = load_rule(args.rule)
    print(f"   Rule size: {len(rule_text):,} characters")
    
    # Create backend
    if args.dry_run:
        print("\n🔧 DRY RUN MODE: Using mock backend")
        backend = create_mock_backend()
    else:
        api_key = os.getenv("GROQ_API_KEY")
        if not api_key:
            print("\n❌ Error: GROQ_API_KEY environment variable not set")
            return 1
        
        print(f"\n🤖 Initializing Groq backend: {args.model}")
        config = LLMConfig(
            model=args.model,
            api_key=api_key,
            temperature=0.0,
            max_tokens=2048,
        )
        backend = GroqBackend(config)
    
    # Create mutator
    mutator = FluffMutator(seed=args.seed)
    
    # Hill climber config
    hc_config = HillClimbConfig(
        max_iterations=args.iterations,
        fitness_strategy=FitnessStrategy.SEVERITY_WEIGHTED,
        early_stop_no_improvement=3,
        save_intermediate=False,
        output_dir=args.output_dir,
        verbose=True,
    )
    
    print(f"\n⚙️  Configuration:")
    print(f"   Batches: {len(batches)}")
    print(f"   Iterations per batch: {args.iterations}")
    print(f"   Total test cases: {len(prompts)}")
    print(f"   Estimated LLM calls: ~{len(prompts) * args.iterations * 2}")
    
    # Run all batches
    all_results = []
    start_time = datetime.now()
    
    for i, batch in enumerate(batches, 1):
        # batch is already list[TestPrompt]
        result = run_batch_experiment(
            batch_num=i,
            prompts=batch,
            rule_text=rule_text,
            backend=backend,
            mutator=mutator,
            config=hc_config,
        )
        all_results.append(result)
    
    end_time = datetime.now()
    total_duration = (end_time - start_time).total_seconds()
    
    # Summary
    print("\n" + "=" * 60)
    print("📊 EXPERIMENT SUMMARY")
    print("=" * 60)
    
    total_llm_calls = sum(r.get("total_llm_calls", 0) for r in all_results)
    avg_improvement = sum(r.get("fitness_increase", 0) for r in all_results) / len(all_results)
    
    print(f"Batches completed: {len(all_results)}")
    print(f"Total duration: {total_duration:.1f}s")
    print(f"Total LLM calls: {total_llm_calls}")
    print(f"Average fitness increase: {avg_improvement:+.2f}")
    
    for r in all_results:
        batch_num = r.get("batch_num", "?")
        if "error" in r:
            print(f"   Batch {batch_num}: ❌ Error - {r['error']}")
        else:
            orig = r.get("original_fitness", 0)
            best = r.get("best_fitness", 0)
            improvement = r.get("fitness_increase", 0)
            print(f"   Batch {batch_num}: {orig:.1f} → {best:.1f} ({improvement:+.1f})")
    
    # Save results
    args.output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    results_file = args.output_dir / f"batched_results_{timestamp}.json"
    
    with open(results_file, "w") as f:
        json.dump({
            "config": {
                "source": source_desc,
                "cases_file": str(args.cases) if args.cases else None,
                "from_dataset": args.from_dataset if hasattr(args, 'from_dataset') else False,
                "batch_size": args.batch_size,
                "iterations": args.iterations,
                "rule": args.rule,
                "model": args.model,
                "seed": args.seed,
                "dry_run": args.dry_run,
            },
            "summary": {
                "total_batches": len(batches),
                "total_prompts": len(prompts),
                "total_duration_seconds": total_duration,
                "total_llm_calls": total_llm_calls,
                "avg_fitness_increase": avg_improvement,
            },
            "batches": all_results,
        }, f, indent=2)
    
    print(f"\n📁 Results saved to: {results_file}")
    print("✅ Experiment complete!")
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
