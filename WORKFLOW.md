# Experiment Workflow

How to run experiments, reproduce them, and read the results. For a one-page
reproduction guide see [REPLICATION.md](REPLICATION.md); for internals see
[ARCHITECTURE.md](ARCHITECTURE.md) and [IMPLEMENTATION.md](IMPLEMENTATION.md).

The main experiment has a prerequisite phase and a search phase. **Phase 1**
retrieves the CodeGuard rules relevant to each benchmark task and freezes the
final task-to-rule maps. **Phase 2** is the main search experiment over
mutations of those mapped rules. **Phase 3** is a follow-up replicate stage for
selected fixed configurations; it is not part of the search budget. The Phase
2 workflow runs the same way locally on an API backend (Claude / OpenAI, no
GPU) and on a GPU host with a local model. Both write the same unnumbered search
artifact contract.

---

## Phase 1 — Build and freeze the task-to-rule maps

The current maps are built with the task-delimited retrieval request implemented
in `src/retrieval/rule_retrieval_mapping.py`. The DelftBlue launcher is
`scripts/slurm/slurm_rule_retrieval.sh`. Repeated retrievals are
validated against their exact task carrier and retrieval contract, then
aggregated into one 11-of-20 consensus map per model and language. Before
qualification:

1. apply the reviewed, outcome-independent eligibility manifest;
2. screen the remaining tasks at temperature 0.6 under both no-rules and
   original-rules conditions for Qwen and Llama over seeds 1–20;
3. distinguish tasks with at least one observed finding, tasks whose 80
   observations are all valid and zero, and zero-finding tasks with incomplete
   observations;
4. carry the observed-finding and incomplete-evidence superset into
   temperature-zero qualification so incomplete outputs remain explicit;
5. admit only observed-finding tasks that are valid at temperature zero for
   both models into the final search population.

The active utilities for these gates are:

- `scripts/setup/materialize_retrieval_consensus.py`;
- `scripts/setup/materialize_eligible_population.py`;
- `scripts/analyze/analyze_population_screening.py`.

Each utility validates its source hashes, task identity and order, model,
generation contract, seed block, and per-task evidence before writing a
derived map. The completed funnel is 351 Python/229 Java source tasks, 322/227
eligible tasks, 206/128 tasks with an observed finding, and 203/126 final
cross-model-valid search tasks.

Steps 1–5 above are the single admission rule recorded in every qualified map
and in `final_search_population_manifest.json` as

```
"policy": "observed_finding_cross_model_temp0_intersection"
```

Read it as: *observed finding* — the task produced at least one Semgrep finding
somewhere in the temperature-0.6 screening block, so it can actually be improved
or degraded; *cross model* — it qualified for **both** Qwen and Llama, so the
two models search the identical task set; *temp0 intersection* — qualification
was judged at temperature 0, the same setting the search runs at. The string is
the only accepted value in `src/evaluation/population_screening.py`, and
`scripts/analyze/validate_qualified_maps.py` rejects any map that declares
something else, so a map built under a different rule cannot silently enter a
final run.

Before Phase 2, run exactly four complete temperature-zero search-population
qualification jobs. These jobs test whether the original mapped rules produce a
valid implementation for every task; they do not perform search. Qualification
must use the complete maps without case subsampling and the fixed
code-generation prompt, which explicitly states the required language. Before
submission, manually verify that the intended
commit and inputs are present:

```bash
MODEL=qwen  LANGUAGES=python RULES_MAP=<screened-qwen-python-map> \
  sbatch --time=02:00:00 scripts/slurm/slurm_qualification.sh
MODEL=qwen  LANGUAGES=java RULES_MAP=<screened-qwen-java-map> \
  sbatch --time=02:00:00 scripts/slurm/slurm_qualification.sh
MODEL=llama LANGUAGES=python RULES_MAP=<screened-llama-python-map> \
  sbatch --time=02:00:00 scripts/slurm/slurm_qualification.sh
MODEL=llama LANGUAGES=java RULES_MAP=<screened-llama-java-map> \
  sbatch --time=02:00:00 scripts/slurm/slurm_qualification.sh
```

Each wrapper writes `qualification_validation.json`; all four results must be
`VALID`. Then materialize the shared model intersection:

```bash
python scripts/setup/materialize_qualified_search_maps.py \
  --qwen-python-manifest experiments/qualification/<qwen-py>/qualification_manifest.json \
  --qwen-java-manifest experiments/qualification/<qwen-java>/qualification_manifest.json \
  --llama-python-manifest experiments/qualification/<llama-py>/qualification_manifest.json \
  --llama-java-manifest experiments/qualification/<llama-ja>/qualification_manifest.json \
  --map-dir <screened-map-directory>

python scripts/analyze/validate_qualified_maps.py rule_maps/qualified
```

Inspect the generated `rule_maps/qualified/` maps and population manifest before
Phase 2, and commit them before final runs. Final searches use `N_CASES=all` and
`SELECTION=first`, preserving the frozen task order and population fingerprint.
The no-rules maps are also language-specific; use those maps rather than
filtering a combined map at runtime.

---

## Phase 2 — Run the search experiment

The entrypoint is `scripts/experiments/run_experiment.py`. Choose a backend
(`--backend`), a model (`--model`), a search strategy (`--optimizer`), and a
rule map.

### Prepare the shared initialization

For each final `(model, language, seed)` combination, evaluate the five initial
candidates once by running either optimizer with `MAIN_LOOP_BUDGET=0`. Validate
that source run, then create a self-contained bundle:

```bash
python scripts/setup/materialize_initialization_bundle.py \
  experiments/results/<five-candidate-source-run> \
  experiments/initialization/<model>_<language>_s<seed>
```

The bundle is keyed by the exact Git commit, model revision, prompt contract,
qualified map and population, rule corpus, mutators, seed, validator settings,
and Semgrep provenance. It also checkpoints the search, mutator, and Torch RNG
streams and the evaluation cache. A mismatch rejects reuse. Pass the resulting
directory through `--initialization-bundle` locally or
`INITIALIZATION_BUNDLE` in the SLURM wrapper.

### Local (API backend)

```bash
source .venv/bin/activate        # or prefix commands with `uv run`

python scripts/experiments/run_experiment.py \
  --backend claude --model claude-haiku-4-5 --optimizer ea \
  --rules-map rule_maps/qualified/final_search_map_qwen_python.json \
  --n-cases 8 --main-loop-budget 25 \
  --archive-cap 6 --max-depth 4 \
  --ea-injection-every 10 --random-max-changes 10 \
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

The chosen model and resolved model revision are recorded in `run_config.json`;
run-level outcomes are in `search_summary.json`.

### Key flags

| Flag | Meaning |
|---|---|
| `--backend {claude,openai,delftblue}` | code-generation provider |
| `--model NAME` | model within the provider (default resolved per backend) |
| `--optimizer {ea,random_search}` | search strategy |
| `--objective-direction {minimize,maximize}` | `minimize` (default) = repair; `maximize` = secondary adversarial direction |
| `--rules-map PATH` | prompt → rule-IDs map (pre-computed maps in `rule_maps/`) |
| `--n-cases N`, `--languages …` | size + language filter of the prompt set |
| `--main-loop-budget B` | safety ceiling after the shared five-candidate initialization; identities do not consume an evaluation |
| `--initialization-bundle PATH` | reuse the strictly keyed five-candidate prefix |
| `--wall-time-budget-seconds S` | declared scheduler allocation; the final common value is frozen after supervisor approval |
| `--selection {first,random}` | take the first N cases, or a seeded random N |
| `--archive-cap`, `--max-depth` | archive and per-rule depth cap |
| `--random-max-changes K` | shared sampler's changes-per-sample cap (default 10) |
| `--ea-injection-every N` | inject an origin-based random candidate every N main-loop evaluations |
| `--order-move-weight P` | reorder probability; mutate probability is `1-P` |
| `--enable-validation` | quality recording; **required** on real runs (feeds f2 fidelity) |
| `--seed N` | reproducibility |
| `--dry-run` | wire a mock backend (no API calls) to check the plumbing |

### DelftBlue (GPU)

The thesis runs use DelftBlue A100 nodes with local Qwen and Llama models. The
model-specific wrappers take the same search overrides and call the common
entrypoint with `--backend delftblue`:

```bash
# Smoke before any big batch
N_CASES=2 MAIN_LOOP_BUDGET=2 LANGUAGES=python OPTIMIZER=ea \
  sbatch --time=0:45:00 --job-name="ea_smoke" scripts/slurm/slurm_ea_qwen32b.sh

# Final repair pattern. N_CASES=all is the frozen qualified population.
: "${APPROVED_SEEDS:?space-separated seeds required}"
: "${EVALUATION_CEILING:?high safety ceiling required}"
: "${APPROVED_WALL_TIME_SECONDS:?approved seconds required}"
: "${APPROVED_SLURM_TIME:?approved SLURM time required}"
for SEED in $APPROVED_SEEDS; do
  for OPT in ea random_search; do
    for LANG in python java; do
      SEED=$SEED OPTIMIZER=$OPT LANGUAGES=$LANG N_CASES=all \
        MAIN_LOOP_BUDGET=$EVALUATION_CEILING \
        INITIALIZATION_BUNDLE="experiments/initialization/qwen_${LANG}_s${SEED}" \
        TIME_BUDGET_SECONDS=$APPROVED_WALL_TIME_SECONDS \
        sbatch --time="$APPROVED_SLURM_TIME" \
               --job-name="${OPT}_${LANG}_s${SEED}" \
               scripts/slurm/slurm_ea_qwen32b.sh
    done
  done
done
```

### Stopping condition on DelftBlue: wall time, not iterations

A final GPU run is bounded by **`sbatch --time`**, not by an evaluation count.
`MAIN_LOOP_BUDGET` is deliberately set to a ceiling high enough never to bind,
so both arms spend the same allocation and are compared on what they achieved
within it. Four settings look like budgets; only the first two affect when a
run actually stops.

| Setting | What it actually does |
|---|---|
| `sbatch --time=HH:MM:SS` | **The real budget.** SLURM kills the job here. |
| `#SBATCH --signal=B:USR1@<lead>` | **The real stop trigger.** SLURM sends SIGUSR1 `<lead>` seconds before that kill. |
| `MAIN_LOOP_BUDGET` / `--main-loop-budget B` | Safety ceiling on evaluations (`E = 5 + B`). Set high; if it binds, the run ended early and the pair is not time-matched. |
| `TIME_BUDGET_SECONDS` / `--wall-time-budget-seconds S` | **Declares the allocation; stops nothing.** No code in `src/` reads it. It is recorded in `run_config.json` so the analyzer can refuse to pool runs that declared different allocations, and so the validator can check the lead is below it. Set it to the same number of seconds as `--time`. |

**`TIME_BUDGET_SECONDS` is not optional on a final run.** It stops nothing, but
`validate_search_run.py` marks a run `final_search_eligible` only when *all* of
these hold, and a missing or zero budget fails the fourth:

- the validator found no issues, and the map is not a diagnostic override;
- `termination_reason == "wall_time_limit"`;
- completion state is `partial` — a run that *finished* its evaluation ceiling
  did not spend its allocation and is not time-comparable;
- `wall_time_budget_seconds` is a positive integer;
- exactly five initialization evaluations are present;
- `n_cases` equals the full map population (`N_CASES=all`).

The stop path is: SLURM raises SIGUSR1 → the batch shell's `trap` forwards it to
Python → `install_pretimeout_handler` flips a flag → the optimizer tests that
flag at the top of each main-loop iteration and before each prompt's generation
→ `WallTimeStop` aborts the in-flight evaluation → Python writes its final
archive snapshot and `search_summary.json` → the wrapper then filters
`semgrep_debug` and runs the validator. There is no internal timer anywhere in
the search; nothing is checked against the clock until the
signal arrives. Every final arm run therefore ends with
`"termination_reason": "wall_time_limit"`, and the discarded in-flight
evaluation is why the validator tolerates a small code-generation-call surplus
on aborted runs.

**Sizing the lead.** SLURM may deliver the signal up to 60 s *earlier* than
asked but never later, so `<lead>` is the guaranteed floor on the shutdown
budget. Measured end-to-end on job `10526272`, which stopped gracefully and
validated cleanly:

| stage | measured | bound |
|---|---|---|
| abort the in-flight evaluation + write artifacts | 294 s | see below |
| `semgrep_debug` filter | 1 s (17–18 s at full population) | `timeout 250` |
| in-job validator | 231 s (≈190–230 s, roughly independent of run length) | `timeout 600` |
| **total** | **526 s** | |

The first row is the one to watch, and it is *not* the discarded generation —
that aborts within one prompt. It is the **candidate proposal**: mutating rules
through the mutation LLM and scoring them with SBERT happens *before* the
generation loop and has no stop check, so a signal landing there runs to
completion. `10526272` was caught during an injection proposal that mutated 9
rules. The worst case is `K = 10` LLM mutations; it does not grow with
population size.

The wrappers therefore default to **1800 s** — about 3.4× the measured total,
2% of a 24 h allocation, and identical in both arms so it cancels in the paired
comparison. Note also that only the *first* row is irreplaceable: once Python
exits, the run is safe on disk and both the filter and the validator can be
re-run on a login node, which is why the validator is capped rather than allowed
to run the job into its SIGKILL. Every run that receives the signal prints its
own measurement:

```bash
grep -r PRETIMEOUT_FINALIZE_SECONDS "$OUTPUT_BASE/slurm_logs/"
# ⏱️  PRETIMEOUT_FINALIZE_SECONDS(total)=526 search_stop_and_write=294 \
#     semgrep_debug_filter=1 validator=231 lead=1800
```

Re-derive the lead from those numbers rather than guessing it. If any run's
`total` approaches the lead, raise the lead before the next batch.

> Log locations: the wrappers `exec`-redirect after the GPU check, so `logs/`
> holds only each job's header and `<OUTPUT_BASE>/slurm_logs/<jobid>_<name>.{out,err}`
> holds the rest. The run's own `run.log` inside the result directory is the
> Python-side tee of the same stream.

GPU environment setup for a **new** DelftBlue account (CUDA torch, the offline
HF model cache, the local Semgrep rule directory) is in
[REPLICATION.md → GPU host](REPLICATION.md#gpu-host-delftblue--cuda); the
wrapper's header documents the env vars it reads.

---

### Monitoring a run

The script logs each proposal/evaluation and a generation heartbeat. For a SLURM job:

```bash
squeue --me                          # queued / running
tail -f experiments/results/slurm_logs/<JOBID>_*.out
```

### Did Semgrep actually run? (clean scan vs. failed scan)

A finding count of 0 is accepted only when Semgrep completed successfully.
Runs abort when Semgrep has a configuration, process, or other
system-wide failure. If only one task has invalid generated code or a
target-analysis error, that task is explicitly excluded during Phase 1 or given
its own baseline score during candidate evaluation; neither case is recorded as
a clean zero. Every scan still writes a record to
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

`errored == 0` means Semgrep ran on every sample (so a recorded zero is a
genuine clean-code result). Any errored records must reconcile with explicit
task-level failure records or a fatal run error; the usual systemic cause is
`semgrep` not being on PATH (activate the venv / use `uv run` / prefix
`PATH="$PWD/.venv/bin:$PATH"`).

---

## Phase 3 — Replicate selected fixed configurations

After selecting conditions from Phase 2, use
`scripts/experiments/run_replicates.py` through
`scripts/slurm/slurm_replicates.sh` to rerun no-rules, original-rules, or one
selected chromosome at temperature greater than zero. One job evaluates one
model, language, and condition over the declared seeds:

```bash
MODEL=qwen LANGUAGES=python CONDITION=norules \
  sbatch scripts/slurm/slurm_replicates.sh

MODEL=qwen LANGUAGES=python CONDITION=withrules \
  BASELINE_REF=experiments/results/<norules-run> \
  sbatch scripts/slurm/slurm_replicates.sh
```

For a selected chromosome, set `RULES_OVERRIDE_DIR` to its
`mutated_rules/evaluation_NNNN/` directory and give it a stable
`CONDITION_LABEL`. Validate every run with `validate_replicate_run.py`; then
analyze the complete matrix with `analyze_replicates.py`. Invalid stochastic
outputs are missing observations rather than clean zero-finding outputs, and
paired task effects are reduced to one effect per seed before inference.

---

## Reproducing a run

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

## Understanding results

### The three objectives (conservative set, all maximised over the whole chromosome)

- **f1 = `total_raw_reduction`** — raw Semgrep-finding reduction vs. baseline under `--objective-direction minimize` (higher = safer); the primary signal.
- **f2 = `rule_fidelity`** — mean SBERT similarity of each mutated rule to its original (1.0 = unchanged); needs `--enable-validation`.
- **f3 = `−parsimony`** — negated count of text-mutated rules (fewer edits = higher).

f1's sign depends on `objective_direction` (f1 is negated at search time so the EA always
maximises): under **minimize** (the repair runs) higher f1 = *safer* code (fewer findings);
under **maximize** (the secondary adversarial direction) higher f1 = *more vulnerable* code.
f2/f3 capture how faithfully and minimally the rule set was edited. The
severity-weighted reduction is reported separately and does not drive search.

### Analysis and validation

Run the per-run validator after each completed search and again after syncing:

```bash
python scripts/analyze/validate_search_run.py --write <run_dir>
```

Analyze a validated matrix with:

```bash
python scripts/analyze/analyze_search_runs.py \
  --output-dir analysis_output/search <run_dir>...
```

The main artifacts are:

- `evaluations.jsonl` — candidate attempts and completed evaluations.
- `intermediate/*.jsonl` — the per-prompt evaluations (findings, generated code).
- `archive_snapshots/` — the EA Pareto archive over time.
- `search_summary.json` — termination, runtime, LLM usage, mutator statistics,
  and evaluation-cache accounting.

### Quick manual peek at the trajectory

```bash
python3 - <<'PY'
import json
for l in open("experiments/results/<run>/evaluations.jsonl"):
    r = json.loads(l)
    print(r["evaluation_index"], r["strategy"], "n="+str(r["chain_length"]),
          "f1="+str(r["f1"]), "acc="+str(r["accepted"]), "+".join(r["mutation_chain"]))
PY
```

---

## Rate limits and partial runs

API backends can hit 429/529; a SLURM job can hit its wall-time. In both cases
the per-evaluation writer appends atomically, so `evaluations.jsonl` and the
already-written `intermediate/*.jsonl` are intact up to the cut-off. The run
summary is written at the end; `run_config.json` is written before model/scanner
preflight, so a failed run still has provenance. To finish a shorter run, lower `--n-cases`
/ `--main-loop-budget`, or wait and re-run.

---

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| Findings all 0 **and** `semgrep_debug` shows errored scans | `semgrep` not on PATH | activate the venv / `uv run` / `PATH="$PWD/.venv/bin:$PATH"` |
| `pytest` gone after `uv sync --extra analysis` | uv pruned the `dev` extra | `uv sync --extra dev --extra analysis` (combine extras) |
| `FileNotFoundError: project-codeguard/...` | submodule not initialised | `git submodule update --init --recursive` |
| `No matching prompts in rule mapping` | the rules map doesn't match the dataset slice | use a committed map under `rule_maps/` |

---

## Best practices

- **Always `--seed`.** It fixes the mutator draws and the search trajectory.
- **Smoke first.** `--dry-run` (mock backend) checks the plumbing for free; a
  two-case run with five initialization and two main-loop evaluations checks
  the backend and Semgrep before a large batch.
- **One run tree per (strategy, language, seed).** The analysis scripts key on `run_config.json`; keep runs in separate `--output-dir`s.
- **Check `semgrep_debug` once per new environment** (§2) to confirm Semgrep actually ran, not just that findings were 0.
