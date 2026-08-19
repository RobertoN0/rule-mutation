#!/usr/bin/env python3
"""Compare sanitized-candidate validation runs with their immutable raw sources."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path


def load_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def search_evaluation(record: dict) -> tuple[dict, dict[str, int], float]:
    raw_dir = Path(record["raw_override_dir"])
    run_dir = raw_dir.parents[1]
    evaluation_index = int(raw_dir.name.split("_")[-1])
    evaluations = load_jsonl(run_dir / "evaluations.jsonl")
    matches = [
        row
        for row in evaluations
        if row.get("evaluation_index") == evaluation_index
        and row.get("chromosome_id") == record["cid"]
    ]
    if len(matches) != 1:
        raise ValueError(
            f"expected one source evaluation for {record['cid']}, got {len(matches)}"
        )

    per_case: dict[str, int] = {}
    intermediate = run_dir / "intermediate" / f"evaluation_{evaluation_index:04d}.jsonl"
    for row in load_jsonl(intermediate):
        fitness = row.get("fitness") or {}
        if fitness.get("analysis_status") == "valid":
            per_case[str(row["index"])] = int(fitness["raw_count"])
    summary = json.loads((run_dir / "search_summary.json").read_text(encoding="utf-8"))
    return matches[0], per_case, float(summary["original_raw_findings"])


def discover_results(root: Path) -> dict[str, list[tuple[Path, dict, list[dict]]]]:
    found: dict[str, list[tuple[Path, dict, list[dict]]]] = {}
    if not root.exists():
        return found
    for directory in sorted(path for path in root.iterdir() if path.is_dir()):
        config_path = directory / "run_config.json"
        validation_path = directory / "replicate_validation.json"
        if not config_path.exists() or not validation_path.exists():
            continue
        validation = json.loads(validation_path.read_text(encoding="utf-8"))
        if validation.get("status") != "VALID":
            continue
        args = json.loads(config_path.read_text(encoding="utf-8"))["args"]
        override = args.get("rules_override_dir")
        if not override:
            continue
        found.setdefault(os.path.realpath(override), []).append(
            (directory, args, load_jsonl(directory / "replicates.jsonl"))
        )
    return found


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--results-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    discovered = discover_results(args.results_root)
    output = {
        "artifact_type": "safe_zone_validation_comparison",
        "sanitization_manifest": str(args.manifest.resolve()),
        "results_root": str(args.results_root.resolve()),
        "candidates": [],
    }

    for candidate in manifest["candidates"]:
        if candidate["strict_safe_zone_valid"]:
            continue
        source, source_per_case, original_raw_findings = search_evaluation(candidate)
        source_f1 = float(source["f1"])
        source_candidate_raw = float(source["total_raw_findings"])
        result_runs = discovered.get(
            os.path.realpath(candidate["sanitized_override_dir"]), []
        )
        result_record = {
            "stratum": candidate["stratum"],
            "rank": candidate["rank"],
            "search_seed": candidate["seed"],
            "cid": candidate["cid"],
            "raw_override_dir": candidate["raw_override_dir"],
            "sanitized_override_dir": candidate["sanitized_override_dir"],
            "source_f1": source_f1,
            "source_candidate_raw_findings": source_candidate_raw,
            "source_valid_per_case_raw_sum": sum(source_per_case.values()),
            "source_valid_tasks": len(source_per_case),
            "source_invalid_outputs": int(source["num_invalid_prompts"]),
            "original_raw_findings": original_raw_findings,
            "validation_runs": [],
        }
        for directory, config, replicates in result_runs:
            run = {
                "directory": str(directory.resolve()),
                "condition": config.get("condition") or config.get("condition_label"),
                "temperature": config.get("temperature"),
                "requested_seeds": config.get("seeds"),
                "n_completed": len(replicates),
                "records": [],
            }
            for replicate in sorted(replicates, key=lambda row: row["seed"]):
                repaired_raw = float(replicate["raw_findings"])
                repaired_per_case = {
                    str(key): int(value)
                    for key, value in replicate.get("per_case_raw", {}).items()
                }
                common = sorted(set(source_per_case) & set(repaired_per_case))
                source_vector = [source_per_case[key] for key in common]
                repaired_vector = [repaired_per_case[key] for key in common]
                run["records"].append(
                    {
                        "seed": replicate["seed"],
                        "raw_findings": repaired_raw,
                        "raw_findings_delta_vs_source": (
                            repaired_raw - source_candidate_raw
                        ),
                        "total_raw_findings_identical_to_source": (
                            repaired_raw == source_candidate_raw
                        ),
                        "sanitized_f1": original_raw_findings - repaired_raw,
                        "sanitized_f1_delta_vs_source": (
                            original_raw_findings - repaired_raw - source_f1
                        ),
                        "invalid_outputs": replicate.get("invalid_outputs"),
                        "n_common_tasks_with_source": len(common),
                        "n_source_tasks_missing": len(source_per_case) - len(common),
                        "per_case_raw_identical_to_source": (
                            len(common) == len(source_per_case)
                            and source_vector == repaired_vector
                        ),
                        "n_per_case_count_changes": sum(
                            left != right
                            for left, right in zip(source_vector, repaired_vector)
                        ),
                    }
                )
            result_record["validation_runs"].append(run)
        output["candidates"].append(result_record)

    output["n_candidates"] = len(output["candidates"])
    output["n_with_result_directories"] = sum(
        bool(record["validation_runs"]) for record in output["candidates"]
    )
    output["n_with_results"] = sum(
        any(run["records"] for run in record["validation_runs"])
        for record in output["candidates"]
    )
    completed_records = [
        replicate
        for candidate in output["candidates"]
        for run in candidate["validation_runs"]
        if run["temperature"] == 0.0
        for replicate in run["records"]
    ]
    output["temperature_zero_summary"] = {
        "n_records": len(completed_records),
        "n_total_raw_findings_identical_to_source": sum(
            row["total_raw_findings_identical_to_source"]
            for row in completed_records
        ),
        "n_per_case_identical_to_source": sum(
            row["per_case_raw_identical_to_source"]
            for row in completed_records
        ),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(output, indent=2) + "\n", encoding="utf-8")
    print(
        f"wrote {args.output}; results available for "
        f"{output['n_with_results']}/{output['n_candidates']} candidates"
    )


if __name__ == "__main__":
    main()
