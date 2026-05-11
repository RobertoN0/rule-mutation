#!/usr/bin/env python3
"""
Multi-job comparison for hill-climbing experiment results.

Usage:
    # Compare all jobs in results/ directory
    python scripts/analyze/compare_jobs.py experiments/results/

    # Compare specific jobs
    python scripts/analyze/compare_jobs.py \
        experiments/results/job9801047_*/ \
        experiments/results/job9801048_*/

    # Compare by language
    python scripts/analyze/compare_jobs.py experiments/results/ --group-by language

    # Compare by strategy
    python scripts/analyze/compare_jobs.py experiments/results/ --group-by strategy

Grouping keys (--group-by):
    language        python vs java
    strategy        round_robin vs ducb vs greedy_batch
    mutator         single-mutator pool name (from run_config)
    model           LLM model used
    n_cases         number of test cases

Comparison metrics reported:
    - Original / best fitness per job and per group mean
    - Fitness delta and improvement rate (% jobs that improved)
    - Iterations run vs max (completion rate)
    - Cache hit rate
    - Wall time per iteration
    - Per-group bandit arm winner (highest mean_reward)
    - Vulnerability delta: best_vulnerable - original_vulnerable
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# Loader (shared with analyze_job.py but kept self-contained)
# ---------------------------------------------------------------------------

def _find_file(job_dir: Path, pattern: str) -> Path | None:
    matches = sorted(job_dir.glob(pattern))
    return matches[-1] if matches else None


def load_job_summary(job_dir: Path) -> dict[str, Any] | None:
    """Load only the lightweight files (no intermediates)."""
    job: dict[str, Any] = {"dir": job_dir, "name": job_dir.name}

    p = _find_file(job_dir, "hillclimb_summary_*.json")
    if not p:
        return None
    job["summary"] = json.loads(p.read_text())

    p = _find_file(job_dir, "hillclimb_per_rule_*.json")
    job["per_rule"] = json.loads(p.read_text()) if p else {}

    p = _find_file(job_dir, "per_prompt_rules_results_*.json")
    if p:
        d = json.loads(p.read_text())
        job["per_prompt_summary"] = d.get("summary", {})
        job["per_prompt_metadata"] = d.get("metadata", {})
    else:
        job["per_prompt_summary"] = {}
        job["per_prompt_metadata"] = {}

    p = job_dir / "run_config.json"
    job["run_config"] = json.loads(p.read_text()) if p.exists() else {}
    job["args"] = job["run_config"].get("args", {})

    return job


def extract_group_key(job: dict, group_by: str) -> str:
    """Return the grouping key for a job."""
    s = job["summary"]
    a = job["args"]
    if group_by == "language":
        langs = a.get("languages") or []
        return ", ".join(sorted(langs)) if langs else "?"
    elif group_by == "strategy":
        return s.get("mutator_strategy", a.get("mutator_strategy", "?")) or "?"
    elif group_by == "mutator":
        muts = s.get("mutators") or a.get("mutators") or ["?"]
        return ", ".join(sorted(muts))
    elif group_by == "model":
        return s.get("llm_model", a.get("model", "?"))
    elif group_by == "n_cases":
        return str(a.get("n_cases", "?"))
    return "all"


# ---------------------------------------------------------------------------
# Metrics extraction
# ---------------------------------------------------------------------------

def job_metrics(job: dict) -> dict[str, Any]:
    s = job["summary"]
    a = job["args"]
    pp = job["per_prompt_summary"]
    pr = job["per_rule"].get("per_rule", {})
    ec = s.get("eval_cache_stats", {})

    orig = s.get("original_fitness", 0.0)
    best = s.get("best_fitness", 0.0)
    delta = best - orig
    n_iters = s.get("num_iterations_run", 0) or 1
    max_iters = s.get("max_iterations", a.get("iterations", 1)) or 1
    wall = s.get("total_time_seconds", 0)

    hits = ec.get("hits", 0)
    misses = ec.get("misses", 0)
    total_lookups = hits + misses

    # Best arm from bandit
    arm_stats = s.get("pool_arm_stats", {})
    arms = arm_stats.get("arms", {})
    best_arm = max(arms, key=lambda k: arms[k].get("mean_reward", 0), default=None) if arms else None
    best_arm_reward = arms[best_arm].get("mean_reward", 0.0) if best_arm else 0.0

    # Improvement rate across per-rule
    n_improved_rules = sum(1 for e in pr.values() if e.get("best_fitness_delta", 0) > 0)
    n_rules = len(pr)

    return {
        "name": job["name"],
        "language": ", ".join(sorted(a.get("languages") or ["?"])),
        "strategy": s.get("mutator_strategy", a.get("mutator_strategy", "?")),
        "mutators": ", ".join(sorted(s.get("mutators", a.get("mutators", ["?"])))),
        "n_cases": a.get("n_cases", "?"),
        "model": s.get("llm_model", a.get("model", "?")),
        "original_fitness": orig,
        "best_fitness": best,
        "fitness_delta": delta,
        "improved": delta > 0,
        "iterations_run": n_iters,
        "max_iterations": max_iters,
        "completion_rate": n_iters / max_iters,
        "wall_seconds": wall,
        "secs_per_iter": wall / n_iters,
        "cache_hit_rate": hits / total_lookups if total_lookups > 0 else None,
        "total_llm_calls": s.get("total_llm_calls", 0),
        "orig_vulnerable": pp.get("original_vulnerable", "?"),
        "best_vulnerable": pp.get("best_vulnerable", "?"),
        "best_arm": best_arm,
        "best_arm_reward": best_arm_reward,
        "rules_improved": n_improved_rules,
        "rules_total": n_rules,
    }


# ---------------------------------------------------------------------------
# Display helpers
# ---------------------------------------------------------------------------

def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _pct(num: float, den: float) -> str:
    if den == 0:
        return "N/A"
    return f"{num/den*100:.1f}%"


def _fmt_s(s: float) -> str:
    if s < 60:
        return f"{s:.0f}s"
    if s < 3600:
        return f"{s/60:.1f}m"
    return f"{s/3600:.1f}h"


# ---------------------------------------------------------------------------
# Report sections
# ---------------------------------------------------------------------------

def report_per_job_table(metrics: list[dict]) -> str:
    lines = ["\n  PER-JOB SUMMARY"]
    hdr = f"  {'Job':<50} {'Lang':>8} {'Orig':>6} {'Best':>6} {'Δ':>5} {'Iters':>8} {'Complete':>9} {'CacheHit':>9} {'s/iter':>7}"
    lines.append(hdr)
    lines.append("  " + "─" * len(hdr))

    for m in sorted(metrics, key=lambda x: -x["fitness_delta"]):
        short = m["name"][-48:] if len(m["name"]) > 50 else m["name"]
        cache_str = f"{m['cache_hit_rate']*100:.0f}%" if m["cache_hit_rate"] is not None else "N/A"
        lines.append(
            f"  {short:<50} {m['language']:>8} {m['original_fitness']:>6.1f} {m['best_fitness']:>6.1f} "
            f"{m['fitness_delta']:>+5.1f} {m['iterations_run']:>4}/{m['max_iterations']:<4} "
            f"{_pct(m['iterations_run'], m['max_iterations']):>9} "
            f"{cache_str:>9} {m['secs_per_iter']:>7.1f}"
        )
    return "\n".join(lines)


def report_group_comparison(metrics: list[dict], group_by: str) -> str:
    groups: dict[str, list[dict]] = defaultdict(list)
    for m in metrics:
        key = m.get("strategy") if group_by == "strategy" else m.get("language") if group_by == "language" else m.get("mutators", "?")
        groups[key].append(m)

    lines = [f"\n  GROUP COMPARISON  (by {group_by})"]
    lines.append(f"  {'Group':<35} {'N':>3} {'Orig':>7} {'Best':>7} {'ΔMean':>7} {'Improved%':>10} {'CompRate':>9} {'CacheHit':>9}")
    lines.append("  " + "─" * 85)

    for grp, items in sorted(groups.items()):
        n = len(items)
        orig_mean = _mean([m["original_fitness"] for m in items])
        best_mean = _mean([m["best_fitness"] for m in items])
        delta_mean = _mean([m["fitness_delta"] for m in items])
        improved = sum(1 for m in items if m["improved"])
        comp_mean = _mean([m["completion_rate"] for m in items])
        cache_rates = [m["cache_hit_rate"] for m in items if m["cache_hit_rate"] is not None]
        cache_str = f"{_mean(cache_rates)*100:.0f}%" if cache_rates else "N/A"
        lines.append(
            f"  {grp:<35} {n:>3} {orig_mean:>7.1f} {best_mean:>7.1f} {delta_mean:>+7.1f} "
            f"{_pct(improved, n):>10} {comp_mean*100:>8.1f}% {cache_str:>9}"
        )
    return "\n".join(lines)


def report_bandit_comparison(metrics: list[dict]) -> str:
    bandit_jobs = [m for m in metrics if m["best_arm"] is not None]
    if not bandit_jobs:
        return "\n  BANDIT: no bandit jobs found (or arm stats missing)"

    lines = ["\n  BANDIT ARM WINNERS  (per job)"]
    lines.append(f"  {'Job':<50} {'Best Arm':<35} {'Reward':>8}")
    lines.append("  " + "─" * 95)

    for m in sorted(bandit_jobs, key=lambda x: -x["best_arm_reward"]):
        short = m["name"][-48:] if len(m["name"]) > 50 else m["name"]
        lines.append(f"  {short:<50} {m['best_arm']:<35} {m['best_arm_reward']:>8.4f}")
    return "\n".join(lines)


def report_vulnerability_delta(metrics: list[dict]) -> str:
    lines = ["\n  VULNERABILITY DELTA (vulnerable prompts: original → best)"]
    lines.append(f"  {'Job':<50} {'Orig':>6} {'Best':>6} {'Δ':>5}")
    lines.append("  " + "─" * 70)

    for m in sorted(metrics, key=lambda x: -(
        (x["best_vulnerable"] - x["orig_vulnerable"])
        if isinstance(x["best_vulnerable"], (int, float)) and isinstance(x["orig_vulnerable"], (int, float))
        else 0
    )):
        short = m["name"][-48:] if len(m["name"]) > 50 else m["name"]
        ov = m["orig_vulnerable"]
        bv = m["best_vulnerable"]
        delta_str = f"{bv - ov:+d}" if isinstance(bv, int) and isinstance(ov, int) else "?"
        lines.append(f"  {short:<50} {str(ov):>6} {str(bv):>6} {delta_str:>5}")
    return "\n".join(lines)


def report_rules_improvement(jobs: list[dict]) -> str:
    """Aggregate per-rule improvement across all jobs."""
    rule_deltas: dict[str, list[float]] = defaultdict(list)
    rule_divs: dict[str, list[float]] = defaultdict(list)

    for job in jobs:
        for rid, entry in job["per_rule"].get("per_rule", {}).items():
            rule_deltas[rid].append(entry.get("best_fitness_delta", 0.0))
            rule_divs[rid].append(entry.get("best_mean_code_divergence", 0.0))

    if not rule_deltas:
        return "\n  CROSS-JOB RULE BREAKDOWN: no per_rule data found"

    lines = ["\n  CROSS-JOB RULE BREAKDOWN"]
    lines.append(f"  {'Rule':<42} {'N':>3} {'MeanΔ':>7} {'MaxΔ':>7} {'MeanDiv':>8} {'MaxDiv':>8}")
    lines.append("  " + "─" * 78)

    for rid in sorted(rule_deltas, key=lambda r: -_mean(rule_deltas[r])):
        short = rid.replace("codeguard-", "cg-")[:41]
        deltas = rule_deltas[rid]
        divs = rule_divs[rid]
        lines.append(
            f"  {short:<42} {len(deltas):>3} {_mean(deltas):>+7.1f} {max(deltas):>+7.1f} "
            f"{_mean(divs):>8.3f} {max(divs):>8.3f}"
        )
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "paths", nargs="+", type=Path,
        help="Job result directories or a single parent directory containing job dirs"
    )
    parser.add_argument(
        "--group-by", choices=["language", "strategy", "mutator", "model", "n_cases"],
        default="language", help="Grouping dimension for comparison (default: language)"
    )
    parser.add_argument(
        "--format", choices=["text", "json"], default="text",
        help="Output format"
    )
    parser.add_argument(
        "--min-iters", type=int, default=0,
        help="Exclude jobs with fewer than N iterations run"
    )
    args = parser.parse_args()

    # Resolve job directories
    job_dirs: list[Path] = []
    for p in args.paths:
        if p.is_dir():
            # If it looks like a job directory (has hillclimb_summary), use directly
            if list(p.glob("hillclimb_summary_*.json")):
                job_dirs.append(p)
            else:
                # Treat as parent directory
                for child in sorted(p.iterdir()):
                    if child.is_dir() and list(child.glob("hillclimb_summary_*.json")):
                        job_dirs.append(child)

    if not job_dirs:
        print("ERROR: no job directories with hillclimb_summary_*.json found", file=sys.stderr)
        sys.exit(1)

    jobs = [j for p in job_dirs if (j := load_job_summary(p)) is not None]
    if args.min_iters > 0:
        jobs = [j for j in jobs if j["summary"].get("num_iterations_run", 0) >= args.min_iters]

    print(f"\nLoaded {len(jobs)} jobs", file=sys.stderr)

    metrics = [job_metrics(j) for j in jobs]

    if args.format == "json":
        print(json.dumps(metrics, indent=2))
        return

    print(report_per_job_table(metrics))
    print(report_group_comparison(metrics, args.group_by))
    print(report_vulnerability_delta(metrics))
    print(report_bandit_comparison(metrics))
    print(report_rules_improvement(jobs))


if __name__ == "__main__":
    main()
