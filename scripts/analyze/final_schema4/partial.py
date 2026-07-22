"""Provisional diagnostics for active or otherwise unfinalized schema-4 runs.

This module is intentionally separate from the strict final-results path.  It
never promotes an active prefix to a healthy final run, never uses a periodic
EA checkpoint as a final archive, and never emits inferential claims.
"""

from __future__ import annotations

import csv
import json
import math
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from statistics import median
from typing import Any, Iterable, Sequence

from .core import (
    ManifestEntry,
    RunAnalysis,
    RunHealth,
    _analyze_single,
    _inspect_single,
    _number,
    load_manifest,
)

PROVISIONAL_STATUS = "PROVISIONAL_ACTIVE_RUN_SNAPSHOT"
_MODEL_FAMILIES = {"qwen", "llama"}
_EXPECTED_INCOMPLETE_ISSUES = {
    "expected exactly one hillclimb summary, found 0",
    "semgrep_debug/semgrep_debug.jsonl missing or empty",
    "natural stop not verified",
    "EA run has no archive snapshot",
    (
        "run_config.json is reconstructed pre-completion provenance, not the "
        "writer-emitted final config"
    ),
}
_CHECKPOINT_LAG_RE = re.compile(r"^final archive snapshot iter=(\d+) != evaluated=(\d+)$")


@dataclass
class PartialEntry:
    """One explicitly supplied or narrowly discovered provisional run."""

    entry: ManifestEntry
    declared_model_family: str = ""
    discovery_issue: str = ""


@dataclass
class PartialRunStatus:
    """Prefix eligibility without changing strict-final health semantics."""

    source: PartialEntry
    health: RunHealth
    model_family: str
    blockers: list[str] = field(default_factory=list)
    cautions: list[str] = field(default_factory=list)
    latest_checkpoint_iter: int | None = None
    files_before: dict[str, tuple[int, int]] = field(default_factory=dict, repr=False)
    files_after: dict[str, tuple[int, int]] = field(default_factory=dict, repr=False)

    @property
    def eligible(self) -> bool:
        return not self.blockers

    @property
    def key(self) -> tuple[str, str, str, str]:
        return (
            self.model_family,
            self.health.actual_language or self.source.entry.language,
            self.health.actual_optimizer or self.source.entry.optimizer,
            self.health.actual_seed or self.source.entry.seed,
        )

    @property
    def label(self) -> str:
        model, language, optimizer, seed = self.key
        return f"{model}/{language}/{optimizer}/seed{seed}"

    def add_blocker(self, message: str) -> None:
        if message and message not in self.blockers:
            self.blockers.append(message)

    def add_caution(self, message: str) -> None:
        if message and message not in self.cautions:
            self.cautions.append(message)


@dataclass
class PartialRun:
    status: PartialRunStatus
    analysis: RunAnalysis

    @property
    def model_family(self) -> str:
        return self.status.model_family

    @property
    def language(self) -> str:
        return self.analysis.language

    @property
    def optimizer(self) -> str:
        return self.analysis.optimizer

    @property
    def seed(self) -> str:
        return self.analysis.seed

    @property
    def label(self) -> str:
        return self.status.label


@dataclass
class PartialBundle:
    statuses: list[PartialRunStatus]
    runs: list[PartialRun]
    source_description: str
    snapshot_utc: str

    @property
    def has_blockers(self) -> bool:
        return any(status.blockers for status in self.statuses)

    @property
    def budgets(self) -> dict[tuple[str, str], int]:
        grouped: dict[tuple[str, str], list[int]] = defaultdict(list)
        for run in self.runs:
            grouped[(run.model_family, run.language)].append(run.analysis.comparison_budget)
        return {key: min(values) for key, values in grouped.items() if values}


def _normalize_declared_family(value: Any) -> str:
    family = str(value or "").strip().lower()
    if family in {"qwen2.5", "qwen32b"}:
        return "qwen"
    if family in {"llama3", "llama70b"}:
        return "llama"
    return family


def discover_partial_entries(results_roots: Sequence[Path]) -> list[PartialEntry]:
    """Discover only run leaves below roots explicitly placed in partial scope."""
    discovered: list[PartialEntry] = []
    seen: set[Path] = set()
    for raw_root in results_roots:
        root = Path(raw_root).expanduser().resolve()
        if not root.is_dir():
            raise ValueError(f"partial results root is not a directory: {root}")
        for config_path in sorted(root.rglob("run_config.json")):
            run_dir = config_path.parent.resolve()
            if run_dir in seen:
                continue
            seen.add(run_dir)
            try:
                config = json.loads(config_path.read_text(encoding="utf-8"))
                if not isinstance(config, dict):
                    raise ValueError("top-level value is not an object")
                args = config.get("args")
                if not isinstance(args, dict):
                    raise ValueError("args is missing or not an object")
                languages = args.get("languages")
                language = (
                    str(languages[0]) if isinstance(languages, list) and len(languages) == 1 else ""
                )
                entry = ManifestEntry(
                    language=language,
                    optimizer=str(args.get("optimizer") or ""),
                    seed=str(args.get("seed") if args.get("seed") is not None else ""),
                    job_id=str(config.get("slurm_job_id") or ""),
                    run_dir=run_dir,
                )
                discovered.append(PartialEntry(entry=entry))
            except (OSError, ValueError, json.JSONDecodeError) as exc:
                discovered.append(
                    PartialEntry(
                        entry=ManifestEntry("", "", "", run_dir=run_dir),
                        discovery_issue=f"run_config discovery failed: {exc}",
                    )
                )
    if not discovered:
        roots = ", ".join(str(Path(root)) for root in results_roots)
        raise ValueError(f"no run_config.json files found under partial roots: {roots}")
    return discovered


def load_partial_manifest(
    path: Path,
    *,
    repo_root: Path,
    results_roots: Sequence[Path] = (),
    logs_root: Path | None = None,
) -> list[PartialEntry]:
    """Load the strict manifest contract for a provisional, separately named path."""
    resolved = Path(path).resolve()
    entries = load_manifest(
        resolved,
        repo_root=repo_root,
        results_roots=results_roots,
        logs_root=logs_root,
    )
    with resolved.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    if len(rows) != len(entries):
        raise ValueError("partial manifest row count changed while it was read")
    return [
        PartialEntry(
            entry=entry,
            declared_model_family=_normalize_declared_family(row.get("model")),
        )
        for entry, row in zip(entries, rows)
    ]


def _file_state(run_dir: Path | None) -> dict[str, tuple[int, int]]:
    if run_dir is None or not run_dir.is_dir():
        return {}
    state: dict[str, tuple[int, int]] = {}
    for path in sorted(run_dir.rglob("*")):
        if not path.is_file():
            continue
        try:
            stat = path.stat()
        except OSError:
            continue
        state[str(path.relative_to(run_dir))] = (stat.st_size, stat.st_mtime_ns)
    return state


def _latest_checkpoint(run_dir: Path | None) -> int | None:
    if run_dir is None:
        return None
    values = []
    for path in (run_dir / "archive_snapshots").glob("iter*.json"):
        match = re.fullmatch(r"iter(\d+)\.json", path.name)
        if match:
            values.append(int(match.group(1)))
    return max(values) if values else None


def _prefix_telemetry_issues(health: RunHealth) -> list[str]:
    """Validate telemetry that strict core checks only after a summary exists."""
    issues: list[str] = []
    cumulative_keys = ("llm_calls_total", "input_tokens_total", "output_tokens_total")
    previous = {key: -1 for key in cumulative_keys}
    for row_number, row in enumerate(health.iterations, 1):
        for key in cumulative_keys:
            value = row.get(key)
            if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                issues.append(f"iterations row {row_number}: {key} is missing/invalid")
                continue
            if value < previous[key]:
                issues.append(f"iterations row {row_number}: {key} is not monotone")
            previous[key] = value
        reused = row.get("n_prompts_reused")
        rerun = row.get("n_prompts_rerun")
        if any(
            not isinstance(value, int) or isinstance(value, bool) or value < 0
            for value in (reused, rerun)
        ):
            issues.append(f"iterations row {row_number}: prompt cache counters are missing/invalid")
        elif row.get("budget_consumed") is True and health.n_cases is not None:
            if reused + rerun != health.n_cases:
                issues.append(
                    f"iterations row {row_number}: reused+rerun={reused + rerun} "
                    f"!= n_cases={health.n_cases}"
                )
        if health.actual_optimizer == "ea":
            selection_meta = row.get("selection_meta")
            if not isinstance(selection_meta, dict) or not isinstance(
                selection_meta.get("restarts_this_iter"), list
            ):
                issues.append(f"iterations row {row_number}: EA restart telemetry is missing")
    return issues


def _verify_local_rules_map(status: PartialRunStatus, repo_root: Path) -> bool:
    """Verify a cluster-absolute map by basename against the local repository copy."""
    health = status.health
    if not health.rules_map or not health.actual_language:
        return False
    candidate = repo_root / "rule_maps" / Path(health.rules_map).name
    if not candidate.is_file():
        return False
    try:
        payload = json.loads(candidate.read_text(encoding="utf-8"))
        mappings = payload.get("mappings")
        if not isinstance(mappings, list):
            return False
        language_ids = {
            str(row["index"])
            for row in mappings
            if isinstance(row, dict)
            and str(row.get("language") or "").lower() == health.actual_language
            and row.get("index") is not None
        }
    except (OSError, ValueError, json.JSONDecodeError):
        return False
    if (
        health.n_cases is None
        or len(language_ids) != health.n_cases
        or language_ids != set(health.baseline_ids)
    ):
        return False
    status.add_caution(f"rules map verified via local basename fallback: {candidate}")
    return True


def _status_from_entry(source: PartialEntry, *, repo_root: Path) -> PartialRunStatus:
    before = _file_state(source.entry.run_dir)
    health = _inspect_single(source.entry)
    family = health.actual_model_family
    status = PartialRunStatus(
        source=source,
        health=health,
        model_family=family,
        latest_checkpoint_iter=_latest_checkpoint(source.entry.run_dir),
        files_before=before,
    )
    if source.discovery_issue:
        status.add_blocker(source.discovery_issue)
    if not family:
        status.add_blocker(f"unsupported or unrecognized model family: {health.model!r}")
    elif family not in _MODEL_FAMILIES:
        status.add_blocker(f"unsupported model family: {family!r}")
    declared = source.declared_model_family
    if declared and declared not in _MODEL_FAMILIES:
        status.add_blocker(f"manifest model_family is unsupported: {declared!r}")
    elif declared and family and declared != family:
        status.add_blocker(f"manifest/config model-family mismatch: {declared!r} != {family!r}")

    for issue in health.issues:
        if issue in _EXPECTED_INCOMPLETE_ISSUES:
            status.add_caution(issue)
            continue
        checkpoint_match = _CHECKPOINT_LAG_RE.fullmatch(issue)
        if checkpoint_match:
            checkpoint, evaluated = (int(value) for value in checkpoint_match.groups())
            if 0 <= checkpoint < evaluated:
                status.add_caution(
                    f"periodic EA checkpoint lags completed prefix: {checkpoint} < {evaluated}"
                )
                continue
        status.add_blocker(issue)
    map_warning = "could not verify rules-map content locally:"
    for warning in health.warnings:
        if warning.startswith(map_warning) and _verify_local_rules_map(status, repo_root):
            continue
        status.add_caution(warning)
    for issue in _prefix_telemetry_issues(health):
        status.add_blocker(issue)
    status.add_caution("active/unfinalized prefix: not eligible for strict final analysis")
    if not (source.entry.run_dir and (source.entry.run_dir / "semgrep_debug").is_dir()):
        status.add_caution(
            "independent Semgrep-debug error/accounting audit unavailable in this snapshot"
        )
    return status


def _add_cross_run_checks(statuses: Sequence[PartialRunStatus]) -> None:
    by_key: dict[tuple[str, str, str, str], list[PartialRunStatus]] = defaultdict(list)
    for status in statuses:
        by_key[status.key].append(status)
    for key, group in by_key.items():
        if len(group) > 1:
            for status in group:
                status.add_blocker(f"duplicate partial run cell {key}: {len(group)} runs")

    by_family_language: dict[tuple[str, str], list[PartialRunStatus]] = defaultdict(list)
    for status in statuses:
        model, language, _, _ = status.key
        if model and language and status.health.config:
            by_family_language[(model, language)].append(status)
    comparable_keys = (
        "backend",
        "model",
        "quantization",
        "bnb_compute_dtype",
        "temperature",
        "rules_map",
        "n_cases",
        "iterations",
        "selection",
        "mutators",
        "objective_direction",
        "max_depth",
        "random_max_changes",
        "order_move_weight",
        "enable_validation",
        "enable_perplexity",
        "enable_eval_cache",
        "semgrep_config",
        "semgrep_timeout_seconds",
        "semgrep_jobs",
    )
    for (model, language), group in by_family_language.items():
        baseline_sets = {status.health.baseline_ids for status in group}
        if len(baseline_sets) > 1:
            for status in group:
                status.add_blocker(
                    f"baseline task set differs within {model}/{language} partial runs"
                )
        shas = {status.health.git_sha for status in group if status.health.git_sha}
        if len(shas) > 1:
            for status in group:
                status.add_blocker(f"git_sha differs within {model}/{language}: {sorted(shas)}")
        for key in comparable_keys:
            values = {
                json.dumps(
                    status.health.config.get("args", {}).get(key),
                    sort_keys=True,
                    default=str,
                )
                for status in group
            }
            if len(values) > 1:
                for status in group:
                    status.add_blocker(
                        f"comparison config mismatch for {model}/{language}: "
                        f"args.{key}={sorted(values)}"
                    )

    paired: dict[tuple[str, str, str], list[PartialRunStatus]] = defaultdict(list)
    for status in statuses:
        model, language, _, seed = status.key
        if model and language and seed:
            paired[(model, language, seed)].append(status)
    for (model, language, seed), group in paired.items():
        arms = {status.key[2] for status in group}
        if not {"ea", "random_search"}.issubset(arms):
            continue
        reference = group[0].health.baseline_signature_by_id
        if any(status.health.baseline_signature_by_id != reference for status in group[1:]):
            for status in group:
                status.add_blocker(
                    f"baseline result mismatch between optimizer arms for "
                    f"{model}/{language}/seed{seed}"
                )


def _analysis_budgets(
    statuses: Sequence[PartialRunStatus],
) -> tuple[dict[tuple[str, str], int], dict[tuple[str, str], str]]:
    grouped: dict[tuple[str, str], list[PartialRunStatus]] = defaultdict(list)
    for status in statuses:
        if status.eligible and status.health.n_evaluated > 0:
            grouped[(status.model_family, status.health.actual_language)].append(status)
    budgets: dict[tuple[str, str], int] = {}
    scopes: dict[tuple[str, str], str] = {}
    for key, group in grouped.items():
        budgets[key] = min(status.health.n_evaluated for status in group)
        arms = {status.health.actual_optimizer for status in group}
        scopes[key] = (
            "partial_cross_arm_common"
            if {"ea", "random_search"}.issubset(arms)
            else "partial_available_runs_minimum"
        )
    return budgets, scopes


def analyze_partial(
    entries: Sequence[PartialEntry],
    *,
    subset_dir: Path,
    repo_root: Path,
    source_description: str,
) -> PartialBundle:
    """Analyze complete committed prefixes while preserving final-run strictness."""
    statuses = [_status_from_entry(entry, repo_root=repo_root) for entry in entries]
    _add_cross_run_checks(statuses)

    analyses: dict[int, PartialRun] = {}
    while True:
        budgets, scopes = _analysis_budgets(statuses)
        failed = False
        analyses = {}
        for status in statuses:
            if not status.eligible:
                continue
            key = (status.model_family, status.health.actual_language)
            budget = budgets.get(key)
            if budget is None:
                status.add_blocker("no positive completed-prefix analysis horizon")
                failed = True
                continue
            checkpoint_path = status.health.final_snapshot_path
            status.health.final_snapshot_path = None
            try:
                analysis = _analyze_single(
                    status.health,
                    comparison_budget=budget,
                    horizon_scope=scopes[key],
                    subset_dir=subset_dir,
                )
            except (OSError, ValueError, json.JSONDecodeError) as exc:
                status.add_blocker(f"completed-prefix metric extraction failed: {exc}")
                failed = True
            else:
                analyses[id(status)] = PartialRun(status=status, analysis=analysis)
                for warning in analysis.subset_warnings:
                    status.add_caution(warning)
            finally:
                status.health.final_snapshot_path = checkpoint_path
        if not failed:
            break

    for status in statuses:
        status.files_after = _file_state(status.source.entry.run_dir)
        if status.files_before != status.files_after:
            status.add_blocker(
                "FILES_CHANGED_DURING_READ: active artifacts were not a stable snapshot"
            )
            analyses.pop(id(status), None)

    runs = [
        analyses[id(status)] for status in statuses if status.eligible and id(status) in analyses
    ]
    return PartialBundle(
        statuses=statuses,
        runs=runs,
        source_description=source_description,
        snapshot_utc=datetime.now(timezone.utc).isoformat(),
    )


def _quantile(values: Sequence[float], q: float) -> float:
    xs = sorted(float(value) for value in values)
    if not xs:
        return math.nan
    if len(xs) == 1:
        return xs[0]
    position = (len(xs) - 1) * q
    low = math.floor(position)
    high = math.ceil(position)
    if low == high:
        return xs[low]
    return xs[low] + (xs[high] - xs[low]) * (position - low)


def _median_iqr(values: Sequence[float]) -> tuple[float, float, float]:
    if not values:
        return (math.nan, math.nan, math.nan)
    return (median(values), _quantile(values, 0.25), _quantile(values, 0.75))


def _csv_value(value: Any) -> Any:
    if isinstance(value, (list, tuple, set, dict)):
        if isinstance(value, set):
            value = sorted(value)
        return json.dumps(value, sort_keys=True)
    if isinstance(value, float) and not math.isfinite(value):
        return ""
    if value is None:
        return ""
    return value


def _write_csv(path: Path, headers: Sequence[str], rows: Iterable[dict[str, Any]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=headers, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({header: _csv_value(row.get(header)) for header in headers})


def _status_rows(bundle: PartialBundle) -> list[dict[str, Any]]:
    rows = []
    for status in bundle.statuses:
        health = status.health
        target = health.max_iterations
        rows.append(
            {
                "snapshot_status": PROVISIONAL_STATUS,
                "model_family": status.model_family,
                "model": health.model,
                "language": health.actual_language or status.source.entry.language,
                "optimizer": health.actual_optimizer or status.source.entry.optimizer,
                "seed": health.actual_seed or status.source.entry.seed,
                "job_id": health.slurm_job_id or status.source.entry.job_id,
                "run_dir": str(health.path or ""),
                "schema_version": health.schema_version,
                "git_sha": health.git_sha,
                "target_evaluations": target,
                "completed_evaluations": health.n_evaluated,
                "progress_fraction": (
                    health.n_evaluated / target if isinstance(target, int) and target > 0 else None
                ),
                "proposals": health.n_proposals,
                "identity_proposals": health.n_identity,
                "latest_completed_iter": health.n_evaluated,
                "latest_checkpoint_iter": status.latest_checkpoint_iter,
                "checkpoint_lag": (
                    health.n_evaluated - status.latest_checkpoint_iter
                    if status.latest_checkpoint_iter is not None
                    else None
                ),
                "baseline_records": health.n_baseline_records,
                "prefix_status": ("PREFIX_ELIGIBLE_PROVISIONAL" if status.eligible else "EXCLUDED"),
                "blockers": status.blockers,
                "cautions": status.cautions,
            }
        )
    return rows


def _metric_rows(bundle: PartialBundle) -> list[dict[str, Any]]:
    rows = []
    for run in bundle.runs:
        baseline_raw = sum(prompt.raw_count for prompt in run.analysis.baseline.values())
        baseline_weighted = sum(prompt.weighted_score for prompt in run.analysis.baseline.values())
        common = run.analysis.task_summaries_budget["full"]
        observed = run.analysis.task_summaries_final["full"]
        rows.append(
            {
                "snapshot_status": PROVISIONAL_STATUS,
                "run": run.label,
                "model_family": run.model_family,
                "language": run.language,
                "optimizer": run.optimizer,
                "seed": run.seed,
                "observed_completed_evaluations": run.status.health.n_evaluated,
                "common_horizon": run.analysis.comparison_budget,
                "horizon_scope": run.analysis.horizon_scope,
                "best_f1_observed_prefix": run.analysis.best_f1_final,
                "best_f1_observed_iter": run.analysis.best_f1_iter,
                "best_f1_common_horizon": run.analysis.best_f1_budget,
                "best_f1_common_iter": run.analysis.best_f1_budget_iter,
                "baseline_raw": baseline_raw,
                "baseline_weighted": baseline_weighted,
                "baseline_movable_tasks": common["n_movable"],
                "repaired_common_horizon": common["n_repaired"],
                "raw_reduction_common_horizon": common["raw_reduction"],
                "weighted_reduction_common_horizon": common["weighted_reduction"],
                "repair_rate_common_horizon": common["repair_rate"],
                "repaired_observed_prefix": observed["n_repaired"],
                "raw_reduction_observed_prefix": observed["raw_reduction"],
                "weighted_reduction_observed_prefix": observed["weighted_reduction"],
            }
        )
    return rows


def _arm_rows(bundle: PartialBundle) -> list[dict[str, Any]]:
    groups: dict[tuple[str, str, str], list[PartialRun]] = defaultdict(list)
    for run in bundle.runs:
        groups[(run.model_family, run.language, run.optimizer)].append(run)
    rows = []
    for (model, language, optimizer), group in sorted(groups.items()):
        best = [run.analysis.best_f1_budget for run in group]
        repaired = [
            float(run.analysis.task_summaries_budget["full"]["n_repaired"]) for run in group
        ]
        weighted = [
            float(run.analysis.task_summaries_budget["full"]["weighted_reduction"]) for run in group
        ]
        rates = [float(run.analysis.task_summaries_budget["full"]["repair_rate"]) for run in group]
        best_median, best_q1, best_q3 = _median_iqr(best)
        repair_median, repair_q1, repair_q3 = _median_iqr(repaired)
        weighted_median, weighted_q1, weighted_q3 = _median_iqr(weighted)
        rows.append(
            {
                "snapshot_status": PROVISIONAL_STATUS,
                "model_family": model,
                "language": language,
                "optimizer": optimizer,
                "n_runs": len(group),
                "common_horizon": min(run.analysis.comparison_budget for run in group),
                "best_f1_median": best_median,
                "best_f1_q1": best_q1,
                "best_f1_q3": best_q3,
                "repaired_median": repair_median,
                "repaired_q1": repair_q1,
                "repaired_q3": repair_q3,
                "weighted_reduction_median": weighted_median,
                "weighted_reduction_q1": weighted_q1,
                "weighted_reduction_q3": weighted_q3,
                "mean_seed_repair_rate": sum(rates) / len(rates) if rates else None,
                "interpretation": "DESCRIPTIVE_ONLY_ACTIVE_PREFIX",
            }
        )
    return rows


def _matched_rows(bundle: PartialBundle) -> list[dict[str, Any]]:
    groups: dict[tuple[str, str, str], dict[str, PartialRun]] = defaultdict(dict)
    for run in bundle.runs:
        groups[(run.model_family, run.language, run.seed)][run.optimizer] = run
    rows = []
    for (model, language, seed), arms in sorted(groups.items()):
        ea = arms.get("ea")
        random_run = arms.get("random_search")
        if ea is None or random_run is None:
            continue
        ea_summary = ea.analysis.task_summaries_budget["full"]
        random_summary = random_run.analysis.task_summaries_budget["full"]
        rows.append(
            {
                "snapshot_status": PROVISIONAL_STATUS,
                "model_family": model,
                "language": language,
                "seed": seed,
                "common_horizon": min(
                    ea.analysis.comparison_budget,
                    random_run.analysis.comparison_budget,
                ),
                "ea_best_f1": ea.analysis.best_f1_budget,
                "random_best_f1": random_run.analysis.best_f1_budget,
                "delta_best_f1_ea_minus_random": (
                    ea.analysis.best_f1_budget - random_run.analysis.best_f1_budget
                ),
                "ea_repaired": ea_summary["n_repaired"],
                "random_repaired": random_summary["n_repaired"],
                "delta_repaired_ea_minus_random": (
                    ea_summary["n_repaired"] - random_summary["n_repaired"]
                ),
                "ea_weighted_reduction": ea_summary["weighted_reduction"],
                "random_weighted_reduction": random_summary["weighted_reduction"],
                "delta_weighted_reduction_ea_minus_random": (
                    ea_summary["weighted_reduction"] - random_summary["weighted_reduction"]
                ),
                "interpretation": "DESCRIPTIVE_MATCHED_PREFIX_ONLY",
            }
        )
    return rows


def _cost_point(run: PartialRun, horizon: int) -> dict[str, Any]:
    records = [
        row
        for row in run.status.health.iterations
        if isinstance(row.get("iter"), int) and row["iter"] <= horizon
    ]
    evaluated = [row for row in records if row.get("budget_consumed") is True]
    last = max(evaluated, key=lambda row: int(row["iter"])) if evaluated else {}
    hits = sum(int(row["n_prompts_reused"]) for row in evaluated)
    misses = run.status.health.n_baseline_records + sum(
        int(row["n_prompts_rerun"]) for row in evaluated
    )
    restart_counts: Counter[str] = Counter()
    for row in records:
        selection_meta = row.get("selection_meta")
        events = (
            selection_meta.get("restarts_this_iter", []) if isinstance(selection_meta, dict) else []
        )
        for event in events if isinstance(events, list) else []:
            if isinstance(event, dict) and event.get("reason"):
                restart_counts[str(event["reason"])] += 1
    return {
        "proposals": len(records),
        "identities": sum(row.get("mutation_identity") is True for row in records),
        "calls": last.get("llm_calls_total"),
        "input_tokens": last.get("input_tokens_total"),
        "output_tokens": last.get("output_tokens_total"),
        "cache_hits": hits,
        "cache_misses": misses,
        "cache_hit_rate": hits / (hits + misses) if hits + misses else None,
        "restart_stagnation": restart_counts.get("stagnation", 0),
        "restart_exhausted": restart_counts.get("exhausted", 0),
    }


def _cost_rows(bundle: PartialBundle) -> list[dict[str, Any]]:
    rows = []
    for run in bundle.runs:
        common = _cost_point(run, run.analysis.comparison_budget)
        observed = _cost_point(run, run.status.health.n_evaluated)
        row = {
            "snapshot_status": PROVISIONAL_STATUS,
            "run": run.label,
            "model_family": run.model_family,
            "language": run.language,
            "optimizer": run.optimizer,
            "seed": run.seed,
            "common_horizon": run.analysis.comparison_budget,
            "observed_horizon": run.status.health.n_evaluated,
            "accounting_scope": (
                "code-generation prefix counters; excludes direct LLM-mutator calls"
            ),
        }
        for prefix, values in (("common", common), ("observed", observed)):
            for key, value in values.items():
                row[f"{prefix}_{key}"] = value
        rows.append(row)
    return rows


def _operator_rows(bundle: PartialBundle) -> list[dict[str, Any]]:
    groups: dict[tuple[str, str, str, str], list[tuple[str, dict[str, Any]]]] = defaultdict(list)
    for run in bundle.runs:
        if run.optimizer != "ea":
            continue
        for row in run.analysis.operator_rows:
            groups[
                (
                    run.model_family,
                    run.language,
                    str(row["family"]),
                    str(row["operator"]),
                )
            ].append((run.label, row))
    output = []
    for (model, language, family, operator), observed in sorted(groups.items()):
        rows = [row for _, row in observed]
        evaluated_deltas = [
            float(row["delta_f1"])
            for row in rows
            if row["evaluated"] and _number(row.get("delta_f1")) is not None
        ]
        output.append(
            {
                "snapshot_status": PROVISIONAL_STATUS,
                "model_family": model,
                "language": language,
                "family": family,
                "operator": operator,
                "common_horizon": min(
                    run.analysis.comparison_budget
                    for run in bundle.runs
                    if run.model_family == model and run.language == language
                ),
                "n_runs_observed": len({label for label, _ in observed}),
                "proposals": len(rows),
                "identities": sum(row["identity"] for row in rows),
                "evaluated": sum(row["evaluated"] for row in rows),
                "security_improving": sum(row["security_improving"] for row in rows),
                "accepted_and_security_improving": sum(
                    row["accepted"] and row["security_improving"] for row in rows
                ),
                "mean_delta_f1_evaluated": (
                    sum(evaluated_deltas) / len(evaluated_deltas) if evaluated_deltas else None
                ),
                "interpretation": "DESCRIPTIVE_NESTED_PROPOSALS_ONLY",
            }
        )
    return output


def _convergence_rows(bundle: PartialBundle) -> list[dict[str, Any]]:
    groups: dict[tuple[str, str, str, int], list[float]] = defaultdict(list)
    for run in bundle.runs:
        best = 0.0
        for row in run.status.health.iterations:
            if row.get("budget_consumed") is not True:
                continue
            iteration = row.get("iter")
            f1 = _number(row.get("f1"))
            if (
                not isinstance(iteration, int)
                or f1 is None
                or iteration > run.analysis.comparison_budget
            ):
                continue
            best = max(best, f1)
            groups[(run.model_family, run.language, run.optimizer, iteration)].append(best)
    rows = []
    for (model, language, optimizer, iteration), values in sorted(groups.items()):
        point, q1, q3 = _median_iqr(values)
        rows.append(
            {
                "snapshot_status": PROVISIONAL_STATUS,
                "model_family": model,
                "language": language,
                "optimizer": optimizer,
                "iteration": iteration,
                "n_runs": len(values),
                "median_best_f1": point,
                "q1_best_f1": q1,
                "q3_best_f1": q3,
            }
        )
    return rows


def _task_rows(bundle: PartialBundle) -> list[dict[str, Any]]:
    rows = []
    for run in bundle.runs:
        for outcome in run.analysis.budget_outcomes:
            rows.append(
                {
                    "snapshot_status": PROVISIONAL_STATUS,
                    "run": run.label,
                    "model_family": run.model_family,
                    "language": run.language,
                    "optimizer": run.optimizer,
                    "seed": run.seed,
                    "common_horizon": run.analysis.comparison_budget,
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


def _cwe_check_rows(
    bundle: PartialBundle,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    cwe: dict[tuple[str, str, str, str], Counter[str]] = defaultdict(Counter)
    checks: dict[tuple[str, str, str, str], Counter[str]] = defaultdict(Counter)
    movable: Counter[tuple[str, str, str]] = Counter()
    for run in bundle.runs:
        stratum = (run.model_family, run.language, run.optimizer)
        for outcome in run.analysis.budget_outcomes:
            if not outcome.movable:
                continue
            movable[stratum] += 1
            cwe_key = (*stratum, outcome.cwe_id)
            cwe[cwe_key]["movable"] += 1
            cwe[cwe_key]["reduced"] += int(outcome.delta_raw > 0)
            cwe[cwe_key]["repaired"] += int(outcome.repaired_to_zero)
            for check_id in outcome.baseline.check_ids:
                checks[(*stratum, check_id)]["baseline_present"] += 1
            for check_id in outcome.baseline.check_ids - outcome.best.check_ids:
                checks[(*stratum, check_id)]["removed"] += 1
            for check_id in outcome.best.check_ids - outcome.baseline.check_ids:
                checks[(*stratum, check_id)]["added"] += 1
    cwe_rows = []
    for (model, language, optimizer, cwe_id), counts in sorted(cwe.items()):
        denominator = counts["movable"]
        cwe_rows.append(
            {
                "snapshot_status": PROVISIONAL_STATUS,
                "model_family": model,
                "language": language,
                "optimizer": optimizer,
                "cwe_id": cwe_id,
                "movable_observations": denominator,
                "reduced": counts["reduced"],
                "reduced_rate": counts["reduced"] / denominator,
                "repaired": counts["repaired"],
                "repaired_rate": counts["repaired"] / denominator,
            }
        )
    check_rows = []
    for (model, language, optimizer, check_id), counts in sorted(checks.items()):
        stratum = (model, language, optimizer)
        baseline_present = counts["baseline_present"]
        baseline_absent = movable[stratum] - baseline_present
        check_rows.append(
            {
                "snapshot_status": PROVISIONAL_STATUS,
                "model_family": model,
                "language": language,
                "optimizer": optimizer,
                "check_id": check_id,
                "movable_observations": movable[stratum],
                "baseline_present": baseline_present,
                "baseline_absent": baseline_absent,
                "removed": counts["removed"],
                "removed_rate": (
                    counts["removed"] / baseline_present if baseline_present else None
                ),
                "added": counts["added"],
                "added_rate": counts["added"] / baseline_absent if baseline_absent else None,
            }
        )
    return cwe_rows, check_rows


def _write_convergence_figure(
    out: Path,
    rows: Sequence[dict[str, Any]],
) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    panels = sorted({(row["model_family"], row["language"]) for row in rows})
    if not panels:
        fig, axis = plt.subplots(figsize=(8, 4.5))
        axis.text(
            0.5,
            0.5,
            f"{PROVISIONAL_STATUS}\nNo eligible completed prefixes",
            ha="center",
            va="center",
        )
        axis.axis("off")
    else:
        fig, axes = plt.subplots(
            len(panels),
            1,
            figsize=(9, max(4.5, 3.8 * len(panels))),
            squeeze=False,
        )
        colors = {"ea": "#2563eb", "random_search": "#dc2626"}
        for axis, (model, language) in zip(axes.flat, panels):
            for optimizer in ("ea", "random_search"):
                selected = [
                    row
                    for row in rows
                    if row["model_family"] == model
                    and row["language"] == language
                    and row["optimizer"] == optimizer
                ]
                if not selected:
                    continue
                x = [row["iteration"] for row in selected]
                y = [row["median_best_f1"] for row in selected]
                low = [row["q1_best_f1"] for row in selected]
                high = [row["q3_best_f1"] for row in selected]
                axis.plot(x, y, label=optimizer, color=colors[optimizer], linewidth=2)
                axis.fill_between(x, low, high, color=colors[optimizer], alpha=0.16)
            axis.set_title(f"{model} / {language} — provisional common-prefix convergence")
            axis.set_xlabel("Completed candidate evaluations")
            axis.set_ylabel("Median best f1 so far")
            axis.grid(alpha=0.25)
            axis.legend()
        fig.suptitle(PROVISIONAL_STATUS, fontsize=10, color="#9a3412")
        fig.tight_layout()
    for suffix in ("png", "svg"):
        fig.savefig(out / f"partial_convergence.{suffix}", dpi=180, bbox_inches="tight")
    plt.close(fig)


def _md_table(headers: Sequence[str], rows: Sequence[Sequence[Any]]) -> str:
    def cell(value: Any) -> str:
        if isinstance(value, float):
            value = "" if not math.isfinite(value) else f"{value:.3f}"
        return str(value).replace("|", "\\|").replace("\n", " ")

    output = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    output.extend("| " + " | ".join(cell(value) for value in row) + " |" for row in rows)
    return "\n".join(output)


def _write_report(
    out: Path,
    bundle: PartialBundle,
    status_rows: Sequence[dict[str, Any]],
    arm_rows: Sequence[dict[str, Any]],
    matched_rows: Sequence[dict[str, Any]],
) -> None:
    cautions = sorted({message for status in bundle.statuses for message in status.cautions})
    blockers = [
        f"{status.label}: {message}" for status in bundle.statuses for message in status.blockers
    ]
    lines = [
        "# Provisional schema-4 active-run diagnostics\n\n",
        f"> **{PROVISIONAL_STATUS}** — these are tester snapshots, not final results.\n\n",
        "## Material Passport\n\n",
        "- Verification Status: PROVISIONAL / IN_PROGRESS\n",
        "- Completed-prefix validation: ANALYZED\n",
        "- Artifact class: active/unfinalized run snapshot\n",
        f"- Snapshot time (UTC): `{bundle.snapshot_utc}`\n",
        f"- Source: `{bundle.source_description}`\n",
        f"- Eligible completed prefixes: {len(bundle.runs)}/{len(bundle.statuses)}\n",
        "- Inferential status: not assessed; no p-values or confidence claims emitted\n",
        "- Final-analysis eligibility: explicitly not assessed by this provisional path\n\n",
        "## Interpretation boundary\n\n",
        "Only fully written candidate records and their matching intermediate artifacts "
        "are analyzed. Arm comparisons use the shortest completed evaluation prefix "
        "shared by the eligible runs. Observed-prefix values have unequal horizons "
        "and remain per-run diagnostics. Periodic EA checkpoints are never treated "
        "as final archives.\n\n",
        "## Run status\n\n",
        _md_table(
            [
                "model/lang/optimizer/seed",
                "completed/target",
                "proposals",
                "checkpoint",
                "prefix status",
            ],
            [
                [
                    (
                        f"{row['model_family']}/{row['language']}/"
                        f"{row['optimizer']}/seed{row['seed']}"
                    ),
                    f"{row['completed_evaluations']}/{row['target_evaluations']}",
                    row["proposals"],
                    row["latest_checkpoint_iter"],
                    row["prefix_status"],
                ]
                for row in status_rows
            ],
        ),
        "\n\n## Descriptive arm snapshot at the common horizon\n\n",
        (
            _md_table(
                [
                    "model/lang",
                    "optimizer",
                    "n",
                    "horizon",
                    "best f1 median [IQR]",
                    "repaired median [IQR]",
                    "weighted reduction median [IQR]",
                ],
                [
                    [
                        f"{row['model_family']}/{row['language']}",
                        row["optimizer"],
                        row["n_runs"],
                        row["common_horizon"],
                        (
                            f"{row['best_f1_median']:.1f} "
                            f"[{row['best_f1_q1']:.1f}, {row['best_f1_q3']:.1f}]"
                        ),
                        (
                            f"{row['repaired_median']:.1f} "
                            f"[{row['repaired_q1']:.1f}, {row['repaired_q3']:.1f}]"
                        ),
                        (
                            f"{row['weighted_reduction_median']:.1f} "
                            f"[{row['weighted_reduction_q1']:.1f}, "
                            f"{row['weighted_reduction_q3']:.1f}]"
                        ),
                    ]
                    for row in arm_rows
                ],
            )
            if arm_rows
            else "No eligible arm summaries."
        ),
        "\n\n## Matched tester seeds\n\n",
        (
            _md_table(
                [
                    "model/lang/seed",
                    "horizon",
                    "Δ best f1",
                    "Δ repaired",
                    "Δ weighted reduction",
                ],
                [
                    [
                        f"{row['model_family']}/{row['language']}/seed{row['seed']}",
                        row["common_horizon"],
                        row["delta_best_f1_ea_minus_random"],
                        row["delta_repaired_ea_minus_random"],
                        row["delta_weighted_reduction_ea_minus_random"],
                    ]
                    for row in matched_rows
                ],
            )
            if matched_rows
            else "No complete EA/random tester-seed pairs."
        ),
        "\n\n## Cautions\n\n",
    ]
    lines.extend(f"- {message}\n" for message in cautions)
    if not cautions:
        lines.append("- No additional cautions recorded.\n")
    lines.append("\n## Exclusions\n\n")
    lines.extend(f"- {message}\n" for message in blockers)
    if not blockers:
        lines.append("- None.\n")
    lines.extend(
        [
            "\n## Outputs\n\n",
            "- `partial_run_status.csv`\n",
            "- `partial_run_metrics.csv`\n",
            "- `partial_arm_summary.csv`\n",
            "- `partial_matched_pairs.csv`\n",
            "- `partial_cost.csv`\n",
            "- `partial_operator.csv`\n",
            "- `partial_convergence.csv`, `.png`, and `.svg`\n",
            "- `partial_per_task_outcomes.csv`\n",
            "- `partial_cwe_repair.csv`\n",
            "- `partial_check_flips.csv`\n",
        ]
    )
    (out / "PARTIAL_REPORT.md").write_text("".join(lines), encoding="utf-8")


def write_partial_analysis(out: Path, bundle: PartialBundle) -> None:
    """Write only provisional artifacts with names distinct from final outputs."""
    out.mkdir(parents=True, exist_ok=True)
    status_rows = _status_rows(bundle)
    metric_rows = _metric_rows(bundle)
    arm_rows = _arm_rows(bundle)
    matched_rows = _matched_rows(bundle)
    cost_rows = _cost_rows(bundle)
    operator_rows = _operator_rows(bundle)
    convergence_rows = _convergence_rows(bundle)
    task_rows = _task_rows(bundle)
    cwe_rows, check_rows = _cwe_check_rows(bundle)

    tables: list[tuple[str, list[str], list[dict[str, Any]]]] = [
        (
            "partial_run_status.csv",
            [
                "snapshot_status",
                "model_family",
                "model",
                "language",
                "optimizer",
                "seed",
                "job_id",
                "run_dir",
                "schema_version",
                "git_sha",
                "target_evaluations",
                "completed_evaluations",
                "progress_fraction",
                "proposals",
                "identity_proposals",
                "latest_completed_iter",
                "latest_checkpoint_iter",
                "checkpoint_lag",
                "baseline_records",
                "prefix_status",
                "blockers",
                "cautions",
            ],
            status_rows,
        ),
        (
            "partial_run_metrics.csv",
            [
                "snapshot_status",
                "run",
                "model_family",
                "language",
                "optimizer",
                "seed",
                "observed_completed_evaluations",
                "common_horizon",
                "horizon_scope",
                "best_f1_observed_prefix",
                "best_f1_observed_iter",
                "best_f1_common_horizon",
                "best_f1_common_iter",
                "baseline_raw",
                "baseline_weighted",
                "baseline_movable_tasks",
                "repaired_common_horizon",
                "raw_reduction_common_horizon",
                "weighted_reduction_common_horizon",
                "repair_rate_common_horizon",
                "repaired_observed_prefix",
                "raw_reduction_observed_prefix",
                "weighted_reduction_observed_prefix",
            ],
            metric_rows,
        ),
        (
            "partial_arm_summary.csv",
            [
                "snapshot_status",
                "model_family",
                "language",
                "optimizer",
                "n_runs",
                "common_horizon",
                "best_f1_median",
                "best_f1_q1",
                "best_f1_q3",
                "repaired_median",
                "repaired_q1",
                "repaired_q3",
                "weighted_reduction_median",
                "weighted_reduction_q1",
                "weighted_reduction_q3",
                "mean_seed_repair_rate",
                "interpretation",
            ],
            arm_rows,
        ),
        (
            "partial_matched_pairs.csv",
            [
                "snapshot_status",
                "model_family",
                "language",
                "seed",
                "common_horizon",
                "ea_best_f1",
                "random_best_f1",
                "delta_best_f1_ea_minus_random",
                "ea_repaired",
                "random_repaired",
                "delta_repaired_ea_minus_random",
                "ea_weighted_reduction",
                "random_weighted_reduction",
                "delta_weighted_reduction_ea_minus_random",
                "interpretation",
            ],
            matched_rows,
        ),
        (
            "partial_cost.csv",
            [
                "snapshot_status",
                "run",
                "model_family",
                "language",
                "optimizer",
                "seed",
                "common_horizon",
                "observed_horizon",
                "common_proposals",
                "common_identities",
                "common_calls",
                "common_input_tokens",
                "common_output_tokens",
                "common_cache_hits",
                "common_cache_misses",
                "common_cache_hit_rate",
                "common_restart_stagnation",
                "common_restart_exhausted",
                "observed_proposals",
                "observed_identities",
                "observed_calls",
                "observed_input_tokens",
                "observed_output_tokens",
                "observed_cache_hits",
                "observed_cache_misses",
                "observed_cache_hit_rate",
                "observed_restart_stagnation",
                "observed_restart_exhausted",
                "accounting_scope",
            ],
            cost_rows,
        ),
        (
            "partial_operator.csv",
            [
                "snapshot_status",
                "model_family",
                "language",
                "family",
                "operator",
                "common_horizon",
                "n_runs_observed",
                "proposals",
                "identities",
                "evaluated",
                "security_improving",
                "accepted_and_security_improving",
                "mean_delta_f1_evaluated",
                "interpretation",
            ],
            operator_rows,
        ),
        (
            "partial_convergence.csv",
            [
                "snapshot_status",
                "model_family",
                "language",
                "optimizer",
                "iteration",
                "n_runs",
                "median_best_f1",
                "q1_best_f1",
                "q3_best_f1",
            ],
            convergence_rows,
        ),
        (
            "partial_per_task_outcomes.csv",
            [
                "snapshot_status",
                "run",
                "model_family",
                "language",
                "optimizer",
                "seed",
                "common_horizon",
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
            task_rows,
        ),
        (
            "partial_cwe_repair.csv",
            [
                "snapshot_status",
                "model_family",
                "language",
                "optimizer",
                "cwe_id",
                "movable_observations",
                "reduced",
                "reduced_rate",
                "repaired",
                "repaired_rate",
            ],
            cwe_rows,
        ),
        (
            "partial_check_flips.csv",
            [
                "snapshot_status",
                "model_family",
                "language",
                "optimizer",
                "check_id",
                "movable_observations",
                "baseline_present",
                "baseline_absent",
                "removed",
                "removed_rate",
                "added",
                "added_rate",
            ],
            check_rows,
        ),
    ]
    for filename, headers, rows in tables:
        _write_csv(out / filename, headers, rows)
    _write_convergence_figure(out, convergence_rows)
    _write_report(out, bundle, status_rows, arm_rows, matched_rows)
