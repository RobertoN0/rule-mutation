"""
Cost / operational analysis (G5): wall time, LLM calls, token burn, eval-cache
effectiveness, per-prompt latency, and budget-matched best-f1 (the same
truncation used for the Qwen-vs-Llama matched comparison — never compare runs at
different iteration counts).

Pure compute: returns row lists, never writes or plots.
"""

from __future__ import annotations

import statistics

import loaders as L
from metrics.outcomes import lang_key

COST_HEADER = [
    "run", "strategy", "language", "seed", "iterations", "wall_time_h",
    "llm_calls", "input_tokens", "output_tokens", "cache_hit_rate",
    "tokens_per_iter", "sec_per_iter",
]
LATENCY_HEADER = ["run", "prompts", "gen_ms_mean", "gen_ms_median", "analysis_ms_mean", "analysis_ms_median"]


def cost_row(run: L.RunData) -> list:
    s = run.summary
    cache = s.get("eval_cache_stats", {}) or {}
    hits = int(cache.get("hits", 0) or 0)
    misses = int(cache.get("misses", 0) or 0)
    total = hits + misses
    n = int(s.get("num_iterations_run") or len(L.valid_iters(run)))
    wall = float(s.get("total_time_seconds", 0) or 0)
    inp = int(s.get("total_input_tokens", 0) or 0)
    out = int(s.get("total_output_tokens", 0) or 0)
    return [
        run.run_dir.name, run.strategy, lang_key(run), run.seed, n,
        round(wall / 3600, 3),
        int(s.get("total_llm_calls", 0) or 0), inp, out,
        round(hits / total, 4) if total else 0.0,
        round((inp + out) / n, 1) if n else 0.0,
        round(wall / n, 1) if n else 0.0,
    ]


def latency_row(run: L.RunData) -> list:
    recs = run.baseline()
    gen = [float(r["generation_latency_ms"]) for r in recs if r.get("generation_latency_ms")]
    ana = [float(r["analysis_latency_ms"]) for r in recs if r.get("analysis_latency_ms")]
    return [
        run.run_dir.name, len(recs),
        round(statistics.mean(gen), 1) if gen else 0.0,
        round(statistics.median(gen), 1) if gen else 0.0,
        round(statistics.mean(ana), 1) if ana else 0.0,
        round(statistics.median(ana), 1) if ana else 0.0,
    ]


def best_f1_at(run: L.RunData, max_iter: int) -> float:
    """Best f1 reached within the first ``max_iter`` iterations (budget cap)."""
    best = 0.0
    for it in L.valid_iters(run):
        if int(it.get("iter", 0)) <= max_iter:
            best = max(best, float(it.get("f1") or 0.0))
    return best


def budget_rows(runs: list[L.RunData], budgets: list[int]) -> tuple[list[str], list[list]]:
    """Matched-budget best-f1 per run. Returns (header, rows)."""
    header = ["run", "strategy", "seed"] + [f"best_f1@{b}" for b in budgets]
    rows = [
        [run.run_dir.name, run.strategy, run.seed] + [best_f1_at(run, b) for b in budgets]
        for run in runs
    ]
    return header, rows


def matched_budgets(runs: list[L.RunData], n: int = 4) -> list[int]:
    """``n`` evenly-spaced budgets up to the shortest run (so comparisons are fair)."""
    counts = [len(L.valid_iters(run)) for run in runs if L.valid_iters(run)]
    if not counts:
        return []
    shortest = min(counts)
    return sorted({max(1, round(shortest * (i + 1) / n)) for i in range(n)})
