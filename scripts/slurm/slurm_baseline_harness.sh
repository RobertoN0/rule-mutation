#!/bin/bash
#SBATCH --job-name="bh"
#SBATCH --account=education-eemcs-msc-cs
#SBATCH --partition=gpu-a100
#SBATCH --time=24:00:00
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=8
#SBATCH --gpus-per-task=1
#SBATCH --mem-per-cpu=8000M
#SBATCH --output=/home/rnegro/thesis/rule-mutation/logs/%j_%x.out
#SBATCH --error=/home/rnegro/thesis/rule-mutation/logs/%j_%x.err

#############################################################################
# Baseline harness: load the model ONCE, run REPLICATES temp>0 iteration-0
# passes over BOTH conditions (norules + withrules) for one (MODEL, LANGUAGES).
# Replaces the per-seed one-pass jobs that stall under the 1-GPU cap.
#
# Per-replicate results are flushed to baseline_replicates.jsonl, so a wall-time
# kill only loses the in-progress replicate (earlier ones are safe).
#
# Usage (set --time to match the estimate for the model/lang):
#   MODEL=qwen  LANGUAGES=python N_CASES=351 sbatch --time=24:00:00 --job-name=bh_qwen_py  scripts/slurm/slurm_baseline_harness.sh
#   MODEL=qwen  LANGUAGES=java   N_CASES=229 sbatch --time=16:00:00 --job-name=bh_qwen_ja  scripts/slurm/slurm_baseline_harness.sh
#   MODEL=llama LANGUAGES=python N_CASES=351 sbatch --time=47:00:00 --job-name=bh_llama_py scripts/slurm/slurm_baseline_harness.sh
#   MODEL=llama LANGUAGES=java   N_CASES=229 sbatch --time=30:00:00 --job-name=bh_llama_ja scripts/slurm/slurm_baseline_harness.sh
#############################################################################

set -e

MODEL=${MODEL:-qwen}                 # qwen | llama
LANGUAGES=${LANGUAGES:-python}
N_CASES=${N_CASES:-351}
SELECTION=${SELECTION:-random}
TEMPERATURE=${TEMPERATURE:-0.6}
REPLICATES=${REPLICATES:-10}
SEED_BASE=${SEED_BASE:-42}

if [ "$MODEL" = "qwen" ]; then
    MODEL_ID="Qwen/Qwen2.5-Coder-32B-Instruct"
    QUANTIZATION=${QUANTIZATION:-fp16}
    BNB_COMPUTE_DTYPE=${BNB_COMPUTE_DTYPE:-float16}
elif [ "$MODEL" = "llama" ]; then
    MODEL_ID="meta-llama/Llama-3.3-70B-Instruct"
    QUANTIZATION=${QUANTIZATION:-4bit}
    BNB_COMPUTE_DTYPE=${BNB_COMPUTE_DTYPE:-bfloat16}
else
    echo "ERROR: MODEL must be 'qwen' or 'llama' (got: $MODEL)"; exit 1
fi

REPO_ROOT="${REPO_ROOT:-/home/rnegro/thesis/rule-mutation}"
NORULES_MAP="$REPO_ROOT/rule_maps/map_no_rules_python_java.json"
WITHRULES_MAP="$REPO_ROOT/rule_maps/map_qwen32b_python_java.json"
SEMGREP_RULESET=${SEMGREP_RULESET:-/scratch/$USER/semgrep-rules/security-audit}
SEMGREP_TIMEOUT_SECONDS=${SEMGREP_TIMEOUT_SECONDS:-180}
SEMGREP_JOBS=${SEMGREP_JOBS:-4}

cd "$REPO_ROOT"
source "$REPO_ROOT/.venv/bin/activate"
if [ -z "$VIRTUAL_ENV" ]; then echo "ERROR: venv activation failed"; exit 1; fi

export HF_HOME=/scratch/$USER/models
export TRANSFORMERS_CACHE=$HF_HOME/hub
export HF_HUB_OFFLINE=1
export PYTHONUNBUFFERED=1

echo "=========================================================================="
echo "Baseline Harness: $MODEL_ID"
echo "  Language=$LANGUAGES  N_CASES=$N_CASES  T=$TEMPERATURE  replicates=$REPLICATES (seeds ${SEED_BASE}..$((SEED_BASE+REPLICATES-1)))"
echo "  Conditions: norules + withrules (one model load)"
echo "  Started: $(date)  Job: $SLURM_JOB_ID  Node: $(hostname)"
echo "=========================================================================="
nvidia-smi --query-gpu=name,memory.total,memory.free --format=csv

if [ ! -e "$SEMGREP_RULESET" ]; then echo "ERROR: Semgrep rules not found: $SEMGREP_RULESET"; exit 1; fi

DATE=$(date +%m%d)
TTAG="t$(echo "$TEMPERATURE" | tr -d '.')"
OUTPUT_DIR="experiments/results/job${SLURM_JOB_ID}_harness_${MODEL}_${LANGUAGES}_${N_CASES}_${TTAG}_r${REPLICATES}_${DATE}"
mkdir -p "$OUTPUT_DIR" logs

python scripts/experiments/baseline_harness.py \
    --model "$MODEL_ID" \
    --quantization "$QUANTIZATION" \
    --bnb-compute-dtype "$BNB_COMPUTE_DTYPE" \
    --language "$LANGUAGES" \
    --n-cases "$N_CASES" \
    --selection "$SELECTION" \
    --temperature "$TEMPERATURE" \
    --replicates "$REPLICATES" \
    --seed-base "$SEED_BASE" \
    --norules-map "$NORULES_MAP" \
    --withrules-map "$WITHRULES_MAP" \
    --semgrep-config "$SEMGREP_RULESET" \
    --semgrep-timeout-seconds "$SEMGREP_TIMEOUT_SECONDS" \
    --semgrep-jobs "$SEMGREP_JOBS" \
    --output-dir "$OUTPUT_DIR"

echo "=========================================================================="
echo "Harness complete. Output: $OUTPUT_DIR   End: $(date)"
echo "=========================================================================="
