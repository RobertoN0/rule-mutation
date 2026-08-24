#!/usr/bin/env python3
"""Three-way Phase-3 comparison: no-rules, authored rules, and selected candidates.

The published RQ4 artifact records only the totals of each pairwise comparison,
each on its own task set, so the effect of the authored rules themselves is not
recoverable from it and the layers do not decompose. This script rebuilds the
comparison from the stored per-task counts on a task set shared by every
condition, which makes three questions separable:

  layer 1  authored vs no-rules   -- do the manually authored rules help at all?
  layer 2  candidate vs authored  -- do our mutations improve on them?
  layer 3  candidate vs no-rules  -- the total effect.

Task-set policy. For each (stratum, seed) the analysis uses the intersection of
the qualified task ids with the per-task maps of the no-rules baseline, the
authored baseline, and *all five* candidates of that stratum. The set therefore
does not depend on which candidate is being tested, which is what makes layer 1
a single comparison per stratum rather than five copies of one, and what makes
the decomposition exact for every candidate.

Inference is the Wilcoxon signed-rank test with exact permutation p-values and
Vargha-Delaney A12, matching the local analysis. Three families are declared and
Holm-corrected separately; they are never pooled.

Read-only with respect to every run artifact. Writes one new JSON/MD pair and
does not touch rq4_phase3_safe_comparison.json.
"""

from __future__ import annotations

import json
import statistics
from collections import defaultdict

import numpy as np
from scipy import stats

import rq4_phase3_safe_compare as rq4
from common import OUT, holm, write

TARGET_SEEDS = rq4.TARGET_SEEDS
TARGET_K = rq4.TARGET_K
STRATA = ["llama_java", "llama_python", "qwen_java", "qwen_python"]


# --------------------------------------------------------------------------
# statistics -- identical to the local session's implementation
# --------------------------------------------------------------------------
def exact_p(d):
    """Exact two-sided p for the Wilcoxon signed-rank statistic."""
    d = np.asarray([x for x in d if x != 0], float)
    n = len(d)
    if n == 0:
        return 1.0
    ranks = stats.rankdata(np.abs(d))
    r2 = np.rint(ranks * 2).astype(int)  # average ranks are multiples of 0.5
    obs2 = r2[d > 0].sum()
    tot2 = r2.sum()
    counts = {0: 1}
    for r in r2:
        nxt = {}
        for s, c in counts.items():
            nxt[s] = nxt.get(s, 0) + c
            nxt[s + r] = nxt.get(s + r, 0) + c
        counts = nxt
    dev = abs(obs2 - tot2 / 2)
    return sum(c for s, c in counts.items() if abs(s - tot2 / 2) >= dev - 1e-9) / 2**n


def a12(x, y):
    """Vargha-Delaney A12 = P(X>Y) + 0.5 P(X=Y)."""
    x = np.asarray(x, float)
    y = np.asarray(y, float)
    nx, ny = len(x), len(y)
    r = stats.rankdata(np.concatenate([x, y]))
    return float((r[:nx].sum() / nx - (nx + 1) / 2) / ny)


def a12_label(v):
    d = abs(v - 0.5)
    return "negligible" if d < 0.06 else "small" if d < 0.14 else "medium" if d < 0.21 else "large"


def rank_biserial(d):
    """Matched-pairs rank-biserial correlation (W+ - W-) / (W+ + W-)."""
    d = np.asarray([x for x in d if x != 0], float)
    if len(d) == 0:
        return 0.0
    ranks = stats.rankdata(np.abs(d))
    wp = ranks[d > 0].sum()
    wn = ranks[d < 0].sum()
    return float((wp - wn) / (wp + wn)) if (wp + wn) else 0.0


def describe(deltas, worse_totals, better_totals, label):
    """One test. `deltas` are oriented so positive means fewer findings."""
    nz = [x for x in deltas if x != 0]
    p = exact_p(deltas)
    effect = a12(worse_totals, better_totals)
    return {
        "comparison": label,
        "n_seeds": len(deltas),
        "n_nonzero": len(nz),
        "median_delta": statistics.median(deltas) if deltas else 0.0,
        "mean_delta": statistics.fmean(deltas) if deltas else 0.0,
        "median_pct_of_reference": (
            100.0 * statistics.median(deltas) / statistics.median(worse_totals)
            if deltas and statistics.median(worse_totals)
            else None
        ),
        "paired_win_rate": (sum(1 for x in deltas if x > 0) / len(deltas) if deltas else None),
        "n_positive": sum(1 for x in deltas if x > 0),
        "n_negative": sum(1 for x in deltas if x < 0),
        "n_ties": len(deltas) - len(nz),
        "wilcoxon_exact_p": p,
        "a12": effect,
        "a12_label": a12_label(effect),
        "rank_biserial": rank_biserial(deltas),
        "per_seed_delta": deltas,
    }


# --------------------------------------------------------------------------
# data assembly
# --------------------------------------------------------------------------
def per_case(row):
    return {str(k): int(v) for k, v in (row.get("per_case_raw") or {}).items()}


def main() -> int:
    by_cid, by_override = rq4.selected_candidates()
    discovered = rq4.discover_replays(by_override)

    candidates_by_stratum = defaultdict(list)
    for cand in sorted(by_cid.values(), key=lambda r: (r["stratum"], r["rank"])):
        candidates_by_stratum[cand["stratum"]].append(cand)

    output = {
        "artifact_type": "rq4_three_way_phase3_baseline_comparison",
        "generated_from": "experiments/{01_population_and_maps/phase3_screening/block1,"
        "05_phase3_resampling,06_safe_zone_validation}/**/replicates.jsonl",
        "unit_of_analysis": "one generation seed; 20 seeds per comparison at temperature 0.6",
        "task_set_policy": (
            "per (stratum, seed): qualified task ids intersected with the per-task maps of "
            "the no-rules baseline, the authored baseline, and all five candidates of the "
            "stratum. Independent of which candidate is tested, so layer 1 is one comparison "
            "per stratum and the layers decompose exactly."
        ),
        "multiplicity": {
            "policy": "three declared families, Holm within each, never pooled",
            "families": {
                "layer1_authored_vs_norules": 4,
                "layer2_candidate_vs_authored": 4 * TARGET_K,
                "layer3_candidate_vs_norules": 4 * TARGET_K,
            },
        },
        "statistics": (
            "Wilcoxon signed-rank with exact permutation p-values over all 2^n sign "
            "assignments; Vargha-Delaney A12 oriented so >0.5 favours the condition with "
            "fewer findings; matched-pairs rank-biserial correlation"
        ),
        "common_task_counts": {},
        "layer1_authored_vs_norules": {},
        "layer2_candidate_vs_authored": {},
        "layer3_candidate_vs_norules": {},
        "decomposition_check": {},
        "problems": [],
    }

    max_residual = 0.0
    residual_failures = []
    l1_p, l2_p, l3_p = {}, {}, {}

    for stratum in STRATA:
        model, language = stratum.split("_")
        ids = rq4.final_task_ids(model, language)
        authored = rq4.baseline_replicates(model, language, "withrules")
        norules = rq4.baseline_replicates(model, language, "norules")
        cands = candidates_by_stratum[stratum]
        if len(cands) != TARGET_K:
            output["problems"].append(f"{stratum}: {len(cands)} candidates, expected {TARGET_K}")

        cand_reps = {}
        for cand in cands:
            dirs = discovered.get(cand["cid"], [])
            if not dirs:
                output["problems"].append(
                    f"{stratum} r{cand['rank']} {cand['cid'][:8]}: no replay directory"
                )
                continue
            cand_reps[cand["cid"]] = rq4.pool_replicates(dirs)

        seeds = set(authored) & set(norules)
        for reps in cand_reps.values():
            seeds &= set(reps)
        seeds = sorted(seeds)
        if len(seeds) != TARGET_SEEDS:
            output["problems"].append(
                f"{stratum}: {len(seeds)} seeds common to all conditions, expected {TARGET_SEEDS}"
            )

        # --- shared task set per seed, plus the cost against pairwise sets ---
        common_by_seed, cost_rows = {}, []
        for seed in seeds:
            a_case, n_case = per_case(authored[seed]), per_case(norules[seed])
            common = ids & set(a_case) & set(n_case)
            pairwise_sizes = []
            for cid, reps in cand_reps.items():
                c_case = per_case(reps[seed])
                common &= set(c_case)
                pairwise_sizes.append(len(ids & set(c_case) & set(a_case)))
            common_by_seed[seed] = sorted(common)
            cost_rows.append(
                {
                    "seed": seed,
                    "n_qualified": len(ids),
                    "n_common_three_way": len(common),
                    "n_dropped_vs_qualified": len(ids) - len(common),
                    "median_pairwise_candidate_vs_authored": statistics.median(pairwise_sizes),
                    "extra_tasks_dropped_vs_pairwise": statistics.median(pairwise_sizes)
                    - len(common),
                }
            )
        sizes = [r["n_common_three_way"] for r in cost_rows]
        output["common_task_counts"][stratum] = {
            "n_qualified_tasks": len(ids),
            "n_common_min": min(sizes) if sizes else 0,
            "n_common_max": max(sizes) if sizes else 0,
            "n_common_median": statistics.median(sizes) if sizes else 0,
            "median_extra_dropped_vs_pairwise": statistics.median(
                [r["extra_tasks_dropped_vs_pairwise"] for r in cost_rows]
            )
            if cost_rows
            else 0,
            "per_seed": cost_rows,
        }

        # --- layer 1: authored vs no-rules, one test per stratum ---
        n_tot, a_tot, d1 = [], [], []
        for seed in seeds:
            keys = common_by_seed[seed]
            a_case, n_case = per_case(authored[seed]), per_case(norules[seed])
            nt = sum(n_case[k] for k in keys)
            at = sum(a_case[k] for k in keys)
            n_tot.append(nt)
            a_tot.append(at)
            d1.append(float(nt - at))
        row = describe(d1, n_tot, a_tot, "authored rules vs no rules")
        row["norules_totals"] = n_tot
        row["authored_totals"] = a_tot
        output["layer1_authored_vs_norules"][stratum] = row
        l1_p[stratum] = row["wilcoxon_exact_p"]

        # --- layers 2 and 3, per candidate ---
        for cand in cands:
            cid = cand["cid"]
            if cid not in cand_reps:
                continue
            key = f"{stratum}_r{cand['rank']}_{cid[:8]}"
            c_tot, d2, d3 = [], [], []
            for i, seed in enumerate(seeds):
                keys = common_by_seed[seed]
                c_case = per_case(cand_reps[cid][seed])
                ct = sum(c_case[k] for k in keys)
                c_tot.append(ct)
                d2.append(float(a_tot[i] - ct))
                d3.append(float(n_tot[i] - ct))
                resid = abs(d3[-1] - (d1[i] + d2[-1]))
                max_residual = max(max_residual, resid)
                if resid > 0:
                    residual_failures.append(
                        {"stratum": stratum, "seed": seed, "cid": cid, "residual": resid}
                    )

            meta = {
                "stratum": stratum,
                "rank": cand["rank"],
                "cid": cid,
                "search_seed": cand["seed"],
                "candidate_kind": (
                    "raw_structurally_valid"
                    if cand["strict_safe_zone_valid"]
                    else "sanitized_after_structural_violation"
                ),
                "candidate_totals": c_tot,
            }
            r2 = describe(d2, a_tot, c_tot, "candidate vs authored rules")
            r2.update(meta)
            r3 = describe(d3, n_tot, c_tot, "candidate vs no rules")
            r3.update(meta)
            output["layer2_candidate_vs_authored"][key] = r2
            output["layer3_candidate_vs_norules"][key] = r3
            l2_p[key] = r2["wilcoxon_exact_p"]
            l3_p[key] = r3["wilcoxon_exact_p"]

    # --- Holm within each family ---
    for name, pv, target in (
        ("layer1_authored_vs_norules", l1_p, 4),
        ("layer2_candidate_vs_authored", l2_p, 4 * TARGET_K),
        ("layer3_candidate_vs_norules", l3_p, 4 * TARGET_K),
    ):
        complete = len(pv) == target
        adjusted = holm(pv) if complete else {}
        output["multiplicity"].setdefault("results", {})[name] = {
            "n_tests": len(pv),
            "n_planned": target,
            "family_complete": complete,
            "decision_status": "final" if complete else "incomplete; no decisions issued",
            "holm": {
                k: {"p": v[0], "threshold": v[1], "reject": v[2]} for k, v in adjusted.items()
            },
            "n_reject": sum(1 for v in adjusted.values() if v[2]),
            "n_raw_p_below_05": sum(1 for p in pv.values() if p < 0.05),
        }
        for k, v in adjusted.items():
            output[name][k]["holm"] = {"p": v[0], "threshold": v[1], "reject": v[2]}

    output["decomposition_check"] = {
        "identity": "delta(norules->candidate) == delta(norules->authored) + delta(authored->candidate)",
        "pass": not residual_failures,
        "max_residual": max_residual,
        "n_checked": 4 * TARGET_K * TARGET_SEEDS,
        "failures": residual_failures[:20],
    }

    (OUT).mkdir(parents=True, exist_ok=True)
    (OUT / "rq4_three_way_baseline_comparison.json").write_text(json.dumps(output, indent=2))
    print(f"wrote {OUT / 'rq4_three_way_baseline_comparison.json'}")
    write("rq4_three_way_baseline_comparison.md", render_md(output))
    return 0


def render_md(o) -> str:
    L = [
        "# RQ4: final three-way Phase-3 baseline comparison",
        "",
        o["task_set_policy"],
        "",
        f"Statistics: {o['statistics']}.",
        "",
        "## Common task set",
        "",
        "| Stratum | qualified | three-way common (median) | extra dropped vs pairwise |",
        "|---|---|---|---|",
    ]
    for s, c in o["common_task_counts"].items():
        L.append(
            f"| {s} | {c['n_qualified_tasks']} | {c['n_common_median']:.0f} "
            f"({c['n_common_min']}-{c['n_common_max']}) | {c['median_extra_dropped_vs_pairwise']:.0f} |"
        )
    L += [
        "",
        "## Layer 1: authored rules vs no rules",
        "",
        "| Stratum | median delta | % of no-rules | win rate | exact p | Holm | A12 | rank-biserial |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for s, r in o["layer1_authored_vs_norules"].items():
        h = r.get("holm", {})
        L.append(
            f"| {s} | {r['median_delta']:+.1f} | {r['median_pct_of_reference']:+.1f}% | "
            f"{r['paired_win_rate']:.2f} | {r['wilcoxon_exact_p']:.4g} | "
            f"{'reject' if h.get('reject') else 'no'} | {r['a12']:.3f} ({r['a12_label']}) | "
            f"{r['rank_biserial']:+.3f} |"
        )
    for layer, title, ref in (
        ("layer2_candidate_vs_authored", "Layer 2: candidate vs authored rules", "authored"),
        ("layer3_candidate_vs_norules", "Layer 3: candidate vs no rules", "no-rules"),
    ):
        L += [
            "",
            f"## {title}",
            "",
            f"| Candidate | kind | median delta | % of {ref} | win rate | exact p | Holm | A12 |",
            "|---|---|---|---|---|---|---|---|",
        ]
        for k, r in o[layer].items():
            h = r.get("holm", {})
            L.append(
                f"| {k} | {'raw' if r['candidate_kind'].startswith('raw') else 'sanitised'} | "
                f"{r['median_delta']:+.1f} | {r['median_pct_of_reference']:+.1f}% | "
                f"{r['paired_win_rate']:.2f} | {r['wilcoxon_exact_p']:.4g} | "
                f"{'reject' if h.get('reject') else 'no'} | {r['a12']:.3f} |"
            )
    d = o["decomposition_check"]
    L += [
        "",
        "## Decomposition check",
        "",
        f"`{d['identity']}`",
        "",
        f"{'PASS' if d['pass'] else 'FAIL'} over {d['n_checked']} (stratum, seed, candidate) "
        f"triples; largest residual {d['max_residual']}.",
    ]
    if o["problems"]:
        L += ["", "## Problems", ""] + [f"- {p}" for p in o["problems"]]
    return "\n".join(L) + "\n"


if __name__ == "__main__":
    raise SystemExit(main())
