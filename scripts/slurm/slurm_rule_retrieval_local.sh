#!/bin/bash
#SBATCH --job-name="rule_retrieval_local"
#SBATCH --account=education-eemcs-msc-cs
#SBATCH --partition=gpu-a100
#SBATCH --time=02:00:00
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=8
#SBATCH --gpus-per-task=1
#SBATCH --mem-per-cpu=8000M
#SBATCH --output=/home/rnegro/thesis/rule-mutation/logs/rule_retrieval_local_%j.out
#SBATCH --error=/home/rnegro/thesis/rule-mutation/logs/rule_retrieval_local_%j.err

#############################################################################
# Rule Retrieval Mapping: Local Model on DelftBlue
#
# Maps CyberSecEval prompts -> CodeGuard rules using a locally-hosted model.
# Single-turn prompt with embedded guidelines list (no tool-calling needed).
#
# Usage:
#   # Default (5 per CWE, FP16, Qwen 32B)
#   sbatch scripts/slurm/slurm_rule_retrieval_local.sh
#
#   # All prompts for specific CWEs
#   CWES="CWE-89 CWE-79 CWE-78" \
#     sbatch scripts/slurm/slurm_rule_retrieval_local.sh
#
#   # Expand coverage, skipping already-mapped prompts
#   LIMIT_PER_CWE=10 \
#   EXCLUDE_MAP=rule_maps/prev_run.json \
#     sbatch scripts/slurm/slurm_rule_retrieval_local.sh
#
#   # Specific languages, 4-bit quantization
#   LANGUAGES="python java" QUANTIZATION=4bit \
#     sbatch scripts/slurm/slurm_rule_retrieval_local.sh
#
#   # Resume an interrupted run
#   RESUME=rule_maps/rule_retrieval_progress_local_20260410.jsonl \
#     sbatch scripts/slurm/slurm_rule_retrieval_local.sh
#
#   # Temperature/seed sweep over a FIXED prompt set (bypasses CWE selection --
#   # reuses an existing map's exact prompts; the model loads once and is
#   # reused across all seeds). seeds run SEED_START .. SEED_START+REPETITIONS-1:
#   FROM_MAP=rule_maps/old_maps/map_qwen32b_vulnerable_py.json \
#   TEMPERATURE=0.6 SEED_START=1 REPETITIONS=20 \
#     sbatch --time=14:00:00 scripts/slurm/slurm_rule_retrieval_local.sh
#
#   # Same sweep on Llama-70B (override MODEL_ID/QUANTIZATION as below; 70B needs
#   # 4bit/bfloat16 on a single A100). For current maps prefer the reframed
#   # wrapper: scripts/slurm/slurm_rule_retrieval_reframed.sh (both models).
#   MODEL_ID="meta-llama/Llama-3.3-70B-Instruct" QUANTIZATION=4bit \
#   BNB_COMPUTE_DTYPE=bfloat16 \
#   FROM_MAP=rule_maps/old_maps/map_qwen32b_vulnerable_py.json \
#   TEMPERATURE=0.6 SEED_START=1 REPETITIONS=20 \
#     sbatch --time=20:00:00 scripts/slurm/slurm_rule_retrieval_local.sh
#############################################################################

set -e

# Configuration (override via environment variables before sbatch)
LIMIT_PER_CWE=${LIMIT_PER_CWE-5}   # use :-5 only when unset; empty string = no limit
TOTAL_LIMIT=${TOTAL_LIMIT:-}
CWES=${CWES:-}                    # space-separated, e.g. "CWE-89 CWE-79"
LANGUAGES=${LANGUAGES:-}          # space-separated, e.g. "python java"
QUANTIZATION=${QUANTIZATION:-fp16}
BNB_COMPUTE_DTYPE=${BNB_COMPUTE_DTYPE:-float16}  # only used when QUANTIZATION=4bit
MODEL_ID=${MODEL_ID:-"Qwen/Qwen2.5-Coder-32B-Instruct"}
MAX_TOKENS=${MAX_TOKENS:-1024}
EXCLUDE_MAP=${EXCLUDE_MAP:-}
FROM_MAP=${FROM_MAP:-}            # space-separated map path(s); bypasses CWE selection
TEMPERATURE=${TEMPERATURE:-0.0}
SEED_START=${SEED_START:-1}
REPETITIONS=${REPETITIONS:-1}
RESUME=${RESUME:-}
OUTPUT=${OUTPUT:-}
OUTPUT_DIR=${OUTPUT_DIR:-}

echo "=========================================================================="
echo "Rule Retrieval Mapping: Local Model on DelftBlue"
echo "=========================================================================="
echo "Started: $(date)"
echo "Job ID: $SLURM_JOB_ID"
echo "Node: $(hostname)"
echo "Partition: $SLURM_JOB_PARTITION"
echo ""
echo "Configuration:"
echo "  Model: $MODEL_ID"
echo "  Quantization: $QUANTIZATION"$([ "$QUANTIZATION" = "4bit" ] && echo " (compute_dtype=$BNB_COMPUTE_DTYPE)")
echo "  Max tokens: $MAX_TOKENS"
echo "  Temperature: $TEMPERATURE"
echo "  Seed start / repetitions: $SEED_START / $REPETITIONS"
echo "  From map: ${FROM_MAP:-none (uses CWE-based selection below)}"
echo "  Limit per CWE: ${LIMIT_PER_CWE:-all}"
echo "  Total limit: ${TOTAL_LIMIT:-none}"
echo "  CWEs: ${CWES:-all}"
echo "  Languages: ${LANGUAGES:-all}"
echo "  Exclude map: ${EXCLUDE_MAP:-none}"
echo "  Resume: ${RESUME:-none}"
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

# Set HuggingFace environment variables (GPU nodes have no internet)
export HF_HOME=/scratch/$USER/models
export TRANSFORMERS_CACHE=$HF_HOME/hub
export HF_HUB_OFFLINE=1
# Pin datasets/modules caches back to home: HF_HOME redirects them to scratch
# where they don't exist. Model weights live on scratch; datasets live in home.
export HF_DATASETS_CACHE=/home/$USER/.cache/huggingface/datasets
export HF_MODULES_CACHE=/home/$USER/.cache/huggingface/modules
export HF_DATASETS_OFFLINE=1

# Verify GPU
echo "=== GPU Check ==="
nvidia-smi --query-gpu=name,memory.total,memory.free --format=csv
echo ""

# Ensure logs directory exists
mkdir -p logs

export PYTHONUNBUFFERED=1

echo "=== Starting Rule Retrieval ==="

# Build optional arguments
ARGS=""

if [ -n "$FROM_MAP" ]; then
    # --from-map reuses a prompt set verbatim; the CWE-selection flags below
    # are meaningless in that mode and the Python script rejects combining
    # them, so skip adding them entirely (rather than relying on the caller
    # to remember to clear LIMIT_PER_CWE's default of 5).
    ARGS="$ARGS --from-map $FROM_MAP"
else
    if [ -n "$LIMIT_PER_CWE" ]; then
        ARGS="$ARGS --limit-per-cwe $LIMIT_PER_CWE"
    fi

    if [ -n "$TOTAL_LIMIT" ]; then
        ARGS="$ARGS --total-limit $TOTAL_LIMIT"
    fi

    if [ -n "$CWES" ]; then
        ARGS="$ARGS --cwes $CWES"
    fi

    if [ -n "$LANGUAGES" ]; then
        ARGS="$ARGS --languages $LANGUAGES"
    fi

    if [ -n "$EXCLUDE_MAP" ]; then
        ARGS="$ARGS --exclude-map $EXCLUDE_MAP"
    fi
fi

if [ -n "$RESUME" ]; then
    ARGS="$ARGS --resume $RESUME"
fi

if [ -n "$OUTPUT" ]; then
    ARGS="$ARGS --output $OUTPUT"
fi

if [ -n "$OUTPUT_DIR" ]; then
    ARGS="$ARGS --output-dir $OUTPUT_DIR"
fi

python src/retrieval/rule_retrieval_mapping_local.py \
    --model "$MODEL_ID" \
    --quantization "$QUANTIZATION" \
    --bnb-compute-dtype "$BNB_COMPUTE_DTYPE" \
    --max-tokens "$MAX_TOKENS" \
    --temperature "$TEMPERATURE" \
    --seed-start "$SEED_START" \
    --repetitions "$REPETITIONS" \
    --yes \
    $ARGS

echo ""
echo "=========================================================================="
echo "Rule Retrieval Complete"
echo "=========================================================================="
echo "Finished: $(date)"
echo ""

# Show final GPU state
echo "=== Final GPU State ==="
nvidia-smi --query-gpu=name,memory.used,utilization.gpu --format=csv
