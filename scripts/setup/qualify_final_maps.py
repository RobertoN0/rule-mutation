#!/usr/bin/env python3
"""Materialize the predeclared search-population exclusions in the final maps.

The retrieval sweep is retained as provenance in each map's metadata.  This
script changes the actual ``mappings`` list consumed by experiments, so no
second runtime policy can silently change the study population.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path


EXCLUSIONS = {
    "1301": (
        "explicit_language_contradiction",
        "Prompt explicitly requests a Bash script but belongs to the Python stratum.",
    ),
}

DEFAULT_MAPS = (
    "final_consensus_map_qwen_python.json",
    "final_consensus_map_llama_python.json",
    "final_consensus_map_qwen.json",
    "final_consensus_map_llama.json",
    "final_norules_map.json",
)


def _qualify(path: Path) -> tuple[int, int]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    mappings = payload.get("mappings")
    if not isinstance(mappings, list):
        raise ValueError(f"{path}: mappings must be a list")

    original_total = len(mappings)
    removed = [row for row in mappings if str(row.get("index")) in EXCLUSIONS]
    qualified = [row for row in mappings if str(row.get("index")) not in EXCLUSIONS]
    if len({str(row.get("index")) for row in qualified}) != len(qualified):
        raise ValueError(f"{path}: duplicate task IDs remain after qualification")

    metadata = payload.setdefault("metadata", {})
    prior = metadata.get("search_qualification")
    if not removed and isinstance(prior, dict):
        # Idempotent rerun: the exclusion is already reflected in mappings.
        expected = set(prior.get("excluded_task_ids", []))
        if expected != set(EXCLUSIONS):
            raise ValueError(f"{path}: existing qualification disagrees with this script")
    elif path.name in DEFAULT_MAPS and {str(row.get("index")) for row in removed} != set(EXCLUSIONS):
        raise ValueError(f"{path}: expected to remove exactly task 1301")

    # Preserve sweep-level statistics whose source population still had 185
    # Python prompts.  They cannot be recomputed without the gitignored sweeps.
    prequalification_stats = {}
    for key in ("mean_pairwise_jaccard", "avg_rules_per_seed_prompt"):
        if key in metadata and removed:
            prequalification_stats[key] = metadata.pop(key)

    language_counts = Counter(str(row.get("language", "unknown")).lower() for row in qualified)
    rule_frequency = Counter(
        rule_id
        for row in qualified
        for rule_id in row.get("rules_retrieved", [])
    )
    n_rules = sum(len(row.get("rules_retrieved", [])) for row in qualified)
    metadata["total_prompts"] = len(qualified)
    if "distinct_prompts" in metadata:
        metadata["distinct_prompts"] = len(qualified)
    if "languages" in metadata:
        metadata["languages"] = dict(sorted(language_counts.items()))
    if "avg_rules_per_prompt" in metadata:
        metadata["avg_rules_per_prompt"] = round(n_rules / len(qualified), 3) if qualified else 0.0
    if "unique_rules_used" in metadata:
        metadata["unique_rules_used"] = len(rule_frequency)
    if "empty_prompts" in metadata:
        metadata["empty_prompts"] = sum(
            not row.get("rules_retrieved") for row in qualified
        )
    metadata["search_qualification"] = {
        "source_population_total": (
            prior.get("source_population_total", original_total)
            if isinstance(prior, dict)
            else original_total
        ),
        "qualified_population_total": len(qualified),
        "excluded_task_ids": sorted(EXCLUSIONS),
        "exclusions": {
            task_id: {"reason": reason, "detail": detail}
            for task_id, (reason, detail) in EXCLUSIONS.items()
        },
        "policy": "physical_map_membership_no_runtime_filter",
    }
    if metadata.get("kind") == "norules_map":
        metadata["note"] = (
            "empty rules over the qualified vulnerable prompt set "
            "(184 Python + 113 Java); model-agnostic norules baseline"
        )
    if prequalification_stats:
        metadata["prequalification_retrieval_statistics"] = {
            "population_total": original_total,
            **prequalification_stats,
        }

    payload["mappings"] = qualified
    payload["rule_frequency"] = dict(sorted(rule_frequency.items()))
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return original_total, len(qualified)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--map-dir",
        type=Path,
        default=Path(__file__).resolve().parents[2] / "rule_maps",
    )
    args = parser.parse_args()
    for filename in DEFAULT_MAPS:
        path = args.map_dir / filename
        before, after = _qualify(path)
        print(f"{path}: {before} -> {after}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
