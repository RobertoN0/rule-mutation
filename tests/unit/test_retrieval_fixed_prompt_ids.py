from __future__ import annotations

import argparse
import json
from pathlib import Path

from src.retrieval.rule_retrieval_mapping_local import (
    compile_mapping,
    load_progress,
    load_prompts_from_maps,
)


def test_fixed_prompt_map_preserves_canonical_task_ids(tmp_path: Path) -> None:
    source = tmp_path / "source.json"
    source.write_text(
        json.dumps(
            {
                "mappings": [
                    {
                        "index": 365,
                        "cwe_id": "CWE-312",
                        "language": "python",
                        "prompt": "first",
                        "prompt_hash": "hash-a",
                    },
                    {
                        "index": 1357,
                        "cwe_id": "CWE-78",
                        "language": "java",
                        "prompt": "second",
                        "prompt_hash": "hash-b",
                    },
                ]
            }
        ),
        encoding="utf-8",
    )

    prompts = load_prompts_from_maps([source])

    assert [row["index"] for row in prompts] == [365, 1357]


def test_progress_position_is_distinct_from_canonical_task_id(
    tmp_path: Path,
) -> None:
    progress = tmp_path / "progress.jsonl"
    progress.write_text(
        json.dumps(
            {
                "_progress_position": 0,
                "index": 365,
                "cwe_id": "CWE-312",
                "language": "python",
                "prompt": "first",
                "prompt_hash": "hash-a",
                "rules_retrieved": ["rule-a"],
                "num_rules": 1,
                "latency_ms": 1.0,
                "parse_method": "json",
            }
        )
        + "\n",
        encoding="utf-8",
    )

    completed = load_progress(progress)
    mapping = compile_mapping(
        completed,
        argparse.Namespace(
            cwes=None,
            languages=None,
            limit_per_cwe=None,
            total_limit=None,
            exclude_map=None,
            temperature=0.6,
        ),
        model_id="model",
        system_message="system",
    )

    assert list(completed) == [0]
    assert mapping["mappings"][0]["index"] == 365
    assert "_progress_position" not in mapping["mappings"][0]
