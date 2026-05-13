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

#############################################################################
# SBST Experiment: (1+1) EA + Pareto archive OR random_baseline.
#
# Ad-hoc SLURM wrapper for the new optimizers introduced 2026-05-12.
# The legacy lex / D-UCB / round-robin path is served by the original
#   scripts/slurm/slurm_bandit_qwen32b.sh
# — this file is exclusively for OPTIMIZER ∈ {ea, random_baseline}.
#
# Usage:
#   # Default: (1+1) EA, 16 cases, 10 iterations, archive_cap=6, restart_h=8.
#   sbatch scripts/slurm/slurm_ea_qwen32b.sh
#
#   # Smoke test before the real run — 2 cases, 5 iters
#   N_CASES=2 N_ITERATIONS=5 \
#     sbatch --time=0:30:00 --job-name="ea_smoke" \
#            scripts/slurm/slurm_ea_qwen32b.sh
#
#   # Full sweep — 200 iters python, 4h walltime
#   N_CASES=25 N_ITERATIONS=200 LANGUAGES=python \
#     sbatch --time=4:00:00 --job-name="ea_python_200" \
#            scripts/slurm/slurm_ea_qwen32b.sh
#
#   # Pure random baseline for ablation
#   OPTIMIZER=random_baseline N_CASES=25 N_ITERATIONS=200 LANGUAGES=python \
#     sbatch --time=4:00:00 --job-name="rand_python_200" \
#            scripts/slurm/slurm_ea_qwen32b.sh
#
#   # Archive-size sweep — six jobs at different caps
#   for cap in 2 4 6 8 10 12; do
#     ARCHIVE_CAP=$cap N_ITERATIONS=200 \
#       sbatch --job-name="ea_cap${cap}" scripts/slurm/slurm_ea_qwen32b.sh
#   done
#############################################################################

set -e

# ─────── Optimizer (new) ────────────────────────────────────────────────────
OPTIMIZER=${OPTIMIZER:-ea}                # "ea" | "random_baseline"
ARCHIVE_CAP=${ARCHIVE_CAP:-6}             # Pareto archive size per rule
RESTART_H=${RESTART_H:-8}                 # stagnation threshold
MAX_DEPTH_EA=${MAX_DEPTH_EA:-4}           # per-entry depth cap

# ─────── Standard config (unchanged) ────────────────────────────────────────
N_CASES=${N_CASES:-16}
N_ITERATIONS=${N_ITERATIONS:-10}
QUANTIZATION=${QUANTIZATION:-fp16}
SEED=${SEED:-42}
SELECTION=${SELECTION:-first}
LANGUAGES=${LANGUAGES:-}
SEMGREP_RULESET=${SEMGREP_RULESET:-/scratch/$USER/semgrep-rules/security-audit}
SEMGREP_TIMEOUT_SECONDS=${SEMGREP_TIMEOUT_SECONDS:-180}
SEMGREP_JOBS=${SEMGREP_JOBS:-4}
# Mutator pool: same list as the legacy script; --mutator-strategy is still
# required because the pool is constructed regardless of optimizer, but EA
# and random_baseline ignore the strategy and do their own constrained
# random selection.
MUTATORS=${MUTATORS:-"synonym_replacement add_random_word verb_weakening negation_injection voice_change paraphrase section_reorder_shuffle section_reorder_degrade"}
MUTATOR_STRATEGY=${MUTATOR_STRATEGY:-round_robin}
ENABLE_VALIDATION=${ENABLE_VALIDATION:-0}
ENABLE_PERPLEXITY=${ENABLE_PERPLEXITY:-0}
MUTATION_MAX_RETRIES=${MUTATION_MAX_RETRIES:-2}
ENABLE_EVAL_CACHE=${ENABLE_EVAL_CACHE:-1}

MODEL_ID="Qwen/Qwen2.5-Coder-32B-Instruct"
RULES_MAP=${RULES_MAP:-"/home/rnegro/thesis/rule-mutation/pipeline_breakdown/rule_retrieval_output/map_qwen32b_python_java.json"}

# Validate OPTIMIZER value
if [ "$OPTIMIZER" != "ea" ] && [ "$OPTIMIZER" != "random_baseline" ]; then
    echo "❌ ERROR: OPTIMIZER must be 'ea' or 'random_baseline' (got: $OPTIMIZER)."
    echo "   For lex / D-UCB / round-robin runs use slurm_bandit_qwen32b.sh instead."
    exit 1
fi

echo "=========================================================================="
echo "SBST: (1+1) EA / random_baseline run with Qwen 32B"
echo "=========================================================================="
echo "Started: $(date)"
echo "Job ID: $SLURM_JOB_ID"
echo "Node: $(hostname)"
echo "Partition: $SLURM_JOB_PARTITION"
echo ""
echo "Optimizer configuration:"
echo "  Optimizer:       $OPTIMIZER"
if [ "$OPTIMIZER" = "ea" ]; then
    echo "  Archive cap:     $ARCHIVE_CAP"
    echo "  Restart h:       $RESTART_H"
fi
echo "  Max depth (EA):  $MAX_DEPTH_EA"
echo ""
echo "Run configuration:"
echo "  Model:           $MODEL_ID"
echo "  Quantization:    $QUANTIZATION"
echo "  Test cases:      $N_CASES"
echo "  Iterations:      $N_ITERATIONS"
echo "  Seed:            $SEED"
echo "  Selection:       $SELECTION"
echo "  Languages:       ${LANGUAGES:-all}"
echo "  Semgrep rules:   $SEMGREP_RULESET"
echo "  Semgrep timeout: ${SEMGREP_TIMEOUT_SECONDS}s"
echo "  Semgrep jobs:    $SEMGREP_JOBS"
echo "  Mutators:        $MUTATORS"
echo "  Pool strategy:   $MUTATOR_STRATEGY  (ignored by EA/random_baseline — pool init only)"
echo "  Validation:      $ENABLE_VALIDATION (1=enabled)"
echo "  Perplexity gate: $ENABLE_PERPLEXITY (1=enabled; requires ENABLE_VALIDATION=1)"
echo "  Eval cache:      $ENABLE_EVAL_CACHE (0=disabled)"
echo ""
echo "Input files:"
echo "  Rules map:       $RULES_MAP"
echo ""

# Activate conda environment
echo "=== Activating Environment ==="
source /scratch/$USER/software/miniconda3/etc/profile.d/conda.sh
conda activate sbst

if [ "$CONDA_DEFAULT_ENV" != "sbst" ]; then
    echo "❌ ERROR: Failed to activate sbst environment"
    exit 1
fi

echo "✅ Environment: $CONDA_DEFAULT_ENV"
echo "   Python: $(which python)"
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
    OUTPUT_DIR="experiments/results/job${SLURM_JOB_ID}_ea_cap${ARCHIVE_CAP}_h${RESTART_H}_${N_CASES}_${DATE}"
else
    OUTPUT_DIR="experiments/results/job${SLURM_JOB_ID}_rand_${N_CASES}_${DATE}"
fi
mkdir -p "$OUTPUT_DIR"
mkdir -p logs

# Flush SLURM logs into the output dir on any exit (matches legacy script)
_flush_slurm_logs() {
  for f in /home/rnegro/thesis/rule-mutation/logs/*${SLURM_JOB_ID}*.out \
            /home/rnegro/thesis/rule-mutation/logs/*${SLURM_JOB_ID}*.err; do
    [ -f "$f" ] && cp "$f" "${OUTPUT_DIR}/" 2>/dev/null || true
  done
}
trap _flush_slurm_logs EXIT TERM INT

echo "=== Starting Experiment ==="
echo "Output directory: $OUTPUT_DIR"
echo ""

REPO_ROOT="${REPO_ROOT:-/home/rnegro/thesis/rule-mutation}"
cd "$REPO_ROOT"

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
    VALIDATION_FLAG="--enable-validation --mutation-max-retries $MUTATION_MAX_RETRIES"
    if [ "$ENABLE_PERPLEXITY" = "1" ]; then
        VALIDATION_FLAG="$VALIDATION_FLAG --enable-perplexity"
    fi
fi

# Build optional no-eval-cache flag (cache is ON by default; set ENABLE_EVAL_CACHE=0 to disable)
NO_EVAL_CACHE_FLAG=""
if [ "$ENABLE_EVAL_CACHE" = "0" ]; then
    NO_EVAL_CACHE_FLAG="--no-eval-cache"
fi

python scripts/experiments/run_with_rules_map.py \
    --rules-map "$RULES_MAP" \
    --n-cases "$N_CASES" \
    $LANG_ARG \
    --selection "$SELECTION" \
    --iterations "$N_ITERATIONS" \
    --model "$MODEL_ID" \
    --backend local \
    --quantization "$QUANTIZATION" \
    --seed "$SEED" \
    --mutators $MUTATORS \
    --mutator-strategy "$MUTATOR_STRATEGY" \
    --optimizer "$OPTIMIZER" \
    --archive-cap "$ARCHIVE_CAP" \
    --restart-h "$RESTART_H" \
    --max-depth-ea "$MAX_DEPTH_EA" \
    $VALIDATION_FLAG \
    $NO_EVAL_CACHE_FLAG \
    --semgrep-config "$SEMGREP_RULESET" \
    --semgrep-timeout-seconds "$SEMGREP_TIMEOUT_SECONDS" \
    --semgrep-jobs "$SEMGREP_JOBS" \
    --output-dir "$OUTPUT_DIR"

echo ""
echo "=========================================================================="
echo "Experiment Complete"
echo "=========================================================================="
echo "Output directory: $OUTPUT_DIR"
echo "End: $(date)"
