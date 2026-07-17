# Experiment Workflow

How to run experiments, reproduce them, and read the results. For a one-page
reproduction guide see [REPLICATION.md](REPLICATION.md); for internals see
[ARCHITECTURE.md](ARCHITECTURE.md) and [IMPLEMENTATION.md](IMPLEMENTATION.md).

The pipeline runs the same way locally on an API backend (Claude / OpenAI, no
GPU) and on a GPU host with a local model. Both write the same
`schema_version: 4` output.

---

## 1. Running experiments

The entrypoint is `scripts/experiments/run_experiment.py`. Choose a backend
(`--backend`), a model (`--model`), a search strategy (`--optimizer`), and a
rule map.

### Local (API backend)

```bash
source .venv/bin/activate        # or prefix commands with `uv run`

python scripts/experiments/run_experiment.py \
  --backend claude --model claude-haiku-4-5 --optimizer ea \
  --rules-map rule_maps/map_qwen32b_python_java.json \
  --n-cases 8 --iterations 25 \
  --archive-cap 6 --restart-h 8 --max-depth 4 \
  --ea-init-samples 10 --ea-injection-every 10 --random-max-changes 10 \
  --mutators synonym_replacement add_random_word verb_weakening \
             section_reorder_shuffle section_reorder_degrade \
             negation_injection voice_change paraphrase \
  --enable-validation \
  --languages python --seed 42 \
  --output-dir experiments/results/local_ea
```

Swap `--optimizer random_search` for the i.i.d. baseline (same sampler, no
archive). `--enable-validation` is **required** on real runs (it computes the f2
rule-fidelity objective); only `--dry-run` may omit it.

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
| `--optimizer {ea,random_search}` | search strategy |
| `--objective-direction {minimize,maximize}` | `minimize` (default) = repair; `maximize` = secondary adversarial direction |
| `--rules-map PATH` | prompt → rule-IDs map (pre-computed maps in `rule_maps/`) |
| `--n-cases N`, `--languages …` | size + language filter of the prompt set |
| `--iterations T` | evaluation budget (identities retry without consuming it; wall-time bounds real runs) |
| `--selection {first,random}` | take the first N cases, or a seeded random N |
| `--archive-cap`, `--restart-h`, `--max-depth` | archive + depth-cap knobs |
| `--random-max-changes K` | shared sampler's changes-per-sample cap (default 10) |
| `--ea-init-samples`, `--ea-injection-every`, `--ea-move`, `--ea-n-mutations` | EA init/injection/move knobs |
| `--ea-origin-parent` / `--no-ea-origin-parent` | keep the origin as a sampleable local-move parent (default on) |
| `--enable-validation` | quality recording; **required** on real runs (feeds f2 fidelity) |
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

# Final repair batch — paired EA vs random over the FULL case sets
# (185 python / 114 java), seeds 42 + 43 (8 jobs). Runs are wall-time-bounded
# (SIGUSR1); N_ITERATIONS is a high soft cap. EA_INIT_SAMPLES / EA_ORIGIN_PARENT
# are EA-only (the random arm ignores them).
declare -A NCASES=( [python]=185 [java]=114 )
for SEED in 42 43; do
  for OPT in ea random_search; do
    for LANG in python java; do
      SEED=$SEED OPTIMIZER=$OPT LANGUAGES=$LANG N_CASES=${NCASES[$LANG]} \
        N_ITERATIONS=200 EA_INIT_SAMPLES=6 EA_ORIGIN_PARENT=false \
        ORDER_MOVE_WEIGHT=0.1 EA_INJECTION_EVERY=10 \
        sbatch --time=6:00:00 --job-name="${OPT}_${LANG}_s${SEED}" \
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

Reproduce any run with `scripts/experiments/rerun_from_config.py`, which reads the
run's `run_config.json` and dispatches by backend. Pass the run directory (its
`run_config.json` is found automatically) or the `run_config.json` path directly:

```bash
python scripts/experiments/rerun_from_config.py experiments/results/<run> --print          # show the command, don't run
python scripts/experiments/rerun_from_config.py experiments/results/<run>                  # reproduce as originally run
python scripts/experiments/rerun_from_config.py experiments/results/<run> --output-dir experiments/results/rerun_x   # override out dir
```

API runs re-invoke the python entrypoint; DelftBlue runs map the recorded args
back to the SLURM wrapper's env vars (`--as delftblue` to force that form).

---

## 4. Understanding results

### The three objectives (conservative set, all maximised over the whole chromosome)

- **f1 = `total_semgrep_delta`** — vulnerability reduction vs. baseline under `--objective-direction minimize` (higher = safer); the primary signal.
- **f2 = `rule_fidelity`** — mean SBERT similarity of each mutated rule to its original (1.0 = unchanged); needs `--enable-validation`.
- **f3 = `−parsimony`** — negated count of text-mutated rules (fewer edits = higher).

f1's sign depends on `objective_direction` (f1 is negated at search time so the EA always
maximises): under **minimize** (the repair runs) higher f1 = *safer* code (fewer findings);
under **maximize** (the secondary adversarial direction) higher f1 = *more vulnerable* code.
f2/f3 capture how faithfully and minimally the rule set was edited; they do not
measure generated-code change. The CodeBLEU-derived divergence fields above are
the diagnostics for whether the output shifted while Semgrep stayed flat.

### Analysis toolkit — work in progress

A set of scripts under `scripts/analyze/` (needs `--extra analysis`) turns the
raw run artifacts into figures and statistics. It is **being reworked for the
repair/chromosome design**: the research-question mapping, the specific
statistical tests, and the figure set are **not finalised**, so they are not
documented here yet and are out of scope for the current code review. Until then,
read the raw evidence directly — it is complete and stable (schema 4):

- `iterations.jsonl` — the per-iteration trajectory (objectives, phase, move, acceptance).
- `intermediate/*.jsonl` — the per-prompt evaluations (findings, generated code).
- `archive_snapshots/` — the EA Pareto archive over time.
- `hillclimb_summary_*.json` — run-level totals, mutator stats, eval-cache hygiene.

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
| `No matching prompts in rule mapping` | the rules map doesn't match the dataset slice | use a committed map under `rule_maps/` |
| `WARNING: no reference data-flows extracted` (only visible in old logs) | CodeBLEU can't parse a few prompts | harmless and **silenced by default** (root-logger filter in `composite_fitness.py`); that prompt's divergence omits the data-flow sub-score. Findings unaffected. |

---

## 7. Best practices

- **Always `--seed`.** It fixes the mutator draws and the search trajectory.
- **Smoke first.** `--dry-run` (mock backend) checks the plumbing for free; a 2-case/5-iter real smoke checks the backend + Semgrep before a big batch.
- **One run tree per (strategy, language, seed).** The analysis scripts key on `run_config.json`; keep runs in separate `--output-dir`s.
- **Check `semgrep_debug` once per new environment** (§2) to confirm Semgrep actually ran, not just that findings were 0.
