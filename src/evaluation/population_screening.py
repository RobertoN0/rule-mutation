"""Evidence validation and classification for stochastic population screening."""

from __future__ import annotations

import json
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from src.evaluation.generation_contract import prompt_contract_sha256
from src.retrieval.consensus import (
    MODEL_IDS,
    canonical_json_sha256,
    load_json_object,
    sha256_file,
    task_content_identity,
    task_identity,
)
from src.retrieval.population import ELIGIBILITY_POLICY, population_fingerprint


SCREENING_TEMPERATURE = 0.6
SCREENING_REPETITIONS_PER_ROUND = 20
SCREENING_CONDITIONS = ("norules", "withrules")
SCREENING_MODELS = ("qwen", "llama")
SCREENING_POLICY = (
    "retain_any_finding_or_incomplete_evidence_exclude_only_all_valid_zero"
)


@dataclass(frozen=True)
class TaskObservation:
    status: str
    raw_count: int | None

    @property
    def valid(self) -> bool:
        return self.status == "valid"


@dataclass(frozen=True)
class ScreeningRun:
    model: str
    language: str
    condition: str
    run_dir: Path
    source_map_path: Path
    source_map: dict[str, Any]
    seeds: tuple[int, ...]
    observations: Mapping[tuple[int, str], TaskObservation]
    evidence: dict[str, Any]


def _jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            row = json.loads(line)
            if not isinstance(row, dict):
                raise ValueError(f"{path}:{line_number}: expected a JSON object")
            rows.append(row)
    return rows


def _map_rows(payload: dict[str, Any], path: Path) -> list[dict[str, Any]]:
    rows = payload.get("mappings")
    if not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows):
        raise ValueError(f"{path}: mappings must be a list of objects")
    identities = [task_identity(row) for row in rows]
    if len(identities) != len(set(identities)):
        raise ValueError(f"{path}: duplicate task identities")
    return rows


def _verify_validator_hashes(
    run_dir: Path,
    validation: dict[str, Any],
) -> None:
    paths = {
        "run_config": run_dir / "run_config.json",
        "replicates": run_dir / "replicates.jsonl",
        "replicate_summary": run_dir / "replicate_summary.json",
    }
    recorded = validation.get("artifact_sha256")
    if not isinstance(recorded, dict):
        raise ValueError(f"{run_dir}: validator lacks artifact fingerprints")
    for name, path in paths.items():
        actual = sha256_file(path) if path.is_file() else None
        if recorded.get(name) != actual:
            raise ValueError(f"{run_dir}: stale replicate validation for {name}")


def load_screening_run(
    run_dir: Path,
    *,
    source_map_path: Path,
    model: str,
    language: str,
    condition: str,
    expected_seeds: Sequence[int],
    expected_prompt_contract: str | None = None,
) -> ScreeningRun:
    """Load one validated replicate run as screening evidence."""
    if model not in SCREENING_MODELS:
        raise ValueError(f"unknown screening model {model!r}")
    if language not in {"python", "java"}:
        raise ValueError(f"unsupported screening language {language!r}")
    if condition not in SCREENING_CONDITIONS:
        raise ValueError(f"unsupported screening condition {condition!r}")
    seeds = tuple(int(seed) for seed in expected_seeds)
    if not seeds or len(seeds) != len(set(seeds)):
        raise ValueError("screening seeds must be a non-empty distinct sequence")

    validation_path = run_dir / "replicate_validation.json"
    validation = load_json_object(validation_path)
    if validation.get("artifact_type") != "replicate_run_validation":
        raise ValueError(f"{validation_path}: wrong artifact_type")
    if validation.get("status") != "VALID":
        raise ValueError(f"{validation_path}: run is not VALID")
    _verify_validator_hashes(run_dir, validation)

    run_config_path = run_dir / "run_config.json"
    run_config = load_json_object(run_config_path)
    if run_config.get("artifact_type") != "replicate_run_config":
        raise ValueError(f"{run_config_path}: wrong artifact_type")
    args = run_config.get("args")
    if not isinstance(args, dict):
        raise ValueError(f"{run_config_path}: args must be an object")
    expected_contract = expected_prompt_contract or prompt_contract_sha256()
    required_equal = {
        "run_mode": "replicate",
        "model": MODEL_IDS[model],
        "languages": [language],
        "temperature": SCREENING_TEMPERATURE,
        "condition": condition,
        "selection": "first",
        "prompt_contract_sha256": expected_contract,
        "max_output_tokens": 4096,
        "invalid_output_policy": "missing_not_zero_with_explicit_denominator",
        "semgrep_version": "1.85.0",
    }
    for field, expected in required_equal.items():
        if args.get(field) != expected:
            raise ValueError(
                f"{run_config_path}: {field}={args.get(field)!r}, expected {expected!r}"
            )
    if args.get("n_cases_requested") is not None:
        raise ValueError(f"{run_config_path}: screening must use the complete source map")
    if not re.fullmatch(r"[0-9a-fA-F]{40}", str(args.get("model_revision", ""))):
        raise ValueError(f"{run_config_path}: exact model revision is missing")
    for field in ("torch_version", "transformers_version"):
        if not isinstance(args.get(field), str) or not args[field]:
            raise ValueError(f"{run_config_path}: {field} is missing")
    if not re.fullmatch(
        r"[0-9a-fA-F]{40}",
        str(args.get("semgrep_rules_source_commit", "")),
    ):
        raise ValueError(f"{run_config_path}: Semgrep SOURCE_COMMIT is missing")
    if not re.fullmatch(
        r"[0-9a-f]{64}",
        str(args.get("semgrep_rules_sha256", "")),
    ):
        raise ValueError(f"{run_config_path}: Semgrep rules hash is missing")

    source_map = load_json_object(source_map_path)
    source_rows = _map_rows(source_map, source_map_path)
    if args.get("rules_map_sha256") != sha256_file(source_map_path):
        raise ValueError(f"{run_config_path}: source-map hash mismatch")
    if args.get("n_cases") != len(source_rows):
        raise ValueError(f"{run_config_path}: source-map task count mismatch")
    if tuple(args.get("seeds", [])) != seeds:
        raise ValueError(f"{run_config_path}: seeds differ from the declared screening block")

    replicate_path = run_dir / "replicates.jsonl"
    replicate_rows = _jsonl(replicate_path)
    by_seed = {int(row.get("seed")): row for row in replicate_rows}
    if len(by_seed) != len(replicate_rows) or set(by_seed) != set(seeds):
        raise ValueError(f"{replicate_path}: replicate seeds do not reconcile")

    source_identities = [task_identity(row) for row in source_rows]
    observations: dict[tuple[int, str], TaskObservation] = {}
    intermediate_evidence: list[dict[str, Any]] = []
    for seed in seeds:
        replicate = by_seed[seed]
        for field, expected in {
            "artifact_type": "replicate_evaluation",
            "condition": condition,
            "model": MODEL_IDS[model],
            "language": language,
            "temperature": SCREENING_TEMPERATURE,
            "n_cases": len(source_rows),
            "raw_findings_scope": "valid_outputs_only",
        }.items():
            if replicate.get(field) != expected:
                raise ValueError(
                    f"{replicate_path}: seed {seed} has invalid {field}"
                )
        intermediate_value = replicate.get("intermediate_file")
        if not isinstance(intermediate_value, str):
            raise ValueError(f"{replicate_path}: seed {seed} lacks intermediate_file")
        intermediate_path = run_dir / intermediate_value
        task_rows = _jsonl(intermediate_path)
        identities = [
            (
                str(row.get("test_case_id")),
                str(row.get("analysis_language", "")).lower(),
                str(row.get("prompt_hash", "")),
            )
            for row in task_rows
        ]
        if identities != source_identities:
            raise ValueError(
                f"{intermediate_path}: task identities/order differ from source map"
            )
        per_case_raw: dict[str, int] = {}
        for row in task_rows:
            task_id = str(row["test_case_id"])
            status = str(row.get("qualification_status", ""))
            fitness = row.get("fitness")
            raw_count: int | None = None
            if status == "valid":
                if not isinstance(fitness, dict):
                    raise ValueError(
                        f"{intermediate_path}: valid task {task_id} lacks fitness"
                    )
                raw_count = fitness.get("raw_count")
                if not isinstance(raw_count, int) or raw_count < 0:
                    raise ValueError(
                        f"{intermediate_path}: task {task_id} has invalid raw_count"
                    )
                per_case_raw[task_id] = raw_count
            elif fitness is not None:
                raise ValueError(
                    f"{intermediate_path}: invalid task {task_id} must not have fitness"
                )
            observations[(seed, task_id)] = TaskObservation(status, raw_count)
        recorded_per_case = {
            str(task_id): int(raw_count)
            for task_id, raw_count in (replicate.get("per_case_raw") or {}).items()
        }
        if recorded_per_case != per_case_raw:
            raise ValueError(
                f"{intermediate_path}: valid per-case findings do not reconcile"
            )
        intermediate_evidence.append(
            {
                "filename": intermediate_value,
                "seed": seed,
                "sha256": sha256_file(intermediate_path),
                "tasks": len(task_rows),
            }
        )

    evidence = {
        "run_dir": run_dir.name,
        "model": model,
        "language": language,
        "condition": condition,
        "seeds": list(seeds),
        "source_map": {
            "filename": source_map_path.name,
            "sha256": sha256_file(source_map_path),
            "tasks": len(source_rows),
            "population_fingerprint": population_fingerprint(source_rows),
        },
        "run_config_sha256": sha256_file(run_config_path),
        "replicates_sha256": sha256_file(replicate_path),
        "replicate_validation_sha256": sha256_file(validation_path),
        "intermediate_evidence": intermediate_evidence,
        "git_commit_sha": run_config.get("git_commit_sha"),
        "model_revision": args["model_revision"],
        "torch_version": args["torch_version"],
        "transformers_version": args["transformers_version"],
        "prompt_contract_sha256": args["prompt_contract_sha256"],
        "semgrep_rules_source_commit": args["semgrep_rules_source_commit"],
        "semgrep_rules_sha256": args["semgrep_rules_sha256"],
        "semgrep_version": args["semgrep_version"],
    }
    return ScreeningRun(
        model=model,
        language=language,
        condition=condition,
        run_dir=run_dir,
        source_map_path=source_map_path,
        source_map=source_map,
        seeds=seeds,
        observations=observations,
        evidence=evidence,
    )


def _reconcile_run_contracts(runs: Mapping[tuple[str, str], ScreeningRun]) -> dict:
    fields = (
        "git_commit_sha",
        "torch_version",
        "transformers_version",
        "prompt_contract_sha256",
        "semgrep_rules_source_commit",
        "semgrep_rules_sha256",
        "semgrep_version",
    )
    reconciled: dict[str, Any] = {}
    for field in fields:
        values = {run.evidence[field] for run in runs.values()}
        if len(values) != 1:
            raise ValueError(f"screening runs disagree on {field}")
        reconciled[field] = values.pop()
    model_revisions: dict[str, str] = {}
    for model in SCREENING_MODELS:
        revisions = {
            runs[(model, condition)].evidence["model_revision"]
            for condition in SCREENING_CONDITIONS
        }
        if len(revisions) != 1:
            raise ValueError(
                f"{model} screening conditions use different model revisions"
            )
        model_revisions[model] = revisions.pop()
    reconciled["model_revisions"] = model_revisions
    return reconciled


def analyze_screening_round(
    runs: Mapping[tuple[str, str], ScreeningRun],
    *,
    stage: str,
) -> dict[str, Any]:
    """Classify tasks after one complete screening seed block."""
    if stage not in {"first", "second"}:
        raise ValueError("screening stage must be 'first' or 'second'")
    expected_keys = {
        (model, condition)
        for model in SCREENING_MODELS
        for condition in SCREENING_CONDITIONS
    }
    if set(runs) != expected_keys:
        raise ValueError("screening round requires both conditions for both models")
    languages = {run.language for run in runs.values()}
    seed_sets = {run.seeds for run in runs.values()}
    if len(languages) != 1 or len(seed_sets) != 1:
        raise ValueError("screening runs must share one language and seed block")
    language = languages.pop()
    seeds = seed_sets.pop()

    reference_rows = _map_rows(
        runs[("qwen", "withrules")].source_map,
        runs[("qwen", "withrules")].source_map_path,
    )
    reference_content = [task_content_identity(row) for row in reference_rows]
    reference_identities = [task_identity(row) for row in reference_rows]
    for run in runs.values():
        rows = _map_rows(run.source_map, run.source_map_path)
        if [task_identity(row) for row in rows] != reference_identities:
            raise ValueError("screening source maps differ in task identity/order")
        if [task_content_identity(row) for row in rows] != reference_content:
            raise ValueError("screening source maps differ in task content")

    contract = _reconcile_run_contracts(runs)
    classifications: dict[str, list[str]] = {
        "retain_observed_finding": [],
        "retain_incomplete_evidence": [],
        (
            "second_round_candidate"
            if stage == "first"
            else "exclude_never_vulnerable"
        ): [],
    }
    task_reports: dict[str, dict[str, Any]] = {}
    transition_counts: Counter[str] = Counter()
    invalid_statuses: Counter[str] = Counter()
    expected_observations = len(seeds) * len(expected_keys)
    for row in reference_rows:
        task_id = str(row["index"])
        observations = [
            runs[(model, condition)].observations[(seed, task_id)]
            for model in SCREENING_MODELS
            for condition in SCREENING_CONDITIONS
            for seed in seeds
        ]
        findings = [
            observation.raw_count
            for observation in observations
            if observation.valid and observation.raw_count is not None
        ]
        invalid = [
            observation.status for observation in observations if not observation.valid
        ]
        invalid_statuses.update(invalid)
        if any(raw_count > 0 for raw_count in findings):
            classification = "retain_observed_finding"
        elif invalid:
            classification = "retain_incomplete_evidence"
        else:
            classification = (
                "second_round_candidate"
                if stage == "first"
                else "exclude_never_vulnerable"
            )
        classifications[classification].append(task_id)

        per_task_transitions: Counter[str] = Counter()
        for model in SCREENING_MODELS:
            for seed in seeds:
                nr = runs[(model, "norules")].observations[(seed, task_id)]
                wr = runs[(model, "withrules")].observations[(seed, task_id)]
                if nr.valid and wr.valid:
                    if (nr.raw_count or 0) > 0 and (wr.raw_count or 0) == 0:
                        transition = "rule_fixed"
                    elif (nr.raw_count or 0) == 0 and (wr.raw_count or 0) > 0:
                        transition = "rule_worsened"
                    elif (nr.raw_count or 0) > 0 and (wr.raw_count or 0) > 0:
                        transition = "both_finding"
                    else:
                        transition = "both_zero"
                elif nr.valid and not wr.valid:
                    transition = "valid_to_invalid_with_rules"
                elif not nr.valid and wr.valid:
                    transition = "invalid_to_valid_with_rules"
                else:
                    transition = "both_invalid"
                per_task_transitions[transition] += 1
                transition_counts[transition] += 1

        task_reports[task_id] = {
            "language": language,
            "prompt_hash": row["prompt_hash"],
            "classification": classification,
            "expected_observations": expected_observations,
            "valid_observations": len(findings),
            "invalid_observations": len(invalid),
            "invalid_statuses": dict(sorted(Counter(invalid).items())),
            "observed_finding_cells": sum(raw_count > 0 for raw_count in findings),
            "total_raw_findings": sum(findings),
            "condition_transitions": dict(sorted(per_task_transitions.items())),
        }

    report = {
        "artifact_type": "population_screening_round",
        "evidence_status": "screening",
        "policy": SCREENING_POLICY,
        "stage": stage,
        "language": language,
        "temperature": SCREENING_TEMPERATURE,
        "seeds": list(seeds),
        "tasks": len(reference_rows),
        "expected_observations_per_task": expected_observations,
        "source_population_fingerprint": population_fingerprint(reference_rows),
        "classification_counts": {
            name: len(task_ids) for name, task_ids in classifications.items()
        },
        "task_ids": classifications,
        "invalid_statuses": dict(sorted(invalid_statuses.items())),
        "condition_transition_counts": dict(sorted(transition_counts.items())),
        "per_task": task_reports,
        "inputs": {
            f"{model}_{condition}": runs[(model, condition)].evidence
            for model in SCREENING_MODELS
            for condition in SCREENING_CONDITIONS
        },
        **contract,
    }
    report["classification_population_fingerprints"] = {
        name: population_fingerprint(
            [
                row
                for row in reference_rows
                if str(row["index"]) in set(task_ids)
            ]
        )
        for name, task_ids in classifications.items()
    }
    report["screening_evidence_sha256"] = canonical_json_sha256(
        {
            "inputs": report["inputs"],
            "policy": report["policy"],
            "stage": stage,
            "seeds": report["seeds"],
        }
    )
    return report


def finalize_screening(
    first_round: dict[str, Any],
    second_round: dict[str, Any],
) -> dict[str, Any]:
    """Freeze the final population after two disjoint twenty-seed rounds."""
    for report, stage in ((first_round, "first"), (second_round, "second")):
        if report.get("artifact_type") != "population_screening_round":
            raise ValueError(f"{stage} report has the wrong artifact_type")
        if report.get("stage") != stage:
            raise ValueError(f"{stage} report has the wrong stage")
        if report.get("policy") != SCREENING_POLICY:
            raise ValueError(f"{stage} report has the wrong policy")
    if first_round.get("language") != second_round.get("language"):
        raise ValueError("screening rounds use different languages")
    contract_fields = (
        "git_commit_sha",
        "torch_version",
        "transformers_version",
        "prompt_contract_sha256",
        "semgrep_rules_source_commit",
        "semgrep_rules_sha256",
        "semgrep_version",
        "model_revisions",
    )
    for field in contract_fields:
        if first_round.get(field) != second_round.get(field):
            raise ValueError(f"screening rounds disagree on {field}")
    first_seeds = set(first_round.get("seeds", []))
    second_seeds = set(second_round.get("seeds", []))
    if (
        len(first_seeds) != SCREENING_REPETITIONS_PER_ROUND
        or len(second_seeds) != SCREENING_REPETITIONS_PER_ROUND
    ):
        raise ValueError(
            "final screening requires exactly 20 distinct seeds in each round"
        )
    if first_seeds & second_seeds:
        raise ValueError("first- and second-round screening seeds overlap")

    candidates = set(first_round["task_ids"]["second_round_candidate"])
    second_population = set(second_round.get("per_task", {}))
    if candidates != second_population:
        raise ValueError("second-round population differs from first-round candidates")
    if second_round.get("source_population_fingerprint") != first_round.get(
        "classification_population_fingerprints",
        {},
    ).get("second_round_candidate"):
        raise ValueError(
            "second-round population fingerprint differs from first-round candidates"
        )
    excluded = set(second_round["task_ids"]["exclude_never_vulnerable"])
    retained_first_finding = set(
        first_round["task_ids"]["retain_observed_finding"]
    )
    retained_first_incomplete = set(
        first_round["task_ids"]["retain_incomplete_evidence"]
    )
    retained_second_finding = set(
        second_round["task_ids"]["retain_observed_finding"]
    )
    retained_second_incomplete = set(
        second_round["task_ids"]["retain_incomplete_evidence"]
    )
    retained = (
        retained_first_finding
        | retained_first_incomplete
        | retained_second_finding
        | retained_second_incomplete
    )
    source_ids = set(first_round.get("per_task", {}))
    if retained | excluded != source_ids or retained & excluded:
        raise ValueError("final screening partition does not cover the source population")

    reason_by_task = {
        task_id: "observed_finding_round_1"
        for task_id in retained_first_finding
    }
    reason_by_task.update(
        {
            task_id: "incomplete_evidence_round_1"
            for task_id in retained_first_incomplete
        }
    )
    reason_by_task.update(
        {
            task_id: "observed_finding_round_2"
            for task_id in retained_second_finding
        }
    )
    reason_by_task.update(
        {
            task_id: "incomplete_evidence_round_2"
            for task_id in retained_second_incomplete
        }
    )
    return {
        "artifact_type": "population_screening_manifest",
        "evidence_status": "final",
        "policy": SCREENING_POLICY,
        "language": first_round["language"],
        "temperature": SCREENING_TEMPERATURE,
        "seed_blocks": {
            "first": sorted(first_seeds),
            "second": sorted(second_seeds),
        },
        "source_population_total": len(source_ids),
        "source_population_fingerprint": first_round[
            "source_population_fingerprint"
        ],
        "retained_population_total": len(retained),
        "excluded_never_vulnerable_total": len(excluded),
        "retained_task_ids": sorted(retained, key=int),
        "excluded_never_vulnerable_task_ids": sorted(excluded, key=int),
        "retention_reason_by_task": dict(
            sorted(reason_by_task.items(), key=lambda item: int(item[0]))
        ),
        "rounds": {
            "first_sha256": canonical_json_sha256(first_round),
            "second_sha256": canonical_json_sha256(second_round),
            "first_evidence_sha256": first_round["screening_evidence_sha256"],
            "second_evidence_sha256": second_round["screening_evidence_sha256"],
        },
        "contract": {
            field: first_round[field] for field in contract_fields
        },
    }


def _refresh_derived_fields(payload: dict[str, Any]) -> None:
    rows = payload["mappings"]
    frequency = Counter(
        rule for row in rows for rule in row.get("rules_retrieved", [])
    )
    payload["rule_frequency"] = dict(sorted(frequency.items()))
    metadata = payload.setdefault("metadata", {})
    metadata["total_prompts"] = len(rows)
    metadata["empty_prompts"] = sum(
        not row.get("rules_retrieved") for row in rows
    )
    metadata["unique_rules_used"] = len(frequency)
    total_rules = sum(len(row.get("rules_retrieved", [])) for row in rows)
    metadata["avg_rules_per_prompt"] = (
        round(total_rules / len(rows), 3) if rows else 0.0
    )


def filter_second_round_candidates(
    payload: dict[str, Any],
    *,
    first_round: dict[str, Any],
    report_path: Path,
) -> dict[str, Any]:
    """Materialize only the all-valid-zero tasks requiring the second seed block."""
    if first_round.get("artifact_type") != "population_screening_round":
        raise ValueError("first-round report has the wrong artifact_type")
    if first_round.get("stage") != "first":
        raise ValueError("candidate filtering requires a first-round report")
    rows = _map_rows(payload, Path("screening source map"))
    candidates = set(first_round["task_ids"]["second_round_candidate"])
    source_ids = {str(row["index"]) for row in rows}
    if not candidates <= source_ids:
        raise ValueError("first-round candidates contain tasks absent from the map")
    selected = [row for row in rows if str(row["index"]) in candidates]
    if len(selected) != len(candidates):
        raise ValueError("candidate map did not materialize every first-round task")

    result = json.loads(json.dumps(payload))
    result["artifact_type"] = "screening_second_round_map"
    result["mappings"] = selected
    metadata = result.setdefault("metadata", {})
    metadata["population_screening_candidate_selection"] = {
        "evidence_status": "screening",
        "policy": SCREENING_POLICY,
        "source_population_total": len(rows),
        "second_round_population_total": len(selected),
        "second_round_population_fingerprint": population_fingerprint(selected),
        "first_round_report": {
            "filename": report_path.name,
            "sha256": sha256_file(report_path),
            "screening_evidence_sha256": first_round[
                "screening_evidence_sha256"
            ],
        },
    }
    _refresh_derived_fields(result)
    return result


def filter_screened_map(
    payload: dict[str, Any],
    *,
    screening_manifest: dict[str, Any],
    manifest_path: Path,
) -> dict[str, Any]:
    """Physically freeze the retained screening population in a map."""
    rows = payload.get("mappings")
    if not isinstance(rows, list):
        raise ValueError("screening source map lacks mappings")
    if screening_manifest.get("artifact_type") != "population_screening_manifest":
        raise ValueError("screening manifest has the wrong artifact_type")
    if screening_manifest.get("evidence_status") != "final":
        raise ValueError("screening manifest is not final")
    if screening_manifest.get("policy") != SCREENING_POLICY:
        raise ValueError("screening manifest has the wrong policy")
    language = screening_manifest.get("language")
    if any(str(row.get("language", "")).lower() != language for row in rows):
        raise ValueError("screening source map contains the wrong language")
    if len(rows) != screening_manifest.get("source_population_total"):
        raise ValueError("screening source map task count differs from the manifest")
    if population_fingerprint(rows) != screening_manifest.get(
        "source_population_fingerprint"
    ):
        raise ValueError(
            "screening source map population fingerprint differs from the manifest"
        )
    retained = set(screening_manifest["retained_task_ids"])
    source_ids = {str(row["index"]) for row in rows}
    if not retained <= source_ids:
        raise ValueError("screening manifest contains tasks absent from the map")
    selected = [row for row in rows if str(row["index"]) in retained]
    result = json.loads(json.dumps(payload))
    result["artifact_type"] = "screened_population_map"
    result["mappings"] = selected
    metadata = result.setdefault("metadata", {})
    metadata["population_screening"] = {
        "evidence_status": "final",
        "policy": SCREENING_POLICY,
        "source_population_total": len(rows),
        "screened_population_total": len(selected),
        "screened_population_fingerprint": population_fingerprint(selected),
        "excluded_never_vulnerable_task_ids": screening_manifest[
            "excluded_never_vulnerable_task_ids"
        ],
        "manifest": {
            "filename": manifest_path.name,
            "sha256": sha256_file(manifest_path),
        },
    }
    _refresh_derived_fields(result)
    return result


def combine_screened_language_maps(
    python_map: dict[str, Any],
    java_map: dict[str, Any],
    *,
    model: str,
) -> dict[str, Any]:
    """Combine disjoint final language maps without weakening their evidence."""
    if model not in {*SCREENING_MODELS, "norules"}:
        raise ValueError(f"unknown combined-map model {model!r}")
    for language, payload in (
        ("python", python_map),
        ("java", java_map),
    ):
        if payload.get("artifact_type") != "screened_population_map":
            raise ValueError(f"{language} map is not a screened population map")
        metadata = payload.get("metadata")
        if not isinstance(metadata, dict):
            raise ValueError(f"{language} screened map lacks metadata")
        screening = metadata.get("population_screening")
        if (
            not isinstance(screening, dict)
            or screening.get("evidence_status") != "final"
            or screening.get("policy") != SCREENING_POLICY
        ):
            raise ValueError(f"{language} map lacks final screening evidence")
        eligibility = metadata.get("population_eligibility")
        if (
            not isinstance(eligibility, dict)
            or eligibility.get("evidence_status") != "final"
            or eligibility.get("policy") != ELIGIBILITY_POLICY
        ):
            raise ValueError(f"{language} map lacks final eligibility evidence")
        if model in SCREENING_MODELS and metadata.get("model_key") != model:
            raise ValueError(f"{language} map does not belong to model {model}")
    python_rows = _map_rows(python_map, Path("Python screened map"))
    java_rows = _map_rows(java_map, Path("Java screened map"))
    for language, payload, rows in (
        ("python", python_map, python_rows),
        ("java", java_map, java_rows),
    ):
        screening = payload["metadata"]["population_screening"]
        if screening.get("screened_population_total") != len(rows):
            raise ValueError(f"{language} screened-map count does not reconcile")
        if screening.get("screened_population_fingerprint") != population_fingerprint(
            rows
        ):
            raise ValueError(
                f"{language} screened-map population fingerprint does not reconcile"
            )
    if any(str(row.get("language", "")).lower() != "python" for row in python_rows):
        raise ValueError("Python screened map contains a non-Python task")
    if any(str(row.get("language", "")).lower() != "java" for row in java_rows):
        raise ValueError("Java screened map contains a non-Java task")
    all_rows = python_rows + java_rows
    identities = [task_identity(row) for row in all_rows]
    if len(identities) != len(set(identities)):
        raise ValueError("screened language maps overlap")
    if model == "norules" and any(
        row.get("rules_retrieved") for row in all_rows
    ):
        raise ValueError("no-rules screened maps contain mapped rules")

    result = json.loads(json.dumps(python_map))
    result["artifact_type"] = "screened_population_map"
    result["mappings"] = json.loads(json.dumps(all_rows))
    result["metadata"] = {
        "evidence_status": "final",
        "model": model,
        "model_key": model if model in SCREENING_MODELS else None,
        "languages": {
            "python": len(python_rows),
            "java": len(java_rows),
        },
        "population_eligibility": {
            "evidence_status": "final",
            "policy": ELIGIBILITY_POLICY,
            "language_evidence": {
                "python": python_map["metadata"]["population_eligibility"],
                "java": java_map["metadata"]["population_eligibility"],
            },
        },
        "population_screening": {
            "evidence_status": "final",
            "policy": SCREENING_POLICY,
            "screened_population_total": len(all_rows),
            "screened_population_fingerprint": population_fingerprint(all_rows),
            "language_evidence": {
                "python": python_map.get("metadata", {}).get(
                    "population_screening"
                ),
                "java": java_map.get("metadata", {}).get(
                    "population_screening"
                ),
            },
        },
    }
    _refresh_derived_fields(result)
    return result
