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
#   EXCLUDE_MAP=pipeline_breakdown/rule_retrieval_output/prev_run.json \
#     sbatch scripts/slurm/slurm_rule_retrieval_local.sh
#
#   # Specific languages, 4-bit quantization
#   LANGUAGES="python java" QUANTIZATION=4bit \
#     sbatch scripts/slurm/slurm_rule_retrieval_local.sh
#
#   # Resume an interrupted run
#   RESUME=pipeline_breakdown/rule_retrieval_output/rule_retrieval_progress_local_20260410.jsonl \
#     sbatch scripts/slurm/slurm_rule_retrieval_local.sh
#############################################################################

set -e

# Configuration (override via environment variables before sbatch)
LIMIT_PER_CWE=${LIMIT_PER_CWE-5}   # use :-5 only when unset; empty string = no limit
TOTAL_LIMIT=${TOTAL_LIMIT:-}
CWES=${CWES:-}                    # space-separated, e.g. "CWE-89 CWE-79"
LANGUAGES=${LANGUAGES:-}          # space-separated, e.g. "python java"
QUANTIZATION=${QUANTIZATION:-fp16}
MODEL_ID=${MODEL_ID:-"Qwen/Qwen2.5-Coder-32B-Instruct"}
MAX_TOKENS=${MAX_TOKENS:-1024}
EXCLUDE_MAP=${EXCLUDE_MAP:-}
RESUME=${RESUME:-}
OUTPUT=${OUTPUT:-}

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
echo "  Quantization: $QUANTIZATION"
echo "  Max tokens: $MAX_TOKENS"
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

if [ -n "$RESUME" ]; then
    ARGS="$ARGS --resume $RESUME"
fi

if [ -n "$OUTPUT" ]; then
    ARGS="$ARGS --output $OUTPUT"
fi

python pipeline_breakdown/rule_retrieval_mapping_local.py \
    --model "$MODEL_ID" \
    --quantization "$QUANTIZATION" \
    --max-tokens "$MAX_TOKENS" \
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
