from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

import pytest


MAP_DIR = Path("rule_maps")


@pytest.mark.parametrize("model", ["qwen", "llama"])
def test_final_search_maps_have_canonical_qualified_populations(model: str) -> None:
    python_map = json.loads(
        (MAP_DIR / f"final_consensus_map_{model}_python.json").read_text()
    )
    java_map = json.loads(
        (MAP_DIR / f"final_consensus_map_{model}_java.json").read_text()
    )
    combined = json.loads((MAP_DIR / f"final_consensus_map_{model}.json").read_text())

    assert len(python_map["mappings"]) == 184
    assert len(java_map["mappings"]) == 113
    assert len(combined["mappings"]) == 297
    assert combined["metadata"]["languages"] == {"java": 113, "python": 184}
    assert "1301" not in {str(row["index"]) for row in combined["mappings"]}
    qualification = combined["metadata"]["search_qualification"]
    assert qualification["excluded_task_ids"] == ["1301"]
    assert qualification["policy"] == "physical_map_membership_no_runtime_filter"


@pytest.mark.parametrize(
    "filename",
    [
        "final_consensus_map_qwen_python.json",
        "final_consensus_map_llama_python.json",
        "final_consensus_map_qwen.json",
        "final_consensus_map_llama.json",
        "final_norules_map.json",
    ],
)
def test_qualified_map_derived_fields_reconcile(filename: str) -> None:
    payload = json.loads((MAP_DIR / filename).read_text())
    mappings = payload["mappings"]
    frequency = Counter(
        rule for row in mappings for rule in row.get("rules_retrieved", [])
    )
    assert payload["metadata"]["total_prompts"] == len(mappings)
    assert payload["rule_frequency"] == dict(sorted(frequency.items()))
    assert len({str(row["index"]) for row in mappings}) == len(mappings)


def test_runtime_policy_file_was_removed() -> None:
    assert not (MAP_DIR / "evaluation_policy.json").exists()
