# Experiment Workflow

How to run experiments, reproduce them, and read the results. For a one-page
reproduction guide see [REPLICATION.md](REPLICATION.md); for internals see
[ARCHITECTURE.md](ARCHITECTURE.md) and [IMPLEMENTATION.md](IMPLEMENTATION.md).

The pipeline runs the same way locally on an API backend (Claude / OpenAI, no
GPU) and on a GPU host with a local model. Both write the same
`schema_version: 2` output, so the same analysis scripts read both.

---

## 1. Running experiments

The entrypoint is `scripts/experiments/run_with_rules_map.py`. Choose a backend
(`--backend`), a model (`--model`), a search strategy (`--optimizer`), and a
rule map.

### Local (API backend)

```bash
source .venv/bin/activate        # or prefix commands with `uv run`

python scripts/experiments/run_with_rules_map.py \
  --backend claude --model claude-haiku-4-5 --optimizer ea \
  --rules-map pipeline_breakdown/rule_retrieval_output/map_qwen32b_python_java.json \
  --n-cases 8 --iterations 25 \
  --archive-cap 6 --restart-h 8 --max-depth-ea 4 \
  --mutators synonym_replacement add_random_word verb_weakening \
             section_reorder_shuffle section_reorder_degrade \
             negation_injection voice_change paraphrase \
  --enable-validation --mutation-max-retries 2 \
  --languages python --seed 42 \
  --output-dir experiments/results/local_ea
```

Swap `--optimizer random_baseline` (with `--max-mutations-per-iter K`) for the
ablation. Drop `--enable-validation` to skip the quality recording.

### Choosing the model

`--backend` selects the provider; `--model` selects the model within it. If
`--model` is omitted it defaults per backend (`claude → claude-haiku-4-5`,
`openai → gpt-4o-mini`, `delftblue → Qwen2.5-Coder-32B-Instruct`). Examples:

```bash
--backend claude --model claude-sonnet-4-6      # a stronger (pricier) Anthropic model
--backend openai --model gpt-4o                  # a different OpenAI model
```

The chosen model is recorded in `run_config.json` and `hillclimb_summary_*.json`.

### Key flags

| Flag | Meaning |
|---|---|
| `--backend {claude,openai,delftblue}` | code-generation provider |
| `--model NAME` | model within the provider (default resolved per backend) |
| `--optimizer {ea,random_baseline}` | search strategy |
| `--rules-map PATH` | prompt → rule-IDs map (pre-computed maps in `pipeline_breakdown/rule_retrieval_output/`) |
| `--n-cases N`, `--languages …` | size + language filter of the prompt set |
| `--iterations T` | search budget (one code-gen call per iteration) |
| `--selection {first,random}` | take the first N cases, or a seeded random N |
| `--archive-cap`, `--restart-h`, `--max-depth-ea` | EA archive knobs |
| `--max-mutations-per-iter K` | random-baseline chain-length cap |
| `--enable-validation`, `--mutation-max-retries` | observational quality recording |
| `--seed N` | reproducibility |
| `--dry-run` | wire a mock backend (no API calls) to check the plumbing |

### DelftBlue (GPU)

The thesis runs used DelftBlue A100 nodes with a local Qwen model. The SLURM
wrapper `scripts/slurm/slurm_ea_qwen32b.sh` takes env-var overrides and calls
the same entrypoint with `--backend delftblue`:

```bash
# Smoke before any big batch
N_CASES=2 N_ITERATIONS=10 LANGUAGES=python OPTIMIZER=ea \
  sbatch --time=0:45:00 --job-name="ea_smoke" scripts/slurm/slurm_ea_qwen32b.sh

# Multi-seed batch — paired EA vs random across seeds × languages (12 jobs)
for SEED in 1 7 123; do
  for OPT in ea random_baseline; do
    for LANG in python java; do
      SEED=$SEED OPTIMIZER=$OPT N_CASES=25 N_ITERATIONS=200 LANGUAGES=$LANG SELECTION=random \
        sbatch --time=12:00:00 --job-name="${OPT}_${LANG}_s${SEED}" \
               scripts/slurm/slurm_ea_qwen32b.sh
    done
  done
done
```

GPU environment setup (CUDA torch, the offline HF model cache, the local Semgrep
rule directory) is host-specific and outside this guide; the wrapper's header
documents the env vars it reads.

---

## 2. Monitoring a run

The script logs a per-iteration line and a generation heartbeat. For a SLURM job:

```bash
squeue --me                          # queued / running
tail -f logs/<JOBID>_*.out           # live progress
```

### Did Semgrep actually run? (clean scan vs. failed scan)

A finding count of 0 can mean two very different things: the generated code is
clean, **or** Semgrep failed to run (e.g. not on PATH). They are
distinguishable because every scan writes a record to
`semgrep_debug/semgrep_debug.jsonl` with an `error` field — `null` on success,
a message on failure. This one-liner counts each:

```bash
python3 - <<'PY'
import json
recs = [json.loads(l) for l in open("experiments/results/<run>/semgrep_debug/semgrep_debug.jsonl")]
clean   = sum(r["error"] is None for r in recs)
errored = sum(r["error"] is not None for r in recs)
print(f"{clean} clean scans, {errored} errored")
PY
```

`errored == 0` means Semgrep ran on every sample (so a 0 finding count is a
genuine "clean code" result). Any errored records mean Semgrep itself failed —
the usual cause is `semgrep` not being on PATH (activate the venv / use
`uv run` / prefix `PATH="$PWD/.venv/bin:$PATH"`).

---

## 3. Reproducing a run

Every run dir has a `rerun.sh` that delegates to
`scripts/experiments/rerun_from_config.py`, which reads `run_config.json` and
dispatches by backend:

```bash
bash experiments/results/<run>/rerun.sh --print          # show the command, don't run
bash experiments/results/<run>/rerun.sh                  # reproduce as originally run
bash experiments/results/<run>/rerun.sh --output-dir experiments/results/rerun_x   # override out dir
```

API runs re-invoke the python entrypoint; DelftBlue runs map the recorded args
back to the SLURM wrapper's env vars (`--as delftblue` to force that form).

---

## 4. Understanding results

### The three objectives (all maximised, over the prompts that use the rule)

- **f1 = `total_semgrep_delta`** — extra Semgrep findings vs. baseline (primary).
- **f2 = `proportion_divergent`** — fraction of affected prompts whose generated code changed (`code_divergence > 0`).
- **f3 = `conditional_mean_divergence`** — mean code divergence among those that changed.

Higher f1 = the mutation made the LLM write more vulnerable code. f2/f3 capture
whether the mutation changed the generated code *at all* — useful when Semgrep
finds nothing but the output still shifted.

### Reading a run with the analysis toolkit

```bash
uv sync --extra dev --extra analysis     # combine extras (see the uv note in the README)

# Per run: RQ1 (per-rule + per-prompt baseline-vs-best, Wilcoxon/McNemar),
#          RQ2 (per-mutator effective rate + bootstrap CI), convergence, cost + hygiene
python scripts/analyze/analyze_run.py experiments/results/<run>

# Across runs: RQ3 (EA vs random, paired sign/Wilcoxon), multi-seed median+IQR
python scripts/analyze/compare_runs.py experiments/results/

# Validation audit (only for --enable-validation runs): per-criterion fail rate,
#   per-mutator pass rate, "what if we had gated" simulation
python scripts/analyze/validation_audit.py experiments/results/<val_run>
```

Each per-run script writes `summary.md` + CSVs + PNGs into `<run>/analysis/`.

### Quick manual peek at the trajectory

```bash
python3 - <<'PY'
import json
for l in open("experiments/results/<run>/iterations.jsonl"):
    r = json.loads(l)
    print(r["iter"], r["strategy"], "n="+str(r["chain_length"]),
          "f1="+str(r["f1"]), "acc="+str(r["accepted"]), "+".join(r["mutation_chain"]))
PY
```

---

## 5. Rate limits and partial runs

API backends can hit 429/529; a SLURM job can hit its wall-time. In both cases
the per-iteration writer appends atomically, so `iterations.jsonl` and the
already-written `intermediate/*.jsonl` are intact up to the cut-off. The run
summary and `run_config.json` are written at the very end, so a killed run may
lack them (the data is still there). To finish a shorter run, lower `--n-cases`
/ `--iterations`, or wait and re-run.

---

## 6. Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| Findings all 0 **and** `semgrep_debug` shows errored scans | `semgrep` not on PATH | activate the venv / `uv run` / `PATH="$PWD/.venv/bin:$PATH"` |
| `pytest` gone after `uv sync --extra analysis` | uv pruned the `dev` extra | `uv sync --extra dev --extra analysis` (combine extras) |
| `FileNotFoundError: project-codeguard/...` | submodule not initialised | `git submodule update --init --recursive` |
| `No matching prompts in rule mapping` | the rules map doesn't match the dataset slice | use a committed map under `pipeline_breakdown/rule_retrieval_output/` |
| `WARNING: no reference data-flows extracted` (only visible in old logs) | CodeBLEU can't parse a few prompts | harmless and **silenced by default** (root-logger filter in `composite_fitness.py`); that prompt's divergence omits the data-flow sub-score. Findings unaffected. |

---

## 7. Best practices

- **Always `--seed`.** It fixes the mutator draws and the search trajectory.
- **Smoke first.** `--dry-run` (mock backend) checks the plumbing for free; a 2-case/5-iter real smoke checks the backend + Semgrep before a big batch.
- **One run tree per (strategy, language, seed).** The analysis scripts key on `run_config.json`; keep runs in separate `--output-dir`s.
- **Check `semgrep_debug` once per new environment** (§2) to confirm Semgrep actually ran, not just that findings were 0.
