#!/usr/bin/env python
"""RQ2 - does the archive EA beat i.i.d. random search at equal wall-clock budget?

The comparison uses the best structurally compliant candidate *observed* in
each original run.  It is a post-hoc sensitivity analysis, not a reconstruction
of a search that enforced the contract while adapting its archive.

WHY THE CHANGE
--------------
The four model/language strata were pre-specified but not pre-registered.  Raw
p-values and Holm-adjusted family decisions are both reported.  The exact sign
test is primary because it needs neither a symmetric distribution of paired
differences nor a random-treatment interpretation.  An exact paired sign-flip
test on the mean is retained as a sensitivity analysis; its inferential reading
requires within-pair exchangeability under the null.

Effect size is paired: median within-seed difference and the paired
common-language probability P(EA>random)+0.5P(tie).  The former unpaired A12
calculation was inappropriate because it discarded the seed matching.
"""
from __future__ import annotations

import json
import statistics

from common import (
    bootstrap_median_ci,
    holm,
    load_runs,
    paired_superiority,
    perm_test_paired,
    safe_zone_gated_pairs,
    sign_test,
    write,
)

ALPHA = 0.05


def main():
    strata = load_runs()
    kept, excluded = safe_zone_gated_pairs(strata)

    rep = {
        "artifact_type": "rq2_posthoc_safe_zone_sensitivity",
        "interpretation": (
            "best structurally compliant candidates observed within raw searches; "
            "not equivalent to constrained-search reruns"
        ),
        "excluded": excluded,
        "strata": {},
        "family": {},
    }
    p_primary, p_sensitivity = {}, {}

    for key, pairs in kept.items():
        d_f1 = [e["f1"] - r["f1"] for _, e, r in pairs]
        d_w = [e["wred"] - r["wred"] for _, e, r in pairs]
        if len(d_f1) < 2:
            continue

        p_sg, pos, neg = sign_test(d_f1)
        p_perm, note = perm_test_paired(d_f1)
        med_lo, med_hi = bootstrap_median_ci(d_f1)
        w_lo, w_hi = bootstrap_median_ci(d_w)
        eff = paired_superiority(d_f1)

        p_primary[key] = p_sg
        p_sensitivity[key] = p_perm

        rep["strata"][key] = dict(
            n=len(d_f1),
            deltas_f1=d_f1,
            deltas_weighted=d_w,
            primary=dict(
                test="exact two-sided sign test",
                p=p_sg,
                positive_pairs=pos,
                negative_pairs=neg,
                ties=len(d_f1) - pos - neg,
                note="ties excluded from the binomial test",
            ),
            sign_flip_sensitivity=dict(
                test="exact paired sign-flip test on mean delta",
                p=p_perm,
                note=(
                    note + "; inferential interpretation assumes within-pair "
                    "exchangeability under the null"
                ),
            ),
            median_delta=dict(
                value=statistics.median(d_f1),
                bootstrap_ci=[med_lo, med_hi],
            ),
            paired_superiority=eff,
            mean_delta=sum(d_f1) / len(d_f1),
            secondary_weighted_descriptive=dict(
                mean_delta=sum(d_w) / len(d_w),
                median_delta=statistics.median(d_w),
                median_bootstrap_ci=[w_lo, w_hi],
                note="weighted score attached to the raw-f1-selected compliant candidate",
            ),
            mean_E_ea=sum(e["E"] for _, e, _ in pairs) / len(pairs),
            mean_E_rand=sum(r["E"] for _, _, r in pairs) / len(pairs),
            per_seed=[
                dict(seed=s, ea_f1=e["f1"], rand_f1=r["f1"], delta=e["f1"] - r["f1"],
                     ea_E=e["E"], rand_E=r["E"], origin=e["orig"])
                for s, e, r in pairs
            ],
        )

    rep["family"] = dict(
        declared="4 strata x 1 primary outcome (best raw finding reduction)",
        rationale=(
            "Four pre-specified (not pre-registered) model/language strata. Raw "
            "p-values are shown, while Holm controls the four-test family."
        ),
        holm_primary={
            k: dict(p=v[0], threshold=v[1], reject=v[2])
            for k, v in holm(p_primary, ALPHA).items()
        },
        holm_sign_flip_sensitivity={
            k: dict(p=v[0], threshold=v[1], reject=v[2])
            for k, v in holm(p_sensitivity, ALPHA).items()
        },
    )
    write("rq2_ea_vs_random.json", json.dumps(rep, indent=2))

    hp = rep["family"]["holm_primary"]
    hsf = rep["family"]["holm_sign_flip_sensitivity"]

    L = [
        "# RQ2 - archive EA vs i.i.d. random search (equal 24 h wall clock)",
        "",
        "Unit of analysis: the paired run seed. Strata are never pooled.",
        "Primary outcome: best raw Semgrep-finding reduction (`f1`).",
        "The score is the best structurally compliant candidate observed within each",
        "raw search. This post-hoc filter does not reconstruct constrained trajectories.",
        "",
        "## Declared family",
        "",
        f"- **Family**: {rep['family']['declared']}",
        f"- **Rationale**: {rep['family']['rationale']}",
        "- Holm thresholds attach to p-value rank, not to a fixed stratum.",
        "",
        "## Primary result - paired effect size and exact sign test",
        "",
        "| stratum | n | median Δ [95% boot CI] | paired superiority | + / - / tie | sign p | Holm p-thr | Holm rejects |",
        "|---|---:|---|---:|---:|---:|---:|:--:|",
    ]
    for key in sorted(rep["strata"]):
        s = rep["strata"][key]
        h = hp[key]
        L.append(
            f"| {key} | {s['n']} | {s['median_delta']['value']:.1f} "
            f"[{s['median_delta']['bootstrap_ci'][0]:.1f}, {s['median_delta']['bootstrap_ci'][1]:.1f}] | "
            f"{s['paired_superiority']:.3f} | "
            f"{s['primary']['positive_pairs']} / {s['primary']['negative_pairs']} / {s['primary']['ties']} | "
            f"{s['primary']['p']:.5f} | "
            f"{h['threshold']:.4f} | {'YES' if h['reject'] else 'no'} |"
        )

    L += [
        "",
        "### Sign-flip sensitivity analysis",
        "",
        "The sign-flip test uses magnitudes but its inferential reading assumes that",
        "algorithm labels are exchangeable within a seed pair under the null.",
        "",
        "| stratum | mean Δ | sign-flip p | Holm p-thr | Holm rejects |",
        "|---|---:|---:|---:|:--:|",
    ]
    for key in sorted(rep["strata"]):
        s = rep["strata"][key]
        h = hsf[key]
        L.append(
            f"| {key} | {s['mean_delta']:.2f} | {s['sign_flip_sensitivity']['p']:.5f} | "
            f"{h['threshold']:.4f} | {'YES' if h['reject'] else 'no'} |"
        )

    L += [
        "",
        "## Secondary descriptive check - severity-weighted reduction",
        "",
        "This is the weighted score attached to each raw-f1-selected compliant",
        "candidate; it was not separately selected as a weighted optimum.",
        "",
        "| stratum | median Δ weighted [95% boot CI] | mean Δ weighted |",
        "|---|---:|---:|",
    ]
    for key in sorted(rep["strata"]):
        s = rep["strata"][key]
        w = s["secondary_weighted_descriptive"]
        L.append(
            f"| {key} | {w['median_delta']:.1f} "
            f"[{w['median_bootstrap_ci'][0]:.1f}, {w['median_bootstrap_ci'][1]:.1f}] | "
            f"{w['mean_delta']:.2f} |"
        )

    L += [
        "",
        "## Diagnostic - evaluations completed (mediator, not an outcome)",
        "",
        "| stratum | mean E (EA) | mean E (random) | ratio |",
        "|---|---:|---:|---:|",
    ]
    for key in sorted(rep["strata"]):
        s = rep["strata"][key]
        L.append(
            f"| {key} | {s['mean_E_ea']:.0f} | {s['mean_E_rand']:.0f} | "
            f"{s['mean_E_ea'] / s['mean_E_rand']:.2f}× |"
        )

    L += ["", "## Per-seed detail", ""]
    for key in sorted(rep["strata"]):
        s = rep["strata"][key]
        L += [
            f"### {key} (n={s['n']})",
            "",
            "| seed | origin | EA f1 | random f1 | Δ | EA E | random E |",
            "|---:|---:|---:|---:|---:|---:|---:|",
        ]
        for r in s["per_seed"]:
            L.append(
                f"| {r['seed']} | {r['origin']} | {r['ea_f1']:.0f} | {r['rand_f1']:.0f} "
                f"| {r['delta']:+.0f} | {r['ea_E']} | {r['rand_E']} |"
            )
        L.append("")

    if excluded:
        L += ["## Excluded", ""] + [f"- {e}" for e in excluded]

    write("rq2_ea_vs_random.md", "\n".join(L) + "\n")
    print("\n".join(L[:24]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
