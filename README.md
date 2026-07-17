# CodeGuard SBST Framework

**Search-Based Software Testing for LLM Security-Instruction Robustness**

This MSc thesis framework studies how the **phrasing** of **[CodeGuard](https://github.com/cosai-oasis/project-codeguard) security coding guidelines** affects the security of LLM-generated code. CodeGuard rules (shipped as the `project-codeguard/` git submodule) are the natural-language security instructions given to a code-generating LLM. The framework applies **semantics-preserving mutations** to those rules — rewording, reordering, or restructuring them — and uses **Search-Based Software Testing** to find rule-set edits that lead the LLM to generate **fewer** vulnerabilities, as detected by [Semgrep](https://github.com/semgrep/semgrep). The search direction is **repair** (minimise vulnerable generation); an adversarial direction (maximise) is retained only for secondary experiments.

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
uv run pytest tests/unit/ -q     # should report "230 passed"
```

### Dependency extras

`uv sync` installs exactly the resolved set and **removes anything not in it**, so list every extra you want in one command:

```bash
uv sync --extra dev --extra analysis     # both at once — NOT two separate syncs
```

| Extra | Adds | When |
|---|---|---|
| `dev` | `pytest`, `ruff` | development + running the test suite |
| `analysis` | `matplotlib`, `scipy` | generating report figures locally (see [Analyze results](#analyze-results)) |
| `gpu` | `accelerate`, `bitsandbytes` | quantized local inference on CUDA hosts (DelftBlue) |
| `retrieval` | `langchain`, `langgraph` | re-building the rule-retrieval map (pre-computed maps are committed) |

> **uv gotcha:** running `uv sync --extra analysis` after `uv sync --extra dev` will *uninstall* pytest/ruff, because each sync makes the venv match only the extras you named. Combine them (`--extra dev --extra analysis`) or use `uv sync --extra analysis --inexact` to keep what's already there.

---

## Reproduce locally (API backends — no GPU required)

The pipeline (mutate → generate → Semgrep → CodeBLEU → optional validation) runs end-to-end on any CPU machine using **Anthropic Claude** or **OpenAI** as the code-generation backend. Pick one of the two paths below.

First, set an API key:

```bash
cp .env.example .env
# edit .env — add ANTHROPIC_API_KEY (recommended) or OPENAI_API_KEY
```

### Option A — Native (`.venv`)

```bash
source .venv/bin/activate     # puts the venv's `semgrep` + `python` on PATH

# Tiny smoke (≈ $0.10 with claude-haiku-4-5): 2 cases × 5 iterations
python scripts/experiments/run_experiment.py \
  --backend claude --optimizer ea --enable-validation \
  --n-cases 2 --iterations 5 \
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
    --n-cases 2 --iterations 3 \
    --mutators synonym_replacement add_random_word verb_weakening \
    --seed 42 --languages python \
    --output-dir /app/results/docker_smoke
```

See [REPLICATION.md](REPLICATION.md) for the complete reviewer-facing reproduction guide (prerequisites, what gets installed, reproducibility guarantees, troubleshooting).

A run directory contains: `run_config.json`, `hillclimb_summary_*.json`, `iterations.jsonl`, `archive_snapshots/` (EA only), `intermediate/{baseline,…}.jsonl`, `mutated_rules/iterNNN/`, `semgrep_debug/`, and `run.log`. The exact schema is documented in [IMPLEMENTATION.md](IMPLEMENTATION.md#output-schema).

---

## Analyze results

Every run records the raw evidence needed for analysis — the per-iteration
trajectory (`iterations.jsonl`), the per-prompt evaluations (`intermediate/`),
the archive snapshots (EA), and the run summary. The exact fields are in
[IMPLEMENTATION.md → Output schema](IMPLEMENTATION.md#output-schema).

> **Analysis toolkit — work in progress.** A set of scripts under
> `scripts/analyze/` (needs the `analysis` extra: `matplotlib`, `scipy`) is being
> reworked for the repair/chromosome design. Its figures, statistics, and the
> research-question mapping are **not yet finalised** and are out of scope for the
> current code review; they will be documented here once stable.

---

## How it works

1. **Select** test prompts from CyberSecEval.
2. **Map** relevant CodeGuard rules to each prompt via AI-based retrieval (or use pre-computed maps in `rule_maps/`).
3. **Mutate** rules in the chromosome with one of 8 semantics-preserving strategies.
4. **Validate** mutation quality (SBERT similarity, instruction adherence, security-keyword retention).
5. **Generate** code with the configured backend on the original vs. mutated rule — Qwen2.5-Coder-32B-Instruct on DelftBlue, or Claude / OpenAI locally.
6. **Score** each prompt with Semgrep (and record CodeBLEU as a diagnostic), then
   assemble whole-chromosome f1 vulnerability reduction, f2 mean SBERT rule
   fidelity, and f3 −parsimony.
7. **Optimize** with one of two interchangeable search strategies (`--optimizer`)
   over **full rule-set chromosomes** (per-gene rule alleles + a global rule-order gene),
   scored on the conservative objectives (f1 = vulnerability reduction, f2 = rule fidelity, f3 = −parsimony):
   - **`ea`** — a (1+1) EA over a single **Pareto archive of full chromosomes**, seeded with 10 random samples from the origin and topped up by a periodic random injection; each local move mutates one gene on a sampled parent (rule changes stack) or, with weight 0.1, reorders a rule.
   - **`random_search`** — the i.i.d. baseline: every iteration is an independent random sample from the origin (best-of-budget, no archive, no carry-forward). Both arms share one random sampler, so under a matched seed they start from the same draws.

### Mutation strategies

All 8 are **semantics-preserving** rephrasings (the search decides which edits
help); none changes a rule's stated intent.

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

Scale the local smoke up by raising `--n-cases` / `--iterations`, switching `--optimizer ea`, and adding `--enable-validation`. See [WORKFLOW.md](WORKFLOW.md) for patterns, cost guidance, and result interpretation.

### DelftBlue HPC

Experiments run on A100 GPU nodes with Qwen2.5-Coder-32B-Instruct loaded offline (`HF_HUB_OFFLINE=1`). The wrapper `scripts/slurm/slurm_ea_qwen32b.sh` takes env-var overrides:

```bash
# Smoke before any big batch
N_CASES=2 N_ITERATIONS=10 LANGUAGES=python OPTIMIZER=ea \
  sbatch --time=0:45:00 --job-name="ea_smoke" scripts/slurm/slurm_ea_qwen32b.sh

# Final repair batch — EA vs random over the FULL case sets (185 python /
# 114 java), seeds 42 + 43. Runs are wall-time-bounded (SIGUSR1); N_ITERATIONS
# is a high soft cap. EA_INIT_SAMPLES / EA_ORIGIN_PARENT are EA-only (the random
# arm ignores them).
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

The archive/mutation knobs (`ARCHIVE_CAP=6`, `RESTART_H=8`, `MAX_DEPTH=4`,
`RANDOM_MAX_CHANGES=10`, `EA_N_MUTATIONS=1`) keep their defaults; `--enable-validation`
is on by default in the wrapper (feeds the f2 fidelity objective).

Reproduce any run with `python scripts/experiments/rerun_from_config.py <run_dir>` (backend-aware: API → python entrypoint, DelftBlue → `sbatch`). See [WORKFLOW.md](WORKFLOW.md) for the full DelftBlue round-trip.

---

## Project layout

```
├── src/
│   ├── mutation/          # 8 mutators + MutatorPool + MutationQualityValidator + ParsedRule
│   ├── optimizer/         # chromosome + single Pareto archive (chromosome.py), EA + i.i.d. random-search runners (search.py)
│   │                      #   + shared random sampler; ExperimentEngine orchestration (engine.py)
│   ├── evaluation/        # Semgrep runner, CodeBLEU code-divergence, fitness, rule/dataset loading
│   ├── llm_backends/      # Claude / OpenAI / DelftBlue-local backends
│   └── retrieval/         # prompt → CodeGuard-rule map builders (local + Anthropic; [retrieval] extra)
├── scripts/
│   ├── experiments/       # run_experiment.py (entrypoint); rerun_from_config.py (reproducer)
│   ├── slurm/             # slurm_ea_qwen32b.sh (EA / random) + slurm_rule_retrieval_local.sh
│   └── analyze/           # analysis toolkit (WIP — being reworked for the repair design)
├── tests/unit/            # 230 unit tests
├── project-codeguard/     # CodeGuard security rule library (git submodule)
├── rule_maps/             # Pre-computed prompt → rule-ID retrieval maps
├── literature_review/     # Paper PDFs + INDEX_AND_LINKS.md + analysis docs
├── experiments/results/   # Experiment outputs (gitignored)
├── Dockerfile             # API-only replication image
├── ARCHITECTURE.md        # Technical reference (modules, schema, extension points)
├── WORKFLOW.md            # Running experiments + DelftBlue round-trip + result interpretation
└── REPLICATION.md         # Reviewer-facing reproduction guide
```

---

## Datasets, rules & literature

- **CyberSecEval** (Meta AI) — code-generation prompts across Python, C, Java, JavaScript, PHP, covering many CWE types. Fetched from the HuggingFace Hub at runtime.
- **CodeGuard** — the security rule library in the [`project-codeguard/`](project-codeguard/skills/software-security/rules/) submodule. Each rule is a Markdown document (YAML frontmatter + prose + code examples) covering input validation, cryptography, authentication, API security, logging, client-side web security, and more.
- **Literature review** — theoretical grounding for the mutators and validation criteria:

  | Document | Contents |
  |----------|----------|
  | [Index & Paper Links](literature_review/INDEX_AND_LINKS.md) | Papers — descriptions, links, local PDFs |
  | [Thesis Relevance](literature_review/THESIS_RELEVANCE.md) | Quick map: paper → codebase component |


---

## Documentation

| Document | Contents |
|----------|----------|
| [REPLICATION.md](REPLICATION.md) | Reviewer reproduction (API-only): prerequisites → smoke → reproducibility guarantees |
| [ARCHITECTURE.md](ARCHITECTURE.md) | High-level design: the pipeline, the two search strategies, the fitness model, data flow |
| [IMPLEMENTATION.md](IMPLEMENTATION.md) | Module-by-module reference, output schema, extension points, dependencies |
| [WORKFLOW.md](WORKFLOW.md) | Running experiments, result interpretation |
| [literature_review/](literature_review/INDEX_AND_LINKS.md) | Paper index, thesis relevance |
