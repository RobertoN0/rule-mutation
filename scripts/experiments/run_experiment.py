#!/usr/bin/env python3
# ruff: noqa: E402  # imports intentionally follow runtime path and optional-dependency setup
"""
Main experiment runner: rule-set search (EA / random search) over a retrieval map.

Prompts come exclusively from a retrieval map (retrieval_map_*.json / rule_maps/).
Baseline Semgrep scores are computed live at iteration 0 — no pre-computed
values are loaded. Direction: REPAIR by default (--objective-direction minimize;
positive f1 = fewer vulnerabilities than baseline).

Usage:
    # Smoke: 5 cases, mock backend, no API calls
    python scripts/experiments/run_experiment.py --n-cases 5 --dry-run

    # Local API smoke (Claude backend; needs ANTHROPIC_API_KEY in .env)
    python scripts/experiments/run_experiment.py \
        --backend claude --n-cases 10 --iterations 15 \
        --languages python --mutators verb_weakening synonym_replacement \
        --enable-validation

    # Full run shape (DelftBlue submits this via scripts/slurm/slurm_ea_qwen32b.sh)
    python scripts/experiments/run_experiment.py \
        --rules-map rule_maps/final_consensus_map_qwen.json \
        --model Qwen/Qwen2.5-Coder-32B-Instruct \
        --optimizer ea --iterations 200 --enable-validation
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
    MutationQualityValidator,
    create_mutator_pool,
)
from src.optimizer import ExperimentEngine, SearchConfig
from src.evaluation import (
    load_rule_mapping,
    create_rule_loader,
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

# Output schema version written to run_config.json. rerun_from_config and the
# analysis layer key off it; bump it whenever the run_config arg set or the
# iterations.jsonl record shape changes.
SCHEMA_VERSION = 4

# Default paths (relative to project root)
DEFAULT_RULES_MAP = (
    PROJECT_ROOT / "rule_maps" / "final_consensus_map_qwen.json"
)
RULES_DIR = PROJECT_ROOT / "project-codeguard" / "skills" / "software-security" / "rules"

# Mutators that issue LLM calls (need a real backend, and cost money on APIs).
LLM_MUTATORS = {"negation_injection", "voice_change", "paraphrase"}
LLM_BACKENDS = {"delftblue", "claude", "openai"}

BACKEND_DEFAULT_MODELS = {
    "claude":    "claude-haiku-4-5",
    "openai":    "gpt-4o-mini",
    "delftblue": "Qwen/Qwen2.5-Coder-32B-Instruct",
}


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


# ═══════════════════════════════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════════════════════════════

def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the rule-set search (EA / random search) with a per-prompt rule mapping"
    )
    # ----- input / case selection --------------------------------------------
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
    # ----- search budget + direction ------------------------------------------
    parser.add_argument(
        "--iterations", "-i",
        type=int,
        default=5,
        help="Candidate-evaluation budget (default: 5). Identity/no-op proposals "
             "are logged and retried without advancing the index; EA "
             "init/injection evaluations count against this budget too. "
             "Upper-bound cap: set high for time-bounded "
             "SLURM runs and let the wall-time signal (SIGUSR1) stop the run."
    )
    parser.add_argument(
        "--objective-direction",
        choices=["minimize", "maximize"],
        default="minimize",
        help="f1 optimization direction. 'minimize' (default) = REPAIR: reward "
             "fewer vulnerabilities than baseline (positive recorded f1 ⇒ the "
             "mutation reduced vulns). 'maximize' = the adversarial direction, "
             "kept for secondary experiments only.",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=42,
        help="Random seed for reproducibility"
    )
    # ----- LLM backend ---------------------------------------------------------
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
        help="Test pipeline without API calls (mock backend)"
    )
    # ----- mutation operators --------------------------------------------------
    parser.add_argument(
        "--mutators",
        nargs="+",
        default=["synonym_replacement"],
        help=(
            "Space-separated list of mutation operators (default: synonym_replacement). "
            "LLM-based mutators (negation_injection, voice_change, paraphrase) "
            "require a real LLM backend (delftblue/claude/openai)."
        ),
    )
    # ----- optimizer -----------------------------------------------------------
    parser.add_argument(
        "--optimizer",
        default="ea",
        choices=["ea", "random_search"],
        help=(
            "Optimizer family (default: ea). "
            "ea = (1+1) EA over a full-chromosome Pareto archive, with random "
            "initialization + periodic random injection; "
            "random_search = i.i.d. random sampler (independent chromosome per "
            "iteration, best-of-budget, no archive)."
        ),
    )
    parser.add_argument(
        "--archive-cap",
        type=int,
        default=6,
        help="EA only: max Pareto archive size (default: 6, sweep-tunable).",
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
        "--max-depth",
        type=int,
        default=4,
        help=(
            "Per-rule stacked-mutation depth cap, enforced in both arms and "
            "inside the random sampler (default: 4)."
        ),
    )
    parser.add_argument(
        "--random-max-changes",
        type=int,
        default=10,
        help=(
            "K for the shared random sampler: each random chromosome stacks "
            "n ∈ [1, K] changes on a copy of its base (default: 10 — the "
            "supervisor's pseudocode). Used by random_search and by the EA's "
            "init/injection phases."
        ),
    )
    parser.add_argument(
        "--ea-n-mutations",
        type=int,
        default=1,
        help=(
            "EA local move: max mutators stacked on the chosen gene per move "
            "(default: 1 = the canonical (1+1) small step; >1 samples a 1..n "
            "chain — ablation knob)."
        ),
    )
    parser.add_argument(
        "--ea-init-samples",
        type=int,
        default=10,
        help=(
            "EA: number of initial iterations that sample independent random "
            "chromosomes from the origin and offer them to the archive "
            "(population-style seeding; default: 10)."
        ),
    )
    parser.add_argument(
        "--ea-injection-every",
        type=int,
        default=10,
        help=(
            "EA: after init, every N-th iteration injects one origin-based "
            "random chromosome instead of a parent-based move (diversity "
            "maintenance; default: 10; 0 = off)."
        ),
    )
    parser.add_argument(
        "--ea-move",
        default="local",
        choices=["local", "random_builder"],
        help=(
            "EA move for post-init iterations: 'local' (default) mutates ONE "
            "gene of the parent; 'random_builder' applies the random sampler "
            "to the archive parent (selection-only ablation)."
        ),
    )
    parser.add_argument(
        "--order-move-weight",
        type=float,
        default=0.1,
        help=(
            "Probability of a rule-order move: per EA local move AND per change "
            "inside the random sampler, so both arms share one operator pool "
            "(default: 0.1)."
        ),
    )
    parser.add_argument(
        "--ea-origin-parent",
        action=argparse.BooleanOptionalAction,
        default=True,
        help=(
            "EA only: whether the origin is a sampleable parent for local moves "
            "(default: on). On seeds minimal parsimony-1 single-rule lineages any "
            "time; --no-ea-origin-parent restricts local moves to front members "
            "(the origin still anchors dominance and best())."
        ),
    )
    # ----- validation -----------------------------------------------------------
    parser.add_argument(
        "--enable-validation",
        action="store_true",
        help=(
            "Enable in-loop mutation quality validation (SBERT semantic "
            "similarity + structural criteria). Observational — never gates "
            "acceptance — but REQUIRED for real runs: the f2 rule-fidelity "
            "objective is the validator's SBERT similarity."
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
    # ----- evaluation / Semgrep -------------------------------------------------
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

    args = parser.parse_args(argv)

    # The f2 rule-fidelity objective is computed by the validator's SBERT model;
    # without it f2 degenerates to a constant 1.0. Only mock smokes may skip it.
    if not args.dry_run and not args.enable_validation:
        parser.error(
            "--enable-validation is required for real runs: the f2 rule-fidelity "
            "objective is SBERT-based. Only --dry-run (mock backend) may omit it."
        )
    if args.iterations < 0:
        parser.error("--iterations must be >= 0")
    if args.archive_cap < 1:
        parser.error("--archive-cap must be >= 1")
    if args.restart_h < 1:
        parser.error("--restart-h must be >= 1")
    if args.max_depth < 1:
        parser.error("--max-depth must be >= 1")
    if args.random_max_changes < 1:
        parser.error("--random-max-changes must be >= 1")
    if args.ea_n_mutations < 1:
        parser.error("--ea-n-mutations must be >= 1")
    if args.ea_init_samples < 0:
        parser.error("--ea-init-samples must be >= 0")
    if args.ea_injection_every < 0:
        parser.error("--ea-injection-every must be >= 0")
    if not 0.0 <= args.order_move_weight <= 1.0:
        parser.error("--order-move-weight must be between 0 and 1")

    if args.model is None:
        args.model = BACKEND_DEFAULT_MODELS[args.backend]

    return args


# ═══════════════════════════════════════════════════════════════════════════════
# SETUP HELPERS (each owns one concern; main() only orchestrates)
# ═══════════════════════════════════════════════════════════════════════════════

def setup_run_logging(output_dir: Path | None) -> None:
    """Tee stdout/stderr into <output_dir>/run.log for a persistent local log."""
    if output_dir is None:
        return
    output_dir.mkdir(parents=True, exist_ok=True)
    log_path = output_dir / "run.log"
    log_fh = open(log_path, "w", buffering=1)  # line-buffered
    orig_stdout, orig_stderr = sys.stdout, sys.stderr
    sys.stdout = _TeeStream(orig_stdout, log_fh)
    sys.stderr = _TeeStream(orig_stderr, log_fh)
    import atexit

    def _restore_streams():
        sys.stdout = orig_stdout
        sys.stderr = orig_stderr
        try:
            log_fh.close()
        except Exception:
            pass

    atexit.register(_restore_streams)
    print(f"📝 Logging stdout+stderr to {log_path}")


def install_pretimeout_handler():
    """SIGUSR1 → graceful-stop flag (SLURM --signal=B:USR1@<lead>).

    The optimizer checks the returned predicate at controlled checkpoints and
    breaks cleanly, so the run still writes its final archive snapshot, summary,
    and run_config.json instead of being killed mid-iteration.
    """
    import signal
    stop_requested = {"flag": False}

    def _on_sigusr1(_signum, _frame):
        if not stop_requested["flag"]:
            stop_requested["flag"] = True
            print("\n⏱️  SIGUSR1 received (SLURM pre-timeout) — aborting the in-flight "
                  "iteration and saving final results from the last completed one.",
                  flush=True)

    try:
        signal.signal(signal.SIGUSR1, _on_sigusr1)
    except (ValueError, OSError):
        pass  # not on main thread / unsupported platform — degrade silently
    return lambda: stop_requested["flag"]


def seed_everything(seed: int) -> None:
    """Seed transformers (covers torch/np/random) or fall back to stdlib random."""
    try:
        from transformers import set_seed
        set_seed(seed)
    except Exception as err:  # transformers absent (non-GPU env) → best effort
        import random
        random.seed(seed)
        print(f"⚠️  transformers.set_seed unavailable ({err}); seeded stdlib random only")


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
    live at iteration 0 by the engine.
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


def create_backend(args: argparse.Namespace):
    """Create the code-generation LLM backend selected by --backend/--dry-run.

    Exits with a readable error when the backend's requirements (extras, API
    keys, model cache) are not met.
    """
    if args.dry_run:
        print("\n🔧 DRY RUN MODE: Using mock backend")
        return create_mock_backend()

    if args.backend == "delftblue":
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
                return backend
            print("   ⚠️  Model not found in local cache or CUDA unavailable")
            print("   Hint: Set HF_HOME and TRANSFORMERS_CACHE to your model directory")
            sys.exit(1)
        except LLMError as e:
            print(f"❌ Error initializing local backend: {e}")
            sys.exit(1)

    if args.backend == "claude":
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
            return backend
        except LLMError as e:
            print(f"❌ Error initializing Claude backend: {e}")
            sys.exit(1)

    # args.backend == "openai" (argparse choices guarantee it)
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
        return backend
    except LLMError as e:
        print(f"❌ Error initializing OpenAI backend: {e}")
        sys.exit(1)


def create_pool(args: argparse.Namespace, backend):
    """Create the mutator pool; guard LLM-based mutators behind real backends."""
    has_llm_mutator = any(m in LLM_MUTATORS for m in args.mutators)

    if has_llm_mutator and args.backend not in LLM_BACKENDS:
        llm_names = [m for m in args.mutators if m in LLM_MUTATORS]
        print(
            f"\n❌ Error: LLM mutator(s) {llm_names} need a real LLM backend "
            f"(delftblue/claude/openai). Got --backend={args.backend}."
        )
        sys.exit(1)
    if has_llm_mutator and args.dry_run:
        llm_names = [m for m in args.mutators if m in LLM_MUTATORS]
        print(
            f"\n❌ Error: LLM mutator(s) {llm_names} cannot run under --dry-run "
            f"(mock backend)."
        )
        sys.exit(1)

    if has_llm_mutator and args.backend in ("claude", "openai"):
        llm_names = [m for m in args.mutators if m in LLM_MUTATORS]
        print(
            f"\n💸 NOTE: LLM mutator(s) {llm_names} share the code-gen backend "
            f"({args.backend}). They will issue ADDITIONAL paid API calls — "
            f"budget accordingly."
        )

    print(f"\n🧬 Initializing mutator pool: {args.mutators}")
    print(f"   Seed: {args.seed}")
    backend_for_mutator = backend if has_llm_mutator else None
    return create_mutator_pool(
        args.mutators,
        seed=args.seed,
        backend=backend_for_mutator,
    )


def create_validator(args: argparse.Namespace, backend) -> MutationQualityValidator | None:
    """Create the quality validator when enabled (SBERT + structural criteria)."""
    if not args.enable_validation:
        return None
    use_ppl = args.enable_perplexity and args.backend == "delftblue" and not args.dry_run
    ppl_model_handle = None
    ppl_tokenizer_handle = None
    if use_ppl:
        print("\n🔬 Setting up MutationQualityValidator (perplexity gate ON)")
        print("   Force-loading generation model for perplexity scoring …")
        ppl_model_handle = backend._load_model()  # type: ignore[attr-defined]
        ppl_tokenizer_handle = backend._load_tokenizer()  # type: ignore[attr-defined]
        print(f"   Generation model loaded: {type(ppl_model_handle).__name__}")
    else:
        print("\n🔬 Setting up MutationQualityValidator")
    print("   SBERT semantic similarity (all-mpnet-base-v2, threshold=0.75)")
    print("   Structural criteria: inline code retention + security keyword retention")
    if use_ppl:
        print("   Perplexity ratio (threshold=2.5, model=32B shared)")
    return MutationQualityValidator(
        use_sbert=True,
        use_perplexity=use_ppl,
        ppl_model_handle=ppl_model_handle,
        ppl_tokenizer_handle=ppl_tokenizer_handle,
    )


def build_search_config(args: argparse.Namespace) -> SearchConfig:
    """Map CLI args onto the search configuration."""
    return SearchConfig(
        max_iterations=args.iterations,
        save_intermediate=True,
        output_dir=args.output_dir,
        verbose=True,
        enable_validation=args.enable_validation,
        enable_eval_cache=not args.no_eval_cache,
        optimizer=args.optimizer,
        archive_cap=args.archive_cap,
        restart_h=args.restart_h,
        max_depth=args.max_depth,
        random_max_changes=args.random_max_changes,
        ea_n_mutations=args.ea_n_mutations,
        ea_init_samples=args.ea_init_samples,
        ea_injection_every=args.ea_injection_every,
        ea_move=args.ea_move,
        order_move_weight=args.order_move_weight,
        ea_origin_parent=args.ea_origin_parent,
        objective_direction=args.objective_direction,
    )


def configure_semgrep_from_args(args: argparse.Namespace) -> dict:
    """Configure Semgrep execution + debug capture; returns the active config."""
    configure_semgrep(
        rule_config=args.semgrep_config,
        subprocess_timeout_seconds=args.semgrep_timeout_seconds,
        jobs=args.semgrep_jobs,
    )
    semgrep_config = get_semgrep_config()
    semgrep_debug_dir = args.output_dir / "semgrep_debug"
    configure_semgrep_debug(semgrep_debug_dir)
    print(f"🔎 Semgrep config: {semgrep_config['rule_config']}")
    print(f"   Semgrep timeout: {semgrep_config['subprocess_timeout_seconds']}s")
    print(f"   Semgrep jobs: {semgrep_config['jobs']}")
    print(f"\U0001f50d Semgrep inputs/outputs → {semgrep_debug_dir}/semgrep_debug.jsonl", flush=True)
    return semgrep_config


def print_config_summary(args: argparse.Namespace, config: SearchConfig, n_prompts: int) -> None:
    print("\n⚙️  Search Configuration:")
    print(f"   Test cases: {n_prompts}")
    print(f"   Evaluation budget: {config.max_iterations}")
    print(f"   Direction: {args.objective_direction} "
          f"({'repair — positive f1 = fewer vulns' if args.objective_direction == 'minimize' else 'adversarial'})")
    if args.optimizer == "ea":
        print(f"   Optimizer: ea (move={args.ea_move}, chain≤{args.ea_n_mutations}, "
              f"init={args.ea_init_samples}, inject_every={args.ea_injection_every}, "
              f"archive_cap={args.archive_cap}, restart_h={args.restart_h}, "
              f"max_depth={args.max_depth}, "
              f"order_w={args.order_move_weight}, "
              f"origin_parent={args.ea_origin_parent})")
    else:
        print(f"   Optimizer: random_search (K={args.random_max_changes}, "
              f"max_depth={args.max_depth}, order_w={args.order_move_weight})")
    print(f"   Mutators: {args.mutators}")
    print(f"   Validation: {'enabled (SBERT + structural)' if args.enable_validation else 'disabled (mock smoke only)'}")
    print(f"   Eval cache: {'enabled' if config.enable_eval_cache else 'disabled'}")
    print(f"   Output dir: {args.output_dir}")


def print_results_summary(result, n_prompts: int) -> None:
    print("\n" + "=" * 70)
    print("📊 RESULTS SUMMARY")
    print("=" * 70)
    print(f"Test cases: {n_prompts}")
    print(f"Iterations run: {len(result.iterations)}")
    print(f"Total time: {result.total_time_seconds:.1f}s")
    print(f"LLM calls: {result.total_llm_calls}")
    print(
        f"Tokens: {result.total_input_tokens:,} in + "
        f"{result.total_output_tokens:,} out = "
        f"{result.total_input_tokens + result.total_output_tokens:,}"
    )
    print()
    orig_raw = sum(r.raw_count for r in result.original_fitness.individual_results)
    best_raw = sum(r.raw_count for r in result.best_fitness.individual_results)
    print(f"Original fitness: {result.original_fitness.total_fitness:.1f}")
    print(f"  - Vulnerable prompts: {result.original_fitness.num_vulnerable}/{result.original_fitness.num_prompts}")
    print(f"  - Raw vulnerabilities (total semgrep findings): {orig_raw}")
    print(f"  - Mean fitness: {result.original_fitness.mean_fitness:.2f}")
    print()
    print(f"Best fitness: {result.best_fitness.total_fitness:.1f}")
    print(f"  - Vulnerable prompts: {result.best_fitness.num_vulnerable}/{result.best_fitness.num_prompts}")
    print(f"  - Raw vulnerabilities (total semgrep findings): {best_raw}")
    print(f"  - Mean fitness: {result.best_fitness.mean_fitness:.2f}")
    print()
    print(f"Fitness increase: {result.fitness_increase:+.1f}")
    print(f"Improvement ratio: {result.improvement_ratio:.2f}x")


def save_run_config(args: argparse.Namespace, semgrep_config: dict, timestamp: str) -> None:
    """Write run_config.json — every CLI arg + provenance, the rerun contract."""
    import subprocess
    try:
        git_sha = subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=PROJECT_ROOT,
            stderr=subprocess.DEVNULL,
        ).decode().strip()
    except Exception:
        git_sha = None

    run_config = {
        "schema_version": SCHEMA_VERSION,
        "argv": sys.argv,
        "args": {
            "backend":                args.backend,
            "model":                  args.model,
            "quantization":           args.quantization,
            "bnb_compute_dtype":      args.bnb_compute_dtype,
            "temperature":            args.temperature,
            "rules_map":              str(args.rules_map),
            "n_cases":                args.n_cases,
            "iterations":             args.iterations,
            "seed":                   args.seed,
            "selection":              args.selection,
            "languages":              args.languages,
            "mutators":               args.mutators,
            "optimizer":              args.optimizer,
            "objective_direction":    args.objective_direction,
            "archive_cap":            args.archive_cap,
            "restart_h":              args.restart_h,
            "max_depth":              args.max_depth,
            "random_max_changes":     args.random_max_changes,
            "ea_n_mutations":         args.ea_n_mutations,
            "ea_init_samples":        args.ea_init_samples,
            "ea_injection_every":     args.ea_injection_every,
            "ea_move":                args.ea_move,
            "order_move_weight":      args.order_move_weight,
            "ea_origin_parent":       args.ea_origin_parent,
            "enable_validation":      args.enable_validation,
            "enable_perplexity":      args.enable_perplexity,
            "enable_eval_cache":      not args.no_eval_cache,
            "semgrep_config":         str(semgrep_config["rule_config"]),
            "semgrep_timeout_seconds": semgrep_config["subprocess_timeout_seconds"],
            "semgrep_jobs":           semgrep_config["jobs"],
            "output_dir":             str(args.output_dir),
        },
        "timestamp": timestamp,
        "git_sha": git_sha,
        "slurm_job_id": os.getenv("SLURM_JOB_ID"),
        "hostname": os.getenv("HOSTNAME") or __import__("socket").gethostname(),
    }
    config_file = args.output_dir / "run_config.json"
    with open(config_file, "w") as f:
        json.dump(run_config, f, indent=2)

    print("   • run_config.json saved → reproduce with:")
    print(f"       python scripts/experiments/rerun_from_config.py {args.output_dir}")


# ═══════════════════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════════════════

def main():
    args = parse_args()

    seed_everything(args.seed)
    setup_run_logging(args.output_dir)

    print("=" * 70)
    print("🚀 SBST: Rule-Set Search with Per-Prompt Rule Mapping")
    print("=" * 70)

    should_stop = install_pretimeout_handler()

    if not args.rules_map.exists():
        print(f"❌ Error: Rules map file not found: {args.rules_map}")
        sys.exit(1)

    rule_loader = create_rule_loader(RULES_DIR)
    print(f"📜 Rule loader initialized: {len(rule_loader.available_rules)} rules available")

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

    backend = create_backend(args)
    pool = create_pool(args, backend)
    validator = create_validator(args, backend)

    # Composite evaluator is always on — provides the per-prompt semgrep delta
    # (f1) and the CodeBLEU divergence diagnostics. reference_codes starts
    # empty; the engine populates it from iteration-0 output.
    eval_lang = args.languages[0] if args.languages and len(args.languages) == 1 else "python"
    composite_evaluator = CompositeFitnessEvaluator(reference_codes={}, lang=eval_lang)

    config = build_search_config(args)
    print_config_summary(args, config, len(prompts_with_rules))
    semgrep_config = configure_semgrep_from_args(args)

    climber = ExperimentEngine(backend, pool, config, validator=validator,
                          composite_evaluator=composite_evaluator)

    print("\n" + "=" * 70)
    print(f"🏔️  Starting {args.optimizer} search over per-prompt rule sets")
    print("=" * 70)

    try:
        result = climber.run_search(
            prompts_with_rules=prompts_with_rules,
            should_stop_fn=should_stop,
        )
    except LLMError as e:
        print(f"\n❌ LLM Error: {e}")
        sys.exit(1)
    except KeyboardInterrupt:
        print("\n\n⚠️  Interrupted by user")
        sys.exit(130)

    print_results_summary(result, len(prompts_with_rules))

    if args.output_dir:
        args.output_dir.mkdir(parents=True, exist_ok=True)
        from datetime import datetime
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        # The per-prompt trajectory (intermediate/), per-iteration records
        # (iterations.jsonl), archive snapshots, mutated rules, and the run
        # summary are all written during the run by the engine.
        save_run_config(args, semgrep_config, timestamp)

    print("\n✅ Experiment complete!")
    return 0


if __name__ == "__main__":
    sys.exit(main())
