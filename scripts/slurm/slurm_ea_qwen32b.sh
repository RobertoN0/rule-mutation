#!/bin/bash
#SBATCH --job-name="sbst_ea"
#SBATCH --account=education-eemcs-msc-cs
#SBATCH --partition=gpu-a100
#SBATCH --time=01:30:00
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=8
#SBATCH --gpus-per-task=1
#SBATCH --mem-per-cpu=8000M
#SBATCH --output=/home/rnegro/thesis/rule-mutation/logs/%j_%x.out
#SBATCH --error=/home/rnegro/thesis/rule-mutation/logs/%j_%x.err
# Graceful pre-timeout: deliver SIGUSR1 to the batch shell (B:) 300s before the
# wall-time SIGKILL so the run can save final results. Override per-job for
# long-iteration (full-population) runs, e.g.:  sbatch --signal=B:USR1@700 ...
#SBATCH --signal=B:USR1@300

#############################################################################
# SBST Experiment: (1+1) EA (random init + injection) OR i.i.d. random_search.
#
# Wall-time calibration (25 cases, fp16, gpu-a100):
#   ~2.7 min/iteration regardless of optimizer. Empirical baselines:
#   EA  python 200 iters → ~11-12h   EA  java 200 iters → ~9h
#   rand python 200 iters → ~9.5h    rand java 200 iters → ~9h
#   Validation adds SBERT + optional perplexity (same 32B model reused).
#   NOTE (2026-07-12 redesign): random_search mutates 1-10 rules per sample and
#   EA init/injection do the same, so per-iteration cache reuse is lower than
#   the old single-rule walk — budget conservatively until recalibrated.
#
# This file is the only mutation-run launcher: OPTIMIZER ∈ {ea, random_search}.
# Validation is ON by default — the f2 rule-fidelity objective needs SBERT.
#
# Usage:
#   # Default: (1+1) EA, 16 cases, 10 iterations, init=10, inject_every=10.
#   sbatch scripts/slurm/slurm_ea_qwen32b.sh
#
#   # Smoke test before the real run — 2 cases, 5 iters
#   N_CASES=2 N_ITERATIONS=5 \
#     sbatch --time=0:30:00 --job-name="ea_smoke" \
#            scripts/slurm/slurm_ea_qwen32b.sh
#
#   # Full EA — 200 iters python, shuffled prompt order (avoid saturated head)
#   N_CASES=185 N_ITERATIONS=200 LANGUAGES=python SELECTION=random \
#     sbatch --time=12:00:00 --job-name="ea_python_200" \
#            scripts/slurm/slurm_ea_qwen32b.sh
#
#   # Random-search baseline — python (same budget)
#   OPTIMIZER=random_search N_CASES=185 N_ITERATIONS=200 LANGUAGES=python SELECTION=random \
#     sbatch --time=12:00:00 --job-name="rand_python_200" \
#            scripts/slurm/slurm_ea_qwen32b.sh
#
#   # Selection-only ablation: EA whose move IS the random sampler
#   EA_MOVE=random_builder N_CASES=185 N_ITERATIONS=200 LANGUAGES=python SELECTION=random \
#     sbatch --time=12:00:00 --job-name="ea_rb_python_200" \
#            scripts/slurm/slurm_ea_qwen32b.sh
#
#   # Chain-length ablation (multi-mutation local moves)
#   EA_N_MUTATIONS=4 N_ITERATIONS=200 SELECTION=random \
#     sbatch --job-name="ea_chain4" scripts/slurm/slurm_ea_qwen32b.sh
#############################################################################

set -e

# ─────── Optimizer ───────────────────────────────────────────────────────────
OPTIMIZER=${OPTIMIZER:-ea}                # "ea" | "random_search"
ARCHIVE_CAP=${ARCHIVE_CAP:-6}             # Pareto archive size (EA)
RESTART_H=${RESTART_H:-8}                 # stagnation threshold (EA)
ARCHIVE_ADMISSION=${ARCHIVE_ADMISSION:-neutral_drift}  # neutral_drift | strict_repair
MAX_DEPTH=${MAX_DEPTH:-4}                 # per-rule stacked-mutation depth cap (both arms)
# K for the shared random sampler: each random chromosome stacks n∈[1,K] changes
# (supervisor pseudocode: random(1,10)). Used by random_search + EA init/injection.
RANDOM_MAX_CHANGES=${RANDOM_MAX_CHANGES:-10}
# EA local move: max mutators stacked on the chosen gene per move (1 = canonical
# (1+1) small step; >1 = chain ablation).
EA_N_MUTATIONS=${EA_N_MUTATIONS:-1}
# EA random initialization + periodic injection (2026-07-10 supervisor design).
EA_INIT_SAMPLES=${EA_INIT_SAMPLES:-10}    # initial random samples offered to the archive
EA_INJECTION_EVERY=${EA_INJECTION_EVERY:-10}  # inject a random sample every N EA iters (0=off)
# EA move: "local" (mutate ONE gene, main design) | "random_builder" (ablation).
EA_MOVE=${EA_MOVE:-local}
# Probability of a rule-order move (per EA local move AND per sampler change).
ORDER_MOVE_WEIGHT=${ORDER_MOVE_WEIGHT:-0.1}
# Origin as a sampleable EA parent: true = seed minimal parsimony-1 lineages
# any time (default); false = local moves only from front members (ablation).
EA_ORIGIN_PARENT=${EA_ORIGIN_PARENT:-true}

# ─────── Standard config ─────────────────────────────────────────────────────
N_CASES=${N_CASES:-16}
N_ITERATIONS=${N_ITERATIONS:-10}
QUANTIZATION=${QUANTIZATION:-fp16}
TEMPERATURE=${TEMPERATURE:-0.0}
SEED=${SEED:-42}
SELECTION=${SELECTION:-first}
LANGUAGES=${LANGUAGES:-}
SEMGREP_RULESET=${SEMGREP_RULESET:-/scratch/$USER/semgrep-rules/security-audit}
SEMGREP_TIMEOUT_SECONDS=${SEMGREP_TIMEOUT_SECONDS:-180}
SEMGREP_JOBS=${SEMGREP_JOBS:-4}
# Mutator pool: the full 8-mutator set. EA and random_search do their own
# constrained random selection over this pool (no pool-level strategy).
MUTATORS=${MUTATORS:-"synonym_replacement add_random_word verb_weakening negation_injection voice_change paraphrase section_reorder_shuffle section_reorder_degrade"}
# Validation default ON: the f2 rule-fidelity objective is SBERT-based and the
# entrypoint refuses real runs without it.
ENABLE_VALIDATION=${ENABLE_VALIDATION:-1}
ENABLE_PERPLEXITY=${ENABLE_PERPLEXITY:-0}
ENABLE_EVAL_CACHE=${ENABLE_EVAL_CACHE:-1}
# Optimization direction: "minimize" (REPAIR: fewer vulns, default) | "maximize".
OBJECTIVE_DIRECTION=${OBJECTIVE_DIRECTION:-minimize}
# Time-bounded runs: set N_ITERATIONS high and let the SBATCH --time + the
# pre-timeout signal (--signal=B:USR1@<lead>, header) stop the run by aborting the
# in-flight iteration and finalizing from the last completed one. No iteration budget.

MODEL_ID="Qwen/Qwen2.5-Coder-32B-Instruct"
RULES_MAP=${RULES_MAP:-"/home/rnegro/thesis/rule-mutation/rule_maps/map_qwen32b_python_java.json"}

# Validate OPTIMIZER value
if [ "$OPTIMIZER" != "ea" ] && [ "$OPTIMIZER" != "random_search" ]; then
    echo "❌ ERROR: OPTIMIZER must be 'ea' or 'random_search' (got: $OPTIMIZER)."
    exit 1
fi

echo "=========================================================================="
echo "SBST: (1+1) EA / random_search run with Qwen 32B"
echo "=========================================================================="
echo "Started: $(date)"
echo "Job ID: $SLURM_JOB_ID"
echo "Node: $(hostname)"
echo "Partition: $SLURM_JOB_PARTITION"
echo ""
echo "Optimizer configuration:"
echo "  Optimizer:       $OPTIMIZER"
if [ "$OPTIMIZER" = "ea" ]; then
    echo "  EA move:         $EA_MOVE (chain<=$EA_N_MUTATIONS)"
    echo "  Init samples:    $EA_INIT_SAMPLES"
    echo "  Inject every:    $EA_INJECTION_EVERY"
    echo "  Archive cap:     $ARCHIVE_CAP"
    echo "  Restart h:       $RESTART_H"
    echo "  Admission:       $ARCHIVE_ADMISSION"
    echo "  Origin parent:   $EA_ORIGIN_PARENT"
fi
echo "  Max depth:       $MAX_DEPTH"
echo "  Sampler K:       $RANDOM_MAX_CHANGES (n_changes in [1,K])"
echo "  Order weight:    $ORDER_MOVE_WEIGHT"
echo ""
echo "Run configuration:"
echo "  Model:           $MODEL_ID"
echo "  Quantization:    $QUANTIZATION"
echo "  Temperature:     $TEMPERATURE"
echo "  Test cases:      $N_CASES"
echo "  Iterations:      $N_ITERATIONS"
echo "  Seed:            $SEED"
echo "  Selection:       $SELECTION"
echo "  Languages:       ${LANGUAGES:-all}"
echo "  Semgrep rules:   $SEMGREP_RULESET"
echo "  Semgrep timeout: ${SEMGREP_TIMEOUT_SECONDS}s"
echo "  Semgrep jobs:    $SEMGREP_JOBS"
echo "  Mutators:        $MUTATORS"
echo "  Validation:      $ENABLE_VALIDATION (1=enabled)"
echo "  Perplexity gate: $ENABLE_PERPLEXITY (1=enabled; requires ENABLE_VALIDATION=1)"
echo "  Eval cache:      $ENABLE_EVAL_CACHE (0=disabled)"
echo "  Objective dir:   $OBJECTIVE_DIRECTION (minimize=reward fewer vulns)"
echo ""
echo "Input files:"
echo "  Rules map:       $RULES_MAP"
echo ""

REPO_ROOT="${REPO_ROOT:-/home/rnegro/thesis/rule-mutation}"
cd "$REPO_ROOT"

# Activate the venv and call python directly below. NEVER switch to `uv run python`:
# uv run re-syncs the venv to the lockfile on every invocation, which would revert the
# manually-installed CUDA torch (2.12.0+cu126) back to the lock's CPU pin. Inference
# would then silently run on CPU.
echo "=== Activating uv Environment ==="
source "$REPO_ROOT/.venv/bin/activate"

if [ -z "$VIRTUAL_ENV" ]; then
    echo "ERROR: Failed to activate uv environment at $REPO_ROOT/.venv"
    exit 1
fi

echo "Environment: $VIRTUAL_ENV"
echo "Python: $(which python)"
echo ""

# HuggingFace offline (GPU nodes have no internet)
export HF_HOME=/scratch/$USER/models
export TRANSFORMERS_CACHE=$HF_HOME/hub
export HF_HUB_OFFLINE=1

# GPU sanity
echo "=== GPU Check ==="
nvidia-smi --query-gpu=name,memory.total,memory.free --format=csv
echo ""

# Output dir naming policy: job<ID>_<strategy>_<lang>_s<seed>_<monthday>.
# Run-specific knobs (archive cap, restart h, n_cases) live in run_config.json,
# not the directory name — the name stays uniform across strategies so result sets
# are never confused. OUTPUT_BASE lets a curated set land in its own directory.
OUTPUT_BASE=${OUTPUT_BASE:-experiments/results}
DATE=$(date +%m%d)
STRAT_TAG=$([ "$OPTIMIZER" = "ea" ] && echo "ea" || echo "rand")
LANG_TAG=${LANGUAGES:-all}
OUTPUT_DIR="${OUTPUT_BASE}/job${SLURM_JOB_ID}_${STRAT_TAG}_${LANG_TAG}_s${SEED}_${DATE}"
mkdir -p "$OUTPUT_DIR"
mkdir -p logs

echo "=== Starting Experiment ==="
echo "Output directory: $OUTPUT_DIR"
echo ""

export PYTHONUNBUFFERED=1
export SEMGREP_RULESET
export SEMGREP_TIMEOUT_SECONDS
export SEMGREP_JOBS

if [ ! -e "$SEMGREP_RULESET" ]; then
    echo "❌ ERROR: Local Semgrep rules not found: $SEMGREP_RULESET"
    echo "   Run this once on a login node first:"
    echo "   scripts/setup/download_semgrep_security_audit_rules.sh"
    exit 1
fi

# Build optional language filter argument
LANG_ARG=""
if [ -n "$LANGUAGES" ]; then
    LANG_ARG="--languages $LANGUAGES"
fi

# Build optional validation flag (and optional perplexity extension)
VALIDATION_FLAG=""
if [ "$ENABLE_VALIDATION" = "1" ]; then
    VALIDATION_FLAG="--enable-validation"
    if [ "$ENABLE_PERPLEXITY" = "1" ]; then
        VALIDATION_FLAG="$VALIDATION_FLAG --enable-perplexity"
    fi
fi

# Build optional no-eval-cache flag (cache is ON by default; set ENABLE_EVAL_CACHE=0 to disable)
NO_EVAL_CACHE_FLAG=""
if [ "$ENABLE_EVAL_CACHE" = "0" ]; then
    NO_EVAL_CACHE_FLAG="--no-eval-cache"
fi

# Origin-as-parent flag (EA only; on by default, set EA_ORIGIN_PARENT=false to ablate)
ORIGIN_PARENT_FLAG="--ea-origin-parent"
if [ "$EA_ORIGIN_PARENT" = "false" ]; then
    ORIGIN_PARENT_FLAG="--no-ea-origin-parent"
fi

# Run in the background so the batch shell stays responsive to SIGUSR1. The
# trap forwards SLURM's pre-timeout signal to Python, which breaks the optimizer
# loop and saves final results before the wall-time SIGKILL. The while-loop
# re-issues `wait` because `wait` returns early when interrupted by the trap.
python scripts/experiments/run_experiment.py \
    --rules-map "$RULES_MAP" \
    --n-cases "$N_CASES" \
    $LANG_ARG \
    --selection "$SELECTION" \
    --iterations "$N_ITERATIONS" \
    --model "$MODEL_ID" \
    --backend delftblue \
    --quantization "$QUANTIZATION" \
    --temperature "$TEMPERATURE" \
    --seed "$SEED" \
    --mutators $MUTATORS \
    --optimizer "$OPTIMIZER" \
    --archive-cap "$ARCHIVE_CAP" \
    --restart-h "$RESTART_H" \
    --archive-admission "$ARCHIVE_ADMISSION" \
    --max-depth "$MAX_DEPTH" \
    --random-max-changes "$RANDOM_MAX_CHANGES" \
    --ea-n-mutations "$EA_N_MUTATIONS" \
    --ea-init-samples "$EA_INIT_SAMPLES" \
    --ea-injection-every "$EA_INJECTION_EVERY" \
    --ea-move "$EA_MOVE" \
    --order-move-weight "$ORDER_MOVE_WEIGHT" \
    $ORIGIN_PARENT_FLAG \
    $VALIDATION_FLAG \
    $NO_EVAL_CACHE_FLAG \
    --objective-direction "$OBJECTIVE_DIRECTION" \
    --semgrep-config "$SEMGREP_RULESET" \
    --semgrep-timeout-seconds "$SEMGREP_TIMEOUT_SECONDS" \
    --semgrep-jobs "$SEMGREP_JOBS" \
    --output-dir "$OUTPUT_DIR" &
PYTHON_PID=$!
trap 'echo "↪ Forwarding SLURM pre-timeout SIGUSR1 to Python (PID $PYTHON_PID)"; kill -USR1 "$PYTHON_PID" 2>/dev/null' USR1
# `set -e` (line 71) would abort the script the moment `wait` returns non-zero —
# which happens every time the USR1 trap interrupts it. Disable errexit around
# the wait so we can re-wait for Python's *real* exit after forwarding the signal.
set +e
wait "$PYTHON_PID"
EXIT_CODE=$?
# wait returns 128+signum (>128) when interrupted by the trap rather than by the
# child exiting — re-wait until Python actually finishes saving and exits.
while [ "$EXIT_CODE" -gt 128 ]; do
    wait "$PYTHON_PID"
    EXIT_CODE=$?
done
set -e
trap - USR1

echo ""
echo "=========================================================================="
echo "Experiment Complete"
echo "=========================================================================="
echo "Output directory: $OUTPUT_DIR"
echo "End: $(date)"

exit ${EXIT_CODE:-0}
