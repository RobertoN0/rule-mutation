# Replication Package

This document is the reviewer-facing entry point for reproducing the
experiments from the thesis **without DelftBlue access**.

The framework supports two execution paths:

| Path | Where it runs | What it uses | Reproducible? |
|---|---|---|---|
| **A. API-based** (this doc) | Any laptop / VM | OpenAI / Anthropic / Groq API | ✅ Yes |
| **B. Local GPU**            | DelftBlue A100 nodes | HuggingFace + transformers + bitsandbytes | ❌ Cluster-only |

All reproducibility claims in this document refer to **Path A**.

---

## Prerequisites

You need:

1. **Git** (≥ 2.30) — to clone the repository and initialise submodules.
2. **One of**:
   - [`uv`](https://docs.astral.sh/uv/) ≥ 0.5 — the recommended Python manager
     (one-line install: `curl -LsSf https://astral.sh/uv/install.sh | sh`), or
   - **Docker** ≥ 24 — if you prefer a sealed image.
3. **An LLM API key** for at least one provider:
   - **Anthropic Claude** (recommended) — `claude-haiku-4-5` is cheapest and is
     used by the default smoke test.
   - **OpenAI** — e.g. `gpt-4o-mini`.
   - **Groq** — free tier available at https://console.groq.com.

No GPU, no DelftBlue account, no HuggingFace authentication is required for
the default replication path. The CyberSecEval dataset is fetched
automatically from the HuggingFace Hub at runtime.

---

## 1. Clone the repository

```bash
git clone https://github.com/<your-org>/Thesis-rules-codeguard.git
cd Thesis-rules-codeguard

# project-codeguard contains the security rule library and is a submodule
git submodule update --init --recursive
```

## 2. Configure secrets

```bash
cp .env.example .env
$EDITOR .env   # fill in at least one of ANTHROPIC_API_KEY / OPENAI_API_KEY / GROQ_API_KEY
```

The `.env` file is git-ignored. Never commit API keys.

## 3. Pick a path

### Path A1 — uv (recommended)

```bash
# Install all API-only dependencies into a project-local .venv
uv sync

# Smoke test (one Claude Haiku call, ~256 tokens, well under a cent)
uv run python scripts/validation/validate_claude.py
```

Expected output ends with `🎉 Claude backend is wired up correctly.`

For a tiny end-to-end pipeline run (1 case, 1 iteration), see §5.

### Path A2 — Docker

```bash
docker build -t codeguard-sbst:replication .

# Smoke test inside the container
docker run --rm --env-file .env codeguard-sbst:replication

# Run a tiny experiment, persisting results back to the host
docker run --rm \
    --env-file .env \
    -v "$(pwd)/results:/app/results" \
    codeguard-sbst:replication \
    python scripts/experiments/run_with_rules_map.py \
        --interesting-cases pipeline_breakdown/generation_results/interesting_cases_96_sonnet_4_6.json \
        --rules-map        pipeline_breakdown/rule_retrieval_output/retrieval_map_96_sonnet_4_6.json \
        --backend claude --model claude-haiku-4-5 \
        --n-cases 1 --iterations 1 \
        --output-dir results/docker_smoke
```

---

## 4. What gets installed

`pyproject.toml` declares two dependency surfaces:

- **Default (`uv sync`)** — API-only path. Pulls in `anthropic`, `openai`,
  `semgrep`, `datasets`, `pandas`, and the rule-retrieval agent framework.
  Total install ≈ 500 MB.
- **`[gpu]` extras (`uv sync --extra gpu`)** — pulls in `torch`,
  `transformers`, `accelerate`, `bitsandbytes`. **Only needed on DelftBlue.**
  Total install ≈ 4 GB.

Exact versions are pinned in `uv.lock` (committed). The same lockfile is
consumed by the Dockerfile (`uv sync --frozen --no-dev`).

---

## 5. Tiny end-to-end run

Once the smoke test passes you can reproduce one prompt's worth of pipeline:

```bash
uv run python scripts/experiments/run_with_rules_map.py \
    --interesting-cases pipeline_breakdown/generation_results/interesting_cases_96_sonnet_4_6.json \
    --rules-map        pipeline_breakdown/rule_retrieval_output/retrieval_map_96_sonnet_4_6.json \
    --backend claude --model claude-haiku-4-5 \
    --n-cases 1 --iterations 1 \
    --output-dir results/replication_smoke \
    --seed 42
```

This makes ≤ 2 API calls (1 baseline + 1 mutation) and writes
`results/replication_smoke/intermediate_results/*.json` containing the
generated code, Semgrep findings, and fitness score.

> **Note:** the `--backend claude` flag requires the Claude backend to be
> registered in `scripts/experiments/run_with_rules_map.py`. That wiring is
> tracked in [bd-4l1](../) and is done in a separate commit — see
> "Pipeline integration status" below.

---

## 6. Pipeline integration status

The replication package (this commit) ships:

- ✅ `pyproject.toml` + `uv.lock` + `.python-version` (deterministic install)
- ✅ `Dockerfile` + `.dockerignore` (sealed alternative)
- ✅ `.env.example` (secret template)
- ✅ `src/llm_backends/claude_backend.py` (Anthropic backend implementation)
- ✅ `scripts/validation/validate_claude.py` (smoke test, runnable standalone)

The following follow-up wiring lives in a separate commit so the replication
package can be reviewed independently of pipeline changes:

- ⏳ Register `ClaudeBackend` in `src/llm_backends/__init__.py`.
- ⏳ Add `--backend claude` / `--backend openai` choices to
  `scripts/experiments/run_with_rules_map.py`.
- ⏳ Optional: an `OpenAIBackend` mirroring the Claude backend.

Until the follow-up commit lands, `validate_claude.py` is sufficient to
verify the API-only execution environment.

---

## 7. Reproducibility guarantees and limitations

**Guaranteed deterministic** given the same seed:

- Mutator behaviour (`--seed N`).
- Test-case selection order (`--selection first` or `--selection random
  --seed N`).
- Semgrep findings on the same generated source (Semgrep is deterministic).

**Not guaranteed bit-identical**:

- LLM outputs across runs. Even at `temperature=0` providers reserve the
  right to change weights, batching, or sampling internals; intermediate
  results are stored verbatim per run so analyses can be repeated on saved
  artifacts.
- Generated code byte-equality across LLM provider versions.

**Provider drift mitigations**:

- `intermediate_results/*.json` saves the exact generated code and Semgrep
  findings, so downstream analyses do not need to re-call the LLM.
- `--seed` is recorded in the experiment summary.

---

## 8. Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `ANTHROPIC_API_KEY is not set` | `.env` missing or unfilled | `cp .env.example .env`, fill in the key |
| `Rate-limited / overloaded` | Anthropic 429 or 529 | Wait a few seconds and retry; for Haiku this is rare under replication load |
| `semgrep: command not found` | `uv sync` not run, or running outside the venv | `uv run …` instead of bare `python …`, or `source .venv/bin/activate` |
| `FileNotFoundError: project-codeguard/...` | Submodule not initialised | `git submodule update --init --recursive` |
| Docker build fails on `COPY project-codeguard` | Same — submodule empty | Initialise the submodule before `docker build` |

---

## 9. Citation

If you use this replication package, please cite the thesis (citation block
TBD — to be added on submission).
