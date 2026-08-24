"""Portable, strictly keyed bundles for the shared five-candidate prefix."""

from __future__ import annotations

import hashlib
import json
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from ..evaluation.fitness import AggregatedFitness
from .chromosome import GeneState, RuleSetChromosome
from .search import INITIALIZATION_SAMPLES, PrecomputedInitializationCandidate


IDENTITY_ARGUMENT_FIELDS = (
    "model",
    "quantization",
    "bnb_compute_dtype",
    "temperature",
    "model_revision",
    "torch_version",
    "transformers_version",
    "prompt_contract_sha256",
    "rules_map_sha256",
    "population_fingerprint",
    "population_evidence_status",
    "n_cases",
    "evaluation_population_fingerprint",
    "languages",
    "mutators",
    "seed",
    "objective_direction",
    "max_depth",
    "random_max_changes",
    "order_move_weight",
    "enable_validation",
    "semgrep_version",
    "semgrep_timeout_seconds",
    "semgrep_jobs",
    "semgrep_rules_sha256",
    "semgrep_rules_source_commit",
    "max_output_tokens",
    "rule_corpus_sha256",
)


@dataclass(frozen=True)
class LoadedInitializationBundle:
    path: Path
    content_sha256: str
    identity: dict[str, Any]
    candidates: list[PrecomputedInitializationCandidate]
    runner_random_state: object
    runtime_random_state: dict[str, Any]
    precomputed_usage: dict[str, Any]


def canonical_sha256(payload: Any) -> str:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def build_initialization_identity(run_config: dict[str, Any]) -> dict[str, Any]:
    """Extract the fields whose equality makes prefix reuse scientifically valid."""
    args = run_config.get("args")
    if not isinstance(args, dict):
        raise ValueError("run_config lacks an args object")
    identity = {
        "git_commit_sha": run_config.get("git_commit_sha"),
        "arguments": {field: args.get(field) for field in IDENTITY_ARGUMENT_FIELDS},
    }
    return identity


def _json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path}: expected a JSON object")
    return payload


def _jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            row = json.loads(line)
            if not isinstance(row, dict):
                raise ValueError(f"{path}:{line_number}: expected a JSON object")
            rows.append(row)
    return rows


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _fitness_from_record(record: dict[str, Any]) -> AggregatedFitness:
    return AggregatedFitness(
        total_fitness=float(record["total_fitness"]),
        mean_fitness=float(record["mean_fitness"]),
        max_fitness=float(record["max_fitness"]),
        num_prompts=int(record["num_prompts"]),
        num_vulnerable=int(record["num_vulnerable"]),
        individual_results=[],
        total_raw_reduction=float(record["f1"]),
        total_raw_count=int(record["total_raw_findings"]),
        total_weighted_score=float(record["total_weighted_score"]),
        total_weighted_reduction=float(record["weighted_reduction"]),
        num_valid_prompts=int(record["num_valid_prompts"]),
        num_invalid_prompts=int(record["num_invalid_prompts"]),
        failure_counts=dict(record.get("failure_counts") or {}),
        num_prompts_affected=int(record["num_prompts_affected"]),
        rule_fidelity=float(record["rule_fidelity"]),
        parsimony=int(record["parsimony"]),
    )


def _candidate_from_payload(payload: dict[str, Any]) -> PrecomputedInitializationCandidate:
    genes = {
        rule_id: GeneState(
            rule_id=rule_id,
            text=str(gene["text"]),
            mutation_path=[str(value) for value in gene["mutation_path"]],
        )
        for rule_id, gene in payload["chromosome"]["genes"].items()
    }
    chromosome = RuleSetChromosome(
        genes=genes,
        order_priority={
            str(key): int(value)
            for key, value in payload["chromosome"]["order_priority"].items()
        },
        cid=str(payload["chromosome"]["cid"]),
    )
    proposal = payload["proposal"]
    return PrecomputedInitializationCandidate(
        child=chromosome,
        fitness=_fitness_from_record(payload["fitness"]),
        n_requested_changes=int(proposal["n_requested_changes"]),
        n_attempted_changes=int(proposal["n_attempted_changes"]),
        n_effective_changes=int(proposal["n_effective_changes"]),
        attempted_operators=[str(value) for value in proposal["attempted_operators"]],
        attempted_mutators=[str(value) for value in proposal["attempted_mutators"]],
        effective_mutators=[str(value) for value in proposal["effective_mutators"]],
        changes=[str(value) for value in proposal["changes"]],
        validation_metadata=dict(payload.get("validation_metadata") or {}),
    )


def load_initialization_bundle(
    path: Path,
    *,
    expected_identity: dict[str, Any],
) -> LoadedInitializationBundle:
    """Load a bundle only when every strict reuse-key field matches."""
    bundle_dir = path.resolve()
    manifest_path = (
        bundle_dir / "initialization_bundle.json"
        if bundle_dir.is_dir()
        else bundle_dir
    )
    manifest = _json(manifest_path)
    if manifest.get("artifact_type") != "initialization_bundle":
        raise ValueError(f"{manifest_path}: wrong artifact type")
    identity = manifest.get("identity")
    if identity != expected_identity:
        raise ValueError(
            "initialisation bundle identity differs from the current run; "
            "generate a new bundle for this exact configuration"
        )
    content = {key: value for key, value in manifest.items() if key != "content_sha256"}
    content_sha256 = canonical_sha256(content)
    if manifest.get("content_sha256") != content_sha256:
        raise ValueError(f"{manifest_path}: bundle content hash does not reconcile")
    evidence = manifest.get("evidence_sha256")
    if not isinstance(evidence, dict):
        raise ValueError(f"{manifest_path}: missing evidence hashes")
    for name, expected_sha in evidence.items():
        evidence_path = manifest_path.parent / str(name)
        if not evidence_path.is_file() or _file_sha256(evidence_path) != expected_sha:
            raise ValueError(f"{manifest_path}: stale or missing evidence {name}")
    candidates_payload = manifest.get("candidates")
    if not isinstance(candidates_payload, list) or len(candidates_payload) != (
        INITIALIZATION_SAMPLES
    ):
        raise ValueError(
            f"{manifest_path}: expected {INITIALIZATION_SAMPLES} candidates"
        )
    state = manifest.get("random_state")
    if not isinstance(state, dict) or "runner" not in state or "runtime" not in state:
        raise ValueError(f"{manifest_path}: incomplete random-state checkpoint")
    return LoadedInitializationBundle(
        path=manifest_path.parent,
        content_sha256=content_sha256,
        identity=identity,
        candidates=[_candidate_from_payload(value) for value in candidates_payload],
        runner_random_state=_lists_to_tuples(state["runner"]),
        runtime_random_state=dict(state["runtime"]),
        precomputed_usage=dict(manifest.get("precomputed_usage") or {}),
    )


def _lists_to_tuples(value: Any) -> Any:
    if isinstance(value, list):
        return tuple(_lists_to_tuples(item) for item in value)
    return value


def capture_runtime_random_state(
    mutators: Iterable[Any],
    runner_random_state: object,
) -> dict[str, Any]:
    """Capture all RNG streams used after the shared initialisation."""
    import torch

    mutator_states = {
        str(mutator.name): mutator.rng.getstate()
        for mutator in mutators
        if hasattr(mutator, "rng")
    }
    return {
        "artifact_type": "initialization_random_state",
        "runner": runner_random_state,
        "runtime": {
            "mutators": mutator_states,
            "torch_cpu": torch.get_rng_state().tolist(),
            "torch_cuda": (
                [state.tolist() for state in torch.cuda.get_rng_state_all()]
                if torch.cuda.is_available()
                else []
            ),
        },
    }


def restore_runtime_random_state(
    state: dict[str, Any],
    mutators: Iterable[Any],
) -> None:
    """Restore mutator and Torch RNG streams at the prefix boundary."""
    import torch

    expected_mutators = state.get("mutators")
    if not isinstance(expected_mutators, dict):
        raise ValueError("bundle runtime state lacks mutator RNG states")
    actual = {str(mutator.name): mutator for mutator in mutators}
    if set(actual) != set(expected_mutators):
        raise ValueError("bundle mutator RNG-state set differs from the current run")
    for name, mutator in actual.items():
        mutator.rng.setstate(_lists_to_tuples(expected_mutators[name]))
    torch.set_rng_state(torch.tensor(state["torch_cpu"], dtype=torch.uint8))
    cuda_states = state.get("torch_cuda")
    if not isinstance(cuda_states, list):
        raise ValueError("bundle CUDA RNG state is malformed")
    if torch.cuda.is_available():
        if len(cuda_states) != torch.cuda.device_count():
            raise ValueError("bundle CUDA RNG-state count differs from current devices")
        torch.cuda.set_rng_state_all(
            [torch.tensor(value, dtype=torch.uint8) for value in cuda_states]
        )
    elif cuda_states:
        raise ValueError("bundle contains CUDA RNG state but CUDA is unavailable")


def materialize_initialization_bundle(
    source_run: Path,
    output_dir: Path,
) -> Path:
    """Create a self-contained reusable bundle from a five-evaluation run."""
    source_run = source_run.resolve()
    output_dir = output_dir.resolve()
    if output_dir.exists():
        raise FileExistsError(f"refusing to overwrite existing bundle: {output_dir}")
    config = _json(source_run / "run_config.json")
    args = config.get("args") if isinstance(config.get("args"), dict) else {}
    if config.get("artifact_type") != "search_run_config":
        raise ValueError("source is not a current search run")
    if args.get("main_loop_budget") != 0:
        raise ValueError("bundle source must use main_loop_budget=0")
    validation = _json(source_run / "search_validation.json")
    if validation.get("status") != "VALID":
        raise ValueError("bundle source search validation is not VALID")
    validated_hashes = validation.get("artifact_sha256")
    if not isinstance(validated_hashes, dict):
        raise ValueError("bundle source validation lacks artifact hashes")
    for name, relative in {
        "run_config": "run_config.json",
        "search_summary": "search_summary.json",
        "evaluations": "evaluations.jsonl",
        "evaluation_manifest": "evaluation_manifest.json",
        "initialization_random_state": "initialization_random_state.json",
    }.items():
        path = source_run / relative
        if validated_hashes.get(name) != (
            _file_sha256(path) if path.is_file() else None
        ):
            raise ValueError(f"bundle source validation is stale for {relative}")
    summary = _json(source_run / "search_summary.json")
    if (
        summary.get("termination_reason") != "evaluation_budget_complete"
        or summary.get("num_evaluations_completed") != INITIALIZATION_SAMPLES
    ):
        raise ValueError("bundle source did not complete exactly five evaluations")
    state = _json(source_run / "initialization_random_state.json")
    if state.get("artifact_type") != "initialization_random_state":
        raise ValueError("source random-state checkpoint is invalid")
    records = [
        row
        for row in _jsonl(source_run / "evaluations.jsonl")
        if row.get("evaluation_consumed") is True
    ]
    if len(records) != INITIALIZATION_SAMPLES or any(
        row.get("phase") != "initialization" for row in records
    ):
        raise ValueError(
            "source evaluations do not contain exactly five initial candidates"
        )

    candidates: list[dict[str, Any]] = []
    evidence_sources: dict[str, Path] = {}
    precomputed_code_calls = 0
    precomputed_code_input_tokens = 0
    precomputed_code_output_tokens = 0
    for index, record in enumerate(records, 1):
        evaluation_dir = (
            source_run / "mutated_rules" / f"evaluation_{index:04d}"
        )
        meta = _json(evaluation_dir / "meta.json")
        genes: dict[str, Any] = {}
        for rule_id in meta.get("mutated_rule_ids", []):
            short = str(rule_id).replace("codeguard-", "cg-")
            text_path = evaluation_dir / f"{short}.md"
            genes[str(rule_id)] = {
                "text": text_path.read_text(encoding="utf-8"),
                "mutation_path": list(meta["gene_paths"][rule_id]),
            }
        candidates.append(
            {
                "evaluation_index": index,
                "chromosome": {
                    "cid": record["chromosome_id"],
                    "genes": genes,
                    "order_priority": dict(meta.get("order_priority") or {}),
                },
                "fitness": {
                    key: record[key]
                    for key in (
                        "total_fitness",
                        "mean_fitness",
                        "max_fitness",
                        "num_prompts",
                        "num_vulnerable",
                        "num_valid_prompts",
                        "num_invalid_prompts",
                        "num_prompts_affected",
                        "f1",
                        "rule_fidelity",
                        "parsimony",
                        "total_raw_findings",
                        "total_weighted_score",
                        "weighted_reduction",
                        "failure_counts",
                    )
                },
                "proposal": {
                    "n_requested_changes": record["n_requested_changes"],
                    "n_attempted_changes": record["n_attempted_changes"],
                    "n_effective_changes": record["n_effective_changes"],
                    "attempted_operators": record["attempted_operators"],
                    "attempted_mutators": record["attempted_mutators"],
                    "effective_mutators": record["mutation_chain"],
                    "changes": meta.get("changes") or [],
                },
                "validation_metadata": meta.get("validation_metadata") or {},
            }
        )
        relative = f"intermediate/evaluation_{index:04d}.jsonl"
        evidence_sources[relative] = source_run / relative
        prompt_rows = _jsonl(evidence_sources[relative])
        precomputed_code_calls += sum(
            row.get("eval_cache_hit") is not True for row in prompt_rows
        )
        precomputed_code_input_tokens += sum(
            int(row.get("input_tokens") or 0)
            for row in prompt_rows
            if row.get("eval_cache_hit") is not True
        )
        precomputed_code_output_tokens += sum(
            int(row.get("output_tokens") or 0)
            for row in prompt_rows
            if row.get("eval_cache_hit") is not True
        )

    output_dir.mkdir(parents=True)
    evidence_hashes: dict[str, str] = {}
    for relative, source in evidence_sources.items():
        target = output_dir / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        evidence_hashes[relative] = _file_sha256(target)
    manifest: dict[str, Any] = {
        "artifact_type": "initialization_bundle",
        "identity": build_initialization_identity(config),
        "identity_sha256": canonical_sha256(build_initialization_identity(config)),
        "source_run_config_sha256": _file_sha256(source_run / "run_config.json"),
        "random_state": {
            "runner": state["runner"],
            "runtime": state["runtime"],
        },
        "candidates": candidates,
        "precomputed_usage": {
            "code_generation_calls": precomputed_code_calls,
            "code_generation_input_tokens": precomputed_code_input_tokens,
            "code_generation_output_tokens": precomputed_code_output_tokens,
            "mutation_llm": dict(summary.get("mutation_llm_usage_actual") or {}),
        },
        "evidence_sha256": evidence_hashes,
    }
    manifest["content_sha256"] = canonical_sha256(manifest)
    path = output_dir / "initialization_bundle.json"
    path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return path
