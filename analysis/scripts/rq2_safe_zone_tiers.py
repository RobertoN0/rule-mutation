#!/usr/bin/env python3
"""RQ2 specification-curve-style safe-zone sensitivity analysis.

This report keeps three estimands visibly separate:

``raw_executed``
    The best score reported by the mutation/search implementation that was
    actually executed. This answers the system-level algorithm comparison.

``core_structural``
    A post-hoc diagnostic that requires frontmatter and fenced-code structure
    to be preserved, while allowing inline-code changes. This tier was created
    after the safe-zone problem was discovered and is exploratory.

``full_contract``
    The post-hoc exact contract used elsewhere in the corrected analysis:
    preserve frontmatter, fenced-code blocks, and inline-code spans.

The latter two tiers select the best admissible candidate *observed along the
historical raw trajectory*. Neither reconstructs the trajectory that a search
with fail-closed enforcement would have followed.
"""
from __future__ import annotations

import json
import statistics
from pathlib import Path

from common import (
    OUT,
    SAFE_ZONE_AUDIT,
    bootstrap_median_ci,
    gated_pairs,
    holm,
    load_runs,
    paired_superiority,
    perm_test_paired,
    sign_test,
    write,
)


ALPHA = 0.05
EXPECTED_STRATA = {
    "llama_java",
    "llama_python",
    "qwen_java",
    "qwen_python",
}
TIERS = {
    "raw_executed": {
        "label": "Raw executed system",
        "audit_field": "reported_best_f1",
        "status": "system-level result",
        "description": (
            "Best result reported by the mutation/search implementation that "
            "was actually executed."
        ),
    },
    "core_structural": {
        "label": "Core structural sensitivity",
        "audit_field": "core_structural_best_f1",
        "status": "post-hoc exploratory sensitivity",
        "description": (
            "Best observed candidate preserving frontmatter and fenced-code "
            "structure; inline-code changes are allowed."
        ),
    },
    "full_contract": {
        "label": "Full safe-zone sensitivity",
        "audit_field": "strict_best_f1",
        "status": "post-hoc conservative sensitivity",
        "description": (
            "Best observed candidate preserving frontmatter, fenced-code "
            "blocks, and inline-code spans exactly."
        ),
    },
}


def _holm_rows(pvalues: dict[str, float]) -> dict[str, dict]:
    return {
        key: {"p": values[0], "threshold": values[1], "reject": values[2]}
        for key, values in holm(pvalues, ALPHA).items()
    }


def _load_and_validate_pairs() -> tuple[dict, list[str], dict]:
    strata = load_runs()
    raw_pairs, excluded = gated_pairs(strata)
    if set(raw_pairs) != EXPECTED_STRATA:
        raise ValueError(
            f"expected strata {sorted(EXPECTED_STRATA)}, got {sorted(raw_pairs)}"
        )
    if excluded:
        raise ValueError(f"unexpected excluded run pairs: {excluded}")
    if any(len(pairs) != 10 for pairs in raw_pairs.values()):
        raise ValueError("expected exactly ten matched seeds per stratum")

    audit = json.loads(SAFE_ZONE_AUDIT.read_text(encoding="utf-8"))
    if audit.get("n_runs") != 80 or len(audit.get("runs", [])) != 80:
        raise ValueError("safe-zone audit must contain exactly 80 runs")
    rows = {
        (row["stratum"], int(row["seed"]), row["optimizer"]): row
        for row in audit["runs"]
    }
    if len(rows) != 80:
        raise ValueError("safe-zone audit has duplicate run identities")

    tier_pairs: dict[str, dict[str, list]] = {
        tier: {} for tier in TIERS
    }
    for stratum, pairs in raw_pairs.items():
        for seed, ea, rand in pairs:
            converted: dict[str, list[dict]] = {tier: [] for tier in TIERS}
            for optimizer, source in (("ea", ea), ("rand", rand)):
                row = rows[(stratum, seed, optimizer)]
                if row.get("validation_status") != "VALID":
                    raise ValueError(f"invalid audited run: {stratum} s{seed} {optimizer}")
                if Path(row["run_dir"]).resolve() != Path(source["dir"]).resolve():
                    raise ValueError(f"audit path mismatch: {stratum} s{seed} {optimizer}")
                if abs(float(row["reported_best_f1"]) - float(source["f1"])) > 1e-12:
                    raise ValueError(f"raw-score mismatch: {stratum} s{seed} {optimizer}")

                raw = float(row["reported_best_f1"])
                core = float(row["core_structural_best_f1"])
                full = float(row["strict_best_f1"])
                if not full <= core <= raw:
                    raise ValueError(
                        "safe-zone tiers are not nested for "
                        f"{stratum} s{seed} {optimizer}: {full}, {core}, {raw}"
                    )
                for tier, definition in TIERS.items():
                    target = dict(source)
                    target["f1"] = float(row[definition["audit_field"]])
                    converted[tier].append(target)

            for tier in TIERS:
                tier_pairs[tier].setdefault(stratum, []).append(
                    (seed, converted[tier][0], converted[tier][1])
                )
    return tier_pairs, excluded, audit


def _analyse_tier(pairs_by_stratum: dict[str, list]) -> dict:
    report = {"strata": {}, "families": {}}
    sign_ps: dict[str, float] = {}
    sign_flip_ps: dict[str, float] = {}
    for stratum in sorted(pairs_by_stratum):
        pairs = pairs_by_stratum[stratum]
        deltas = [float(ea["f1"] - rand["f1"]) for _, ea, rand in pairs]
        sign_p, positive, negative = sign_test(deltas)
        sign_flip_p, sign_flip_note = perm_test_paired(deltas)
        ci_low, ci_high = bootstrap_median_ci(deltas)
        sign_ps[stratum] = sign_p
        sign_flip_ps[stratum] = sign_flip_p
        report["strata"][stratum] = {
            "n_pairs": len(deltas),
            "deltas_f1": deltas,
            "median_delta": statistics.median(deltas),
            "median_percentile_bootstrap_ci": [ci_low, ci_high],
            "mean_delta": sum(deltas) / len(deltas),
            "paired_superiority": paired_superiority(deltas),
            "sign_test": {
                "p": sign_p,
                "positive_pairs": positive,
                "negative_pairs": negative,
                "ties": len(deltas) - positive - negative,
                "note": "ties excluded from the exact binomial test",
            },
            "sign_flip_sensitivity": {
                "p": sign_flip_p,
                "note": (
                    sign_flip_note
                    + "; inferential interpretation assumes within-pair "
                    "exchangeability under the null"
                ),
            },
            "per_seed": [
                {
                    "seed": seed,
                    "ea_f1": ea["f1"],
                    "random_f1": rand["f1"],
                    "delta": ea["f1"] - rand["f1"],
                }
                for seed, ea, rand in pairs
            ],
        }

    report["families"] = {
        "sign_test_superseded": {
            "family": "four model-language strata within this tier",
            "holm": _holm_rows(sign_ps),
        },
        "magnitude_sensitive_sign_flip": {
            "family": "four model-language strata within this tier",
            "holm": _holm_rows(sign_flip_ps),
        },
    }
    report["n_holm_rejections_sign_test_superseded"] = sum(
        row["reject"]
        for row in report["families"]["sign_test_superseded"]["holm"].values()
    )
    return report


def _crosscheck_existing_full(full: dict) -> None:
    existing_path = OUT / "rq2_ea_vs_random.json"
    if not existing_path.exists():
        return
    existing = json.loads(existing_path.read_text(encoding="utf-8"))
    for stratum, row in full["strata"].items():
        previous = existing["strata"][stratum]
        if row["deltas_f1"] != previous["deltas_f1"]:
            raise ValueError(f"full-tier delta mismatch for {stratum}")
        if abs(row["sign_test"]["p"] - previous["primary"]["p"]) > 1e-12:
            raise ValueError(f"full-tier sign-test mismatch for {stratum}")


def _aggregate_issue_counts(audit: dict) -> dict:
    totals = {
        "completed_evaluations": 0,
        "full_contract_invalid_evaluations": 0,
        "core_structural_invalid_evaluations": 0,
        "issue_evaluation_counts": {},
        "issue_combinations": {},
    }
    for row in audit["runs"]:
        totals["completed_evaluations"] += row["n_completed_evaluations"]
        totals["full_contract_invalid_evaluations"] += row["n_structurally_invalid"]
        totals["core_structural_invalid_evaluations"] += row[
            "n_core_structurally_invalid"
        ]
        for key, value in row["issue_evaluation_counts"].items():
            totals["issue_evaluation_counts"][key] = (
                totals["issue_evaluation_counts"].get(key, 0) + value
            )
        for key, value in row["issue_combinations"].items():
            totals["issue_combinations"][key] = (
                totals["issue_combinations"].get(key, 0) + value
            )
    n = totals["completed_evaluations"]
    totals["full_contract_invalid_fraction"] = (
        totals["full_contract_invalid_evaluations"] / n
    )
    totals["core_structural_invalid_fraction"] = (
        totals["core_structural_invalid_evaluations"] / n
    )
    totals["inline_only_rescued_evaluations"] = (
        totals["full_contract_invalid_evaluations"]
        - totals["core_structural_invalid_evaluations"]
    )
    totals["inline_only_rescued_fraction"] = (
        totals["inline_only_rescued_evaluations"] / n
    )
    totals["issue_evaluation_counts"] = dict(
        sorted(totals["issue_evaluation_counts"].items())
    )
    totals["issue_combinations"] = dict(sorted(totals["issue_combinations"].items()))
    return totals


def _render_markdown(report: dict) -> str:
    lines = [
        "# RQ2 safe-zone specification sensitivity",
        "",
        "> **Statistical procedure updated.** The lens data, medians, and intervals in",
        "> this file remain current. Its exact sign tests are superseded provenance. The",
        "> submitted thesis uses exact Wilcoxon signed-rank p-values, A12, and",
        "> lens-specific Holm decisions from `rq_wilcoxon_effect_sizes.json`.",
        "",
        "Unit: one EA/random pair matched by search seed and initialisation bundle.",
        "Outcome: best raw Semgrep-finding reduction (`f1`) observed in 24 hours.",
        "Historical test within each tier: exact two-sided paired sign test; ties are",
        "excluded. Holm correction covers the four model-language strata within",
        "that tier. The sign-flip test is magnitude-sensitive secondary evidence.",
        "",
        "> **Interpretation guardrail.** The core and full tiers are post-hoc",
        "> filters over candidates visited by the historical searches. They do not",
        "> reconstruct fail-closed constrained-search trajectories. The core tier",
        "> is an exploratory component diagnostic and must not be selected as the",
        "> primary result merely because it is more favourable.",
        "",
        "## Three lenses",
        "",
    ]
    for tier, definition in TIERS.items():
        lines.extend(
            [
                f"### {definition['label']}",
                "",
                f"**Status:** {definition['status']}. {definition['description']}",
                "",
                "| stratum | median EA−random [95% boot CI] | paired superiority | + / − / tie | sign p | Holm threshold | Holm rejects |",
                "|---|---:|---:|---:|---:|---:|:--:|",
            ]
        )
        result = report["tiers"][tier]
        holm_rows = result["families"]["sign_test_superseded"]["holm"]
        for stratum in sorted(result["strata"]):
            row = result["strata"][stratum]
            sign = row["sign_test"]
            hrow = holm_rows[stratum]
            ci = row["median_percentile_bootstrap_ci"]
            lines.append(
                f"| {stratum} | {row['median_delta']:.1f} "
                f"[{ci[0]:.1f}, {ci[1]:.1f}] | {row['paired_superiority']:.3f} | "
                f"{sign['positive_pairs']} / {sign['negative_pairs']} / {sign['ties']} | "
                f"{sign['p']:.5f} | {hrow['threshold']:.4f} | "
                f"{'YES' if hrow['reject'] else 'no'} |"
            )
        lines.extend(
            [
                "",
                "Superseded sign-test Holm rejections: "
                f"**{result['n_holm_rejections_sign_test_superseded']}/4**.",
                "",
            ]
        )

    issue = report["safe_zone_component_counts"]
    lines.extend(
        [
            "## Why the full result changes",
            "",
            f"Across {issue['completed_evaluations']:,} completed evaluations, "
            f"{issue['full_contract_invalid_evaluations']:,} "
            f"({issue['full_contract_invalid_fraction']:.1%}) failed the full contract. "
            f"The core tier rejected {issue['core_structural_invalid_evaluations']:,} "
            f"({issue['core_structural_invalid_fraction']:.1%}); "
            f"{issue['inline_only_rescued_evaluations']:,} evaluations "
            f"({issue['inline_only_rescued_fraction']:.1%}) were therefore excluded "
            "only by the inline-code requirement.",
            "",
            "Issue counts overlap because one evaluation can have multiple problems:",
            "",
        ]
    )
    for key, value in issue["issue_evaluation_counts"].items():
        lines.append(f"- `{key}`: {value:,} evaluations")
    lines.extend(
        [
            "",
            "## Thesis-safe synthesis",
            "",
            "In the mutation space executed by the implementation, the archive EA",
            "outperformed matched random search in all four model-language strata",
            "after Holm correction. A post-hoc exploratory sensitivity analysis",
            "retaining frontmatter and fenced-code structure preserved this conclusion",
            "in three strata. Under the most conservative contract, which additionally",
            "required exact inline-code preservation, the paired advantage remained",
            "descriptively positive in all four strata but no comparison remained",
            "significant after family-wise correction. Thus, the algorithmic advantage",
            "is clear for the executed system but sensitive to the strictest",
            "admissibility definition.",
            "",
            "Do not infer from the full-tier non-rejections that EA and random are",
            "equivalent. Also do not claim that a genuinely constrained EA would have",
            "followed the post-hoc filtered trajectory; that counterfactual was not run.",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> int:
    tier_pairs, excluded, audit = _load_and_validate_pairs()
    tiers = {tier: _analyse_tier(pairs) for tier, pairs in tier_pairs.items()}
    _crosscheck_existing_full(tiers["full_contract"])
    report = {
        "artifact_type": "rq2_safe_zone_tier_sensitivity",
        "generated_from": str(SAFE_ZONE_AUDIT),
        "unit_of_analysis": "EA/random search pair matched by seed and initialization bundle",
        "outcome": "best raw Semgrep-finding reduction observed in 24 hours",
        "inference_status": (
            "paired data, medians, and intervals are current; sign-test fields are "
            "superseded by rq_wilcoxon_effect_sizes.json"
        ),
        "primary_test": "exact Wilcoxon signed-rank; stored in rq_wilcoxon_effect_sizes.json",
        "multiplicity": (
            "Holm correction across four model-language strata separately within each "
            "tier; cross-tier comparisons are a nested specification sensitivity, not "
            "three independent confirmatory families"
        ),
        "guardrails": [
            "core and full tiers are post-hoc filters over historical trajectories",
            "core tier is exploratory and was defined after discovering the issue",
            "full-tier non-rejection is not evidence of equivalence",
            "no tier establishes semantic equivalence of mutated rules",
        ],
        "excluded": excluded,
        "tier_definitions": TIERS,
        "safe_zone_component_counts": _aggregate_issue_counts(audit),
        "tiers": tiers,
    }
    write("rq2_safe_zone_tiers.json", json.dumps(report, indent=2) + "\n")
    write("rq2_safe_zone_tiers.md", _render_markdown(report))
    print(_render_markdown(report).split("## Why the full result changes", 1)[0])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
