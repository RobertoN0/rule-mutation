# Replication Package

This is the reviewer-facing guide to reproducing the experiments **without
DelftBlue access**, using an LLM provider API. For project orientation start at
[README.md](README.md); for internals see [ARCHITECTURE.md](ARCHITECTURE.md).

The framework supports two execution paths:

| Path | Where it runs | Code generation | Reproducible here |
|---|---|---|---|
| **A. API-based** (this doc) | Any laptop / VM, CPU only | Anthropic / OpenAI API | ✅ Yes |
| **B. Local GPU** | DelftBlue A100 nodes | HuggingFace + transformers | ❌ Cluster-only |

Both paths run the *same Phase 2 search workflow*: baseline → mutation →
generation → output validation → Semgrep → search. They write the same
output schema. Only the
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
uv run python -m nltk.downloader wordnet omw-1.4 \
  averaged_perceptron_tagger averaged_perceptron_tagger_eng
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

Once the smoke test passes, reproduce a short search run with the final Python
map:

```bash
# uv:           prefix with `uv run`
# activated venv:  source .venv/bin/activate first
python scripts/experiments/run_experiment.py \
  --backend claude --optimizer ea --enable-validation \
  --rules-map rule_maps/qualified/final_search_map_qwen_python.json \
  --n-cases 2 --main-loop-budget 2 \
  --archive-cap 6 --max-depth 4 \
  --ea-injection-every 10 --random-max-changes 10 \
  --mutators synonym_replacement add_random_word verb_weakening \
             section_reorder_shuffle section_reorder_degrade \
  --languages python --seed 42 \
  --output-dir experiments/results/replication_smoke
```

This evaluates a five-candidate initialization followed by two main-loop
candidates and writes a complete run directory (see §6). The number of API
calls depends on the task count and evaluation-cache reuse. To run independent
random search instead, use `--optimizer random_search` (same initialization and
sampler, no archive).

`--enable-validation` is **required** on every real run: it computes the f2
rule-fidelity objective (SBERT similarity of each mutated rule to its original)
and records the post-hoc quality metadata (instruction adherence, keyword
retention, etc.) into `evaluations.jsonl` — nothing is rejected. Only `--dry-run`
may omit it. The run validator checks that the resulting artifacts
reconcile before they are used as evidence.

Reproduce that exact run from its recorded config:

```bash
python scripts/experiments/rerun_from_config.py experiments/results/replication_smoke --print   # show the command
python scripts/experiments/rerun_from_config.py experiments/results/replication_smoke           # actually re-run
```

> **PATH note:** the pipeline shells out to `semgrep`. Either `source
> .venv/bin/activate` (recommended) or run via `uv run …`. If you invoke
> `.venv/bin/python` directly, prefix with `PATH="$PWD/.venv/bin:$PATH"` so the
> subprocess can find `semgrep`; otherwise the evaluator aborts the run instead
> of recording a failed scan as zero findings. The
> `semgrep_debug/semgrep_debug.jsonl` trace distinguishes a failed scan
> (`error != null`) from a genuinely clean scan (`error: null`).

---

## 5. Inspect the results

A completed run records everything needed for analysis directly on disk (see
§6). The `evaluations.jsonl` trajectory and the `intermediate/*.jsonl` per-task
evaluations are plain JSON lines you can read without any extra tooling.

For search-run health, use:

```bash
.venv/bin/python scripts/analyze/validate_search_run.py --write <run_dir>
```

This is a reconciliation validator, not the final multi-run thesis analyzer:
it checks artifact consistency, raw f1, imputation, map/rule provenance, and
Semgrep-debug coverage.

> `uv sync --extra analysis` replaces the resolved set, so it removes the `dev`
> extras (pytest/ruff) if they were installed. To keep everything, sync all the
> extras you want at once: `uv sync --extra dev --extra analysis`.

---

## 6. What a run directory contains

```
experiments/results/<name>/
├── run_config.json                  # arguments + code/model/map/scanner provenance
├── search_summary.json              # termination, runtime, LLM/mutator/cache accounting
├── evaluations.jsonl                # attempts and completed candidate evaluations
├── archive_snapshots/evaluation_NNNN.json # EA only — periodic and final front
├── intermediate/                    # per-task evaluation records
│   ├── baseline.jsonl
│   └── evaluation_NNNN.jsonl
├── mutated_rules/evaluation_NNNN/   # mutated rule text (.md) + evaluation metadata
├── semgrep_debug/semgrep_debug.jsonl  # per-scan trace (failure vs zero-findings)
├── evaluation_manifest.json         # exact task set + map-fixed analysis language
├── evaluation_failures.jsonl        # present only when a fatal evaluation was recorded
├── search_validation.json           # validator result when --write was used
└── run.log                          # stdout/stderr tee
```

The full field-level schema is documented in
[IMPLEMENTATION.md → Output schema](IMPLEMENTATION.md#output-schema).

---

## 7. What gets installed

`pyproject.toml` declares the base dependencies plus optional extras:

- **Default (`uv sync`)** — the API path: `anthropic`, `openai`, `semgrep`,
  `tree-sitter-java` for Java qualification, `sentence-transformers` (for the
  validator), `datasets`, `pandas`. Pinned exactly in `uv.lock` (committed); the
  Dockerfile consumes the same lockfile via `uv sync --frozen --no-dev`.
- **`--extra gpu`** — `accelerate`, `bitsandbytes` (+ a CUDA torch reinstall, see
  below). **Only needed for Path B.**
- **`--extra analysis`** — `scipy` for paired statistical analysis.
- **`--extra dev`** — `pytest`, `ruff`.

### GPU host (DelftBlue / CUDA)

`pyproject.toml` pins `torch` to PyTorch's **CPU** wheel index
(`[tool.uv.sources]`), because the CUDA wheel is ~5 GB and no replicator on a
laptop needs it. A GPU host therefore builds the environment in two steps: sync
the extras, then swap torch for the CUDA build. This is the whole procedure for
standing up a fresh account:

```bash
# 1. Keep the ~7 GB CUDA stack off the quota'd /home. /scratch is NOT backed up;
#    treat the venv as rebuildable from these steps.
export UV_PROJECT_ENVIRONMENT=/scratch/$USER/venvs/rule-mutation

# 2. Sync every extra you need IN ONE COMMAND (uv prunes anything not named).
uv sync --python 3.12 --extra gpu --extra analysis --extra dev
ln -s "$UV_PROJECT_ENVIRONMENT" .venv    # so `source .venv/bin/activate` works

# 3. Swap the CPU torch wheel for the CUDA one. The CUDA toolkit version is
#    deliberately NOT in uv.lock — pinning it there would force the 5 GB wheel
#    on every replicator.
uv pip install --reinstall --index-url https://download.pytorch.org/whl/cu126 torch

# 4. Verify. `cuda.is_available()` is False on a login node — check it in a job.
source .venv/bin/activate
python -c "import torch; print(torch.__version__)"   # expect 2.12.0+cu126
semgrep --version                                     # expect 1.85.0
python -c "import bitsandbytes, accelerate"           # must not raise
srun --account=<your-slurm-account> --partition=gpu-a100 \
     --ntasks=1 --gpus-per-task=1 --time=00:05:00 \
     python -c "import torch; print(torch.cuda.is_available())"   # expect True
```

> **Never run a bare `uv sync` afterwards.** It reverts torch to the CPU wheel —
> every GPU job then fails — and prunes the extras' helper packages, which is how
> Semgrep silently starts reporting zero findings. If it happens, re-run steps 2
> and 3.

The exact package set behind the thesis results is frozen in
`scripts/setup/venv_packages_delftblue.txt` (180 pins, including
`torch==2.12.0+cu126` and the matching `nvidia-*-cu12` stack). Use it to
reproduce the environment byte-for-byte rather than re-resolving:

```bash
uv pip install --index-url https://download.pytorch.org/whl/cu126 \
               --extra-index-url https://pypi.org/simple \
               -r scripts/setup/venv_packages_delftblue.txt
```

Two host-specific inputs live outside the venv and must be staged separately on
a new account: the offline Hugging Face model cache (`/scratch/$USER/models/hub/`,
populated on a login node — jobs run offline and will not download) and the
Semgrep rule directory (`/scratch/$USER/semgrep-rules/security-audit`, via
`scripts/setup/download_semgrep_security_audit_rules.sh`).

Two values are also hard-coded in the SLURM wrappers and must be changed on a
different account: `#SBATCH --account=` and the `REPO_ROOT` default (also used by
the `--output`/`--error` header paths). `REPO_ROOT` is overridable by
environment variable; the `#SBATCH` lines are not, so edit them.

---

## 8. Reproducibility guarantees and limitations

**Deterministic given the same `--seed`:**

- Rule-based mutator behaviour and the seeded search draws.
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

`--seed`, the exact model revision (for the local backend), library versions,
the Git commit, map/rule hashes, and Semgrep provenance are recorded in
`run_config.json`. For the final local-model matrix, the shared initialization
bundle additionally restores the search, mutator, and Torch RNG states at the
five-candidate boundary.

The output-token cap is fixed at 4096 and recorded in `run_config.json`.
`finish_reason` is saved per task. The final maps carry the reviewed eligibility,
stochastic-screening, and temperature-zero qualification evidence that fixes
their task membership and analysis language. If one
candidate output is invalid, that task receives its baseline score; an invalid
baseline or evaluator/system error aborts rather than being counted as a clean
zero-finding result.

---

## 9. Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `ANTHROPIC_API_KEY is not set` | `.env` missing or unfilled | `cp .env.example .env`, add the key |
| `Semgrep not installed or not in PATH` | venv not active when calling `.venv/bin/python` directly | `source .venv/bin/activate`, or run via `uv run …`, or prefix `PATH="$PWD/.venv/bin:$PATH"`; the run aborts rather than recording zero findings |
| `Mutator preflight failed for 'synonym_replacement'` | WordNet or the NLTK POS tagger is absent (compute nodes cannot fetch it) | On an internet-connected/login node run `python -m nltk.downloader wordnet omw-1.4 averaged_perceptron_tagger averaged_perceptron_tagger_eng`; the experiment aborts before model inference instead of silently using identity mutations |
| `pytest` missing after `uv sync --extra analysis` | uv pruned the `dev` extra | `uv sync --extra dev --extra analysis` (combine extras) |
| `FileNotFoundError: project-codeguard/...` | submodule not initialised | `git submodule update --init --recursive` |
| Docker build fails on `COPY project-codeguard` | same — submodule empty | initialise the submodule before `docker build` |
| Rate-limited (429 / 529) | provider throttling | wait and retry; the run saves all completed iterations and exits gracefully |
