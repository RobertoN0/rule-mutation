#!/usr/bin/env python3
"""Freeze the shared Qwen/Llama temperature-zero-valid search population."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from src.evaluation.generation_contract import (  # noqa: E402
    PROMPT_PROFILES,
    prompt_contract_sha256,
)

MODEL_IDS = {
    "qwen": "Qwen/Qwen2.5-Coder-32B-Instruct",
    "llama": "meta-llama/Llama-3.3-70B-Instruct",
}
LANGUAGES = ("python", "java")
MODELS = ("qwen", "llama")


@dataclass(frozen=True)
class QualificationInput:
    model: str
    language: str
    manifest_path: Path
    manifest: dict[str, Any]
    run_config: dict[str, Any]


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_file(path: Path) -> str:
    return _sha256_bytes(path.read_bytes())


def _population_fingerprint(mappings: list[dict[str, Any]]) -> str:
    identity = [
        {
            "test_case_id": str(row["index"]),
            "analysis_language": str(row["language"]).lower(),
            "prompt_hash": row.get("prompt_hash"),
        }
        for row in mappings
    ]
    encoded = json.dumps(identity, sort_keys=True, separators=(",", ":")).encode()
    return _sha256_bytes(encoded)


def _load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path}: expected a JSON object")
    return payload


def _load_source_map(path: Path) -> dict[str, Any]:
    payload = _load_json(path)
    mappings = payload.get("mappings")
    if not isinstance(mappings, list):
        raise ValueError(f"{path}: mappings must be a list")
    ids = [str(row.get("index")) for row in mappings]
    if len(ids) != len(set(ids)):
        raise ValueError(f"{path}: duplicate task IDs")
    return payload


def _task_identities(payload: dict[str, Any]) -> dict[str, tuple[Any, ...]]:
    return {
        str(row["index"]): (
            row.get("prompt_hash"),
            row.get("prompt"),
            row.get("cwe_id"),
            str(row.get("language", "")).lower(),
        )
        for row in payload["mappings"]
    }


def _load_qualification(
    manifest_path: Path,
    *,
    model: str,
    language: str,
    source_map_path: Path,
    source_map: dict[str, Any],
) -> QualificationInput:
    manifest = _load_json(manifest_path)
    run_config_path = manifest_path.parent / "run_config.json"
    if not run_config_path.exists():
        raise ValueError(f"{manifest_path}: sibling run_config.json is required")
    run_config = _load_json(run_config_path)
    validation_path = manifest_path.parent / "qualification_validation.json"
    if not validation_path.exists():
        raise ValueError(
            f"{manifest_path}: run validate_qualification_run.py --write before materializing maps"
        )
    validation = _load_json(validation_path)
    if validation.get("status") != "VALID":
        raise ValueError(f"{validation_path}: qualification validation is not VALID")
    if validation.get("artifact_type") != "qualification_validation":
        raise ValueError(f"{validation_path}: wrong validation artifact_type")
    if validation.get("manifest_sha256") != _sha256_file(manifest_path):
        raise ValueError(f"{validation_path}: validation does not cover the current manifest")
    artifact_paths = {
        "run_config": run_config_path,
        "qualification_manifest": manifest_path,
        "qualification_generations": manifest_path.parent / "qualification_generations.jsonl",
        "qualification_tasks": (
            manifest_path.parent / "intermediate" / "qualification_tasks.jsonl"
        ),
        "semgrep_debug": manifest_path.parent / "semgrep_debug" / "semgrep_debug.jsonl",
        "evaluation_failures": manifest_path.parent / "evaluation_failures.jsonl",
    }
    recorded_artifacts = validation.get("artifact_sha256")
    if not isinstance(recorded_artifacts, dict):
        raise ValueError(f"{validation_path}: validation lacks artifact fingerprints")
    for name, path in artifact_paths.items():
        actual = _sha256_file(path) if path.is_file() else None
        if recorded_artifacts.get(name) != actual:
            raise ValueError(f"{validation_path}: stale validation for {name}")
    args = run_config.get("args", {})

    if run_config.get("artifact_type") != "qualification_run_config":
        raise ValueError(f"{run_config_path}: wrong artifact_type")
    if manifest.get("status") != "COMPLETE":
        raise ValueError(f"{manifest_path}: qualification is not complete")
    if manifest.get("artifact_type") != "qualification_manifest":
        raise ValueError(f"{manifest_path}: wrong artifact_type")
    if manifest.get("mode") != "qualification":
        raise ValueError(f"{manifest_path}: wrong manifest mode")
    if manifest.get("temperature") != 0.0 or args.get("temperature") != 0.0:
        raise ValueError(f"{manifest_path}: qualification must use temperature 0")
    if manifest.get("analysis_languages") != [language]:
        raise ValueError(
            f"{manifest_path}: expected exactly analysis language {language!r}"
        )
    if args.get("run_mode") != "qualification":
        raise ValueError(f"{run_config_path}: run_mode is not qualification")
    if args.get("backend") != "delftblue" or args.get("dry_run"):
        raise ValueError(f"{run_config_path}: final qualification must run on DelftBlue")
    if re.fullmatch(
        r"[0-9a-fA-F]{40}",
        str(args.get("model_revision", "")),
    ) is None:
        raise ValueError(f"{run_config_path}: exact model revision is missing")
    for field in ("torch_version", "transformers_version"):
        if not isinstance(args.get(field), str) or not args[field]:
            raise ValueError(f"{run_config_path}: {field} is missing")
    prompt_profile = args.get("prompt_profile")
    if prompt_profile not in PROMPT_PROFILES:
        raise ValueError(f"{run_config_path}: unknown prompt profile {prompt_profile!r}")
    prompt_hash = prompt_contract_sha256(prompt_profile)
    if args.get("prompt_contract_sha256") != prompt_hash:
        raise ValueError(f"{run_config_path}: prompt-contract hash mismatch")
    if manifest.get("prompt_profile") != prompt_profile:
        raise ValueError(f"{manifest_path}: prompt profile differs from run_config")
    if manifest.get("prompt_contract_sha256") != prompt_hash:
        raise ValueError(f"{manifest_path}: prompt-contract hash mismatch")
    if args.get("max_output_tokens") != 4096:
        raise ValueError(f"{run_config_path}: max_output_tokens must be 4096")
    if args.get("model") != MODEL_IDS[model] or manifest.get("model") != MODEL_IDS[model]:
        raise ValueError(f"{manifest_path}: model identity does not match {model}")
    if args.get("rules_map_sha256") != _sha256_file(source_map_path):
        raise ValueError(f"{run_config_path}: source-map hash mismatch")
    source_commit = args.get("semgrep_rules_source_commit")
    if not isinstance(source_commit, str) or re.fullmatch(r"[0-9a-fA-F]{40}", source_commit) is None:
        raise ValueError(
            f"{run_config_path}: final qualification requires a pinned Semgrep SOURCE_COMMIT"
        )
    rules_hash = args.get("semgrep_rules_sha256")
    if not isinstance(rules_hash, str) or re.fullmatch(r"[0-9a-f]{64}", rules_hash) is None:
        raise ValueError(f"{run_config_path}: invalid Semgrep rule-content hash")
    if args.get("semgrep_version") != "1.85.0":
        raise ValueError(f"{run_config_path}: Semgrep version is not 1.85.0")

    mappings = source_map["mappings"]
    source_ids = {str(row["index"]) for row in mappings}
    if manifest.get("total_prompts") != len(mappings):
        raise ValueError(f"{manifest_path}: prompt count differs from source map")
    valid_ids = [str(task_id) for task_id in manifest.get("valid_task_ids", [])]
    if len(valid_ids) != len(set(valid_ids)) or not set(valid_ids) <= source_ids:
        raise ValueError(f"{manifest_path}: invalid or duplicate valid_task_ids")
    excluded_ids = {str(row.get("test_case_id")) for row in manifest.get("excluded", [])}
    if set(valid_ids) | excluded_ids != source_ids or set(valid_ids) & excluded_ids:
        raise ValueError(f"{manifest_path}: valid/excluded partition does not cover source map")

    expected_valid = [row for row in mappings if str(row["index"]) in set(valid_ids)]
    if manifest.get("qualified_population_fingerprint") != _population_fingerprint(expected_valid):
        raise ValueError(f"{manifest_path}: qualified-population fingerprint mismatch")
    return QualificationInput(model, language, manifest_path, manifest, run_config)


def _reconcile_semgrep_provenance(inputs: list[QualificationInput]) -> dict[str, Any]:
    tuples = {
        (
            item.run_config["args"]["semgrep_rules_source_commit"],
            item.run_config["args"]["semgrep_rules_sha256"],
            item.run_config["args"]["semgrep_version"],
        )
        for item in inputs
    }
    if len(tuples) != 1:
        raise ValueError("all four qualifications must use identical Semgrep provenance")
    source_commit, rules_sha256, version = tuples.pop()
    git_commits = {item.run_config.get("git_commit_sha") for item in inputs}
    if len(git_commits) != 1 or not all(
        re.fullmatch(r"[0-9a-fA-F]{40}", str(value or ""))
        for value in git_commits
    ):
        raise ValueError("all four qualifications must use the same recorded code commit")
    software_versions = {
        (
            item.run_config["args"]["torch_version"],
            item.run_config["args"]["transformers_version"],
        )
        for item in inputs
    }
    if len(software_versions) != 1:
        raise ValueError("all four qualifications must use identical model-library versions")
    torch_version, transformers_version = software_versions.pop()
    prompt_contracts = {
        (
            item.run_config["args"]["prompt_profile"],
            item.run_config["args"]["prompt_contract_sha256"],
        )
        for item in inputs
    }
    if len(prompt_contracts) != 1:
        raise ValueError("all four qualifications must use the same prompt profile")
    prompt_profile, prompt_sha256 = prompt_contracts.pop()
    return {
        "semgrep_rules_source_commit": source_commit,
        "semgrep_rules_sha256": rules_sha256,
        "semgrep_version": version,
        "code_git_commit_sha": git_commits.pop(),
        "torch_version": torch_version,
        "transformers_version": transformers_version,
        "prompt_profile": prompt_profile,
        "prompt_contract_sha256": prompt_sha256,
    }


def _derived_fields(payload: dict[str, Any]) -> None:
    mappings = payload["mappings"]
    metadata = payload.setdefault("metadata", {})
    languages = Counter(str(row.get("language", "unknown")).lower() for row in mappings)
    rule_frequency = Counter(
        rule_id for row in mappings for rule_id in row.get("rules_retrieved", [])
    )
    metadata["total_prompts"] = len(mappings)
    if "distinct_prompts" in metadata:
        metadata["distinct_prompts"] = len(mappings)
    if len(languages) > 1 or "languages" in metadata:
        metadata["languages"] = dict(sorted(languages.items()))
    n_rules = sum(len(row.get("rules_retrieved", [])) for row in mappings)
    if "avg_rules_per_prompt" in metadata:
        metadata["avg_rules_per_prompt"] = round(n_rules / len(mappings), 3) if mappings else 0.0
    if "unique_rules_used" in metadata:
        metadata["unique_rules_used"] = len(rule_frequency)
    if "empty_prompts" in metadata:
        metadata["empty_prompts"] = sum(not row.get("rules_retrieved") for row in mappings)
    payload["rule_frequency"] = dict(sorted(rule_frequency.items()))


def _write_map(
    source: dict[str, Any],
    output_path: Path,
    allowed_ids: set[str],
    qualification: dict[str, Any],
    *,
    overwrite: bool,
) -> dict[str, Any]:
    if output_path.exists() and not overwrite:
        raise FileExistsError(f"refusing to overwrite {output_path}; pass --overwrite")
    payload = json.loads(json.dumps(source))
    payload["artifact_type"] = "qualified_rule_map"
    prior = payload.setdefault("metadata", {}).get("search_qualification")
    payload["mappings"] = [
        row for row in payload["mappings"] if str(row["index"]) in allowed_ids
    ]
    payload["metadata"]["retrieval_map_qualification"] = prior
    payload["metadata"]["search_qualification"] = qualification
    _derived_fields(payload)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return payload


def materialize(args: argparse.Namespace) -> dict[str, Any]:
    map_dir = args.map_dir
    output_dir = args.output_dir
    source_maps: dict[tuple[str, str], tuple[Path, dict[str, Any]]] = {}
    for model in MODELS:
        for language in LANGUAGES:
            path = map_dir / f"final_consensus_map_{model}_{language}.json"
            source_maps[(model, language)] = (path, _load_source_map(path))
    for language in LANGUAGES:
        qwen_rows = _task_identities(source_maps[("qwen", language)][1])
        llama_rows = _task_identities(source_maps[("llama", language)][1])
        if qwen_rows != llama_rows:
            raise ValueError(
                f"Qwen/Llama {language} source maps do not define the same task identities"
            )

    expected_combined_identities = {
        **_task_identities(source_maps[("qwen", "python")][1]),
        **_task_identities(source_maps[("qwen", "java")][1]),
    }
    for model in MODELS:
        combined_path = map_dir / f"final_consensus_map_{model}.json"
        combined = _load_source_map(combined_path)
        if _task_identities(combined) != expected_combined_identities:
            raise ValueError(
                f"{combined_path}: combined map task identities differ from language maps"
            )
    norules_source = _load_source_map(map_dir / "final_norules_map.json")
    if _task_identities(norules_source) != expected_combined_identities:
        raise ValueError("final_norules_map.json task identities differ from consensus maps")

    requested_manifests = {
        ("qwen", "python"): args.qwen_python_manifest,
        ("llama", "python"): args.llama_python_manifest,
        ("qwen", "java"): args.qwen_java_manifest,
        ("llama", "java"): args.llama_java_manifest,
    }
    inputs: dict[tuple[str, str], QualificationInput] = {}
    for key, manifest_path in requested_manifests.items():
        source_path, source_map = source_maps[key]
        inputs[key] = _load_qualification(
            manifest_path,
            model=key[0],
            language=key[1],
            source_map_path=source_path,
            source_map=source_map,
        )

    provenance = _reconcile_semgrep_provenance(list(inputs.values()))
    shared_ids: dict[str, set[str]] = {}
    exclusions: dict[str, dict[str, Any]] = {}
    for language in LANGUAGES:
        per_model_valid = {
            model: set(inputs[(model, language)].manifest["valid_task_ids"])
            for model in MODELS
        }
        shared_ids[language] = set.intersection(*per_model_valid.values())
        if not shared_ids[language]:
            raise ValueError(
                f"temperature-zero qualification left an empty shared {language} population"
            )
        source_ids = {
            str(row["index"])
            for row in source_maps[("qwen", language)][1]["mappings"]
        }
        for task_id in sorted(source_ids - shared_ids[language], key=int):
            model_status = {}
            for model in MODELS:
                excluded = {
                    str(row["test_case_id"]): row
                    for row in inputs[(model, language)].manifest["excluded"]
                }
                model_status[model] = excluded.get(task_id, {"status": "valid"})
            exclusions[task_id] = {
                "language": language,
                "reason": "not_valid_for_every_model_at_temperature_zero",
                "models": model_status,
            }

    qualification_inputs = {
        f"{model}_{language}": {
            "qualification_run": inputs[(model, language)].manifest_path.parent.name,
            "manifest_sha256": _sha256_file(inputs[(model, language)].manifest_path),
            "run_config_sha256": _sha256_file(
                inputs[(model, language)].manifest_path.parent / "run_config.json"
            ),
            "validation_sha256": _sha256_file(
                inputs[(model, language)].manifest_path.parent
                / "qualification_validation.json"
            ),
            "slurm_job_id": inputs[(model, language)].run_config.get("slurm_job_id"),
            "model_revision": inputs[(model, language)].run_config["args"][
                "model_revision"
            ],
            "valid_prompts": inputs[(model, language)].manifest["valid_prompts"],
            "excluded_prompts": inputs[(model, language)].manifest["excluded_prompts"],
        }
        for model in MODELS
        for language in LANGUAGES
    }
    output_payloads: dict[str, dict[str, Any]] = {}
    for model in MODELS:
        for language in LANGUAGES:
            source = source_maps[(model, language)][1]
            selected = [
                row for row in source["mappings"]
                if str(row["index"]) in shared_ids[language]
            ]
            fingerprint = _population_fingerprint(selected)
            qualification = {
                "evidence_status": "final",
                "policy": "frozen_cross_model_temp0_intersection",
                "temperature": 0.0,
                "source_population_total": len(source["mappings"]),
                "qualified_population_total": len(selected),
                "qualified_population_fingerprint": fingerprint,
                "excluded_task_ids": sorted(
                    {
                        str(row["index"]) for row in source["mappings"]
                    } - shared_ids[language],
                    key=int,
                ),
                "exclusions": {
                    task_id: detail
                    for task_id, detail in exclusions.items()
                    if detail["language"] == language
                },
                "qualification_inputs": qualification_inputs,
                **provenance,
            }
            name = f"final_search_map_{model}_{language}.json"
            output_payloads[name] = _write_map(
                source,
                output_dir / name,
                shared_ids[language],
                qualification,
                overwrite=args.overwrite,
            )

        combined_source = _load_source_map(map_dir / f"final_consensus_map_{model}.json")
        combined_ids = shared_ids["python"] | shared_ids["java"]
        selected = [
            row for row in combined_source["mappings"]
            if str(row["index"]) in combined_ids
        ]
        qualification = {
            "evidence_status": "final",
            "policy": "frozen_cross_model_temp0_intersection",
            "temperature": 0.0,
            "source_population_total": len(combined_source["mappings"]),
            "qualified_population_total": len(selected),
            "qualified_population_fingerprint": _population_fingerprint(selected),
            "language_counts": {
                language: len(shared_ids[language]) for language in LANGUAGES
            },
            "excluded_task_ids": sorted(exclusions, key=int),
            "exclusions": exclusions,
            "qualification_inputs": qualification_inputs,
            **provenance,
        }
        name = f"final_search_map_{model}.json"
        output_payloads[name] = _write_map(
            combined_source,
            output_dir / name,
            combined_ids,
            qualification,
            overwrite=args.overwrite,
        )

    for language in LANGUAGES:
        language_ids = shared_ids[language]
        language_selected = [
            row
            for row in norules_source["mappings"]
            if str(row["index"]) in language_ids
        ]
        language_qualification = {
            "evidence_status": "final",
            "policy": "frozen_cross_model_temp0_intersection",
            "temperature": 0.0,
            "source_population_total": sum(
                str(row.get("language", "")).lower() == language
                for row in norules_source["mappings"]
            ),
            "qualified_population_total": len(language_selected),
            "qualified_population_fingerprint": _population_fingerprint(
                language_selected
            ),
            "excluded_task_ids": sorted(
                {
                    task_id
                    for task_id, detail in exclusions.items()
                    if detail["language"] == language
                },
                key=int,
            ),
            "exclusions": {
                task_id: detail
                for task_id, detail in exclusions.items()
                if detail["language"] == language
            },
            "qualification_inputs": qualification_inputs,
            **provenance,
        }
        name = f"final_search_norules_map_{language}.json"
        output_payloads[name] = _write_map(
            norules_source,
            output_dir / name,
            language_ids,
            language_qualification,
            overwrite=args.overwrite,
        )

    all_shared = shared_ids["python"] | shared_ids["java"]
    norules_selected = [
        row for row in norules_source["mappings"] if str(row["index"]) in all_shared
    ]
    norules_qualification = {
        "evidence_status": "final",
        "policy": "frozen_cross_model_temp0_intersection",
        "temperature": 0.0,
        "source_population_total": len(norules_source["mappings"]),
        "qualified_population_total": len(norules_selected),
        "qualified_population_fingerprint": _population_fingerprint(norules_selected),
        "language_counts": {language: len(shared_ids[language]) for language in LANGUAGES},
        "excluded_task_ids": sorted(exclusions, key=int),
        "exclusions": exclusions,
        "qualification_inputs": qualification_inputs,
        **provenance,
    }
    output_payloads["final_search_norules_map.json"] = _write_map(
        norules_source,
        output_dir / "final_search_norules_map.json",
        all_shared,
        norules_qualification,
        overwrite=args.overwrite,
    )

    population_manifest = {
        "artifact_type": "qualified_population_manifest",
        "evidence_status": "final",
        "policy": "frozen_cross_model_temp0_intersection",
        "temperature": 0.0,
        "language_counts": {language: len(shared_ids[language]) for language in LANGUAGES},
        "task_ids": {
            language: sorted(shared_ids[language], key=int) for language in LANGUAGES
        },
        "exclusions": exclusions,
        "qualification_inputs": qualification_inputs,
        "outputs": {
            name: {
                "sha256": _sha256_file(output_dir / name),
                "prompts": len(payload["mappings"]),
                "population_fingerprint": payload["metadata"]["search_qualification"][
                    "qualified_population_fingerprint"
                ],
            }
            for name, payload in output_payloads.items()
        },
        **provenance,
    }
    manifest_path = output_dir / "final_search_population_manifest.json"
    if manifest_path.exists() and not args.overwrite:
        raise FileExistsError(f"refusing to overwrite {manifest_path}; pass --overwrite")
    manifest_path.write_text(json.dumps(population_manifest, indent=2) + "\n", encoding="utf-8")
    return population_manifest


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--qwen-python-manifest", type=Path, required=True)
    parser.add_argument("--llama-python-manifest", type=Path, required=True)
    parser.add_argument("--qwen-java-manifest", type=Path, required=True)
    parser.add_argument("--llama-java-manifest", type=Path, required=True)
    parser.add_argument("--map-dir", type=Path, default=PROJECT_ROOT / "rule_maps")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=PROJECT_ROOT / "rule_maps" / "qualified",
    )
    parser.add_argument("--overwrite", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    manifest = materialize(args)
    print(
        "Frozen shared population: "
        + ", ".join(
            f"{language}={count}"
            for language, count in manifest["language_counts"].items()
        )
    )
    print(f"Maps and manifest written to {args.output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
