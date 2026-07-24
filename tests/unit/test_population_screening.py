from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.evaluation.population_screening import (
    SCREENING_POLICY,
    ScreeningRun,
    TaskObservation,
    analyze_screening_round,
    combine_screened_language_maps,
    filter_screened_map,
    filter_second_round_candidates,
    finalize_screening,
    load_screening_run,
)
from src.retrieval.consensus import MODEL_IDS, sha256_file, write_json
from src.retrieval.population import ELIGIBILITY_POLICY, population_fingerprint


def _row(task_id: int, language: str = "python") -> dict:
    return {
        "index": task_id,
        "language": language,
        "prompt_hash": f"{task_id:016x}",
        "cwe_id": "CWE-1",
        "prompt": f"Task {task_id}",
        "rules_retrieved": ["codeguard-example"],
        "num_rules": 1,
    }


def _run(
    model: str,
    condition: str,
    rows: list[dict],
    observations: dict[str, TaskObservation],
    *,
    seed: int | tuple[int, ...],
) -> ScreeningRun:
    seeds = (seed,) if isinstance(seed, int) else seed
    source = {"mappings": rows}
    evidence = {
        "git_commit_sha": "a" * 40,
        "model_revision": f"{model[0]}" * 40,
        "torch_version": "2.12.0",
        "transformers_version": "5.9.0",
        "prompt_contract_sha256": "b" * 64,
        "semgrep_rules_source_commit": "c" * 40,
        "semgrep_rules_sha256": "d" * 64,
        "semgrep_version": "1.85.0",
    }
    return ScreeningRun(
        model=model,
        language=str(rows[0]["language"]),
        condition=condition,
        run_dir=Path(f"{model}_{condition}"),
        source_map_path=Path(f"{model}_{condition}.json"),
        source_map=source,
        seeds=seeds,
        observations={
            (screening_seed, task_id): observation
            for screening_seed in seeds
            for task_id, observation in observations.items()
        },
        evidence=evidence,
    )


def _round_runs(
    rows: list[dict],
    cells: dict[tuple[str, str, str], TaskObservation],
    *,
    seed: int | tuple[int, ...],
) -> dict[tuple[str, str], ScreeningRun]:
    return {
        (model, condition): _run(
            model,
            condition,
            rows,
            {
                str(row["index"]): cells[
                    (model, condition, str(row["index"]))
                ]
                for row in rows
            },
            seed=seed,
        )
        for model in ("qwen", "llama")
        for condition in ("norules", "withrules")
    }


def test_two_stage_screening_retains_findings_and_incomplete_evidence(
    tmp_path: Path,
) -> None:
    rows = [_row(task_id) for task_id in (1, 2, 3, 4)]
    cells = {
        (model, condition, str(task_id)): TaskObservation("valid", 0)
        for model in ("qwen", "llama")
        for condition in ("norules", "withrules")
        for task_id in (1, 2, 3, 4)
    }
    cells[("qwen", "norules", "1")] = TaskObservation("valid", 2)
    cells[("llama", "withrules", "2")] = TaskObservation(
        "language_drift",
        None,
    )
    cells[("qwen", "withrules", "4")] = TaskObservation("valid", 1)
    first = analyze_screening_round(
        _round_runs(rows, cells, seed=tuple(range(1, 21))),
        stage="first",
    )

    assert first["task_ids"]["retain_observed_finding"] == ["1", "4"]
    assert first["task_ids"]["retain_incomplete_evidence"] == ["2"]
    assert first["task_ids"]["second_round_candidate"] == ["3"]
    assert first["condition_transition_counts"]["rule_fixed"] == 20
    assert first["condition_transition_counts"]["rule_worsened"] == 20
    assert (
        first["condition_transition_counts"]["valid_to_invalid_with_rules"] == 20
    )

    report_path = tmp_path / "first.json"
    write_json(report_path, first, overwrite=False)
    candidate = filter_second_round_candidates(
        {"mappings": rows},
        first_round=first,
        report_path=report_path,
    )
    assert [row["index"] for row in candidate["mappings"]] == [3]

    second_cells = {
        (model, condition, "3"): TaskObservation("valid", 0)
        for model in ("qwen", "llama")
        for condition in ("norules", "withrules")
    }
    second = analyze_screening_round(
        _round_runs([rows[2]], second_cells, seed=tuple(range(21, 41))),
        stage="second",
    )
    manifest = finalize_screening(first, second)
    assert manifest["retained_task_ids"] == ["1", "2", "4"]
    assert manifest["excluded_never_vulnerable_task_ids"] == ["3"]

    manifest_path = tmp_path / "manifest.json"
    write_json(manifest_path, manifest, overwrite=False)
    screened = filter_screened_map(
        {"mappings": rows},
        screening_manifest=manifest,
        manifest_path=manifest_path,
    )
    assert [row["index"] for row in screened["mappings"]] == [1, 2, 4]


def test_finalize_rejects_overlapping_seed_blocks() -> None:
    rows = [_row(1)]
    cells = {
        (model, condition, "1"): TaskObservation("valid", 0)
        for model in ("qwen", "llama")
        for condition in ("norules", "withrules")
    }
    first = analyze_screening_round(
        _round_runs(rows, cells, seed=tuple(range(1, 21))),
        stage="first",
    )
    second = analyze_screening_round(
        _round_runs(rows, cells, seed=tuple(range(1, 21))),
        stage="second",
    )
    with pytest.raises(ValueError, match="overlap"):
        finalize_screening(first, second)


def test_finalize_requires_twenty_seeds_per_round() -> None:
    rows = [_row(1)]
    cells = {
        (model, condition, "1"): TaskObservation("valid", 0)
        for model in ("qwen", "llama")
        for condition in ("norules", "withrules")
    }
    first = analyze_screening_round(
        _round_runs(rows, cells, seed=tuple(range(1, 20))),
        stage="first",
    )
    second = analyze_screening_round(
        _round_runs(rows, cells, seed=tuple(range(21, 41))),
        stage="second",
    )
    with pytest.raises(ValueError, match="exactly 20 distinct seeds"):
        finalize_screening(first, second)


def test_combine_screened_language_maps() -> None:
    def screened(rows: list[dict]) -> dict:
        return {
            "artifact_type": "screened_population_map",
            "mappings": rows,
            "metadata": {
                "model_key": "qwen",
                "population_eligibility": {
                    "evidence_status": "final",
                    "policy": ELIGIBILITY_POLICY,
                },
                "population_screening": {
                    "evidence_status": "final",
                    "policy": SCREENING_POLICY,
                    "screened_population_total": len(rows),
                    "screened_population_fingerprint": population_fingerprint(rows),
                },
            },
        }

    python_map = screened([_row(1, "python")])
    java_map = screened([_row(2, "java")])
    combined = combine_screened_language_maps(
        python_map,
        java_map,
        model="qwen",
    )
    assert [row["index"] for row in combined["mappings"]] == [1, 2]
    assert combined["metadata"]["languages"] == {"python": 1, "java": 1}


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(row) + "\n" for row in rows),
        encoding="utf-8",
    )


def _screening_fixture(
    tmp_path: Path,
    *,
    intermediate_task_id: str = "1",
) -> tuple[Path, Path]:
    source_map_path = tmp_path / "source.json"
    write_json(source_map_path, {"mappings": [_row(1)]}, overwrite=False)
    run_dir = tmp_path / "run"
    intermediate = Path("intermediate/withrules_seed0010.jsonl")
    _write_jsonl(
        run_dir / intermediate,
        [
            {
                "artifact_type": "replicate_task_evaluation",
                "test_case_id": intermediate_task_id,
                "analysis_language": "python",
                "prompt_hash": f"{1:016x}",
                "qualification_status": "valid",
                "fitness": {"raw_count": 0},
            }
        ],
    )
    replicate = {
        "artifact_type": "replicate_evaluation",
        "condition": "withrules",
        "model": MODEL_IDS["qwen"],
        "language": "python",
        "seed": 10,
        "temperature": 0.6,
        "n_cases": 1,
        "raw_findings_scope": "valid_outputs_only",
        "per_case_raw": {intermediate_task_id: 0},
        "intermediate_file": str(intermediate),
    }
    _write_jsonl(run_dir / "replicates.jsonl", [replicate])
    write_json(run_dir / "replicate_summary.json", {}, overwrite=False)
    prompt_contract = "e" * 64
    write_json(
        run_dir / "run_config.json",
        {
            "artifact_type": "replicate_run_config",
            "git_commit_sha": "a" * 40,
            "args": {
                "run_mode": "replicate",
                "model": MODEL_IDS["qwen"],
                "model_revision": "b" * 40,
                "torch_version": "2.12.0",
                "transformers_version": "5.9.0",
                "languages": ["python"],
                "n_cases": 1,
                "n_cases_requested": None,
                "selection": "first",
                "temperature": 0.6,
                "prompt_contract_sha256": prompt_contract,
                "condition": "withrules",
                "seeds": [10],
                "rules_map_sha256": sha256_file(source_map_path),
                "max_output_tokens": 4096,
                "invalid_output_policy": (
                    "missing_not_zero_with_explicit_denominator"
                ),
                "semgrep_version": "1.85.0",
                "semgrep_rules_source_commit": "c" * 40,
                "semgrep_rules_sha256": "d" * 64,
            },
        },
        overwrite=False,
    )
    write_json(
        run_dir / "replicate_validation.json",
        {
            "artifact_type": "replicate_run_validation",
            "status": "VALID",
            "artifact_sha256": {
                "run_config": sha256_file(run_dir / "run_config.json"),
                "replicates": sha256_file(run_dir / "replicates.jsonl"),
                "replicate_summary": sha256_file(
                    run_dir / "replicate_summary.json"
                ),
            },
        },
        overwrite=False,
    )
    return run_dir, source_map_path


def test_load_screening_run_checks_intermediate_task_identity(
    tmp_path: Path,
) -> None:
    run_dir, source_map = _screening_fixture(
        tmp_path,
        intermediate_task_id="999",
    )
    with pytest.raises(ValueError, match="identities/order"):
        load_screening_run(
            run_dir,
            source_map_path=source_map,
            model="qwen",
            language="python",
            condition="withrules",
            expected_seeds=(10,),
            expected_prompt_contract="e" * 64,
        )
