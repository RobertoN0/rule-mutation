# syntax=docker/dockerfile:1.7
# =============================================================================
# CodeGuard SBST — Replication Image (API-only)
# =============================================================================
# This image is the "press play" path for thesis reviewers. It ships an
# API-only install (no transformers / torch / bitsandbytes); the local GPU
# backend is intentionally excluded — it requires DelftBlue.
#
# Build:
#   docker build -t codeguard-sbst:replication .
#
# Run the smoke test (single Claude Haiku call, ~1 cent):
#   docker run --rm \
#     --env-file .env \
#     codeguard-sbst:replication
#
# Run a small experiment, persisting results to the host:
#   docker run --rm \
#     --env-file .env \
#     -v "$(pwd)/results:/app/results" \
#     codeguard-sbst:replication \
#     python scripts/experiments/run_with_rules_map.py \
#       --backend claude --optimizer random_baseline \
#       --rules-map pipeline_breakdown/rule_retrieval_output/map_qwen32b_python_java.json \
#       --n-cases 2 --iterations 3 --languages python --seed 42 \
#       --mutators synonym_replacement add_random_word verb_weakening \
#       --output-dir /app/results/docker_smoke
# =============================================================================

FROM python:3.12-slim AS base

# Bring in uv from the official image. Pinned to a known-good release so the
# image is byte-deterministic across rebuilds.
COPY --from=ghcr.io/astral-sh/uv:0.9.29 /uv /usr/local/bin/uv

# System packages:
#   * git           — `git submodule update --init` (project-codeguard) and any
#                     pip-VCS resolutions semgrep may chain.
#   * ca-certificates — outbound HTTPS to Anthropic / OpenAI / HF.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        git \
        ca-certificates \
    && rm -rf /var/lib/apt/lists/*

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/app/.venv \
    PATH="/app/.venv/bin:$PATH" \
    PYTHONPATH="/app"

WORKDIR /app

# --- Dependency layer ------------------------------------------------------
# Copy only the files that affect dependency resolution first so layer cache
# survives source-code changes.
COPY pyproject.toml uv.lock .python-version ./

# --frozen   — must match uv.lock exactly (fails the build on drift)
# --no-dev   — skip dev extras (pytest, ruff)
# (Default install: no extras, so the [gpu] group is NOT pulled in.)
RUN uv sync --frozen --no-dev

# --- Source layer ----------------------------------------------------------
COPY src                 ./src
COPY scripts             ./scripts
COPY project-codeguard   ./project-codeguard
COPY pipeline_breakdown  ./pipeline_breakdown
COPY README.md           ./README.md
COPY REPLICATION.md      ./REPLICATION.md
COPY ARCHITECTURE.md     ./ARCHITECTURE.md
COPY WORKFLOW.md         ./WORKFLOW.md

# Smoke test by default. Override at `docker run` time for real experiments.
CMD ["python", "scripts/validation/validate_claude.py"]
