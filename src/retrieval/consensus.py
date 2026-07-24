"""Validation and deterministic materialization of retrieval consensus maps."""

from __future__ import annotations

import hashlib
import json
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Sequence

from src.evaluation.rule_mapping import compute_prompt_hash


MODEL_IDS = {
    "qwen": "Qwen/Qwen2.5-Coder-32B-Instruct",
    "llama": "meta-llama/Llama-3.3-70B-Instruct",
}
MODEL_QUANTIZATION = {"qwen": "fp16", "llama": "4bit"}
MODEL_COMPUTE_DTYPE = {"qwen": None, "llama": "bfloat16"}
RETRIEVAL_MAX_TOKENS = 1024
RETRIEVAL_TEMPERATURE = 0.6
RETRIEVAL_TEMPLATE = "v2_reframed_user_turn"
RETRIEVAL_REPETITIONS = 20
CONSENSUS_MIN_SELECTIONS = 11
VALID_PARSE_METHODS = {"json", "regex_fallback"}


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def canonical_json_sha256(payload: Any) -> str:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode()
    return sha256_bytes(encoded)


def load_json_object(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path}: expected a JSON object")
    return payload


def load_rule_ids(rules_dir: Path) -> set[str]:
    rule_ids = {path.stem for path in rules_dir.glob("*.md") if path.is_file()}
    if not rule_ids:
        raise ValueError(f"{rules_dir}: no CodeGuard rule files found")
    return rule_ids


def task_identity(row: dict[str, Any]) -> tuple[str, str, str]:
    return (
        str(row.get("index")),
        str(row.get("language", "")).lower(),
        str(row.get("prompt_hash", "")),
    )


def task_content_identity(row: dict[str, Any]) -> tuple[str, str, str, str]:
    return (
        str(row.get("language", "")).lower(),
        str(row.get("prompt_hash", "")),
        str(row.get("cwe_id", "")),
        str(row.get("prompt", "")),
    )


def _mappings(payload: dict[str, Any], path: Path | None = None) -> list[dict[str, Any]]:
    rows = payload.get("mappings")
    label = str(path) if path is not None else "payload"
    if not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows):
        raise ValueError(f"{label}: mappings must be a list of objects")
    return rows


def _metadata_seed(payload: dict[str, Any], path: Path) -> int:
    seed = payload.get("metadata", {}).get("seed")
    if not isinstance(seed, int):
        raise ValueError(f"{path}: metadata.seed must be an integer")
    return seed


@dataclass(frozen=True)
class RetrievalMapEvidence:
    path: Path
    payload: dict[str, Any]
    seed: int
    sha256: str


@dataclass(frozen=True)
class RetrievalSweepEvidence:
    model: str
    language: str
    carrier_path: Path
    carrier: dict[str, Any]
    accepted_seeds: tuple[int, ...]
    maps: tuple[RetrievalMapEvidence, ...]
    validation_report: dict[str, Any]


def validate_retrieval_map(
    path: Path,
    *,
    carrier: dict[str, Any],
    model: str,
    language: str,
    expected_seed: int,
    valid_rule_ids: set[str],
) -> dict[str, Any]:
    """Validate one retrieval draw without treating parse failure as zero rules."""
    issues: list[str] = []
    try:
        payload = load_json_object(path)
        rows = _mappings(payload, path)
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        return {
            "artifact_type": "retrieval_map_validation",
            "status": "INVALID",
            "path": path.name,
            "issues": [str(exc)],
        }

    carrier_rows = _mappings(carrier)
    expected_identities = [task_identity(row) for row in carrier_rows]
    actual_identities = [task_identity(row) for row in rows]
    if actual_identities != expected_identities:
        issues.append("mapping identities/order differ from the input carrier")
    if len(actual_identities) != len(set(actual_identities)):
        issues.append("mapping contains duplicate canonical identities")

    metadata = payload.get("metadata")
    if not isinstance(metadata, dict):
        metadata = {}
        issues.append("metadata must be an object")
    model_config = metadata.get("model_config")
    if not isinstance(model_config, dict):
        model_config = {}
        issues.append("metadata.model_config must be an object")
    if model not in MODEL_IDS:
        issues.append(f"unknown model key {model!r}")
    elif metadata.get("model") != MODEL_IDS[model]:
        issues.append("metadata.model differs from the expected model")
    if metadata.get("seed") != expected_seed:
        issues.append("metadata.seed differs from the accepted seed")
    if metadata.get("temperature") != RETRIEVAL_TEMPERATURE:
        issues.append("metadata.temperature is not 0.6")
    if metadata.get("prompt_template_version") != RETRIEVAL_TEMPLATE:
        issues.append("retrieval prompt-template version is not the frozen template")
    if metadata.get("total_prompts") != len(rows):
        issues.append("metadata.total_prompts differs from the mapping count")
    if model_config.get("model") != MODEL_IDS.get(model):
        issues.append("model_config.model differs from the expected model")
    if model_config.get("seed") != expected_seed:
        issues.append("model_config.seed differs from the accepted seed")
    if model_config.get("temperature") != RETRIEVAL_TEMPERATURE:
        issues.append("model_config.temperature is not 0.6")
    quantization = model_config.get("quantization")
    if quantization != MODEL_QUANTIZATION.get(model):
        issues.append("model_config.quantization differs from the frozen contract")
    if model_config.get("bnb_4bit_compute_dtype") != MODEL_COMPUTE_DTYPE.get(model):
        issues.append(
            "model_config.bnb_4bit_compute_dtype differs from the frozen contract"
        )
    if model_config.get("max_tokens") != RETRIEVAL_MAX_TOKENS:
        issues.append("model_config.max_tokens differs from the frozen contract")

    expected_language = language.lower()
    parse_counts: Counter[str] = Counter()
    for position, row in enumerate(rows):
        task_label = f"position {position} / task {row.get('index')}"
        if position < len(carrier_rows):
            source = carrier_rows[position]
            for field in ("cwe_id", "language", "prompt_hash", "prompt"):
                if row.get(field) != source.get(field):
                    issues.append(f"{task_label}: {field} differs from the carrier")
        if str(row.get("language", "")).lower() != expected_language:
            issues.append(f"{task_label}: language differs from {expected_language}")
        prompt = row.get("prompt")
        if not isinstance(prompt, str) or not prompt:
            issues.append(f"{task_label}: prompt is missing")
        elif row.get("prompt_hash") != compute_prompt_hash(prompt):
            issues.append(f"{task_label}: prompt_hash does not match prompt text")
        rules = row.get("rules_retrieved")
        if not isinstance(rules, list) or not all(isinstance(rule, str) for rule in rules):
            issues.append(f"{task_label}: rules_retrieved must be a list of strings")
            rules = []
        if len(rules) != len(set(rules)):
            issues.append(f"{task_label}: rules_retrieved contains duplicates")
        unknown = sorted(set(rules) - valid_rule_ids)
        if unknown:
            issues.append(f"{task_label}: unknown rule IDs {unknown}")
        if row.get("num_rules") != len(rules):
            issues.append(f"{task_label}: num_rules differs from rules_retrieved")
        parse_method = str(row.get("parse_method", ""))
        parse_counts[parse_method] += 1
        if parse_method not in VALID_PARSE_METHODS:
            issues.append(f"{task_label}: invalid parse_method {parse_method!r}")
        if not rules:
            issues.append(
                f"{task_label}: retrieval selected no valid rule; this is not "
                "accepted as a successful draw"
            )
        if not isinstance(row.get("raw_response"), str) or not row["raw_response"]:
            issues.append(f"{task_label}: raw_response is missing")
        for field in ("input_tokens", "output_tokens"):
            if not isinstance(row.get(field), int) or row[field] < 0:
                issues.append(f"{task_label}: {field} is invalid")
        if not isinstance(row.get("latency_ms"), (int, float)) or row["latency_ms"] < 0:
            issues.append(f"{task_label}: latency_ms is invalid")

    recorded_parse_counts = metadata.get("parse_method_stats")
    if recorded_parse_counts != dict(parse_counts):
        issues.append("metadata.parse_method_stats does not reconcile")

    return {
        "artifact_type": "retrieval_map_validation",
        "status": "VALID" if not issues else "INVALID",
        "path": path.name,
        "sha256": sha256_file(path),
        "model": model,
        "language": expected_language,
        "seed": expected_seed,
        "mapping_count": len(rows),
        "parse_method_counts": dict(sorted(parse_counts.items())),
        "issues": issues,
    }


def validate_retrieval_sweep(
    map_paths: Sequence[Path],
    *,
    carrier_path: Path,
    model: str,
    language: str,
    accepted_seeds: Sequence[int],
    rules_dir: Path,
) -> RetrievalSweepEvidence:
    """Require exactly twenty semantically valid draws for one fixed carrier."""
    seeds = tuple(int(seed) for seed in accepted_seeds)
    if len(seeds) != RETRIEVAL_REPETITIONS or len(set(seeds)) != len(seeds):
        raise ValueError("accepted_seeds must contain exactly 20 distinct seeds")
    if len(map_paths) != RETRIEVAL_REPETITIONS:
        raise ValueError("exactly 20 retrieval-map paths are required")
    if model not in MODEL_IDS:
        raise ValueError(f"unknown model key {model!r}")
    if language not in {"python", "java"}:
        raise ValueError(f"unsupported language {language!r}")

    carrier = load_json_object(carrier_path)
    _mappings(carrier, carrier_path)
    valid_rule_ids = load_rule_ids(rules_dir)
    by_seed: dict[int, RetrievalMapEvidence] = {}
    validations: list[dict[str, Any]] = []
    system_prompt_hashes: set[str] = set()
    user_template_hashes: set[str] = set()
    for path in map_paths:
        payload = load_json_object(path)
        seed = _metadata_seed(payload, path)
        if seed in by_seed:
            raise ValueError(f"duplicate retrieval seed {seed}")
        validation = validate_retrieval_map(
            path,
            carrier=carrier,
            model=model,
            language=language,
            expected_seed=seed,
            valid_rule_ids=valid_rule_ids,
        )
        validations.append(validation)
        by_seed[seed] = RetrievalMapEvidence(path, payload, seed, sha256_file(path))
        metadata = payload.get("metadata", {})
        system_prompt = metadata.get("system_prompt")
        user_template = metadata.get("user_prompt_template")
        if not isinstance(system_prompt, str) or not system_prompt:
            raise ValueError(f"{path}: retrieval system prompt is missing")
        if not isinstance(user_template, str) or not user_template:
            raise ValueError(f"{path}: retrieval user prompt template is missing")
        system_prompt_hashes.add(sha256_bytes(system_prompt.encode()))
        user_template_hashes.add(sha256_bytes(user_template.encode()))

    if set(by_seed) != set(seeds):
        raise ValueError(
            f"retrieval seeds {sorted(by_seed)} differ from accepted seeds "
            f"{sorted(seeds)}"
        )
    invalid = [row for row in validations if row["status"] != "VALID"]
    if invalid:
        detail = "; ".join(
            f"seed {row['seed']}: {', '.join(row['issues'][:3])}" for row in invalid
        )
        raise ValueError(f"retrieval sweep contains invalid maps: {detail}")
    if len(system_prompt_hashes) != 1:
        raise ValueError("retrieval maps do not share one system prompt")
    if len(user_template_hashes) != 1:
        raise ValueError("retrieval maps do not share one user prompt template")

    ordered_maps = tuple(by_seed[seed] for seed in seeds)
    contract = {
        "model": MODEL_IDS[model],
        "quantization": MODEL_QUANTIZATION[model],
        "bnb_4bit_compute_dtype": MODEL_COMPUTE_DTYPE[model],
        "max_tokens": RETRIEVAL_MAX_TOKENS,
        "language": language,
        "temperature": RETRIEVAL_TEMPERATURE,
        "prompt_template_version": RETRIEVAL_TEMPLATE,
        "system_prompt_sha256": next(iter(system_prompt_hashes)),
        "user_prompt_template_sha256": next(iter(user_template_hashes)),
        "rule_catalog_ids": sorted(valid_rule_ids),
        "repetitions": RETRIEVAL_REPETITIONS,
        "consensus_min_selections": CONSENSUS_MIN_SELECTIONS,
    }
    report = {
        "artifact_type": "retrieval_sweep_validation",
        "status": "VALID",
        "model": model,
        "language": language,
        "carrier": {
            "filename": carrier_path.name,
            "sha256": sha256_file(carrier_path),
            "tasks": len(_mappings(carrier)),
        },
        "accepted_seeds": list(seeds),
        "retrieval_contract": contract,
        "retrieval_contract_sha256": canonical_json_sha256(contract),
        "inputs": [
            {"filename": item.path.name, "seed": item.seed, "sha256": item.sha256}
            for item in ordered_maps
        ],
        "map_validations": validations,
    }
    return RetrievalSweepEvidence(
        model=model,
        language=language,
        carrier_path=carrier_path,
        carrier=carrier,
        accepted_seeds=seeds,
        maps=ordered_maps,
        validation_report=report,
    )


def _content_positions(rows: Sequence[dict[str, Any]]) -> dict[
    tuple[str, str, str, str], list[int]
]:
    positions: dict[tuple[str, str, str, str], list[int]] = defaultdict(list)
    for position, row in enumerate(rows):
        positions[task_content_identity(row)].append(position)
    return positions


def _select_source_positions(
    sweep: RetrievalSweepEvidence,
    canonical_rows: Sequence[dict[str, Any]],
) -> tuple[list[int], list[dict[str, Any]]]:
    source_rows = _mappings(sweep.carrier)
    source_positions = _content_positions(source_rows)
    canonical_positions = _content_positions(canonical_rows)
    selected: dict[int, int] = {}
    duplicate_resolutions: list[dict[str, Any]] = []
    for content_key, target_positions in canonical_positions.items():
        candidates = source_positions.get(content_key, [])
        if not candidates:
            raise ValueError(
                "canonical carrier contains a task absent from the retrieval carrier: "
                f"{content_key[:3]}"
            )
        if len(target_positions) == len(candidates):
            for target, source in zip(target_positions, candidates, strict=True):
                selected[target] = source
            continue
        if len(target_positions) == 1 and len(candidates) > 1:
            canonical_task_id = str(canonical_rows[target_positions[0]]["index"])
            exact_matches = [
                position
                for position in candidates
                if str(source_rows[position]["index"]) == canonical_task_id
            ]
            if len(exact_matches) != 1:
                selected_position = candidates[0]
                resolution = "first_source_occurrence_for_positional_legacy_carrier"
            else:
                selected_position = exact_matches[0]
                resolution = "exact_canonical_task_id"
            selected[target_positions[0]] = selected_position
            duplicate_resolutions.append(
                {
                    "canonical_task_id": canonical_task_id,
                    "source_task_id": str(source_rows[selected_position]["index"]),
                    "source_position": selected_position,
                    "source_occurrences": len(candidates),
                    "resolution": resolution,
                }
            )
            continue
        raise ValueError(
            "canonical/retrieval carrier occurrence counts are ambiguous for "
            f"{content_key[:3]}"
        )
    return (
        [selected[position] for position in range(len(canonical_rows))],
        duplicate_resolutions,
    )


def _derived_map_fields(payload: dict[str, Any]) -> None:
    rows = _mappings(payload)
    frequency = Counter(
        rule_id for row in rows for rule_id in row.get("rules_retrieved", [])
    )
    payload["rule_frequency"] = dict(sorted(frequency.items()))
    metadata = payload.setdefault("metadata", {})
    metadata["total_prompts"] = len(rows)
    metadata["empty_prompts"] = sum(not row.get("rules_retrieved") for row in rows)
    metadata["unique_rules_used"] = len(frequency)
    total_rules = sum(len(row.get("rules_retrieved", [])) for row in rows)
    metadata["avg_rules_per_prompt"] = (
        round(total_rules / len(rows), 3) if rows else 0.0
    )


def materialize_consensus_map(
    sweep: RetrievalSweepEvidence,
    *,
    canonical_carrier_path: Path,
) -> dict[str, Any]:
    """Build one canonical-indexed majority map from a validated sweep."""
    canonical_carrier = load_json_object(canonical_carrier_path)
    canonical_rows = _mappings(canonical_carrier, canonical_carrier_path)
    for row in canonical_rows:
        if str(row.get("language", "")).lower() != sweep.language:
            raise ValueError("canonical carrier contains the wrong language")
    source_positions, duplicate_resolutions = _select_source_positions(
        sweep,
        canonical_rows,
    )

    materialized_rows: list[dict[str, Any]] = []
    for canonical_row, source_position in zip(
        canonical_rows, source_positions, strict=True
    ):
        counts: Counter[str] = Counter()
        for evidence in sweep.maps:
            rules = set(_mappings(evidence.payload)[source_position]["rules_retrieved"])
            counts.update(rules)
        ordered_frequency = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
        retained = [
            rule_id
            for rule_id, count in ordered_frequency
            if count >= CONSENSUS_MIN_SELECTIONS
        ]
        row = {
            key: canonical_row[key]
            for key in ("index", "cwe_id", "language", "prompt_hash", "prompt")
        }
        row["rules_retrieved"] = retained
        row["num_rules"] = len(retained)
        row["seed_frequency"] = dict(ordered_frequency)
        materialized_rows.append(row)

    validation = sweep.validation_report
    payload = {
        "artifact_type": "retrieval_consensus_map",
        "metadata": {
            "evidence_status": "candidate",
            "kind": "retrieval_consensus",
            "model": MODEL_IDS[sweep.model],
            "model_key": sweep.model,
            "language": sweep.language,
            "temperature": RETRIEVAL_TEMPERATURE,
            "prompt_template_version": RETRIEVAL_TEMPLATE,
            "accepted_seeds": list(sweep.accepted_seeds),
            "retrieval_repetitions": RETRIEVAL_REPETITIONS,
            "consensus_min_selections": CONSENSUS_MIN_SELECTIONS,
            "consensus_rule": "rule retained iff selected in at least 11 of 20 valid draws",
            "retrieval_contract_sha256": validation[
                "retrieval_contract_sha256"
            ],
            "retrieval_carrier": {
                "filename": sweep.carrier_path.name,
                "sha256": sha256_file(sweep.carrier_path),
            },
            "canonical_carrier": {
                "filename": canonical_carrier_path.name,
                "sha256": sha256_file(canonical_carrier_path),
            },
            "retrieval_inputs": validation["inputs"],
            "canonical_duplicate_resolutions": duplicate_resolutions,
        },
        "mappings": materialized_rows,
    }
    _derived_map_fields(payload)
    return payload


def merge_consensus_parts(
    part_paths: Sequence[Path],
    *,
    canonical_carrier_path: Path,
    model: str,
    language: str,
) -> dict[str, Any]:
    """Merge disjoint canonical consensus parts in full-carrier order."""
    if len(part_paths) < 1:
        raise ValueError("at least one consensus part is required")
    canonical_carrier = load_json_object(canonical_carrier_path)
    canonical_rows = _mappings(canonical_carrier, canonical_carrier_path)
    canonical_by_id = {str(row["index"]): row for row in canonical_rows}
    if len(canonical_by_id) != len(canonical_rows):
        raise ValueError("canonical carrier contains duplicate task IDs")

    rows_by_id: dict[str, dict[str, Any]] = {}
    source_parts: list[dict[str, Any]] = []
    retrieval_contracts: set[str] = set()
    for path in part_paths:
        payload = load_json_object(path)
        if payload.get("artifact_type") != "retrieval_consensus_map":
            raise ValueError(f"{path}: not a retrieval_consensus_map")
        metadata = payload.get("metadata", {})
        if metadata.get("model") != MODEL_IDS.get(model):
            raise ValueError(f"{path}: model differs from {model}")
        if metadata.get("language") != language:
            raise ValueError(f"{path}: language differs from {language}")
        if metadata.get("prompt_template_version") != RETRIEVAL_TEMPLATE:
            raise ValueError(f"{path}: retrieval template is not frozen")
        if metadata.get("retrieval_repetitions") != RETRIEVAL_REPETITIONS:
            raise ValueError(f"{path}: retrieval repetition count is not 20")
        if metadata.get("consensus_min_selections") != CONSENSUS_MIN_SELECTIONS:
            raise ValueError(f"{path}: consensus threshold is not 11")
        retrieval_contract = metadata.get("retrieval_contract_sha256")
        if (
            not isinstance(retrieval_contract, str)
            or len(retrieval_contract) != 64
            or any(character not in "0123456789abcdef" for character in retrieval_contract)
        ):
            raise ValueError(f"{path}: retrieval contract hash is invalid")
        retrieval_contracts.add(retrieval_contract)
        rows = _mappings(payload, path)
        for row in rows:
            task_id = str(row["index"])
            if task_id in rows_by_id:
                raise ValueError(f"consensus parts overlap on task {task_id}")
            canonical = canonical_by_id.get(task_id)
            if canonical is None or task_content_identity(row) != task_content_identity(
                canonical
            ):
                raise ValueError(f"{path}: task {task_id} differs from canonical carrier")
            rows_by_id[task_id] = row
        source_parts.append(
            {
                "filename": path.name,
                "sha256": sha256_file(path),
                "tasks": len(rows),
                "accepted_seeds": metadata.get("accepted_seeds"),
                "retrieval_contract_sha256": metadata.get(
                    "retrieval_contract_sha256"
                ),
            }
        )
    if len(retrieval_contracts) != 1:
        raise ValueError("consensus parts use different retrieval contracts")

    if set(rows_by_id) != set(canonical_by_id):
        missing = sorted(set(canonical_by_id) - set(rows_by_id), key=int)
        extra = sorted(set(rows_by_id) - set(canonical_by_id), key=int)
        raise ValueError(
            f"consensus parts do not cover the canonical carrier; "
            f"missing={missing}, extra={extra}"
        )
    ordered_rows = [rows_by_id[str(row["index"])] for row in canonical_rows]
    hash_groups: dict[str, list[str]] = defaultdict(list)
    for row in canonical_rows:
        hash_groups[str(row["prompt_hash"])].append(str(row["index"]))
    duplicate_prompts = {
        prompt_hash: task_ids
        for prompt_hash, task_ids in hash_groups.items()
        if len(task_ids) > 1
    }
    payload = {
        "artifact_type": "retrieval_consensus_map",
        "metadata": {
            "evidence_status": "candidate",
            "kind": "full_retrieval_consensus",
            "model": MODEL_IDS[model],
            "model_key": model,
            "language": language,
            "temperature": RETRIEVAL_TEMPERATURE,
            "prompt_template_version": RETRIEVAL_TEMPLATE,
            "retrieval_contract_sha256": retrieval_contracts.pop(),
            "retrieval_repetitions_per_task": RETRIEVAL_REPETITIONS,
            "consensus_min_selections": CONSENSUS_MIN_SELECTIONS,
            "consensus_rule": "rule retained iff selected in at least 11 of 20 valid draws",
            "canonical_carrier": {
                "filename": canonical_carrier_path.name,
                "sha256": sha256_file(canonical_carrier_path),
            },
            "source_parts": source_parts,
            "duplicate_prompt_hashes": duplicate_prompts,
        },
        "mappings": ordered_rows,
    }
    _derived_map_fields(payload)
    return payload


def build_norules_map(
    canonical_carrier_path: Path,
    *,
    evidence_status: str = "candidate",
) -> dict[str, Any]:
    carrier = load_json_object(canonical_carrier_path)
    rows = _mappings(carrier, canonical_carrier_path)
    materialized = []
    for source in rows:
        row = {
            key: source[key]
            for key in ("index", "cwe_id", "language", "prompt_hash", "prompt")
        }
        row["rules_retrieved"] = []
        row["num_rules"] = 0
        materialized.append(row)
    payload = {
        "artifact_type": "no_rules_map",
        "metadata": {
            "evidence_status": evidence_status,
            "kind": "no_rules",
            "canonical_carrier": {
                "filename": canonical_carrier_path.name,
                "sha256": sha256_file(canonical_carrier_path),
            },
        },
        "mappings": materialized,
    }
    _derived_map_fields(payload)
    return payload


def build_population_carrier(source_path: Path) -> dict[str, Any]:
    """Strip historical retrieval fields from a canonical task population."""
    source = load_json_object(source_path)
    source_rows = _mappings(source, source_path)
    task_ids: set[str] = set()
    materialized: list[dict[str, Any]] = []
    languages: Counter[str] = Counter()
    for position, source_row in enumerate(source_rows):
        task_id = str(source_row.get("index"))
        if task_id in task_ids:
            raise ValueError(f"{source_path}: duplicate task ID {task_id}")
        task_ids.add(task_id)
        language = str(source_row.get("language", "")).lower()
        if language not in {"python", "java"}:
            raise ValueError(
                f"{source_path}: position {position} has unsupported language "
                f"{language!r}"
            )
        prompt = source_row.get("prompt")
        if not isinstance(prompt, str) or not prompt:
            raise ValueError(f"{source_path}: task {task_id} lacks prompt text")
        if source_row.get("prompt_hash") != compute_prompt_hash(prompt):
            raise ValueError(f"{source_path}: task {task_id} has a stale prompt hash")
        cwe_id = source_row.get("cwe_id")
        if not isinstance(cwe_id, str) or not cwe_id:
            raise ValueError(f"{source_path}: task {task_id} lacks a CWE identifier")
        materialized.append(
            {
                "index": source_row["index"],
                "cwe_id": cwe_id,
                "language": language,
                "prompt_hash": source_row["prompt_hash"],
                "prompt": prompt,
            }
        )
        languages[language] += 1
    return {
        "artifact_type": "task_population_carrier",
        "metadata": {
            "evidence_status": "source",
            "dataset": source.get("metadata", {}).get(
                "dataset",
                "walledai/CyberSecEval",
            ),
            "tasks": len(materialized),
            "languages": dict(sorted(languages.items())),
            "source_artifact": {
                "filename": source_path.name,
                "sha256": sha256_file(source_path),
            },
        },
        "mappings": materialized,
    }


def write_json(path: Path, payload: dict[str, Any], *, overwrite: bool) -> None:
    if path.exists() and not overwrite:
        raise FileExistsError(f"refusing to overwrite {path}; pass --overwrite")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def paths_for_accepted_seeds(
    directory: Path,
    accepted_seeds: Iterable[int],
) -> list[Path]:
    """Resolve exactly one JSON map per accepted seed from a sweep directory."""
    resolved: list[Path] = []
    files = sorted(directory.glob("retrieval_map_*.json"))
    for seed in accepted_seeds:
        matches = []
        for path in files:
            try:
                payload = load_json_object(path)
            except (OSError, json.JSONDecodeError, ValueError):
                continue
            if payload.get("metadata", {}).get("seed") == int(seed):
                matches.append(path)
        if len(matches) != 1:
            raise ValueError(
                f"{directory}: expected exactly one retrieval map for seed {seed}, "
                f"found {len(matches)}"
            )
        resolved.append(matches[0])
    return resolved
