#!/usr/bin/env python3
"""
Run Hill Climbing with Per-Prompt Rule Mapping.

Prompts come exclusively from a retrieval map (retrieval_map_*.json).
Baseline Semgrep scores are computed live at iteration 0 — no pre-computed
values are loaded.

Usage:
    # Run with first 5 cases from the default retrieval map
    python scripts/experiments/run_with_rules_map.py --n-cases 5

    # Full run with specific model and iteration budget
    python scripts/experiments/run_with_rules_map.py \
        --rules-map rule_maps/map_qwen32b_python_java.json \
        --model Qwen/Qwen2.5-Coder-32B-Instruct \
        --iterations 10

    # Dry run (no API calls)
    python scripts/experiments/run_with_rules_map.py --dry-run
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import warnings
from pathlib import Path

# Silence noisy third-party output that floods the log:
#   * nlpaug emits SyntaxWarnings about `\s` escape sequences on import.
#   * nlpaug.SynonymAug calls nltk.download('averaged_perceptron_tagger') on
#     every augment() — defensive but produces hundreds of "[nltk_data] ..."
#     lines per experiment. We pre-fetch the corpora once (quiet) so the
#     defensive download finds them present and stays silent.
warnings.filterwarnings(
    "ignore",
    category=SyntaxWarning,
    module=r"nlpaug.*",
)
try:
    import nltk  # type: ignore
    for _pkg in ("wordnet", "omw-1.4", "averaged_perceptron_tagger",
                 "averaged_perceptron_tagger_eng", "punkt", "punkt_tab"):
        try:
            nltk.download(_pkg, quiet=True, raise_on_error=False)
        except Exception:
            pass
except ImportError:
    pass


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

# Load .env from project root so API keys defined there flow into os.environ.
try:
    from dotenv import load_dotenv  # type: ignore
    load_dotenv(PROJECT_ROOT / ".env")
except ImportError:
    pass

from src.llm_backends import LLMConfig, ClaudeBackend, OpenAIBackend
from src.llm_backends.base import LLMError

# DelftBlue local backend depends on the [gpu] extras (accelerate, bitsandbytes).
# Import lazily so the API-only replication path on macOS/Windows still works.
try:
    from src.llm_backends import DelftBlueLocalBackend  # noqa: F401
    _HAS_DELFTBLUE = True
except ImportError:
    _HAS_DELFTBLUE = False
from src.mutation import (
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
    load_rule_mapping,
    create_rule_loader,
    RuleMappingIndex,
    RuleLoader,
    PromptWithRules,
)
from src.evaluation.composite_fitness import CompositeFitnessEvaluator
from src.evaluation.semgrep_runner import (
    configure_semgrep,
    configure_semgrep_debug,
    get_semgrep_config,
)


# ═══════════════════════════════════════════════════════════════════════════════
# CONFIGURATION
# ═══════════════════════════════════════════════════════════════════════════════

# Output schema version written to run_config.json. Bumped to 2 for the
# post-redesign schema (unified mutation_chain, stateless random baseline).
# Distinguishes new run trees from the old (schema_version absent ⇒ legacy).
SCHEMA_VERSION = 2

# Default paths (relative to project root)
DEFAULT_RULES_MAP = (
    PROJECT_ROOT / "rule_maps" / "map_qwen32b_python_java.json"
)
RULES_DIR = PROJECT_ROOT / "project-codeguard" / "skills" / "software-security" / "rules"


class _TeeStream:
    """Write text to multiple streams in lockstep.

    Used to duplicate stdout/stderr into ``<output_dir>/run.log`` so local runs
    leave a persistent log next to their artifacts (mirroring DelftBlue SLURM
    ``.out`` / ``.err`` files landing in ``logs/``).
    """

    def __init__(self, *streams):
        self._streams = streams

    def write(self, data):
        for s in self._streams:
            try:
                s.write(data)
                s.flush()
            except (ValueError, OSError):
                pass

    def flush(self):
        for s in self._streams:
            try:
                s.flush()
            except (ValueError, OSError):
                pass

    def isatty(self):
        return self._streams[0].isatty() if self._streams else False



def load_prompts_with_rules(
    rules_map_path: Path,
    rule_loader: RuleLoader,
    n_cases: int | None = None,
    languages: list[str] | None = None,
    selection: str = "first",
    seed: int = 42,
) -> list[PromptWithRules]:
    """Load prompts from the retrieval mapping.

    Each RuleMapping entry provides: prompt, language, cwe_id, rules_retrieved.
    Baseline Semgrep scores and reference codes for code-divergence are computed
    live at iteration 0 by the hill climber.

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
    print(f"📥 Loaded {len(mappings)} entries from retrieval map")
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

    print(f"✅ Created {len(prompts_with_rules)} prompts with rules")

    return prompts_with_rules



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
        "--model", "-m",
        default=None,
        help=(
            "Model identifier. If omitted, resolved per --backend: "
            "claude → claude-haiku-4-5, openai → gpt-4o-mini, "
            "delftblue → Qwen/Qwen2.5-Coder-32B-Instruct."
        ),
    )
    parser.add_argument(
        "--backend", "-b",
        default="delftblue",
        choices=["claude", "openai", "delftblue"],
        help=(
            "LLM backend: claude (Anthropic Messages API), "
            "openai (OpenAI Chat Completions API), "
            "delftblue (HuggingFace local inference on a DelftBlue GPU node, "
            "requires [gpu] extras)."
        ),
    )
    parser.add_argument(
        "--quantization",
        default="fp16",
        choices=["fp16", "4bit"],
        help="Quantization for the delftblue backend: fp16 (default) or 4bit"
    )
    parser.add_argument(
        "--bnb-compute-dtype",
        default="float16",
        choices=["float16", "bfloat16"],
        help=(
            "4-bit (NF4) dequant compute dtype for the delftblue backend. "
            "Only used when --quantization 4bit. Default float16; use bfloat16 "
            "for bf16-native models (e.g. Llama-3.3) to avoid fp16 overflow."
        ),
    )
    parser.add_argument(
        "--temperature",
        type=float,
        default=0.0,
        help=(
            "Sampling temperature for the code-gen (model-under-test) calls "
            "only (default: 0.0 = deterministic greedy decoding, matching the "
            "temp=0 baselines). >0.0 enables sampling (do_sample=True) for the "
            "temp>0 statistical arm. Does NOT affect LLM mutators: they pass "
            "their own fixed per-call temperature (e.g. paraphrase=0.6)."
        ),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Test pipeline without API calls"
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
        default=["synonym_replacement"],
        help=(
            "Space-separated list of mutation operators (default: synonym_replacement). "
            "LLM-based mutators (negation_injection, voice_change, paraphrase) "
            "require a real LLM backend (delftblue/claude/openai). "
            "Single value works for backward compat."
        ),
    )
    # ----- (1+1) EA + Pareto archive flags -----------------------------------
    parser.add_argument(
        "--optimizer",
        default="ea",
        choices=["ea", "random_baseline"],
        help=(
            "Optimizer family (default: ea). "
            "ea = (1+1) EA over per-rule Pareto archive (3 objectives); "
            "random_baseline = stateless per-iteration multi-mutation sampler, no archive."
        ),
    )
    parser.add_argument(
        "--archive-cap",
        type=int,
        default=6,
        help="EA only: max Pareto archive size per rule (default: 6, sweep-tunable).",
    )
    parser.add_argument(
        "--restart-h",
        type=int,
        default=8,
        help=(
            "EA only: consecutive non-inserts before stagnation restart "
            "(default: 8, sweep-tunable)."
        ),
    )
    parser.add_argument(
        "--max-depth-ea",
        type=int,
        default=4,
        help=(
            "EA only: per-entry depth cap (mutations from original; default: 4). "
            "When all archive entries hit this, the rule's archive is reset."
        ),
    )
    parser.add_argument(
        "--max-mutations-per-iter",
        type=int,
        default=4,
        help=(
            "random_baseline only: max chain length K (default: 4). Each iteration "
            "samples n in [1, K] distinct mutators and applies them to the original rule."
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
            "model — no second model is loaded. No-op when --backend is not delftblue."
        ),
    )
    parser.add_argument(
        "--mutation-max-retries",
        type=int,
        default=2,
        help=(
            "DEPRECATED (no-op since the 2026-06-11 retry removal; kept for config/CLI compat). "
            "Mutations are now applied once; identity results are skipped as no-ops."
        ),
    )
    parser.add_argument(
        "--no-eval-cache",
        action="store_true",
        default=not bool(int(os.getenv("ENABLE_EVAL_CACHE", "1"))),
        help=(
            "Disable the per-prompt (code, Semgrep) evaluation cache. "
            "By default the cache is ON: under temperature=0 greedy decoding, "
            "prompts whose assembled rule text is byte-identical to a prior "
            "evaluation reuse the cached code and Semgrep result, skipping "
            "both LLM generation and Semgrep. Use this flag (or "
            "ENABLE_EVAL_CACHE=0) to force re-evaluation every time."
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
    parser.add_argument(
        "--output-dir", "-o",
        type=Path,
        default=PROJECT_ROOT / "experiments" / "results",
        help="Directory to save results"
    )
    
    args = parser.parse_args()

    try:
        from transformers import set_seed as _set_seed
        _set_seed(args.seed)
    except Exception as _seed_err:  # transformers absent (non-GPU env) → best effort
        import random as _random
        _random.seed(args.seed)
        print(f"⚠️  transformers.set_seed unavailable ({_seed_err}); seeded stdlib random only")

    # Install stdout/stderr tee → <output_dir>/run.log so local runs leave a
    # persistent log next to their artifacts (DelftBlue SLURM .out/.err files
    # already land in logs/)
    if args.output_dir is not None:
        args.output_dir.mkdir(parents=True, exist_ok=True)
        _log_path = args.output_dir / "run.log"
        _log_fh = open(_log_path, "w", buffering=1)  # line-buffered
        _orig_stdout, _orig_stderr = sys.stdout, sys.stderr
        sys.stdout = _TeeStream(_orig_stdout, _log_fh)
        sys.stderr = _TeeStream(_orig_stderr, _log_fh)
        import atexit as _atexit
        def _restore_streams():
            sys.stdout = _orig_stdout
            sys.stderr = _orig_stderr
            try:
                _log_fh.close()
            except Exception:
                pass
        _atexit.register(_restore_streams)
        print(f"📝 Logging stdout+stderr to {_log_path}")

    print("=" * 70)
    print("🚀 SBST: Hill Climbing with Per-Prompt Rule Mapping")
    print("=" * 70)

    # ── Graceful pre-timeout shutdown ────────────────────────────────────────
    # SLURM (--signal=B:USR1@<lead>) forwards SIGUSR1 a configurable number of
    # seconds before the wall-time SIGKILL. We flip a flag; the optimizer checks
    # it at the top of each iteration and breaks cleanly, so the run still writes
    # its final archive snapshot, hillclimb_summary, and run_config.json
    # instead of being killed mid-iteration with those artefacts unwritten.
    import signal as _signal
    _stop_requested = {"flag": False}
    def _on_sigusr1(_signum, _frame):
        if not _stop_requested["flag"]:
            _stop_requested["flag"] = True
            print("\n⏱️  SIGUSR1 received (SLURM pre-timeout) — finishing the current "
                  "iteration then saving final results.", flush=True)
    try:
        _signal.signal(_signal.SIGUSR1, _on_sigusr1)
    except (ValueError, OSError):
        pass  # not on main thread / unsupported platform — degrade silently
    _should_stop = lambda: _stop_requested["flag"]

    # Validate input files
    if not args.rules_map.exists():
        print(f"❌ Error: Rules map file not found: {args.rules_map}")
        sys.exit(1)
    
    # Create rule loader
    rule_loader = create_rule_loader(RULES_DIR)
    print(f"📜 Rule loader initialized: {len(rule_loader.available_rules)} rules available")
    
    # Load prompts with rules
    print()
    prompts_with_rules = load_prompts_with_rules(
        rules_map_path=args.rules_map,
        rule_loader=rule_loader,
        n_cases=args.n_cases,
        languages=args.languages,
        selection=args.selection,
        seed=args.seed,
    )
    
    if not prompts_with_rules:
        print("❌ Error: No prompts loaded")
        sys.exit(1)

    # Resolve default model per backend if --model was not provided.
    if args.model is None:
        BACKEND_DEFAULT_MODELS = {
            "claude":    "claude-haiku-4-5",
            "openai":    "gpt-4o-mini",
            "delftblue": "Qwen/Qwen2.5-Coder-32B-Instruct",
        }
        args.model = BACKEND_DEFAULT_MODELS[args.backend]

    # Create LLM backend
    if args.dry_run:
        print("\n🔧 DRY RUN MODE: Using mock backend")
        backend = create_mock_backend()
    elif args.backend == "delftblue":
        # Local HuggingFace backend for DelftBlue GPU nodes
        if not _HAS_DELFTBLUE:
            print(
                "❌ DelftBlue backend requires the [gpu] extras "
                "(accelerate/bitsandbytes). Install them with:\n"
                "     uv sync --extra gpu"
            )
            sys.exit(1)
        print(f"\n🤖 Initializing DelftBlue local backend: {args.model}")
        print(f"   Quantization: {args.quantization}")

        config = LLMConfig(
            model=args.model,
            temperature=args.temperature,
            max_tokens=4096,
            extra={
                "quantization": args.quantization,
                "bnb_4bit_compute_dtype": args.bnb_compute_dtype,
                "local_files_only": True,
                "trust_remote_code": True,
            },
        )
        try:
            backend = DelftBlueLocalBackend(config)  # type: ignore[name-defined]
            if backend.is_available():
                print("   ✅ Model found in local cache")
            else:
                print("   ⚠️  Model not found in local cache or CUDA unavailable")
                print("   Hint: Set HF_HOME and TRANSFORMERS_CACHE to your model directory")
                sys.exit(1)
        except LLMError as e:
            print(f"❌ Error initializing local backend: {e}")
            sys.exit(1)
    elif args.backend == "claude":
        # Anthropic Claude backend (replication-friendly, paid API)
        api_key = os.getenv("ANTHROPIC_API_KEY")
        if not api_key:
            print("\n❌ Error: ANTHROPIC_API_KEY environment variable not set")
            print("   Get your key from: https://console.anthropic.com")
            print("   Then add it to .env (see .env.example) or export it.")
            sys.exit(1)

        print(f"\n🤖 Initializing Claude backend: {args.model}")
        config = LLMConfig(
            model=args.model,
            api_key=api_key,
            temperature=args.temperature,
            max_tokens=4096,
        )
        try:
            backend = ClaudeBackend(config)
            if backend.is_available():
                print("   ✅ Anthropic API key present (deferred connectivity check)")
        except LLMError as e:
            print(f"❌ Error initializing Claude backend: {e}")
            sys.exit(1)
    elif args.backend == "openai":
        # OpenAI Chat Completions backend (paid API)
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            print("\n❌ Error: OPENAI_API_KEY environment variable not set")
            print("   Get your key from: https://platform.openai.com/api-keys")
            print("   Then add it to .env (see .env.example) or export it.")
            sys.exit(1)

        print(f"\n🤖 Initializing OpenAI backend: {args.model}")
        config = LLMConfig(
            model=args.model,
            api_key=api_key,
            temperature=args.temperature,
            max_tokens=4096,
        )
        try:
            backend = OpenAIBackend(config)
            if backend.is_available():
                print("   ✅ OpenAI API connection verified")
            else:
                print("   ⚠️  Could not verify OpenAI API connection — will attempt anyway")
        except LLMError as e:
            print(f"❌ Error initializing OpenAI backend: {e}")
            sys.exit(1)

    # Create mutator pool
    _LLM_MUTATORS = {"negation_injection", "voice_change", "paraphrase"}
    _LLM_BACKENDS = {"delftblue", "claude", "openai"}
    has_llm_mutator = any(m in _LLM_MUTATORS for m in args.mutators)

    if has_llm_mutator and args.backend not in _LLM_BACKENDS:
        llm_names = [m for m in args.mutators if m in _LLM_MUTATORS]
        print(
            f"\n❌ Error: LLM mutator(s) {llm_names} need a real LLM backend "
            f"(delftblue/claude/openai). Got --backend={args.backend}."
        )
        sys.exit(1)

    if has_llm_mutator and args.backend in ("claude", "openai"):
        llm_names = [m for m in args.mutators if m in _LLM_MUTATORS]
        print(
            f"\n💸 NOTE: LLM mutator(s) {llm_names} share the code-gen backend "
            f"({args.backend}). They will issue ADDITIONAL paid API calls — "
            f"budget accordingly."
        )

    print(f"\n🧬 Initializing mutator pool: {args.mutators}")
    print(f"   Seed: {args.seed}")
    backend_for_mutator = backend if has_llm_mutator else None # type: ignore
    pool = create_mutator_pool(
        args.mutators,
        seed=args.seed,
        backend=backend_for_mutator,
    )

    # Create validator if enabled
    validator = None
    if args.enable_validation:
        use_ppl = getattr(args, "enable_perplexity", False) and args.backend == "delftblue"
        ppl_model_handle = None
        ppl_tokenizer_handle = None
        if use_ppl:
            print(f"\n🔬 Setting up MutationQualityValidator (perplexity gate ON)")
            print(f"   Force-loading generation model for perplexity scoring …")
            ppl_model_handle = backend._load_model() # type: ignore
            ppl_tokenizer_handle = backend._load_tokenizer() # type: ignore
            print(f"   Generation model loaded: {type(ppl_model_handle).__name__}")
        else:
            print(f"\n🔬 Setting up MutationQualityValidator")
        print(f"   SBERT semantic similarity (all-mpnet-base-v2, threshold=0.75)")
        print(f"   Structural criteria: inline code retention + security keyword retention")
        if use_ppl:
            print(f"   Perplexity ratio (threshold=2.5, model=32B shared)")
        validator = MutationQualityValidator(
            use_sbert=True,
            use_perplexity=use_ppl,
            ppl_model_handle=ppl_model_handle,
            ppl_tokenizer_handle=ppl_tokenizer_handle,
        )

    # Build composite evaluator (always on — provides CodeBLEU secondary axis)
    # reference_codes starts empty; the hill climber populates it from iter-0 LLM output
    _eval_lang = args.languages[0] if args.languages and len(args.languages) == 1 else "python"
    composite_evaluator = CompositeFitnessEvaluator(reference_codes={}, lang=_eval_lang)

    # Configure hill climber
    hc_config = HillClimbConfig(
        max_iterations=args.iterations,
        save_intermediate=True,
        output_dir=args.output_dir,
        verbose=True,
        enable_validation=args.enable_validation,
        mutation_max_retries=args.mutation_max_retries,
        enable_eval_cache=not args.no_eval_cache,
        optimizer=args.optimizer,
        archive_cap=args.archive_cap,
        restart_h=args.restart_h,
        max_depth_ea=args.max_depth_ea,
        max_mutations_per_iter=args.max_mutations_per_iter,
    )

    print(f"\n⚙️  Hill Climbing Configuration:")
    print(f"   Test cases: {len(prompts_with_rules)}")
    print(f"   Max iterations: {hc_config.max_iterations}")
    print(f"   Optimizer: {args.optimizer}"
          + (f"   (archive_cap={args.archive_cap}, restart_h={args.restart_h}, "
             f"max_depth_ea={args.max_depth_ea})" if args.optimizer == "ea" else "")
          + (f"   (max_depth={args.max_depth_ea})" if args.optimizer == "random_baseline" else ""))
    print(f"   Mutators: {args.mutators}")
    print(f"   Validation: {'enabled (SBERT + structural)' if args.enable_validation else 'disabled'}")
    print(f"   Eval cache: {'enabled' if hc_config.enable_eval_cache else 'disabled'}")
    print(f"   Output dir: {args.output_dir}")
    
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
    climber = HillClimber(backend, pool, hc_config, validator=validator, # type: ignore
                          composite_evaluator=composite_evaluator)
    
    # Run optimization with per-prompt rules
    print("\n" + "=" * 70)
    print("🏔️  Starting Per-Prompt-Rules Hill Climbing Optimization")
    print("=" * 70)
    
    try:
        result = climber.optimize_per_prompt_rules(
            prompts_with_rules=prompts_with_rules,
            should_stop_fn=_should_stop,
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
    print(
        f"Tokens: {result.total_input_tokens:,} in + "
        f"{result.total_output_tokens:,} out = "
        f"{result.total_input_tokens + result.total_output_tokens:,}"
    )
    print()
    _orig_raw = sum(r.raw_count for r in result.original_fitness.individual_results)
    _best_raw = sum(r.raw_count for r in result.best_fitness.individual_results)
    print(f"Original fitness: {result.original_fitness.total_fitness:.1f}")
    print(f"  - Vulnerable prompts: {result.original_fitness.num_vulnerable}/{result.original_fitness.num_prompts}")
    print(f"  - Raw vulnerabilities (total semgrep findings): {_orig_raw}")
    print(f"  - Mean fitness: {result.original_fitness.mean_fitness:.2f}")
    print()
    print(f"Best fitness: {result.best_fitness.total_fitness:.1f}")
    print(f"  - Vulnerable prompts: {result.best_fitness.num_vulnerable}/{result.best_fitness.num_prompts}")
    print(f"  - Raw vulnerabilities (total semgrep findings): {_best_raw}")
    print(f"  - Mean fitness: {result.best_fitness.mean_fitness:.2f}")
    print()
    print(f"Fitness increase: {result.fitness_increase:+.1f}")
    print(f"Improvement ratio: {result.improvement_ratio:.2f}x")
    
    # Save detailed results
    if args.output_dir:
        args.output_dir.mkdir(parents=True, exist_ok=True)
        from datetime import datetime
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

        # The per-prompt trajectory (intermediate/{iter_id}.jsonl), per-iteration
        # records (iterations.jsonl), archive snapshots (archive_snapshots/), mutated
        # rules (mutated_rules/), and the run summary (hillclimb_summary_*.json) are
        # all written during the run by HillClimber. There is intentionally NO
        # consolidated per_prompt_rules_results dump — it was fully derivable from
        # those files (output-schema spec File 8).

        # ── Rerun artefacts ──────────────────────────────────────────────────
        # run_config.json — every CLI arg + derived runtime values
        import subprocess as _subprocess, sys as _sys
        try:
            _git_sha = _subprocess.check_output(
                ["git", "rev-parse", "HEAD"],
                cwd=PROJECT_ROOT,
                stderr=_subprocess.DEVNULL,
            ).decode().strip()
        except Exception:
            _git_sha = None

        run_config = {
            "schema_version": SCHEMA_VERSION,
            "argv": _sys.argv,
            "args": {
                "backend":                args.backend,
                "model":                  args.model,
                "quantization":           getattr(args, "quantization", None),
                "bnb_compute_dtype":      getattr(args, "bnb_compute_dtype", None),
                "temperature":            getattr(args, "temperature", None),
                "rules_map":              str(args.rules_map),
                "n_cases":                args.n_cases,
                "iterations":             args.iterations,
                "seed":                   args.seed,
                "selection":              args.selection,
                "languages":              args.languages,
                "mutators":               args.mutators,
                "optimizer":              args.optimizer,
                "archive_cap":            args.archive_cap,
                "restart_h":              args.restart_h,
                "max_depth_ea":           args.max_depth_ea,
                "max_mutations_per_iter": args.max_mutations_per_iter,
                "enable_validation":      args.enable_validation,
                "enable_perplexity":      getattr(args, "enable_perplexity", False),
                "enable_eval_cache":     not args.no_eval_cache,
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

        print(f"   • run_config.json saved → reproduce with:")
        print(f"       python scripts/experiments/rerun_from_config.py {args.output_dir}")

    print("\n✅ Per-prompt-rules experiment complete!")
    return 0


if __name__ == "__main__":
    sys.exit(main())
