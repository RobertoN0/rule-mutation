#!/usr/bin/env python3
"""Recompute the thesis's exact Wilcoxon tests and A12 effect sizes.

The submitted report uses this procedure for RQ2 and RQ4. Exact two-sided
p-values enumerate the permutation null over every 2^n assignment of signs;
the normal approximation is retained only as a diagnostic. The earlier exact
sign-test p-values remain alongside the Wilcoxon results under
``sign_test_p_superseded``.

RQ2 is reconstructed from ``rq2_safe_zone_tiers.json``. RQ4 is reconstructed
from the final shared-task-set artifact,
``rq5_three_way_baseline_comparison.json``; the older pairwise-task-set RQ4
artifact is deliberately not used.

The raw experiment archive is not required:

    python3 rq_wilcoxon_effect_sizes.py <results_dir> <output_json>
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import numpy as np
from scipy import stats


def a12(x, y):
    """Vargha-Delaney A12: P(X>Y) + 0.5 P(X=Y), with averaged ties."""
    x = np.asarray(x, float)
    y = np.asarray(y, float)
    nx, ny = len(x), len(y)
    ranks = stats.rankdata(np.concatenate([x, y]))
    rank_sum_x = ranks[:nx].sum()
    return float((rank_sum_x / nx - (nx + 1) / 2) / ny)


def magnitude(value):
    """Vargha-Delaney magnitude thresholds, based on distance from 0.5."""
    distance = abs(value - 0.5)
    if distance < 0.06:
        return "negligible"
    if distance < 0.14:
        return "small"
    if distance < 0.21:
        return "medium"
    return "large"


def exact_p(differences):
    """Exact two-sided Wilcoxon signed-rank p-value under the sign-flip null."""
    differences = np.asarray([value for value in differences if value != 0], float)
    n = len(differences)
    if n == 0:
        return 1.0

    ranks = stats.rankdata(np.abs(differences))
    doubled_ranks = np.rint(ranks * 2).astype(int)
    observed = doubled_ranks[differences > 0].sum()
    total = doubled_ranks.sum()

    counts = {0: 1}
    for rank in doubled_ranks:
        next_counts = {}
        for rank_sum, count in counts.items():
            next_counts[rank_sum] = next_counts.get(rank_sum, 0) + count
            with_rank = rank_sum + rank
            next_counts[with_rank] = next_counts.get(with_rank, 0) + count
        counts = next_counts

    observed_deviation = abs(observed - total / 2)
    extreme_count = sum(
        count
        for rank_sum, count in counts.items()
        if abs(rank_sum - total / 2) >= observed_deviation - 1e-9
    )
    return extreme_count / (2**n)


def signed_rank(differences):
    """Two-sided signed-rank summary; zeros use the Wilcox discard policy."""
    differences = np.asarray(differences, float)
    nonzero = differences[differences != 0]
    n_effective = len(nonzero)
    if n_effective == 0:
        return {
            "test": "wilcoxon signed-rank",
            "p": 1.0,
            "p_normal_approx": 1.0,
            "statistic": None,
            "n_effective": 0,
            "n_zeros_dropped": int(len(differences)),
            "method": "degenerate: all differences zero",
            "rank_biserial": 0.0,
        }

    approximation = stats.wilcoxon(
        nonzero,
        alternative="two-sided",
        zero_method="wilcox",
        method="approx",
    )
    ranks = stats.rankdata(np.abs(nonzero))
    positive_ranks = ranks[nonzero > 0].sum()
    negative_ranks = ranks[nonzero < 0].sum()
    return {
        "test": "wilcoxon signed-rank",
        "p": float(exact_p(differences)),
        "p_normal_approx": float(approximation.pvalue),
        "statistic": float(approximation.statistic),
        "n_effective": n_effective,
        "n_zeros_dropped": int(len(differences) - n_effective),
        "method": "exact permutation null over 2^n sign assignments",
        "rank_biserial": float(
            (positive_ranks - negative_ranks) / (positive_ranks + negative_ranks)
        ),
    }


def sign_test(differences):
    """Superseded exact two-sided sign test, retained for Appendix F."""
    positive = sum(value > 0 for value in differences)
    negative = sum(value < 0 for value in differences)
    n = positive + negative
    if n == 0:
        return 1.0
    tail = sum(math.comb(n, k) for k in range(min(positive, negative) + 1))
    return min(1.0, 2 * tail / (2**n))


def holm(pvalues):
    """Holm-Bonferroni step-down decisions for one declared family."""
    items = sorted(pvalues.items(), key=lambda item: item[1])
    family_size = len(items)
    output = {}
    previous_rejected = True
    for index, (name, pvalue) in enumerate(items):
        threshold = 0.05 / (family_size - index)
        reject = bool(pvalue <= threshold) and previous_rejected
        previous_rejected = reject
        output[name] = {
            "p": float(pvalue),
            "threshold": float(threshold),
            "reject": reject,
        }
    return output


def build_report(results_dir: Path) -> dict:
    """Build the RQ2/RQ4 statistical artifact from published canonical JSON."""
    report = {
        "artifact_type": "wilcoxon_signed_rank_and_vargha_delaney",
        "purpose": (
            "Primary inferential procedure for RQ2 and RQ4, replacing the exact sign "
            "test. Vargha-Delaney A12 is the reported effect size."
        ),
        "alpha": 0.05,
        "multiplicity": ("Holm-Bonferroni within each declared family; families are not pooled."),
    }

    tiers = json.loads((results_dir / "rq2_safe_zone_tiers.json").read_text())
    rq2 = {}
    for tier_name, tier in tiers["tiers"].items():
        strata = {}
        for stratum, block in tier["strata"].items():
            differences = block["deltas_f1"]
            ea = [pair["ea_f1"] for pair in block["per_seed"]]
            random = [pair.get("random_f1", pair.get("rand_f1")) for pair in block["per_seed"]]
            effect = a12(ea, random)
            strata[stratum] = {
                "n_pairs": len(differences),
                "median_delta": float(np.median(differences)),
                "wilcoxon": signed_rank(differences),
                "vargha_delaney_a12": {
                    "value": effect,
                    "magnitude": magnitude(effect),
                    "reading": "P(EA run beats random run), ties at half",
                },
                "paired_superiority": block.get("paired_superiority"),
                "sign_test_p_superseded": block.get("sign_test", {}).get("p"),
            }
        family = holm({name: row["wilcoxon"]["p"] for name, row in strata.items()})
        for name, decision in family.items():
            strata[name]["holm"] = decision
        rq2[tier_name] = {
            "strata": strata,
            "n_holm_rejections": sum(row["reject"] for row in family.values()),
        }
    report["rq2_ea_vs_random"] = rq2

    three_way = json.loads((results_dir / "rq5_three_way_baseline_comparison.json").read_text())
    rq4 = {}
    for name, row in three_way["layer2_candidate_vs_authored"].items():
        differences = row["per_seed_delta"]
        authored_totals = three_way["layer1_authored_vs_norules"][row["stratum"]]["authored_totals"]
        candidate_totals = row["candidate_totals"]
        effect = a12(authored_totals, candidate_totals)
        if abs(effect - row["a12"]) > 1e-12:
            raise ValueError(f"RQ4 A12 mismatch for {name}")

        wilcoxon = signed_rank(differences)
        if abs(wilcoxon["p"] - row["wilcoxon_exact_p"]) > 1e-12:
            raise ValueError(f"RQ4 Wilcoxon mismatch for {name}")

        rq4[name] = {
            "stratum": row["stratum"],
            "rank": row["rank"],
            "candidate_kind": row["candidate_kind"],
            "n_seeds": len(differences),
            "median_delta": float(np.median(differences)),
            "wilcoxon": wilcoxon,
            "vargha_delaney_a12": {
                "value": effect,
                "magnitude": magnitude(effect),
                "reading": "P(candidate has fewer findings than authored rules), ties at half",
            },
            "paired_superiority": (
                sum(value > 0 for value in differences)
                + 0.5 * sum(value == 0 for value in differences)
            )
            / len(differences),
            "sign_test_p_superseded": sign_test(differences),
        }

    family = holm({name: row["wilcoxon"]["p"] for name, row in rq4.items()})
    for name, decision in family.items():
        rq4[name]["holm"] = decision
    report["rq4_candidates_vs_authored"] = {
        "runs": rq4,
        "n_candidates": len(rq4),
        "n_holm_rejections": sum(row["reject"] for row in family.values()),
        "family": "one Holm family across all twenty selected candidates",
        "task_set": "shared across no-rules, authored-rules, and all five candidates per stratum and seed",
    }
    return report


def main(results_dir: Path, output_path: Path) -> None:
    report = build_report(results_dir)
    output_path.write_text(json.dumps(report, indent=2) + "\n")
    print("wrote", output_path)


if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit("usage: rq_wilcoxon_effect_sizes.py <results_dir> <output_json>")
    main(Path(sys.argv[1]), Path(sys.argv[2]))
