#!/bin/bash
#SBATCH --job-name="replicates"
#SBATCH --account=education-eemcs-msc-cs
#SBATCH --partition=gpu-a100
#SBATCH --time=24:00:00
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=8
#SBATCH --gpus-per-task=1
#SBATCH --mem-per-cpu=8000M

#############################################################################
# Replicate runner: load the model ONCE, run temp>0 replicates of a SINGLE
# condition under chosen seeds, for one (MODEL, LANGUAGES). One condition per
# job; choose the wall time at submission and split norules/withrules into jobs.
#
# Per-replicate results flush to replicates.jsonl (append), and per-prompt
# records (incl. generated code) to intermediate/<condtag>_seed<NNNN>.jsonl, so a
# wall-time kill only loses the in-progress replicate. Re-running with SEEDS set
# to the missing seeds resumes the same OUTPUT_DIR.
#
# Usage:
#   # No-rules / with-rules baselines (one condition each):
#   MODEL=qwen LANGUAGES=python CONDITION=norules sbatch scripts/slurm/slurm_replicates.sh
#   MODEL=qwen LANGUAGES=python CONDITION=withrules \
#       BASELINE_REF=experiments/results/<norules_run_dir> sbatch scripts/slurm/slurm_replicates.sh
#
#   # Resume only the missing seeds into an existing run dir:
#   MODEL=qwen LANGUAGES=java CONDITION=withrules SEEDS=47,48,49,50,51 \
#       OUTPUT_DIR=experiments/results/<existing_dir> sbatch scripts/slurm/slurm_replicates.sh
#
#   # Override mode (a specific EA iteration's mutated rules over its prompt subset):
#   MODEL=qwen LANGUAGES=python CONDITION_LABEL=selected_evaluation \
#       RULES_OVERRIDE_DIR=$PWD/experiments/results/<ea_run>/mutated_rules/evaluation_0042 \
#       sbatch scripts/slurm/slurm_replicates.sh
#############################################################################

set -e

MODEL=${MODEL:-qwen}                 # qwen | llama
LANGUAGES=${LANGUAGES:-python}
if [ "$LANGUAGES" != "python" ] && [ "$LANGUAGES" != "java" ]; then
    echo "ERROR: LANGUAGES must be python or java (got: $LANGUAGES)"; exit 1
fi
N_CASES=${N_CASES:-}
SELECTION=${SELECTION:-first}
TEMPERATURE=${TEMPERATURE:-0.6}
REPLICATES=${REPLICATES:-10}
SEED_BASE=${SEED_BASE:-42}
SEEDS=${SEEDS:-}                               # explicit comma list (e.g. 47,48,49) → forwards --seeds
CONDITION=${CONDITION:-}                        # norules | withrules (ignored in override mode)
BASELINE_REF=${BASELINE_REF:-}                  # prior run dir → forwards --baseline-ref
BASELINE_CONDITION=${BASELINE_CONDITION:-norules}
RULES_OVERRIDE_DIR=${RULES_OVERRIDE_DIR:-}      # set → override mode (single condition)
CONDITION_LABEL=${CONDITION_LABEL:-override}
ONLY_OVERRIDDEN=${ONLY_OVERRIDDEN:-1}           # override mode: 1 = only the iteration's affected prompts
OUTPUT_DIR=${OUTPUT_DIR:-}                       # set to an existing run dir to resume/top-up missing seeds
OUTPUT_BASE=${OUTPUT_BASE:-}
ALLOW_UNQUALIFIED_MAP=${ALLOW_UNQUALIFIED_MAP:-0}

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

# Resolve the condition tag (used for the output dir name + records).
if [ -n "$RULES_OVERRIDE_DIR" ]; then
    CONDTAG="$CONDITION_LABEL"
elif [ -n "$CONDITION" ]; then
    CONDTAG="$CONDITION"
else
    echo "ERROR: set CONDITION=norules|withrules (or RULES_OVERRIDE_DIR for override mode)"; exit 1
fi

REPO_ROOT="${REPO_ROOT:-/home/rnegro/thesis/rule-mutation}"
OUTPUT_BASE=${OUTPUT_BASE:-"$REPO_ROOT/experiments/results"}
NORULES_MAP=${NORULES_MAP:-"$REPO_ROOT/rule_maps/qualified/final_search_norules_map_${LANGUAGES}.json"}
WITHRULES_MAP=${WITHRULES_MAP:-"$REPO_ROOT/rule_maps/qualified/final_search_map_${MODEL}_${LANGUAGES}.json"}
SEMGREP_RULESET=${SEMGREP_RULESET:-/scratch/$USER/semgrep-rules/security-audit}
SEMGREP_TIMEOUT_SECONDS=${SEMGREP_TIMEOUT_SECONDS:-180}
SEMGREP_JOBS=${SEMGREP_JOBS:-4}

cd "$REPO_ROOT"
mkdir -p "$OUTPUT_BASE/slurm_logs"
exec >"$OUTPUT_BASE/slurm_logs/${SLURM_JOB_ID}_${SLURM_JOB_NAME}.out" \
     2>"$OUTPUT_BASE/slurm_logs/${SLURM_JOB_ID}_${SLURM_JOB_NAME}.err"
source "$REPO_ROOT/.venv/bin/activate"
if [ -z "$VIRTUAL_ENV" ]; then echo "ERROR: venv activation failed"; exit 1; fi

export HF_HOME=/scratch/$USER/models
export TRANSFORMERS_CACHE=$HF_HOME/hub
export HF_HUB_OFFLINE=1
export PYTHONUNBUFFERED=1

# Seed description for the banner.
if [ -n "$SEEDS" ]; then SEED_DESC="seeds=$SEEDS"; else SEED_DESC="seeds ${SEED_BASE}..$((SEED_BASE+REPLICATES-1))"; fi

echo "=========================================================================="
echo "Replicate runner: $MODEL_ID"
echo "  Language=$LANGUAGES  N_CASES=${N_CASES:-all}  T=$TEMPERATURE  condition=$CONDTAG  $SEED_DESC"
if [ -n "$RULES_OVERRIDE_DIR" ]; then echo "  Override dir=$RULES_OVERRIDE_DIR"; fi
if [ -n "$BASELINE_REF" ]; then echo "  Baseline-ref=$BASELINE_REF (cond=$BASELINE_CONDITION)"; fi
echo "  Started: $(date)  Job: $SLURM_JOB_ID  Node: $(hostname)"
echo "=========================================================================="
nvidia-smi --query-gpu=name,memory.total,memory.free --format=csv

if [ ! -e "$SEMGREP_RULESET" ]; then echo "ERROR: Semgrep rules not found: $SEMGREP_RULESET"; exit 1; fi
if [ ! -s "$SEMGREP_RULESET/SOURCE_COMMIT" ]; then
    echo "ERROR: final replicate runs require pinned Semgrep rules with SOURCE_COMMIT"; exit 1
fi

# OUTPUT_DIR may be passed in to resume an existing run; otherwise derive it.
DATE=$(date +%m%d)
TTAG="t$(echo "$TEMPERATURE" | tr -d '.')"
CTAG=$(echo "$CONDTAG" | tr -c 'a-zA-Z0-9' '_')
if [ -z "$OUTPUT_DIR" ]; then
    OUTPUT_DIR="$OUTPUT_BASE/job${SLURM_JOB_ID}_replicates_${MODEL}_${LANGUAGES}_${N_CASES:-all}_${TTAG}_r${REPLICATES}_${CTAG}_${DATE}"
fi
mkdir -p "$OUTPUT_DIR"

# Build condition + seed + baseline args.
COND_ARGS=()
if [ -n "$RULES_OVERRIDE_DIR" ]; then
    if [ ! -d "$RULES_OVERRIDE_DIR" ]; then echo "ERROR: RULES_OVERRIDE_DIR not a dir: $RULES_OVERRIDE_DIR"; exit 1; fi
    COND_ARGS=(--rules-override-dir "$RULES_OVERRIDE_DIR" --condition-label "$CONDITION_LABEL" --withrules-map "$WITHRULES_MAP")
    if [ "$ONLY_OVERRIDDEN" = "1" ]; then COND_ARGS+=(--only-overridden-prompts); fi
elif [ "$CONDITION" = "norules" ]; then
    COND_ARGS=(--condition norules --norules-map "$NORULES_MAP")
elif [ "$CONDITION" = "withrules" ]; then
    COND_ARGS=(--condition withrules --withrules-map "$WITHRULES_MAP")
else
    echo "ERROR: CONDITION must be 'norules' or 'withrules' (got: $CONDITION)"; exit 1
fi

SEED_ARGS=()
if [ -n "$SEEDS" ]; then SEED_ARGS=(--seeds "$SEEDS"); else SEED_ARGS=(--replicates "$REPLICATES" --seed-base "$SEED_BASE"); fi

BASE_ARGS=()
if [ -n "$BASELINE_REF" ]; then BASE_ARGS=(--baseline-ref "$BASELINE_REF" --baseline-condition "$BASELINE_CONDITION"); fi

CASE_ARGS=()
if [ -n "$N_CASES" ]; then CASE_ARGS=(--n-cases "$N_CASES"); fi

MAP_POLICY_ARGS=()
if [ "$ALLOW_UNQUALIFIED_MAP" = "1" ]; then MAP_POLICY_ARGS=(--allow-unqualified-map); fi

python scripts/experiments/run_replicates.py \
    --model "$MODEL_ID" \
    --quantization "$QUANTIZATION" \
    --bnb-compute-dtype "$BNB_COMPUTE_DTYPE" \
    --language "$LANGUAGES" \
    "${CASE_ARGS[@]}" \
    "${MAP_POLICY_ARGS[@]}" \
    --selection "$SELECTION" \
    --temperature "$TEMPERATURE" \
    "${SEED_ARGS[@]}" \
    "${COND_ARGS[@]}" \
    "${BASE_ARGS[@]}" \
    --semgrep-config "$SEMGREP_RULESET" \
    --semgrep-timeout-seconds "$SEMGREP_TIMEOUT_SECONDS" \
    --semgrep-jobs "$SEMGREP_JOBS" \
    --output-dir "$OUTPUT_DIR"

if [ -f "$OUTPUT_DIR/semgrep_debug/semgrep_debug.jsonl" ]; then
    timeout 250 python scripts/experiments/filter_semgrep_debug.py \
        --force --in-place --audit-json "$OUTPUT_DIR" \
        || echo "WARNING: Semgrep debug compaction incomplete; raw log retained"
fi

python scripts/analyze/validate_replicate_run.py --write "$OUTPUT_DIR"

echo "=========================================================================="
echo "Replicates complete. Output: $OUTPUT_DIR   End: $(date)"
echo "=========================================================================="
