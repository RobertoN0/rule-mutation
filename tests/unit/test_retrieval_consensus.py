from __future__ import annotations

import argparse
import json
from pathlib import Path

import pytest

from scripts.setup.materialize_retrieval_consensus import parse_seed_list
from src.evaluation.rule_mapping import compute_prompt_hash
from src.retrieval.consensus import (
    MODEL_IDS,
    build_norules_map,
    build_population_carrier,
    materialize_consensus_map,
    merge_consensus_parts,
    validate_retrieval_sweep,
)


def _row(index: int, prompt: str, rules: list[str]) -> dict:
    return {
        "index": index,
        "cwe_id": "CWE-1",
        "language": "python",
        "prompt_hash": compute_prompt_hash(prompt),
        "prompt": prompt,
        "rules_retrieved": rules,
        "num_rules": len(rules),
        "raw_response": json.dumps(rules),
        "parse_method": "json" if rules else "failed",
        "input_tokens": 100,
        "output_tokens": 20,
        "latency_ms": 50.0,
    }


def _map_payload(seed: int, rows: list[dict]) -> dict:
    parse_counts: dict[str, int] = {}
    for row in rows:
        method = row["parse_method"]
        parse_counts[method] = parse_counts.get(method, 0) + 1
    return {
        "metadata": {
            "model": MODEL_IDS["qwen"],
            "seed": seed,
            "temperature": 0.6,
            "total_prompts": len(rows),
            "prompt_template_version": "v2_reframed_user_turn",
            "system_prompt": "fixed retrieval system prompt",
            "user_prompt_template": "fixed retrieval user template",
            "parse_method_stats": parse_counts,
            "model_config": {
                "model": MODEL_IDS["qwen"],
                "quantization": "fp16",
                "bnb_4bit_compute_dtype": None,
                "max_tokens": 1024,
                "seed": seed,
                "temperature": 0.6,
            },
        },
        "mappings": rows,
    }


def _write_fixture_sweep(
    root: Path,
    *,
    seeds: tuple[int, ...] = tuple(range(1, 21)),
    failed_seed: int | None = None,
) -> tuple[Path, Path, list[Path]]:
    rules_dir = root / "rules"
    rules_dir.mkdir()
    (rules_dir / "rule-a.md").write_text("A\n")
    (rules_dir / "rule-b.md").write_text("B\n")
    carrier_rows = [
        _row(0, "first prompt", ["rule-a"]),
        _row(1, "second prompt", ["rule-b"]),
    ]
    carrier = root / "carrier.json"
    carrier.write_text(json.dumps({"mappings": carrier_rows}))
    paths = []
    for position, seed in enumerate(seeds):
        first_rules = ["rule-a"] if position < 11 else ["rule-b"]
        rows = [
            _row(0, "first prompt", first_rules),
            _row(1, "second prompt", ["rule-b"]),
        ]
        if seed == failed_seed:
            rows[0] = _row(0, "first prompt", [])
            rows[0]["raw_response"] = '["invented-rule"]'
        path = root / f"retrieval_map_seed{seed}.json"
        path.write_text(json.dumps(_map_payload(seed, rows)))
        paths.append(path)
    return rules_dir, carrier, paths


def test_retrieval_sweep_requires_twenty_semantically_valid_maps(
    tmp_path: Path,
) -> None:
    rules_dir, carrier, paths = _write_fixture_sweep(
        tmp_path,
        failed_seed=9,
    )

    with pytest.raises(ValueError, match="seed 9.*invalid parse_method"):
        validate_retrieval_sweep(
            paths,
            carrier_path=carrier,
            model="qwen",
            language="python",
            accepted_seeds=tuple(range(1, 21)),
            rules_dir=rules_dir,
        )


def test_consensus_uses_strict_majority_and_canonical_indices(tmp_path: Path) -> None:
    seeds = tuple(range(1, 20)) + (21,)
    rules_dir, carrier, paths = _write_fixture_sweep(tmp_path, seeds=seeds)
    canonical = tmp_path / "canonical.json"
    canonical.write_text(
        json.dumps(
            {
                "mappings": [
                    _row(101, "first prompt", []),
                    _row(102, "second prompt", []),
                ]
            }
        )
    )
    sweep = validate_retrieval_sweep(
        paths,
        carrier_path=carrier,
        model="qwen",
        language="python",
        accepted_seeds=seeds,
        rules_dir=rules_dir,
    )

    result = materialize_consensus_map(
        sweep,
        canonical_carrier_path=canonical,
    )

    assert [row["index"] for row in result["mappings"]] == [101, 102]
    assert result["mappings"][0]["rules_retrieved"] == ["rule-a"]
    assert result["mappings"][0]["seed_frequency"] == {
        "rule-a": 11,
        "rule-b": 9,
    }
    assert result["mappings"][1]["rules_retrieved"] == ["rule-b"]
    assert result["metadata"]["accepted_seeds"] == list(seeds)
    assert result["metadata"]["consensus_min_selections"] == 11


def test_consensus_records_legacy_positional_duplicate_resolution(
    tmp_path: Path,
) -> None:
    rules_dir = tmp_path / "rules"
    rules_dir.mkdir()
    (rules_dir / "rule-a.md").write_text("A\n")
    (rules_dir / "rule-b.md").write_text("B\n")
    carrier_rows = [
        _row(0, "duplicate prompt", ["rule-a"]),
        _row(1, "duplicate prompt", ["rule-b"]),
    ]
    carrier = tmp_path / "legacy-positional-carrier.json"
    carrier.write_text(json.dumps({"mappings": carrier_rows}))
    paths = []
    for seed in range(1, 21):
        path = tmp_path / f"retrieval_map_seed{seed}.json"
        path.write_text(
            json.dumps(
                _map_payload(
                    seed,
                    [
                        _row(0, "duplicate prompt", ["rule-a"]),
                        _row(1, "duplicate prompt", ["rule-b"]),
                    ],
                )
            )
        )
        paths.append(path)
    canonical = tmp_path / "canonical.json"
    canonical.write_text(
        json.dumps({"mappings": [_row(380, "duplicate prompt", [])]})
    )
    sweep = validate_retrieval_sweep(
        paths,
        carrier_path=carrier,
        model="qwen",
        language="python",
        accepted_seeds=tuple(range(1, 21)),
        rules_dir=rules_dir,
    )

    result = materialize_consensus_map(
        sweep,
        canonical_carrier_path=canonical,
    )

    assert result["mappings"][0]["rules_retrieved"] == ["rule-a"]
    assert result["metadata"]["canonical_duplicate_resolutions"] == [
        {
            "canonical_task_id": "380",
            "source_task_id": "0",
            "source_position": 0,
            "source_occurrences": 2,
            "resolution": "first_source_occurrence_for_positional_legacy_carrier",
        }
    ]


def test_merge_requires_exact_full_carrier_coverage(tmp_path: Path) -> None:
    full_carrier = tmp_path / "full.json"
    full_rows = [
        _row(101, "first prompt", []),
        _row(102, "second prompt", []),
    ]
    full_carrier.write_text(json.dumps({"mappings": full_rows}))
    part_paths = []
    for index, row in enumerate(full_rows):
        part = tmp_path / f"part-{index}.json"
        part.write_text(
            json.dumps(
                {
                    "artifact_type": "retrieval_consensus_map",
                    "metadata": {
                        "model": MODEL_IDS["qwen"],
                        "language": "python",
                        "prompt_template_version": "v2_reframed_user_turn",
                        "accepted_seeds": list(range(1, 21)),
                        "retrieval_repetitions": 20,
                        "consensus_min_selections": 11,
                        "retrieval_contract_sha256": "a" * 64,
                    },
                    "mappings": [row],
                }
            )
        )
        part_paths.append(part)

    result = merge_consensus_parts(
        part_paths,
        canonical_carrier_path=full_carrier,
        model="qwen",
        language="python",
    )

    assert [row["index"] for row in result["mappings"]] == [101, 102]
    assert result["metadata"]["total_prompts"] == 2
    assert result["metadata"]["retrieval_contract_sha256"] == "a" * 64


def test_merge_rejects_different_retrieval_contracts(tmp_path: Path) -> None:
    full_carrier = tmp_path / "full.json"
    full_rows = [
        _row(101, "first prompt", []),
        _row(102, "second prompt", []),
    ]
    full_carrier.write_text(json.dumps({"mappings": full_rows}))
    part_paths = []
    for index, row in enumerate(full_rows):
        part = tmp_path / f"part-{index}.json"
        part.write_text(
            json.dumps(
                {
                    "artifact_type": "retrieval_consensus_map",
                    "metadata": {
                        "model": MODEL_IDS["qwen"],
                        "language": "python",
                        "prompt_template_version": "v2_reframed_user_turn",
                        "accepted_seeds": list(range(1, 21)),
                        "retrieval_repetitions": 20,
                        "consensus_min_selections": 11,
                        "retrieval_contract_sha256": f"{index + 1:x}" * 64,
                    },
                    "mappings": [row],
                }
            )
        )
        part_paths.append(part)

    with pytest.raises(ValueError, match="different retrieval contracts"):
        merge_consensus_parts(
            part_paths,
            canonical_carrier_path=full_carrier,
            model="qwen",
            language="python",
        )


def test_norules_map_preserves_identity_and_empties_rules(tmp_path: Path) -> None:
    carrier = tmp_path / "carrier.json"
    carrier.write_text(
        json.dumps({"mappings": [_row(10, "prompt", ["rule-a"])]})
    )

    result = build_norules_map(carrier)

    assert result["artifact_type"] == "no_rules_map"
    assert result["mappings"][0]["index"] == 10
    assert result["mappings"][0]["rules_retrieved"] == []
    assert result["metadata"]["empty_prompts"] == 1


def test_population_carrier_strips_retrieval_evidence(tmp_path: Path) -> None:
    source = tmp_path / "historical-map.json"
    source.write_text(
        json.dumps(
            {
                "metadata": {"dataset": "walledai/CyberSecEval"},
                "mappings": [
                    {
                        **_row(10, "prompt", ["rule-a"]),
                        "raw_response": "historical retrieval output",
                    }
                ],
            }
        )
    )

    result = build_population_carrier(source)

    assert result["artifact_type"] == "task_population_carrier"
    assert result["metadata"]["languages"] == {"python": 1}
    assert result["mappings"] == [
        {
            "index": 10,
            "cwe_id": "CWE-1",
            "language": "python",
            "prompt_hash": compute_prompt_hash("prompt"),
            "prompt": "prompt",
        }
    ]


def test_seed_list_supports_replacement_seed() -> None:
    assert parse_seed_list("1-19,21") == tuple(range(1, 20)) + (21,)
    with pytest.raises(argparse.ArgumentTypeError):
        parse_seed_list("1-3,3")
