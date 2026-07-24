#!/bin/bash
#SBATCH --job-name="qual"
#SBATCH --account=education-eemcs-msc-cs
#SBATCH --partition=gpu-a100
#SBATCH --time=02:00:00
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=8
#SBATCH --gpus-per-task=1
#SBATCH --mem-per-cpu=8000M
#SBATCH --output=/home/rnegro/thesis/rule-mutation/logs/%j_%x.out
#SBATCH --error=/home/rnegro/thesis/rule-mutation/logs/%j_%x.err
#SBATCH --signal=B:USR1@300

set -euo pipefail

MODEL=${MODEL:-qwen}
LANGUAGES=${LANGUAGES:-python}
PROMPT_PROFILE=${PROMPT_PROFILE:-original_with_language}
REPO_ROOT=${REPO_ROOT:-/home/rnegro/thesis/rule-mutation}
OUTPUT_BASE=${OUTPUT_BASE:-experiments/qualification}
SEMGREP_RULESET=${SEMGREP_RULESET:-/scratch/$USER/semgrep-rules/security-audit}
SEMGREP_TIMEOUT_SECONDS=${SEMGREP_TIMEOUT_SECONDS:-180}
SEMGREP_JOBS=${SEMGREP_JOBS:-4}

if [ "$LANGUAGES" != "python" ] && [ "$LANGUAGES" != "java" ]; then
    echo "ERROR: LANGUAGES must be exactly python or java"; exit 1
fi
case "$PROMPT_PROFILE" in
    current_language_complete) PROFILE_TAG="current" ;;
    original_no_language) PROFILE_TAG="original_nolang" ;;
    original_with_language) PROFILE_TAG="original_lang" ;;
    *) echo "ERROR: unsupported PROMPT_PROFILE: $PROMPT_PROFILE"; exit 1 ;;
esac

if [ "$MODEL" = "qwen" ]; then
    MODEL_ID="Qwen/Qwen2.5-Coder-32B-Instruct"
    QUANTIZATION=${QUANTIZATION:-fp16}
    BNB_COMPUTE_DTYPE=${BNB_COMPUTE_DTYPE:-float16}
elif [ "$MODEL" = "llama" ]; then
    MODEL_ID="meta-llama/Llama-3.3-70B-Instruct"
    QUANTIZATION=${QUANTIZATION:-4bit}
    BNB_COMPUTE_DTYPE=${BNB_COMPUTE_DTYPE:-bfloat16}
else
    echo "ERROR: MODEL must be qwen or llama"; exit 1
fi

RULES_MAP=${RULES_MAP:-"$REPO_ROOT/rule_maps/final_consensus_map_${MODEL}_${LANGUAGES}.json"}
OUTPUT_DIR=${OUTPUT_DIR:-"$OUTPUT_BASE/job${SLURM_JOB_ID}_${MODEL}_${LANGUAGES}_${PROFILE_TAG}"}

cd "$REPO_ROOT"
source "$REPO_ROOT/.venv/bin/activate"
if [ -z "${VIRTUAL_ENV:-}" ]; then echo "ERROR: venv activation failed"; exit 1; fi

export HF_HOME=/scratch/$USER/models
export TRANSFORMERS_CACHE=$HF_HOME/hub
export HF_HUB_OFFLINE=1
export PYTHONUNBUFFERED=1

if [ ! -e "$RULES_MAP" ]; then echo "ERROR: rules map not found: $RULES_MAP"; exit 1; fi
if [ ! -e "$SEMGREP_RULESET" ]; then echo "ERROR: Semgrep rules not found: $SEMGREP_RULESET"; exit 1; fi
if [ ! -s "$SEMGREP_RULESET/SOURCE_COMMIT" ]; then
    echo "ERROR: final qualification requires pinned Semgrep rules with SOURCE_COMMIT"; exit 1
fi

mkdir -p "$OUTPUT_DIR" logs

echo "=========================================================================="
echo "Temperature-zero search-population qualification"
echo "  Model: $MODEL_ID"
echo "  Language: $LANGUAGES"
echo "  Prompt profile: $PROMPT_PROFILE"
echo "  Source map: $RULES_MAP"
echo "  Semgrep source commit: $(head -n 1 "$SEMGREP_RULESET/SOURCE_COMMIT")"
echo "  Output: $OUTPUT_DIR"
echo "  Job: $SLURM_JOB_ID  Node: $(hostname)"
echo "=========================================================================="
nvidia-smi --query-gpu=name,memory.total,memory.free --format=csv

python scripts/experiments/run_qualification.py \
    --backend delftblue \
    --model "$MODEL_ID" \
    --quantization "$QUANTIZATION" \
    --bnb-compute-dtype "$BNB_COMPUTE_DTYPE" \
    --languages "$LANGUAGES" \
    --prompt-profile "$PROMPT_PROFILE" \
    --rules-map "$RULES_MAP" \
    --semgrep-config "$SEMGREP_RULESET" \
    --semgrep-timeout-seconds "$SEMGREP_TIMEOUT_SECONDS" \
    --semgrep-jobs "$SEMGREP_JOBS" \
    --output-dir "$OUTPUT_DIR" &
PYTHON_PID=$!
trap 'echo "Forwarding SIGUSR1 to qualification process $PYTHON_PID"; kill -USR1 "$PYTHON_PID" 2>/dev/null' USR1
set +e
wait "$PYTHON_PID"
EXIT_CODE=$?
while [ "$EXIT_CODE" -gt 128 ]; do
    wait "$PYTHON_PID"
    EXIT_CODE=$?
done
set -e
trap - USR1

if [ -f "$OUTPUT_DIR/semgrep_debug/semgrep_debug.jsonl" ]; then
    timeout 250 python scripts/experiments/filter_semgrep_debug.py \
        --force --in-place --audit-json "$OUTPUT_DIR" \
        || echo "WARNING: Semgrep debug compaction incomplete; raw log retained"
fi

if [ "$EXIT_CODE" -eq 0 ]; then
    if ! python scripts/analyze/validate_qualification_run.py --write "$OUTPUT_DIR"; then
        echo "ERROR: qualification artifact validation failed"
        EXIT_CODE=3
    fi
fi

exit "$EXIT_CODE"
