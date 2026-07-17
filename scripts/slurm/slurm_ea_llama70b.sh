#!/bin/bash
#SBATCH --job-name="sbst_ea_llama"
#SBATCH --account=education-eemcs-msc-cs
#SBATCH --partition=gpu-a100
#SBATCH --time=02:00:00
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
# MODEL: meta-llama/Llama-3.3-70B-Instruct, 4-bit NF4 quantization.
#   70B-4bit needs ~35 GB weights + KV cache → fits on ONE A100 80GB.
#   bf16 compute dtype (Llama-3.3 is bf16-native; fp16 dequant can overflow).
#
# Wall-time: NOT yet calibrated for this model. The 32B-fp16 baseline was
#   ~2.7 min/iteration (25 cases, gpu-a100). 70B-4bit is expected ~1.5-2x
#   slower per token, plus a longer (~3-5 min) weight-load step. ALWAYS run a
#   smoke test first and read the per-iteration timing before sizing a full run.
#
# Mirrors scripts/slurm/slurm_ea_qwen32b.sh; only the model, default
# quantization (4bit) and compute dtype (bf16) differ. OPTIMIZER ∈ {ea,
# random_search}.
#
# Usage:
#   # Smoke test FIRST — 2 cases, 5 iters (validates load + a few iterations)
#   N_CASES=2 N_ITERATIONS=5 \
#     sbatch --time=0:40:00 --job-name="ea_llama_smoke" \
#            scripts/slurm/slurm_ea_llama70b.sh
#
#   # Default: (1+1) EA, 16 cases, 10 iterations, archive_cap=6, restart_h=8.
#   sbatch scripts/slurm/slurm_ea_llama70b.sh
#
#   # Full sweep — 200 iters python (bump --time after smoke-test calibration!)
#   N_CASES=25 N_ITERATIONS=200 LANGUAGES=python SELECTION=random \
#     sbatch --time=20:00:00 --job-name="ea_llama_python_200" \
#            scripts/slurm/slurm_ea_llama70b.sh
#
#   # Full sweep — 200 iters java
#   N_CASES=25 N_ITERATIONS=200 LANGUAGES=java SELECTION=random \
#     sbatch --time=18:00:00 --job-name="ea_llama_java_200" \
#            scripts/slurm/slurm_ea_llama70b.sh
#
#   # Pure random baseline for ablation — python
#   OPTIMIZER=random_search N_CASES=25 N_ITERATIONS=200 LANGUAGES=python SELECTION=random \
#     sbatch --time=18:00:00 --job-name="rand_llama_python_200" \
#            scripts/slurm/slurm_ea_llama70b.sh
#
#   # Override quantization back to fp16 (will NOT fit 70B on one 80GB GPU;
#   # would need device_map across multiple GPUs) — not recommended.
#   QUANTIZATION=fp16 sbatch ... scripts/slurm/slurm_ea_llama70b.sh
#############################################################################

set -e

# ─────── Optimizer ───────────────────────────────────────────────────────────
OPTIMIZER=${OPTIMIZER:-ea}                # "ea" | "random_search"
ARCHIVE_CAP=${ARCHIVE_CAP:-6}             # Pareto archive size (EA)
RESTART_H=${RESTART_H:-8}                 # stagnation threshold (EA)
MAX_DEPTH=${MAX_DEPTH:-4}                 # per-rule stacked-mutation depth cap (both arms)
RANDOM_MAX_CHANGES=${RANDOM_MAX_CHANGES:-10}  # sampler K: n_changes in [1,K]
EA_N_MUTATIONS=${EA_N_MUTATIONS:-1}       # EA local move chain cap (1 = canonical step)
EA_INIT_SAMPLES=${EA_INIT_SAMPLES:-10}    # initial random samples offered to the archive
EA_INJECTION_EVERY=${EA_INJECTION_EVERY:-10}  # inject a random sample every N EA iters (0=off)
EA_MOVE=${EA_MOVE:-local}                 # "local" | "random_builder" (ablation)
ORDER_MOVE_WEIGHT=${ORDER_MOVE_WEIGHT:-0.1}   # rule-order move probability
EA_ORIGIN_PARENT=${EA_ORIGIN_PARENT:-true}    # origin sampleable as EA parent (false=ablate)

# ─────── Standard config ─────────────────────────────────────────────────────
N_CASES=${N_CASES:-16}
N_ITERATIONS=${N_ITERATIONS:-10}
QUANTIZATION=${QUANTIZATION:-4bit}        # 70B fits on one 80GB A100 only at 4bit
BNB_COMPUTE_DTYPE=${BNB_COMPUTE_DTYPE:-bfloat16}  # Llama-3.3 is bf16-native
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
# Validation default ON: the f2 rule-fidelity objective is SBERT-based.
ENABLE_VALIDATION=${ENABLE_VALIDATION:-1}
ENABLE_PERPLEXITY=${ENABLE_PERPLEXITY:-0}
ENABLE_EVAL_CACHE=${ENABLE_EVAL_CACHE:-1}
# Optimization direction: "minimize" (REPAIR: fewer vulns, default) | "maximize".
OBJECTIVE_DIRECTION=${OBJECTIVE_DIRECTION:-minimize}

MODEL_ID="meta-llama/Llama-3.3-70B-Instruct"
# Reusing the Qwen-generated retrieval map for now (same prompts+rules; only the
# code-gen model changes). Regenerate a Llama-specific map later if needed.
RULES_MAP=${RULES_MAP:-"/home/rnegro/thesis/rule-mutation/rule_maps/map_qwen32b_python_java.json"}

# Validate OPTIMIZER value
if [ "$OPTIMIZER" != "ea" ] && [ "$OPTIMIZER" != "random_search" ]; then
    echo "❌ ERROR: OPTIMIZER must be 'ea' or 'random_search' (got: $OPTIMIZER)."
    exit 1
fi

echo "=========================================================================="
echo "SBST: (1+1) EA / random_search run with Llama-3.3-70B-Instruct (4bit)"
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
    echo "  Origin parent:   $EA_ORIGIN_PARENT"
fi
echo "  Max depth:       $MAX_DEPTH"
echo "  Sampler K:       $RANDOM_MAX_CHANGES (n_changes in [1,K])"
echo "  Order weight:    $ORDER_MOVE_WEIGHT"
echo ""
echo "Run configuration:"
echo "  Model:           $MODEL_ID"
echo "  Quantization:    $QUANTIZATION"
echo "  BnB compute:     $BNB_COMPUTE_DTYPE"
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

# Output dir: tag the optimizer (and cap for EA) so EA / random / sweep runs don't mingle
DATE=$(date +%m%d)
if [ "$OPTIMIZER" = "ea" ]; then
    OUTPUT_DIR="experiments/results/job${SLURM_JOB_ID}_ea_llama_cap${ARCHIVE_CAP}_h${RESTART_H}_${N_CASES}_${DATE}"
else
    OUTPUT_DIR="experiments/results/job${SLURM_JOB_ID}_rand_llama_${N_CASES}_${DATE}"
fi
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
    --bnb-compute-dtype "$BNB_COMPUTE_DTYPE" \
    --temperature "$TEMPERATURE" \
    --seed "$SEED" \
    --mutators $MUTATORS \
    --optimizer "$OPTIMIZER" \
    --archive-cap "$ARCHIVE_CAP" \
    --restart-h "$RESTART_H" \
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
