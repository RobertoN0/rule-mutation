# CodeGuard SBST Framework

**Search-Based Software Testing for LLM Security-Instruction Robustness**

This MSc thesis framework studies how the **phrasing** of **[CodeGuard](https://github.com/cosai-oasis/project-codeguard) security coding guidelines** affects the security of LLM-generated code. CodeGuard rules (shipped as the `project-codeguard/` git submodule) are the natural-language security instructions given to a code-generating LLM. The framework applies **controlled mutations** to those rules — rewording, reordering, restructuring, or deliberately weakening them — and uses **Search-Based Software Testing** to find rule-set edits that lead the LLM to generate **fewer** vulnerabilities, as detected by [Semgrep](https://github.com/semgrep/semgrep). Rule fidelity is measured explicitly rather than assumed. The search direction is **repair** (minimise vulnerable generation); an adversarial direction (maximise) is retained only for secondary experiments.

---

## Quick Start

Dependencies are managed with [`uv`](https://docs.astral.sh/uv/) (Python ≥ 3.11) — one canonical lockfile, deterministic installs, identical locally and on DelftBlue.

```bash
# 1. Install uv
#    Linux / macOS (curl):
curl -LsSf https://astral.sh/uv/install.sh | sh
#    macOS (Homebrew):
brew install uv
#    Windows (PowerShell):
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"

# 2. Clone with the project-codeguard submodule (the rule library)
git clone --recurse-submodules https://github.com/RobertoN0/rule-mutation.git
cd rule-mutation

# 3. Install dependencies (creates .venv/)
uv sync --extra dev          # core + pytest/ruff for development

# 4. Verify
uv run pytest tests/unit/ -q     # the complete unit suite should pass
```

### Dependency extras

`uv sync` installs exactly the resolved set and **removes anything not in it**, so list every extra you want in one command:

```bash
uv sync --extra dev --extra analysis     # both at once — NOT two separate syncs
```

| Extra | Adds | When |
|---|---|---|
| `dev` | `pytest`, `ruff` | development + running the test suite |
| `analysis` | `scipy` | paired statistical analysis (see [Analyze results](#analyze-results)) |
| `gpu` | `accelerate`, `bitsandbytes` | quantized local inference on CUDA hosts (DelftBlue) |
| `retrieval` | `langchain`, `langgraph` | re-building the rule-retrieval map (pre-computed maps are committed) |

> **uv gotcha:** running `uv sync --extra analysis` after `uv sync --extra dev` will *uninstall* pytest/ruff, because each sync makes the venv match only the extras you named. Combine them (`--extra dev --extra analysis`) or use `uv sync --extra analysis --inexact` to keep what's already there.

---

## Reproduce locally (API backends — no GPU required)

The Phase 2 search experiment (baseline → mutate → generate → validate → Semgrep → search) runs end-to-end on any CPU machine using **Anthropic Claude** or **OpenAI** as the code-generation backend. Pick one of the two paths below.

First, set an API key:

```bash
cp .env.example .env
# edit .env — add ANTHROPIC_API_KEY (recommended) or OPENAI_API_KEY
```

### Option A — Native (`.venv`)

```bash
source .venv/bin/activate     # puts the venv's `semgrep` + `python` on PATH

    # Tiny smoke: 2 cases × (5 initialization + 2 main-loop evaluations)
python scripts/experiments/run_experiment.py \
  --backend claude --optimizer ea --enable-validation \
  --n-cases 2 --main-loop-budget 2 \
  --mutators synonym_replacement add_random_word verb_weakening \
             section_reorder_shuffle section_reorder_degrade \
  --seed 42 --languages python \
  --output-dir experiments/results/local_smoke

# Reproduce that exact run from its recorded config
python scripts/experiments/rerun_from_config.py experiments/results/local_smoke --print   # show the command
python scripts/experiments/rerun_from_config.py experiments/results/local_smoke           # actually re-run
```

> If you call `.venv/bin/python` directly instead of activating, prefix the
> command with `PATH="$PWD/.venv/bin:$PATH"` so the subprocess `semgrep` is
> found — otherwise every scan fails with "Semgrep not installed".

### Option B — Docker (sealed, API-only image)

```bash
docker build -t codeguard-sbst:replication .

# Default CMD = the Claude backend smoke test (one ~$0.0001 call)
docker run --rm --env-file .env codeguard-sbst:replication

# A tiny experiment, persisting results to the host
docker run --rm \
  --env-file .env \
  -v "$(pwd)/results:/app/results" \
  codeguard-sbst:replication \
  python scripts/experiments/run_experiment.py \
    --backend claude --optimizer random_search --enable-validation \
    --n-cases 2 --main-loop-budget 2 \
    --mutators synonym_replacement add_random_word verb_weakening \
    --seed 42 --languages python \
    --output-dir /app/results/docker_smoke
```

See [REPLICATION.md](REPLICATION.md) for the complete reviewer-facing reproduction guide (prerequisites, what gets installed, reproducibility guarantees, troubleshooting).

A run directory contains `run_config.json`, `search_summary.json`,
`evaluations.jsonl`, `archive_snapshots/` (EA only),
`intermediate/{baseline,evaluation_NNNN}.jsonl`, `mutated_rules/`,
`semgrep_debug/`, and `run.log`. The exact contract is documented in
[IMPLEMENTATION.md](IMPLEMENTATION.md#output-schema).

---

## Analyze results

Every run records the raw evidence needed for analysis — the per-evaluation
trajectory (`evaluations.jsonl`), the per-task evaluations (`intermediate/`),
the archive snapshots (EA), and the run summary. The exact fields are in
[IMPLEMENTATION.md → Output schema](IMPLEMENTATION.md#output-schema).

Use `scripts/analyze/validate_search_run.py` to reconcile each search run and
`scripts/analyze/analyze_search_runs.py` for the cross-run comparison. The
proposed primary comparison is best f1 after the same scheduler allocation;
evaluation-count and elapsed-search curves are secondary views. EA and random
search are compared by matched seed within each model and language; pooled
model/language values are descriptive only. Temperature>0 repetitions are
validated with `validate_replicate_run.py` and analyzed with
`analyze_replicates.py`.

---

## How it works

The study has two main phases and one follow-up analysis stage. Phase 1 runs
before the search and freezes the task-to-rule population. Phase 2 is the main
experiment: it searches over mutations of the mapped CodeGuard rules. Phase 3
re-evaluates selected conditions at temperature>0 for statistical analysis.

### Phase 1 — Rule retrieval and final map construction

1. **Build the source population.** Select all Python and Java tasks from
   CyberSecEval while preserving their canonical task identifiers and prompts.
2. **Audit eligibility before retrieval or generation.** Record and remove
   prompts that explicitly request a language incompatible with their dataset
   label, together with the reviewed duplicate Java task. This prospective
   filter leaves 322 Python and 227 Java tasks and does not depend on model
   behavior or Semgrep outcomes.
3. **Retrieve rules repeatedly and form a consensus.** For each model/language
   pair, run rule retrieval 20 times at temperature 0.6. These are repetitions
   of *rule selection*, not code generation. A rule is mapped to a task only
   when it appears in at least 11 of the 20 valid retrievals, which turns
   stochastic retrieval into one deterministic model-specific consensus map.
4. **Screen for positive vulnerability evidence.** For every eligible task,
   generate code at temperature 0.6 for 20 seeds under both no-rules and
   original-rules conditions with both code models. A task therefore has up to
   80 screening observations: `20 seeds × 2 models × 2 rule conditions`.
   Semgrep findings are counted only for valid target-language outputs. The
   screening report keeps three outcomes separate:
   - **observed finding** — at least one valid observation contains a Semgrep
     finding, so the task is eligible for the search;
   - **all-valid zero** — every observation is valid and no finding is observed;
   - **incomplete zero** — no finding is observed, but at least one generation
     is invalid or missing.

   The latter two classes are excluded from the search population for different
   evidential reasons. In particular, an incomplete output is never converted
   into a clean zero or described as proof that the task is safe.
5. **Qualify deterministic search execution.** Generate each positive-evidence
   task once at temperature zero with its original mapped rules for Qwen and
   Llama. Final membership requires a valid target-language output from both
   models. The cross-model intersection freezes 203 Python and 126 Java tasks,
   along with the prompt, map, model, and Semgrep provenance needed by the
   search.

> **Two different uses of temperature>0.** Phase 1 screening selects tasks for
> which vulnerability reduction is empirically observable; it tests only the
> no-rules and original-rules conditions. Phase 3 instead repeats the already
> selected baselines and search-produced chromosomes to estimate their effects
> across seeds. Phase 1 is a population-construction gate, whereas Phase 3
> supplies the final paired statistical evidence.

### Phase 2 — Search experiment

1. **Establish the baseline** by generating and scanning code under the original
   mapped rules.
2. **Build a candidate chromosome** by mutating rule text or changing rule order.
3. **Record mutation quality** using SBERT similarity, instruction adherence,
   and security-keyword retention.
4. **Generate and validate one target-language implementation** for every task.
5. **Score** valid implementations with Semgrep (raw findings primary; severity
   weighting diagnostic), then assemble whole-chromosome f1 vulnerability
   reduction, f2 mean SBERT rule fidelity, and f3 −parsimony.
6. **Optimize** with one of two search strategies (`--optimizer`)
   over **full rule-set chromosomes** (per-gene rule alleles + a global rule-order gene),
   scored on the objectives (f1 = vulnerability reduction, f2 = rule fidelity, f3 = −parsimony):
   - **`ea`** — an archive-based, steady-state EA. Five origin-based random
     candidates create the initial Pareto front. Each main-loop evaluation is
     either a periodic origin-based injection or a one-step mutation/reorder of
     a deep-copied, uniformly sampled front member. The archive is never reset.
   - **`random_search`** — independent origin-based samples, with no archive or
     carry-forward. EA and random search reuse the same precomputed five
     candidates for a matched model, language, seed, map, and prompt contract.

### Phase 3 — Temperature>0 repetitions

`scripts/experiments/run_replicates.py` evaluates one fixed condition per run:
the no-rules baseline, the original-rule baseline, or a chromosome selected
from the search. Each condition is regenerated over the approved common seed
set at the chosen nonzero temperature. The runner records prompt-level
generation validity and Semgrep results for every seed; invalid or missing
outputs remain missing observations with explicit denominators.

`scripts/analyze/analyze_replicates.py` then compares conditions on matched
seeds and on the common set of valid tasks. The no-rules/original-rules
comparison measures the effect of supplying the original CodeGuard rules, while
the original-rules/selected-chromosome comparison tests whether a search
improvement persists under stochastic generation. These repetitions occur
after search and are not charged to its initialization or main-loop budget.

### Mutation strategies

The eight operators are controlled rule-text transformations. Fidelity is
measured explicitly because some operators intentionally weaken or perturb the
instruction; the framework does not assume that every produced text is
semantically identical.

**Function-based** (deterministic, no extra model request):

| Mutator | What it does |
|---------|-------------|
| `verb_weakening` | Replaces MUST/NEVER/ALWAYS with weaker synonyms throughout prose |
| `synonym_replacement` | Substitutes nouns and verbs with WordNet synonyms |
| `add_random_word` | Inserts security-domain adjectives/adverbs before nouns and verbs |
| `section_reorder_shuffle` | Randomly permutes `##` sections; falls back to prose paragraph reordering |
| `section_reorder_degrade` | Moves the highest-scoring security section to last position (LLM recency bias) |

**LLM-based** (one extra model request per mutation, same backend as code generation):

| Mutator | What it does |
|---------|-------------|
| `negation_injection` | Inserts contradictory qualifiers before imperative security directives |
| `voice_change` | Transforms active imperatives to passive advisory form |
| `paraphrase` | Rewrites prose with weaker vocabulary; inline code masked before the LLM call |

All mutators respect the **safe-zone contract**: YAML frontmatter, fenced code blocks, and inline code are never modified. Full details of each mutator and the quality validator are in [ARCHITECTURE.md](ARCHITECTURE.md).

---

## Running real experiments

### Local, longer runs (API backends)

Scale the local smoke up by raising `--n-cases` /
`--main-loop-budget`, selecting `--optimizer ea`, and adding
`--enable-validation`. See [WORKFLOW.md](WORKFLOW.md) for patterns, cost
guidance, and result interpretation.

### DelftBlue HPC

Experiments run on A100 GPU nodes with Qwen2.5-Coder-32B-Instruct or
Llama-3.3-70B-Instruct loaded offline (`HF_HUB_OFFLINE=1`). The Qwen and Llama
wrappers take the same search env-var overrides:

```bash
# Smoke before any big batch
N_CASES=2 MAIN_LOOP_BUDGET=2 LANGUAGES=python OPTIMIZER=ea \
  sbatch --time=0:45:00 --job-name="ea_smoke" scripts/slurm/slurm_ea_qwen32b.sh

# Final repair pattern — after qualification and creation of one initialization
# bundle per model/language/seed.
: "${APPROVED_SEEDS:?space-separated seeds required}"
: "${ITERATION_BUDGET:?high safety ceiling required}"
: "${APPROVED_WALL_TIME_SECONDS:?approved seconds required}"
: "${APPROVED_SLURM_TIME:?approved SLURM time required}"
for SEED in $APPROVED_SEEDS; do
  for OPT in ea random_search; do
    for LANG in python java; do
      SEED=$SEED OPTIMIZER=$OPT LANGUAGES=$LANG N_CASES=all \
        MAIN_LOOP_BUDGET=$ITERATION_BUDGET \
        INITIALIZATION_BUNDLE="experiments/initialization/qwen_${LANG}_s${SEED}" \
        TIME_BUDGET_SECONDS=$APPROVED_WALL_TIME_SECONDS \
        PRETIMEOUT_LEAD_SECONDS=300 \
        sbatch --time="$APPROVED_SLURM_TIME" \
               --job-name="${OPT}_${LANG}_s${SEED}" \
               scripts/slurm/slurm_ea_qwen32b.sh
    done
  done
done
```

Search and replicate entrypoints check the map metadata for the final
observed-finding and cross-model temperature-zero-valid population policy. This
prevents an interim retrieval or screening map from being used as final
evidence by mistake. `--allow-unqualified-map` bypasses that check only for a
deliberate plumbing diagnostic; validators mark such a run ineligible for final
comparison.

The method uses `ARCHIVE_CAP=6`, `MAX_DEPTH=4`,
`RANDOM_MAX_CHANGES=10`, `EA_INJECTION_EVERY=10`, and
`ORDER_MOVE_WEIGHT=0.1`. Validation is enabled by default in the wrapper
because it supplies the f2 fidelity objective.

Reproduce any run with `python scripts/experiments/rerun_from_config.py <run_dir>` (backend-aware: API → python entrypoint, DelftBlue → `sbatch`). See [WORKFLOW.md](WORKFLOW.md) for the full DelftBlue round-trip.

---

## Project layout

```
├── src/
│   ├── mutation/          # 8 mutators + MutatorPool + MutationQualityValidator + ParsedRule
│   ├── optimizer/         # chromosome + single Pareto archive (chromosome.py), EA + i.i.d. random-search runners (search.py)
│   │                      #   + shared random sampler; ExperimentEngine orchestration (engine.py)
│   ├── evaluation/        # Output qualification/normalization, population qualification, Semgrep, fitness
│   ├── llm_backends/      # Claude / OpenAI / DelftBlue-local backends
│   └── retrieval/         # Phase 1: task → CodeGuard-rule map builders (local + Anthropic; [retrieval] extra)
├── scripts/
│   ├── experiments/       # run_experiment.py, rerun_from_config.py, Semgrep-debug filter
│   ├── slurm/             # Qwen/Llama search launchers + final retrieval launcher
│   └── analyze/           # run validators and final search/replicate analysis
├── tests/unit/            # unit and integration-contract tests
├── project-codeguard/     # CodeGuard security rule library (git submodule)
├── rule_maps/             # Source-population audit + final maps under qualified/
├── experiments/results/   # Experiment outputs (gitignored)
├── Dockerfile             # API-only replication image
├── ARCHITECTURE.md        # Technical reference (modules, schema, extension points)
├── WORKFLOW.md            # Running experiments + DelftBlue round-trip + result interpretation
└── REPLICATION.md         # Reviewer-facing reproduction guide
```

---

## Datasets and rules

- **CyberSecEval** (Meta AI) — code-generation prompts across Python, C, Java, JavaScript, PHP, covering many CWE types. Fetched from the HuggingFace Hub at runtime.
- **CodeGuard** — the security rule library in the [`project-codeguard/`](project-codeguard/skills/software-security/rules/) submodule. Each rule is a Markdown document (YAML frontmatter + prose + code examples) covering input validation, cryptography, authentication, API security, logging, client-side web security, and more.
---

## Documentation

| Document | Contents |
|----------|----------|
| [REPLICATION.md](REPLICATION.md) | Reviewer reproduction (API-only): prerequisites → smoke → reproducibility guarantees |
| [ARCHITECTURE.md](ARCHITECTURE.md) | High-level design: the pipeline, the two search strategies, the fitness model, data flow |
| [IMPLEMENTATION.md](IMPLEMENTATION.md) | Module-by-module reference, output schema, extension points, dependencies |
| [WORKFLOW.md](WORKFLOW.md) | Running experiments, result interpretation |
