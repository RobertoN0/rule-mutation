#!/usr/bin/env python3
"""
Single-job analysis for hill-climbing experiment results.

Usage:
    python scripts/analyze/analyze_job.py experiments/results/job9801047_*/
    python scripts/analyze/analyze_job.py experiments/results/job9801047_*/ --format json
    python scripts/analyze/analyze_job.py experiments/results/job9801047_*/ --section bandit

Sections (use --section to print only one):
    overview        Run metadata + top-level fitness outcome
    efficiency      Iteration throughput, cache hit rate, LLM call rate
    rules           Per-rule best delta + code divergence + prompts affected
    bandit          Arm pull counts, mean reward, exploration balance (DECAYING_UCB)
    compounding     Mutation depth + saturation state per rule
    divergence      Code divergence distribution: mean, zero-div prompts, per-rule best
    vulns           Vulnerability type breakdown (check_ids frequency from intermediates)
    latency         Generation and analysis latency distributions from intermediates
    identity        Detected identity mutations per mutator (from intermediate logs)
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# Loader helpers
# ---------------------------------------------------------------------------

def _find_file(job_dir: Path, pattern: str) -> Path | None:
    matches = sorted(job_dir.glob(pattern))
    return matches[-1] if matches else None


def load_job(job_dir: Path) -> dict[str, Any]:
    """Load all output files from a job directory into a single dict."""
    job = {"dir": job_dir, "name": job_dir.name}

    p = _find_file(job_dir, "hillclimb_summary_*.json")
    job["summary"] = json.loads(p.read_text()) if p else {}

    p = _find_file(job_dir, "hillclimb_per_rule_*.json")
    job["per_rule"] = json.loads(p.read_text()) if p else {}

    p = _find_file(job_dir, "per_prompt_rules_results_*.json")
    job["per_prompt"] = json.loads(p.read_text()) if p else {}

    p = job_dir / "run_config.json"
    job["run_config"] = json.loads(p.read_text()) if p.exists() else {}

    # Intermediate results — lazy: list paths, load on demand
    ir_dir = job_dir / "intermediate_results"
    if ir_dir.exists():
        job["intermediate_paths"] = sorted(ir_dir.glob("*.json"))
    else:
        job["intermediate_paths"] = []

    return job


def load_intermediates(job: dict) -> list[dict]:
    """Load all intermediate result files."""
    results = []
    for p in job["intermediate_paths"]:
        try:
            results.append(json.loads(p.read_text()))
        except json.JSONDecodeError:
            pass
    return results


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------

def _bar(value: float, max_val: float, width: int = 20) -> str:
    if max_val == 0:
        return "─" * width
    filled = int(round(value / max_val * width))
    return "█" * filled + "░" * (width - filled)


def _pct(num: float, den: float) -> str:
    if den == 0:
        return "N/A"
    return f"{num/den*100:.1f}%"


def _fmt_seconds(s: float) -> str:
    if s < 60:
        return f"{s:.1f}s"
    if s < 3600:
        return f"{s/60:.1f}m"
    return f"{s/3600:.1f}h"


# ---------------------------------------------------------------------------
# Analysis sections
# ---------------------------------------------------------------------------

def section_overview(job: dict) -> str:
    s = job["summary"]
    rc = job["run_config"]
    args = rc.get("args", {})
    lines = ["=" * 72, f"JOB: {job['name']}", "=" * 72]

    lines.append(f"  Model:      {s.get('llm_model', args.get('model', '?'))}")
    lines.append(f"  Strategy:   {s.get('mutator_strategy', args.get('mutator_strategy', '?'))}")
    lines.append(f"  Mutators:   {', '.join(s.get('mutators', args.get('mutators', ['?'])))}")
    lines.append(f"  Language:   {', '.join(args.get('languages', ['?']))}")
    lines.append(f"  Cases:      {args.get('n_cases', '?')}")
    lines.append(f"  Iters:      {s.get('num_iterations_run', '?')}/{s.get('max_iterations', args.get('iterations', '?'))}")
    lines.append(f"  Seed:       {args.get('seed', '?')}")
    lines.append(f"  Git SHA:    {rc.get('git_sha', '?')[:10]}")
    lines.append("")

    orig = s.get("original_fitness", 0.0)
    best = s.get("best_fitness", 0.0)
    delta = best - orig
    pct = (delta / orig * 100) if orig > 0 else 0.0

    lines.append("  FITNESS OUTCOME")
    lines.append(f"  {'Original':20s} {orig:.1f}")
    lines.append(f"  {'Best':20s} {best:.1f}")
    lines.append(f"  {'Delta':20s} {delta:+.1f}  ({pct:+.1f}%)")

    pp = job["per_prompt"].get("summary", {})
    if pp:
        orig_v = pp.get("original_vulnerable", "?")
        best_v = pp.get("best_vulnerable", "?")
        lines.append(f"  {'Vulnerable prompts':20s} {orig_v} → {best_v}")

    lines.append(f"  {'Wall time':20s} {_fmt_seconds(s.get('total_time_seconds', 0))}")
    return "\n".join(lines)


def section_efficiency(job: dict) -> str:
    s = job["summary"]
    n_iters = s.get("num_iterations_run", 0) or 1
    wall = s.get("total_time_seconds", 0)
    llm_calls = s.get("total_llm_calls", 0)
    ec = s.get("eval_cache_stats", {})

    lines = ["\n  EFFICIENCY"]
    lines.append(f"  {'Wall time':30s} {_fmt_seconds(wall)}")
    lines.append(f"  {'Time per iteration':30s} {_fmt_seconds(wall / n_iters)}")
    lines.append(f"  {'Total LLM calls':30s} {llm_calls}")
    lines.append(f"  {'LLM calls per iteration':30s} {llm_calls / n_iters:.2f}")

    if ec:
        hits = ec.get("hits", 0)
        misses = ec.get("misses", 0)
        total_lookups = hits + misses
        lines.append(f"  {'Cache hits':30s} {hits}/{total_lookups} ({_pct(hits, total_lookups)})")
        lines.append(f"  {'Cache entries':30s} {ec.get('total_entries', '?')}")
    return "\n".join(lines)


def section_rules(job: dict) -> str:
    pr = job["per_rule"]
    if not pr:
        return "\n  PER-RULE: no per_rule file found"

    lines = ["\n  PER-RULE BREAKDOWN"]
    lines.append(f"  {'Rule':<42} {'Iters':>5} {'BestΔ':>7} {'BestDiv':>8} {'Prompts':>8}")
    lines.append("  " + "─" * 72)

    per_rule = pr.get("per_rule", {})
    # Sort by best_fitness_delta descending
    for rid, entry in sorted(per_rule.items(), key=lambda kv: -kv[1].get("best_fitness_delta", 0)):
        short = rid.replace("codeguard-", "cg-")[:41]
        iters = entry.get("iterations_targeted", 0)
        best_d = entry.get("best_fitness_delta", 0.0)
        best_div = entry.get("best_mean_code_divergence", 0.0)
        n_aff = entry.get("num_prompts_affected", 0)
        lines.append(
            f"  {short:<42} {iters:>5} {best_d:>+7.1f} {best_div:>8.3f} {n_aff:>8}"
        )

    # Improvement fraction
    improved = sum(1 for e in per_rule.values() if e.get("best_fitness_delta", 0) > 0)
    lines.append(f"\n  Rules improved:  {improved}/{len(per_rule)} ({_pct(improved, len(per_rule))})")
    lines.append(f"  Rules with div>0: {sum(1 for e in per_rule.values() if e.get('best_mean_code_divergence', 0) > 0)}/{len(per_rule)}")
    return "\n".join(lines)


def section_bandit(job: dict) -> str:
    s = job["summary"]
    arm_stats = s.get("pool_arm_stats")
    if not arm_stats:
        return "\n  BANDIT: not available (single-mutator or no arm stats)"

    strategy = arm_stats.get("strategy", "?")
    total_pulls = arm_stats.get("total_pulls", 0)
    gamma = arm_stats.get("gamma")

    lines = [f"\n  BANDIT ARMS  (strategy={strategy}, gamma={gamma}, total_pulls={total_pulls})"]
    lines.append(f"  {'Arm':<40} {'Pulls':>6} {'%Total':>7} {'MeanReward':>11} {'TotalReward':>12} {'Bar'}")
    lines.append("  " + "─" * 80)

    arms = arm_stats.get("arms", {})
    max_reward = max((v.get("mean_reward", 0) for v in arms.values()), default=1.0) or 1.0

    for arm_key, stats in sorted(arms.items(), key=lambda kv: -kv[1].get("pulls", 0)):
        pulls = stats.get("pulls", 0)
        mean_r = stats.get("mean_reward", 0.0)
        total_r = stats.get("total_reward", 0.0)
        bar = _bar(mean_r, max_reward, width=16)
        lines.append(
            f"  {arm_key:<40} {pulls:>6} {_pct(pulls, total_pulls):>7} {mean_r:>11.4f} {total_r:>12.3f} {bar}"
        )

    # Exploration uniformity: std dev of pulls
    pull_counts = [v.get("pulls", 0) for v in arms.values()]
    if pull_counts and len(pull_counts) > 1:
        mean_p = sum(pull_counts) / len(pull_counts)
        std_p = math.sqrt(sum((x - mean_p) ** 2 for x in pull_counts) / len(pull_counts))
        lines.append(f"\n  Pull distribution: mean={mean_p:.1f}, std={std_p:.1f}, cv={std_p/mean_p:.2f} (cv→0 = uniform)")

    # Non-zero reward arms
    active = sum(1 for v in arms.values() if v.get("mean_reward", 0) > 0)
    lines.append(f"  Arms with mean_reward>0: {active}/{len(arms)}")
    return "\n".join(lines)


def section_compounding(job: dict) -> str:
    s = job["summary"]
    comp = s.get("compounding_state")
    if not comp:
        return "\n  COMPOUNDING: not available"

    lines = ["\n  COMPOUNDING STATE"]
    lines.append(f"  {'Rule':<42} {'Depth':>5} {'Saturated':>10}")
    lines.append("  " + "─" * 60)

    saturated_count = 0
    for rid, state in sorted(comp.items()):
        short = rid.replace("codeguard-", "cg-")[:41]
        depth = state.get("depth", 0)
        sat = state.get("saturated", False)
        if sat:
            saturated_count += 1
        sat_str = "★ YES" if sat else "no"
        lines.append(f"  {short:<42} {depth:>5} {sat_str:>10}")

    lines.append(f"\n  Saturated rules: {saturated_count}/{len(comp)}")
    return "\n".join(lines)


def section_divergence(job: dict) -> str:
    """Code divergence metrics — from intermediate results."""
    intermediates = load_intermediates(job)
    if not intermediates:
        return "\n  DIVERGENCE: no intermediate results found"

    mutation_results = [r for r in intermediates if str(r.get("phase", "")).startswith("mutation")]
    if not mutation_results:
        return "\n  DIVERGENCE: no mutation intermediates found"

    divs = [r["fitness"].get("code_divergence", 0.0) for r in mutation_results]
    non_zero = [d for d in divs if d > 0.0]
    zero_count = len(divs) - len(non_zero)

    lines = ["\n  CODE DIVERGENCE  (from intermediate mutation results)"]
    lines.append(f"  Total mutation evals:      {len(divs)}")
    lines.append(f"  Zero divergence:           {zero_count} ({_pct(zero_count, len(divs))})")
    lines.append(f"  Non-zero divergence:       {len(non_zero)} ({_pct(len(non_zero), len(divs))})")

    if non_zero:
        mean_div = sum(non_zero) / len(non_zero)
        sorted_d = sorted(non_zero)
        p25 = sorted_d[len(sorted_d) // 4]
        p50 = sorted_d[len(sorted_d) // 2]
        p75 = sorted_d[3 * len(sorted_d) // 4]
        lines.append(f"  Mean (non-zero):           {mean_div:.4f}")
        lines.append(f"  P25 / P50 / P75:           {p25:.4f} / {p50:.4f} / {p75:.4f}")
        lines.append(f"  Max:                       {max(non_zero):.4f}")

    # Per-mutator divergence (from mutation_changes context — not directly available)
    # Use per-rule best from per_rule file if available
    pr = job["per_rule"].get("per_rule", {})
    if pr:
        lines.append("\n  Per-rule best_mean_code_divergence:")
        for rid, entry in sorted(pr.items(), key=lambda kv: -kv[1].get("best_mean_code_divergence", 0)):
            short = rid.replace("codeguard-", "cg-")[:41]
            lines.append(f"    {short:<42} {entry.get('best_mean_code_divergence', 0.0):.4f}")

    return "\n".join(lines)


def section_vulns(job: dict) -> str:
    """Vulnerability check_id frequency from intermediate results."""
    intermediates = load_intermediates(job)
    if not intermediates:
        return "\n  VULNS: no intermediate results found"

    baseline = [r for r in intermediates if r.get("phase") == "baseline"]
    mutations = [r for r in intermediates if str(r.get("phase", "")).startswith("mutation")]

    def _count_checks(records: list[dict]) -> Counter:
        c: Counter = Counter()
        for r in records:
            for check_id in r.get("fitness", {}).get("check_ids", []):
                c[check_id] += 1
        return c

    base_checks = _count_checks(baseline)
    mut_checks = _count_checks(mutations)

    all_checks = set(base_checks) | set(mut_checks)
    lines = ["\n  VULNERABILITY CHECK_ID BREAKDOWN"]
    lines.append(f"  {'Check ID (last 2 segments)':<52} {'Baseline':>9} {'Mutation':>9} {'Delta':>7}")
    lines.append("  " + "─" * 80)

    for cid in sorted(all_checks, key=lambda c: -(mut_checks.get(c, 0) - base_checks.get(c, 0))):
        b = base_checks.get(cid, 0)
        m = mut_checks.get(cid, 0)
        delta = m - b
        # Shorten long check IDs (keep last 2 dot-separated segments)
        parts = cid.split(".")
        short_cid = ".".join(parts[-2:]) if len(parts) >= 2 else cid
        short_cid = short_cid[:51]
        lines.append(f"  {short_cid:<52} {b:>9} {m:>9} {delta:>+7}")

    lines.append(f"\n  Baseline evals: {len(baseline)}, Mutation evals: {len(mutations)}")
    lines.append(f"  Distinct check_ids: {len(all_checks)}")
    return "\n".join(lines)


def section_latency(job: dict) -> str:
    """Generation and analysis latency from intermediate results."""
    intermediates = load_intermediates(job)
    if not intermediates:
        return "\n  LATENCY: no intermediate results found"

    def _stats(values: list[float]) -> str:
        if not values:
            return "N/A"
        values = sorted(values)
        mean = sum(values) / len(values)
        p50 = values[len(values) // 2]
        p95 = values[int(len(values) * 0.95)]
        return f"mean={mean/1000:.2f}s  p50={p50/1000:.2f}s  p95={p95/1000:.2f}s  n={len(values)}"

    gen_all = [r.get("generation_latency_ms", 0) for r in intermediates if not r.get("eval_cache_hit")]
    ana_all = [r.get("analysis_latency_ms", 0) for r in intermediates]
    gen_cache = [r.get("generation_latency_ms", 0) for r in intermediates if r.get("eval_cache_hit")]

    lines = ["\n  LATENCY"]
    lines.append(f"  Generation (non-cached):  {_stats(gen_all)}")
    lines.append(f"  Generation (cache hit):   {_stats(gen_cache)}")
    lines.append(f"  Semgrep analysis:         {_stats(ana_all)}")
    return "\n".join(lines)


def section_identity(job: dict) -> str:
    """Identity mutations detected via log scanning."""
    log_files = list(job["dir"].glob("*.out")) + list(job["dir"].glob("*.err"))
    if not log_files:
        return "\n  IDENTITY: no .out/.err log files found"

    identity_lines = []
    for lf in log_files:
        try:
            for line in lf.read_text(errors="replace").splitlines():
                if "produced identity" in line or "identity mutation" in line.lower():
                    identity_lines.append(line.strip())
        except OSError:
            pass

    mutator_counts: Counter = Counter()
    for line in identity_lines:
        # Extract mutator name from log line pattern: "mutator=<name>"
        if "mutator=" in line:
            part = line.split("mutator=")[-1].split(")")[0].split(",")[0].strip()
            mutator_counts[part] += 1

    lines = ["\n  IDENTITY MUTATIONS (from .out log)"]
    lines.append(f"  Total identity log lines: {len(identity_lines)}")
    if mutator_counts:
        lines.append("  Per mutator:")
        for mut, cnt in mutator_counts.most_common():
            lines.append(f"    {mut:<35} {cnt}")
    elif identity_lines:
        lines.append("  (could not parse mutator names from lines)")
        for line in identity_lines[:5]:
            lines.append(f"    {line[:100]}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

SECTIONS = {
    "overview": section_overview,
    "efficiency": section_efficiency,
    "rules": section_rules,
    "bandit": section_bandit,
    "compounding": section_compounding,
    "divergence": section_divergence,
    "vulns": section_vulns,
    "latency": section_latency,
    "identity": section_identity,
}


def _resolve_job_dir(path: Path) -> Path:
    """Given any path (dir or file) inside or equal to a job directory, return the job dir.

    Handles the common shell pitfall where 'job_dir/*/' expands to the contents of
    the directory rather than the directory itself.
    """
    # Walk up until we find a directory containing hillclimb_summary_*.json
    candidate = path if path.is_dir() else path.parent
    for _ in range(4):  # max 4 levels up
        if list(candidate.glob("hillclimb_summary_*.json")):
            return candidate
        candidate = candidate.parent
    return path  # fallback: use as-is and let load_job report the error


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "job_dir", type=Path,
        help="Job result directory (or any file/subdir inside it — glob expansion is handled)"
    )
    parser.add_argument(
        "--section", choices=list(SECTIONS), default=None,
        help="Print only this section (default: all)"
    )
    parser.add_argument(
        "--format", choices=["text", "json"], default="text",
        help="Output format (default: text)"
    )
    parser.add_argument(
        "--no-intermediates", action="store_true",
        help="Skip loading intermediate results (faster, skips vulns/latency/divergence/identity)"
    )
    args = parser.parse_args()

    job_dir = _resolve_job_dir(args.job_dir)
    if not job_dir.exists():
        print(f"ERROR: {job_dir} does not exist", file=sys.stderr)
        sys.exit(1)

    job = load_job(job_dir)

    if args.no_intermediates:
        job["intermediate_paths"] = []

    if args.format == "json":
        out = {
            "job": job["name"],
            "summary": job["summary"],
            "per_rule": job["per_rule"],
            "per_prompt_summary": job["per_prompt"].get("summary", {}),
            "run_config_args": job["run_config"].get("args", {}),
        }
        print(json.dumps(out, indent=2))
        return

    sections_to_run = [args.section] if args.section else list(SECTIONS)
    for sec in sections_to_run:
        print(SECTIONS[sec](job))
        print()


if __name__ == "__main__":
    main()
