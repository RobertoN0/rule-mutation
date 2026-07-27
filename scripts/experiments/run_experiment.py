#!/usr/bin/env python3
# ruff: noqa: E402  # imports intentionally follow runtime path and optional-dependency setup
"""
Main experiment runner: rule-set search (EA / random search) over a retrieval map.

Prompts come exclusively from a retrieval map. Origin-baseline Semgrep scores
are computed live before the search candidates. Final matched runs may restore
their shared five-candidate initialization from a strictly keyed bundle.
Direction is repair by default (``--objective-direction minimize``): positive
f1 means fewer findings than the origin baseline.

Usage:
    # Smoke: 5 cases, mock backend, no API calls
    python scripts/experiments/run_experiment.py \
        --n-cases 5 --dry-run

    # Local API smoke (Claude backend; needs ANTHROPIC_API_KEY in .env)
    python scripts/experiments/run_experiment.py \
        --backend claude --n-cases 10 --main-loop-budget 15 \
        --languages python --mutators verb_weakening synonym_replacement \
        --enable-validation

    # Full run shape (DelftBlue submits this via scripts/slurm/slurm_ea_qwen32b.sh)
    python scripts/experiments/run_experiment.py \
        --rules-map rule_maps/qualified/final_search_map_qwen_python.json \
        --model Qwen/Qwen2.5-Coder-32B-Instruct \
        --optimizer ea --main-loop-budget 100000 --enable-validation
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import os
import re
import subprocess
import sys
import warnings
from pathlib import Path

# Silence a harmless SyntaxWarning emitted while importing nlpaug.  NLTK data
# is deliberately *not* downloaded here: DelftBlue compute nodes are offline,
# and a failed implicit download must not degrade a mutator into a silent no-op.
warnings.filterwarnings(
    "ignore",
    category=SyntaxWarning,
    module=r"nlpaug.*",
)


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
from src.optimizer.engine import EvaluationInfrastructureError
from src.evaluation.output_validation import BaselineOutputError
from src.evaluation.generation_contract import (
    MAX_OUTPUT_TOKENS,
    prompt_contract_sha256,
)
from src.evaluation.population_screening import FINAL_SEARCH_POPULATION_POLICY
from src.evaluation import (
    load_rule_mapping,
    create_rule_loader,
    RuleLoader,
    PromptWithRules,
)
from src.evaluation.semgrep_runner import (
    configure_semgrep,
    configure_semgrep_debug,
    get_semgrep_config,
)


# ═══════════════════════════════════════════════════════════════════════════════
# CONFIGURATION
# ═══════════════════════════════════════════════════════════════════════════════

# Default paths (relative to project root)
DEFAULT_RULES_MAP = (
    PROJECT_ROOT / "rule_maps" / "qualified" / "final_search_map_qwen.json"
)


def _provenance_path(path: str | Path) -> str:
    """Record repository files portably while preserving external locations."""
    resolved = Path(path).resolve()
    try:
        return resolved.relative_to(PROJECT_ROOT.resolve()).as_posix()
    except ValueError:
        return str(resolved)


def _git_commit_sha() -> str | None:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=PROJECT_ROOT,
            stderr=subprocess.DEVNULL,
        ).decode().strip()
    except (OSError, subprocess.CalledProcessError):
        return None


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
    parser.add_argument(
        "--allow-unqualified-map",
        action="store_true",
        help=(
            "Bypass the final-population metadata check for a deliberate "
            "plumbing diagnostic. Such a run is ineligible for final analysis."
        ),
    )
    # ----- search budget + direction ------------------------------------------
    parser.add_argument(
        "--main-loop-budget", "-i",
        type=int,
        default=5,
        help=(
            "Candidate evaluations after the shared five-candidate "
            "initialization (default: 5; total evaluations = 5 + this value). "
            "Identity/no-op proposals do not consume an evaluation. Set this "
            "ceiling high for time-bounded SLURM runs."
        ),
    )
    parser.add_argument(
        "--initialization-bundle",
        type=Path,
        default=None,
        help=(
            "Reuse a strictly keyed bundle containing the shared five evaluated "
            "initial candidates. The run is rejected if any provenance or "
            "population field differs."
        ),
    )
    parser.add_argument(
        "--wall-time-budget-seconds",
        type=int,
        default=(
            int(os.environ["TIME_BUDGET_SECONDS"])
            if os.getenv("TIME_BUDGET_SECONDS")
            else None
        ),
        help=(
            "Declared scheduler allocation used for the primary time-budget "
            "comparison. Matched final runs must use the same approved value."
        ),
    )
    parser.add_argument(
        "--pretimeout-lead-seconds",
        type=int,
        default=int(os.getenv("PRETIMEOUT_LEAD_SECONDS", "300")),
        help="Seconds before scheduler termination at which SIGUSR1 is delivered.",
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
            "ea = archive-based EA over full rule-set chromosomes, with five "
            "shared random initial candidates and periodic random injection; "
            "random_search = i.i.d. random sampler (independent chromosome per "
            "evaluation, best-of-budget, no archive)."
        ),
    )
    parser.add_argument(
        "--archive-cap",
        type=int,
        default=6,
        help="EA only: max Pareto archive size (default: 6, sweep-tunable).",
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
        "--ea-injection-every",
        type=int,
        default=10,
        help=(
            "EA: every N-th main-loop evaluation injects one origin-based "
            "random chromosome instead of a parent-based move (diversity "
            "maintenance; default: 10; 0 = off)."
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
    if args.main_loop_budget < 0:
        parser.error("--main-loop-budget must be >= 0")
    if (
        args.wall_time_budget_seconds is not None
        and args.wall_time_budget_seconds < 1
    ):
        parser.error("--wall-time-budget-seconds must be >= 1")
    if args.pretimeout_lead_seconds < 1:
        parser.error("--pretimeout-lead-seconds must be >= 1")
    if args.archive_cap < 1:
        parser.error("--archive-cap must be >= 1")
    if args.max_depth < 1:
        parser.error("--max-depth must be >= 1")
    if args.random_max_changes < 1:
        parser.error("--random-max-changes must be >= 1")
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

    The returned predicate carries `.received_at` (a `time.monotonic()` reading,
    or `None`) so the caller can report how long the graceful shutdown took —
    that measurement is what sizes `--signal=B:USR1@<lead>`.
    """
    import signal
    import time
    stop_requested = {"flag": False, "at": None}

    def _on_sigusr1(_signum, _frame):
        if not stop_requested["flag"]:
            stop_requested["at"] = time.monotonic()
            stop_requested["flag"] = True
            print("\n⏱️  SIGUSR1 received (SLURM pre-timeout) — aborting the in-flight "
                  "iteration and saving final results from the last completed one.",
                  flush=True)

    try:
        signal.signal(signal.SIGUSR1, _on_sigusr1)
    except (ValueError, OSError):
        pass  # not on main thread / unsupported platform — degrade silently

    def should_stop() -> bool:
        return stop_requested["flag"]

    should_stop.received_at = lambda: stop_requested["at"]
    return should_stop


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
    Baseline Semgrep scores are computed live at iteration 0 by the engine.
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
                "prompt_hash": m.prompt_hash,
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
            max_tokens=MAX_OUTPUT_TOKENS,
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
            max_tokens=MAX_OUTPUT_TOKENS,
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
        max_tokens=MAX_OUTPUT_TOKENS,
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
    pool = create_mutator_pool(
        args.mutators,
        seed=args.seed,
        backend=backend_for_mutator,
    )
    # Fail before the first search iteration if an optional mutator dependency
    # is unavailable.  This is especially important on offline cluster nodes:
    # nlpaug otherwise tries an implicit NLTK download, and a missing resource
    # can become an identity mutation instead of an explicit setup failure.
    for mutator in pool.mutators:
        preflight = getattr(mutator, "validate_runtime_dependencies", None)
        if preflight is not None:
            try:
                preflight()
            except (ImportError, RuntimeError) as exc:
                print(f"\n❌ Mutator preflight failed for '{mutator.name}': {exc}")
                sys.exit(1)
    return pool


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
        main_loop_budget=args.main_loop_budget,
        save_intermediate=True,
        output_dir=args.output_dir,
        verbose=True,
        enable_validation=args.enable_validation,
        enable_eval_cache=not args.no_eval_cache,
        optimizer=args.optimizer,
        archive_cap=args.archive_cap,
        max_depth=args.max_depth,
        random_max_changes=args.random_max_changes,
        ea_injection_every=args.ea_injection_every,
        order_move_weight=args.order_move_weight,
        objective_direction=args.objective_direction,
        initialization_bundle=args.initialization_bundle,
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
    print(
        f"   Evaluation budget: 5 initialization + "
        f"{config.main_loop_budget} main-loop = {5 + config.main_loop_budget} total"
    )
    print(f"   Direction: {args.objective_direction} "
          f"({'repair — positive f1 = fewer vulns' if args.objective_direction == 'minimize' else 'adversarial'})")
    print(f"   Prompt contract: {prompt_contract_sha256()}")
    if args.optimizer == "ea":
        print(f"   Optimizer: ea (single local move, "
              f"init=5, inject_every={args.ea_injection_every}, "
              f"archive_cap={args.archive_cap}, "
              f"max_depth={args.max_depth}, "
              f"order_w={args.order_move_weight})")
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
    print(f"Evaluations completed: {len(result.iterations)}")
    print(f"Total time: {result.total_time_seconds:.1f}s")
    print(f"Initialization time: {result.initialization_time_seconds:.1f}s")
    print(f"Main-loop time: {result.main_loop_time_seconds:.1f}s")
    print(f"LLM calls: {result.total_llm_calls}")
    print(
        f"Tokens: {result.total_input_tokens:,} in + "
        f"{result.total_output_tokens:,} out = "
        f"{result.total_input_tokens + result.total_output_tokens:,}"
    )
    print()
    print("Baseline:")
    print(f"  - Vulnerable prompts: {result.original_fitness.num_vulnerable}/{result.original_fitness.num_prompts}")
    print(
        "  - Raw vulnerabilities (primary): "
        f"{result.original_fitness.total_raw_count}"
    )
    print(f"  - Severity-weighted score (diagnostic): {result.original_fitness.total_weighted_score:.1f}")
    print()
    print("Best evaluated repair (origin is the floor):")
    print(f"  - Vulnerable prompts: {result.best_fitness.num_vulnerable}/{result.best_fitness.num_prompts}")
    print(
        "  - Raw vulnerabilities (primary): "
        f"{result.best_fitness.total_raw_count}"
    )
    print(f"  - Severity-weighted score (diagnostic): {result.best_fitness.total_weighted_score:.1f}")
    print(
        f"  - Invalid prompts (baseline-imputed): {result.best_fitness.num_invalid_prompts} "
        f"{result.best_fitness.failure_counts}"
    )
    print(
        "  - Raw finding reduction (primary f1): "
        f"{result.original_fitness.total_raw_count - result.best_fitness.total_raw_count:+d}"
    )
    print(
        "  - Weighted-score reduction (diagnostic): "
        f"{result.original_fitness.total_weighted_score - result.best_fitness.total_weighted_score:+.1f}"
    )


def _rule_corpus_sha256(prompts_with_rules: list[PromptWithRules]) -> str:
    originals: dict[str, str] = {}
    for prompt in prompts_with_rules:
        for rule_id, text in prompt.individual_rules.items():
            prior = originals.setdefault(rule_id, text)
            if prior != text:
                raise ValueError(f"inconsistent original text for rule {rule_id}")
    payload = json.dumps(
        sorted(originals.items()),
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _evaluation_population_fingerprint(
    prompts_with_rules: list[PromptWithRules],
) -> str:
    identity = [
        {
            "test_case_id": str(
                prompt.metadata.get("test_case_id", f"case_{index}")
            ),
            "analysis_language": prompt.language,
            "prompt_hash": prompt.metadata.get("prompt_hash")
            or hashlib.sha256(prompt.prompt.encode("utf-8")).hexdigest(),
        }
        for index, prompt in enumerate(prompts_with_rules)
    ]
    encoded = json.dumps(
        identity,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _model_revision(args: argparse.Namespace) -> str | None:
    if args.dry_run or args.backend != "delftblue":
        return None
    from transformers import AutoConfig

    config = AutoConfig.from_pretrained(
        args.model,
        local_files_only=True,
        trust_remote_code=True,
    )
    revision = getattr(config, "_commit_hash", None)
    if re.fullmatch(r"[0-9a-fA-F]{40}", str(revision or "")) is None:
        raise ValueError(
            f"could not resolve an exact cached model revision for {args.model}"
        )
    return str(revision)


def save_run_config(
    args: argparse.Namespace,
    semgrep_config: dict,
    timestamp: str,
    *,
    prompts_with_rules: list[PromptWithRules],
) -> dict:
    """Write run_config.json — every CLI arg + provenance, the rerun contract."""
    git_commit_sha = _git_commit_sha()
    map_payload = json.loads(args.rules_map.read_text(encoding="utf-8"))
    map_qualification = map_payload.get("metadata", {}).get("search_qualification")
    bundle_content_sha256 = None
    if args.initialization_bundle is not None:
        bundle_manifest = (
            args.initialization_bundle / "initialization_bundle.json"
            if args.initialization_bundle.is_dir()
            else args.initialization_bundle
        )
        bundle_content_sha256 = json.loads(
            bundle_manifest.read_text(encoding="utf-8")
        ).get("content_sha256")
    n_prompts_evaluated = len(prompts_with_rules)
    run_config = {
        "artifact_type": "search_run_config",
        "argv": sys.argv,
        "args": {
            "backend":                args.backend,
            "dry_run":                args.dry_run,
            "model":                  args.model,
            "model_revision":         _model_revision(args),
            "torch_version":          importlib.metadata.version("torch"),
            "transformers_version":   importlib.metadata.version("transformers"),
            "quantization":           args.quantization,
            "bnb_compute_dtype":      args.bnb_compute_dtype,
            "temperature":            args.temperature,
            "prompt_contract_sha256": prompt_contract_sha256(),
            "run_mode":               "search",
            "allow_unqualified_map":  args.allow_unqualified_map,
            "rules_map":              _provenance_path(args.rules_map),
            "rules_map_sha256":       hashlib.sha256(args.rules_map.read_bytes()).hexdigest(),
            "population_fingerprint": (
                map_qualification.get("qualified_population_fingerprint")
                if isinstance(map_qualification, dict) else None
            ),
            "population_policy": (
                map_qualification.get("policy")
                if isinstance(map_qualification, dict) else None
            ),
            "population_evidence_status": (
                map_qualification.get("evidence_status")
                if isinstance(map_qualification, dict) else None
            ),
            "n_cases":                n_prompts_evaluated,
            "evaluation_population_fingerprint": (
                _evaluation_population_fingerprint(prompts_with_rules)
            ),
            "rule_corpus_sha256":      _rule_corpus_sha256(prompts_with_rules),
            "n_cases_requested":      args.n_cases,
            "initialization_evaluations": 5,
            "main_loop_budget":       args.main_loop_budget,
            "total_evaluation_budget": 5 + args.main_loop_budget,
            "wall_time_budget_seconds": args.wall_time_budget_seconds,
            "pretimeout_lead_seconds": args.pretimeout_lead_seconds,
            "seed":                   args.seed,
            "selection":              args.selection,
            "languages":              args.languages,
            "mutators":               args.mutators,
            "optimizer":              args.optimizer,
            "objective_direction":    args.objective_direction,
            "fitness_strategy":       "raw_count",
            "max_output_tokens":      MAX_OUTPUT_TOKENS,
            "archive_cap":            args.archive_cap,
            "max_depth":              args.max_depth,
            "random_max_changes":     args.random_max_changes,
            "ea_injection_every":     args.ea_injection_every,
            "order_move_weight":      args.order_move_weight,
            "enable_validation":      args.enable_validation,
            "enable_perplexity":      args.enable_perplexity,
            "enable_eval_cache":      not args.no_eval_cache,
            "semgrep_config":         str(semgrep_config["rule_config"]),
            "semgrep_timeout_seconds": semgrep_config["subprocess_timeout_seconds"],
            "semgrep_jobs":           semgrep_config["jobs"],
            "semgrep_version":        semgrep_config["semgrep_version"],
            "semgrep_rule_config_kind": semgrep_config["rule_config_kind"],
            "semgrep_rules_sha256":   semgrep_config["rule_config_sha256"],
            "semgrep_rule_file_count": semgrep_config["rule_file_count"],
            "semgrep_rules_source_commit": semgrep_config["rule_source_commit"],
            "output_dir":             str(args.output_dir),
            "initialization_bundle": (
                str(args.initialization_bundle.resolve())
                if args.initialization_bundle is not None else None
            ),
            "initialization_bundle_content_sha256": bundle_content_sha256,
        },
        "timestamp": timestamp,
        "git_commit_sha": git_commit_sha,
        "slurm_job_id": os.getenv("SLURM_JOB_ID"),
        "hostname": os.getenv("HOSTNAME") or __import__("socket").gethostname(),
    }
    config_file = args.output_dir / "run_config.json"
    with open(config_file, "w") as f:
        json.dump(run_config, f, indent=2)

    print("   • run_config.json saved → reproduce with:")
    print(f"       python scripts/experiments/rerun_from_config.py {args.output_dir}")
    return run_config


# ═══════════════════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════════════════

def main():
    args = parse_args()

    if not args.dry_run and re.fullmatch(
        r"[0-9a-fA-F]{40}", str(_git_commit_sha() or "")
    ) is None:
        print("❌ Error: real search cannot resolve an exact Git commit SHA")
        return 1

    seed_everything(args.seed)
    setup_run_logging(args.output_dir)

    print("=" * 70)
    print("🚀 SBST: Rule-Set Search with Per-Prompt Rule Mapping")
    print("=" * 70)

    should_stop = install_pretimeout_handler()

    if not args.rules_map.exists():
        print(f"❌ Error: Rules map file not found: {args.rules_map}")
        sys.exit(1)

    map_payload = json.loads(args.rules_map.read_text(encoding="utf-8"))
    map_qualification = map_payload.get("metadata", {}).get("search_qualification")
    frozen_policy = (
        map_qualification.get("policy") if isinstance(map_qualification, dict) else None
    )
    evidence_status = (
        map_qualification.get("evidence_status")
        if isinstance(map_qualification, dict) else None
    )
    if (
        not args.dry_run
        and not args.allow_unqualified_map
        and (
            frozen_policy != FINAL_SEARCH_POPULATION_POLICY
            or evidence_status != "final"
        )
    ):
        print(
            "❌ Error: final search requires a map whose metadata records the "
            "observed-finding and cross-model temperature-zero-valid population. "
            "Use a map under rule_maps/qualified/, or pass "
            "--allow-unqualified-map only for a diagnostic that will not be "
            "used as final evidence."
        )
        sys.exit(1)
    qualified_prompt_contract = (
        map_qualification.get("prompt_contract_sha256")
        if isinstance(map_qualification, dict)
        else None
    )
    if (
        not args.dry_run
        and not args.allow_unqualified_map
        and qualified_prompt_contract != prompt_contract_sha256()
    ):
        print(
            "❌ Error: the selected map was not qualified with the active "
            "code-generation prompt contract."
        )
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

    config = build_search_config(args)
    print_config_summary(args, config, len(prompts_with_rules))
    semgrep_config = configure_semgrep_from_args(args)
    if not args.dry_run:
        if semgrep_config.get("rule_config_kind") != "local":
            print("❌ Error: real search requires a pinned local Semgrep ruleset")
            return 1
        if re.fullmatch(
            r"[0-9a-fA-F]{40}", str(semgrep_config.get("rule_source_commit") or "")
        ) is None:
            print("❌ Error: local Semgrep rules must contain a 40-hex SOURCE_COMMIT")
            return 1
        if semgrep_config.get("semgrep_version") != "1.85.0":
            print(
                "❌ Error: comparative runs require Semgrep 1.85.0; found "
                f"{semgrep_config.get('semgrep_version')}"
            )
            return 1
    if args.output_dir:
        args.output_dir.mkdir(parents=True, exist_ok=True)
        from datetime import datetime
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        # Write provenance before the first model/scanner call so failed
        # preflights and infrastructure aborts remain attributable.
        run_config = save_run_config(
            args,
            semgrep_config,
            timestamp,
            prompts_with_rules=prompts_with_rules,
        )
        from src.optimizer.initialization import (
            build_initialization_identity,
            load_initialization_bundle,
        )

        config.initialization_identity = build_initialization_identity(run_config)
        if args.initialization_bundle is not None:
            try:
                bundle = load_initialization_bundle(
                    args.initialization_bundle,
                    expected_identity=config.initialization_identity,
                )
            except (OSError, ValueError, json.JSONDecodeError) as exc:
                print(f"❌ Error: initialization bundle rejected: {exc}")
                return 1
            if (
                run_config["args"]["initialization_bundle_content_sha256"]
                != bundle.content_sha256
            ):
                print("❌ Error: initialization bundle changed while configuring the run")
                return 1

    # Run configuration is durable before model loading, NLTK/SBERT preflight,
    # or the first generation/scanner call. Infrastructure failures therefore
    # remain attributable instead of leaving an anonymous partial directory.
    backend = create_backend(args)
    pool = create_pool(args, backend)
    validator = create_validator(args, backend)
    climber = ExperimentEngine(backend, pool, config, validator=validator)

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
    except BaselineOutputError as e:
        print(f"\n❌ Baseline preflight failed; search was not started:\n{e}")
        sys.exit(1)
    except EvaluationInfrastructureError as e:
        print(f"\n❌ Evaluation infrastructure failure; score was not trusted: {e}")
        sys.exit(1)
    except KeyboardInterrupt:
        print("\n\n⚠️  Interrupted by user")
        sys.exit(130)

    print_results_summary(result, len(prompts_with_rules))

    # Graceful-shutdown cost. Everything after the signal is dead allocation, so
    # this number is what `--signal=B:USR1@<lead>` has to cover on the Python
    # side; the SLURM wrapper reports its own post-run stages separately.
    received_at = getattr(should_stop, "received_at", lambda: None)()
    if received_at is not None:
        import time as _time
        print(f"⏱️  PRETIMEOUT_FINALIZE_SECONDS(python)="
              f"{_time.monotonic() - received_at:.1f}", flush=True)

    print("\n✅ Experiment complete!")
    return 0


if __name__ == "__main__":
    sys.exit(main())
