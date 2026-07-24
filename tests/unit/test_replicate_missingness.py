from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.analyze.analyze_replicates import effect as analyze_effect
from scripts.analyze.analyze_replicates import _assert_comparable
from scripts.analyze.analyze_replicates import pool
from scripts.experiments.run_replicates import (
    _baseline_effect,
    _load_intermediate,
    _metric_summary,
)


def test_metric_summary_reports_available_n_for_missing_values() -> None:
    records = [
        {
            "seed": 1,
            "raw_findings_per_valid_prompt": 1.0,
            "vulnerable_rate_valid": 0.5,
            "weighted_score_per_valid_prompt": 2.0,
            "invalid_outputs": 1,
        },
        {
            "seed": 2,
            "raw_findings_per_valid_prompt": None,
            "vulnerable_rate_valid": None,
            "weighted_score_per_valid_prompt": None,
            "invalid_outputs": 2,
        },
    ]

    summary = _metric_summary(records)

    assert summary["raw_findings_per_valid_prompt"]["n"] == 1
    assert summary["raw_findings_per_valid_prompt"]["per_seed"] == {1: 1.0}
    assert summary["invalid_outputs"]["n"] == 2


def test_intermediate_loader_excludes_invalid_outputs_instead_of_scoring_zero(
    tmp_path: Path,
) -> None:
    intermediate = tmp_path / "intermediate"
    intermediate.mkdir()
    rows = [
        {
            "test_case_id": "1",
            "qualification_status": "valid",
            "fitness": {"raw_count": 2},
        },
        {
            "test_case_id": "2",
            "qualification_status": "syntax_invalid",
            "fitness": None,
        },
    ]
    (intermediate / "withrules_seed0042.jsonl").write_text(
        "\n".join(json.dumps(row) for row in rows) + "\n"
    )

    assert _load_intermediate(tmp_path, "withrules_seed0042") == {"1": 2}


def _write_intermediate(
    run_dir: Path,
    condition: str,
    seed: int,
    values: dict[str, int | None],
) -> None:
    intermediate = run_dir / "intermediate"
    intermediate.mkdir(parents=True, exist_ok=True)
    rows = []
    for task_id, raw_count in values.items():
        rows.append(
            {
                "test_case_id": task_id,
                "qualification_status": (
                    "valid" if raw_count is not None else "syntax_invalid"
                ),
                "fitness": {"raw_count": raw_count} if raw_count is not None else None,
            }
        )
    (intermediate / f"{condition}_seed{seed:04d}.jsonl").write_text(
        "\n".join(json.dumps(row) for row in rows) + "\n"
    )


def test_baseline_effect_uses_seed_level_common_valid_prompt_effects(
    tmp_path: Path,
) -> None:
    this_dir = tmp_path / "with"
    base_dir = tmp_path / "without"
    _write_intermediate(this_dir, "withrules", 1, {"1": 1, "2": None, "3": 0})
    _write_intermediate(base_dir, "norules", 1, {"1": 3, "2": 4, "3": 0})
    _write_intermediate(this_dir, "withrules", 2, {"1": 0, "2": 2, "3": 1})
    _write_intermediate(base_dir, "norules", 2, {"1": 1, "2": None, "3": 1})
    common_fields = {
        "raw_findings_per_valid_prompt": 1.0,
        "vulnerable_rate_valid": 0.5,
        "weighted_score_per_valid_prompt": 1.0,
        "invalid_outputs": 1,
    }
    this = [{"seed": seed, **common_fields} for seed in (1, 2)]
    base = [{"seed": seed, **common_fields} for seed in (1, 2)]

    effect = _baseline_effect(
        this,
        base,
        this_dir,
        base_dir,
        "withrules",
        "norules",
    )["paired_valid_prompt_effect"]

    assert effect["analysis_unit"] == "seed"
    assert effect["n_seeds"] == 2
    assert effect["total_prompt_pairs_descriptive"] == 4
    assert [row["paired_valid_prompts"] for row in effect["per_seed"]] == [2, 2]
    assert [row["raw_findings_per_prompt_delta"] for row in effect["per_seed"]] == [
        -1.0,
        -0.5,
    ]


def test_standalone_replicate_analysis_uses_all_seed_level_paired_valid_effects(
    tmp_path: Path,
) -> None:
    this_dir = tmp_path / "with"
    base_dir = tmp_path / "without"
    _write_intermediate(this_dir, "withrules", 1, {"1": 1, "2": None, "3": 0})
    _write_intermediate(base_dir, "norules", 1, {"1": 3, "2": 4, "3": 0})
    _write_intermediate(this_dir, "withrules", 2, {"1": 0, "2": 2, "3": 1})
    _write_intermediate(base_dir, "norules", 2, {"1": 1, "2": None, "3": 1})
    metrics = {
        "raw_findings_per_valid_prompt": 1.0,
        "vulnerable_rate_valid": 0.5,
        "weighted_score_per_valid_prompt": 1.0,
        "invalid_outputs": 1,
    }
    treatment = [
        {
            "seed": seed,
            "_run_dir": str(this_dir),
            "intermediate_file": f"intermediate/withrules_seed{seed:04d}.jsonl",
            **metrics,
        }
        for seed in (1, 2)
    ]
    baseline = [
        {
            "seed": seed,
            "_run_dir": str(base_dir),
            "intermediate_file": f"intermediate/norules_seed{seed:04d}.jsonl",
            **metrics,
        }
        for seed in (1, 2)
    ]

    paired = analyze_effect(treatment, baseline)["paired_valid_prompt_effect"]

    assert paired["n_seeds"] == 2
    assert paired["total_prompt_pairs_descriptive"] == 4
    assert [row["raw_findings_per_prompt_delta"] for row in paired["per_seed"]] == [
        -1.0,
        -0.5,
    ]


def test_replicate_pool_rejects_duplicate_condition_seed_evidence(tmp_path: Path) -> None:
    dirs = [tmp_path / "one", tmp_path / "two"]
    for run_dir in dirs:
        run_dir.mkdir()
        (run_dir / "replicates.jsonl").write_text(
            json.dumps({"condition": "withrules", "seed": 42}) + "\n"
        )

    with pytest.raises(ValueError, match="duplicate condition/seed"):
        pool(dirs)


def test_replicate_analysis_rejects_cross_model_pooling(tmp_path: Path) -> None:
    dirs = [tmp_path / "qwen", tmp_path / "llama"]
    for run_dir, model in zip(dirs, ("qwen", "llama")):
        run_dir.mkdir()
        (run_dir / "run_config.json").write_text(
            json.dumps({"git_commit_sha": "a" * 40, "args": {"model": model}})
        )

    with pytest.raises(ValueError, match="incompatible replicate contracts"):
        _assert_comparable(dirs)
