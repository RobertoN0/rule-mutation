#!/bin/bash
#SBATCH --job-name="sbst_rules_map"
#SBATCH --partition=gpu-a100
#SBATCH --time=10:00:00
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=8
#SBATCH --gpus-per-task=1
#SBATCH --mem-per-cpu=8000M
#SBATCH --output=/home/rnegro/thesis/rule-mutation/logs/sbst_rules_map_%j.out
#SBATCH --error=/home/rnegro/thesis/rule-mutation/logs/sbst_rules_map_%j.err

#############################################################################
# SBST Experiment: Per-Prompt Rules Hill Climbing with Qwen 32B
# 
# Uses:
# - Interesting cases from batch experiments (pre-selected test prompts)
# - Rule retrieval mapping (per-prompt CodeGuard rules via AI selection)
# - Local Qwen2.5-Coder-32B-Instruct on A100 80GB GPU
# 
# Usage:
#   # Default (3 cases, 3 iterations, FP16)
#   sbatch scripts/slurm/slurm_rules_map_qwen32b.sh
#
#   # Custom configuration
#   N_CASES=5 N_ITERATIONS=5 sbatch scripts/slurm/slurm_rules_map_qwen32b.sh
#
#   # With 4-bit quantization (18GB VRAM)
#   QUANTIZATION=4bit sbatch scripts/slurm/slurm_rules_map_qwen32b.sh
#############################################################################

set -e  # Exit on error

# Configuration (override via environment variables before sbatch)
N_CASES=${N_CASES:-16}
N_ITERATIONS=${N_ITERATIONS:-10}
EARLY_STOP=${EARLY_STOP:-0}        # 0 = disabled; run all iterations
QUANTIZATION=${QUANTIZATION:-fp16}
SEED=${SEED:-42}
SELECTION=${SELECTION:-random}
LANGUAGES=${LANGUAGES:-}  # space-separated, e.g. "c python"; empty = all
SEMGREP_RULESET=${SEMGREP_RULESET:-/scratch/$USER/semgrep-rules/security-audit}
SEMGREP_TIMEOUT_SECONDS=${SEMGREP_TIMEOUT_SECONDS:-180}
SEMGREP_JOBS=${SEMGREP_JOBS:-1}

MODEL_ID="Qwen/Qwen2.5-Coder-32B-Instruct"

# Input files (from previous batch experiments)
INTERESTING_CASES="pipeline_breakdown/generation_results/interesting_cases_96_sonnet_4_6.json"
RULES_MAP="pipeline_breakdown/rule_retrieval_output/retrieval_map_96_sonnet_4_6.json"

echo "=========================================================================="
echo "SBST: Per-Prompt Rules Hill Climbing with Qwen 32B"
echo "=========================================================================="
echo "Started: $(date)"
echo "Job ID: $SLURM_JOB_ID"
echo "Node: $(hostname)"
echo "Partition: $SLURM_JOB_PARTITION"
echo ""
echo "Configuration:"
echo "  Model: $MODEL_ID"
echo "  Quantization: $QUANTIZATION"
echo "  Test cases: $N_CASES"
echo "  Iterations: $N_ITERATIONS"
echo "  Early stop: ${EARLY_STOP} (0=disabled)"
echo "  Seed: $SEED"
echo "  Selection: $SELECTION"
echo "  Languages: ${LANGUAGES:-all}"
echo "  Semgrep rules: $SEMGREP_RULESET"
echo "  Semgrep timeout: ${SEMGREP_TIMEOUT_SECONDS}s"
echo "  Semgrep jobs: $SEMGREP_JOBS"
echo ""
echo "Input files:"
echo "  Interesting cases: $INTERESTING_CASES"
echo "  Rules map: $RULES_MAP"
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

# Set HuggingFace environment variables (GPU nodes have no internet)
export HF_HOME=/scratch/$USER/models
export TRANSFORMERS_CACHE=$HF_HOME/hub
export HF_HUB_OFFLINE=1

# Verify GPU
echo "=== GPU Check ==="
nvidia-smi --query-gpu=name,memory.total,memory.free --format=csv
echo ""

# Create output directory with timestamp
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
OUTPUT_DIR="experiments/results/rules_map_${TIMESTAMP}_job${SLURM_JOB_ID}"
mkdir -p "$OUTPUT_DIR"
mkdir -p logs

echo "=== Starting Experiment ==="
echo "Output directory: $OUTPUT_DIR"
echo ""

# SLURM copies the script to a spool directory, so BASH_SOURCE[0] is unreliable.
# Absolute path to the repo root. SLURM copies this script to a spool directory,
# making BASH_SOURCE[0] and SLURM_SUBMIT_DIR unreliable for path resolution.
# Override by setting REPO_ROOT in the environment before sbatch if the repo moves.
REPO_ROOT="${REPO_ROOT:-/home/rnegro/thesis/rule-mutation}"
cd "$REPO_ROOT"

# Ensure Python output is never buffered in SLURM log files
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

# Run the experiment with per-prompt rules
# Build optional language filter argument
LANG_ARG=""
if [ -n "$LANGUAGES" ]; then
    LANG_ARG="--languages $LANGUAGES"
fi

python scripts/experiments/run_with_rules_map.py \
    --backend local \
    --model "$MODEL_ID" \
    --quantization "$QUANTIZATION" \
    --interesting-cases "$INTERESTING_CASES" \
    --rules-map "$RULES_MAP" \
    --n-cases "$N_CASES" \
    --iterations "$N_ITERATIONS" \
    --early-stop "$EARLY_STOP" \
    --seed "$SEED" \
    --selection "$SELECTION" \
    --semgrep-config "$SEMGREP_RULESET" \
    --semgrep-timeout-seconds "$SEMGREP_TIMEOUT_SECONDS" \
    --semgrep-jobs "$SEMGREP_JOBS" \
    $LANG_ARG \
    --output-dir "$OUTPUT_DIR"

echo ""
echo "=========================================================================="
echo "Experiment Complete"
echo "=========================================================================="
echo "Finished: $(date)"
echo "Results saved to: $OUTPUT_DIR"
echo ""

# List output files
echo "=== Output Files ==="
ls -lh "$OUTPUT_DIR"
echo ""

# Show final GPU state
echo "=== Final GPU State ==="
nvidia-smi --query-gpu=name,memory.used,utilization.gpu --format=csv
