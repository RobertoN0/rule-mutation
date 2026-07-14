# Replication Package

This is the reviewer-facing guide to reproducing the experiments **without
DelftBlue access**, using an LLM provider API. For project orientation start at
[README.md](README.md); for internals see [ARCHITECTURE.md](ARCHITECTURE.md).

The framework supports two execution paths:

| Path | Where it runs | Code generation | Reproducible here |
|---|---|---|---|
| **A. API-based** (this doc) | Any laptop / VM, CPU only | Anthropic / OpenAI API | ✅ Yes |
| **B. Local GPU** | DelftBlue A100 nodes | HuggingFace + transformers | ❌ Cluster-only |

Both paths run the *same* mutation → generate → Semgrep → CodeBLEU → search
pipeline and write the *same* output schema. Only the
code-generation backend differs. Everything below refers to **Path A**.

---

## Prerequisites

1. **Git** ≥ 2.30 — to clone the repository and initialise the `project-codeguard` submodule.
2. **One of**:
   - [`uv`](https://docs.astral.sh/uv/) ≥ 0.5 (recommended). Install:
     `curl -LsSf https://astral.sh/uv/install.sh | sh` (Linux/macOS),
     `brew install uv` (macOS), or the PowerShell one-liner on Windows.
   - **Docker** ≥ 24 — if you prefer a sealed image.
3. **An LLM API key** for at least one provider:
   - **Anthropic Claude** (recommended) — `claude-haiku-4-5` is the cheapest and is the default for the smoke test.
   - **OpenAI** — e.g. `gpt-4o-mini`.

No GPU, no DelftBlue account, and no HuggingFace authentication are required.
The CyberSecEval dataset is fetched from the HuggingFace Hub at runtime, and the
CodeGuard rules ship in the `project-codeguard/` submodule.

---

## 1. Clone the repository

```bash
git clone --recurse-submodules https://github.com/RobertoN0/rule-mutation.git
cd rule-mutation

# If you forgot --recurse-submodules:
git submodule update --init --recursive
```

## 2. Configure secrets

```bash
cp .env.example .env
$EDITOR .env       # fill in ANTHROPIC_API_KEY (or OPENAI_API_KEY)
```

`.env` is git-ignored. Never commit API keys.

## 3. Install + smoke test

### Path A1 — uv (recommended)

```bash
uv sync                                              # API-only deps into .venv/
uv run python scripts/validation/validate_claude.py  # one ~$0.0001 Claude call
```

Expected output ends with `🎉 Claude backend is wired up correctly.`

### Path A2 — Docker

```bash
docker build -t codeguard-sbst:replication .

# Default CMD = the validate_claude.py smoke test
docker run --rm --env-file .env codeguard-sbst:replication
```

---

## 4. Tiny end-to-end run

Once the smoke test passes, reproduce a short search run (the default rules map
covers Python + Java; `--languages python` keeps it small and cheap):

```bash
# uv:           prefix with `uv run`
# activated venv:  source .venv/bin/activate first
python scripts/experiments/run_experiment.py \
  --backend claude --optimizer ea --enable-validation \
  --rules-map rule_maps/map_qwen32b_python_java.json \
  --n-cases 2 --iterations 5 \
  --archive-cap 6 --restart-h 8 --max-depth 4 \
  --ea-init-samples 10 --ea-injection-every 10 --random-max-changes 10 \
  --mutators synonym_replacement add_random_word verb_weakening \
             section_reorder_shuffle section_reorder_degrade \
  --languages python --seed 42 \
  --output-dir experiments/results/replication_smoke
```

This makes ~6 API calls (a baseline pass + 5 iterations, minus eval-cache hits)
and writes a complete run directory (see §6). To run the i.i.d. baseline
instead, swap `--optimizer random_search` (same sampler, no archive).

`--enable-validation` is **required** on every real run: it computes the f2
rule-fidelity objective (SBERT similarity of each mutated rule to its original)
and records the post-hoc quality metadata (instruction adherence, keyword
retention, etc.) into `iterations.jsonl` — nothing is rejected. Only `--dry-run`
may omit it. Summarise the metadata with `scripts/analyze/validation_audit.py`
(see §5).

Reproduce that exact run from its recorded config:

```bash
python scripts/experiments/rerun_from_config.py experiments/results/replication_smoke --print   # show the command
python scripts/experiments/rerun_from_config.py experiments/results/replication_smoke           # actually re-run
```

> **PATH note:** the pipeline shells out to `semgrep`. Either `source
> .venv/bin/activate` (recommended) or run via `uv run …`. If you invoke
> `.venv/bin/python` directly, prefix with `PATH="$PWD/.venv/bin:$PATH"` so the
> subprocess can find `semgrep`; otherwise scans fail with "Semgrep not
> installed" (the run still completes, but every finding count is 0). The
> `semgrep_debug/semgrep_debug.jsonl` trace distinguishes a failed scan
> (`error != null`) from a genuinely clean scan (`error: null`).

---

## 5. Inspect the results

A completed run records everything needed for analysis directly on disk (see
§6). The `iterations.jsonl` trajectory and the `intermediate/*.jsonl` per-prompt
evaluations are plain JSON lines you can read without any extra tooling.

> **Analysis toolkit — work in progress.** Scripts under `scripts/analyze/`
> (`--extra analysis`: `matplotlib`, `scipy`) turn runs into figures and
> statistics, but they are being reworked for the repair/chromosome design and
> are not finalised — out of scope for this reproduction. Read the raw artifacts
> in the meantime.

> `uv sync --extra analysis` replaces the resolved set, so it removes the `dev`
> extras (pytest/ruff) if they were installed. To keep everything, sync all the
> extras you want at once: `uv sync --extra dev --extra analysis`.

---

## 6. What a run directory contains

```
experiments/results/<name>/
├── run_config.json                  # every CLI arg + git SHA + schema_version: 4
├── hillclimb_summary_*.json         # run-level totals, mutator stats, cache hygiene
├── iterations.jsonl                 # one record per search iteration (the trajectory)
├── archive_snapshots/iterNNNN.json  # EA only — single chromosome Pareto archive every 20 iters + final
├── intermediate/                    # per-prompt evaluation records
│   ├── baseline.jsonl
│   └── {ea_iter0001,rand_iter0001,…}.jsonl
├── mutated_rules/iterNNN/           # mutated rule text (.md) + meta.json (mutation_chain, changes)
├── semgrep_debug/semgrep_debug.jsonl  # per-scan trace (failure vs zero-findings)
└── run.log                          # stdout/stderr tee
```

The full field-level schema is documented in
[IMPLEMENTATION.md → Output schema](IMPLEMENTATION.md#output-schema).

---

## 7. What gets installed

`pyproject.toml` declares the base dependencies plus optional extras:

- **Default (`uv sync`)** — the API path: `anthropic`, `openai`, `semgrep`,
  `codebleu` + tree-sitter grammars, `sentence-transformers` (for the optional
  validator), `datasets`, `pandas`. Pinned exactly in `uv.lock` (committed); the
  Dockerfile consumes the same lockfile via `uv sync --frozen --no-dev`.
- **`--extra gpu`** — `accelerate`, `bitsandbytes` (+ a CUDA torch reinstall on
  DelftBlue). **Only needed for Path B.**
- **`--extra analysis`** — `matplotlib`, `scipy` for the report scripts.
- **`--extra dev`** — `pytest`, `ruff`.

---

## 8. Reproducibility guarantees and limitations

**Deterministic given the same `--seed`:**

- Mutator behaviour and the search trajectory (rule/mutator draws).
- Test-case selection order (`--selection first`, or `--selection random --seed N`).
- Semgrep findings on identical generated source (Semgrep is deterministic).
- The eval cache: identical assembled rule text → reused code + findings.

**Not bit-identical across runs:**

- LLM outputs. Even at `temperature=0`, providers may change weights, batching,
  or sampling internals between calls. The generated code, Semgrep findings, and
  fitness are therefore **saved verbatim per prompt** in `intermediate/*.jsonl`,
  so all downstream analysis re-runs on the saved artifacts without re-calling
  the model.
- Byte-equality of generated code across provider/model versions.

`--seed`, the model, and the git SHA are recorded in `run_config.json`.

---

## 9. Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `ANTHROPIC_API_KEY is not set` | `.env` missing or unfilled | `cp .env.example .env`, add the key |
| `Semgrep not installed or not in PATH` (and findings all 0) | venv not active when calling `.venv/bin/python` directly | `source .venv/bin/activate`, or run via `uv run …`, or prefix `PATH="$PWD/.venv/bin:$PATH"` |
| `pytest` missing after `uv sync --extra analysis` | uv pruned the `dev` extra | `uv sync --extra dev --extra analysis` (combine extras) |
| `FileNotFoundError: project-codeguard/...` | submodule not initialised | `git submodule update --init --recursive` |
| Docker build fails on `COPY project-codeguard` | same — submodule empty | initialise the submodule before `docker build` |
| Rate-limited (429 / 529) | provider throttling | wait and retry; the run saves all completed iterations and exits gracefully |
| `WARNING: There is no reference data-flows extracted…` (only visible in old logs) | CodeBLEU's data-flow extractor can't parse a few prompts | harmless and **silenced by default** (a root-logger filter in `composite_fitness.py`); that prompt's code-divergence simply omits the data-flow sub-score. Semgrep findings are unaffected. |
