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
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import loaders as L
import stats as S
from report.tables import md_table, write_csv
from viz.style import plt


# ---------------------------------------------------------------------------
# RQ1 — per-prompt baseline vs best
# ---------------------------------------------------------------------------

def rq1_per_rule_table(run: L.RunData) -> list[list]:
    """One row per rule: baseline findings, best findings, Δ, winning chain, depth.

    Restricted to prompts that actually involve the rule (original_rule_ids).
    """
    base = run.baseline()
    base_by_tc = {str(r["test_case_id"]): r for r in base}
    worst = L.per_rule_worst(run)
    rows: list[list] = []
    for rid, it in sorted(L.per_rule_best(run).items()):
        affected = [
            tc for tc, r in base_by_tc.items()
            if rid in (r.get("rules_used", {}) or {}).get("original_rule_ids", [])
        ]
        base_f = sum(int(base_by_tc[tc]["fitness"]["raw_count"]) for tc in affected)
        it_find = L.iteration_findings(run, it["iter"])
        best_f = sum(int(it_find.get(tc, 0)) for tc in affected)
        wit = worst.get(rid)
        rows.append([
            rid.replace("codeguard-", "cg-"),
            len(affected),
            base_f,
            best_f,
            best_f - base_f,
            "+".join(it.get("mutation_chain") or []) or "(none)",
            it.get("chain_length"),
            f'{it["f1"]:+.2f}',
            f'{wit["f1"]:+.2f}' if wit else "+0.00",
            ("+".join(wit.get("mutation_chain") or []) or "(none)") if wit else "(none)",
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


def fig_per_rule_fitness(run: L.RunData, out: Path) -> Path | None:
    """Per-rule fitness reach: the most-adversarial (max f1, red →) and the
    most-defensive (min f1, green ←) result the search found for each rule."""
    best = L.per_rule_best(run)
    worst = L.per_rule_worst(run)
    rids = sorted(set(best) | set(worst))
    if not rids:
        return None
    labels = [r.replace("codeguard-", "cg-") for r in rids]
    best_v = [float(best.get(r, {}).get("f1", 0.0) or 0.0) for r in rids]
    worst_v = [float(worst.get(r, {}).get("f1", 0.0) or 0.0) for r in rids]

    fig, ax = plt.subplots(figsize=(7, 0.32 * len(rids) + 1.5))
    ax.barh(labels, best_v, color="#c73e3a", label="best f1 (most vulnerable)")
    ax.barh(labels, worst_v, color="#3d8f5f", label="safest f1 (most defensive)")
    ax.axvline(0, color="#333333", linewidth=0.8)
    ax.set_xlabel("f1 = total_semgrep_delta vs baseline")
    ax.set_title(f"Per-rule fitness reach — {run.name}")
    ax.tick_params(labelsize=8)
    ax.grid(True, axis="x", alpha=0.25, linewidth=0.4)
    ax.legend(fontsize=8, loc="lower right")
    p = out / "per_rule_fitness.png"
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

    # RQ1 significance — does the best mutation systematically change findings?
    lines.append("\n## RQ1 significance — paired tests (baseline vs best)")
    lines.append("_For each prompt: finding count under the original rules vs. at the run's best "
                 "(most-adversarial) iteration. Low p = the best mutation significantly increases findings._")
    b, t, _ = rq1_paired_findings(run)
    if b:
        pos = [x > 0 for x in b]; pos_t = [x > 0 for x in t]
        lines.append(f"- {S.wilcoxon_paired(b, t)}")
        lines.append(f"- {S.mcnemar_binary(pos, pos_t)}")
    else:
        lines.append("(no prompts)")

    # Per-rule fitness reach (most-adversarial vs most-defensive per rule) — the headline figure
    f = fig_per_rule_fitness(run, out)
    if f:
        lines.append("\n## Per-rule fitness reach (best vs safest)")
        lines.append("_Per rule: red = most-vulnerable f1 reached (→), green = safest/most-negative f1 (←); "
                     "0 = the original rule. Bars left of 0 = rephrasings made the model write safer code._")
        lines.append(f"![per-rule fitness]({f.name})")

    # RQ1 detail table (long; for drill-down)
    lines.append("\n## RQ1 — per-rule findings (table)")
    r1 = rq1_per_rule_table(run)
    header1 = ["rule", "prompts", "base_find", "best_find", "Δ", "winning_chain", "chain_len",
               "best_f1", "safest_f1", "safest_chain"]
    write_csv(out / "rq1_per_rule.csv", header1, r1)
    lines.append(md_table(header1, r1) if r1 else "(no rules)")

    # RQ2
    lines.append("\n## RQ2 — per-mutator effectiveness")
    lines.append("_effective_rate = fraction of a mutator's applications that increased f1; "
                 "95% CI is a bootstrap interval (wide = few applications)._")
    r2 = rq2_table(run)
    header2 = ["mutator", "applications", "f1_advancing", "effective_rate", "95%_CI"]
    write_csv(out / "rq2_per_mutator.csv", header2, r2)
    lines.append(md_table(header2, r2) if r2 else "(no mutator applications)")
    f = fig_rq2(run, out)
    if f:
        lines.append(f"\n![RQ2]({f.name})")

    # Convergence (best-so-far f1 over iterations) — kept for drill-down
    f = fig_convergence(run, out)
    if f:
        lines.append(f"\n## Convergence (secondary)\n![convergence]({f.name})")

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
