#!/bin/bash
#SBATCH --job-name="rule_retrieval_reframed"
#SBATCH --account=education-eemcs-msc-cs
#SBATCH --partition=gpu-a100
#SBATCH --time=02:00:00
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=8
#SBATCH --gpus-per-task=1
#SBATCH --mem-per-cpu=8000M
#SBATCH --output=/home/rnegro/thesis/rule-mutation/logs/%j_%x.out
#SBATCH --error=/home/rnegro/thesis/rule-mutation/logs/%j_%x.err

#############################################################################
# Rule Retrieval Mapping on DelftBlue -- REFRAMED prompt (v2), any model.
#
# Runs src/retrieval/rule_retrieval_mapping_reframed.py, which moves the
# "select guidelines, do NOT write code" instruction into the user turn and
# wraps the code-generation prompt as <task> data -- the root-cause fix for
# Llama-3.3-70B writing code instead of selecting rules.
#
# One script for BOTH models: model, quantization and compute dtype are env
# vars (defaults = Qwen fp16). Single A100 80GB, one GPU / one node.
#
# ── Full-carrier retrieval and replacement-seed examples ─────────────────
#
#   # Qwen, one language carrier, 20 draws:
#   FROM_MAP=rule_maps/staging/eligible_python_carrier.json \
#   TEMPERATURE=0.6 SEED_START=1 REPETITIONS=20 \
#   OUTPUT_DIR=experiments/final_map_pipeline/retrieval/qwen_python \
#     sbatch --time=8:00:00 --job-name=reframed_qwen_py \
#            scripts/slurm/slurm_rule_retrieval_reframed.sh
#
#   # One replacement draw after rejecting an invalid seed:
#   FROM_MAP=rule_maps/staging/eligible_java_carrier.json \
#   TEMPERATURE=0.6 SEED_START=21 REPETITIONS=1 \
#   OUTPUT_DIR=experiments/final_map_pipeline/retrieval/qwen_java \
#     sbatch --time=2:00:00 --job-name=reframed_qwen_java_s21 \
#            scripts/slurm/slurm_rule_retrieval_reframed.sh
#
#   # Llama uses the same carrier with 4-bit/bfloat16 model settings:
#   MODEL_ID=meta-llama/Llama-3.3-70B-Instruct QUANTIZATION=4bit BNB_COMPUTE_DTYPE=bfloat16 \
#   FROM_MAP=rule_maps/staging/eligible_python_carrier.json \
#   TEMPERATURE=0.6 SEED_START=1 REPETITIONS=20 \
#   OUTPUT_DIR=experiments/final_map_pipeline/retrieval/llama_python \
#     sbatch --time=18:00:00 --job-name=reframed_llama_py \
#            scripts/slurm/slurm_rule_retrieval_reframed.sh
#
#   # Smoke (1 seed far outside the real range + dedicated dir, cleaned up after):
#   FROM_MAP=rule_maps/_smoke/smoke_py8.json \
#   TEMPERATURE=0.6 SEED_START=9001 REPETITIONS=1 \
#   OUTPUT_DIR=rule_maps/_smoke/reframed_smoke \
#     sbatch --time=1:00:00 --job-name=reframed_smoke \
#            scripts/slurm/slurm_rule_retrieval_reframed.sh
#
# Resume: a wall-time-killed sweep is idempotent -- resubmit the same command
# and seeds already written to OUTPUT_DIR are skipped.
#############################################################################

set -e

# Configuration (override via environment variables before sbatch)
QUANTIZATION=${QUANTIZATION:-fp16}               # fp16 (Qwen) | 4bit (Llama-70B on one A100)
BNB_COMPUTE_DTYPE=${BNB_COMPUTE_DTYPE:-float16}  # only used when QUANTIZATION=4bit; bf16 for Llama-3.3
MODEL_ID=${MODEL_ID:-"Qwen/Qwen2.5-Coder-32B-Instruct"}
MAX_TOKENS=${MAX_TOKENS:-1024}
FROM_MAP=${FROM_MAP:-}            # space-separated map path(s); the fixed prompt set to map
TEMPERATURE=${TEMPERATURE:-0.0}
SEED_START=${SEED_START:-1}
REPETITIONS=${REPETITIONS:-1}
OUTPUT_DIR=${OUTPUT_DIR:-}        # default in the Python script: rule_maps/temp_sweep_reframed
OUTPUT=${OUTPUT:-}
RESUME=${RESUME:-}
REPO_ROOT="${REPO_ROOT:-/home/rnegro/thesis/rule-mutation}"

mkdir -p "$REPO_ROOT/logs"
exec >"$REPO_ROOT/logs/rule_retrieval_reframed_${SLURM_JOB_ID}.out" \
     2>"$REPO_ROOT/logs/rule_retrieval_reframed_${SLURM_JOB_ID}.err"

echo "=========================================================================="
echo "Rule Retrieval Mapping on DelftBlue (REFRAMED v2)"
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
echo "  From map: ${FROM_MAP:-none}"
echo "  Output dir: ${OUTPUT_DIR:-default (rule_maps/temp_sweep_reframed)}"
echo "  Resume: ${RESUME:-none}"
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

echo "=== Starting Reframed Rule Retrieval ==="

# Build optional arguments
ARGS=""

if [ -n "$FROM_MAP" ]; then
    ARGS="$ARGS --from-map $FROM_MAP"
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

python src/retrieval/rule_retrieval_mapping_reframed.py \
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
echo "Reframed Rule Retrieval Complete"
echo "=========================================================================="
echo "Finished: $(date)"
echo ""

# Show final GPU state
echo "=== Final GPU State ==="
nvidia-smi --query-gpu=name,memory.used,utilization.gpu --format=csv
