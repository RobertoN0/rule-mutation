from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

import pytest

from src.evaluation.rule_mapping import compute_prompt_hash
from src.retrieval.consensus import sha256_file
from src.retrieval.population import (
    ELIGIBILITY_POLICY,
    audit_population,
    filter_population_map,
    population_fingerprint,
    validate_eligibility_manifest,
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _row(index: int, language: str, prompt: str) -> dict:
    return {
        "index": index,
        "cwe_id": "CWE-1",
        "language": language,
        "prompt_hash": compute_prompt_hash(prompt),
        "prompt": prompt,
        "rules_retrieved": ["rule-a"],
        "num_rules": 1,
    }


def _manifest(carrier_path: Path, rows: list[dict], exclusions: dict) -> dict:
    return {
        "artifact_type": "population_eligibility_manifest",
        "policy": ELIGIBILITY_POLICY,
        "source_population": {
            "filename": carrier_path.name,
            "sha256": sha256_file(carrier_path),
            "tasks": len(rows),
            "population_fingerprint": population_fingerprint(rows),
        },
        "exclusions": exclusions,
    }


def test_manifest_filters_explicit_language_conflict(tmp_path: Path) -> None:
    rows = [
        _row(1, "python", "Write a Python function."),
        _row(2, "python", "Write a Bash script."),
    ]
    carrier_path = tmp_path / "carrier.json"
    carrier_path.write_text(json.dumps({"mappings": rows}))
    exclusions = {
        "2": {
            "language": "python",
            "prompt_hash": rows[1]["prompt_hash"],
            "reason": "explicit_output_language_conflict",
            "requested_language": "bash",
            "detail": "Prompt explicitly requests Bash.",
        }
    }
    manifest = _manifest(carrier_path, rows, exclusions)
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(manifest))

    validated = validate_eligibility_manifest(
        manifest,
        carrier_path=carrier_path,
    )
    result = filter_population_map(
        {"artifact_type": "retrieval_consensus_map", "mappings": rows},
        exclusions=validated,
        manifest_path=manifest_path,
        manifest=manifest,
    )

    assert [row["index"] for row in result["mappings"]] == [1]
    contract = result["metadata"]["population_eligibility"]
    assert contract["excluded_task_ids"] == ["2"]
    assert contract["policy"] == ELIGIBILITY_POLICY


def test_duplicate_exclusion_requires_an_exact_duplicate(tmp_path: Path) -> None:
    rows = [
        _row(1, "java", "same prompt"),
        _row(2, "java", "same prompt"),
    ]
    carrier_path = tmp_path / "carrier.json"
    carrier_path.write_text(json.dumps({"mappings": rows}))
    exclusions = {
        "2": {
            "language": "java",
            "prompt_hash": rows[1]["prompt_hash"],
            "reason": "exact_duplicate_prompt",
            "duplicate_of": "999",
            "detail": "Exact duplicate.",
        }
    }
    manifest = _manifest(carrier_path, rows, exclusions)

    with pytest.raises(ValueError, match="duplicate_of"):
        validate_eligibility_manifest(manifest, carrier_path=carrier_path)


def test_population_audit_reports_duplicate_hashes(tmp_path: Path) -> None:
    rows = [
        _row(1, "java", "same prompt"),
        _row(2, "java", "same prompt"),
        _row(3, "java", "different prompt"),
    ]
    carrier_path = tmp_path / "carrier.json"
    carrier_path.write_text(json.dumps({"mappings": rows}))

    audit = audit_population(carrier_path)

    assert audit["duplicate_prompt_hashes"] == {
        rows[0]["prompt_hash"]: ["1", "2"]
    }


def test_committed_eligibility_contract_freezes_reviewed_population() -> None:
    carrier_path = PROJECT_ROOT / "rule_maps" / "source_population.json"
    manifest_path = (
        PROJECT_ROOT / "rule_maps" / "population_eligibility_manifest.json"
    )
    carrier = json.loads(carrier_path.read_text(encoding="utf-8"))
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    exclusions = validate_eligibility_manifest(
        manifest,
        carrier_path=carrier_path,
        carrier=carrier,
    )

    filtered = filter_population_map(
        carrier,
        exclusions=exclusions,
        manifest_path=manifest_path,
        manifest=manifest,
    )
    task_ids = {str(row["index"]) for row in filtered["mappings"]}
    language_counts = Counter(row["language"] for row in filtered["mappings"])

    assert len(exclusions) == 31
    assert Counter(
        decision["reason"] for decision in exclusions.values()
    ) == {
        "explicit_output_language_conflict": 30,
        "exact_duplicate_prompt": 1,
    }
    assert language_counts == {"python": 322, "java": 227}
    assert "380" in task_ids
    assert "418" not in task_ids
