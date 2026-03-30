#!/bin/bash
#SBATCH --job-name="sbst_rules_map"
#SBATCH --account=education-eemcs-msc-cs
#SBATCH --partition=gpu-a100
#SBATCH --time=01:30:00
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
#   # Default (16 cases, 10 iterations, FP16, first selection, 1h30 wall-time)
#   sbatch scripts/slurm/slurm_rules_map_qwen32b.sh
#
#   # Validation run (4 C-language cases, 5 iterations, specific mutator)
#   N_CASES=4 N_ITERATIONS=5 MUTATOR=paraphrase LANGUAGES=c ENABLE_VALIDATION=1 \
#     sbatch --job-name="paraphrase_map" \
#            --output="/home/rnegro/thesis/rule-mutation/logs/paraphrase_%j.out" \
#            --error="/home/rnegro/thesis/rule-mutation/logs/paraphrase_%j.err" \
#            scripts/slurm/slurm_rules_map_qwen32b.sh
#
#   # Scale-up run (all languages, 2h wall-time override)
#   N_CASES=16 N_ITERATIONS=10 MUTATOR=fluff ENABLE_VALIDATION=1 \
#     sbatch --time=2:00:00 --job-name="fluff_map" \
#            --output="/home/rnegro/thesis/rule-mutation/logs/fluff_%j.out" \
#            --error="/home/rnegro/thesis/rule-mutation/logs/fluff_%j.err" \
#            scripts/slurm/slurm_rules_map_qwen32b.sh
#
#   # With 4-bit quantization (18GB VRAM, use gpu-a100-small partition)
#   QUANTIZATION=4bit sbatch scripts/slurm/slurm_rules_map_qwen32b.sh
#############################################################################

set -e  # Exit on error

# Configuration (override via environment variables before sbatch)
N_CASES=${N_CASES:-16}
N_ITERATIONS=${N_ITERATIONS:-10}
EARLY_STOP=${EARLY_STOP:-0}        # 0 = disabled; run all iterations
QUANTIZATION=${QUANTIZATION:-fp16}
SEED=${SEED:-42}
SELECTION=${SELECTION:-first}
LANGUAGES=${LANGUAGES:-}  # space-separated, e.g. "c python"; empty = all
SEMGREP_RULESET=${SEMGREP_RULESET:-/scratch/$USER/semgrep-rules/security-audit}
SEMGREP_TIMEOUT_SECONDS=${SEMGREP_TIMEOUT_SECONDS:-180}
SEMGREP_JOBS=${SEMGREP_JOBS:-1}
MUTATOR=${MUTATOR:-fluff}          # mutator name; LLM mutators require --backend local
ENABLE_VALIDATION=${ENABLE_VALIDATION:-0}   # 1 = run SBERT quality gate after each mutation
MUTATION_MAX_RETRIES=${MUTATION_MAX_RETRIES:-2}

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
echo "  Mutator: $MUTATOR"
echo "  Validation: ${ENABLE_VALIDATION} (1=enabled)"
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

# Create output directory — job ID prefix ensures sort order; date is month+day only
# (full timestamp is already captured inside run_config.json and results filenames)
DATE=$(date +%m%d)
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
OUTPUT_DIR="experiments/results/job${SLURM_JOB_ID}_${MUTATOR}_${DATE}"
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

# Build optional validation flag
VALIDATION_FLAG=""
if [ "$ENABLE_VALIDATION" = "1" ]; then
    VALIDATION_FLAG="--enable-validation --mutation-max-retries $MUTATION_MAX_RETRIES"
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
    --mutator "$MUTATOR" \
    $VALIDATION_FLAG \
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
