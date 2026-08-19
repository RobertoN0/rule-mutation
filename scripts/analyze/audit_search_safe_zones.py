#!/usr/bin/env python3
"""Audit safe-zone preservation across every completed search evaluation.

The audit is post-hoc and read-only. It recomputes the best structurally valid
f1 attainable in each run; it does not pretend that filtering reconstructs the
trajectory of a search whose archive saw invalid candidates.
"""

from __future__ import annotations

import argparse
import glob
import hashlib
import json
import re
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path


FRONTMATTER_RE = re.compile(r"^---\n.*?\n---\n", re.DOTALL)
FENCE_RE = re.compile(r"```[^\n]*\n.*?```[ \t]*(?:\n|$)", re.DOTALL)
INLINE_RE = re.compile(r"`[^`\n]+`")


def signature(text: str) -> tuple[str, Counter[str], Counter[str], int]:
    match = FRONTMATTER_RE.match(text)
    frontmatter = match.group(0) if match else ""
    fences = FENCE_RE.findall(text)
    prose = FENCE_RE.sub("", text)
    return (
        frontmatter,
        Counter(fences),
        Counter(INLINE_RE.findall(prose)),
        text.count("```"),
    )


def parse_cell(cell: str) -> tuple[str, int, str] | None:
    parts = cell.split("_")
    if len(parts) < 4 or parts[0] not in {"qwen", "llama"}:
        return None
    if parts[1] not in {"java", "python"} or not parts[2].startswith("s"):
        return None
    return f"{parts[0]}_{parts[1]}", int(parts[2][1:]), parts[3]


def audit_run(run_dir: Path, originals: dict[str, tuple]) -> dict:
    cell = run_dir.parent.name
    parsed = parse_cell(cell)
    if parsed is None:
        raise ValueError(f"unrecognized search cell: {cell}")
    stratum, seed, optimizer = parsed
    summary = json.loads((run_dir / "search_summary.json").read_text())
    validation = json.loads((run_dir / "search_validation.json").read_text())

    content_cache: dict[tuple[str, str], tuple[bool, list[str]]] = {}
    evaluated = 0
    invalid = 0
    invalid_evaluation_indices: list[int] = []
    strict: list[dict] = [
        {
            "f1": 0.0,
            "weighted_reduction": 0.0,
            "evaluation_index": 0,
            "chromosome_id": "origin",
        }
    ]
    # Secondary diagnostic tier: preserve frontmatter and fenced-code structure,
    # while allowing inline-code differences. This is reported only to explain
    # which component drives the strict sensitivity result; it is not the full
    # safe-zone contract and must not replace the pre-specified strict result.
    core_structural: list[dict] = list(strict)
    core_structural_invalid = 0
    issue_evaluation_counts: Counter[str] = Counter()
    issue_rule_occurrences: Counter[str] = Counter()
    issue_combinations: Counter[tuple[str, ...]] = Counter()
    invalid_examples: list[dict] = []

    evaluations_path = run_dir / "evaluations.jsonl"
    for line in evaluations_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        record = json.loads(line)
        if record.get("f1") is None:
            continue
        evaluated += 1
        evaluation_index = int(record["evaluation_index"])
        override_dir = run_dir / "mutated_rules" / f"evaluation_{evaluation_index:04d}"
        rule_issues: list[dict] = []
        files = sorted(override_dir.glob("*.md")) if override_dir.exists() else []
        for path in files:
            rule_id = "codeguard-" + path.stem[3:]
            original_signature = originals.get(rule_id)
            if original_signature is None:
                rule_issues.append({"rule_id": rule_id, "issues": ["missing_original"]})
                continue
            content = path.read_bytes()
            digest = hashlib.sha256(content).hexdigest()
            cache_key = (rule_id, digest)
            cached = content_cache.get(cache_key)
            if cached is None:
                candidate_signature = signature(content.decode("utf-8"))
                issues: list[str] = []
                if candidate_signature[0] != original_signature[0]:
                    issues.append("frontmatter")
                if candidate_signature[1] != original_signature[1]:
                    issues.append("fences")
                if candidate_signature[2] != original_signature[2]:
                    issues.append("inline")
                if candidate_signature[3] != original_signature[3]:
                    issues.append("triple_ticks")
                cached = (not issues, issues)
                content_cache[cache_key] = cached
            if not cached[0]:
                rule_issues.append({"rule_id": rule_id, "issues": cached[1]})

        issue_names = {
            issue
            for rule_issue in rule_issues
            for issue in rule_issue["issues"]
        }
        if rule_issues:
            invalid += 1
            invalid_evaluation_indices.append(evaluation_index)
            issue_evaluation_counts.update(issue_names)
            issue_combinations[tuple(sorted(issue_names))] += 1
            issue_rule_occurrences.update(
                issue
                for rule_issue in rule_issues
                for issue in rule_issue["issues"]
            )
            if len(invalid_examples) < 25:
                invalid_examples.append(
                    {
                        "evaluation_index": evaluation_index,
                        "chromosome_id": record.get("chromosome_id"),
                        "f1": record.get("f1"),
                        "rule_issues": rule_issues,
                    }
                )
        candidate_row = {
            "f1": float(record["f1"]),
            "weighted_reduction": (
                float(record["weighted_reduction"])
                if record.get("weighted_reduction") is not None
                else None
            ),
            "evaluation_index": evaluation_index,
            "chromosome_id": record.get("chromosome_id"),
        }
        if not rule_issues:
            strict.append(candidate_row)
        if issue_names - {"inline"}:
            core_structural_invalid += 1
        else:
            core_structural.append(candidate_row)

    strict_best = max(
        strict,
        key=lambda row: (row["f1"], -row["evaluation_index"]),
    )
    core_structural_best = max(
        core_structural,
        key=lambda row: (row["f1"], -row["evaluation_index"]),
    )
    reported_best = float(summary["raw_findings_reduction"])
    return {
        "stratum": stratum,
        "seed": seed,
        "optimizer": optimizer,
        "run_dir": str(run_dir.resolve()),
        "validation_status": validation.get("status"),
        "reported_best_f1": reported_best,
        "strict_best_f1": strict_best["f1"],
        "strict_best_weighted_reduction": strict_best["weighted_reduction"],
        "strict_best_evaluation_index": strict_best["evaluation_index"],
        "strict_best_chromosome_id": strict_best["chromosome_id"],
        "core_structural_best_f1": core_structural_best["f1"],
        "core_structural_best_evaluation_index": core_structural_best[
            "evaluation_index"
        ],
        "core_structural_best_chromosome_id": core_structural_best[
            "chromosome_id"
        ],
        "reported_minus_strict": reported_best - strict_best["f1"],
        "n_completed_evaluations": evaluated,
        "n_structurally_invalid": invalid,
        "n_core_structurally_invalid": core_structural_invalid,
        "issue_evaluation_counts": dict(sorted(issue_evaluation_counts.items())),
        "issue_rule_occurrences": dict(sorted(issue_rule_occurrences.items())),
        "issue_combinations": {
            "+".join(key): value
            for key, value in sorted(issue_combinations.items())
        },
        "invalid_evaluation_indices": invalid_evaluation_indices,
        "invalid_fraction": invalid / evaluated if evaluated else None,
        "invalid_examples_truncated": invalid_examples,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--search-root", type=Path, required=True)
    parser.add_argument("--original-rules", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--workers", type=int, default=8)
    args = parser.parse_args()

    originals = {
        path.stem: signature(path.read_text(encoding="utf-8"))
        for path in args.original_rules.glob("*.md")
    }
    run_dirs = [
        Path(path)
        for path in glob.glob(str(args.search_root / "*" / "arms" / "*" / "job*"))
        if (Path(path) / "evaluations.jsonl").exists()
        and (Path(path) / "search_summary.json").exists()
        and (Path(path) / "search_validation.json").exists()
    ]
    runs: list[dict] = []
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {pool.submit(audit_run, run_dir, originals): run_dir for run_dir in run_dirs}
        for future in as_completed(futures):
            record = future.result()
            runs.append(record)
            print(
                f"{record['stratum']:13s} s{record['seed']:2d} "
                f"{record['optimizer']:4s} {record['reported_best_f1']:.0f} -> "
                f"{record['strict_best_f1']:.0f} "
                f"({record['n_structurally_invalid']} invalid)"
            )

    runs.sort(key=lambda row: (row["stratum"], row["seed"], row["optimizer"]))
    output = {
        "artifact_type": "search_safe_zone_audit",
        "interpretation": (
            "post-hoc strict filter; not equivalent to rerunning an adaptive "
            "search with fail-closed safe-zone enforcement"
        ),
        "n_runs": len(runs),
        "runs": runs,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(output, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {args.output} ({len(runs)} runs)")


if __name__ == "__main__":
    main()
