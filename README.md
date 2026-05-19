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
3. **Mutate** the rules with one of 9 adversarial strategies
4. **Validate** mutation quality (SBERT semantic similarity, instruction adherence, security keyword retention)
5. **Generate** code with Qwen2.5-Coder-32B-Instruct on original vs. mutated rules
6. **Score** vulnerability count via Semgrep (`SEVERITY_WEIGHTED`: ERROR×3 + WARNING×1)
7. **Optimize** via hill climbing — keep mutations that increase the vulnerability score

---

## Mutation Strategies

**Function-based** (deterministic, no extra VRAM):

| Mutator | What it does |
|---------|-------------|
| `fluff` | Prepends bureaucratic prefix, appends noise suffix, weakens imperative verbs |
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
uv run pytest tests/unit/ -q     # should report 176/176 passing
```

### Optional extras

- `--extra gpu` — adds `accelerate` + `bitsandbytes` for quantized inference on CUDA hosts (DelftBlue A100, etc.). Skip on CPU-only machines.

### DelftBlue notes

On DelftBlue login nodes (which have outbound HTTPS), use the same install command. Redirect uv's cache to `/scratch` to avoid filling the small `/home` quota:

```bash
export UV_CACHE_DIR=/scratch/$USER/uv-cache
uv sync --extra gpu      # DelftBlue uses the GPU extras
```

DelftBlue's Python documentation [explicitly recommends](https://doc.dhpc.tudelft.nl/delftblue/Python/) this install pattern.

---

## Running Experiments (DelftBlue HPC)

Experiments run on DelftBlue A100 GPU nodes with Qwen2.5-Coder-32B-Instruct loaded locally (`HF_HUB_OFFLINE=1`).

```bash
# Validation run — single mutator, 4 C-language cases, 5 iterations
N_CASES=4 N_ITERATIONS=5 MUTATOR=paraphrase LANGUAGES=c ENABLE_VALIDATION=1 \
  sbatch --job-name="paraphrase_val" \
         --output="logs/paraphrase_%j.out" \
         --error="logs/paraphrase_%j.err" \
         scripts/slurm/slurm_bandit_qwen32b.sh

# Scale-up — all 9 mutators, all languages, 16 cases, 10 iterations
for MUTATOR in fluff verb_weakening synonym_replacement add_random_word \
               section_reorder_shuffle section_reorder_degrade \
               negation_injection voice_change paraphrase; do
  N_CASES=16 N_ITERATIONS=10 ENABLE_VALIDATION=1 MUTATOR=$MUTATOR \
    sbatch --time=02:30:00 --job-name="${MUTATOR}_su" \
           --output="logs/${MUTATOR}_scaleup_%j.out" \
           --error="logs/${MUTATOR}_scaleup_%j.err" \
           scripts/slurm/slurm_bandit_qwen32b.sh
done
```

Output directories are named `experiments/results/job{SLURM_ID}_{mutator}_{MMDD}/`, sorted by submission order. Each contains `run_config.json` (full CLI args + git SHA), `rerun.sh` (exact reproduction script), and `mutated_rules/iter{N}/`.

See [WORKFLOW.md](WORKFLOW.md) for full setup, environment activation, and result interpretation.

---

## Project Structure

```
├── src/
│   ├── mutation/          # 9 mutators + MutationQualityValidator + ParsedRule
│   ├── optimizer/         # Hill climbing algorithm
│   ├── evaluation/        # Fitness, Semgrep runner, rule/dataset loading
│   └── llm_backends/      # DelftBlue local backend (Groq legacy)
├── scripts/
│   ├── experiments/       # run_with_rules_map.py — main experiment entry point
│   └── slurm/             # slurm_bandit_qwen32b.sh (lex/D-UCB) + slurm_ea_qwen32b.sh (EA / random_baseline)
├── project-codeguard/     # 23 CodeGuard security rules (git submodule)
├── literature_review/     # Paper PDFs + INDEX_AND_LINKS.md + analysis docs
├── pipeline_breakdown/    # Pre-computed interesting cases + rule retrieval map
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
