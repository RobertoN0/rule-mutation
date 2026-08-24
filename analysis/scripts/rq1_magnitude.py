#!/usr/bin/env python
"""RQ1 - to what extent can controlled rule mutations improve effectiveness?

This is an ESTIMATION question, not a testing question. The archive only ever
keeps a chromosome that is at least as good as the origin, so best-f1 >= 0 by
construction and a null test against zero is degenerate: it cannot fail. We
report it once, flagged, and then spend the section on magnitude:

The primary sensitivity analysis uses the best structurally compliant candidate
observed in each original search run.  This post-hoc filter is not equivalent
to rerunning the adaptive search with safe-zone enforcement; the raw reported
optima are retained alongside it so the impact is visible.

We report:

  * absolute reduction in raw Semgrep findings (f1) achieved by the EA
  * that reduction as a PERCENTAGE of the origin's findings  <- the headline
  * the severity-weighted equivalent, since f1 is severity-blind
  * the same quantities for random search, so the reader can see how much of the
    magnitude is attributable to search rather than to sampling at all

Unit of analysis is the run (seed). Strata are never pooled.
"""
from __future__ import annotations

import json

from common import (
    bootstrap_ci,
    bootstrap_median_ci,
    load_runs,
    safe_zone_gated_pairs,
    write,
)


def describe(vals):
    s = sorted(vals)
    n = len(s)
    med = s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2
    med_lo, med_hi = bootstrap_median_ci(vals)
    mean_lo, mean_hi = bootstrap_ci(vals)
    return dict(
        n=n,
        min=s[0],
        max=s[-1],
        median=med,
        mean=sum(vals) / n,
        median_boot_ci=[med_lo, med_hi],
        mean_boot_ci=[mean_lo, mean_hi],
    )


def main():
    strata = load_runs()
    kept, excluded = safe_zone_gated_pairs(strata)

    rep = {
        "artifact_type": "rq1_posthoc_safe_zone_sensitivity",
        "interpretation": (
            "best structurally compliant candidate observed within each raw search; "
            "not equivalent to a constrained-search rerun"
        ),
        "excluded": excluded,
        "strata": {},
    }
    for key, pairs in kept.items():
        ea_f1 = [e["f1"] for _, e, _ in pairs]
        rd_f1 = [r["f1"] for _, _, r in pairs]
        ea_w = [e["wred"] for _, e, _ in pairs]
        orig = [e["orig"] for _, e, _ in pairs]
        orig_w = [e["orig_w"] for _, e, _ in pairs if e["orig_w"] is not None]
        ea_reported = [e["reported_f1"] for _, e, _ in pairs]
        rd_reported = [r["reported_f1"] for _, _, r in pairs]

        # percentage of the origin's findings removed, computed per seed then
        # summarised -- never as a ratio of the two aggregates
        ea_pct = [100.0 * f / o for f, o in zip(ea_f1, orig) if o]
        rd_pct = [100.0 * f / o for f, o in zip(rd_f1, orig) if o]
        ea_wpct = [
            100.0 * e["wred"] / e["orig_w"]
            for _, e, _ in pairs
            if e["orig_w"]
        ]
        ea_reported_pct = [100.0 * f / o for f, o in zip(ea_reported, orig) if o]
        rd_reported_pct = [100.0 * f / o for f, o in zip(rd_reported, orig) if o]

        rep["strata"][key] = dict(
            origin_raw=orig[0] if len(set(orig)) == 1 else orig,
            origin_weighted=orig_w[0] if orig_w and len(set(orig_w)) == 1 else orig_w,
            ea_f1=describe(ea_f1),
            rand_f1=describe(rd_f1),
            ea_pct_of_origin=describe(ea_pct) if ea_pct else None,
            rand_pct_of_origin=describe(rd_pct) if rd_pct else None,
            reported_ea_f1=describe(ea_reported),
            reported_rand_f1=describe(rd_reported),
            reported_ea_pct_of_origin=describe(ea_reported_pct),
            reported_rand_pct_of_origin=describe(rd_reported_pct),
            ea_weighted=describe(ea_w),
            ea_weighted_pct=describe(ea_wpct) if ea_wpct else None,
            safe_zone_audit=dict(
                ea_best_changed=sum(e["reported_minus_strict"] > 0 for _, e, _ in pairs),
                rand_best_changed=sum(r["reported_minus_strict"] > 0 for _, _, r in pairs),
                ea_invalid_fraction=describe(
                    [e["safe_zone_invalid_fraction"] for _, e, _ in pairs]
                ),
                rand_invalid_fraction=describe(
                    [r["safe_zone_invalid_fraction"] for _, _, r in pairs]
                ),
            ),
            per_seed=[
                dict(
                    seed=s,
                    origin=e["orig"],
                    ea_f1=e["f1"],
                    rand_f1=r["f1"],
                    ea_reported_f1=e["reported_f1"],
                    rand_reported_f1=r["reported_f1"],
                    ea_pct=100.0 * e["f1"] / e["orig"] if e["orig"] else None,
                    ea_strict_evaluation=e["strict_best_evaluation_index"],
                    rand_strict_evaluation=r["strict_best_evaluation_index"],
                )
                for s, e, r in pairs
            ],
        )

    write("rq1_magnitude.json", json.dumps(rep, indent=2))

    L = [
        "# RQ1 - to what extent can controlled rule mutations improve effectiveness?",
        "",
        "Estimation, not null-hypothesis testing: the elitist archive makes a test",
        "against zero degenerate. Primary values below are the best structurally",
        "compliant candidates observed in each original run. This is a **post-hoc",
        "sensitivity filter**, not a reconstruction of a constrained adaptive search.",
        "",
        "## Headline - findings removed by the best compliant candidate observed",
        "",
        "| stratum | origin findings | EA f1 median [min-max] | **EA % of origin** | random f1 median | random % of origin |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for key in sorted(rep["strata"]):
        s = rep["strata"][key]
        e, r = s["ea_f1"], s["rand_f1"]
        ep, rp = s["ea_pct_of_origin"], s["rand_pct_of_origin"]
        L.append(
            f"| {key} | {s['origin_raw']} | {e['median']:.0f} "
            f"[{e['min']:.0f}-{e['max']:.0f}] | **{ep['median']:.1f}%** | "
            f"{r['median']:.0f} | {rp['median']:.1f}% |"
        )

    L += [
        "",
        "## Estimates with percentile-bootstrap intervals",
        "",
        "Intervals are 95% percentile-bootstrap intervals for the run-level median",
        "(20,000 resamples). With only ten runs per stratum they are approximate.",
        "",
        "| stratum | n | EA f1 median [95% boot CI] | EA % of origin median [95% boot CI] | EA weighted median [95% boot CI] |",
        "|---|---:|---|---|---|",
    ]
    for key in sorted(rep["strata"]):
        s = rep["strata"][key]
        e, ep, ew = s["ea_f1"], s["ea_pct_of_origin"], s["ea_weighted"]
        L.append(
            f"| {key} | {e['n']} | {e['median']:.1f} "
            f"[{e['median_boot_ci'][0]:.1f}, {e['median_boot_ci'][1]:.1f}] "
            f"| {ep['median']:.2f}% [{ep['median_boot_ci'][0]:.2f}, {ep['median_boot_ci'][1]:.2f}] "
            f"| {ew['median']:.1f} [{ew['median_boot_ci'][0]:.1f}, {ew['median_boot_ci'][1]:.1f}] |"
        )

    L += [
        "",
        "## Safe-zone sensitivity - reported optimum versus compliant optimum",
        "",
        "`best changed` counts runs whose raw reported optimum was structurally invalid.",
        "The invalid share is the fraction of completed evaluations failing the exact",
        "frontmatter/fenced-block/inline-code preservation contract.",
        "",
        "| stratum | EA reported % | EA compliant % | EA best changed | EA invalid share median | random best changed |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for key in sorted(rep["strata"]):
        s = rep["strata"][key]
        a = s["safe_zone_audit"]
        L.append(
            f"| {key} | {s['reported_ea_pct_of_origin']['median']:.1f}% | "
            f"{s['ea_pct_of_origin']['median']:.1f}% | {a['ea_best_changed']}/10 | "
            f"{100*a['ea_invalid_fraction']['median']:.1f}% | {a['rand_best_changed']}/10 |"
        )

    L += [
        "",
        "## Severity check",
        "",
        "`f1` counts Semgrep findings without regard to severity (ERROR=3, WARNING=1, INFO=0).",
        "The weighted value is the score attached to the candidate selected by raw f1;",
        "it is not a separately optimised best-weighted candidate.",
        "If the weighted reduction is proportionally smaller than the raw reduction,",
        "the search is preferentially removing low-severity findings.",
        "",
        "| stratum | EA raw % of origin | EA weighted % of origin | ratio |",
        "|---|---:|---:|---:|",
    ]
    for key in sorted(rep["strata"]):
        s = rep["strata"][key]
        ep, wp = s["ea_pct_of_origin"], s["ea_weighted_pct"]
        if not wp:
            L.append(f"| {key} | {ep['median']:.1f}% | n/a | n/a |")
            continue
        ratio = wp["median"] / ep["median"] if ep["median"] else float("nan")
        L.append(
            f"| {key} | {ep['median']:.1f}% | {wp['median']:.1f}% | {ratio:.2f} |"
        )

    L += ["", "## Per-seed detail", ""]
    for key in sorted(rep["strata"]):
        s = rep["strata"][key]
        L += [
            f"### {key}",
            "",
            "| seed | origin | EA compliant f1 | EA reported f1 | EA % | random compliant f1 | random reported f1 |",
            "|---:|---:|---:|---:|---:|---:|---:|",
        ]
        for row in s["per_seed"]:
            L.append(
                f"| {row['seed']} | {row['origin']} | {row['ea_f1']:.0f} | "
                f"{row['ea_reported_f1']:.0f} | {row['ea_pct']:.1f}% | "
                f"{row['rand_f1']:.0f} | {row['rand_reported_f1']:.0f} |"
            )
        L.append("")

    if excluded:
        L += ["## Excluded", ""] + [f"- {e}" for e in excluded]

    write("rq1_magnitude.md", "\n".join(L) + "\n")
    print("\n".join(L[:16]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
