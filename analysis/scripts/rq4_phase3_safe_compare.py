#!/usr/bin/env python3
"""RQ4 comparison using sanitized replays for structurally invalid selections.

The original temperature-0.6 baselines are intentionally reused.  Candidates
that already passed the exact safe-zone contract use their existing Phase-3
replays; candidates that failed it use only the sanitized T=0.6 replays under
``experiments/06_safe_zone_validation``.  No raw and sanitized evidence is
silently mixed.

Inference is paired by stochastic seed.  The exact sign test is primary; an
exact sign-flip test on the mean delta is a magnitude-sensitive sensitivity
analysis whose interpretation requires within-pair exchangeability under the
null. Holm controls one family of all complete candidate-level primary tests.
The selected candidates are not called independent repairs: they share tasks,
models, baselines, and a post-selection procedure.
"""

from __future__ import annotations

import glob
import json
import os
import statistics
from collections import defaultdict
from pathlib import Path

from common import (
    OUT,
    REPO,
    bootstrap_median_ci,
    holm,
    paired_superiority,
    perm_test_paired,
    sign_test,
    write,
)

RAW_PHASE3 = Path(REPO) / "experiments/05_phase3_resampling"
SAFE_PHASE3 = Path(REPO) / "experiments/06_safe_zone_validation"
BASELINES = (
    Path(REPO)
    / "experiments/01_population_and_maps/phase3_screening/block1"
)
QUALIFIED = Path(REPO) / "rule_maps/qualified"
MANIFEST = Path(
    os.environ.get(
        "PHASE3_SANITIZED_MANIFEST",
        "/home/rnegro/analysis/phase3_sanitized/manifest.json",
    )
)
T0_REPORT = OUT / "safe_zone_validation.json"
TARGET_SEEDS = 20
TARGET_K = 5


def load_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def final_task_ids(model: str, language: str) -> set[str]:
    payload = json.loads(
        (QUALIFIED / f"final_search_map_{model}_{language}.json").read_text()
    )
    return {str(row["index"]) for row in payload["mappings"]}


def selected_candidates() -> tuple[dict[str, dict], dict[str, dict]]:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    by_cid: dict[str, dict] = {}
    by_override: dict[str, dict] = {}
    for row in manifest["candidates"]:
        candidate = dict(row)
        candidate["expected_replay_override"] = (
            row["raw_override_dir"]
            if row["strict_safe_zone_valid"]
            else row["sanitized_override_dir"]
        )
        by_cid[row["cid"]] = candidate
        by_override[os.path.realpath(candidate["expected_replay_override"])] = candidate

    # Some existing valid-candidate replays were run on a collaborator account.
    reconciliation = OUT / "phase3_foreign_reconciliation.json"
    if reconciliation.exists():
        resolved = json.loads(reconciliation.read_text())["resolved"]
        for foreign, local in resolved.items():
            local_real = os.path.realpath(local)
            candidate = next(
                (
                    row
                    for row in by_cid.values()
                    if row["strict_safe_zone_valid"]
                    and os.path.realpath(row["raw_override_dir"]) == local_real
                ),
                None,
            )
            if candidate is not None:
                by_override[foreign] = candidate
    return by_cid, by_override


def discover_replays(by_override: dict[str, dict]) -> dict[str, list[Path]]:
    found: dict[str, list[Path]] = defaultdict(list)
    for root in (RAW_PHASE3, SAFE_PHASE3):
        if not root.exists():
            continue
        for name in sorted(glob.glob(str(root / "*"))):
            directory = Path(name)
            config_path = directory / "run_config.json"
            validation_path = directory / "replicate_validation.json"
            if (
                not config_path.exists()
                or not validation_path.exists()
                or not (directory / "replicates.jsonl").exists()
            ):
                continue
            validation = json.loads(validation_path.read_text(encoding="utf-8"))
            if validation.get("status") != "VALID":
                continue
            args = json.loads(config_path.read_text())["args"]
            if float(args.get("temperature", -1)) != 0.6:
                continue
            override = args.get("rules_override_dir")
            if not override:
                continue
            candidate = by_override.get(os.path.realpath(override))
            if candidate is None:
                continue
            expected_root = RAW_PHASE3 if candidate["strict_safe_zone_valid"] else SAFE_PHASE3
            if directory.parent.resolve() != expected_root.resolve():
                continue
            found[candidate["cid"]].append(directory)
    return found


def pool_replicates(directories: list[Path]) -> dict[int, dict]:
    records: dict[int, dict] = {}
    for directory in directories:
        for row in load_jsonl(directory / "replicates.jsonl"):
            seed = int(row["seed"])
            if seed in records:
                raise ValueError(f"duplicate replay seed {seed} in {directories}")
            records[seed] = row
    return records


def source_deterministic(candidate: dict) -> dict:
    raw_dir = Path(candidate["raw_override_dir"])
    run_dir = raw_dir.parents[1]
    evaluation_index = int(raw_dir.name.rsplit("_", 1)[1])
    matches = [
        row
        for row in load_jsonl(run_dir / "evaluations.jsonl")
        if row.get("evaluation_index") == evaluation_index
        and row.get("chromosome_id") == candidate["cid"]
        and row.get("f1") is not None
    ]
    if len(matches) != 1:
        raise ValueError(
            f"expected one source evaluation for {candidate['cid']}, got {len(matches)}"
        )
    summary = json.loads((run_dir / "search_summary.json").read_text())
    return {
        "source": "raw_search_evaluation",
        "origin_raw_findings": float(summary["original_raw_findings"]),
        "candidate_raw_findings": float(matches[0]["total_raw_findings"]),
        "gain": float(matches[0]["f1"]),
        "safe_zone_repair_delta": 0.0,
    }


def t0_deterministic(candidate: dict, t0_by_cid: dict[str, dict]) -> dict | None:
    report = t0_by_cid.get(candidate["cid"])
    if report is None:
        return None
    records = [
        row
        for run in report["validation_runs"]
        if float(run["temperature"]) == 0.0
        for row in run["records"]
    ]
    if len(records) != 1:
        return None
    row = records[0]
    return {
        "source": "sanitized_temperature_zero_validation",
        "origin_raw_findings": float(report["original_raw_findings"]),
        "candidate_raw_findings": float(row["raw_findings"]),
        "gain": float(row["sanitized_f1"]),
        "safe_zone_repair_delta": float(row["sanitized_f1_delta_vs_source"]),
        "total_raw_findings_identical_to_raw_source": row[
            "total_raw_findings_identical_to_source"
        ],
    }


def baseline_replicates(model: str, language: str, condition: str) -> dict[int, dict]:
    directory = BASELINES / f"{model}_{language}_{condition}"
    return {int(row["seed"]): row for row in load_jsonl(directory / "replicates.jsonl")}


def paired_rows(candidate_reps: dict[int, dict], base_reps: dict[int, dict], ids: set[str]):
    rows = []
    for seed in sorted(set(candidate_reps) & set(base_reps)):
        candidate_case = {
            str(key): int(value)
            for key, value in candidate_reps[seed].get("per_case_raw", {}).items()
        }
        baseline_case = {
            str(key): int(value)
            for key, value in base_reps[seed].get("per_case_raw", {}).items()
        }
        common = sorted(ids & set(candidate_case) & set(baseline_case))
        rows.append(
            {
                "seed": seed,
                "candidate": sum(candidate_case[key] for key in common),
                "baseline": sum(baseline_case[key] for key in common),
                "delta": sum(
                    baseline_case[key] - candidate_case[key] for key in common
                ),
                "n_common_tasks": len(common),
                "n_dropped_tasks": len(ids) - len(common),
            }
        )
    return rows


def analyse_rows(rows: list[dict]) -> dict:
    deltas = [float(row["delta"]) for row in rows]
    if not deltas:
        return {"n": 0, "per_seed": rows}
    sign_p, positive, negative = sign_test(deltas)
    flip_p, flip_note = perm_test_paired(deltas)
    lo, hi = bootstrap_median_ci(deltas)
    tasks = [row["n_common_tasks"] for row in rows]
    return {
        "n": len(deltas),
        "median_delta": statistics.median(deltas),
        "median_bootstrap_ci": [lo, hi],
        "mean_delta": statistics.fmean(deltas),
        "paired_superiority": paired_superiority(deltas),
        "sign_test": {
            "p": sign_p,
            "positive": positive,
            "negative": negative,
            "ties": len(deltas) - positive - negative,
        },
        "sign_flip_sensitivity": {
            "p": flip_p,
            "note": flip_note + "; requires within-pair exchangeability under the null",
        },
        "common_tasks": {
            "minimum": min(tasks),
            "maximum": max(tasks),
            "unique_counts": sorted(set(tasks)),
            "task_seed_pairs_dropped": sum(row["n_dropped_tasks"] for row in rows),
        },
        "per_seed": rows,
    }


def main() -> int:
    by_cid, by_override = selected_candidates()
    discovered = discover_replays(by_override)
    t0_payload = json.loads(T0_REPORT.read_text()) if T0_REPORT.exists() else {"candidates": []}
    t0_by_cid = {row["cid"]: row for row in t0_payload["candidates"]}

    output = {
        "artifact_type": "rq4_safe_zone_aware_phase3_comparison",
        "interpretation": (
            "validation-style stochastic resampling of post-selected candidates; "
            "selected candidates share benchmarks, baselines, and model systems"
        ),
        "baseline_policy": "reuse final original-rules/no-rules temperature-0.6 baselines",
        "target_seeds": TARGET_SEEDS,
        "runs": {},
        "pending": [],
    }

    for candidate in sorted(
        by_cid.values(), key=lambda row: (row["stratum"], row["rank"])
    ):
        model, language = candidate["stratum"].split("_")
        deterministic = (
            source_deterministic(candidate)
            if candidate["strict_safe_zone_valid"]
            else t0_deterministic(candidate, t0_by_cid)
        )
        directories = discovered.get(candidate["cid"], [])
        reps = pool_replicates(directories)
        if deterministic is None or len(reps) < TARGET_SEEDS:
            output["pending"].append(
                {
                    "cid": candidate["cid"],
                    "stratum": candidate["stratum"],
                    "rank": candidate["rank"],
                    "deterministic_available": deterministic is not None,
                    "temperature_06_seeds": len(reps),
                }
            )
        comparisons = {}
        ids = final_task_ids(model, language)
        for baseline in ("withrules", "norules"):
            comparisons[baseline] = analyse_rows(
                paired_rows(reps, baseline_replicates(model, language, baseline), ids)
            )
        withrules = comparisons["withrules"]
        surviving = (
            100.0 * withrules["median_delta"] / deterministic["gain"]
            if deterministic is not None
            and deterministic["gain"] != 0
            and withrules.get("n")
            else None
        )
        key = f"{candidate['stratum']}_r{candidate['rank']}_{candidate['cid'][:8]}"
        output["runs"][key] = {
            "stratum": candidate["stratum"],
            "rank": candidate["rank"],
            "search_seed": candidate["seed"],
            "cid": candidate["cid"],
            "candidate_kind": (
                "raw_structurally_valid"
                if candidate["strict_safe_zone_valid"]
                else "sanitized_after_structural_violation"
            ),
            "replay_directories": [str(path.resolve()) for path in directories],
            "n_seeds": len(reps),
            "deterministic": deterministic,
            "pct_of_deterministic_gain_surviving": surviving,
            "comparisons": comparisons,
        }

    complete = {
        key: row
        for key, row in output["runs"].items()
        if (
            row["deterministic"] is not None
            and row["comparisons"]["withrules"].get("n") == TARGET_SEEDS
        )
    }
    all_p_values = {
        key: row["comparisons"]["withrules"]["sign_test"]["p"]
        for key, row in complete.items()
    }
    multiplicity_family_complete = len(all_p_values) == 4 * TARGET_K
    # Withhold interim Holm decisions. Adding the pending candidates changes
    # both the family size and potentially every step-down threshold.
    all_adjusted = holm(all_p_values) if multiplicity_family_complete else {}
    output["multiplicity"] = {
        "family": "all 20 selected-candidate vs original-rules comparisons",
        "n_complete_tests": len(all_p_values),
        "n_planned_tests": 4 * TARGET_K,
        "family_complete": multiplicity_family_complete,
        "decision_status": (
            "final" if multiplicity_family_complete
            else "pending; no Holm decisions until all 20 tests are complete"
        ),
        "method": "Holm family-wise error control; arbitrary dependence allowed",
        "holm": {
            key: {"p": value[0], "threshold": value[1], "reject": value[2]}
            for key, value in all_adjusted.items()
        },
    }

    aggregate = {}
    for stratum in sorted({row["stratum"] for row in output["runs"].values()}):
        family = {
            key: row
            for key, row in complete.items()
            if row["stratum"] == stratum
        }
        p_values = {
            key: row["comparisons"]["withrules"]["sign_test"]["p"]
            for key, row in family.items()
        }
        adjusted = {
            key: all_adjusted[key]
            for key in family
            if key in all_adjusted
        }
        aggregate[stratum] = {
            "k_complete": len(family),
            "k_planned": TARGET_K,
            "n_raw_sign_p_below_05": sum(value < 0.05 for value in p_values.values()),
            "n_holm_reject": (
                sum(value[2] for value in adjusted.values())
                if multiplicity_family_complete
                else None
            ),
            "holm": {
                key: {"p": value[0], "threshold": value[1], "reject": value[2]}
                for key, value in adjusted.items()
            },
            "note": (
                "decisions come from the single planned 20-candidate family and "
                "are withheld until it is complete; Holm allows arbitrary dependence, "
                "but candidates are not independent replications"
            ),
        }
    output["aggregate"] = aggregate

    write("rq4_phase3_safe_comparison.json", json.dumps(output, indent=2))

    lines = [
        "# RQ4 - safe-zone-aware temperature-0.6 resampling",
        "",
        "Invalid selected candidates use sanitized replays; candidates already passing",
        "the contract retain their existing replays. Original baselines are reused.",
        "Positive delta means fewer Semgrep findings than the original-rule baseline.",
        "",
        "| stratum | rank | kind | seeds | T=0 gain | median T=0.6 delta [boot CI] | paired superiority | sign p | surviving |",
        "|---|---:|---|---:|---:|---|---:|---:|---:|",
    ]
    for row in output["runs"].values():
        comparison = row["comparisons"]["withrules"]
        deterministic = row["deterministic"]
        if not deterministic or not comparison.get("n"):
            lines.append(
                f"| {row['stratum']} | {row['rank']} | {row['candidate_kind']} | "
                f"{row['n_seeds']} | pending | pending | pending | pending | pending |"
            )
            continue
        ci = comparison["median_bootstrap_ci"]
        lines.append(
            f"| {row['stratum']} | {row['rank']} | {row['candidate_kind']} | "
            f"{row['n_seeds']} | {deterministic['gain']:.1f} | "
            f"{comparison['median_delta']:.1f} [{ci[0]:.1f}, {ci[1]:.1f}] | "
            f"{comparison['paired_superiority']:.3f} | "
            f"{comparison['sign_test']['p']:.5f} | "
            f"{row['pct_of_deterministic_gain_surviving']:.1f}% |"
        )
    lines += [
        "",
        f"Multiplicity status: {output['multiplicity']['decision_status']}.",
        "The planned Holm family contains all 20 candidate-vs-original comparisons.",
        "",
        "The five candidates per stratum come from different search seeds but share",
        "the same tasks, baseline generations, model system, and selection procedure;",
        "they are selected candidates, not independent repairs.",
        "",
    ]
    write("rq4_phase3_safe_comparison.md", "\n".join(lines))
    print(f"complete candidates: {20 - len(output['pending'])}/20")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
