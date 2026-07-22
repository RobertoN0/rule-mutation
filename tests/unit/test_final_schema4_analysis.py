"""Contract tests for the strict schema-4 final-results analyzer."""

from __future__ import annotations

import csv
import json
import math
import shutil
import sys
from pathlib import Path

import pytest

_ANALYZE = Path(__file__).resolve().parents[2] / "scripts" / "analyze"
sys.path.insert(0, str(_ANALYZE))

from final_schema4.core import (  # noqa: E402
    ManifestEntry,
    analyze_manifest,
    best_chromosome_per_config_rows,
    best_chromosome_rows,
    cost_rows,
    expected_manifest_entries,
    inspect_manifest,
    load_manifest,
    parse_seed_spec,
    per_config_rows,
    rq3_rows,
)
from final_schema4.report import _recurring_edits, write_analysis, write_pending  # noqa: E402
from final_schema4.partial import (  # noqa: E402
    PartialEntry,
    analyze_partial,
    write_partial_analysis,
)


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(row) + "\n" for row in rows),
        encoding="utf-8",
    )


def _prompt(tid: str, raw: int, weighted: float, checks: list[str], iteration: str) -> dict:
    return {
        "iter_id": iteration,
        "test_case_id": tid,
        "language": "python",
        "cwe_id": "CWE-X",
        "rules_used": {
            "original_rule_ids": ["codeguard-0-r"],
            "mutated_rule_ids": ["codeguard-0-r"] if iteration != "baseline" else [],
            "render_order": ["codeguard-0-r"],
            "prompt_affected": iteration != "baseline",
            "chromosome_id": iteration,
        },
        "fitness": {
            "raw_count": raw,
            "weighted_score": weighted,
            "check_ids": checks,
        },
        "generated_code": "ignored by analysis",
    }


def _iteration(
    number: int,
    strategy: str,
    phase: str,
    f1: float | None,
    *,
    attempt: int | None = None,
    attempt_in_iter: int = 1,
    budget: bool = True,
    identity: bool = False,
) -> dict:
    prefix = "ea" if strategy == "ea" else "rand"
    chromosome_id = (
        f"{prefix}_iter{number:04d}"
        if budget
        else f"{prefix}_iter{number:04d}_identity{attempt_in_iter}"
    )
    if number == 1:
        calls, input_tokens, output_tokens = (4, 60, 12)
    elif budget:
        calls, input_tokens, output_tokens = (6, 100, 20)
    else:
        calls, input_tokens, output_tokens = (4, 60, 12)
    return {
        "iter": number,
        "attempt": attempt if attempt is not None else number,
        "attempt_in_iter": attempt_in_iter,
        "budget_consumed": budget,
        "strategy": strategy,
        "phase": phase,
        "chromosome_id": chromosome_id,
        "parent_chromosome_id": "origin",
        "move_type": "mutate" if strategy == "ea" else "sample",
        "rule_id": "codeguard-0-r" if strategy == "ea" else None,
        "mutation_chain": ["verb_weakening"],
        "chain_length": 1,
        "n_requested_changes": 1,
        "n_attempted_changes": 1,
        "n_effective_changes": 0 if identity else 1,
        "attempted_mutators": ["verb_weakening"],
        "mutation_identity": identity,
        "objective_mode": "conservative",
        "f1": f1,
        "f2": 0.9 if f1 is not None else None,
        "f3": -1.0 if f1 is not None else None,
        "rule_fidelity": 0.9 if f1 is not None else None,
        "parsimony": 1.0 if f1 is not None else None,
        "f1_advance": f1 is not None and f1 > 0,
        "mutated_rule_ids": ["codeguard-0-r"],
        "accepted": f1 is not None,
        "llm_calls_total": calls,
        "input_tokens_total": input_tokens,
        "output_tokens_total": output_tokens,
        "n_prompts_reused": 0,
        "n_prompts_rerun": 2 if budget else 0,
        "selection_meta": (
            {"parent_f1": 0.0, "restarts_this_iter": []} if strategy == "ea" else {}
        ),
    }


def _write_run(
    root: Path,
    *,
    optimizer: str,
    job_id: str,
    seed: int = 42,
) -> Path:
    run = root / f"job{job_id}_{optimizer}"
    run.mkdir(parents=True)
    rule_map = root / "rule_maps" / "unavailable_fixture_map.json"
    rule_map.parent.mkdir(parents=True, exist_ok=True)
    rule_map.write_text(
        json.dumps(
            {
                "mappings": [
                    {"index": 1, "language": "python"},
                    {"index": 2, "language": "python"},
                ]
            }
        ),
        encoding="utf-8",
    )
    strategy = optimizer
    iterations = [
        _iteration(1, strategy, "init" if optimizer == "ea" else "random", 3.0),
    ]
    if optimizer == "ea":
        iterations.append(_iteration(2, strategy, "ea", None, budget=False, identity=True))
        iterations.append(_iteration(2, strategy, "ea", 4.0, attempt=3, attempt_in_iter=2))
    else:
        iterations.append(_iteration(2, strategy, "random", 3.0))
    _write_jsonl(run / "iterations.jsonl", iterations)
    baseline = [
        _prompt("1", 2, 4.0, ["check-a"], "baseline"),
        _prompt("2", 0, 0.0, [], "baseline"),
    ]
    _write_jsonl(run / "intermediate" / "baseline.jsonl", baseline)
    prefix = "ea" if optimizer == "ea" else "rand"
    _write_jsonl(
        run / "intermediate" / f"{prefix}_iter0001.jsonl",
        [
            _prompt("1", 1, 1.0, ["check-a"], f"{prefix}_iter0001"),
            _prompt("2", 0, 0.0, [], f"{prefix}_iter0001"),
        ],
    )
    _write_jsonl(
        run / "intermediate" / f"{prefix}_iter0002.jsonl",
        [
            _prompt(
                "1",
                0 if optimizer == "ea" else 1,
                0.0 if optimizer == "ea" else 1.0,
                [],
                f"{prefix}_iter0002",
            ),
            _prompt("2", 0, 0.0, [], f"{prefix}_iter0002"),
        ],
    )
    config = {
        "schema_version": 4,
        "git_sha": "abc123",
        "slurm_job_id": job_id,
        "args": {
            "backend": "delftblue",
            "model": "Qwen/Qwen2.5-Coder-32B-Instruct",
            "temperature": 0.0,
            "rules_map": "unavailable_fixture_map.json",
            "optimizer": optimizer,
            "languages": ["python"],
            "seed": seed,
            "n_cases": 2,
            "iterations": 2,
            "selection": "first",
            "mutators": ["verb_weakening"],
            "objective_direction": "minimize",
            "enable_validation": True,
            "enable_eval_cache": True,
            "ea_init_samples": 1,
            "ea_move": "local",
        },
    }
    (run / "run_config.json").write_text(json.dumps(config), encoding="utf-8")
    summary = {
        "llm_provider": "DelftBlueLocalHF",
        "llm_model": "Qwen/Qwen2.5-Coder-32B-Instruct",
        "mutators": ["verb_weakening"],
        "max_iterations": 2,
        "num_iterations_run": 2,
        "original_fitness": 4,
        "best_fitness": 0 if optimizer == "ea" else 1,
        "improvement": -4 if optimizer == "ea" else -3,
        "total_time_seconds": 10,
        "total_llm_calls": 6,
        "total_input_tokens": 100,
        "total_output_tokens": 20,
        "pool_arm_stats": {
            "strategy": optimizer,
            "restart_reason_counts": {"stagnation": 0, "exhausted": 0},
        },
        "eval_cache_stats": {
            "enabled": True,
            "hits": 0,
            "misses": 6,
            "total_entries": 6,
        },
    }
    (run / "hillclimb_summary_x.json").write_text(json.dumps(summary), encoding="utf-8")
    _write_jsonl(
        run / "semgrep_debug" / "semgrep_debug.jsonl",
        [{"error": None, "findings_count": 0} for _ in range(6)],
    )
    (run / "run.log").write_text("run complete\nresults saved\n", encoding="utf-8")
    prefix = "ea" if optimizer == "ea" else "rand"
    for iteration in (1, 2):
        iter_dir = run / "mutated_rules" / f"iter{iteration:03d}"
        iter_dir.mkdir(parents=True)
        (iter_dir / "cg-0-r.md").write_text("mutated", encoding="utf-8")
        (iter_dir / "meta.json").write_text(
            json.dumps(
                {
                    "iteration": iteration,
                    "chromosome_id": f"{prefix}_iter{iteration:04d}",
                    "parent_id": "origin",
                    "move_type": "mutate" if optimizer == "ea" else "sample",
                    "changed_rule_id": "codeguard-0-r" if optimizer == "ea" else None,
                    "chain": ["verb_weakening"],
                    "mutated_rule_ids": ["codeguard-0-r"],
                    "order_priority": {},
                    "changes": [],
                    "gene_paths": {"codeguard-0-r": ["verb_weakening"]},
                    "accepted": True,
                    "validation_metadata": {},
                }
            ),
            encoding="utf-8",
        )
    if optimizer == "ea":
        text_ref = "mutated_rules/iter002/cg-0-r.md"
        mutated = run / text_ref
        mutated.write_text("mutated", encoding="utf-8")
        snapshot = {
            "iter": 2,
            "schema_version": 4,
            "origin": {"cid": "origin", "f1": 0.0, "f2": 1.0, "f3": 0.0},
            "chromosomes": [
                {
                    "cid": "ea_iter0002",
                    "f1": 4.0,
                    "f2": 0.9,
                    "f3": -1.0,
                    "mutated_rule_ids": ["codeguard-0-r"],
                    "order_priority": {},
                    "iteration_added": 2,
                    "genes": {
                        "codeguard-0-r": {
                            "mutation_path": ["verb_weakening"],
                            "depth": 1,
                            "text_ref": text_ref,
                        }
                    },
                }
            ],
        }
        snapshot_path = run / "archive_snapshots" / "iter0002.json"
        snapshot_path.parent.mkdir(parents=True)
        snapshot_path.write_text(json.dumps(snapshot), encoding="utf-8")
    return run


def _subset_dir(tmp_path: Path) -> Path:
    subset = tmp_path / "subsets"
    subset.mkdir()
    with (subset / "baseline_common_python.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["tid", "qwen_class"])
        writer.writeheader()
        writer.writerow({"tid": "1", "qwen_class": "PERSISTENT"})
        writer.writerow({"tid": "2", "qwen_class": "NEVER"})
    return subset


def test_health_separates_proposals_from_evaluations(tmp_path):
    ea = _write_run(tmp_path, optimizer="ea", job_id="101")
    random_run = _write_run(tmp_path, optimizer="random_search", job_id="102")
    health = inspect_manifest(
        [
            ManifestEntry("python", "ea", "42", "101", ea),
            ManifestEntry("python", "random_search", "42", "102", random_run),
        ]
    )
    assert all(item.healthy for item in health)
    ea_health = next(item for item in health if item.actual_optimizer == "ea")
    assert ea_health.n_proposals == 3
    assert ea_health.n_evaluated == 2
    assert ea_health.n_identity == 1


def test_manifest_model_must_match_exact_config_family(tmp_path):
    qwen = _write_run(tmp_path, optimizer="ea", job_id="101")
    health = inspect_manifest([ManifestEntry("python", "ea", "42", "101", qwen, model="llama")])[0]
    assert not health.healthy
    assert any("model mismatch" in issue for issue in health.issues)


def test_analysis_rejects_mixed_model_bundle(tmp_path):
    qwen = _write_run(tmp_path / "qwen", optimizer="ea", job_id="101")
    llama = _write_run(tmp_path / "llama", optimizer="ea", job_id="102")
    config_path = llama / "run_config.json"
    config = json.loads(config_path.read_text(encoding="utf-8"))
    config["args"]["model"] = "meta-llama/Llama-3.3-70B-Instruct"
    config_path.write_text(json.dumps(config), encoding="utf-8")
    summary_path = llama / "hillclimb_summary_x.json"
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    summary["llm_model"] = "meta-llama/Llama-3.3-70B-Instruct"
    summary_path.write_text(json.dumps(summary), encoding="utf-8")

    with pytest.raises(ValueError, match="one model family"):
        analyze_manifest(
            [
                ManifestEntry("python", "ea", "42", "101", qwen, model="qwen"),
                ManifestEntry("python", "ea", "42", "102", llama, model="llama"),
            ],
            subset_dir=_subset_dir(tmp_path),
        )


def test_partial_path_accepts_only_validated_active_prefix(tmp_path):
    ea = _write_run(tmp_path, optimizer="ea", job_id="101")
    config_path = ea / "run_config.json"
    config = json.loads(config_path.read_text(encoding="utf-8"))
    config["args"]["iterations"] = 3
    config["timestamp"] = "RECONSTRUCTED_pre_completion"
    config["_reconstructed"] = "fixture active-run provenance"
    config_path.write_text(json.dumps(config), encoding="utf-8")
    (ea / "hillclimb_summary_x.json").unlink()
    shutil.rmtree(ea / "semgrep_debug")
    (ea / "run.log").write_text("candidate 3 is still running\n", encoding="utf-8")
    entry = ManifestEntry("python", "ea", "42", "101", ea, model="qwen")

    strict_health = inspect_manifest([entry])[0]
    assert not strict_health.healthy
    assert any("reconstructed pre-completion" in issue for issue in strict_health.issues)

    bundle = analyze_partial(
        [PartialEntry(entry=entry, declared_model_family="qwen")],
        subset_dir=_subset_dir(tmp_path),
        repo_root=tmp_path,
        source_description="unit-test active snapshot",
    )
    assert len(bundle.runs) == 1
    assert bundle.runs[0].analysis.comparison_budget == 2
    assert any("reconstructed pre-completion" in caution for caution in bundle.statuses[0].cautions)

    out = tmp_path / "partial-analysis"
    write_partial_analysis(out, bundle)
    report = (out / "PARTIAL_REPORT.md").read_text(encoding="utf-8")
    assert "PROVISIONAL / IN_PROGRESS" in report
    assert (out / "partial_run_metrics.csv").is_file()
    assert not (out / "rq3_ea_vs_random.csv").exists()


def test_analysis_uses_origin_floor_and_prompt_level_best(tmp_path):
    ea = _write_run(tmp_path, optimizer="ea", job_id="101")
    random_run = _write_run(tmp_path, optimizer="random_search", job_id="102")
    bundle = analyze_manifest(
        [
            ManifestEntry("python", "ea", "42", "101", ea),
            ManifestEntry("python", "random_search", "42", "102", random_run),
        ],
        subset_dir=_subset_dir(tmp_path),
    )
    assert bundle.common_budgets == {"python": 2}
    assert len(bundle.runs) == 2
    ea_analysis = next(run for run in bundle.runs if run.optimizer == "ea")
    random_analysis = next(run for run in bundle.runs if run.optimizer == "random_search")
    assert ea_analysis.best_f1_final == 4.0
    assert ea_analysis.task_summaries_budget["persistent"]["n_repaired"] == 1
    assert random_analysis.task_summaries_budget["persistent"]["n_repaired"] == 0
    comparison = next(row for row in rq3_rows(bundle.runs) if row["metric"] == "best_f1")
    assert comparison["a12_ea_vs_random"] == 1.0
    chromosome = next(row for row in best_chromosome_rows(bundle.runs) if row["optimizer"] == "ea")
    assert chromosome["final_front_f1"] == 4.0
    assert chromosome["n_rules_mutated"] == 1
    representatives = {
        row["optimizer"]: row for row in best_chromosome_per_config_rows(bundle.runs)
    }
    assert representatives["ea"]["representative_seed"] == "42"
    assert representatives["ea"]["final_front_f1"] == 4.0
    assert representatives["random_search"]["representative_run"] is None


def test_lone_healthy_arm_remains_available_for_rq1(tmp_path):
    ea = _write_run(tmp_path, optimizer="ea", job_id="101")
    bundle = analyze_manifest(
        [ManifestEntry("python", "ea", "42", "101", ea)],
        subset_dir=_subset_dir(tmp_path),
    )
    assert bundle.common_budgets == {}
    assert bundle.analysis_budgets == {"python": 2}
    assert len(bundle.runs) == 1
    assert bundle.healths[0].healthy


def test_cross_arm_baseline_task_mismatch_is_unhealthy(tmp_path):
    ea = _write_run(tmp_path, optimizer="ea", job_id="101")
    random_run = _write_run(tmp_path, optimizer="random_search", job_id="102")
    for path in [
        random_run / "intermediate" / "baseline.jsonl",
        random_run / "intermediate" / "rand_iter0001.jsonl",
        random_run / "intermediate" / "rand_iter0002.jsonl",
    ]:
        rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
        for row in rows:
            if row["test_case_id"] == "2":
                row["test_case_id"] = "3"
        _write_jsonl(path, rows)
    healths = inspect_manifest(
        [
            ManifestEntry("python", "ea", "42", "101", ea),
            ManifestEntry("python", "random_search", "42", "102", random_run),
        ]
    )
    assert all(not health.healthy for health in healths)
    assert all(
        any("baseline task-set mismatch" in issue for issue in health.issues) for health in healths
    )


def test_cross_arm_baseline_fingerprint_mismatch_is_unhealthy(tmp_path):
    ea = _write_run(tmp_path, optimizer="ea", job_id="101")
    random_run = _write_run(tmp_path, optimizer="random_search", job_id="102")
    baseline_path = random_run / "intermediate" / "baseline.jsonl"
    rows = [json.loads(line) for line in baseline_path.read_text(encoding="utf-8").splitlines()]
    rows[1]["fitness"]["raw_count"] = 1
    rows[1]["fitness"]["check_ids"] = ["info-only-check"]
    _write_jsonl(baseline_path, rows)
    healths = inspect_manifest(
        [
            ManifestEntry("python", "ea", "42", "101", ea),
            ManifestEntry("python", "random_search", "42", "102", random_run),
        ]
    )
    assert all(not health.healthy for health in healths)
    assert all(
        any("raw/weighted/check/CWE mismatch" in issue for issue in health.issues)
        for health in healths
    )


def test_semgrep_error_field_is_required(tmp_path):
    ea = _write_run(tmp_path, optimizer="ea", job_id="101")
    debug_path = ea / "semgrep_debug" / "semgrep_debug.jsonl"
    rows = [json.loads(line) for line in debug_path.read_text(encoding="utf-8").splitlines()]
    rows[0].pop("error")
    _write_jsonl(debug_path, rows)
    health = inspect_manifest([ManifestEntry("python", "ea", "42", "101", ea)])[0]
    assert not health.healthy
    assert any("omit the required error field" in issue for issue in health.issues)


def test_graceful_inflight_discard_keeps_completed_outcomes_eligible(tmp_path):
    ea = _write_run(tmp_path, optimizer="ea", job_id="101")
    config_path = ea / "run_config.json"
    config = json.loads(config_path.read_text(encoding="utf-8"))
    config["args"]["iterations"] = 3
    config_path.write_text(json.dumps(config), encoding="utf-8")
    summary_path = ea / "hillclimb_summary_x.json"
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    summary["max_iterations"] = 3
    summary["total_llm_calls"] += 1
    summary["total_input_tokens"] += 10
    summary["total_output_tokens"] += 2
    summary["eval_cache_stats"]["misses"] += 1
    summary_path.write_text(json.dumps(summary), encoding="utf-8")
    (ea / "run.log").write_text(
        "Pre-timeout during iteration 3 — discarding in-flight; "
        "finalizing from 2 completed iterations.\n"
        "results saved\n",
        encoding="utf-8",
    )

    health = inspect_manifest([ManifestEntry("python", "ea", "42", "101", ea)])[0]
    assert health.healthy
    assert health.stop_class == "graceful_pre_timeout"
    assert any("partial work" in warning for warning in health.warnings)
    assert any("partial prompt" in warning for warning in health.warnings)


def test_random_graceful_inflight_accounting_uses_random_log_wording(tmp_path):
    random_run = _write_run(tmp_path, optimizer="random_search", job_id="102")
    config_path = random_run / "run_config.json"
    config = json.loads(config_path.read_text(encoding="utf-8"))
    config["args"]["iterations"] = 3
    config_path.write_text(json.dumps(config), encoding="utf-8")
    summary_path = random_run / "hillclimb_summary_x.json"
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    summary["max_iterations"] = 3
    summary["total_llm_calls"] += 1
    summary["total_input_tokens"] += 10
    summary["total_output_tokens"] += 2
    summary["eval_cache_stats"]["misses"] += 1
    summary_path.write_text(json.dumps(summary), encoding="utf-8")
    (random_run / "run.log").write_text(
        "Pre-timeout mid-eval — stopping after 2 iterations.\nresults saved\n",
        encoding="utf-8",
    )

    health = inspect_manifest([ManifestEntry("python", "random_search", "42", "102", random_run)])[
        0
    ]
    assert health.healthy
    assert health.stop_class == "graceful_pre_timeout"
    assert any("partial work" in warning for warning in health.warnings)
    assert any("partial prompt" in warning for warning in health.warnings)


def test_missing_semgrep_debug_requires_explicit_qualified_override(tmp_path):
    ea = _write_run(tmp_path, optimizer="ea", job_id="101")
    shutil.rmtree(ea / "semgrep_debug")
    entry = ManifestEntry("python", "ea", "42", "101", ea)

    strict = inspect_manifest([entry])[0]
    assert not strict.healthy
    assert "semgrep_debug/semgrep_debug.jsonl missing or empty" in strict.issues

    qualified = inspect_manifest(
        [entry],
        expected_languages=["python"],
        expected_optimizers=["ea"],
        allow_missing_semgrep_debug=True,
    )[0]
    assert qualified.healthy
    assert not qualified.issues
    assert any(warning.startswith("QUALIFIED OVERRIDE:") for warning in qualified.warnings)
    assert not any(
        warning.startswith("manifest omits configuration cells:") for warning in qualified.warnings
    )


def test_eval_cache_requires_deterministic_temperature(tmp_path):
    ea = _write_run(tmp_path, optimizer="ea", job_id="101")
    config_path = ea / "run_config.json"
    config = json.loads(config_path.read_text(encoding="utf-8"))
    config["args"]["temperature"] = 0.7
    config_path.write_text(json.dumps(config), encoding="utf-8")

    health = inspect_manifest([ManifestEntry("python", "ea", "42", "101", ea)])[0]
    assert not health.healthy
    assert any("requires temperature=0" in issue for issue in health.issues)


def test_final_full_population_rejects_a_larger_sampled_map(tmp_path):
    ea = _write_run(tmp_path, optimizer="ea", job_id="101")
    map_path = ea.parent / "rule_maps" / "unavailable_fixture_map.json"
    payload = json.loads(map_path.read_text(encoding="utf-8"))
    payload["mappings"].append({"index": 3, "language": "python"})
    map_path.write_text(json.dumps(payload), encoding="utf-8")

    health = inspect_manifest([ManifestEntry("python", "ea", "42", "101", ea)])[0]
    assert not health.healthy
    assert any(
        "final full-population runs must evaluate the entire language map" in issue
        for issue in health.issues
    )


def test_final_snapshot_objectives_must_match_accepted_iteration(tmp_path):
    ea = _write_run(tmp_path, optimizer="ea", job_id="101")
    snapshot_path = ea / "archive_snapshots" / "iter0002.json"
    snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
    snapshot["chromosomes"][0]["f1"] = 99.0
    snapshot_path.write_text(json.dumps(snapshot), encoding="utf-8")
    health = inspect_manifest([ManifestEntry("python", "ea", "42", "101", ea)])[0]
    assert not health.healthy
    assert any(
        "objectives do not match its accepted iteration record" in issue for issue in health.issues
    )


def test_candidate_prompt_chromosome_provenance_is_reconciled(tmp_path):
    ea = _write_run(tmp_path, optimizer="ea", job_id="101")
    candidate_path = ea / "intermediate" / "ea_iter0002.jsonl"
    rows = [json.loads(line) for line in candidate_path.read_text(encoding="utf-8").splitlines()]
    rows[0]["rules_used"]["chromosome_id"] = "wrong-chromosome"
    _write_jsonl(candidate_path, rows)
    bundle = analyze_manifest(
        [ManifestEntry("python", "ea", "42", "101", ea)],
        subset_dir=_subset_dir(tmp_path),
    )
    assert bundle.runs == []
    assert any(
        "prompt provenance does not match iteration" in error for error in bundle.extraction_errors
    )


def test_extraction_exclusion_recomputes_common_budget(tmp_path):
    ea = _write_run(tmp_path, optimizer="ea", job_id="101", seed=42)
    random_run = _write_run(tmp_path, optimizer="random_search", job_id="102", seed=42)
    malformed_short = _write_run(tmp_path, optimizer="random_search", job_id="103", seed=43)
    iteration_rows = [
        json.loads(line)
        for line in (malformed_short / "iterations.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    _write_jsonl(malformed_short / "iterations.jsonl", iteration_rows[:1])
    shutil.rmtree(malformed_short / "mutated_rules" / "iter002")
    summary_path = malformed_short / "hillclimb_summary_x.json"
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    summary["num_iterations_run"] = 1
    summary["total_llm_calls"] = 4
    summary["total_input_tokens"] = 60
    summary["total_output_tokens"] = 12
    summary["eval_cache_stats"]["misses"] = 4
    summary["eval_cache_stats"]["total_entries"] = 4
    summary_path.write_text(json.dumps(summary), encoding="utf-8")
    _write_jsonl(
        malformed_short / "semgrep_debug" / "semgrep_debug.jsonl",
        [{"error": None, "findings_count": 0} for _ in range(4)],
    )
    candidate_path = malformed_short / "intermediate" / "rand_iter0001.jsonl"
    candidate_rows = [
        json.loads(line) for line in candidate_path.read_text(encoding="utf-8").splitlines()
    ]
    candidate_rows.append(dict(candidate_rows[0]))
    _write_jsonl(candidate_path, candidate_rows)
    (malformed_short / "run.log").write_text("graceful stop\nresults saved\n", encoding="utf-8")

    bundle = analyze_manifest(
        [
            ManifestEntry("python", "ea", "42", "101", ea),
            ManifestEntry("python", "random_search", "42", "102", random_run),
            ManifestEntry("python", "random_search", "43", "103", malformed_short),
        ],
        subset_dir=_subset_dir(tmp_path),
    )

    assert bundle.common_budgets == {"python": 2}
    assert len(bundle.runs) == 2
    assert any("duplicate test_case_id=1" in error for error in bundle.extraction_errors)
    malformed_health = next(health for health in bundle.healths if health.entry.job_id == "103")
    assert not malformed_health.healthy


def test_seed_spec_and_expected_matrix_are_explicit():
    assert parse_seed_spec("1-3,3,7,10") == ["1", "2", "3", "7", "10"]
    entries = expected_manifest_entries(
        Path("experiments/final"),
        seeds=parse_seed_spec("1-10"),
    )
    assert len(entries) == 80
    assert len({entry.key for entry in entries}) == 80


def test_manifest_resolves_direct_and_single_child_seed_leaves(tmp_path):
    repo = tmp_path / "repo"
    direct = repo / "experiments" / "final" / "qwen" / "python" / "ea" / "seed1"
    nested_container = (
        repo / "experiments" / "final" / "qwen" / "python" / "random_search" / "seed1"
    )
    nested = nested_container / "job102_rand_python_s1_0719"
    direct.mkdir(parents=True)
    nested.mkdir(parents=True)
    (direct / "run_config.json").write_text(
        json.dumps({"slurm_job_id": "101"}),
        encoding="utf-8",
    )
    (nested / "run_config.json").write_text(
        json.dumps({"slurm_job_id": "102"}),
        encoding="utf-8",
    )
    manifest = tmp_path / "analysis" / "manifest.csv"
    manifest.parent.mkdir()
    manifest.write_text(
        "model,language,optimizer,seed,run_dir\n"
        "qwen,python,ea,1,experiments/final/qwen/python/ea/seed1\n"
        "qwen,python,random_search,1,"
        "experiments/final/qwen/python/random_search/seed1\n",
        encoding="utf-8",
    )

    entries = load_manifest(manifest, repo_root=repo)
    assert entries[0].run_dir == direct
    assert entries[0].resolution_issue == ""
    assert entries[1].run_dir == nested
    assert entries[1].resolution_issue == ""


def test_manifest_rejects_ambiguous_seed_container(tmp_path):
    repo = tmp_path / "repo"
    container = repo / "experiments" / "final" / "qwen" / "java" / "ea" / "seed2"
    for job_id in ("201", "202"):
        child = container / f"job{job_id}_ea_java_s2_0719"
        child.mkdir(parents=True)
        (child / "run_config.json").write_text(
            json.dumps({"slurm_job_id": job_id}),
            encoding="utf-8",
        )
    manifest = tmp_path / "manifest.csv"
    manifest.write_text(
        "model,language,optimizer,seed,run_dir\n"
        "qwen,java,ea,2,experiments/final/qwen/java/ea/seed2\n",
        encoding="utf-8",
    )

    entry = load_manifest(manifest, repo_root=repo)[0]
    assert entry.run_dir == container
    assert "multiple run dirs" in entry.resolution_issue


def test_job_id_resolution_uses_recorded_provenance_not_folder_name(tmp_path):
    repo = tmp_path / "repo"
    results = repo / "experiments" / "final" / "qwen"
    run = results / "python" / "ea" / "seed3"
    run.mkdir(parents=True)
    (run / "run_config.json").write_text(
        json.dumps({"slurm_job_id": "303"}),
        encoding="utf-8",
    )
    manifest = tmp_path / "manifest.csv"
    manifest.write_text(
        "model,language,optimizer,seed,job_id\nqwen,python,ea,3,303\n",
        encoding="utf-8",
    )

    entry = load_manifest(
        manifest,
        repo_root=repo,
        results_roots=[results],
    )[0]
    assert entry.run_dir == run
    assert entry.resolution_issue == ""


def test_expected_seed_contract_detects_seed_missing_from_every_arm(tmp_path):
    entries = expected_manifest_entries(
        tmp_path / "runs",
        seeds=parse_seed_spec("1-9"),
    )
    healths = inspect_manifest(entries, expected_seeds=parse_seed_spec("1-10"))
    warnings = {warning for health in healths for warning in health.warnings}
    assert any("manifest violates expected seed contract" in warning for warning in warnings)
    assert any("('qwen', 'java', 'ea', '10')" in warning for warning in warnings)


def test_pending_writer_never_invents_values(tmp_path):
    out = tmp_path / "analysis"
    expected = expected_manifest_entries(Path("experiments/final"))
    write_pending(
        out,
        reason="fixture has no final manifest",
        expected_entries=expected,
    )
    assert "[PENDING: final runs]" in (out / "REPORT.md").read_text(encoding="utf-8")
    assert (out / "run_health.csv").is_file()
    assert (out / "convergence.png").is_file()
    assert (out / "convergence.svg").is_file()
    assert "0/11 data-dependent checks assessed" in (out / "VALIDATION.md").read_text(
        encoding="utf-8"
    )
    assert "[PENDING: final runs]" in (out / "METHODS.md").read_text(encoding="utf-8")
    rows = list(csv.DictReader((out / "analysis_manifest_template.csv").open(encoding="utf-8")))
    assert len(rows) == 80
    assert (
        len({(row["model"], row["language"], row["optimizer"], row["seed"]) for row in rows}) == 80
    )
    assert {(row["model"], row["language"], row["optimizer"]) for row in rows} == {
        (model, language, optimizer)
        for model in ("qwen", "llama")
        for language in ("python", "java")
        for optimizer in ("ea", "random_search")
    }
    assert rows[0]["run_dir"] == "experiments/final/qwen/python/ea/seed1"
    assert rows[-1]["run_dir"] == "experiments/final/llama/java/random_search/seed10"
    assert all(not row["job_id"] and not row["log_path"] for row in rows)


def test_complete_report_path_on_synthetic_schema4_manifest(tmp_path):
    ea = _write_run(tmp_path / "runs", optimizer="ea", job_id="101")
    random_run = _write_run(tmp_path / "runs", optimizer="random_search", job_id="102")
    bundle = analyze_manifest(
        [
            ManifestEntry("python", "ea", "42", "101", ea),
            ManifestEntry("python", "random_search", "42", "102", random_run),
        ],
        subset_dir=_subset_dir(tmp_path),
    )
    out = tmp_path / "analysis"
    manifest = tmp_path / "manifest.csv"
    manifest.write_text("language,optimizer,seed,job_id\n", encoding="utf-8")
    write_analysis(
        out,
        bundle,
        manifest_path=manifest,
        repo_root=Path(__file__).resolve().parents[2],
    )
    assert "Healthy runs analyzed: 2/2" in (out / "REPORT.md").read_text(encoding="utf-8")
    assert "[PENDING: final runs]" not in (out / "per_config_summary.csv").read_text(
        encoding="utf-8"
    )
    assert (out / "best_chromosomes.md").is_file()
    assert (out / "best_chromosome_per_config.csv").is_file()
    assert (out / "check_flips.svg").is_file()
    assert (out / "rq3_friedman_sensitivity.csv").is_file()
    assert (out / "rq2_per_family.csv").is_file()
    assert (
        "accepted_and_security_improving"
        in (out / "rq2_per_operator.csv").read_text(encoding="utf-8").splitlines()[0]
    )
    assert (
        "codegen_calls_full_run"
        in (out / "cost_hygiene.csv").read_text(encoding="utf-8").splitlines()[0]
    )
    assert "repaired_rate" in (out / "cwe_repair.csv").read_text(encoding="utf-8").splitlines()[0]
    assert (
        "baseline_present" in (out / "check_flips.csv").read_text(encoding="utf-8").splitlines()[0]
    )
    cwe_rows = list(csv.DictReader((out / "cwe_repair.csv").open(encoding="utf-8")))
    assert {(row["language"], row["optimizer"], row["subset_scope"]) for row in cwe_rows} == {
        ("python", "ea", "baseline_vulnerable_movable"),
        ("python", "random_search", "baseline_vulnerable_movable"),
    }
    assert {row["optimizer"]: float(row["repaired_rate"]) for row in cwe_rows} == {
        "ea": 1.0,
        "random_search": 0.0,
    }
    check_rows = list(csv.DictReader((out / "check_flips.csv").open(encoding="utf-8")))
    assert {row["optimizer"]: row["baseline_present"] for row in check_rows} == {
        "ea": "1",
        "random_search": "1",
    }
    assert "DESCRIPTIVE_ONLY_POST_SELECTION" in (out / "rq3_friedman_sensitivity.csv").read_text(
        encoding="utf-8"
    )
    assert "baseline raw median [IQR]" in (out / "tables.md").read_text(encoding="utf-8")
    assert "ANALYZED_WITH_CAUTION" in (out / "REPORT.md").read_text(encoding="utf-8")
    assert "nonrectangular" in (out / "VALIDATION.md").read_text(encoding="utf-8").lower()
    assert "Not applicable: random search has no persistent Pareto archive" in (
        out / "best_chromosomes.md"
    ).read_text(encoding="utf-8")
    assert (out / "METHODS.md").is_file()


def test_subset_rows_are_subset_specific_and_single_seed_ci_is_unavailable(tmp_path):
    ea = _write_run(tmp_path, optimizer="ea", job_id="101")
    bundle = analyze_manifest(
        [ManifestEntry("python", "ea", "42", "101", ea)],
        subset_dir=_subset_dir(tmp_path),
    )
    rows = {
        row["subset"]: row
        for row in per_config_rows(bundle.runs)
        if row["language"] == "python" and row["optimizer"] == "ea"
    }
    assert rows["persistent"]["baseline_raw_median"] == 2
    assert rows["variable"]["baseline_raw_median"] == 0
    assert math.isnan(rows["full"]["seed_rate_bootstrap_low"])
    assert "fewer than 2 eligible seeds" in rows["full"]["rate_inference_note"]
    comparison = rq3_rows(bundle.runs)
    assert comparison == []


def test_unknown_subset_token_cannot_claim_complete_classification(tmp_path):
    ea = _write_run(tmp_path, optimizer="ea", job_id="101")
    subset = _subset_dir(tmp_path)
    subset_path = subset / "baseline_common_python.csv"
    rows = list(csv.DictReader(subset_path.open(encoding="utf-8")))
    rows[0]["qwen_class"] = "PERSISTNENT_TYPO"
    with subset_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["tid", "qwen_class"])
        writer.writeheader()
        writer.writerows(rows)
    bundle = analyze_manifest(
        [ManifestEntry("python", "ea", "42", "101", ea)],
        subset_dir=subset,
    )
    assert not bundle.runs[0].subset_classification_complete
    persistent = next(row for row in per_config_rows(bundle.runs) if row["subset"] == "persistent")
    assert persistent["subset_status"].startswith("UNAVAILABLE")


def test_missing_cost_telemetry_excludes_run_without_zero_fabrication(tmp_path):
    ea = _write_run(tmp_path, optimizer="ea", job_id="101")
    summary_path = ea / "hillclimb_summary_x.json"
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    summary.pop("total_llm_calls")
    summary_path.write_text(json.dumps(summary), encoding="utf-8")

    entry = ManifestEntry("python", "ea", "42", "101", ea)
    health = inspect_manifest([entry])[0]
    assert not health.healthy
    assert any("summary total_llm_calls is missing/invalid" in issue for issue in health.issues)

    bundle = analyze_manifest([entry], subset_dir=_subset_dir(tmp_path))
    assert bundle.runs == []
    assert cost_rows(bundle.runs) == []
    out = tmp_path / "analysis"
    manifest = tmp_path / "manifest.csv"
    manifest.write_text("language,optimizer,seed,job_id\n", encoding="utf-8")
    write_analysis(out, bundle, manifest_path=manifest, repo_root=tmp_path)
    pending_cost = list(csv.DictReader((out / "cost_hygiene.csv").open(encoding="utf-8")))
    assert len(pending_cost) == 1
    assert set(pending_cost[0].values()) == {"[PENDING: final runs]"}


def test_persistent_baseline_drift_is_an_analysis_caution(tmp_path):
    ea = _write_run(tmp_path, optimizer="ea", job_id="101")
    subset = _subset_dir(tmp_path)
    subset_path = subset / "baseline_common_python.csv"
    rows = list(csv.DictReader(subset_path.open(encoding="utf-8")))
    rows[1]["qwen_class"] = "PERSISTENT"
    with subset_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["tid", "qwen_class"])
        writer.writeheader()
        writer.writerows(rows)

    bundle = analyze_manifest(
        [ManifestEntry("python", "ea", "42", "101", ea)],
        subset_dir=subset,
    )
    assert any(
        "persistent-baseline drift: 1" in warning for warning in bundle.runs[0].subset_warnings
    )
    assert any("persistent-baseline drift: 1" in warning for warning in bundle.analysis_warnings)
    assert bundle.has_cautions
    persistent = next(row for row in per_config_rows(bundle.runs) if row["subset"] == "persistent")
    assert persistent["subset_status"].startswith("AVAILABLE_WITH_CAUTION")


def test_qwen_subset_labels_are_not_applied_to_llama(tmp_path):
    ea = _write_run(tmp_path, optimizer="ea", job_id="101")
    config_path = ea / "run_config.json"
    config = json.loads(config_path.read_text(encoding="utf-8"))
    config["args"]["model"] = "meta-llama/Llama-3.3-70B-Instruct"
    config_path.write_text(json.dumps(config), encoding="utf-8")
    summary_path = ea / "hillclimb_summary_x.json"
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    summary["llm_model"] = "meta-llama/Llama-3.3-70B-Instruct"
    summary_path.write_text(json.dumps(summary), encoding="utf-8")

    bundle = analyze_manifest(
        [ManifestEntry("python", "ea", "42", "101", ea, model="llama")],
        subset_dir=_subset_dir(tmp_path),
    )
    run = bundle.runs[0]
    assert not run.subset_classification_complete
    assert any("labels are unavailable for model" in warning for warning in run.subset_warnings)
    persistent = next(row for row in per_config_rows(bundle.runs) if row["subset"] == "persistent")
    assert persistent["subset_status"].startswith("UNAVAILABLE")


def test_recurring_exact_text_is_not_split_by_mutation_path(tmp_path):
    first = _write_run(tmp_path, optimizer="ea", job_id="101", seed=42)
    second = _write_run(tmp_path, optimizer="ea", job_id="102", seed=43)
    snapshot_path = second / "archive_snapshots" / "iter0002.json"
    snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
    snapshot["chromosomes"][0]["genes"]["codeguard-0-r"]["mutation_path"] = ["paraphrase"]
    snapshot_path.write_text(json.dumps(snapshot), encoding="utf-8")

    bundle = analyze_manifest(
        [
            ManifestEntry("python", "ea", "42", "101", first),
            ManifestEntry("python", "ea", "43", "102", second),
        ],
        subset_dir=_subset_dir(tmp_path),
    )
    recurring = _recurring_edits(bundle.runs)
    assert len(recurring) == 1
    assert recurring[0]["n_distinct_seeds"] == 2
    assert recurring[0]["mutation_paths"] == ['["paraphrase"]', '["verb_weakening"]']


def test_blank_cwe_or_check_id_is_excluded_during_metric_extraction(tmp_path):
    ea = _write_run(tmp_path, optimizer="ea", job_id="101")
    candidate_path = ea / "intermediate" / "ea_iter0001.jsonl"
    rows = [json.loads(line) for line in candidate_path.read_text(encoding="utf-8").splitlines()]
    rows[0]["cwe_id"] = ""
    rows[1]["fitness"]["check_ids"] = [""]
    _write_jsonl(candidate_path, rows)

    bundle = analyze_manifest(
        [ManifestEntry("python", "ea", "42", "101", ea)],
        subset_dir=_subset_dir(tmp_path),
    )
    assert bundle.runs == []
    assert any("cwe_id is blank" in error for error in bundle.extraction_errors)

    check_run = _write_run(tmp_path / "check", optimizer="ea", job_id="102")
    check_path = check_run / "intermediate" / "ea_iter0001.jsonl"
    check_rows = [json.loads(line) for line in check_path.read_text(encoding="utf-8").splitlines()]
    check_rows[0]["fitness"]["check_ids"] = [""]
    _write_jsonl(check_path, check_rows)
    check_bundle = analyze_manifest(
        [ManifestEntry("python", "ea", "42", "102", check_run)],
        subset_dir=_subset_dir(tmp_path / "check"),
    )
    assert check_bundle.runs == []
    assert any(
        "check_ids must be a unique list of nonblank strings" in error
        for error in check_bundle.extraction_errors
    )


def test_figures_keep_an_explicit_panel_for_a_zero_movable_stratum(tmp_path):
    python_ea = _write_run(tmp_path / "python", optimizer="ea", job_id="101")
    java_random = _write_run(
        tmp_path / "java",
        optimizer="random_search",
        job_id="102",
    )

    config_path = java_random / "run_config.json"
    config = json.loads(config_path.read_text(encoding="utf-8"))
    config["args"]["languages"] = ["java"]
    config_path.write_text(json.dumps(config), encoding="utf-8")
    rule_map_path = java_random.parent / "rule_maps" / "unavailable_fixture_map.json"
    rule_map = json.loads(rule_map_path.read_text(encoding="utf-8"))
    for mapping in rule_map["mappings"]:
        mapping["language"] = "java"
    rule_map_path.write_text(json.dumps(rule_map), encoding="utf-8")

    for result_path in [
        java_random / "intermediate" / "baseline.jsonl",
        java_random / "intermediate" / "rand_iter0001.jsonl",
        java_random / "intermediate" / "rand_iter0002.jsonl",
    ]:
        rows = [json.loads(line) for line in result_path.read_text(encoding="utf-8").splitlines()]
        for row in rows:
            row["language"] = "java"
            row["fitness"]["raw_count"] = 0
            row["fitness"]["weighted_score"] = 0.0
            row["fitness"]["check_ids"] = []
        _write_jsonl(result_path, rows)

    iteration_path = java_random / "iterations.jsonl"
    iterations = [
        json.loads(line) for line in iteration_path.read_text(encoding="utf-8").splitlines()
    ]
    for row in iterations:
        row["f1"] = 0.0
        row["f1_advance"] = False
    _write_jsonl(iteration_path, iterations)
    summary_path = java_random / "hillclimb_summary_x.json"
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    summary["original_fitness"] = 0.0
    summary["best_fitness"] = 0.0
    summary["improvement"] = 0.0
    summary_path.write_text(json.dumps(summary), encoding="utf-8")

    subset = _subset_dir(tmp_path)
    with (subset / "baseline_common_java.csv").open(
        "w",
        newline="",
        encoding="utf-8",
    ) as handle:
        writer = csv.DictWriter(handle, fieldnames=["tid", "qwen_class"])
        writer.writeheader()
        writer.writerow({"tid": "1", "qwen_class": "NEVER"})
        writer.writerow({"tid": "2", "qwen_class": "NEVER"})

    bundle = analyze_manifest(
        [
            ManifestEntry("python", "ea", "42", "101", python_ea),
            ManifestEntry("java", "random_search", "42", "102", java_random),
        ],
        subset_dir=subset,
    )
    assert len(bundle.runs) == 2
    out = tmp_path / "analysis"
    manifest = tmp_path / "manifest.csv"
    manifest.write_text("language,optimizer,seed,job_id\n", encoding="utf-8")
    write_analysis(out, bundle, manifest_path=manifest, repo_root=tmp_path)

    cwe_svg = (out / "cwe_repair.svg").read_text(encoding="utf-8")
    check_svg = (out / "check_flips.svg").read_text(encoding="utf-8")
    assert "java / random_search" in cwe_svg
    assert "No baseline-vulnerable movable observations" in cwe_svg
    assert "java / random_search" in check_svg
    assert "No Semgrep check IDs on eligible movable observations" in check_svg
    assert "(NA)" in check_svg
