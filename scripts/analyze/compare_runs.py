#!/usr/bin/env python3
"""
Cross-run analysis → RQ3 (EA vs random) + multi-seed aggregation (schema_version 2).

Given several run directories (or parent dirs containing them), groups runs by
(language, seed, strategy) and produces:

  RQ3 — does the (1+1) EA outperform random selection?
    - per-seed best-f1 table (strategy × language × seed; + iter-to-first-best, LLM calls)
    - figure: per-seed best f1, paired EA vs random (one line per seed)
    - paired sign test on EA-minus-random best-f1 across matched seeds
    - figure: convergence band — best-so-far f1 over iterations, median + IQR
      across seeds, one band per strategy (per language)

  RQ2 (cross-strategy) — per-mutator effective rate, EA vs random (adjacent bars)

  Cost — per-run wall time / LLM calls / tokens table

  Multi-seed aggregation — median + IQR of best-f1 per (strategy, language)

Usage:
    python scripts/analyze/compare_runs.py <run_dir_or_parent> [<more> ...] [--out <dir>]
"""

from __future__ import annotations

import argparse
import csv
import statistics
import sys
from collections import defaultdict
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import loaders as L
import stats as S


def _lang_key(run: L.RunData) -> str:
    return ",".join(run.languages) if run.languages else "all"


def write_csv(path: Path, header, rows) -> None:
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f); w.writerow(header); w.writerows(rows)


def md_table(header, rows) -> str:
    out = ["| " + " | ".join(header) + " |", "| " + " | ".join("---" for _ in header) + " |"]
    out += ["| " + " | ".join(str(c) for c in r) + " |" for r in rows]
    return "\n".join(out)


def _iqr_band(curves: list[list[float]]) -> tuple[list[float], list[float], list[float]]:
    """Median + p25/p75 across best-so-far curves (forward-filled to max length)."""
    if not curves:
        return [], [], []
    T = max(len(c) for c in curves)
    filled = []
    for c in curves:
        c = list(c) + ([c[-1]] * (T - len(c)) if c else [0.0] * T)
        filled.append(c)
    arr = np.asarray(filled, float)
    med = np.median(arr, axis=0).tolist()
    lo = np.quantile(arr, 0.25, axis=0).tolist()
    hi = np.quantile(arr, 0.75, axis=0).tolist()
    return med, lo, hi


def compare(runs: list[L.RunData], out: Path) -> str:
    out.mkdir(parents=True, exist_ok=True)
    lines = ["# Cross-run comparison\n", f"Runs: {len(runs)}\n"]

    by_strategy: dict[str, list[L.RunData]] = defaultdict(list)
    best: dict[tuple, float] = {}        # (lang, seed, strategy) -> best_f1
    for r in runs:
        by_strategy[r.strategy].append(r)
        best[(_lang_key(r), r.seed, r.strategy)] = L.best_f1(r)

    # ---- Per-seed best table ----
    lines.append("## RQ3 — per-seed best f1")
    header = ["language", "seed", "strategy", "best_f1", "iter_to_first_best", "llm_calls"]
    rows = []
    for r in sorted(runs, key=lambda x: (_lang_key(x), str(x.seed), x.strategy)):
        rows.append([_lang_key(r), r.seed, r.strategy, f"{L.best_f1(r):+.2f}",
                     L.iter_to_first_best(r), r.summary.get("total_llm_calls")])
    write_csv(out / "rq3_per_seed_best.csv", header, rows)
    lines.append(md_table(header, rows))

    # ---- Paired EA vs random ----
    langs = sorted({_lang_key(r) for r in runs})
    deltas = []
    pair_rows = []
    for lang in langs:
        seeds = sorted({s for (lg, s, st) in best if lg == lang})
        for seed in seeds:
            ea = best.get((lang, seed, "ea"))
            rd = best.get((lang, seed, "random_baseline"))
            if ea is not None and rd is not None:
                deltas.append(ea - rd)
                pair_rows.append([lang, seed, f"{ea:+.2f}", f"{rd:+.2f}", f"{ea - rd:+.2f}"])
    if pair_rows:
        lines.append("\n**EA vs random (matched seeds):**")
        lines.append(md_table(["language", "seed", "ea_best", "rand_best", "ea−rand"], pair_rows))
        lines.append(f"\n- {S.sign_test(deltas)}")
        if len(deltas) >= 2:
            lines.append(f"- {S.wilcoxon_paired([0]*len(deltas), deltas)}")
        f = _fig_paired(best, langs, out)
        if f:
            lines.append(f"\n![RQ3 paired]({f.name})")
    else:
        lines.append("\n_(no matched EA/random seed pairs — need both strategies at the same seed+language)_")

    # ---- Convergence bands ----
    cfigs = _fig_convergence_bands(by_strategy, runs, out)
    for f in cfigs:
        lines.append(f"\n![convergence]({f.name})")

    # ---- RQ2 cross-strategy ----
    lines.append("\n## RQ2 — per-mutator effective rate (EA vs random)")
    r2_rows, r2_fig = _rq2_cross(by_strategy, out)
    lines.append(md_table(["mutator", "ea_rate", "ea_n", "rand_rate", "rand_n"], r2_rows) if r2_rows else "(no data)")
    if r2_fig:
        lines.append(f"\n![RQ2 cross]({r2_fig.name})")

    # ---- Cost ----
    lines.append("\n## Cost per run")
    cheader = ["run", "strategy", "seed", "wall_s", "llm_calls", "in_tok", "out_tok"]
    crows = [[r.name, r.strategy, r.seed, r.summary.get("total_time_seconds"),
              r.summary.get("total_llm_calls"), r.summary.get("total_input_tokens"),
              r.summary.get("total_output_tokens")] for r in runs]
    write_csv(out / "cost.csv", cheader, crows)
    lines.append(md_table(cheader, crows))

    # ---- Multi-seed aggregation ----
    lines.append("\n## Multi-seed aggregation (median best-f1 [IQR])")
    agg_rows = []
    grp: dict[tuple, list[float]] = defaultdict(list)
    for (lang, seed, st), v in best.items():
        grp[(lang, st)].append(v)
    for (lang, st), vals in sorted(grp.items()):
        med = statistics.median(vals)
        lo = min(vals); hi = max(vals)
        agg_rows.append([lang, st, len(vals), f"{med:+.2f}", f"[{lo:+.2f}, {hi:+.2f}]"])
    lines.append(md_table(["language", "strategy", "n_seeds", "median_best_f1", "range"], agg_rows))

    text = "\n".join(lines) + "\n"
    (out / "comparison.md").write_text(text, encoding="utf-8")
    return text


def _fig_paired(best: dict, langs: list[str], out: Path) -> Path | None:
    fig, ax = plt.subplots(figsize=(6, 4))
    plotted = False
    for lang in langs:
        seeds = sorted({s for (lg, s, st) in best if lg == lang})
        for seed in seeds:
            ea = best.get((lang, seed, "ea")); rd = best.get((lang, seed, "random_baseline"))
            if ea is not None and rd is not None:
                ax.plot([0, 1], [rd, ea], marker="o", label=f"{lang} s{seed}")
                plotted = True
    if not plotted:
        plt.close(fig); return None
    ax.set_xticks([0, 1]); ax.set_xticklabels(["random", "ea"])
    ax.set_ylabel("best f1 (total_semgrep_delta)")
    ax.set_title("RQ3 — best f1 per seed, paired")
    ax.legend(fontsize=7)
    p = out / "rq3_paired_best.png"
    fig.tight_layout(); fig.savefig(p, dpi=120); plt.close(fig)
    return p


def _fig_convergence_bands(by_strategy: dict, runs: list[L.RunData], out: Path) -> list[Path]:
    figs: list[Path] = []
    langs = sorted({_lang_key(r) for r in runs})
    for lang in langs:
        fig, ax = plt.subplots(figsize=(7, 4))
        any_band = False
        for st, st_runs in sorted(by_strategy.items()):
            curves = [[y for _, y in L.convergence(r)] for r in st_runs if _lang_key(r) == lang]
            curves = [c for c in curves if c]
            if not curves:
                continue
            med, lo, hi = _iqr_band(curves)
            xs = range(1, len(med) + 1)
            ax.plot(xs, med, label=f"{st} (median, n={len(curves)})")
            ax.fill_between(xs, lo, hi, alpha=0.2)
            any_band = True
        if not any_band:
            plt.close(fig); continue
        ax.set_xlabel("iteration"); ax.set_ylabel("best-so-far f1")
        ax.set_title(f"Convergence band — {lang}")
        ax.legend(fontsize=8)
        p = out / f"convergence_band_{lang.replace(',', '_')}.png"
        fig.tight_layout(); fig.savefig(p, dpi=120); plt.close(fig)
        figs.append(p)
    return figs


def _rq2_cross(by_strategy: dict, out: Path):
    def agg(st_runs):
        acc: dict[str, list[int]] = defaultdict(list)
        for r in st_runs:
            for m, ov in L.per_mutator_outcomes(r).items():
                acc[m].extend(ov)
        return acc
    ea = agg(by_strategy.get("ea", []))
    rd = agg(by_strategy.get("random_baseline", []))
    names = sorted(set(ea) | set(rd))
    rows = []
    for m in names:
        e = ea.get(m, []); r = rd.get(m, [])
        er = (sum(e) / len(e)) if e else float("nan")
        rr = (sum(r) / len(r)) if r else float("nan")
        rows.append([m, f"{er:.3f}", len(e), f"{rr:.3f}", len(r)])
    if not names:
        return rows, None
    fig, ax = plt.subplots(figsize=(9, 4))
    x = np.arange(len(names)); w = 0.4
    ax.bar(x - w / 2, [(sum(ea.get(m, [])) / len(ea[m])) if ea.get(m) else 0 for m in names], w, label="ea")
    ax.bar(x + w / 2, [(sum(rd.get(m, [])) / len(rd[m])) if rd.get(m) else 0 for m in names], w, label="random")
    ax.set_xticks(x); ax.set_xticklabels([n.replace("_", "\n") for n in names], fontsize=7)
    ax.set_ylabel("f1-advancing rate"); ax.set_title("RQ2 — per-mutator effective rate (EA vs random)")
    ax.legend()
    p = out / "rq2_cross_strategy.png"
    fig.tight_layout(); fig.savefig(p, dpi=120); plt.close(fig)
    return rows, p


def main() -> int:
    ap = argparse.ArgumentParser(description="Cross-run SBST comparison (RQ3 + multi-seed)")
    ap.add_argument("paths", nargs="+", type=Path, help="Run dirs or parent dirs")
    ap.add_argument("--out", type=Path, default=Path("analysis_output/compare"))
    args = ap.parse_args()
    runs = L.discover_runs(args.paths)
    if not runs:
        print("No runs found.", file=sys.stderr); return 1
    print(compare(runs, args.out))
    print(f"\n📁 Figures + tables written to {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
