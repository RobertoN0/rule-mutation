#!/usr/bin/env python3
"""Build the analysis figures from the v2 JSON.

Run with the isolated plot venv (matplotlib is deliberately NOT in the frozen
repo .venv):

    /scratch/rnegro/plotvenv/bin/python /home/rnegro/analysis/make_figures.py

Writes PNG + PDF into /home/rnegro/analysis/figures/.
"""
import json
import os
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D

# Override ANALYSIS_BASE to read/write the figure set somewhere else.
BASE = Path(os.environ.get("ANALYSIS_BASE", "/home/rnegro/analysis"))
REP = BASE / "report"
FIG = BASE / "figures"
FIG.mkdir(exist_ok=True)

STRATA = ["qwen_python", "qwen_java", "llama_python", "llama_java"]
NICE = {
    "qwen_python": "Qwen · Python",
    "qwen_java": "Qwen · Java",
    "llama_python": "Llama · Python",
    "llama_java": "Llama · Java",
}
EA_C, RD_C = "#2f6f9f", "#c8781e"
GRID = dict(alpha=0.25, linewidth=0.6)


def save(fig, name):
    for ext in ("png", "pdf"):
        fig.savefig(FIG / f"{name}.{ext}", dpi=200, bbox_inches="tight")
    plt.close(fig)
    print(f"  wrote {name}.png / .pdf")


def load(n):
    return json.load(open(REP / n))


# --------------------------------------------------------------------------
# Fig 1 - RQ1 magnitude: share of the origin's findings removed
# --------------------------------------------------------------------------
def fig1():
    d = load("rq1_magnitude.json")["strata"]
    fig, ax = plt.subplots(figsize=(7.2, 4.0))
    x = range(len(STRATA))
    w = 0.36
    for off, key, c, lab in (
        (-w / 2, "ea_pct_of_origin", EA_C, "archive EA"),
        (w / 2, "rand_pct_of_origin", RD_C, "random search"),
    ):
        med = [d[s][key]["median"] for s in STRATA]
        lo = [d[s][key]["median"] - d[s][key]["min"] for s in STRATA]
        hi = [d[s][key]["max"] - d[s][key]["median"] for s in STRATA]
        ax.bar([i + off for i in x], med, w, color=c, label=lab, zorder=3)
        ax.errorbar(
            [i + off for i in x], med, yerr=[lo, hi], fmt="none",
            ecolor="#333", elinewidth=1.0, capsize=3, zorder=4,
        )
    ax.set_xticks(list(x))
    ax.set_xticklabels([NICE[s] for s in STRATA])
    ax.set_ylabel("Semgrep findings removed\n(% of the original rules' findings)")
    ax.set_title(
        "RQ1 — best structurally admissible rule-text/order mutations visited\n"
        "bar = median over seeds; whiskers = min–max",
        fontsize=10,
    )
    ax.grid(axis="y", **GRID)
    ax.set_axisbelow(True)
    ax.legend(frameon=False)
    save(fig, "fig1_rq1_magnitude")


# --------------------------------------------------------------------------
# Fig 2 - RQ2 paired per-seed differences (the core result)
# --------------------------------------------------------------------------
def fig2():
    d = load("rq2_ea_vs_random.json")["strata"]
    fig, ax = plt.subplots(figsize=(8.0, 4.8))
    allv = [v for s in STRATA for v in d[s]["deltas_f1"]]
    lo_y, hi_y = min(allv) - 1.5, max(allv) + 4.5
    ax.set_ylim(lo_y, hi_y)
    for i, s in enumerate(STRATA):
        dl = d[s]["deltas_f1"]
        med = d[s]["median_delta"]
        jit = [i + (j - (len(dl) - 1) / 2) * 0.055 for j in range(len(dl))]
        cols = ["#2f6f9f" if v > 0 else ("#999" if v == 0 else "#c0392b") for v in dl]
        ax.scatter(jit, dl, s=34, c=cols, zorder=3, edgecolor="white", linewidth=0.6)
        ax.errorbar(
            i, med["value"],
            yerr=[
                [med["value"] - med["bootstrap_ci"][0]],
                [med["bootstrap_ci"][1] - med["value"]],
            ],
            fmt="_", color="black", markersize=26, elinewidth=1.8, capsize=5, zorder=4,
        )
        # annotations sit on one shared line just under the top of the axes
        ax.annotate(
            f"sign p={d[s]['primary']['p']:.4g}\nPpair={d[s]['paired_superiority']:.2f}",
            (i, hi_y - 0.4), ha="center", va="top", fontsize=8.5, color="#333",
        )
    ax.axhline(0, color="#555", linewidth=1.0, linestyle="--")
    ax.set_xticks(range(len(STRATA)))
    ax.set_xticklabels([f"{NICE[s]}\n(n={d[s]['n']})" for s in STRATA])
    ax.set_ylabel("EA - random  (findings removed)")
    ax.set_title(
        "RQ2 - archive EA vs random search at equal 24 h budget\n"
        "compliant candidates observed post hoc; bar = median with bootstrap 95% CI",
        fontsize=10,
    )
    ax.grid(axis="y", **GRID)
    ax.set_axisbelow(True)
    ax.legend(
        handles=[
            Line2D([], [], marker="o", ls="", color="#2f6f9f", label="EA better"),
            Line2D([], [], marker="o", ls="", color="#999", label="tie"),
            Line2D([], [], marker="o", ls="", color="#c0392b", label="random better"),
        ],
        frameon=False, fontsize=8.5, ncol=3,
        loc="upper center", bbox_to_anchor=(0.5, -0.16),
    )
    save(fig, "fig2_rq2_paired_deltas")


def fig2_tiers():
    """RQ2 specification sensitivity across the three safe-zone lenses."""
    data = load("rq2_safe_zone_tiers.json")
    tier_order = ["raw_executed", "core_structural", "full_contract"]
    tier_labels = ["executed\nsystem", "fenced\ncode", "full\ncontract"]
    ink = "#2b2b2b"
    accent = "#356f8d"
    fig, axes = plt.subplots(1, 4, figsize=(11.6, 2.25), sharex=True, sharey=False)
    for ax, stratum in zip(axes, STRATA):
        tier_rows = [data["tiers"][tier]["strata"][stratum] for tier in tier_order]
        lower = min(0, min(row["median_percentile_bootstrap_ci"][0] for row in tier_rows))
        upper = max(row["median_percentile_bootstrap_ci"][1] for row in tier_rows)
        span = max(1.0, upper - lower)
        ax.set_ylim(lower - 0.07 * span, upper + 0.25 * span)
        for x, tier in enumerate(tier_order):
            row = data["tiers"][tier]["strata"][stratum]
            ci = row["median_percentile_bootstrap_ci"]
            median = row["median_delta"]
            holm_row = data["tiers"][tier]["families"]["primary_sign_test"]["holm"][stratum]
            reject = holm_row["reject"]
            ax.errorbar(
                x,
                median,
                yerr=[[median - ci[0]], [ci[1] - median]],
                fmt="o",
                markersize=6.2,
                markerfacecolor=accent if reject else "white",
                markeredgecolor=accent if reject else ink,
                markeredgewidth=1.25,
                ecolor=accent if reject else ink,
                elinewidth=1.25,
                capsize=3,
                zorder=3,
            )
            p_text = f"{row['sign_test']['p']:.3g}"
            if p_text.startswith("0."):
                p_text = p_text[1:]
            ax.annotate(
                f"p={p_text}",
                (x, ci[1] + 0.045 * span),
                ha="left" if x == 0 else ("right" if x == len(tier_order) - 1 else "center"),
                va="bottom",
                fontsize=9.3,
                color=ink,
            )
        ax.plot(
            range(len(tier_order)),
            [data["tiers"][tier]["strata"][stratum]["median_delta"] for tier in tier_order],
            color="#777",
            linewidth=0.8,
            zorder=2,
        )
        ax.axhline(0, color="#555", linewidth=0.8, linestyle="--", zorder=1)
        ax.set_title(NICE[stratum], fontsize=11.3, pad=3)
        ax.set_xticks(range(len(tier_order)))
        ax.set_xticklabels(tier_labels, fontsize=9.6)
        ax.tick_params(axis="y", labelsize=9.6)
        ax.grid(axis="y", **GRID)
        ax.set_axisbelow(True)
    axes[0].set_ylabel("Median EA - random\n(findings removed)", fontsize=10.5)
    fig.suptitle(
        "RQ2 - EA advantage under nested structural lenses",
        fontsize=12.2,
        y=0.985,
    )
    fig.legend(
        handles=[
            Line2D([], [], marker="o", ls="", markerfacecolor=accent,
                   markeredgecolor=accent, label="Holm rejection"),
            Line2D([], [], marker="o", ls="", markerfacecolor="white",
                   markeredgecolor=ink, label="no Holm rejection"),
        ],
        frameon=False,
        fontsize=9.2,
        loc="upper center",
        bbox_to_anchor=(0.5, 0.89),
        ncol=2,
        handletextpad=0.4,
        columnspacing=1.2,
    )
    fig.subplots_adjust(left=0.072, right=0.995, bottom=0.22, top=0.68, wspace=0.14)
    save(fig, "fig2_rq2_safe_zone_tiers")


# --------------------------------------------------------------------------
# Fig 3 - RQ2 paired common-language effect size
# --------------------------------------------------------------------------
def fig3():
    d = load("rq2_ea_vs_random.json")["strata"]
    fig, ax = plt.subplots(figsize=(6.6, 3.2))
    ys = range(len(STRATA))
    for i, s in enumerate(STRATA):
        value = d[s]["paired_superiority"]
        ax.scatter(value, i, s=95, color=EA_C, zorder=3)
        ax.annotate(f"  {value:.3f}", (value, i), va="center", fontsize=9)
    ax.axvline(0.5, color="#666", ls=":", lw=1)
    ax.annotate("equal wins/ties", (0.5, len(STRATA) - 0.4),
                fontsize=8, color="#666", ha="center")
    ax.set_yticks(list(ys))
    ax.set_yticklabels([NICE[s] for s in STRATA])
    ax.set_xlim(0.45, 0.85)
    ax.set_xlabel("paired superiority = P(EA>random) + 0.5·P(tie), matched by seed")
    ax.set_title("RQ2 — descriptive paired advantage after safe-zone filtering", fontsize=10)
    ax.grid(axis="x", **GRID)
    ax.set_axisbelow(True)
    save(fig, "fig3_rq2_effect_size")


# --------------------------------------------------------------------------
# Fig 4 - RQ3 move families, aggregated at the independent-run level
# --------------------------------------------------------------------------
def fig4():
    d = load("rq3_mutators.json")["level1_single_operator"]
    fig, axes = plt.subplots(2, 2, figsize=(11.0, 7.2), sharex=False)
    for ax, s in zip(axes.ravel(), STRATA):
        ops = d[s]["operators"]
        items = sorted(ops.items(), key=lambda kv: kv[1]["run_mean_delta"]["median"])
        names = [k for k, _ in items]
        effect = [v["run_mean_delta"]["median"] for _, v in items]
        lo = [
            value - v["run_mean_delta"]["q25"]
            for value, (_, v) in zip(effect, items)
        ]
        hi = [
            v["run_mean_delta"]["q75"] - value
            for value, (_, v) in zip(effect, items)
        ]
        y = range(len(names))
        colours = ["#d17c2f" if name == "whole_rule_reorder" else EA_C for name in names]
        ax.scatter(effect, list(y), color=colours, s=42, zorder=4)
        ax.errorbar(
            effect, list(y), xerr=[lo, hi], fmt="none",
            ecolor="#555", elinewidth=2.0, capsize=3.0, zorder=3,
        )
        for i, (_, v) in enumerate(items):
            ax.annotate(
                        f" P+={v['run_positive_rate']['median']:.2f}",
                        (v["run_mean_delta"]["q75"], i),
                        va="center", fontsize=7.5, color="#555")
        ax.axvline(0, color="#666", linewidth=0.9, linestyle="--", zorder=1)
        ax.set_yticks(list(y))
        ax.set_yticklabels(names, fontsize=8.5)
        ax.set_title(f"{NICE[s]}  ({d[s]['total_clean_moves']} clean moves)", fontsize=9.5)
        ax.grid(axis="x", **GRID)
        ax.set_axisbelow(True)
    for ax in axes[1]:
        ax.set_xlabel("median within-run mean Δf1  — IQR across runs")
    fig.suptitle(
        "RQ3 — local changes from text mutation and whole-rule ordering\n"
        "Δf1 > 0 means fewer findings; safe-zone-valid contrasts; orange = inter-rule reorder",
        fontsize=11,
    )
    fig.tight_layout(rect=[0, 0, 1, 0.94])
    save(fig, "fig4_rq3_operators_effectiveness")


# --------------------------------------------------------------------------
# Fig 5 - RQ3 the divergence: being accepted != removing findings
# --------------------------------------------------------------------------
def fig5():
    d = load("rq3_mutators.json")["level1_single_operator"]
    fig, ax = plt.subplots(figsize=(8.2, 5.6))
    marks = {"qwen_python": "o", "qwen_java": "s", "llama_python": "^", "llama_java": "D"}
    for st in STRATA:
        for name, v in d[st]["operators"].items():
            vw = name == "verb_weakening"
            ax.scatter(
                v["archive_acceptance_rate"], v["f1_advance_rate"],
                marker=marks[st], s=58 if vw else 46, alpha=0.9,
                color="#c0392b" if vw else "#7f8c9a",
                edgecolor="white", linewidth=0.5, zorder=4 if vw else 3,
            )
            if vw:
                # stagger labels: the two Java/Python points nearly coincide in y
                off = {"qwen_python": (10, -14, "left"),
                       "qwen_java": (-10, -12, "right"),
                       "llama_python": (-10, 8, "right"),
                       "llama_java": (-10, 10, "right")}[st]
                ax.annotate(
                    f"{NICE[st]}",
                    (v["archive_acceptance_rate"], v["f1_advance_rate"]),
                    xytext=off[:2], textcoords="offset points",
                    fontsize=7.5, color="#c0392b", ha=off[2],
                )
    ax.set_xlim(0.02, 0.78)
    ax.set_xlabel("archive acceptance rate  (how often the move is kept)")
    ax.set_ylabel("positive-delta rate  (how often the move removes findings)")
    ax.set_title(
        "RQ3 - archive acceptance and positive finding reduction differ\n"
        "verb_weakening (red) is highly accepted but usually has a low positive-delta rate;\n"
        "only Llama/Python shows a comparatively favorable local profile", fontsize=10,
    )
    ax.grid(**GRID)
    ax.set_axisbelow(True)
    ax.legend(
        handles=[Line2D([], [], marker=marks[s2], ls="", color="#7f8c9a", label=NICE[s2])
                 for s2 in STRATA]
        + [Line2D([], [], marker="o", ls="", color="#c0392b", label="verb_weakening")],
        frameon=False, fontsize=8.5, loc="upper left", ncol=2,
    )
    save(fig, "fig5_rq3_acceptance_vs_effect")


# --------------------------------------------------------------------------
# Fig 6 - search progress: evaluations spent per arm
# --------------------------------------------------------------------------
def fig6():
    d = load("rq2_ea_vs_random.json")["strata"]
    fig, ax = plt.subplots(figsize=(7.0, 3.8))
    x = range(len(STRATA))
    w = 0.36
    ea = [d[s]["mean_E_ea"] for s in STRATA]
    rd = [d[s]["mean_E_rand"] for s in STRATA]
    ax.bar([i - w / 2 for i in x], ea, w, color=EA_C, label="archive EA", zorder=3)
    ax.bar([i + w / 2 for i in x], rd, w, color=RD_C, label="random search", zorder=3)
    for i, (a, b) in enumerate(zip(ea, rd)):
        ax.annotate(f"{a:.0f}", (i - w / 2, a), ha="center", va="bottom", fontsize=8)
        ax.annotate(f"{b:.0f}", (i + w / 2, b), ha="center", va="bottom", fontsize=8)
    ax.set_xticks(list(x))
    ax.set_xticklabels([NICE[s] for s in STRATA])
    ax.set_ylabel("mean candidate evaluations\ncompleted in 24 h")
    ax.set_title(
        "Search throughput at equal wall clock — the EA evaluates more\n"
        "candidates because its cache reuses unchanged prompts", fontsize=10,
    )
    ax.grid(axis="y", **GRID)
    ax.set_axisbelow(True)
    ax.legend(frameon=False)
    save(fig, "fig6_evaluations_per_arm")


# --------------------------------------------------------------------------
# Fig 7 - RQ4: do the selected candidates survive stochastic resampling?
# --------------------------------------------------------------------------
# A forest plot keeps candidate-level paired estimates visible.  The five
# candidates in a stratum share tasks, baselines, model, and selection, so they
# are deliberately not described as independent repairs.
def fig7():
    f = REP / "rq4_phase3_safe_comparison.json"
    if not f.exists():
        print("  skip fig7 (no safe-zone-aware rq4 json yet)")
        return
    data = json.load(open(f))
    runs = data["runs"]
    if not runs:
        print("  skip fig7 (no finished phase-3 runs yet)")
        return

    # One row per candidate with at least one paired seed, grouped by stratum.
    rows = []
    for stratum in STRATA:
        fam = sorted(
            (
                (key, r)
                for key, r in runs.items()
                if r["stratum"] == stratum
                and r["comparisons"]["withrules"].get("n", 0) > 0
            ),
            key=lambda item: item[1]["rank"],
        )
        if fam:
            rows.append((stratum, fam))
    if not rows:
        print("  skip fig7 (no selected chromosomes yet)")
        return

    n = sum(len(fam) for _, fam in rows)
    fig, ax = plt.subplots(figsize=(8.2, 0.52 * n + 2.4))
    y, ylabels, seps = [], [], []
    pos = 0
    for stratum, fam in rows:
        adjusted = data.get("aggregate", {}).get(stratum, {}).get("holm", {})
        for key, r in fam:
            wr = r["comparisons"]["withrules"]
            estimate = wr["median_delta"]
            ci_lo, ci_hi = wr["median_bootstrap_ci"]
            rejects = adjusted.get(key, {}).get("reject", False)
            colour = EA_C if rejects else "#9aa5ad"
            ax.errorbar(
                estimate,
                pos,
                xerr=[[estimate - ci_lo], [ci_hi - estimate]],
                fmt="o",
                color=colour,
                ecolor=colour,
                elinewidth=1.8,
                capsize=3.5,
                markersize=7,
                zorder=4,
            )
            deterministic = r.get("deterministic")
            if deterministic is not None:
                ax.scatter(
                    deterministic["gain"], pos, marker="|", s=170,
                    color="#333", zorder=5,
                )
            surviving = r.get("pct_of_deterministic_gain_surviving")
            if surviving is not None:
                ax.annotate(
                    f"{surviving:.0f}%",
                    (ci_hi, pos),
                    xytext=(7, 0),
                    textcoords="offset points",
                    va="center",
                    fontsize=8.5,
                    color="#222",
                    fontweight="bold" if rejects else "normal",
                )
            repaired = r["candidate_kind"] == "sanitized_after_structural_violation"
            lab = f"r{r['rank']} s{r['search_seed']}" + (" repaired" if repaired else " valid")
            if r["n_seeds"] < data["target_seeds"]:
                lab += f" [{r['n_seeds']}/{data['target_seeds']}]"
            ylabels.append(lab)
            y.append(pos)
            pos += 1
        seps.append(pos - 0.5)
        pos += 0.8

    ax.axvline(0, color="#555", lw=1.1, ls="--", zorder=1)
    for s in seps[:-1]:
        ax.axhline(s + 0.4, color="#ccc", lw=0.8, zorder=1)

    ax.set_yticks(y)
    ax.set_yticklabels(ylabels, fontsize=9)
    ax.invert_yaxis()
    ax.set_xlabel("Semgrep findings removed vs the ORIGINAL rules")

    # stratum names down the left, outside the tick labels
    base = 0
    for stratum, fam in rows:
        mid = base + (len(fam) - 1) / 2
        ax.annotate(NICE[stratum], xy=(0, mid), xycoords=("axes fraction", "data"),
                    xytext=(-96, 0), textcoords="offset points",
                    rotation=90, va="center", ha="center",
                    fontsize=10, fontweight="bold")
        base += len(fam) + 0.8

    n_complete = sum(
        r["n_seeds"] == data["target_seeds"]
        for _, fam in rows
        for _, r in fam
    )
    n_reject = sum(
        item.get("reject", False)
        for group in data.get("aggregate", {}).values()
        for item in group.get("holm", {}).values()
    )
    family_complete = data.get("multiplicity", {}).get("family_complete", False)
    holm_status = (
        f"{n_reject} Holm rejections"
        if family_complete
        else "Holm decisions pending all 20 candidates"
    )
    ax.set_title(
        f"RQ4 - stochastic resampling of selected candidates "
        f"({n_complete}/{len(runs)} complete; {holm_status})\n"
        "dot + bar = paired median with percentile-bootstrap interval; tick = T=0 gain;\n"
        "label = share of deterministic gain surviving against original rules",
        fontsize=10)
    ax.grid(axis="x", **GRID)
    ax.set_axisbelow(True)
    ax.legend(handles=[
        Line2D([], [], marker="o", ls="", color=EA_C,
               label="exact sign test rejects after planned 20-test Holm"),
        Line2D([], [], marker="o", ls="", color="#9aa5ad",
               label="no Holm-adjusted rejection"),
        Line2D([], [], marker="|", ls="", color="#333", markersize=10,
               label="deterministic gain at T=0"),
    ], frameon=False, fontsize=8.5, loc="upper center",
        bbox_to_anchor=(0.5, -0.10 - 0.30 / n), ncol=1)
    save(fig, "fig7_rq4_survival")


if __name__ == "__main__":
    print("writing figures to", FIG)
    fig1(); fig2(); fig2_tiers(); fig3(); fig4(); fig5(); fig6(); fig7()
    print("done")
