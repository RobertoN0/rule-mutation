#!/usr/bin/env python3
"""
Vulnerability-repair analysis (minimize direction) — the green-light RQ1 + the
aggregate side of RQ3, on the 20 final runs.

RQ1 (descriptive): per coding task, baseline (original rules, temp-0) vs the
safest findings the search found. How many tasks are driven to zero, the per-task
reduction distribution, and how reproducibly across the 5 seeds — reported on the
full set and on Qwen's own baseline subsets (persistent, variable, never floor).

RQ3 (aggregate complement to best_f1): per-seed tasks-repaired / total weighted
reduction, EA vs random (Mann-Whitney U + Vargha-Delaney A12), plus the Friedman
test across {baseline, EA-best, random-best} and a sampling-breadth confound table.

Temp-0 caveat: every "after" is a repair the SEARCH FOUND, not a temp>0
generalization. Per-task replicate significance is Stage-2 (bd-011).

Usage:
    python scripts/analyze/analyze_repair.py experiments/final \
        --out analysis_output/repair [--no-figures]
"""

from __future__ import annotations

import argparse
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import loaders as L
import stats as S
from metrics import repair as RP
from report.tables import fmt_pct, md_table, write_csv

REPORT_SUBSETS = ("full", "persistent", "variable", "never")

_MWU_A12_REF = (
    "_**Reading MWU + Â₁₂** (EA vs random, 5 seeds each): the **MWU p** tests whether the two arms differ "
    "(significant at **p < 0.05**; with 5v5 the smallest reachable p is 0.0079, so a non-significant p here "
    "often just means underpowered, not 'equal'). **Â₁₂** is the effect size: 0.5 = no difference, "
    "**>0.5 favours EA**, **<0.5 favours random**; magnitude bands are small 0.56/0.44, medium 0.64/0.36, "
    "large 0.71/0.29. Read Â₁₂ as the primary signal at this sample size. Expected/good result: a clear Â away "
    "from 0.5 (guidance helps) OR Â≈0.5 with p≥0.05 (the honest 'guided ≈ random on this landscape')._"
)

_FRIEDMAN_REF = (
    "_**Reading Friedman**: a non-parametric repeated-measures test across the 3 conditions "
    "{baseline, EA-best, random-best} with each coding task as a matched block. **Significant at p < 0.05** = "
    "the three conditions differ systematically across tasks — here that is driven by baseline > both search "
    "arms (i.e. repair works), while EA-best ≈ random-best (no guidance edge). Caveat: at temp-0 each block is "
    "one deterministic value, so this measures spread across the TASK population, not replicate noise — "
    "replicate significance is Stage-2._"
)


def _pct(x):
    return fmt_pct(x) if x is not None else "n/a"


def main() -> int:
    ap = argparse.ArgumentParser(description="Vulnerability-repair analysis (RQ1 + aggregate RQ3)")
    ap.add_argument("paths", nargs="+", type=Path, help="Run dirs or parent dirs")
    ap.add_argument("--out", type=Path, default=Path("analysis_output/repair"))
    ap.add_argument("--subset-dir", type=Path, default=RP.DEFAULT_SUBSET_DIR)
    ap.add_argument("--code-divergence-threshold", type=float, default=0.0)
    ap.add_argument("--no-figures", action="store_true")
    args = ap.parse_args()

    runs = L.discover_runs(args.paths)
    if not runs:
        print("No runs found.", file=sys.stderr)
        return 1
    args.out.mkdir(parents=True, exist_ok=True)

    # rows[lang][tag] = list of per-seed TaskRow lists
    rows: dict[str, dict[str, list]] = defaultdict(lambda: defaultdict(list))
    per_run_csv: list[list] = []
    confounds: list[dict] = []
    for run in runs:
        tr = RP.task_rows(run, args.code_divergence_threshold, args.subset_dir)
        lang = run.languages[0] if run.languages else "?"
        tag = "ea" if run.strategy == "ea" else "rand"
        rows[lang][tag].append(tr)
        confounds.append(RP.confound(run))
        for subset in RP.SUBSETS:
            a = RP.aggregate_repair(tr, subset)
            per_run_csv.append([
                run.name, tag, run.seed, lang, subset, a["n_tasks"], a["n_movable"],
                a["n_repaired"], _pct(a["pct_repaired_of_movable"]),
                round(a["total_delta_score"], 2), a["total_delta_raw"],
                round(a["mean_delta_score_movable"], 3),
            ])

    write_csv(args.out / "per_run_repair.csv",
              ["run", "strategy", "seed", "language", "subset", "n_tasks", "n_movable",
               "n_repaired_to_zero", "pct_repaired_of_movable", "total_delta_weighted",
               "total_delta_raw", "mean_delta_weighted_movable"],
              per_run_csv)
    write_csv(args.out / "confound.csv",
              ["run", "strategy", "seed", "language", "n_iterations", "n_distinct_rules",
               "mean_prompts_affected", "total_prompt_evals"],
              [[c["run"], c["strategy"], c["seed"], c["language"], c["n_iterations"],
                c["n_distinct_rules"], round(c["mean_prompts_affected"], 2),
                c["total_prompt_evals"]] for c in confounds])

    md: list[str] = [
        "# Vulnerability-repair analysis (RQ1 + aggregate RQ3)\n",
        "**What this report answers.** At the level of a single coding task, did rule mutation reduce "
        "vulnerabilities, and does a guided (EA) search repair more than random? This is the RQ1 headline "
        "(how many tasks become non-vulnerable) plus the aggregate side of RQ3.\n",
        "**Key terms.** A task is **movable** if it has ≥1 Semgrep finding at the temp-0 baseline (original "
        "rules). **BEFORE** = that baseline; **AFTER** = the safest findings observed across every rephrasing "
        "of a rule attached to the task. **repaired→0** = driven from ≥1 finding to zero. Subsets come from "
        "Qwen's own 40-seed baseline: **full** = all tasks; **persistent** = vulnerable ≥80% even with the "
        "rule; **variable** = the finding comes and goes across seeds (the borderline band, incl. rule-fixed); "
        "**never** = the floor (should never move).\n",
        "_⚠️ **AFTER is a repair the temp-0 search FOUND** (it exists in the explored rephrasing space), not "
        "proof it generalises. Per-task replicate significance is Stage-2 (bd-011, temp=0.6 reruns)._\n"]

    for lang in sorted(rows):
        md.append(f"\n## {lang}\n")
        ea_by_seed = rows[lang].get("ea", [])
        rd_by_seed = rows[lang].get("rand", [])
        ea_pool = RP.pool_best_across_seeds(ea_by_seed) if ea_by_seed else []
        rd_pool = RP.pool_best_across_seeds(rd_by_seed) if rd_by_seed else []

        # --- RQ1 headline: pooled best-across-seeds repair counts per subset ---
        md.append("### RQ1 — repair reach (pooled best across seeds)\n")
        md.append("_**What & why.** The headline repair count: pooling the best result over all seeds, how many "
                  "movable tasks the search drove to zero findings, split by subset. **How to read:** compare "
                  "`repaired→0` and `% of movable` across subsets — the story is in WHERE repair happens. Expected "
                  "here: the `never` floor stays 0 (sanity check); most repairs land OUTSIDE `persistent` (the "
                  "borderline tasks), so `full` ≫ `persistent`. `Σ weighted removed` = total findings removed "
                  "(ERROR=3, WARNING=1); `median Δ` = the median movable task's reduction (0 means most movable "
                  "tasks are unchanged — the signal is a concentrated minority)._\n")
        head = ["subset", "arm", "n_movable", "repaired→0", "% of movable",
                "Σ weighted removed", "median Δ"]
        body = []
        for subset in REPORT_SUBSETS:
            for tag, pool in (("EA", ea_pool), ("random", rd_pool)):
                if not pool:
                    continue
                a = RP.aggregate_repair(pool, subset)
                body.append([subset, tag, a["n_movable"], a["n_repaired"],
                             _pct(a["pct_repaired_of_movable"]),
                             round(a["total_delta_score"], 1),
                             round(a["median_delta_score_movable"], 2)])
        md.append(md_table(head, body) + "\n")

        # --- RQ3 aggregate: per-seed tasks-repaired EA vs random ---
        md.append("### RQ3 — aggregate global repair, EA vs random (per seed)\n")
        md.append("_**What & why.** The RQ3 complement to best-fitness: instead of the single best rule, count "
                  "each seed's TOTAL repair (tasks driven to zero, and total weighted findings removed) and "
                  "compare the 5 EA seeds vs the 5 random seeds. This rewards breadth of repair, where EA's depth "
                  "could help. **How to read:** the two value-lists are the per-seed results (sorted); then the "
                  "test._\n")
        for subset in ("movable", "persistent", "variable"):
            ea_rep = [RP.aggregate_repair(tr, subset)["n_repaired"] for tr in ea_by_seed]
            rd_rep = [RP.aggregate_repair(tr, subset)["n_repaired"] for tr in rd_by_seed]
            ea_tot = [RP.aggregate_repair(tr, subset)["total_delta_score"] for tr in ea_by_seed]
            rd_tot = [RP.aggregate_repair(tr, subset)["total_delta_score"] for tr in rd_by_seed]
            if not ea_rep or not rd_rep:
                continue
            mw = S.mann_whitney_u(ea_rep, rd_rep)
            a12, mag = S.vargha_delaney_a12(ea_rep, rd_rep)
            mw_t = S.mann_whitney_u(ea_tot, rd_tot)
            a12_t, mag_t = S.vargha_delaney_a12(ea_tot, rd_tot)
            md.append(f"**subset = {subset}**\n")
            md.append(md_table(
                ["metric", "EA per seed", "random per seed", "MWU p", "A12 (EA vs rand)", "magnitude"],
                [["tasks repaired→0", sorted(ea_rep), sorted(rd_rep),
                  f"{mw.p:.3g}" if mw.p is not None else mw.note, f"{a12:.3f}", mag],
                 ["Σ weighted removed", [round(x, 1) for x in sorted(ea_tot)],
                  [round(x, 1) for x in sorted(rd_tot)],
                  f"{mw_t.p:.3g}" if mw_t.p is not None else mw_t.note, f"{a12_t:.3f}", mag_t]]) + "\n")

        md.append(_MWU_A12_REF + "\n")

        # --- Friedman across {baseline, EA-best, random-best} ---
        md.append("### RQ1/RQ3 — Friedman across {baseline, EA-best, random-best}\n")
        md.append(_FRIEDMAN_REF + "\n")
        for subset in ("movable", "persistent", "variable"):
            if not ea_by_seed or not rd_by_seed:
                continue
            tids, base, ea_a, rd_a = RP.three_condition_vectors(ea_by_seed, rd_by_seed, subset)
            fr = S.friedman_test(base, ea_a, rd_a)
            md.append(f"- **{subset}** (n={len(tids)} tasks in both arms): {fr}  "
                      f"_mean weighted findings — baseline {sum(base)/len(base):.2f}, "
                      f"EA-best {sum(ea_a)/len(ea_a):.2f}, random-best {sum(rd_a)/len(rd_a):.2f}_\n"
                      if tids else f"- **{subset}**: no overlapping tasks\n")

        # --- cross-seed consistency ---
        md.append("\n### RQ1 — cross-seed consistency (is a repair reproducible?)\n")
        md.append("_**What & why.** At temp-0 the seeds are 5 independent searches; a repair found in only one "
                  "seed may be luck, one found in all 5 is robust. **How to read:** 'repaired in ALL N seeds' is "
                  "the trustworthy count; a big gap between '≥1 seed' and 'ALL seeds' means fragile, seed-dependent "
                  "repairs. Full per-task detail in the `consistency_*.csv` files._\n")
        for tag, by_seed in (("ea", ea_by_seed), ("rand", rd_by_seed)):
            if not by_seed:
                continue
            for subset in ("movable", "persistent", "variable"):
                cons = RP.cross_seed_consistency(by_seed, subset)
                write_csv(args.out / f"consistency_{lang}_{tag}_{subset}.csv",
                          ["tid", "cwe", "klass", "before_raw", "n_seeds",
                           "n_repaired_seeds", "n_reduced_seeds", "always_repaired",
                           "always_reduced", "mean_delta_raw"],
                          [[c["tid"], c["cwe"], c["klass"], c["before_raw"], c["n_seeds"],
                            c["n_repaired_seeds"], c["n_reduced_seeds"], c["always_repaired"],
                            c["always_reduced"], round(c["mean_delta_raw"], 2)] for c in cons])
                n_all = sum(1 for c in cons if c["always_repaired"])
                n_any = sum(1 for c in cons if c["n_repaired_seeds"] > 0)
                md.append(f"- cross-seed ({tag}, {subset}): {n_any} tasks repaired in "
                          f"≥1 seed, {n_all} repaired in ALL {len(by_seed)} seeds "
                          f"(of {len(cons)} movable)\n")

        # --- confound summary ---
        md.append("\n### RQ3 confound — sampling breadth (mean over seeds)\n")
        md.append("_**What & why.** If EA and random found similar repair but random simply drew more distinct "
                  "rule rephrasings, the RQ3 tie would be a budget artifact, not a real 'guidance doesn't help'. "
                  "This checks it. **How to read:** if the two arms touch a similar `mean n_distinct_rules` and "
                  "`mean n_iterations`, the comparison is fair and the tie is real (the confound is ruled out). A "
                  "large breadth gap in random's favour would instead undercut the RQ3 conclusion._\n")
        c_head = ["arm", "mean n_iterations", "mean n_distinct_rules", "mean prompts/iter"]
        c_body = []
        for tag in ("ea", "rand"):
            cs = [c for c in confounds if c["language"] == lang and c["strategy"] == tag]
            if not cs:
                continue
            c_body.append([tag,
                           round(sum(c["n_iterations"] for c in cs) / len(cs), 1),
                           round(sum(c["n_distinct_rules"] for c in cs) / len(cs), 1),
                           round(sum(c["mean_prompts_affected"] for c in cs) / len(cs), 2)])
        md.append(md_table(c_head, c_body) + "\n")

        # --- figures ---
        if not args.no_figures:
            from viz import repair as VR
            if ea_pool:
                VR.per_task_diff_waterfall(ea_pool, args.out / f"waterfall_{lang}_ea.png",
                                           f"{lang} — per-task findings removed (EA, pooled best)")
                VR.before_after_scatter(ea_pool, args.out / f"scatter_{lang}_ea.png",
                                        f"{lang} — baseline vs safest (EA, pooled best)")
            if rd_pool:
                VR.per_task_diff_waterfall(rd_pool, args.out / f"waterfall_{lang}_rand.png",
                                           f"{lang} — per-task findings removed (random, pooled best)")
            box = {}
            if ea_by_seed:
                box["ea"] = [RP.aggregate_repair(tr, "movable")["n_repaired"] for tr in ea_by_seed]
            if rd_by_seed:
                box["rand"] = [RP.aggregate_repair(tr, "movable")["n_repaired"] for tr in rd_by_seed]
            if len(box) == 2:
                VR.repaired_box(box, args.out / f"repaired_box_{lang}.png",
                                f"{lang} — tasks repaired to zero per seed")
            md.append("\n### Figures\n")
            md.append("_**Waterfall** — one bar per movable task, sorted by findings removed (before − after). "
                      "Dark green = driven to zero, light green = reduced, grey (height 0) = no repair. Read the "
                      "shape: a few tall bars then a long flat tail = a concentrated repair signal on a minority "
                      "of tasks._\n")
            md.append(f"![waterfall ea](waterfall_{lang}_ea.png)\n")
            md.append("_**Scatter** — each task at (baseline findings, safest-observed findings). Points ON the "
                      "diagonal didn't move; points BELOW are safer; a point dropping to the x-axis (y=0) is a "
                      "repair to zero. Clustering near the diagonal = little movement._\n")
            md.append(f"![scatter ea](scatter_{lang}_ea.png)\n")
            md.append("_**Repaired box** — the 5 per-seed 'tasks repaired to zero' counts, EA vs random (dots = "
                      "seeds). Overlapping boxes = no strategy advantage (the RQ3 aggregate finding)._\n")
            md.append(f"![repaired box](repaired_box_{lang}.png)\n")

    (args.out / "repair.md").write_text("".join(md))
    print(f"Repair analysis written to {args.out}")
    print(f"  {args.out / 'repair.md'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
