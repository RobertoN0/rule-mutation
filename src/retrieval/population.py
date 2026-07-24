"""Prospective task-population eligibility and map filtering."""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from src.retrieval.consensus import (
    canonical_json_sha256,
    load_json_object,
    sha256_file,
    task_content_identity,
    task_identity,
)


ELIGIBILITY_POLICY = "prospective_dataset_content_audit"
ALLOWED_EXCLUSION_REASONS = {
    "explicit_output_language_conflict",
    "exact_duplicate_prompt",
}


def population_fingerprint(rows: list[dict[str, Any]]) -> str:
    identities = [
        {
            "test_case_id": str(row["index"]),
            "analysis_language": str(row["language"]).lower(),
            "prompt_hash": row["prompt_hash"],
        }
        for row in rows
    ]
    return canonical_json_sha256(identities)


def _rows(payload: dict[str, Any], label: str) -> list[dict[str, Any]]:
    rows = payload.get("mappings")
    if not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows):
        raise ValueError(f"{label}: mappings must be a list of objects")
    return rows


def duplicate_prompt_groups(carrier: dict[str, Any]) -> dict[str, list[str]]:
    groups: dict[str, list[str]] = defaultdict(list)
    for row in _rows(carrier, "carrier"):
        groups[str(row["prompt_hash"])].append(str(row["index"]))
    return {
        prompt_hash: task_ids
        for prompt_hash, task_ids in groups.items()
        if len(task_ids) > 1
    }


def validate_eligibility_manifest(
    manifest: dict[str, Any],
    *,
    carrier_path: Path,
    carrier: dict[str, Any] | None = None,
) -> dict[str, dict[str, Any]]:
    """Validate explicit exclusions against immutable carrier identities."""
    carrier = carrier or load_json_object(carrier_path)
    carrier_rows = _rows(carrier, str(carrier_path))
    by_id = {str(row["index"]): row for row in carrier_rows}
    if len(by_id) != len(carrier_rows):
        raise ValueError("carrier contains duplicate task IDs")

    if manifest.get("artifact_type") != "population_eligibility_manifest":
        raise ValueError("eligibility manifest has the wrong artifact_type")
    if manifest.get("policy") != ELIGIBILITY_POLICY:
        raise ValueError("eligibility manifest has the wrong policy")
    source = manifest.get("source_population")
    if not isinstance(source, dict):
        raise ValueError("eligibility manifest lacks source_population")
    if source.get("sha256") != sha256_file(carrier_path):
        raise ValueError("eligibility manifest source-population hash mismatch")
    if source.get("tasks") != len(carrier_rows):
        raise ValueError("eligibility manifest source-population count mismatch")
    if source.get("population_fingerprint") != population_fingerprint(carrier_rows):
        raise ValueError("eligibility manifest source fingerprint mismatch")

    exclusions = manifest.get("exclusions")
    if not isinstance(exclusions, dict):
        raise ValueError("eligibility manifest exclusions must be an object")
    duplicates = duplicate_prompt_groups(carrier)
    for task_id, decision in exclusions.items():
        if not isinstance(decision, dict):
            raise ValueError(f"task {task_id}: exclusion must be an object")
        source_row = by_id.get(str(task_id))
        if source_row is None:
            raise ValueError(f"task {task_id}: not present in source population")
        if decision.get("language") != str(source_row["language"]).lower():
            raise ValueError(f"task {task_id}: language differs from source population")
        if decision.get("prompt_hash") != source_row["prompt_hash"]:
            raise ValueError(f"task {task_id}: prompt_hash differs from source population")
        reason = decision.get("reason")
        if reason not in ALLOWED_EXCLUSION_REASONS:
            raise ValueError(f"task {task_id}: unsupported exclusion reason {reason!r}")
        detail = decision.get("detail")
        if not isinstance(detail, str) or not detail.strip():
            raise ValueError(f"task {task_id}: exclusion detail is required")
        if reason == "explicit_output_language_conflict":
            requested = str(decision.get("requested_language", "")).lower()
            if not requested or requested == str(source_row["language"]).lower():
                raise ValueError(
                    f"task {task_id}: requested_language does not establish a conflict"
                )
        if reason == "exact_duplicate_prompt":
            duplicate_of = str(decision.get("duplicate_of", ""))
            group = duplicates.get(str(source_row["prompt_hash"]), [])
            if duplicate_of not in group or duplicate_of == str(task_id):
                raise ValueError(
                    f"task {task_id}: duplicate_of does not identify its exact duplicate"
                )
    return {str(task_id): decision for task_id, decision in exclusions.items()}


def filter_population_map(
    payload: dict[str, Any],
    *,
    exclusions: dict[str, dict[str, Any]],
    manifest_path: Path,
    manifest: dict[str, Any],
) -> dict[str, Any]:
    """Physically remove excluded tasks and record the eligibility contract."""
    result = json.loads(json.dumps(payload))
    rows = _rows(result, "population map")
    ids = [str(row["index"]) for row in rows]
    if len(ids) != len(set(ids)):
        raise ValueError("population map contains duplicate task IDs")
    relevant_exclusions = {
        task_id: decision
        for task_id, decision in exclusions.items()
        if task_id in set(ids)
    }
    selected = [
        row for row in rows if str(row["index"]) not in relevant_exclusions
    ]
    result["mappings"] = selected
    result["artifact_type"] = "eligible_population_map"
    metadata = result.setdefault("metadata", {})
    metadata["population_eligibility"] = {
        "evidence_status": "final",
        "policy": ELIGIBILITY_POLICY,
        "source_population_total": len(rows),
        "eligible_population_total": len(selected),
        "eligible_population_fingerprint": population_fingerprint(selected),
        "excluded_task_ids": sorted(relevant_exclusions, key=int),
        "exclusions": relevant_exclusions,
        "manifest": {
            "filename": manifest_path.name,
            "sha256": sha256_file(manifest_path),
        },
        "full_source_population": manifest["source_population"],
    }
    frequency = Counter(
        rule for row in selected for rule in row.get("rules_retrieved", [])
    )
    result["rule_frequency"] = dict(sorted(frequency.items()))
    metadata["total_prompts"] = len(selected)
    metadata["empty_prompts"] = sum(
        not row.get("rules_retrieved") for row in selected
    )
    metadata["unique_rules_used"] = len(frequency)
    total_rules = sum(len(row.get("rules_retrieved", [])) for row in selected)
    metadata["avg_rules_per_prompt"] = (
        round(total_rules / len(selected), 3) if selected else 0.0
    )
    return result


def audit_population(carrier_path: Path) -> dict[str, Any]:
    carrier = load_json_object(carrier_path)
    rows = _rows(carrier, str(carrier_path))
    languages = Counter(str(row["language"]).lower() for row in rows)
    return {
        "artifact_type": "population_content_audit",
        "source_population": {
            "filename": carrier_path.name,
            "sha256": sha256_file(carrier_path),
            "tasks": len(rows),
            "population_fingerprint": population_fingerprint(rows),
            "languages": dict(sorted(languages.items())),
        },
        "duplicate_prompt_hashes": duplicate_prompt_groups(carrier),
    }


def assert_same_population(
    left: dict[str, Any],
    right: dict[str, Any],
    *,
    label: str,
) -> None:
    left_rows = _rows(left, "left map")
    right_rows = _rows(right, "right map")
    if [task_identity(row) for row in left_rows] != [
        task_identity(row) for row in right_rows
    ]:
        raise ValueError(f"{label}: map task identities/order differ")
    for left_row, right_row in zip(left_rows, right_rows, strict=True):
        if task_content_identity(left_row) != task_content_identity(right_row):
            raise ValueError(f"{label}: map task content differs")
