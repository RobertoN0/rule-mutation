"""CSV, Markdown, and figure output for the strict schema-4 analysis."""

from __future__ import annotations

import csv
import difflib
import hashlib
import json
import math
import os
from collections import defaultdict
from datetime import date
from pathlib import Path
from statistics import median
from typing import Any, Iterable, Sequence

from .core import (
    PENDING,
    AnalysisBundle,
    ManifestEntry,
    RunAnalysis,
    aggregate_convergence,
    best_chromosome_per_config_rows,
    best_chromosome_rows,
    cost_rows,
    cwe_check_rows,
    language_comparison_rows,
    per_config_rows,
    rq1_rows,
    rq2_family_rows,
    rq2_rows,
    rq3_friedman_rows,
    rq3_rows,
    values_csv,
)

_FIGURE_STEMS = (
    "convergence",
    "per_task_reduction",
    "best_f1_box",
    "cwe_repair",
    "check_flips",
    "mutator_family_delta",
)

_TABLE_HEADERS: dict[str, list[str]] = {
    "run_health.csv": [
        "manifest_model",
        "manifest_language",
        "manifest_optimizer",
        "manifest_seed",
        "job_id",
        "run_dir",
        "status",
        "schema_version",
        "git_sha",
        "slurm_job_id",
        "actual_language",
        "actual_optimizer",
        "actual_seed",
        "actual_model_family",
        "backend",
        "model_id",
        "temperature",
        "rules_map",
        "n_cases",
        "max_iterations",
        "n_proposals",
        "n_evaluated",
        "n_identity",
        "n_semgrep_clean",
        "n_semgrep_error",
        "n_baseline_records",
        "n_archive_snapshots",
        "stop_class",
        "issues",
        "warnings",
    ],
    "per_config_summary.csv": [
        "language",
        "optimizer",
        "subset",
        "subset_status",
        "n_seeds",
        "comparison_budget",
        "horizon_scope",
        "baseline_raw_median",
        "baseline_raw_q1",
        "baseline_raw_q3",
        "baseline_weighted_median",
        "baseline_weighted_q1",
        "baseline_weighted_q3",
        "global_best_f1_final_median",
        "global_best_f1_final_q1",
        "global_best_f1_final_q3",
        "global_best_f1_analysis_horizon_median",
        "global_best_f1_analysis_horizon_q1",
        "global_best_f1_analysis_horizon_q3",
        "repaired_per_seed_median",
        "repaired_per_seed_q1",
        "repaired_per_seed_q3",
        "repair_successes_pooled",
        "movable_observations_pooled",
        "repair_rate_pooled",
        "repair_rate_wilson_low",
        "repair_rate_wilson_high",
        "mean_seed_repair_rate",
        "seed_rate_bootstrap_low",
        "seed_rate_bootstrap_high",
        "rate_inference_note",
    ],
    "rq1_paired.csv": [
        "run",
        "language",
        "optimizer",
        "seed",
        "subset",
        "comparison_budget",
        "horizon_scope",
        "n_tasks",
        "wilcoxon_stat",
        "wilcoxon_p",
        "wilcoxon_p_bh",
        "wilcoxon_note",
        "paired_rank_biserial",
        "mcnemar_stat",
        "mcnemar_p",
        "mcnemar_p_bh",
        "mcnemar_note",
        "matched_flip_effect",
        "repaired_to_zero",
        "test_validity",
        "inference_note",
    ],
    "rq3_ea_vs_random.csv": [
        "language",
        "subset",
        "metric",
        "comparison_budget",
        "horizon_scope",
        "n_ea",
        "n_random",
        "ea_values",
        "random_values",
        "mwu_stat",
        "mwu_p",
        "mwu_p_bh",
        "mwu_note",
        "a12_ea_vs_random",
        "a12_bootstrap_low",
        "a12_bootstrap_high",
        "a12_bootstrap_note",
        "a12_magnitude",
        "matched_seed_n",
        "matched_seed_deltas",
        "paired_sign_stat",
        "paired_sign_p",
        "paired_sign_p_bh",
        "paired_sign_effect",
        "paired_sign_note",
        "design_status",
    ],
    "rq3_friedman_sensitivity.csv": [
        "language",
        "comparison_budget",
        "horizon_scope",
        "matched_seed_n",
        "usable_block_n",
        "usable_seeds",
        "baseline_mismatch_seeds",
        "baseline_weighted_values",
        "ea_best_weighted_values",
        "random_best_weighted_values",
        "baseline_weighted_median",
        "ea_best_weighted_median",
        "random_best_weighted_median",
        "friedman_stat",
        "friedman_p",
        "friedman_p_bh",
        "friedman_note",
        "kendall_w",
        "test_validity",
        "design_status",
        "inference_note",
    ],
    "rq2_per_operator.csv": [
        "language",
        "family",
        "operator",
        "comparison_budget",
        "horizon_scope",
        "n_runs_observed",
        "proposals",
        "identities",
        "evaluated",
        "security_improving",
        "accepted_and_security_improving",
        "proposal_improving_rate",
        "proposal_wilson_low",
        "proposal_wilson_high",
        "evaluated_candidate_improving_rate",
        "evaluated_candidate_wilson_low",
        "evaluated_candidate_wilson_high",
        "mean_seed_improving_rate",
        "seed_rate_bootstrap_low",
        "seed_rate_bootstrap_high",
        "archive_accepted",
        "pooled_mean_delta_f1",
        "mean_seed_delta_f1",
        "mean_seed_delta_f1_bootstrap_low",
        "mean_seed_delta_f1_bootstrap_high",
        "credit_scope",
        "inference_note",
    ],
    "rq2_per_family.csv": [
        "language",
        "family",
        "comparison_budget",
        "horizon_scope",
        "n_runs_observed",
        "proposals",
        "identities",
        "evaluated",
        "security_improving",
        "accepted_and_security_improving",
        "proposal_improving_rate",
        "proposal_wilson_low",
        "proposal_wilson_high",
        "evaluated_candidate_improving_rate",
        "evaluated_candidate_wilson_low",
        "evaluated_candidate_wilson_high",
        "mean_seed_improving_rate",
        "seed_rate_bootstrap_low",
        "seed_rate_bootstrap_high",
        "mean_seed_delta_f1",
        "mean_seed_delta_f1_bootstrap_low",
        "mean_seed_delta_f1_bootstrap_high",
        "inference_note",
    ],
    "best_chromosome.csv": [
        "run",
        "language",
        "optimizer",
        "seed",
        "best_ever_f1",
        "best_ever_iter",
        "best_ever_phase",
        "final_front_source",
        "final_front_cid",
        "final_front_f1",
        "final_front_f2",
        "final_front_f3",
        "n_rules_mutated",
        "mutated_rule_ids",
        "mutators",
        "order_priority",
        "parsimony",
        "note",
    ],
    "best_chromosome_per_config.csv": [
        "language",
        "optimizer",
        "n_runs",
        "representative_run",
        "representative_seed",
        "best_ever_f1_max",
        "final_front_f1",
        "final_front_f2",
        "final_front_f3",
        "n_rules_mutated",
        "mutated_rule_ids",
        "mutators",
        "parsimony",
        "fidelity",
        "order_priority",
        "selection_basis",
    ],
    "cost_hygiene.csv": [
        "run",
        "language",
        "optimizer",
        "seed",
        "n_evaluated",
        "n_proposals",
        "n_identity",
        "candidate_evaluation_horizon",
        "horizon_scope",
        "proposals_at_horizon",
        "identity_proposals_at_horizon",
        "codegen_calls_at_horizon",
        "codegen_input_tokens_at_horizon",
        "codegen_output_tokens_at_horizon",
        "eval_cache_hits_at_horizon",
        "eval_cache_misses_at_horizon",
        "eval_cache_hit_rate_at_horizon",
        "restart_stagnation_at_horizon",
        "restart_exhausted_at_horizon",
        "total_time_seconds",
        "codegen_calls_full_run",
        "codegen_input_tokens_full_run",
        "codegen_output_tokens_full_run",
        "eval_cache_hits",
        "eval_cache_misses",
        "eval_cache_hit_rate",
        "restart_stagnation",
        "restart_exhausted",
        "llm_accounting_scope",
    ],
    "cwe_repair.csv": [
        "language",
        "optimizer",
        "subset_scope",
        "cwe_id",
        "movable",
        "reduced",
        "reduced_rate",
        "repaired",
        "repaired_rate",
    ],
    "check_flips.csv": [
        "language",
        "optimizer",
        "subset_scope",
        "check_id",
        "movable_observations",
        "baseline_present",
        "baseline_absent",
        "removed",
        "removed_rate",
        "added",
        "added_rate",
    ],
    "convergence.csv": [
        "language",
        "optimizer",
        "iteration",
        "n_runs",
        "median",
        "q1",
        "q3",
    ],
    "recurring_rule_edits.csv": [
        "language",
        "rule_id",
        "mutation_paths",
        "text_sha256",
        "n_best_chromosomes",
        "n_distinct_seeds",
        "runs",
        "text_refs",
    ],
    "per_task_outcomes.csv": [
        "run",
        "language",
        "optimizer",
        "seed",
        "comparison_budget",
        "horizon_scope",
        "test_case_id",
        "cwe_id",
        "baseline_class",
        "baseline_raw",
        "best_raw",
        "delta_raw",
        "baseline_weighted",
        "best_weighted",
        "delta_weighted",
        "repaired_to_zero",
        "best_iteration",
        "baseline_check_ids",
        "best_check_ids",
    ],
    "subset_validation.csv": [
        "run",
        "language",
        "optimizer",
        "seed",
        "baseline_class",
        "n_tasks",
        "n_vulnerable_in_final_baseline",
        "observed_vulnerable_rate",
        "sanity_status",
    ],
    "language_comparison.csv": [
        "language",
        "optimizer",
        "subset",
        "n_seeds",
        "comparison_budget",
        "horizon_scope",
        "mean_seed_repair_rate",
        "repair_rate_bootstrap_low",
        "repair_rate_bootstrap_high",
        "mean_normalized_weighted_reduction",
        "normalized_reduction_bootstrap_low",
        "normalized_reduction_bootstrap_high",
        "comparison_scope",
    ],
}


def _write_csv(path: Path, headers: Sequence[str], rows: Iterable[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(headers), extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({header: values_csv(row.get(header, "")) for header in headers})


def _fmt(value: Any, digits: int = 3) -> str:
    if value is None:
        return "n/a"
    if isinstance(value, float):
        if math.isnan(value):
            return "n/a"
        return f"{value:.{digits}f}"
    if isinstance(value, (list, dict)):
        return json.dumps(value, sort_keys=True)
    return str(value)


def _md_table(headers: Sequence[str], rows: Sequence[Sequence[Any]]) -> str:
    def clean(value: Any) -> str:
        return _fmt(value).replace("|", "\\|").replace("\n", " ")

    lines = [
        "| " + " | ".join(clean(header) for header in headers) + " |",
        "|" + "|".join("---" for _ in headers) + "|",
    ]
    lines.extend("| " + " | ".join(clean(value) for value in row) + " |" for row in rows)
    return "\n".join(lines)


def _material_passport(status: str) -> str:
    return (
        "## Material Passport\n\n"
        "- Origin Skill: experiment-agent\n"
        "- Origin Mode: validate\n"
        f"- Origin Date: {date.today().isoformat()}\n"
        f"- Verification Status: {status}\n"
        "- Version Label: schema4_final_analysis_v1\n"
    )


def _placeholder_rows(headers: Sequence[str]) -> list[dict[str, str]]:
    return [{header: PENDING for header in headers}]


def _seed_sort_key(value: str) -> tuple[int, int | str]:
    seed = str(value)
    return (0, int(seed)) if seed.isdigit() else (1, seed)


def _setup_matplotlib(out: Path):
    cache = out / ".mplconfig"
    cache.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("MPLCONFIGDIR", str(cache))
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    return plt


def _save_figure(fig, out: Path, stem: str) -> None:
    fig.savefig(out / f"{stem}.png", dpi=180, bbox_inches="tight")
    fig.savefig(out / f"{stem}.svg", bbox_inches="tight")


def _placeholder_figures(out: Path) -> None:
    plt = _setup_matplotlib(out)
    for stem in _FIGURE_STEMS:
        fig, axis = plt.subplots(figsize=(8, 4.5))
        axis.axis("off")
        axis.text(
            0.5,
            0.55,
            PENDING,
            ha="center",
            va="center",
            fontsize=15,
            weight="bold",
        )
        axis.text(
            0.5,
            0.42,
            "Requires the user-confirmed schema-4 final manifest.",
            ha="center",
            va="center",
            fontsize=10,
        )
        _save_figure(fig, out, stem)
        plt.close(fig)


def write_pending(
    out: Path,
    *,
    reason: str,
    expected_entries: Sequence[ManifestEntry],
) -> None:
    """Write the handoff's required pending tables/figures without fake values."""
    out.mkdir(parents=True, exist_ok=True)
    for filename, headers in _TABLE_HEADERS.items():
        _write_csv(out / filename, headers, _placeholder_rows(headers))
    _write_csv(
        out / "analysis_manifest_template.csv",
        ["model", "language", "optimizer", "seed", "job_id", "run_dir", "log_path"],
        [
            {
                "model": entry.model,
                "language": entry.language,
                "optimizer": entry.optimizer,
                "seed": entry.seed,
                "job_id": entry.job_id,
                "run_dir": str(entry.run_dir or ""),
                "log_path": str(entry.log_path or ""),
            }
            for entry in expected_entries
        ],
    )
    _placeholder_figures(out)
    report = (
        "# Final schema-4 repair analysis\n\n"
        f"{_material_passport('UNVERIFIED')}\n"
        "## Status\n\n"
        f"**{PENDING}**\n\n"
        f"{reason}\n\n"
        "No diagnostic, schema-2, or schema-3 outcome value was substituted. Every "
        "table and figure is a structural placeholder generated by the real extraction "
        "entry point. The manifest rows encode the confirmed expected experiment "
        f"matrix ({len(expected_entries)} run cells), not observed results.\n\n"
        "## Expected run layout\n\n"
        "```text\n"
        "experiments/final/\n"
        "├── qwen/{python,java}/{ea,random_search}/seed1 ... seed10\n"
        "└── llama/{python,java}/{ea,random_search}/seed1 ... seed10\n"
        "```\n\n"
        "Each seed container may be the run tree or contain exactly one generated "
        "`job<ID>_*` child. The final full-population jobs must use the verified "
        "185-task Python / 114-task Java vulnerable maps rather than sampling those "
        "counts from the larger default combined map.\n\n"
        "## Prepared deliverables\n\n"
        "- Run-health, supplied-grid rectangularity, and explicit expected-seed table.\n"
        "- Per-configuration RQ1 summary, paired task statistics, RQ2 operator table, "
        "and RQ3 EA-versus-random comparison.\n"
        "- Per-task raw/weighted reductions and final-baseline subset validation.\n"
        "- Best-surviving-chromosome and recurring-edit tables.\n"
        "- Cost/cache/restart hygiene tables.\n"
        "- [Methods and citation boundaries](METHODS.md).\n"
        "- PNG and SVG placeholders for all required figures.\n\n"
        "## Required next input\n\n"
        "Keep one row per final `(model, language, optimizer, seed)` run in "
        "`analysis_manifest_template.csv`. Each prepared `run_dir` may either be the "
        "run tree itself or contain exactly one generated `job<ID>_*` run tree. "
        "Alternatively, replace `run_dir` with `job_id`; include `log_path` when the "
        "local run tree does not contain `run.log`.\n"
    )
    (out / "REPORT.md").write_text(report, encoding="utf-8")
    (out / "run_health.md").write_text(
        f"# Run health / supplied-grid check\n\n{PENDING}\n\nReason: {reason}\n\n"
        "The expected cells are predeclared in `analysis_manifest_template.csv`; "
        "their artifacts and submitted job IDs remain to be verified.\n",
        encoding="utf-8",
    )
    (out / "rq_answers.md").write_text(
        f"# RQ1 / RQ2 / RQ3\n\n- RQ1: {PENDING}\n- RQ2: {PENDING}\n- RQ3: {PENDING}\n",
        encoding="utf-8",
    )
    (out / "tables.md").write_text(
        "# Final analysis tables — digest\n\n"
        f"{PENDING}\n\n"
        "The CSV files contain the complete intended column schemas.\n",
        encoding="utf-8",
    )
    (out / "best_chromosomes.md").write_text(
        f"# Best chromosomes and recurring edits\n\n{PENDING}\n",
        encoding="utf-8",
    )
    (out / "open_questions.md").write_text(
        "# Open questions / data gaps\n\n"
        "1. Do all 80 submitted jobs populate the prepared model × language × "
        "optimizer × seed cells exactly once, with no retries or duplicate job trees?\n"
        "2. Are EA and random seeds inferentially paired (common random numbers) or "
        "to be treated as independent groups?\n"
        "3. Are any random-builder or f1-only archive ablations part of the final "
        "manifest, or are they excluded from RQ1–RQ3?\n"
        "4. Where are the SLURM logs for runs that stop below the configured evaluation "
        "cap?\n"
        "5. Has the Arcuri–Briand source for the exact fairness claim been primary-source "
        "verified and added to the bibliography?\n",
        encoding="utf-8",
    )
    _write_validation(out, pending=True, pending_reason=reason)
    _write_methods(out, pending=True)


def _health_rows(bundle: AnalysisBundle) -> list[dict[str, Any]]:
    rows = []
    for health in bundle.healths:
        rows.append(
            {
                "manifest_model": health.entry.model,
                "manifest_language": health.entry.language,
                "manifest_optimizer": health.entry.optimizer,
                "manifest_seed": health.entry.seed,
                "job_id": health.entry.job_id,
                "run_dir": str(health.path or ""),
                "status": health.status,
                "schema_version": health.schema_version,
                "git_sha": health.git_sha,
                "slurm_job_id": health.slurm_job_id,
                "actual_language": health.actual_language,
                "actual_optimizer": health.actual_optimizer,
                "actual_seed": health.actual_seed,
                "actual_model_family": health.actual_model_family,
                "backend": health.backend,
                "model_id": health.model,
                "temperature": health.temperature,
                "rules_map": health.rules_map,
                "n_cases": health.n_cases,
                "max_iterations": health.max_iterations,
                "n_proposals": health.n_proposals,
                "n_evaluated": health.n_evaluated,
                "n_identity": health.n_identity,
                "n_semgrep_clean": health.n_semgrep_clean,
                "n_semgrep_error": health.n_semgrep_error,
                "n_baseline_records": health.n_baseline_records,
                "n_archive_snapshots": health.n_archive_snapshots,
                "stop_class": health.stop_class,
                "issues": health.issues,
                "warnings": health.warnings,
            }
        )
    return rows


def _manifest_grid_rows(bundle: AnalysisBundle) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str, str], list[str]] = defaultdict(list)
    for health in bundle.healths:
        grouped[(health.entry.model, health.entry.language, health.entry.optimizer)].append(
            health.entry.seed
        )
    rows = []
    models = sorted({health.entry.model for health in bundle.healths})
    for model in models:
        for language in bundle.expected_languages:
            for optimizer in bundle.expected_optimizers:
                seeds = grouped.get((model, language, optimizer), [])
                seed_set = set(seeds)
                expected = set(bundle.expected_seeds)
                if not seeds:
                    status = "OMITTED"
                elif len(seed_set) != len(seeds):
                    status = "DUPLICATE_CELL"
                elif expected and seed_set == expected:
                    status = "EXPECTED_COMPLETE"
                elif expected:
                    status = "EXPECTED_MISMATCH"
                else:
                    status = "PRESENT"
                rows.append(
                    {
                        "model": model,
                        "language": language,
                        "optimizer": optimizer,
                        "manifest_rows": len(seeds),
                        "distinct_seeds": len(set(seeds)),
                        "seeds": sorted(set(seeds), key=_seed_sort_key),
                        "status": status,
                    }
                )
    return rows


def _recurring_edits(runs: Sequence[RunAnalysis]) -> list[dict[str, Any]]:
    groups: dict[tuple[str, str, str], dict[str, Any]] = {}
    for run in runs:
        front = run.final_front_best
        genes = front.get("genes") if isinstance(front.get("genes"), dict) else {}
        for rule_id, gene in genes.items():
            if not isinstance(gene, dict):
                continue
            mutation_path = json.dumps(gene.get("mutation_path") or [])
            text_ref = gene.get("text_ref")
            if not text_ref or not run.health.path:
                continue
            text_path = run.health.path / str(text_ref)
            if not text_path.is_file():
                continue
            text_sha256 = hashlib.sha256(text_path.read_bytes()).hexdigest()
            # Recurrence is byte-identical final rule text, independent of the
            # stochastic mutation lineage that happened to reach it.
            key = (run.language, str(rule_id), text_sha256)
            group = groups.setdefault(
                key,
                {
                    "language": run.language,
                    "rule_id": str(rule_id),
                    "mutation_paths": set(),
                    "text_sha256": text_sha256,
                    "runs": [],
                    "seeds": set(),
                    "text_refs": [],
                },
            )
            group["mutation_paths"].add(mutation_path)
            group["runs"].append(run.health.label)
            group["seeds"].add(run.seed)
            group["text_refs"].append(str(text_path))
    rows = []
    for group in groups.values():
        rows.append(
            {
                "language": group["language"],
                "rule_id": group["rule_id"],
                "mutation_paths": sorted(group["mutation_paths"]),
                "text_sha256": group["text_sha256"],
                "n_best_chromosomes": len(group["runs"]),
                "n_distinct_seeds": len(group["seeds"]),
                "runs": sorted(group["runs"]),
                "text_refs": sorted(group["text_refs"]),
            }
        )
    return sorted(
        rows,
        key=lambda row: (
            row["language"],
            -row["n_distinct_seeds"],
            row["rule_id"],
            row["text_sha256"],
        ),
    )


def _per_task_rows(runs: Sequence[RunAnalysis]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for run in runs:
        run_name = run.health.label
        for outcome in run.budget_outcomes:
            rows.append(
                {
                    "run": run_name,
                    "language": run.language,
                    "optimizer": run.optimizer,
                    "seed": run.seed,
                    "comparison_budget": run.comparison_budget,
                    "horizon_scope": run.horizon_scope,
                    "test_case_id": outcome.test_case_id,
                    "cwe_id": outcome.cwe_id,
                    "baseline_class": outcome.baseline_class,
                    "baseline_raw": outcome.baseline.raw_count,
                    "best_raw": outcome.best.raw_count,
                    "delta_raw": outcome.delta_raw,
                    "baseline_weighted": outcome.baseline.weighted_score,
                    "best_weighted": outcome.best.weighted_score,
                    "delta_weighted": outcome.delta_weighted,
                    "repaired_to_zero": outcome.repaired_to_zero,
                    "best_iteration": outcome.best.iteration,
                    "baseline_check_ids": sorted(outcome.baseline.check_ids),
                    "best_check_ids": sorted(outcome.best.check_ids),
                }
            )
    return rows


def _subset_validation_rows(runs: Sequence[RunAnalysis]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for run in runs:
        grouped: dict[str, list[Any]] = defaultdict(list)
        for outcome in run.final_outcomes:
            grouped[outcome.baseline_class or "UNKNOWN"].append(outcome)
        for baseline_class, outcomes in sorted(grouped.items()):
            vulnerable = sum(outcome.baseline.vulnerable for outcome in outcomes)
            if baseline_class == "ALWAYS_SAFE":
                status = "PASS" if vulnerable == 0 else "FAIL: never-floor violation"
            elif baseline_class == "ALWAYS_VULNERABLE":
                status = (
                    "PASS"
                    if vulnerable == len(outcomes)
                    else "CAUTION: persistent class not fully vulnerable in final baseline"
                )
            elif baseline_class == "UNKNOWN":
                status = "CAUTION: subset class unavailable"
            else:
                status = "OBSERVED"
            rows.append(
                {
                    "run": run.health.label,
                    "language": run.language,
                    "optimizer": run.optimizer,
                    "seed": run.seed,
                    "baseline_class": baseline_class,
                    "n_tasks": len(outcomes),
                    "n_vulnerable_in_final_baseline": vulnerable,
                    "observed_vulnerable_rate": vulnerable / len(outcomes),
                    "sanity_status": status,
                }
            )
    return rows


def _write_best_chromosome_digest(
    out: Path, runs: Sequence[RunAnalysis], *, repo_root: Path
) -> None:
    recurring = [row for row in _recurring_edits(runs) if row["n_distinct_seeds"] >= 2]
    config_representatives = best_chromosome_per_config_rows(runs)
    lines = [
        "# Best chromosomes and recurring edits\n\n",
        "The run headline (`best ever`) is derived from all evaluated iterations. "
        "The qualitative chromosome below is the best member that survives in the "
        "final archive snapshot; a restart can make these differ.\n\n",
        "## Per-configuration representative\n\n",
        _md_table(
            [
                "language",
                "optimizer",
                "healthy runs",
                "representative run/seed",
                "best-ever f1 max",
                "surviving f1/f2/f3",
                "rules",
                "mutators",
                "selection basis",
            ],
            [
                [
                    row["language"],
                    row["optimizer"],
                    row["n_runs"],
                    f"{_fmt(row['representative_run'])}/{_fmt(row['representative_seed'])}",
                    row["best_ever_f1_max"],
                    (
                        f"{_fmt(row['final_front_f1'])}/"
                        f"{_fmt(row['final_front_f2'])}/"
                        f"{_fmt(row['final_front_f3'])}"
                    ),
                    row["mutated_rule_ids"],
                    row["mutators"],
                    row["selection_basis"],
                ]
                for row in config_representatives
            ],
        ),
        "\n\nThe complete per-run table remains in `best_chromosome.csv`; "
        "the configuration representatives are in "
        "`best_chromosome_per_config.csv`.\n\n",
        "## Recurring exact edits\n\n",
        (
            _md_table(
                [
                    "language",
                    "rule",
                    "observed mutation paths",
                    "exact text hash",
                    "distinct seeds",
                ],
                [
                    [
                        row["language"],
                        row["rule_id"],
                        row["mutation_paths"],
                        row["text_sha256"][:12],
                        row["n_distinct_seeds"],
                    ]
                    for row in recurring
                ],
            )
            if recurring
            else "No byte-identical mutated rule text recurs across two healthy seeds."
        ),
        "\n",
    ]
    rules_root = repo_root / "project-codeguard" / "skills" / "software-security" / "rules"
    for run in runs:
        front = run.final_front_best
        run_name = run.health.label
        lines.append(f"\n## {run_name}\n\n")
        if run.optimizer != "ea":
            lines.append(
                "Not applicable: random search has no persistent Pareto archive or "
                "final-front chromosome.\n"
            )
            continue
        if not front or front.get("source") == "origin":
            lines.append("No mutated repair survives the final front.\n")
            continue
        lines.append(
            f"- Final-front f1/f2/f3: {_fmt(front.get('f1'))} / "
            f"{_fmt(front.get('f2'))} / {_fmt(front.get('f3'))}\n"
            f"- Mutated rules: {', '.join(front.get('mutated_rule_ids') or [])}\n"
            f"- Order priorities: `{json.dumps(front.get('order_priority') or {}, sort_keys=True)}`\n"
        )
        genes = front.get("genes") if isinstance(front.get("genes"), dict) else {}
        for rule_id, gene in genes.items():
            if not isinstance(gene, dict):
                continue
            text_ref = gene.get("text_ref")
            lines.append(
                f"\n### {rule_id}\n\n"
                f"- Mutation path: `{json.dumps(gene.get('mutation_path') or [])}`\n"
                f"- Text reference: `{text_ref}`\n"
            )
            if not run.health.path or not text_ref:
                continue
            mutated = run.health.path / str(text_ref)
            original = rules_root / f"{rule_id}.md"
            if not original.is_file() or not mutated.is_file():
                lines.append("- Diff unavailable: original or referenced text is missing.\n")
                continue
            diff = list(
                difflib.unified_diff(
                    original.read_text(encoding="utf-8").splitlines(),
                    mutated.read_text(encoding="utf-8").splitlines(),
                    fromfile=f"original/{rule_id}.md",
                    tofile=f"mutated/{rule_id}.md",
                    n=2,
                    lineterm="",
                )
            )
            if len(diff) > 80:
                diff = diff[:80] + ["... [diff truncated at 80 lines]"]
            lines.append("\n```diff\n" + "\n".join(diff) + "\n```\n")
    (out / "best_chromosomes.md").write_text("".join(lines), encoding="utf-8")


def _write_figures(out: Path, bundle: AnalysisBundle) -> None:
    plt = _setup_matplotlib(out)

    convergence = aggregate_convergence(bundle.runs)
    fig, axes = plt.subplots(
        1,
        max(1, len(bundle.analysis_budgets)),
        figsize=(7 * max(1, len(bundle.analysis_budgets)), 4.5),
        squeeze=False,
    )
    for axis, language in zip(axes[0], sorted(bundle.analysis_budgets)):
        for optimizer, color in (("ea", "#31688e"), ("random_search", "#d1495b")):
            rows = [
                row
                for row in convergence
                if row["language"] == language
                and row["optimizer"] == optimizer
                and row["iteration"] <= bundle.analysis_budgets[language]
            ]
            if not rows:
                continue
            x = [row["iteration"] for row in rows]
            axis.plot(x, [row["median"] for row in rows], label=optimizer, color=color)
            axis.fill_between(
                x,
                [row["q1"] for row in rows],
                [row["q3"] for row in rows],
                alpha=0.2,
                color=color,
            )
        scope = (
            "common EA/random budget"
            if language in bundle.common_budgets
            else "available-run analysis horizon"
        )
        axis.set_title(f"{language} ({scope} {bundle.analysis_budgets[language]})")
        axis.set_xlabel("candidate evaluations")
        axis.set_ylabel("best f1 so far")
        axis.grid(alpha=0.25)
        axis.legend()
    _save_figure(fig, out, "convergence")
    plt.close(fig)

    groups: dict[str, list[float]] = defaultdict(list)
    for run in bundle.runs:
        key = f"{run.language}\n{run.optimizer}"
        movable_deltas = [
            outcome.delta_weighted for outcome in run.budget_outcomes if outcome.movable
        ]
        if movable_deltas:
            groups[key].extend(movable_deltas)
    fig, axis = plt.subplots(figsize=(9, 5))
    if groups:
        labels_order = sorted(groups)
        axis.violinplot([groups[label] for label in labels_order], showmedians=True)
        axis.set_xticks(range(1, len(labels_order) + 1), labels_order)
    axis.set_ylabel("baseline − best weighted findings")
    axis.set_title("Per-task reduction at each labelled analysis horizon")
    axis.grid(axis="y", alpha=0.25)
    _save_figure(fig, out, "per_task_reduction")
    plt.close(fig)

    f1_groups: dict[str, list[float]] = defaultdict(list)
    for run in bundle.runs:
        f1_groups[f"{run.language}\n{run.optimizer}"].append(run.best_f1_budget)
    fig, axis = plt.subplots(figsize=(8, 5))
    if f1_groups:
        labels_order = sorted(f1_groups)
        axis.boxplot(
            [f1_groups[label] for label in labels_order],
            tick_labels=labels_order,
            showmeans=True,
        )
    axis.set_ylabel("best f1 at labelled analysis horizon")
    axis.set_title("EA versus random search by language")
    axis.grid(axis="y", alpha=0.25)
    _save_figure(fig, out, "best_f1_box")
    plt.close(fig)

    cwe_rows, check_rows = cwe_check_rows(bundle.runs)
    figure_strata = sorted({(run.language, run.optimizer) for run in bundle.runs})
    cwe_strata = figure_strata
    if cwe_strata:
        fig, axes = plt.subplots(
            len(cwe_strata),
            1,
            figsize=(11, max(4.5, 4.2 * len(cwe_strata))),
            squeeze=False,
        )
        for axis, (language, optimizer) in zip(axes.flat, cwe_strata):
            selected = sorted(
                (
                    row
                    for row in cwe_rows
                    if row["language"] == language and row["optimizer"] == optimizer
                ),
                key=lambda row: (
                    float(row["repaired_rate"]),
                    int(row["repaired"]),
                    int(row["movable"]),
                ),
                reverse=True,
            )[:15]
            selected.reverse()
            if selected:
                axis.barh(
                    [str(row["cwe_id"]) for row in selected],
                    [float(row["repaired_rate"]) for row in selected],
                    color="#3b8b6e",
                )
                for index, row in enumerate(selected):
                    value = float(row["repaired_rate"])
                    axis.text(
                        min(value + 0.015, 0.96),
                        index,
                        f"{row['repaired']}/{row['movable']}",
                        va="center",
                        fontsize=8,
                    )
            else:
                axis.text(
                    0.5,
                    0.5,
                    "No baseline-vulnerable movable observations",
                    ha="center",
                    va="center",
                    transform=axis.transAxes,
                )
                axis.set_yticks([])
            axis.set_xlim(0, 1)
            axis.set_xlabel("repair rate (repaired / movable task-run observations)")
            axis.set_title(f"{language} / {optimizer} — baseline-vulnerable movable subset")
            axis.grid(axis="x", alpha=0.2)
        fig.suptitle("Repair reach by CWE at the labelled analysis horizon")
        fig.tight_layout(rect=(0, 0, 1, 0.96), h_pad=3.5)
    else:
        fig, axis = plt.subplots(figsize=(9, 5))
        axis.text(0.5, 0.5, "No baseline-vulnerable movable observations", ha="center")
        axis.set_axis_off()
        axis.set_title("Repair reach by CWE")
    _save_figure(fig, out, "cwe_repair")
    plt.close(fig)

    check_strata = figure_strata
    if check_strata:
        fig, axes = plt.subplots(
            len(check_strata),
            1,
            figsize=(13, max(5, 4.5 * len(check_strata))),
            squeeze=False,
        )
        for axis, (language, optimizer) in zip(axes.flat, check_strata):
            selected = sorted(
                (
                    row
                    for row in check_rows
                    if row["language"] == language and row["optimizer"] == optimizer
                ),
                key=lambda row: int(row["removed"]) + int(row["added"]),
                reverse=True,
            )[:15]
            positions = list(range(len(selected)))

            def plottable_rate(row: dict[str, Any], key: str) -> float:
                value = row.get(key)
                return (
                    float(value)
                    if isinstance(value, (int, float)) and math.isfinite(float(value))
                    else math.nan
                )

            if selected:
                axis.barh(
                    positions,
                    [plottable_rate(row, "removed_rate") for row in selected],
                    label="removed / baseline-present",
                    color="#3b8b6e",
                )
                axis.barh(
                    positions,
                    [-plottable_rate(row, "added_rate") for row in selected],
                    label="added / baseline-absent",
                    color="#d1495b",
                )
                labels = [
                    (
                        f"{row['check_id']}\n"
                        f"R {row['removed']}/{row['baseline_present']}"
                        f"{' (NA)' if row['baseline_present'] == 0 else ''}; "
                        f"A {row['added']}/{row['baseline_absent']}"
                        f"{' (NA)' if row['baseline_absent'] == 0 else ''}"
                    )
                    for row in selected
                ]
                axis.set_yticks(positions, labels, fontsize=8)
                axis.legend()
            else:
                axis.text(
                    0.5,
                    0.5,
                    "No Semgrep check IDs on eligible movable observations",
                    ha="center",
                    va="center",
                    transform=axis.transAxes,
                )
                axis.set_yticks([])
            axis.axvline(0, color="black", linewidth=0.8)
            axis.set_xlim(-1, 1)
            axis.set_xlabel("check-specific flip rate (removed positive; added negative)")
            axis.set_title(f"{language} / {optimizer} — baseline-vulnerable movable subset")
            axis.grid(axis="x", alpha=0.2)
        fig.suptitle("Semgrep check flips at each task's best observed candidate")
        fig.tight_layout(rect=(0, 0, 1, 0.96), h_pad=3.5)
    else:
        fig, axis = plt.subplots(figsize=(10, 5))
        axis.text(0.5, 0.5, "No check flips on movable observations", ha="center")
        axis.set_axis_off()
        axis.set_title("Semgrep check flips")
    _save_figure(fig, out, "check_flips")
    plt.close(fig)

    family_rows = rq2_family_rows(bundle.runs)
    family_values: dict[str, float] = {}
    for row in family_rows:
        value = row.get("mean_seed_delta_f1")
        if isinstance(value, (int, float)) and math.isfinite(float(value)):
            family_values[f"{row['language']}\n{row['family']}"] = float(value)
    fig, axis = plt.subplots(figsize=(8, 5))
    names = sorted(family_values)
    axis.bar(
        names,
        [family_values[name] for name in names],
        color="#6b6ecf",
    )
    axis.axhline(0, color="black", linewidth=0.8)
    axis.set_ylabel("mean local Δf1 (descriptive)")
    axis.set_title("Local EA move delta by mutator family")
    _save_figure(fig, out, "mutator_family_delta")
    plt.close(fig)


def _write_validation(
    out: Path,
    *,
    pending: bool,
    bundle: AnalysisBundle | None = None,
    pending_reason: str = "",
) -> None:
    manifest_warnings = [] if bundle is None else bundle.manifest_warnings
    expected_grid_warnings = [] if bundle is None else bundle.expected_grid_warnings
    analysis_warnings = [] if bundle is None else bundle.analysis_warnings
    status = (
        "UNVERIFIED"
        if pending
        else ("ANALYZED_WITH_CAUTION" if bundle and bundle.has_cautions else "ANALYZED")
    )
    if pending:
        coverage = "0/11 data-dependent checks assessed; 11/11 protocols staged."
        detail = (
            f"{PENDING} The rows below are a protocol, not findings about a "
            "user-confirmed eligible final dataset. "
            + (
                f"Reason: {pending_reason}"
                if pending_reason
                else "No eligible final dataset is currently available."
            )
        )
        fallacy_rows = [
            [name, "NOT ASSESSED — PROTOCOL STAGED", application]
            for name, application in [
                (
                    "Simpson's paradox",
                    "Compare pooled patterns with language/optimizer/subset strata.",
                ),
                (
                    "Ecological fallacy",
                    "Keep run-, seed-, and task-level claims at their measured level.",
                ),
                (
                    "Berkson's paradox",
                    "Account for selection into the curated vulnerable task map.",
                ),
                (
                    "Collider bias",
                    "Check that no post-treatment variable enters adjustment.",
                ),
                (
                    "Base-rate neglect",
                    "Report baseline vulnerability and movable denominators.",
                ),
                (
                    "Regression to the mean",
                    "Treat baseline-vulnerable task selection as a limitation.",
                ),
                (
                    "Survivorship bias",
                    "Retain every expected missing/unhealthy run in run_health.csv.",
                ),
                (
                    "Look-elsewhere effect",
                    "Count the test family and apply the planned BH correction.",
                ),
                (
                    "Garden of forking paths",
                    "Record post-hoc choices and avoid confirmatory wording.",
                ),
                (
                    "Correlation != causation",
                    "Bound claims to the controlled benchmark search.",
                ),
                (
                    "Reverse causality",
                    "Verify temporal ordering and mark non-applicability if warranted.",
                ),
            ]
        ]
    else:
        assert bundle is not None
        missing_n = sum(health.status == "missing" for health in bundle.healths)
        unhealthy_n = sum(health.status == "unhealthy" for health in bundle.healths)
        qualified_n = sum(
            any(warning.startswith("QUALIFIED OVERRIDE:") for warning in health.warnings)
            for health in bundle.healths
        )
        test_n = (
            len(rq1_rows(bundle.runs))
            + len(rq3_rows(bundle.runs))
            + len(rq3_friedman_rows(bundle.runs))
        )
        coverage = "11/11 assessed for applicability; CAUTION is not a clearance."
        detail = (
            f"Analyzed {len(bundle.runs)} eligible runs"
            + (
                f", including {qualified_n} admitted under an explicit missing-artifact override"
                if qualified_n
                else ""
            )
            + f"; retained {missing_n} missing "
            f"and {unhealthy_n} unhealthy supplied runs in the health table. "
            f"The emitted statistical family contains {test_n} result rows. "
            + (
                "The supplied grid is nonrectangular, so all aggregates are conditional "
                "on the available cells."
                if manifest_warnings
                else (
                    "The supplied grid is rectangular but does not match the explicitly "
                    "declared expected seed matrix."
                    if expected_grid_warnings
                    else (
                        "The supplied grid matches the explicitly declared language × "
                        "optimizer × seed matrix."
                        if bundle.expected_grid_complete
                        else (
                            "The supplied grid contains all supported language × optimizer "
                            "cells with one shared supplied seed set. No independent expected "
                            "seed contract was provided."
                        )
                    )
                )
            )
            + f" The health audit records {len(analysis_warnings)} distinct warning(s)."
        )
        survivorship_status = (
            "CAUTION — warnings or exclusions present"
            if analysis_warnings or missing_n or unhealthy_n
            else "CHECKED — supplied grid rectangular and no run exclusions"
        )
        fallacy_rows = [
            [
                "Simpson's paradox",
                "CHECKED WITHIN SUPPLIED SCOPE",
                "Only one model/language stratum is supplied; optimizer and baseline-subset rows remain separate.",
            ],
            [
                "Ecological fallacy",
                "CAUTION",
                "Run-level effects are not promoted to individual-task effects.",
            ],
            [
                "Berkson's paradox",
                "CAUTION",
                "The vulnerable maps define a selected task population.",
            ],
            [
                "Collider bias",
                "CAUTION",
                "No covariate adjustment is performed, but accepted/best/front selection makes operator associations selection-conditioned.",
            ],
            [
                "Base-rate neglect",
                "CHECKED",
                "Movable denominators and final baseline vulnerability are explicit.",
            ],
            [
                "Regression to the mean",
                "CAUTION",
                "The headline population is selected for baseline vulnerability.",
            ],
            [
                "Survivorship bias",
                survivorship_status,
                (
                    f"run_health.csv exposes {missing_n} missing and {unhealthy_n} "
                    f"unhealthy runs; analysis warnings: {len(analysis_warnings)}."
                ),
            ],
            [
                "Look-elsewhere effect",
                "CAUTION",
                f"BH-adjusted values are emitted; {test_n} result rows need scoped interpretation.",
            ],
            [
                "Garden of forking paths",
                "CAUTION",
                "The analysis was not preregistered and Stage-1 selection is post hoc.",
            ],
            [
                "Correlation != causation",
                "CAUTION",
                "Optimizer assignment supports only a narrow benchmark comparison; operator associations and Semgrep-proxy outcomes are not promoted to causal claims.",
            ],
            [
                "Reverse causality",
                "N/A",
                "Optimizer assignment precedes outcomes; mutation lineage alone does not identify causal operator effects.",
            ],
        ]
    text = (
        "# Validation report\n\n"
        f"{_material_passport(status)}\n"
        "## Statistical scope\n\n"
        f"{detail}\n\n"
        "Stage-1 baseline-versus-best tests are descriptive over benchmark tasks: the "
        "same search output is used to select the best candidate and estimate repair. "
        "Generalization requires fresh Stage-2 replicates.\n\n"
        "## Fallacy scan\n\n"
        f"**Coverage: {coverage}**\n\n"
        + _md_table(
            ["Fallacy", "Status", "Application here"],
            fallacy_rows,
        )
        + "\n\n"
        "## Manifest integrity and health warnings\n\n"
        + (
            "- " + "\n- ".join(analysis_warnings) + "\n\n"
            if analysis_warnings
            else (
                f"- {PENDING} Supplied-grid rectangularity cannot be assessed until final "
                "runs are supplied.\n\n"
                if pending
                else (
                    "- The supplied grid matches the explicit expected-seed contract.\n\n"
                    if bundle and bundle.expected_grid_complete
                    else (
                        "- The supplied grid is rectangular, but no independent "
                        "expected-seed contract was supplied.\n\n"
                    )
                )
            )
        )
        + "## Reproducibility\n\n"
        "- Method: deterministic offline re-run of the analysis code only.\n"
        f"- Verdict: {'CANNOT_VERIFY until final runs arrive' if pending else status + ', not experiment-reproduced'}.\n"
    )
    (out / "VALIDATION.md").write_text(text, encoding="utf-8")


def _write_methods(out: Path, *, pending: bool) -> None:
    status = "PROTOCOL_STAGED" if pending else "APPLIED_TO_SUPPLIED_MANIFEST"
    text = (
        "# Methods and citation boundaries\n\n"
        f"{_material_passport(status)}\n"
        "## Analysis population\n\n"
        "Only runs named by the user-confirmed manifest are eligible. Every expected "
        "row is health-checked against schema 4, its manifest identity, experiment "
        "configuration, prompt/task map, iteration accounting, Semgrep payloads, and "
        "EA archive snapshots. Missing or unhealthy rows remain visible in "
        "`run_health.csv` but are excluded from aggregates. A nonrectangular supplied "
        "grid is reported as a caution. The CLI separately checks every supplied row "
        "against the explicit `--expected-seeds` contract (1–10 by default), so a seed "
        "omitted from all four configurations is still detected. Job IDs must still "
        "be reconciled with the submitted SLURM batch.\n\n"
        "## Comparison horizon and cost\n\n"
        "The primary EA-versus-random unit is the shortest common number of evaluated "
        "candidates within each language. Identity proposals do not consume this "
        "budget. When only one optimizer arm is supplied, RQ1 may be described at the "
        "minimum available-run horizon, but no cross-arm RQ3 result is emitted.\n\n"
        "Equal candidate evaluations do not establish equal compute. "
        "`cost_hygiene.csv` labels the persisted call/token counters as code-generation "
        "counters: they cover model-under-test generations issued by the experiment "
        "engine, including baseline and cache-miss candidate generations, but exclude "
        "direct model calls made inside LLM-based mutators. Schema 4 does not persist "
        "those mutator token totals. `total_time_seconds` is inclusive observed wall "
        "time, but it also reflects Semgrep, caching, validation, model loading, and "
        "cluster conditions.\n\n"
        "## Research-question estimands\n\n"
        "- RQ1 reports seed-level repair reach and per-task baseline-to-best changes. "
        "Because the best candidate is selected from the same Stage-1 search output, "
        "the paired tests are `DESCRIPTIVE_ONLY_POST_SELECTION`; fresh pre-specified "
        "Stage-2 runs are needed for generalization.\n"
        "- RQ2 gives last-move local attribution for EA-phase proposals. Run-balanced "
        "family and operator summaries are exploratory, not isolated causal effects.\n"
        "- RQ3 emits the handoff-requested independent-sample Mann–Whitney U and "
        "Vargha–Delaney A12, plus a matched-seed sign-test sensitivity. Reusing seeds "
        "and common opening samples creates a paired-design rationale, so the choice "
        "between independent and paired primary inference remains unresolved. A "
        "three-condition Friedman result is sensitivity-only and requires complete "
        "matched blocks.\n"
        "- Benjamini–Hochberg adjustments are reported within emitted test families. "
        "Seed-level bootstrap intervals are primary for rates; pooled Wilson intervals "
        "are descriptive because task/proposal observations are nested.\n"
        "- CWE and check-flip figures use only baseline-vulnerable movable observations, "
        "facet language × optimizer strata, and display rates with explicit task-run "
        "denominators; they do not pool counts across strata.\n\n"
        "## Literature support and limits\n\n"
        "- [Arcuri and Briand, ICSE 2011]"
        "(https://web-backend.simula.no/sites/default/files/publications/"
        "Simula.approve.64.pdf) supports repeated independent runs, comparison with "
        "random search, and effect-size reporting in randomized software-engineering "
        "experiments. The stronger local wording that it specifically prescribes an "
        "identical candidate-evaluation budget has not been verified from that source "
        "and is not attributed to it here.\n"
        "- [ARIEL]"
        "(https://repository.tudelft.nl/record/uuid%3A68d02e6c-1d56-416f-8f5c-"
        "3bda0453c698) is a structural precedent for a repair-oriented (1+1) EA with "
        "a many-objective archive under expensive evaluation; this thesis is an "
        "adaptation, not a direct replication.\n"
        "- [Chen and Li]"
        "(https://arxiv.org/abs/2202.03728) motivates Pareto search over fragile "
        "weighted sums while also supplying the important tight-budget efficiency "
        "caveat.\n"
        "- [Miettinen]"
        "(https://link.springer.com/book/10.1007/978-1-4615-5563-6) supplies the "
        "formal Pareto-optimality basis; the implementation-specific archive policy "
        "still requires direct code evidence.\n"
        "- [Vargha and Delaney]"
        "(https://journals.sagepub.com/doi/10.3102/10769986025002101) supplies the "
        "A-type stochastic-superiority effect size used beside rank tests.\n\n"
        f"## Current execution status\n\n{'[PENDING: final runs]' if pending else 'Methods applied to the supplied manifest; consult REPORT.md and VALIDATION.md for cautions.'}\n"
    )
    (out / "METHODS.md").write_text(text, encoding="utf-8")


def _write_markdown(
    out: Path,
    bundle: AnalysisBundle,
    *,
    manifest_path: Path,
) -> None:
    health_rows = _health_rows(bundle)
    health_table = _md_table(
        [
            "job",
            "model",
            "lang",
            "optimizer",
            "seed",
            "git sha",
            "status",
            "evaluated",
            "stop",
            "issues",
            "warnings",
        ],
        [
            [
                row["job_id"],
                row["manifest_model"],
                row["manifest_language"],
                row["manifest_optimizer"],
                row["manifest_seed"],
                row["git_sha"],
                row["status"],
                row["n_evaluated"],
                row["stop_class"],
                "; ".join(row["issues"]) if isinstance(row["issues"], list) else row["issues"],
                (
                    "; ".join(row["warnings"])
                    if isinstance(row["warnings"], list)
                    else row["warnings"]
                ),
            ]
            for row in health_rows
        ],
    )
    grid_table = _md_table(
        [
            "model",
            "language",
            "optimizer",
            "manifest rows",
            "distinct seeds",
            "seed set",
            "status",
        ],
        [
            [
                row["model"],
                row["language"],
                row["optimizer"],
                row["manifest_rows"],
                row["distinct_seeds"],
                row["seeds"],
                row["status"],
            ]
            for row in _manifest_grid_rows(bundle)
        ],
    )
    manifest_caution = (
        "\n\n## Supplied-grid caution\n\n- " + "\n- ".join(bundle.manifest_warnings)
        if bundle.manifest_warnings
        else ""
    )
    expected_caution = (
        "\n\n## Expected-seed-contract caution\n\n- " + "\n- ".join(bundle.expected_grid_warnings)
        if bundle.expected_grid_warnings
        else ""
    )
    expected_status = (
        f"Expected seed contract: {list(bundle.expected_seeds)} — "
        f"{'COMPLETE' if bundle.expected_grid_complete else 'INCOMPLETE'}.\n\n"
        if bundle.expected_seeds
        else "No independent expected-seed contract was supplied.\n\n"
    )
    qualified_n = sum(
        any(warning.startswith("QUALIFIED OVERRIDE:") for warning in health.warnings)
        for health in bundle.healths
    )
    (out / "run_health.md").write_text(
        "# Run health / supplied-grid check\n\n"
        f"Manifest: `{manifest_path}`\n\n"
        f"Eligible: {bundle.healthy_n}/{len(bundle.healths)} supplied runs"
        + (
            f" ({qualified_n} admitted under an explicit missing-artifact override).\n\n"
            if qualified_n
            else ".\n\n"
        )
        + expected_status
        + "Rectangularity and the explicit expected-seed contract are checked "
        "separately; job IDs should also be reconciled with the submitted SLURM batch.\n\n"
        "## Configuration × seed grid\n\n"
        + grid_table
        + manifest_caution
        + expected_caution
        + "\n\n## Run-level health\n\n"
        + health_table
        + "\n",
        encoding="utf-8",
    )

    config_rows = per_config_rows(bundle.runs)
    compact = _md_table(
        [
            "language",
            "optimizer",
            "subset",
            "subset status",
            "n",
            "horizon",
            "scope",
            "baseline raw median [IQR]",
            "baseline weighted median [IQR]",
            "global run best f1 median [IQR]",
            "repaired/seed median [IQR]",
            "mean seed rate [bootstrap 95% CI]",
            "pooled rate [Wilson 95% CI, descriptive]",
        ],
        [
            [
                row["language"],
                row["optimizer"],
                row["subset"],
                row["subset_status"],
                row["n_seeds"],
                row["comparison_budget"],
                row["horizon_scope"],
                (
                    f"{_fmt(row['baseline_raw_median'])} "
                    f"[{_fmt(row['baseline_raw_q1'])}, "
                    f"{_fmt(row['baseline_raw_q3'])}]"
                ),
                (
                    f"{_fmt(row['baseline_weighted_median'])} "
                    f"[{_fmt(row['baseline_weighted_q1'])}, "
                    f"{_fmt(row['baseline_weighted_q3'])}]"
                ),
                (
                    f"{_fmt(row['global_best_f1_analysis_horizon_median'])} "
                    f"[{_fmt(row['global_best_f1_analysis_horizon_q1'])}, "
                    f"{_fmt(row['global_best_f1_analysis_horizon_q3'])}]"
                ),
                (
                    f"{_fmt(row['repaired_per_seed_median'])} "
                    f"[{_fmt(row['repaired_per_seed_q1'])}, "
                    f"{_fmt(row['repaired_per_seed_q3'])}]"
                ),
                (
                    f"{_fmt(row['mean_seed_repair_rate'])} "
                    f"[{_fmt(row['seed_rate_bootstrap_low'])}, "
                    f"{_fmt(row['seed_rate_bootstrap_high'])}]"
                ),
                (
                    f"{_fmt(row['repair_rate_pooled'])} "
                    f"[{_fmt(row['repair_rate_wilson_low'])}, "
                    f"{_fmt(row['repair_rate_wilson_high'])}]"
                ),
            ]
            for row in config_rows
        ],
    )
    (out / "tables.md").write_text(
        "# Final analysis tables — digest\n\n"
        + compact
        + "\n\nFull precision and all fields are in the CSV files.\n",
        encoding="utf-8",
    )

    rq2 = rq2_rows(bundle.runs)
    rq2_families = rq2_family_rows(bundle.runs)
    rq3 = rq3_rows(bundle.runs)
    friedman = rq3_friedman_rows(bundle.runs)
    language_rows = language_comparison_rows(bundle.runs)
    best_rows = best_chromosome_rows(bundle.runs)
    recurring_rows = [row for row in _recurring_edits(bundle.runs) if row["n_distinct_seeds"] >= 2]
    rq3_best = [row for row in rq3 if row["metric"] == "best_f1"]
    rq3_repairs = [
        row
        for row in rq3
        if row["metric"] == "tasks_repaired_to_zero" and row["subset"] in {"full", "persistent"}
    ]
    covered_operators: list[dict[str, Any]] = []
    for language in sorted({row["language"] for row in rq2}):
        candidates = [
            row
            for row in rq2
            if row["language"] == language
            and isinstance(row.get("mean_seed_improving_rate"), (int, float))
            and math.isfinite(float(row["mean_seed_improving_rate"]))
        ]
        if candidates:
            covered_operators.append(
                max(
                    candidates,
                    key=lambda row: (
                        int(row["evaluated"]),
                        int(row["n_runs_observed"]),
                        float(row["mean_seed_improving_rate"]),
                    ),
                )
            )
    horizon_intro = (
        "At each language's common EA/random candidate-evaluation horizon"
        if all(run.horizon_scope == "cross_arm_common" for run in bundle.runs)
        else (
            "At each row's labelled analysis horizon; `cross_arm_common` is an "
            "equal-arm comparison, while `available_runs_minimum` preserves "
            "descriptive RQ1 evidence when an optimizer arm is absent"
        )
    )
    rq_lines = [
        "# RQ1 / RQ2 / RQ3 — evidence-bounded answer\n\n",
        "## RQ1\n\n",
        f"{horizon_intro}, the observed repair reach is:\n\n",
        _md_table(
            [
                "language",
                "optimizer",
                "subset",
                "subset status",
                "n seeds",
                "horizon/scope",
                "global run best f1 median [IQR]",
                "repaired/seed median",
                "mean seed repair rate [bootstrap 95% CI]",
            ],
            [
                [
                    row["language"],
                    row["optimizer"],
                    row["subset"],
                    row["subset_status"],
                    row["n_seeds"],
                    f"{row['comparison_budget']}/{row['horizon_scope']}",
                    (
                        f"{_fmt(row['global_best_f1_analysis_horizon_median'])} "
                        f"[{_fmt(row['global_best_f1_analysis_horizon_q1'])}, "
                        f"{_fmt(row['global_best_f1_analysis_horizon_q3'])}]"
                    ),
                    _fmt(row["repaired_per_seed_median"]),
                    (
                        f"{_fmt(row['mean_seed_repair_rate'])} "
                        f"[{_fmt(row['seed_rate_bootstrap_low'])}, "
                        f"{_fmt(row['seed_rate_bootstrap_high'])}]"
                    ),
                ]
                for row in config_rows
            ],
        ),
        "\n\nThe paired tests in `rq1_paired.csv` are "
        "`DESCRIPTIVE_ONLY_POST_SELECTION`: each task keeps its baseline as an "
        "oracle floor and selects its best observed search candidate, so worsening "
        "is structurally prevented. Fresh pre-specified Stage-2 replicates are "
        "required for generalization.\n\n",
        "### Best surviving chromosomes\n\n",
        (
            _md_table(
                [
                    "run",
                    "language",
                    "optimizer",
                    "best-ever f1",
                    "final f1/f2/f3",
                    "# rules",
                    "rule IDs",
                    "mutators",
                    "order priorities",
                    "interpretation",
                ],
                [
                    [
                        row["run"],
                        row["language"],
                        row["optimizer"],
                        row["best_ever_f1"],
                        (
                            f"{_fmt(row['final_front_f1'])}/"
                            f"{_fmt(row['final_front_f2'])}/"
                            f"{_fmt(row['final_front_f3'])}"
                        ),
                        row["n_rules_mutated"],
                        row["mutated_rule_ids"],
                        row["mutators"],
                        row["order_priority"],
                        row["note"],
                    ]
                    for row in best_rows
                ],
            )
            if best_rows
            else "No eligible run has a qualitative chromosome record."
        ),
        "\n\nRecurring edits require byte-identical rule text in at least two distinct "
        "healthy seeds for the same rule. Mutation paths are retained as lineage "
        "metadata and do not split identical final text into separate groups.\n\n",
        (
            _md_table(
                ["language", "rule", "observed paths", "text hash", "distinct seeds"],
                [
                    [
                        row["language"],
                        row["rule_id"],
                        row["mutation_paths"],
                        row["text_sha256"][:12],
                        row["n_distinct_seeds"],
                    ]
                    for row in recurring_rows
                ],
            )
            if recurring_rows
            else "No byte-identical edit recurs across two healthy seeds."
        ),
        "\n\n",
        "## RQ2\n\n",
        (
            "The most frequently evaluated local-EA operator in each language is "
            "shown as a coverage example, not as a winner. Sparse operators are not "
            "ranked by a single extreme rate. Attribution is to the last proposed "
            "text mutator/order move and is not isolated causal credit.\n\n"
        ),
        _md_table(
            [
                "language",
                "family/operator",
                "runs",
                "horizon/scope",
                "evaluated",
                "mean seed improving rate [bootstrap 95% CI]",
                "mean local Δf1",
            ],
            [
                [
                    row["language"],
                    f"{row['family']}/{row['operator']}",
                    row["n_runs_observed"],
                    f"{row['comparison_budget']}/{row['horizon_scope']}",
                    row["evaluated"],
                    (
                        f"{_fmt(row['mean_seed_improving_rate'])} "
                        f"[{_fmt(row['seed_rate_bootstrap_low'])}, "
                        f"{_fmt(row['seed_rate_bootstrap_high'])}]"
                    ),
                    row["mean_seed_delta_f1"],
                ]
                for row in covered_operators
            ],
        ),
        "\n\nRun-balanced family aggregates are:\n\n",
        _md_table(
            [
                "language",
                "family",
                "runs",
                "horizon/scope",
                "proposals/evaluated",
                "security improving",
                "accepted and improving",
                "mean seed rate [bootstrap 95% CI]",
                "mean seed local Δf1 [bootstrap 95% CI]",
            ],
            [
                [
                    row["language"],
                    row["family"],
                    row["n_runs_observed"],
                    f"{row['comparison_budget']}/{row['horizon_scope']}",
                    f"{row['proposals']}/{row['evaluated']}",
                    row["security_improving"],
                    row["accepted_and_security_improving"],
                    (
                        f"{_fmt(row['mean_seed_improving_rate'])} "
                        f"[{_fmt(row['seed_rate_bootstrap_low'])}, "
                        f"{_fmt(row['seed_rate_bootstrap_high'])}]"
                    ),
                    (
                        f"{_fmt(row['mean_seed_delta_f1'])} "
                        f"[{_fmt(row['mean_seed_delta_f1_bootstrap_low'])}, "
                        f"{_fmt(row['mean_seed_delta_f1_bootstrap_high'])}]"
                    ),
                ]
                for row in rq2_families
            ],
        ),
        "\n\nAll operators and families are in `rq2_per_operator.csv` and "
        "`rq2_per_family.csv`. Seed-level bootstrap "
        "intervals over proposal-level rates are primary; proposal-level and "
        "evaluated-candidate Wilson intervals are descriptive because moves are "
        "nested within runs, chromosomes, and rules.\n\n",
        "## RQ3\n\n",
        "The primary table requested by the handoff is MWU + Vargha–Delaney A12 at "
        "the shortest common candidate-evaluation horizon. Because the same seed "
        "also drives common opening samples, paired-seed sign-test sensitivity is "
        "reported beside it. The design choice remains unresolved and no single "
        "inferential verdict is promoted here.\n\n",
    ]
    if rq3_best:
        rq_lines.append(
            _md_table(
                [
                    "language",
                    "n EA/random",
                    "budget",
                    "EA/random best-f1 median",
                    "MWU p (BH)",
                    "A12",
                    "paired sign p (BH)/effect",
                ],
                [
                    [
                        row["language"],
                        f"{row['n_ea']}/{row['n_random']}",
                        row["comparison_budget"],
                        (f"{_fmt(median(row['ea_values']))}/{_fmt(median(row['random_values']))}"),
                        f"{_fmt(row['mwu_p'])} ({_fmt(row['mwu_p_bh'])})",
                        (
                            f"{_fmt(row['a12_ea_vs_random'])} "
                            f"[{_fmt(row['a12_bootstrap_low'])}, "
                            f"{_fmt(row['a12_bootstrap_high'])}] "
                            f"{row['a12_magnitude']}; {row['a12_bootstrap_note']}"
                        ),
                        (
                            f"{_fmt(row['paired_sign_p'])} "
                            f"({_fmt(row['paired_sign_p_bh'])})/"
                            f"{_fmt(row['paired_sign_effect'])}"
                        ),
                    ]
                    for row in rq3_best
                ],
            )
            + "\n\n"
        )
    if rq3_repairs:
        rq_lines.extend(
            [
                "EA-versus-random task repairs, including the persistent subset when "
                "final-baseline labels are complete:\n\n",
                _md_table(
                    [
                        "language",
                        "subset",
                        "n EA/random",
                        "EA/random repaired median",
                        "MWU p (BH)",
                        "A12 [bootstrap 95% CI]",
                    ],
                    [
                        [
                            row["language"],
                            row["subset"],
                            f"{row['n_ea']}/{row['n_random']}",
                            (
                                f"{_fmt(median(row['ea_values']))}/"
                                f"{_fmt(median(row['random_values']))}"
                            ),
                            f"{_fmt(row['mwu_p'])} ({_fmt(row['mwu_p_bh'])})",
                            (
                                f"{_fmt(row['a12_ea_vs_random'])} "
                                f"[{_fmt(row['a12_bootstrap_low'])}, "
                                f"{_fmt(row['a12_bootstrap_high'])}]; "
                                f"{row['a12_bootstrap_note']}"
                            ),
                        ]
                        for row in rq3_repairs
                    ],
                ),
                "\n\n",
            ]
        )
    if friedman:
        rq_lines.extend(
            [
                "The required three-condition Friedman result is emitted only as a "
                "matched-seed, `DESCRIPTIVE_ONLY_POST_SELECTION` sensitivity analysis; "
                "EA/random endpoints are best-of-budget selections from the same "
                "Stage-1 outputs used for estimation:\n\n",
                _md_table(
                    [
                        "language",
                        "usable blocks",
                        "baseline/EA/random weighted median",
                        "Friedman p (BH)",
                        "Kendall W",
                    ],
                    [
                        [
                            row["language"],
                            row["usable_block_n"],
                            (
                                f"{_fmt(row['baseline_weighted_median'])}/"
                                f"{_fmt(row['ea_best_weighted_median'])}/"
                                f"{_fmt(row['random_best_weighted_median'])}"
                            ),
                            f"{_fmt(row['friedman_p'])} ({_fmt(row['friedman_p_bh'])})",
                            row["kendall_w"],
                        ]
                        for row in friedman
                    ],
                ),
                "\n\n",
            ]
        )
    if language_rows:
        represented_languages = {row["language"] for row in language_rows}
        language_heading = (
            "## Python versus Java\n\n"
            if represented_languages == {"python", "java"}
            else "## Language-normalized descriptive rows\n\n"
        )
        language_scope = (
            "This comparison is denominator-normalized and descriptive because "
            "the languages use different task populations:\n\n"
            if represented_languages == {"python", "java"}
            else (
                "A cross-language comparison is unavailable because the supplied "
                "healthy manifest does not contain both Python and Java. The available "
                "denominator-normalized rows are:\n\n"
            )
        )
        rq_lines.extend(
            [
                language_heading,
                language_scope,
                _md_table(
                    [
                        "language",
                        "optimizer",
                        "subset",
                        "horizon/scope",
                        "mean seed repair rate",
                        "mean normalized weighted reduction",
                    ],
                    [
                        [
                            row["language"],
                            row["optimizer"],
                            row["subset"],
                            f"{row['comparison_budget']}/{row['horizon_scope']}",
                            (
                                f"{_fmt(row['mean_seed_repair_rate'])} "
                                f"[{_fmt(row['repair_rate_bootstrap_low'])}, "
                                f"{_fmt(row['repair_rate_bootstrap_high'])}]"
                            ),
                            (
                                f"{_fmt(row['mean_normalized_weighted_reduction'])} "
                                f"[{_fmt(row['normalized_reduction_bootstrap_low'])}, "
                                f"{_fmt(row['normalized_reduction_bootstrap_high'])}]"
                            ),
                        ]
                        for row in language_rows
                        if row["subset"] == "full"
                    ],
                ),
                "\n",
            ]
        )
    (out / "rq_answers.md").write_text("".join(rq_lines), encoding="utf-8")

    warnings = [
        *bundle.analysis_warnings,
        *(warning for run in bundle.runs for warning in run.subset_warnings),
    ]
    open_text = (
        "# Open questions / data gaps\n\n"
        "1. Resolve whether the matched seed/common-random-number design is paired or "
        "whether MWU/A12 remains primary.\n"
        "2. Treat equal candidate evaluations as distinct from equal compute; inspect "
        "`cost_hygiene.csv`. Its code-generation counters exclude direct LLM-mutator "
        "calls, so they cannot establish total-compute parity; wall time is the only "
        "inclusive recorded cost proxy.\n"
        "3. Verify and add the exact Arcuri–Briand bibliography entry before citing it "
        "for the fairness prescription.\n"
        "4. Confirm whether random-builder or f1-only archive ablations are excluded "
        "from the final manifest.\n"
        "5. Reconcile the explicit expected-seed contract and every recorded job ID "
        "against the submitted SLURM batch.\n"
        + (
            "\n## Data warnings\n\n- " + "\n- ".join(sorted(set(warnings))) + "\n"
            if warnings
            else ""
        )
        + (
            "\n## Extraction errors\n\n- " + "\n- ".join(bundle.extraction_errors) + "\n"
            if bundle.extraction_errors
            else ""
        )
    )
    (out / "open_questions.md").write_text(open_text, encoding="utf-8")

    excluded_n = sum(not health.healthy for health in bundle.healths)
    qualified_n = sum(
        any(warning.startswith("QUALIFIED OVERRIDE:") for warning in health.warnings)
        for health in bundle.healths
    )
    caution_lines = list(bundle.analysis_warnings)
    if excluded_n:
        caution_lines.append(
            f"{excluded_n} manifest run(s) are missing or unhealthy; see run_health.csv"
        )
    report_status = "ANALYZED_WITH_CAUTION" if bundle.has_cautions else "ANALYZED"
    report_caution = (
        "## Analysis cautions\n\n- "
        + "\n- ".join(caution_lines)
        + (
            "\n\nResults are conditional on the supplied cells and are not the "
            "full supported rectangular grid."
            if bundle.manifest_warnings
            else ""
        )
        + "\n\n"
        if caution_lines
        else ""
    )
    report = (
        "# Final schema-4 repair analysis\n\n"
        f"{_material_passport(report_status)}\n"
        f"- Manifest: `{manifest_path}`\n"
        + (
            f"- Runs admitted under qualified override: {len(bundle.runs)}/{len(bundle.healths)}\n"
            if qualified_n
            else f"- Healthy runs analyzed: {len(bundle.runs)}/{len(bundle.healths)}\n"
        )
        + f"- Expected seeds: `{json.dumps(bundle.expected_seeds)}` "
        f"({'complete' if bundle.expected_grid_complete else 'incomplete or unspecified'})\n"
        f"- Common candidate-evaluation budgets: `{json.dumps(bundle.common_budgets)}`\n\n"
        f"- Available-run analysis horizons: `{json.dumps(bundle.analysis_budgets)}`\n\n"
        + report_caution
        + "## Deliverables\n\n"
        "- [Run health](run_health.md)\n"
        "- [Tables digest](tables.md)\n"
        "- [RQ answers](rq_answers.md)\n"
        "- [Best chromosomes](best_chromosomes.md)\n"
        "- [Methods and citation boundaries](METHODS.md)\n"
        "- [Validation / fallacy scan](VALIDATION.md)\n"
        "- [Open questions](open_questions.md)\n\n"
        "All unhealthy or missing runs remain in `run_health.csv`; aggregates include "
        "only eligible schema-4 runs, preserve qualification warnings, and report n.\n"
    )
    (out / "REPORT.md").write_text(report, encoding="utf-8")


def write_analysis(
    out: Path,
    bundle: AnalysisBundle,
    *,
    manifest_path: Path,
    repo_root: Path,
) -> None:
    out.mkdir(parents=True, exist_ok=True)
    if not bundle.runs:
        write_pending(
            out,
            reason=(
                "A manifest was supplied, but zero runs passed the strict schema-4 "
                "health and extraction gates. See run_health.csv."
            ),
            expected_entries=[health.entry for health in bundle.healths],
        )
        health_rows = _health_rows(bundle)
        _write_csv(out / "run_health.csv", _TABLE_HEADERS["run_health.csv"], health_rows)
        grid_rows = _manifest_grid_rows(bundle)
        warning_text = (
            "\n\n## Supplied-grid caution\n\n- " + "\n- ".join(bundle.manifest_warnings)
            if bundle.manifest_warnings
            else ""
        )
        expected_warning_text = (
            "\n\n## Expected-seed-contract caution\n\n- "
            + "\n- ".join(bundle.expected_grid_warnings)
            if bundle.expected_grid_warnings
            else ""
        )
        (out / "run_health.md").write_text(
            "# Run health / supplied-grid check\n\n"
            f"Expected seeds: `{list(bundle.expected_seeds)}`; status: "
            f"{'COMPLETE' if bundle.expected_grid_complete else 'INCOMPLETE'}.\n\n"
            "## Configuration × seed grid\n\n"
            + _md_table(
                [
                    "model",
                    "language",
                    "optimizer",
                    "manifest rows",
                    "distinct seeds",
                    "seed set",
                    "status",
                ],
                [
                    [
                        row["model"],
                        row["language"],
                        row["optimizer"],
                        row["manifest_rows"],
                        row["distinct_seeds"],
                        row["seeds"],
                        row["status"],
                    ]
                    for row in grid_rows
                ],
            )
            + warning_text
            + expected_warning_text
            + "\n\n## Run-level health\n\n"
            + _md_table(
                [
                    "job",
                    "model",
                    "lang",
                    "optimizer",
                    "seed",
                    "git sha",
                    "status",
                    "issues",
                    "warnings",
                ],
                [
                    [
                        row["job_id"],
                        row["manifest_model"],
                        row["manifest_language"],
                        row["manifest_optimizer"],
                        row["manifest_seed"],
                        row["git_sha"],
                        row["status"],
                        "; ".join(row["issues"])
                        if isinstance(row["issues"], list)
                        else row["issues"],
                        "; ".join(row["warnings"])
                        if isinstance(row["warnings"], list)
                        else row["warnings"],
                    ]
                    for row in health_rows
                ],
            )
            + "\n",
            encoding="utf-8",
        )
        return
    tables = {
        "run_health.csv": _health_rows(bundle),
        "per_config_summary.csv": per_config_rows(bundle.runs),
        "rq1_paired.csv": rq1_rows(bundle.runs),
        "rq3_ea_vs_random.csv": rq3_rows(bundle.runs),
        "rq3_friedman_sensitivity.csv": rq3_friedman_rows(bundle.runs),
        "rq2_per_operator.csv": rq2_rows(bundle.runs),
        "rq2_per_family.csv": rq2_family_rows(bundle.runs),
        "language_comparison.csv": language_comparison_rows(bundle.runs),
        "best_chromosome.csv": best_chromosome_rows(bundle.runs),
        "best_chromosome_per_config.csv": best_chromosome_per_config_rows(bundle.runs),
        "cost_hygiene.csv": cost_rows(bundle.runs),
        "convergence.csv": aggregate_convergence(bundle.runs),
        "recurring_rule_edits.csv": _recurring_edits(bundle.runs),
        "per_task_outcomes.csv": _per_task_rows(bundle.runs),
        "subset_validation.csv": _subset_validation_rows(bundle.runs),
    }
    cwe_rows, check_rows = cwe_check_rows(bundle.runs)
    tables["cwe_repair.csv"] = cwe_rows
    tables["check_flips.csv"] = check_rows
    for filename, headers in _TABLE_HEADERS.items():
        rows = tables.get(filename, [])
        _write_csv(out / filename, headers, rows)
    _write_best_chromosome_digest(out, bundle.runs, repo_root=repo_root)
    _write_figures(out, bundle)
    _write_markdown(out, bundle, manifest_path=manifest_path)
    _write_validation(out, pending=False, bundle=bundle)
    _write_methods(out, pending=False)
