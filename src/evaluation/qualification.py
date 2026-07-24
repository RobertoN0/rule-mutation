"""Temperature-zero qualification for a frozen search population."""

from __future__ import annotations

import hashlib
import json
import time
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from .fitness import calculate_fitness
from .generation_contract import (
    DEFAULT_PROMPT_PROFILE,
    build_code_generation_system_prompt,
    prompt_contract_sha256,
)
from .output_validation import (
    SUPPORTED_ANALYSIS_LANGUAGES,
    normalize_language,
    validate_generated_output,
)
from .rule_mapping import PromptWithRules
from .semgrep_runner import SemgrepSample, run_semgrep_batch_dir


class QualificationInfrastructureError(RuntimeError):
    """A model/scanner/configuration failure that prevents qualification."""


@dataclass(frozen=True)
class QualificationSummary:
    total_prompts: int
    valid_prompts: int
    excluded_prompts: int
    population_fingerprint: str
    prompt_profile: str
    prompt_contract_sha256: str
    manifest_path: Path | None
    rows: tuple[dict[str, Any], ...]


def population_fingerprint(rows: list[dict[str, Any]]) -> str:
    """Hash the ordered task/language/prompt identity contract."""
    identity = [
        {
            "test_case_id": str(row["test_case_id"]),
            "analysis_language": row["analysis_language"],
            "prompt_hash": row.get("prompt_hash"),
        }
        for row in rows
    ]
    payload = json.dumps(identity, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _append_jsonl(path: Path, row: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row) + "\n")


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row) + "\n")


def qualify_search_population(
    llm_backend,
    prompts_with_rules: list[PromptWithRules],
    *,
    output_dir: Path | None,
    temperature: float = 0.0,
    require_temperature_zero: bool = True,
    model_id: str | None = None,
    prompt_profile: str = DEFAULT_PROMPT_PROFILE,
    should_stop_fn: Callable[[], bool] | None = None,
    verbose: bool = True,
) -> QualificationSummary:
    """Generate, validate, and scan every origin prompt without starting search.

    Invalid task outputs are explicit exclusions, not zero findings and not
    fatal errors. Infrastructure failures remain fatal. The returned valid task
    set is model-specific; a separate materialization step intersects both
    models for the language before any final search map is produced.
    """
    if not prompts_with_rules:
        raise ValueError("No prompts were supplied for qualification")
    if require_temperature_zero and temperature != 0.0:
        raise ValueError("Qualification requires deterministic temperature=0")
    if not require_temperature_zero and output_dir is not None:
        raise ValueError("stochastic origin evaluation must use caller-managed artifacts")
    contract_sha256 = prompt_contract_sha256(prompt_profile)

    task_ids = [
        str(prompt.metadata.get("test_case_id", f"case_{idx}"))
        for idx, prompt in enumerate(prompts_with_rules)
    ]
    duplicates = sorted(task_id for task_id, n in Counter(task_ids).items() if n > 1)
    if duplicates:
        raise ValueError(f"Duplicate test_case_id values are not allowed: {duplicates[:3]}")

    unsupported = []
    for idx, prompt in enumerate(prompts_with_rules):
        language = normalize_language(prompt.language)
        if language not in SUPPORTED_ANALYSIS_LANGUAGES:
            unsupported.append(f"TC#{task_ids[idx]}: {language!r}")
    if unsupported:
        raise ValueError(
            "Qualification map contains unsupported languages; no model calls were made: "
            + ", ".join(unsupported[:10])
        )

    generation_log = (
        output_dir / "qualification_generations.jsonl" if output_dir is not None else None
    )
    intermediate_path = (
        output_dir / "intermediate" / "qualification_tasks.jsonl"
        if output_dir is not None else None
    )
    failures_path = output_dir / "evaluation_failures.jsonl" if output_dir is not None else None
    for path in (generation_log, intermediate_path):
        if path is not None and path.exists():
            raise FileExistsError(
                f"qualification output already exists; use a fresh output directory: {path}"
            )

    generated: list[dict[str, Any]] = []
    semgrep_samples: list[SemgrepSample] = []
    total_input_tokens = 0
    total_output_tokens = 0
    started = time.perf_counter()

    for idx, prompt in enumerate(prompts_with_rules):
        if should_stop_fn is not None and should_stop_fn():
            raise QualificationInfrastructureError(
                f"qualification interrupted after {idx}/{len(prompts_with_rules)} prompts"
            )
        task_id = task_ids[idx]
        language = normalize_language(prompt.language)
        assert language is not None
        system = build_code_generation_system_prompt(
            prompt.combined_rules or None,
            language,
            profile=prompt_profile,
        )
        try:
            response = llm_backend.generate(
                system=system,
                messages=[{"role": "user", "content": prompt.prompt}],
            )
        except Exception as exc:
            if failures_path is not None:
                _append_jsonl(
                    failures_path,
                    {
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "artifact_type": "evaluation_failure",
                        "iter_id": "qualification",
                        "stage": "generation",
                        "error_kind": type(exc).__name__,
                        "test_case_id": task_id,
                        "message": str(exc),
                        "fatal": True,
                    },
                )
            raise QualificationInfrastructureError(
                f"generation failed for TC#{task_id}: {exc}"
            ) from exc

        raw_code = response.content
        finish_reason = getattr(response, "finish_reason", "unknown") or "unknown"
        validation = validate_generated_output(
            raw_code,
            expected_language=language,
            finish_reason=finish_reason,
        )
        input_tokens = int(getattr(response, "input_tokens", 0) or 0)
        output_tokens = int(getattr(response, "output_tokens", 0) or 0)
        total_input_tokens += input_tokens
        total_output_tokens += output_tokens
        generation_row = {
            "artifact_type": "qualification_generation",
            "index": idx,
            "test_case_id": task_id,
            "analysis_language": language,
            "prompt_hash": prompt.metadata.get("prompt_hash"),
            "cwe_id": prompt.cwe_id,
            "original_rule_ids": list(prompt.rule_ids),
            "prompt_profile": prompt_profile,
            "system_prompt_sha256": _sha256(system),
            "finish_reason": finish_reason,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "generation_latency_ms": float(getattr(response, "latency_ms", 0.0) or 0.0),
            "generated_code": raw_code,
            "source_code_sha256": _sha256(validation.source_code),
            "analyzed_code_sha256": _sha256(validation.code),
            "output_validation": {
                "status": validation.status,
                "failure_reason": validation.failure_reason,
                "syntax_error": validation.syntax_error,
                "syntax_validation_method": validation.syntax_validation_method,
                "expected_language": validation.expected_language,
                "detected_language": validation.detected_language,
                "fence_languages": validation.fence_languages,
                "ignored_supplementary_languages": (
                    validation.ignored_supplementary_languages
                ),
                "has_fences": validation.has_fences,
                "outside_text_present": validation.outside_text_present,
                "target_block_count": validation.target_block_count,
                "normalization": validation.normalization,
                "analysis_line_map": validation.analysis_line_map,
            },
            "_validation": validation,
        }
        generated.append(generation_row)
        if generation_log is not None:
            durable_row = {key: value for key, value in generation_row.items() if key != "_validation"}
            _append_jsonl(generation_log, durable_row)
        semgrep_samples.append(
            SemgrepSample(
                code_raw=raw_code,
                code_analyzed=validation.code,
                language=language,
                precheck_error=(
                    validation.failure_reason if not validation.is_valid else None
                ),
                precheck_error_kind=validation.status,
                normalization=validation.normalization,
                analysis_line_map=tuple(validation.analysis_line_map),
            )
        )
        if verbose and (idx + 1) % 25 == 0:
            print(f"   Qualified generation {idx + 1}/{len(prompts_with_rules)}", flush=True)

    semgrep_started = time.perf_counter()
    semgrep_results = run_semgrep_batch_dir(semgrep_samples)
    transient_kinds = {"timeout", "process", "json", "unexpected"}
    if any(result.error_kind in transient_kinds for result in semgrep_results):
        if verbose:
            print("   Transient Semgrep failure; retrying qualification batch once", flush=True)
        semgrep_results = run_semgrep_batch_dir(semgrep_samples)
    if len(semgrep_results) != len(semgrep_samples):
        raise QualificationInfrastructureError(
            "Semgrep qualification result count does not match submitted prompt count"
        )
    for idx, result in enumerate(semgrep_results):
        if result.is_system_error:
            task_id = task_ids[idx]
            if failures_path is not None:
                _append_jsonl(
                    failures_path,
                    {
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "artifact_type": "evaluation_failure",
                        "iter_id": "qualification",
                        "stage": "semgrep",
                        "error_kind": result.error_kind or "unknown",
                        "test_case_id": task_id,
                        "message": result.error or "unknown Semgrep error",
                        "fatal": True,
                    },
                )
            raise QualificationInfrastructureError(
                f"Semgrep evaluator failure for TC#{task_id} "
                f"({result.error_kind}): {result.error}"
            )

    per_scanned_sample_ms = (
        (time.perf_counter() - semgrep_started) * 1000
        / max(sum(sample.precheck_error is None for sample in semgrep_samples), 1)
    )
    rows: list[dict[str, Any]] = []
    exclusion_counts: Counter[str] = Counter()
    for idx, (generation, semgrep_result) in enumerate(zip(generated, semgrep_results)):
        validation = generation.pop("_validation")
        status = validation.status
        reason = validation.failure_reason
        partial_findings = []
        if validation.is_valid and semgrep_result.error_kind in {
            "target_parse",
            "target_analysis",
        }:
            status = (
                "semgrep_parse_error"
                if semgrep_result.error_kind == "target_parse"
                else "semgrep_target_error"
            )
            reason = semgrep_result.error
            partial_findings = [
                {
                    "check_id": finding.check_id,
                    "severity": finding.severity,
                    "line": finding.line,
                    "analyzed_line": finding.analyzed_line,
                }
                for finding in semgrep_result.findings
            ]

        fitness = None
        if status == "valid" and semgrep_result.error is None:
            fitness = calculate_fitness(semgrep_result)
        else:
            exclusion_counts[status] += 1
            if failures_path is not None:
                _append_jsonl(
                    failures_path,
                    {
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "artifact_type": "evaluation_failure",
                        "iter_id": "qualification",
                        "stage": "task_qualification",
                        "error_kind": status,
                        "test_case_id": generation["test_case_id"],
                        "message": reason,
                        "fatal": False,
                        "details": {
                            "finish_reason": generation["finish_reason"],
                            "source_code_sha256": generation["source_code_sha256"],
                            "analyzed_code_sha256": generation["analyzed_code_sha256"],
                            "partial_findings": partial_findings,
                        },
                    },
                )

        row = {
            **generation,
            "artifact_type": "qualification_task_evaluation",
            "qualification_status": status,
            "exclusion_reason": reason,
            "analysis_latency_ms": (
                per_scanned_sample_ms if semgrep_samples[idx].precheck_error is None else 0.0
            ),
            "fitness": (
                {
                    "raw_count": fitness.raw_count,
                    "weighted_score": fitness.weighted_score,
                    "error_count": fitness.error_count,
                    "warning_count": fitness.warning_count,
                    "check_ids": fitness.details.get("check_ids", []),
                    "synthetic_findings_filtered": fitness.details.get(
                        "synthetic_findings_filtered", 0
                    ),
                }
                if fitness is not None else None
            ),
            "partial_findings": partial_findings,
        }
        rows.append(row)

    if intermediate_path is not None:
        _write_jsonl(intermediate_path, rows)

    valid_rows = [row for row in rows if row["qualification_status"] == "valid"]
    fingerprint = population_fingerprint(valid_rows)
    manifest_path = output_dir / "qualification_manifest.json" if output_dir is not None else None
    if manifest_path is not None:
        manifest = {
            "artifact_type": "qualification_manifest",
            "mode": "qualification",
            "status": "COMPLETE",
            "qualification_policy": "task_exclusion_then_cross_model_intersection",
            "model": model_id or getattr(llm_backend, "model_name", None),
            "provider": getattr(llm_backend, "provider_name", None),
            "temperature": temperature,
            "prompt_profile": prompt_profile,
            "prompt_contract_sha256": contract_sha256,
            "analysis_languages": sorted({row["analysis_language"] for row in rows}),
            "total_prompts": len(rows),
            "valid_prompts": len(valid_rows),
            "excluded_prompts": len(rows) - len(valid_rows),
            "exclusion_counts": dict(sorted(exclusion_counts.items())),
            "valid_task_ids": [row["test_case_id"] for row in valid_rows],
            "excluded": [
                {
                    "test_case_id": row["test_case_id"],
                    "analysis_language": row["analysis_language"],
                    "status": row["qualification_status"],
                    "reason": row["exclusion_reason"],
                    "finish_reason": row["finish_reason"],
                }
                for row in rows
                if row["qualification_status"] != "valid"
            ],
            "qualified_population_fingerprint": fingerprint,
            "total_llm_calls": len(rows),
            "total_input_tokens": total_input_tokens,
            "total_output_tokens": total_output_tokens,
            "total_time_seconds": time.perf_counter() - started,
            "intermediate_file": "intermediate/qualification_tasks.jsonl",
        }
        manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

    return QualificationSummary(
        total_prompts=len(rows),
        valid_prompts=len(valid_rows),
        excluded_prompts=len(rows) - len(valid_rows),
        population_fingerprint=fingerprint,
        prompt_profile=prompt_profile,
        prompt_contract_sha256=contract_sha256,
        manifest_path=manifest_path,
        rows=tuple(rows),
    )
