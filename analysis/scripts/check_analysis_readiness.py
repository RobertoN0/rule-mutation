#!/usr/bin/env python3
"""Fail loudly on contradictions in the compact thesis-analysis package."""
from __future__ import annotations

import argparse
import json

from common import OUT, write


BASE = OUT.parent
FIGURES = BASE / "figures"
EXPECTED_STRATA = {
    "llama_java",
    "llama_python",
    "qwen_java",
    "qwen_python",
}
EXPECTED_MOVES = {
    "add_random_word",
    "negation_injection",
    "paraphrase",
    "section_reorder_degrade",
    "section_reorder_shuffle",
    "synonym_replacement",
    "verb_weakening",
    "voice_change",
    "whole_rule_reorder",
}


def load(name: str) -> dict:
    return json.loads((OUT / name).read_text(encoding="utf-8"))


def gate(name: str, passed: bool, detail: str, *, required: bool = True) -> dict:
    return {
        "name": name,
        "passed": bool(passed),
        "required_for_report": required,
        "detail": detail,
    }


def check() -> dict:
    gates: list[dict] = []

    audit = load("search_safe_zone_audit.json")
    evaluations = sum(row["n_completed_evaluations"] for row in audit["runs"])
    invalid_full = sum(row["n_structurally_invalid"] for row in audit["runs"])
    invalid_core = sum(row["n_core_structurally_invalid"] for row in audit["runs"])
    audit_ok = (
        audit.get("n_runs") == 80
        and len(audit.get("runs", [])) == 80
        and evaluations == 10789
        and invalid_full == 4598
        and invalid_core == 2297
        and all(row.get("validation_status") == "VALID" for row in audit["runs"])
    )
    gates.append(
        gate(
            "search safe-zone audit",
            audit_ok,
            f"80 runs; {evaluations} evaluations; {invalid_full} full-contract "
            f"exclusions; {invalid_core} fenced-code exclusions; "
            f"{invalid_full - invalid_core} inline-only exclusions",
        )
    )

    rq1 = load("rq1_magnitude.json")
    rq1_ok = (
        set(rq1.get("strata", {})) == EXPECTED_STRATA
        and not rq1.get("excluded")
        and all(row["ea_f1"]["n"] == 10 for row in rq1["strata"].values())
    )
    gates.append(gate("RQ1 compact result", rq1_ok, "four strata x ten EA runs"))

    rq2 = load("rq2_safe_zone_tiers.json")
    strict = load("rq2_ea_vs_random.json")
    wilcoxon = load("rq_wilcoxon_effect_sizes.json")["rq2_ea_vs_random"]
    expected_rejections = {
        "raw_executed": 4,
        "core_structural": 4,
        "full_contract": 0,
    }
    rq2_ok = set(rq2.get("tiers", {})) == set(expected_rejections)
    for tier, expected in expected_rejections.items():
        result = rq2["tiers"][tier]
        rq2_ok = rq2_ok and set(result["strata"]) == EXPECTED_STRATA
        rq2_ok = rq2_ok and wilcoxon[tier]["n_holm_rejections"] == expected
        rq2_ok = rq2_ok and set(wilcoxon[tier]["strata"]) == EXPECTED_STRATA
        rq2_ok = rq2_ok and all(
            row["n_pairs"] == 10 for row in result["strata"].values()
        )
    for stratum in EXPECTED_STRATA:
        current = rq2["tiers"]["full_contract"]["strata"][stratum]
        previous = strict["strata"][stratum]
        rq2_ok = rq2_ok and current["deltas_f1"] == previous["deltas_f1"]
        rq2_ok = rq2_ok and abs(
            current["sign_test"]["p"] - previous["primary"]["p"]
        ) < 1e-12
    gates.append(
        gate(
            "RQ2 three-lens result",
            rq2_ok,
            "four strata x ten matched pairs; exact-Wilcoxon Holm rejections 4/4/0",
        )
    )

    rq3 = load("rq3_mutators.json")
    level1 = rq3.get("level1_single_operator", {})
    rq3_ok = (
        rq3.get("n_ea_runs") == 40
        and set(level1) == EXPECTED_STRATA
        and not rq3.get("excluded")
        and all(
            set(row.get("move_families", {})) == EXPECTED_MOVES
            for row in level1.values()
        )
    )
    gates.append(
        gate(
            "RQ3 nine-family result",
            rq3_ok,
            "40 EA runs; eight text operators plus whole-rule reordering",
        )
    )

    safe = load("safe_zone_validation.json")
    candidates = safe.get("candidates", [])
    t0_values = [
        record["sanitized_f1"]
        for candidate in candidates
        for run in candidate.get("validation_runs", [])
        if float(run.get("temperature", -1)) == 0.0
        for record in run.get("records", [])
    ]
    repair_deltas = [
        record["sanitized_f1_delta_vs_source"]
        for candidate in candidates
        for run in candidate.get("validation_runs", [])
        if float(run.get("temperature", -1)) == 0.0
        for record in run.get("records", [])
    ]
    t0_ok = (
        len(candidates) == 12
        and len(t0_values) == 12
        and all(value > 0 for value in t0_values)
        and min(repair_deltas) == -4
        and max(repair_deltas) == 1
    )
    gates.append(
        gate(
            "sanitised T=0 validation",
            t0_ok,
            "12/12 positive; sanitisation delta range -4 to +1 findings",
        )
    )

    selection = load("phase3_selection_topk.json")
    selected = [
        candidate
        for stratum in selection.get("strata", {}).values()
        for candidate in stratum.get("selected", [])
    ]
    selection_ok = len(selected) == 20
    gates.append(gate("RQ4 candidate selection", selection_ok, "20 selected candidates"))

    rq4 = load("rq4_three_way_baseline_comparison.json")
    runs = rq4.get("layer2_candidate_vs_authored", {})
    multiplicity = rq4.get("multiplicity", {}).get("results", {}).get(
        "layer2_candidate_vs_authored", {}
    )
    complete_n = len(runs)
    rq4_structural_ok = (
        complete_n == 20
        and all(row.get("n_seeds") == 20 for row in runs.values())
        and len(rq4.get("common_task_counts", {})) == 4
        and rq4.get("decomposition_check", {}).get("pass") is True
        and rq4.get("decomposition_check", {}).get("n_checked") == 400
        and not rq4.get("problems")
    )
    rq4_decision_ok = (
        multiplicity.get("n_tests") == 20
        and multiplicity.get("n_planned") == 20
        and multiplicity.get("family_complete") is True
        and multiplicity.get("n_raw_p_below_05") == 7
        and multiplicity.get("n_reject") == 0
        and len(multiplicity.get("holm", {})) == 20
    )
    rq4_detail = "20/20 shared-task-set comparisons; 7 nominal, 0 Holm rejections"
    gates.append(
        gate(
            "RQ4 final shared-task-set artifact",
            rq4_structural_ok and rq4_decision_ok,
            rq4_detail,
        )
    )

    figure_names = [
        "rq1_magnitude",
        "rq2_safe_zone_tiers",
        "rq3_operators",
        "rq4_survival",
    ]
    figure_ok = all(
        (FIGURES / f"{name}.{ext}").is_file()
        and (FIGURES / f"{name}.{ext}").stat().st_size > 0
        for name in figure_names
        for ext in ("png", "pdf")
    )
    gates.append(
        gate(
            "frozen thesis-result figures",
            figure_ok,
            "PNG/PDF pairs exist for the RQ1-RQ4 figures used by the thesis",
        )
    )

    required_ready = all(g["passed"] for g in gates)
    final_ready = all(g["passed"] for g in gates)
    return {
        "artifact_type": "analysis_readiness_audit",
        "rq1_to_rq3_ready": all(
            g["passed"]
            for g in gates
            if g["name"]
            in {
                "search safe-zone audit",
                "RQ1 compact result",
                "RQ2 three-lens result",
                "RQ3 nine-family result",
                "frozen thesis-result figures",
            }
        ),
        "rq4_complete": complete_n == 20 and rq4_decision_ok,
        "all_internal_artifact_gates_pass": required_ready,
        "final_report_numbers_ready": final_ready,
        "gates": gates,
        "verification_checklist": [
            "compile canonical Python scripts",
            "run safe-zone and sanitiser unit tests",
            "run git diff --check",
            "regenerate and visually inspect final RQ4 figure after 20/20",
            "cross-check every main.tex number against canonical JSON",
        ],
    }


def render(report: dict) -> str:
    lines = [
        "# Analysis readiness audit",
        "",
        f"- RQ1--RQ3 ready: **{report['rq1_to_rq3_ready']}**",
        f"- RQ4 complete: **{report['rq4_complete']}**",
        f"- Final report numbers ready: **{report['final_report_numbers_ready']}**",
        "",
        "| gate | pass | detail |",
        "|---|:--:|---|",
    ]
    for row in report["gates"]:
        lines.append(
            f"| {row['name']} | {'YES' if row['passed'] else 'no'} | {row['detail']} |"
        )
    lines.extend(["", "## Verification checklist", ""])
    lines.extend(f"- {item}" for item in report["verification_checklist"])
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--require-final",
        action="store_true",
        help="fail unless the 20-candidate RQ4 family is complete",
    )
    args = parser.parse_args()
    report = check()
    write("analysis_readiness.json", json.dumps(report, indent=2) + "\n")
    write("analysis_readiness.md", render(report))
    print(render(report))
    success = report["final_report_numbers_ready"] if args.require_final else report[
        "all_internal_artifact_gates_pass"
    ]
    return 0 if success else 1


if __name__ == "__main__":
    raise SystemExit(main())
