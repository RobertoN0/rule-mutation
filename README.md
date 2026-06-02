# CodeGuard SBST Framework

**Search-Based Software Testing for LLM Security Instruction Robustness**

An MSc thesis research framework that adversarially mutates LLM security coding guidelines and measures how many security vulnerabilities are present in the generated code.

---

## Research Question

**How resilient are security instructions to adversarial modifications?**

When a CodeGuard rule guiding an LLM's code generation is weakened, obfuscated, or restructured, does the LLM produce more vulnerable code? This framework implements hill climbing over a space of rule mutations to find the worst-case adversarial transformation for each rule.

---

## Literature Review

Theoretical grounding for all mutation strategies and quality validation criteria:

| Document | Contents |
|----------|----------|
| [Index & Paper Links](literature_review/INDEX_AND_LINKS.md) | All 16 papers — descriptions, arXiv links, local PDF downloads |
| [Full Analysis](literature_review/LITERATURE_REVIEW_ANALYSIS.md) | Per-paper: summary, thesis relevance, implementation status |
| [Thesis Relevance](literature_review/THESIS_RELEVANCE.md) | Quick-reference mapping: paper → codebase component |

Key sources: LLMORPH (Cho et al., ASE 2025), AUGMENT (Chataigner et al., 2025), SBST MR selection (arXiv 2507.05565).

---

## Approach

1. **Select** test prompts from CyberSecEval
2. **Map** relevant CodeGuard rules to each prompt via AI-based retrieval
3. **Mutate** the rules with one of 8 adversarial strategies
4. **Validate** mutation quality (SBERT semantic similarity, instruction adherence, security keyword retention) — observational soft gate, recorded but not enforcing
5. **Generate** code with the configured backend on original vs. mutated rules — Qwen2.5-Coder-32B-Instruct on DelftBlue, or Claude / OpenAI for local replication
6. **Score** vulnerability count via Semgrep + code-divergence via CodeBLEU
7. **Optimize** via two interchangeable search strategies: the **(1+1) EA with per-rule Pareto archive** (3 objectives: total Semgrep delta, proportion of divergent prompts, mean conditional divergence) or a **stateless random baseline** (per-iteration multi-mutation sampler) — selected via `--optimizer {ea, random_baseline}`

---

## Mutation Strategies

**Function-based** (deterministic, no extra VRAM):

| Mutator | What it does |
|---------|-------------|
| `verb_weakening` | Replaces MUST/NEVER/ALWAYS with weaker synonyms throughout prose |
| `synonym_replacement` | Substitutes nouns and verbs with WordNet synonyms |
| `add_random_word` | Inserts security-domain adjectives/adverbs before nouns and verbs |
| `section_reorder_shuffle` | Randomly permutes `##` sections; falls back to prose paragraph reordering |
| `section_reorder_degrade` | Moves the highest-scoring security section to last position (LLM recency bias) |

**LLM-based** (Qwen2.5-Coder-32B, same instance as code generation — no extra load):

| Mutator | What it does |
|---------|-------------|
| `negation_injection` | Inserts contradictory qualifiers before imperative security directives |
| `voice_change` | Transforms active imperatives to passive advisory form |
| `paraphrase` | Rewrites prose with weaker vocabulary; inline code masked before LLM call |

All mutators respect the **safe-zone contract**: YAML frontmatter, fenced code blocks, and inline code are never modified.

For full details on each mutator and the quality validator, see [ARCHITECTURE.md](ARCHITECTURE.md).

---

## Setup

Dependency management is via [`uv`](https://docs.astral.sh/uv/) (Python ≥3.11). One canonical lockfile, deterministic installs, works the same locally and on DelftBlue.

```bash
# 1. Install uv (skip if already on PATH)
curl -LsSf https://astral.sh/uv/install.sh | sh

# 2. Clone with the project-codeguard submodule
git clone --recurse-submodules https://github.com/RobertoN0/rule-mutation.git
cd rule-mutation

# 3. Install dependencies (creates .venv/)
uv sync                  # core
uv sync --extra dev      # + pytest for development

# 4. Verify
uv run pytest tests/unit/ -q     # should report 179/179 passing
```

### Optional extras

- `--extra gpu` — `accelerate` + `bitsandbytes` for quantized inference on CUDA hosts (DelftBlue A100, etc.). Skip on CPU-only machines.
- `--extra retrieval` — `langchain` + `langgraph` for re-running the rule-retrieval pipeline (pre-computed maps in `pipeline_breakdown/rule_retrieval_output/` let replicators skip this step).
- `--extra analysis` — `matplotlib` + `scipy` for the report-figure scripts under `scripts/analyze/`. Run locally on downloaded results; not needed at experiment time.
- `--extra dev` — `pytest` + `ruff` for development.

### DelftBlue notes

On DelftBlue login nodes (which have outbound HTTPS), use the same install command. Redirect uv's cache to `/scratch` to avoid filling the small `/home` quota:

```bash
export UV_CACHE_DIR=/scratch/$USER/uv-cache
uv sync --extra gpu      # DelftBlue uses the GPU extras
```

DelftBlue's Python documentation [explicitly recommends](https://doc.dhpc.tudelft.nl/delftblue/Python/) this install pattern.

---

## Reproducing locally (API backends — no GPU required)

The framework supports Anthropic Claude and OpenAI as drop-in code-generation backends, so the full pipeline (mutation → code-gen → Semgrep → CodeBLEU → optional validation) reproduces on any CPU machine. Set the relevant API key in `.env` (see `.env.example`):

```bash
cp .env.example .env
# edit .env to add ANTHROPIC_API_KEY or OPENAI_API_KEY

# Tiny smoke (≈ $0.05 with claude-haiku-4-5) — 2 cases × 5 iterations
PATH="$PWD/.venv/bin:$PATH" python scripts/experiments/run_with_rules_map.py \
  --backend claude --optimizer random_baseline \
  --n-cases 2 --iterations 5 --max-mutations-per-iter 4 \
  --mutators synonym_replacement add_random_word verb_weakening section_reorder_shuffle section_reorder_degrade \
  --seed 42 --languages python \
  --output-dir experiments/results/local_smoke

# Inspect the run
ls experiments/results/local_smoke/
# run_config.json, hillclimb_summary_*.json, iterations.jsonl,
# intermediate/baseline.jsonl, intermediate/rand_iter000N.jsonl,
# mutated_rules/iterNNN/, semgrep_debug/, run.log, rerun.sh

# Reproduce the same run from its config
bash experiments/results/local_smoke/rerun.sh --print   # show the command
bash experiments/results/local_smoke/rerun.sh           # actually re-run
```

The `PATH=$PWD/.venv/bin:$PATH` prefix ensures the `semgrep` binary installed in the venv is on PATH (subprocess inherits the parent's PATH; calling `.venv/bin/python` alone is not enough). Equivalently: `source .venv/bin/activate` first.

After a run, generate the report figures + tables with the `[analysis]` extra:

```bash
uv sync --extra analysis        # one-time
python scripts/analyze/analyze_run.py experiments/results/local_smoke      # per-run RQ1/RQ2 + cost/hygiene
python scripts/analyze/compare_runs.py experiments/results/                # multi-run RQ3 + multi-seed
python scripts/analyze/validation_audit.py <run_dir>                       # only for --enable-validation runs
python scripts/analyze/migrate_legacy_run.py <pre-schema-2_dir>            # bridge old runs into the new toolkit
```

---

## Running Experiments (DelftBlue HPC)

Experiments run on DelftBlue A100 GPU nodes with Qwen2.5-Coder-32B-Instruct loaded locally (`HF_HUB_OFFLINE=1`). The SLURM wrapper `scripts/slurm/slurm_ea_qwen32b.sh` reads env-var overrides (defaults are conservative — see the script header for the full list).

```bash
# Smoke (mandatory before any big batch) — 2 cases × 10 iters, ~30 min
N_CASES=2 N_ITERATIONS=10 LANGUAGES=python OPTIMIZER=ea \
  sbatch --time=0:45:00 --job-name="ea_smoke" scripts/slurm/slurm_ea_qwen32b.sh

# Multi-seed RQ3 batch — 200 iters, 25 cases, paired EA vs random across 3 seeds
for SEED in 1 7 123; do
  for OPT in ea random_baseline; do
    for LANG in python java; do
      SEED=$SEED OPTIMIZER=$OPT N_CASES=25 N_ITERATIONS=200 LANGUAGES=$LANG SELECTION=random \
        sbatch --time=12:00:00 --job-name="${OPT}_${LANG}_s${SEED}" \
               scripts/slurm/slurm_ea_qwen32b.sh
    done
  done
done

# Validation ablation (one job) — populates validation_metadata for the audit script
SEED=42 OPTIMIZER=ea N_CASES=25 N_ITERATIONS=200 LANGUAGES=python SELECTION=random \
  ENABLE_VALIDATION=1 MUTATION_MAX_RETRIES=2 \
  sbatch --time=15:00:00 --job-name="ea_val" scripts/slurm/slurm_ea_qwen32b.sh
```

**Reproducer**: every output dir contains a thin `rerun.sh` that delegates to `scripts/experiments/rerun_from_config.py`. Backend-aware: API runs re-invoke the python entrypoint; DelftBlue runs map the recorded args back to env vars and `sbatch` the wrapper (`bash <run_dir>/rerun.sh --as delftblue --print` to dry-run the sbatch line).

Output directories are named `experiments/results/job{SLURM_ID}_{optimizer}_{N_CASES}_{MMDD}/`. Each contains:

- `run_config.json` — every CLI arg + git SHA + `schema_version: 2`
- `hillclimb_summary_*.json` — run-level totals, mutator stats, cache hygiene
- `iterations.jsonl` — one record per search iteration (the trajectory)
- `archive_snapshots/iter{N:04d}.json` — EA only, per-rule Pareto archive every 20 iters + final
- `intermediate/{baseline,ea_iter0001,…}.jsonl` — per-prompt evaluation records
- `mutated_rules/iter{N:03d}/` — mutated rule text + meta.json
- `semgrep_debug/semgrep_debug.jsonl` — per-scan trace (distinguishes failure from zero-findings)
- `run.log`, `rerun.sh`

See [WORKFLOW.md](WORKFLOW.md) for full setup, environment activation, and result interpretation.

---

## Project Structure

```
├── src/
│   ├── mutation/          # 8 mutators + MutatorPool + MutationQualityValidator + ParsedRule
│   ├── optimizer/         # (1+1) EA + Pareto archive + stateless random baseline
│   ├── evaluation/        # Fitness, Semgrep runner, CodeBLEU code-divergence, rule/dataset loading
│   └── llm_backends/      # Claude / OpenAI / DelftBlue-local backends
├── scripts/
│   ├── experiments/       # run_with_rules_map.py — entrypoint; rerun_from_config.py — backend-aware reproducer
│   ├── slurm/             # slurm_ea_qwen32b.sh (EA / random_baseline) + slurm_rule_retrieval_local.sh (retrieval pipeline)
│   └── analyze/           # loaders, stats, analyze_run, compare_runs, validation_audit, migrate_legacy_run
├── project-codeguard/     # 23 CodeGuard security rules (git submodule)
├── literature_review/     # Paper PDFs + INDEX_AND_LINKS.md + analysis docs
├── pipeline_breakdown/    # Pre-computed rule retrieval maps
├── experiments/results/   # Experiment outputs (gitignored)
├── ARCHITECTURE.md        # Full technical reference
└── WORKFLOW.md            # Running experiments, environment setup
```

---

## Dataset & Rules

**CyberSecEval** (Meta AI): 12k+ code generation prompts across Python, C, Java, JavaScript, PHP, covering 75+ CWE types. Pre-selected "interesting cases" (where security rules make a detectable difference) are in `pipeline_breakdown/generation_results/`.

**CodeGuard** (23 rules): Input validation, memory safety (C/C++), cryptography, authentication, API security, logging, client-side web security. Located in [`project-codeguard/skills/software-security/rules/`](project-codeguard/skills/software-security/rules/).

---

## Documentation

| Document | Contents |
|----------|----------|
| [ARCHITECTURE.md](ARCHITECTURE.md) | System design: mutators, validator criteria, output schema, extension points |
| [WORKFLOW.md](WORKFLOW.md) | Environment setup, SLURM jobs, result interpretation |
| [literature_review/](literature_review/INDEX_AND_LINKS.md) | Paper index, full analysis, thesis relevance |

---

## Task Management

Issues tracked with [beads](https://github.com/BeadsLand/beads):

```bash
bd list       # All issues
bd ready      # Available work
bd show <id>  # Issue details
```
