# CodeGuard SBST Framework

**Search-Based Software Testing for LLM Security-Instruction Robustness**

This MSc thesis framework measures how robust **[CodeGuard](https://github.com/cosai-oasis/project-codeguard) security coding guidelines** are to adversarial rephrasing. CodeGuard rules (shipped as the `project-codeguard/` git submodule) are the natural-language security instructions given to a code-generating LLM; this framework mutates those rules — weakening, obfuscating, or reordering them while preserving their apparent meaning — and measures whether the LLM then writes more vulnerable code, as detected by [Semgrep](https://github.com/semgrep/semgrep). A search algorithm drives the mutations toward the worst case for each rule.

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
uv run pytest tests/unit/ -q     # should report "181 passed"
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

# Tiny smoke (≈ $0.05 with claude-haiku-4-5): 2 cases × 5 iterations
python scripts/experiments/run_with_rules_map.py \
  --backend claude --optimizer ea \
  --n-cases 2 --iterations 5 --max-mutations-per-iter 4 \
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
  python scripts/experiments/run_with_rules_map.py \
    --backend claude --optimizer random_baseline \
    --n-cases 2 --iterations 3 \
    --mutators synonym_replacement add_random_word verb_weakening \
    --seed 42 --languages python \
    --output-dir /app/results/docker_smoke
```

See [REPLICATION.md](REPLICATION.md) for the complete reviewer-facing reproduction guide (prerequisites, what gets installed, reproducibility guarantees, troubleshooting).

A run directory contains: `run_config.json`, `hillclimb_summary_*.json`, `iterations.jsonl`, `archive_snapshots/` (EA only), `intermediate/{baseline,…}.jsonl`, `mutated_rules/iterNNN/`, `semgrep_debug/`, and `run.log`. The exact schema is documented in [IMPLEMENTATION.md](IMPLEMENTATION.md#output-schema).

---

## Analyze results

Report figures + tables are produced by the scripts under `scripts/analyze/` (needs the `analysis` extra):

```bash
uv sync --extra dev --extra analysis    # see the uv gotcha above

# Single run → RQ1 (per-rule + per-prompt baseline-vs-best, Wilcoxon/McNemar),
# RQ2 (per-mutator effective rate + bootstrap CI), convergence, cost + cache hygiene
python scripts/analyze/analyze_run.py experiments/results/local_smoke

# Across runs → RQ3 (EA vs random, paired tests), multi-seed median+IQR
python scripts/analyze/compare_runs.py experiments/results/

# Informational quality-validation audit (only for --enable-validation runs)
python scripts/analyze/validation_audit.py <run_dir>
```

Each script writes a `summary.md` + CSVs + PNGs into `<run_dir>/analysis/` (or a `--out` dir for `compare_runs.py`).

---

## How it works

1. **Select** test prompts from CyberSecEval.
2. **Map** relevant CodeGuard rules to each prompt via AI-based retrieval (pre-computed maps in `pipeline_breakdown/rule_retrieval_output/`).
3. **Mutate** the target rule with one of 8 adversarial strategies.
4. **Validate** mutation quality (SBERT similarity, instruction adherence, security-keyword retention) — *informational and post-hoc*: every candidate is recorded, none are rejected (the validator never gates the search).
5. **Generate** code with the configured backend on the original vs. mutated rule — Qwen2.5-Coder-32B-Instruct on DelftBlue, or Claude / OpenAI locally.
6. **Score** each prompt by Semgrep finding count + code-divergence via CodeBLEU.
7. **Optimize** with one of two interchangeable search strategies (`--optimizer`):
   - **`ea`** — a (1+1) EA with a per-rule 3-objective **Pareto archive** (total Semgrep delta, proportion of divergent prompts, mean conditional divergence).
   - **`random_baseline`** — a stateless per-iteration multi-mutation sampler (the ablation: same budget, no archive, no acceptance test, no state).

### Mutation strategies

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

# Multi-seed RQ3 batch — paired EA vs random across seeds and languages
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

Reproduce any run with `python scripts/experiments/rerun_from_config.py <run_dir>` (backend-aware: API → python entrypoint, DelftBlue → `sbatch`). See [WORKFLOW.md](WORKFLOW.md) for the full DelftBlue round-trip.

---

## Project layout

```
├── src/
│   ├── mutation/          # 8 mutators + MutatorPool + MutationQualityValidator + ParsedRule
│   ├── optimizer/         # (1+1) EA + Pareto archive (ea_optimizer.py, pareto_archive.py)
│   │                      #   + stateless random baseline; HillClimber orchestration
│   ├── evaluation/        # Semgrep runner, CodeBLEU code-divergence, fitness, rule/dataset loading
│   └── llm_backends/      # Claude / OpenAI / DelftBlue-local backends
├── scripts/
│   ├── experiments/       # run_with_rules_map.py (entrypoint); rerun_from_config.py (reproducer)
│   ├── slurm/             # slurm_ea_qwen32b.sh (EA / random) + slurm_rule_retrieval_local.sh
│   └── analyze/           # loaders, stats, analyze_run, compare_runs, validation_audit
├── tests/unit/            # 181 unit tests
├── project-codeguard/     # CodeGuard security rule library (git submodule)
├── pipeline_breakdown/    # Pre-computed rule-retrieval maps
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
  | [Full Analysis](literature_review/LITERATURE_REVIEW_ANALYSIS.md) | Per-paper summary, thesis relevance, implementation status |
  | [Thesis Relevance](literature_review/THESIS_RELEVANCE.md) | Quick map: paper → codebase component |

  Key sources: LLMORPH (Cho et al., ASE 2025), AUGMENT (Chataigner et al., 2025), SBST MR selection (arXiv 2507.05565).

---

## Documentation

| Document | Contents |
|----------|----------|
| [REPLICATION.md](REPLICATION.md) | Reviewer reproduction (API-only): prerequisites → smoke → reproducibility guarantees |
| [ARCHITECTURE.md](ARCHITECTURE.md) | High-level design: the pipeline, the two search strategies, the fitness model, data flow |
| [IMPLEMENTATION.md](IMPLEMENTATION.md) | Module-by-module reference, output schema, extension points, dependencies |
| [WORKFLOW.md](WORKFLOW.md) | Running experiments, result interpretation, analysis toolkit |
| [literature_review/](literature_review/INDEX_AND_LINKS.md) | Paper index, analysis, thesis relevance |
