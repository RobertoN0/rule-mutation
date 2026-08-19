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
            f"80 runs; {evaluations} evaluations; {invalid_full} full-invalid; "
            f"{invalid_core} core-invalid",
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
    expected_rejections = {
        "raw_executed": 4,
        "core_structural": 3,
        "full_contract": 0,
    }
    rq2_ok = set(rq2.get("tiers", {})) == set(expected_rejections)
    for tier, expected in expected_rejections.items():
        result = rq2["tiers"][tier]
        rq2_ok = rq2_ok and set(result["strata"]) == EXPECTED_STRATA
        rq2_ok = rq2_ok and result["n_holm_rejections_primary"] == expected
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
            "four strata x ten matched pairs; primary Holm rejections 4/3/0",
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
            "sanitized T=0 validation",
            t0_ok,
            "12/12 positive; repair delta range -4 to +1 findings",
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

    rq4 = load("rq4_phase3_safe_comparison.json")
    runs = rq4.get("runs", {})
    pending = rq4.get("pending", [])
    multiplicity = rq4.get("multiplicity", {})
    complete_n = multiplicity.get("n_complete_tests")
    rq4_structural_ok = (
        len(runs) == 20
        and multiplicity.get("n_planned_tests") == 20
        and complete_n
        == sum(row.get("n_seeds") == 20 for row in runs.values())
        and all(
            isinstance(row.get("n_seeds"), int)
            and 0 <= row["n_seeds"] <= 20
            for row in runs.values()
        )
    )
    if complete_n == 20:
        rq4_decision_ok = (
            multiplicity.get("family_complete") is True
            and not pending
            and len(multiplicity.get("holm", {})) == 20
        )
        rq4_detail = "20/20 complete; final global Holm family present"
    else:
        rq4_decision_ok = (
            multiplicity.get("family_complete") is False
            and not multiplicity.get("holm")
            and len(pending) == 20 - complete_n
        )
        rq4_detail = (
            f"{complete_n}/20 complete; {len(pending)} pending; Holm correctly withheld"
        )
    gates.append(
        gate(
            "RQ4 artifact consistency",
            rq4_structural_ok and rq4_decision_ok,
            rq4_detail,
        )
    )
    gates.append(
        gate(
            "RQ4 final publication gate",
            complete_n == 20 and rq4_decision_ok,
            rq4_detail,
        )
    )

    figure_names = [
        "fig1_rq1_magnitude",
        "fig2_rq2_safe_zone_tiers",
        "fig4_rq3_operators_effectiveness",
    ]
    figure_ok = all(
        (FIGURES / f"{name}.{ext}").is_file()
        and (FIGURES / f"{name}.{ext}").stat().st_size > 0
        for name in figure_names
        for ext in ("png", "pdf")
    )
    gates.append(
        gate(
            "frozen RQ1-RQ3 figures",
            figure_ok,
            "PNG/PDF pairs exist for the preferred RQ1, RQ2, and RQ3 figures",
        )
    )

    required_ready = all(g["passed"] for g in gates if g["name"] != "RQ4 final publication gate")
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
                "frozen RQ1-RQ3 figures",
            }
        ),
        "rq4_complete": complete_n == 20 and rq4_decision_ok,
        "all_internal_artifact_gates_pass": required_ready,
        "final_report_numbers_ready": final_ready,
        "gates": gates,
        "external_checks_still_required": [
            "compile canonical Python scripts",
            "run safe-zone and sanitizer unit tests",
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
    lines.extend(["", "## External checks still required", ""])
    lines.extend(f"- {item}" for item in report["external_checks_still_required"])
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
