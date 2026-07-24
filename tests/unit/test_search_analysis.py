from __future__ import annotations

import json
from pathlib import Path

from scripts.analyze import analyze_search_runs


def _write_run(
    root: Path,
    *,
    optimizer: str,
    f1_values: list[float],
    elapsed: list[float],
    git_commit_sha: str = "d" * 40,
) -> Path:
    run_dir = root / optimizer
    run_dir.mkdir(parents=True)
    args = {
        "model": "model",
        "languages": ["python"],
        "seed": 42,
        "optimizer": optimizer,
        "temperature": 0.0,
        "prompt_profile": "profile",
        "rules_map_sha256": "a" * 64,
        "evaluation_population_fingerprint": "b" * 64,
        "initialization_bundle_content_sha256": "c" * 64,
        "wall_time_budget_seconds": 86_400,
    }
    (run_dir / "run_config.json").write_text(
        json.dumps({"git_commit_sha": git_commit_sha, "args": args}),
        encoding="utf-8",
    )
    rows = []
    for index, f1 in enumerate(f1_values, 1):
        rows.append(
            {
                "evaluation_index": index,
                "main_loop_iteration": index - 5 if index > 5 else None,
                "elapsed_main_loop_seconds": (
                    elapsed[index - 6] if index > 5 else None
                ),
                "evaluation_consumed": True,
                "phase": "initialization" if index <= 5 else optimizer,
                "f1": f1,
            }
        )
    (run_dir / "evaluations.jsonl").write_text(
        "\n".join(json.dumps(row) for row in rows) + "\n",
        encoding="utf-8",
    )
    (run_dir / "search_summary.json").write_text(
        json.dumps(
            {
                "termination_reason": "wall_time_limit",
                "num_evaluations_completed": len(rows),
                "main_loop_evaluations_completed": len(rows) - 5,
                "main_loop_time_seconds": elapsed[-1] + 1,
                "best_raw_findings": 10 - int(max(f1_values)),
                "original_raw_findings": 10,
                "best_num_invalid_prompts": 0,
            }
        ),
        encoding="utf-8",
    )
    return run_dir


def test_analysis_uses_wall_time_primary_and_evaluation_curves(
    tmp_path: Path,
    monkeypatch,
) -> None:
    ea = _write_run(
        tmp_path,
        optimizer="ea",
        f1_values=[0, 1, 0, 1, 0, 2, 4],
        elapsed=[10, 30],
    )
    random_run = _write_run(
        tmp_path,
        optimizer="random_search",
        f1_values=[0, 1, 0, 1, 0, 3, 3],
        elapsed=[20, 40],
    )
    monkeypatch.setattr(
        analyze_search_runs,
        "validate_run",
        lambda _path: {
            "status": "VALID",
            "issues": [],
            "final_search_eligible": True,
        },
    )

    result = analyze_search_runs.analyze(
        [ea, random_run],
        allow_diagnostic=False,
        bootstrap_samples=50,
        bootstrap_seed=7,
        time_step_seconds=10,
    )

    assert result["analysis_policy"]["primary_budget"] == "equal_scheduler_wall_time"
    assert result["paired_runs"][0]["best_f1_difference_ea_minus_random"] == 1
    assert result["analysis_policy"]["inference_unit"] == (
        "matched seed within model/language"
    )
    assert result["incomplete_pairs"] == []
    assert len(result["strata"]) == 1
    stratum = result["strata"][0]
    assert stratum["paired_best_f1_difference"]["values"] == [1.0]
    ea_curve = stratum["curves"]["ea"]["evaluation_curve"]
    assert [row["mean"] for row in ea_curve] == [2.0, 4.0]
    ea_time = stratum["curves"]["ea"]["time_curve"]
    assert ea_time[0]["mean"] == 1.0


def test_final_analysis_rejects_an_unmatched_optimizer(
    tmp_path: Path,
    monkeypatch,
) -> None:
    ea = _write_run(
        tmp_path,
        optimizer="ea",
        f1_values=[0, 1, 0, 1, 0, 2],
        elapsed=[10],
    )
    monkeypatch.setattr(
        analyze_search_runs,
        "validate_run",
        lambda _path: {
            "status": "VALID",
            "issues": [],
            "final_search_eligible": True,
        },
    )

    try:
        analyze_search_runs.analyze(
            [ea],
            allow_diagnostic=False,
            bootstrap_samples=10,
            bootstrap_seed=7,
            time_step_seconds=10,
        )
    except ValueError as exc:
        assert "requires complete EA/random-search pairs" in str(exc)
    else:
        raise AssertionError("unmatched final analysis should fail")


def test_diagnostic_analysis_reports_an_unmatched_optimizer(
    tmp_path: Path,
    monkeypatch,
) -> None:
    ea = _write_run(
        tmp_path,
        optimizer="ea",
        f1_values=[0, 1, 0, 1, 0, 2],
        elapsed=[10],
    )
    monkeypatch.setattr(
        analyze_search_runs,
        "validate_run",
        lambda _path: {
            "status": "VALID",
            "issues": [],
            "final_search_eligible": False,
        },
    )

    result = analyze_search_runs.analyze(
        [ea],
        allow_diagnostic=True,
        bootstrap_samples=10,
        bootstrap_seed=7,
        time_step_seconds=10,
    )

    assert result["paired_runs"] == []
    assert result["incomplete_pairs"][0]["missing_optimizers"] == [
        "random_search"
    ]


def test_final_analysis_rejects_cross_arm_provenance_drift(
    tmp_path: Path,
    monkeypatch,
) -> None:
    ea = _write_run(
        tmp_path,
        optimizer="ea",
        f1_values=[0, 1, 0, 1, 0, 2],
        elapsed=[10],
        git_commit_sha="d" * 40,
    )
    random_run = _write_run(
        tmp_path,
        optimizer="random_search",
        f1_values=[0, 1, 0, 1, 0, 3],
        elapsed=[10],
        git_commit_sha="e" * 40,
    )
    monkeypatch.setattr(
        analyze_search_runs,
        "validate_run",
        lambda _path: {
            "status": "VALID",
            "issues": [],
            "final_search_eligible": True,
        },
    )

    try:
        analyze_search_runs.analyze(
            [ea, random_run],
            allow_diagnostic=False,
            bootstrap_samples=10,
            bootstrap_seed=7,
            time_step_seconds=10,
        )
    except ValueError as exc:
        assert "requires complete EA/random-search pairs" in str(exc)
    else:
        raise AssertionError("provenance-drifted arms should not form a pair")
