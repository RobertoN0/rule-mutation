#!/bin/bash
#SBATCH --job-name="sbst_ea"
#SBATCH --account=education-eemcs-msc-cs
#SBATCH --partition=gpu-a100
#SBATCH --time=01:30:00
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=8
#SBATCH --gpus-per-task=1
#SBATCH --mem-per-cpu=8000M
# Graceful pre-timeout: deliver SIGUSR1 to the batch shell (B:) 300s before the
# wall-time SIGKILL so the run can save final results. Override per job for
# long-evaluation (full-population) runs, e.g.: sbatch --signal=B:USR1@700 ...
#SBATCH --signal=B:USR1@300

#############################################################################
# SBST Experiment: archive EA (shared init + injection) OR i.i.d. random search.
#
# Historical small-subset timings do not predict the frozen full population.
# Choose wall time at submission from the run objective: short smoke, an
# extended behavior validation, or the supervisor-approved final allocation.
# The pre-timeout signal preserves the last completed candidate. Final
# comparisons use the same allocation; evaluation-index curves are secondary.
#
# This file is the only mutation-run launcher: OPTIMIZER ∈ {ea, random_search}.
# Validation is ON by default — the f2 rule-fidelity objective needs SBERT.
#
# Usage:
#   # Default: EA, 16 cases, 5 shared initialization + 10 main-loop evaluations.
#   sbatch scripts/slurm/slurm_ea_qwen32b.sh
#
#   # Smoke test before the real run
#   N_CASES=2 MAIN_LOOP_BUDGET=5 \
#     sbatch --time=0:30:00 --job-name="ea_smoke" \
#            scripts/slurm/slurm_ea_qwen32b.sh
#
#   # Full-population EA. Use a high evaluation ceiling; wall time is primary.
#   N_CASES=all MAIN_LOOP_BUDGET="$EVALUATION_CEILING" LANGUAGES=python SELECTION=first \
#     sbatch --time="$APPROVED_SLURM_TIME" --job-name="ea_python_final" \
#            scripts/slurm/slurm_ea_qwen32b.sh
#
#   # Random search — same initialization, population, and wall-clock budget.
#   OPTIMIZER=random_search N_CASES=all MAIN_LOOP_BUDGET="$EVALUATION_CEILING" LANGUAGES=python SELECTION=first \
#     sbatch --time="$APPROVED_SLURM_TIME" --job-name="rand_python_final" \
#            scripts/slurm/slurm_ea_qwen32b.sh
#############################################################################

set -e

# ─────── Optimizer ───────────────────────────────────────────────────────────
OPTIMIZER=${OPTIMIZER:-ea}                # "ea" | "random_search"
ARCHIVE_CAP=${ARCHIVE_CAP:-6}             # Pareto archive size (EA)
MAX_DEPTH=${MAX_DEPTH:-4}                 # per-rule stacked-mutation depth cap (both arms)
# K for the shared random sampler: each random chromosome stacks n∈[1,K] changes
# (supervisor pseudocode: random(1,10)). Used by random_search + EA init/injection.
RANDOM_MAX_CHANGES=${RANDOM_MAX_CHANGES:-10}
# Five shared initialization candidates are fixed by the final method.
EA_INJECTION_EVERY=${EA_INJECTION_EVERY:-10}  # inject a random sample every N EA iters (0=off)
# Probability of a rule-order move (per EA local move and per sampler change).
ORDER_MOVE_WEIGHT=${ORDER_MOVE_WEIGHT:-0.1}

# ─────── Standard config ─────────────────────────────────────────────────────
N_CASES=${N_CASES:-16}
MAIN_LOOP_BUDGET=${MAIN_LOOP_BUDGET:-10}
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
ALLOW_UNQUALIFIED_MAP=${ALLOW_UNQUALIFIED_MAP:-0}
REPO_ROOT=${REPO_ROOT:-/home/rnegro/thesis/rule-mutation}
OUTPUT_BASE=${OUTPUT_BASE:-"$REPO_ROOT/experiments/results"}
INITIALIZATION_BUNDLE=${INITIALIZATION_BUNDLE:-}
TIME_BUDGET_SECONDS=${TIME_BUDGET_SECONDS:-}
PRETIMEOUT_LEAD_SECONDS=${PRETIMEOUT_LEAD_SECONDS:-300}
# Time-bounded runs: set MAIN_LOOP_BUDGET high and let the SBATCH --time + the
# pre-timeout signal (--signal=B:USR1@<lead>, header) stop the run by aborting the
# in-flight evaluation and finalizing from the last completed one.

MODEL_ID="Qwen/Qwen2.5-Coder-32B-Instruct"
if [ -z "${RULES_MAP:-}" ]; then
    if [ "$LANGUAGES" = "python" ] || [ "$LANGUAGES" = "java" ]; then
        RULES_MAP="$REPO_ROOT/rule_maps/qualified/final_search_map_qwen_${LANGUAGES}.json"
    else
        RULES_MAP="$REPO_ROOT/rule_maps/qualified/final_search_map_qwen.json"
    fi
fi

# Validate OPTIMIZER value
if [ "$OPTIMIZER" != "ea" ] && [ "$OPTIMIZER" != "random_search" ]; then
    echo "❌ ERROR: OPTIMIZER must be 'ea' or 'random_search' (got: $OPTIMIZER)."
    exit 1
fi

echo "=========================================================================="
echo "SBST: archive EA / random-search run with Qwen 32B"
echo "=========================================================================="
echo "Started: $(date)"
echo "Job ID: $SLURM_JOB_ID"
echo "Node: $(hostname)"
echo "Partition: $SLURM_JOB_PARTITION"
echo ""
echo "Optimizer configuration:"
echo "  Optimizer:       $OPTIMIZER"
if [ "$OPTIMIZER" = "ea" ]; then
    echo "  Init samples:    5 (shared, outside main-loop budget)"
    echo "  Inject every:    $EA_INJECTION_EVERY"
    echo "  Archive cap:     $ARCHIVE_CAP"
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
echo "  Main-loop budget:$MAIN_LOOP_BUDGET"
echo "  Total ceiling:   $((MAIN_LOOP_BUDGET + 5)) evaluations"
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
echo "  Init bundle:     ${INITIALIZATION_BUNDLE:-none}"
echo "  Time budget:     ${TIME_BUDGET_SECONDS:-not declared} seconds"
echo "  Pretimeout lead: ${PRETIMEOUT_LEAD_SECONDS}s"
echo ""
echo "Input files:"
echo "  Rules map:       $RULES_MAP"
echo ""

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
# Run-specific knobs (archive cap, n_cases) live in run_config.json,
# not the directory name — the name stays uniform across strategies so result sets
# are never confused. OUTPUT_BASE lets a curated set land in its own directory.
DATE=$(date +%m%d)
STRAT_TAG=$([ "$OPTIMIZER" = "ea" ] && echo "ea" || echo "rand")
LANG_TAG=${LANGUAGES:-all}
OUTPUT_DIR="${OUTPUT_BASE}/job${SLURM_JOB_ID}_${STRAT_TAG}_${LANG_TAG}_s${SEED}_${DATE}"
mkdir -p "$OUTPUT_DIR"
mkdir -p "$OUTPUT_BASE/slurm_logs"
exec >"$OUTPUT_BASE/slurm_logs/${SLURM_JOB_ID}_${SLURM_JOB_NAME}.out" \
     2>"$OUTPUT_BASE/slurm_logs/${SLURM_JOB_ID}_${SLURM_JOB_NAME}.err"

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
    echo "   scripts/setup/download_semgrep_security_audit_rules.sh <target-dir> <commit>"
    exit 1
fi
if [ ! -s "$SEMGREP_RULESET/SOURCE_COMMIT" ]; then
    echo "❌ ERROR: search requires pinned Semgrep rules with SOURCE_COMMIT."
    exit 1
fi

# Build optional language filter argument
LANG_ARG=""
if [ -n "$LANGUAGES" ]; then
    LANG_ARG="--languages $LANGUAGES"
fi

CASE_ARG=""
if [ "$N_CASES" != "all" ]; then
    CASE_ARG="--n-cases $N_CASES"
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

UNQUALIFIED_MAP_FLAG=""
if [ "$ALLOW_UNQUALIFIED_MAP" = "1" ]; then
    UNQUALIFIED_MAP_FLAG="--allow-unqualified-map"
fi

INITIALIZATION_BUNDLE_FLAG=""
if [ -n "$INITIALIZATION_BUNDLE" ]; then
    INITIALIZATION_BUNDLE_FLAG="--initialization-bundle $INITIALIZATION_BUNDLE"
fi

TIME_BUDGET_FLAG=""
if [ -n "$TIME_BUDGET_SECONDS" ]; then
    TIME_BUDGET_FLAG="--wall-time-budget-seconds $TIME_BUDGET_SECONDS"
fi

# Run in the background so the batch shell stays responsive to SIGUSR1. The
# trap forwards SLURM's pre-timeout signal to Python, which breaks the optimizer
# loop and saves final results before the wall-time SIGKILL. The while-loop
# re-issues `wait` because `wait` returns early when interrupted by the trap.
python scripts/experiments/run_experiment.py \
    --rules-map "$RULES_MAP" \
    $CASE_ARG \
    $LANG_ARG \
    --selection "$SELECTION" \
    --main-loop-budget "$MAIN_LOOP_BUDGET" \
    --model "$MODEL_ID" \
    --backend delftblue \
    --quantization "$QUANTIZATION" \
    --temperature "$TEMPERATURE" \
    --seed "$SEED" \
    --mutators $MUTATORS \
    --optimizer "$OPTIMIZER" \
    --archive-cap "$ARCHIVE_CAP" \
    --max-depth "$MAX_DEPTH" \
    --random-max-changes "$RANDOM_MAX_CHANGES" \
    --ea-injection-every "$EA_INJECTION_EVERY" \
    --order-move-weight "$ORDER_MOVE_WEIGHT" \
    $INITIALIZATION_BUNDLE_FLAG \
    $TIME_BUDGET_FLAG \
    --pretimeout-lead-seconds "$PRETIMEOUT_LEAD_SECONDS" \
    $VALIDATION_FLAG \
    $NO_EVAL_CACHE_FLAG \
    $UNQUALIFIED_MAP_FLAG \
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

# ── Post-run: shrink + audit semgrep_debug ───────────────────────────────────
# Strip the giant raw semgrep stdout (results/paths/timing) from
# semgrep_debug.jsonl, keeping each call's findings + an extracted error audit
# (semgrep_analysis).
FILTER="$REPO_ROOT/scripts/experiments/filter_semgrep_debug.py"
if [ -f "$OUTPUT_DIR/semgrep_debug/semgrep_debug.jsonl" ]; then
    echo ""
    echo "→ Filtering semgrep_debug (strip raw stdout, keep findings + error audit)…"
    timeout 250 python "$FILTER" --in-place --audit-json "$OUTPUT_DIR" \
        || echo "⚠️  semgrep_debug filter incomplete/skipped (raw kept — re-run on login)"
fi

VALIDATOR="$REPO_ROOT/scripts/analyze/validate_search_run.py"
if [ "${EXIT_CODE:-1}" -eq 0 ]; then
    echo "→ Validating search artifacts…"
    if ! python "$VALIDATOR" --write "$OUTPUT_DIR"; then
        echo "❌ Search-run validation failed"
        EXIT_CODE=3
    fi
fi

echo ""
echo "=========================================================================="
echo "Experiment Complete"
echo "=========================================================================="
echo "Output directory: $OUTPUT_DIR"
echo "End: $(date)"

exit ${EXIT_CODE:-0}
