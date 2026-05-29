#!/usr/bin/env python3
"""
Single-run analysis → report figures + tables (schema_version 2).

Produces, for ONE experiment run directory:

  Text (stdout + <out>/summary.md)
    - overview: optimizer, language(s), seed, iterations, best f1
    - cost: wall time, LLM calls, tokens
    - cache hygiene: hit rate, cross-run pollution check (total_entries == misses)
    - search hygiene (EA only): restart reason counts, identity rate, archive size

  RQ1 — does mutation increase findings?
    - per-rule headline table (baseline vs best findings, Δ, winning chain, depth)
    - figure: per-prompt baseline-vs-best finding counts (paired)
    - Wilcoxon signed-rank + McNemar on baseline vs best (all prompts)

  RQ2 — which mutators are most effective?
    - per-mutator table (applications, f1-advancing, effective rate + bootstrap CI)
    - figure: per-mutator effective rate with 95% bootstrap CI error bars

  Trajectory
    - figure: best-so-far f1 over iterations (convergence)

Usage:
    python scripts/analyze/analyze_run.py <run_dir> [--out <dir>]
"""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

sys.path.insert(0, str(Path(__file__).resolve().parent))
import loaders as L
import stats as S


# ---------------------------------------------------------------------------
# Small output helpers
# ---------------------------------------------------------------------------

def write_csv(path: Path, header: list[str], rows: list[list]) -> None:
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(rows)


def md_table(header: list[str], rows: list[list]) -> str:
    out = ["| " + " | ".join(header) + " |",
           "| " + " | ".join("---" for _ in header) + " |"]
    for r in rows:
        out.append("| " + " | ".join(str(c) for c in r) + " |")
    return "\n".join(out)


# ---------------------------------------------------------------------------
# RQ1 — per-prompt baseline vs best
# ---------------------------------------------------------------------------

def rq1_per_rule_table(run: L.RunData) -> list[list]:
    """One row per rule: baseline findings, best findings, Δ, winning chain, depth.

    Restricted to prompts that actually involve the rule (original_rule_ids).
    """
    base = run.baseline()
    base_by_tc = {str(r["test_case_id"]): r for r in base}
    rows: list[list] = []
    for rid, it in sorted(L.per_rule_best(run).items()):
        affected = [
            tc for tc, r in base_by_tc.items()
            if rid in (r.get("rules_used", {}) or {}).get("original_rule_ids", [])
        ]
        base_f = sum(int(base_by_tc[tc]["fitness"]["raw_count"]) for tc in affected)
        it_find = L.iteration_findings(run, it["iter"])
        best_f = sum(int(it_find.get(tc, 0)) for tc in affected)
        rows.append([
            rid.replace("codeguard-", "cg-"),
            len(affected),
            base_f,
            best_f,
            best_f - base_f,
            "+".join(it.get("mutation_chain") or []) or "(none)",
            it.get("chain_length"),
            f'{it["f1"]:+.2f}',
        ])
    return rows


def rq1_paired_findings(run: L.RunData) -> tuple[list[int], list[int], list[str]]:
    """Per-prompt (baseline_count, best_count, language) over all prompts."""
    base = {str(r["test_case_id"]): r for r in run.baseline()}
    bi = L.best_iteration(run)
    if bi is None:
        return [], [], []
    best = L.iteration_findings(run, bi["iter"])
    b_vals, t_vals, langs = [], [], []
    for tc, r in base.items():
        b_vals.append(int(r["fitness"]["raw_count"]))
        t_vals.append(int(best.get(tc, 0)))
        langs.append(r.get("language", "?"))
    return b_vals, t_vals, langs


def fig_rq1(run: L.RunData, out: Path) -> Path | None:
    b, t, langs = rq1_paired_findings(run)
    if not b:
        return None
    fig, ax = plt.subplots(figsize=(7, 4))
    x = range(len(b))
    for i in x:
        ax.plot([0, 1], [b[i], t[i]], color="lightgray", lw=0.8, zorder=1)
    ax.scatter([0] * len(b), b, label="baseline (original rule)", zorder=2)
    ax.scatter([1] * len(t), t, label="best mutation", zorder=2)
    ax.set_xticks([0, 1]); ax.set_xticklabels(["baseline", "best"])
    ax.set_ylabel("Semgrep findings per prompt")
    ax.set_title(f"RQ1 — per-prompt findings: baseline vs best\n{run.name}")
    ax.legend()
    p = out / "rq1_baseline_vs_best.png"
    fig.tight_layout(); fig.savefig(p, dpi=120); plt.close(fig)
    return p


# ---------------------------------------------------------------------------
# RQ2 — per-mutator effectiveness
# ---------------------------------------------------------------------------

def rq2_table(run: L.RunData) -> list[list]:
    outcomes = L.per_mutator_outcomes(run)
    rows: list[list] = []
    for m in sorted(outcomes):
        ov = outcomes[m]
        point, lo, hi = S.bootstrap_ci(ov)
        rows.append([m, len(ov), sum(ov), f"{point:.3f}", f"[{lo:.3f}, {hi:.3f}]"])
    return rows


def fig_rq2(run: L.RunData, out: Path) -> Path | None:
    outcomes = L.per_mutator_outcomes(run)
    if not outcomes:
        return None
    names = sorted(outcomes)
    pts, los, his = [], [], []
    for m in names:
        p, lo, hi = S.bootstrap_ci(outcomes[m])
        pts.append(p); los.append(p - lo); his.append(hi - p)
    fig, ax = plt.subplots(figsize=(8, 4))
    ax.bar(range(len(names)), pts, yerr=[los, his], capsize=4)
    ax.set_xticks(range(len(names)))
    ax.set_xticklabels([n.replace("_", "\n") for n in names], fontsize=8)
    ax.set_ylabel("f1-advancing rate")
    credit = "last-mutator" if run.strategy == "ea" else "whole-chain"
    ax.set_title(f"RQ2 — per-mutator effective rate ({credit} credit, 95% bootstrap CI)\n{run.name}")
    p = out / "rq2_mutator_effective_rate.png"
    fig.tight_layout(); fig.savefig(p, dpi=120); plt.close(fig)
    return p


# ---------------------------------------------------------------------------
# Trajectory
# ---------------------------------------------------------------------------

def fig_convergence(run: L.RunData, out: Path) -> Path | None:
    conv = L.convergence(run)
    if not conv:
        return None
    xs, ys = zip(*conv)
    fig, ax = plt.subplots(figsize=(7, 4))
    ax.plot(xs, ys, marker="o", ms=3)
    ax.set_xlabel("iteration"); ax.set_ylabel("best-so-far f1 (total_semgrep_delta)")
    ax.set_title(f"Convergence — {run.name}")
    p = out / "convergence.png"
    fig.tight_layout(); fig.savefig(p, dpi=120); plt.close(fig)
    return p


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------

def analyze(run: L.RunData, out: Path) -> str:
    out.mkdir(parents=True, exist_ok=True)
    lines: list[str] = [f"# Analysis — {run.name}\n"]

    # Overview / cost / hygiene
    s = run.summary
    lines.append("## Overview")
    lines.append(f"- optimizer/strategy: **{run.strategy}**  |  languages: {run.languages or 'all'}  |  seed: {run.seed}")
    lines.append(f"- iterations run: {s.get('num_iterations_run')} / {s.get('max_iterations')}")
    lines.append(f"- best f1 (total_semgrep_delta): **{L.best_f1(run):+.2f}** (first reached at iter {L.iter_to_first_best(run)})")
    lines.append("\n## Cost")
    lines.append(f"- wall time: {s.get('total_time_seconds')}s  |  LLM calls: {s.get('total_llm_calls')}  "
                 f"|  tokens: {s.get('total_input_tokens')} in / {s.get('total_output_tokens')} out")
    cache = L.cache_stats(run)
    hits, misses, total = cache.get("hits", 0), cache.get("misses", 0), cache.get("total_entries", 0)
    hit_rate = hits / (hits + misses) if (hits + misses) else 0.0
    pollution = "OK (total_entries == misses)" if total == misses else f"⚠️ total_entries={total} != misses={misses}"
    lines.append("\n## Cache hygiene")
    lines.append(f"- hit rate: {hit_rate:.1%} ({hits} hits / {misses} misses)  |  cross-run pollution: {pollution}")
    if run.strategy == "ea":
        lines.append("\n## Search hygiene (EA)")
        lines.append(f"- restart reasons: {L.restart_reason_counts(run)}")
        lines.append(f"- identity rate: {L.identity_rate(run):.1%}")
        arch = run.final_archive().get("archives", {})
        sizes = {rid: len(rec.get("current_entries", [])) for rid, rec in arch.items()}
        lines.append(f"- final archive sizes: {sizes}")

    # RQ1
    lines.append("\n## RQ1 — per-rule findings (baseline → best)")
    r1 = rq1_per_rule_table(run)
    header1 = ["rule", "prompts", "base_find", "best_find", "Δ", "winning_chain", "chain_len", "best_f1"]
    write_csv(out / "rq1_per_rule.csv", header1, r1)
    lines.append(md_table(header1, r1) if r1 else "(no rules)")
    b, t, _ = rq1_paired_findings(run)
    if b:
        pos = [x > 0 for x in b]; pos_t = [x > 0 for x in t]
        lines.append("\n**Paired tests (all prompts, baseline vs best):**")
        lines.append(f"- {S.wilcoxon_paired(b, t)}")
        lines.append(f"- {S.mcnemar_binary(pos, pos_t)}")
    f = fig_rq1(run, out)
    if f:
        lines.append(f"\n![RQ1]({f.name})")

    # RQ2
    lines.append("\n## RQ2 — per-mutator effectiveness")
    r2 = rq2_table(run)
    header2 = ["mutator", "applications", "f1_advancing", "effective_rate", "95%_CI"]
    write_csv(out / "rq2_per_mutator.csv", header2, r2)
    lines.append(md_table(header2, r2) if r2 else "(no mutator applications)")
    f = fig_rq2(run, out)
    if f:
        lines.append(f"\n![RQ2]({f.name})")

    # Trajectory
    f = fig_convergence(run, out)
    if f:
        lines.append(f"\n## Trajectory\n![convergence]({f.name})")

    text = "\n".join(lines) + "\n"
    (out / "summary.md").write_text(text, encoding="utf-8")
    return text


def main() -> int:
    ap = argparse.ArgumentParser(description="Single-run SBST analysis → figures + tables")
    ap.add_argument("run_dir", type=Path)
    ap.add_argument("--out", type=Path, default=None, help="Output dir (default: <run_dir>/analysis)")
    args = ap.parse_args()
    run = L.load_run(args.run_dir)
    out = args.out or (args.run_dir / "analysis")
    print(analyze(run, out))
    print(f"\n📁 Figures + tables written to {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
