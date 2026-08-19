#!/usr/bin/env python3
"""Generate SLURM submissions for structurally sanitized Phase-3 candidates."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path


# Defaults to the DelftBlue research worktree this study ran in. Override with
# RULE_MUTATION_REPO to generate submissions from a different checkout.
REPO = Path(os.environ.get("RULE_MUTATION_REPO", "/home/rnegro/thesis/rule-mutation"))
OUTPUT_BASE = REPO / "experiments/06_safe_zone_validation"
SLURM = "scripts/slurm/slurm_replicates.sh"
T0_WALL = {
    "qwen_java": "02:30:00",
    "qwen_python": "03:00:00",
    "llama_java": "03:30:00",
    "llama_python": "04:30:00",
}
T06_WALL = {
    "qwen_java": "10:00:00",
    "qwen_python": "13:00:00",
    "llama_java": "17:00:00",
}


def common_lines(record: dict, label: str, temperature: float) -> list[str]:
    model, language = record["stratum"].split("_")
    return [
        f"MODEL={model} LANGUAGES={language} TEMPERATURE={temperature} \\",
        "  ONLY_OVERRIDDEN=0 \\",
        f"  CONDITION_LABEL={label} \\",
        f"  RULES_OVERRIDE_DIR={record['sanitized_override_dir']} \\",
        f"  WITHRULES_MAP={record['path']} \\",
        f"  OUTPUT_BASE={OUTPUT_BASE} \\",
    ]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--mode", choices=("t0", "t06", "pipeline"), required=True)
    parser.add_argument("--only", default="", help="comma-separated cid prefixes")
    parser.add_argument(
        "--plan",
        type=Path,
        help="pipeline JSON with predecessor_job_id and ordered candidate prefixes",
    )
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    selected = {
        prefix.strip() for prefix in args.only.split(",") if prefix.strip()
    }
    records = json.loads(args.manifest.read_text(encoding="utf-8"))["candidates"]
    records = [record for record in records if not record["strict_safe_zone_valid"]]
    if selected:
        records = [
            record
            for record in records
            if any(record["cid"].startswith(prefix) for prefix in selected)
        ]
        found = {record["cid"][:8] for record in records}
        missing = {
            prefix for prefix in selected
            if not any(value.startswith(prefix) for value in found)
        }
        if missing:
            raise SystemExit(f"unknown candidate prefix(es): {sorted(missing)}")

    lines = [
        "#!/bin/bash",
        "set -euo pipefail",
        f"cd {REPO}",
        f"mkdir -p {OUTPUT_BASE}",
        "",
    ]
    if args.mode == "pipeline":
        if args.plan is None:
            parser.error("--mode pipeline requires --plan")
        plan = json.loads(args.plan.read_text(encoding="utf-8"))
        by_cid = {record["cid"]: record for record in records}
        scheduled: list[str] = []
        for lane_index, lane in enumerate(plan["lanes"], 1):
            lane_var = f"LANE_{lane_index}"
            lines.extend(
                [
                    f"{lane_var}={int(lane['predecessor_job_id'])}",
                    f'echo "lane {lane_index} starts after ${{{lane_var}}}"',
                ]
            )
            for prefix in lane["candidates"]:
                matches = [cid for cid in by_cid if cid.startswith(prefix)]
                if len(matches) != 1:
                    raise SystemExit(
                        f"pipeline prefix {prefix!r} matched {len(matches)} candidates"
                    )
                cid = matches[0]
                if cid in scheduled:
                    raise SystemExit(f"pipeline candidate repeated: {cid}")
                scheduled.append(cid)
                record = by_cid[cid]
                model, language = record["stratum"].split("_")
                short = record["cid"][:8]
                stem = (
                    f"sz_{model[:1]}{language[:2]}_r{record['rank']}_"
                    f"s{record['seed']}_{short}"
                )
                label = f"{stem}_t06"
                if record["stratum"] == "llama_python":
                    first_var = f"{lane_var}_A"
                    output_dir = OUTPUT_BASE / label
                    lines.extend(
                        [
                            f"{first_var}=$( \\",
                            *[f"  {line}" for line in common_lines(record, label, 0.6)],
                            f"  OUTPUT_DIR={output_dir} \\",
                            "  SEEDS=1,2,3,4,5,6,7,8,9,10 \\",
                            f"  sbatch --parsable --dependency=afterok:${{{lane_var}}} "
                            f"--job-name={label}_a --time=13:00:00 {SLURM} )",
                            f"{lane_var}=$( \\",
                            *[f"  {line}" for line in common_lines(record, label, 0.6)],
                            f"  OUTPUT_DIR={output_dir} \\",
                            "  SEEDS=11,12,13,14,15,16,17,18,19,20 \\",
                            f"  sbatch --parsable --dependency=afterok:${{{first_var}}} "
                            f"--job-name={label}_b --time=13:00:00 {SLURM} )",
                            f'echo "{label}: ${{{first_var}}} -> ${{{lane_var}}}"',
                        ]
                    )
                else:
                    lines.extend(
                        [
                            f"{lane_var}=$( \\",
                            *[f"  {line}" for line in common_lines(record, label, 0.6)],
                            "  SEEDS=1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16,17,18,19,20 \\",
                            f"  sbatch --parsable --dependency=afterok:${{{lane_var}}} "
                            f"--job-name={label} --time={T06_WALL[record['stratum']]} {SLURM} )",
                            f'echo "{label}: ${{{lane_var}}}"',
                        ]
                    )
            lines.append("")
        if set(scheduled) != set(by_cid):
            missing = sorted(set(by_cid) - set(scheduled))
            extra = sorted(set(scheduled) - set(by_cid))
            raise SystemExit(f"pipeline coverage mismatch; missing={missing}, extra={extra}")
        args.output.write_text("\n".join(lines), encoding="utf-8")
        args.output.chmod(0o755)
        print(
            f"wrote {args.output} with {len(scheduled)} candidates in "
            f"{len(plan['lanes'])} lanes"
        )
        return

    for record in records:
        model, language = record["stratum"].split("_")
        short = record["cid"][:8]
        stem = (
            f"sz_{model[:1]}{language[:2]}_r{record['rank']}_"
            f"s{record['seed']}_{short}"
        )
        if args.mode == "t0":
            label = f"{stem}_t0"
            lines.extend(common_lines(record, label, 0.0))
            lines.extend(
                [
                    f"  SEEDS={record['seed']} \\",
                    f"  sbatch --job-name={label} --time={T0_WALL[record['stratum']]} {SLURM}",
                    "",
                ]
            )
        elif record["stratum"] == "llama_python":
            label = f"{stem}_t06"
            output_dir = OUTPUT_BASE / label
            lines.extend(
                [
                    "JID=$( \\",
                    *[f"  {line}" for line in common_lines(record, label, 0.6)],
                    f"  OUTPUT_DIR={output_dir} \\",
                    "  SEEDS=1,2,3,4,5,6,7,8,9,10 \\",
                    f"  sbatch --parsable --job-name={label}_a --time=13:00:00 {SLURM} )",
                    f'echo "{label} chunk A = $JID"',
                    *common_lines(record, label, 0.6),
                    f"  OUTPUT_DIR={output_dir} \\",
                    "  SEEDS=11,12,13,14,15,16,17,18,19,20 \\",
                    f"  sbatch --dependency=afterany:$JID --job-name={label}_b --time=13:00:00 {SLURM}",
                    "",
                ]
            )
        else:
            label = f"{stem}_t06"
            lines.extend(common_lines(record, label, 0.6))
            lines.extend(
                [
                    "  SEEDS=1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16,17,18,19,20 \\",
                    f"  sbatch --job-name={label} --time={T06_WALL[record['stratum']]} {SLURM}",
                    "",
                ]
            )

    args.output.write_text("\n".join(lines), encoding="utf-8")
    args.output.chmod(0o755)
    print(f"wrote {args.output} with {len(records)} candidate(s)")


if __name__ == "__main__":
    main()
