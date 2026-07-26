from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts.setup.materialize_qualified_search_maps import (
    FINAL_SEARCH_POPULATION_POLICY,
    MODEL_IDS,
    _population_fingerprint,
    materialize,
)
from src.evaluation.generation_contract import prompt_contract_sha256
from src.evaluation.population_screening import (
    SCREENING_POLICY,
    combine_screened_language_maps,
)
from src.retrieval.population import ELIGIBILITY_POLICY


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _row(task_id: int, language: str, *, with_rules: bool = True) -> dict:
    rules = ["codeguard-example"] if with_rules else []
    return {
        "index": task_id,
        "cwe_id": "CWE-1",
        "language": language,
        "prompt_hash": f"{task_id:016x}",
        "prompt": f"Task {task_id}",
        "rules_retrieved": rules,
        "num_rules": len(rules),
    }


def _screened_map(rows: list[dict], *, model: str | None) -> dict:
    language = str(rows[0]["language"])
    return {
        "artifact_type": "screened_population_map",
        "metadata": {
            "model_key": model,
            "population_eligibility": {
                "evidence_status": "final",
                "policy": ELIGIBILITY_POLICY,
                "manifest": {
                    "filename": "eligibility.json",
                    "sha256": _sha(Path(rows[0]["_map_root"]) / "eligibility.json"),
                },
            },
            "population_screening": {
                "evidence_status": "final",
                "policy": SCREENING_POLICY,
                "screened_population_total": len(rows),
                "screened_population_fingerprint": _population_fingerprint(rows),
                "manifest": {
                    "filename": f"screening_{language}.json",
                    "sha256": _sha(
                        Path(rows[0]["_map_root"]) / f"screening_{language}.json"
                    ),
                },
            },
        },
        "mappings": [
            {key: value for key, value in row.items() if key != "_map_root"}
            for row in rows
        ],
    }


def _write_map(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload), encoding="utf-8")


def _create_map_dir(root: Path) -> Path:
    root.mkdir()
    source_population = root / "source_population.json"
    source_population.write_text(
        json.dumps({"artifact_type": "source_population", "mappings": []}),
        encoding="utf-8",
    )
    (root / "eligibility.json").write_text(
        json.dumps(
            {
                "artifact_type": "population_eligibility_manifest",
                "source_population": {
                    "filename": source_population.name,
                    "sha256": _sha(source_population),
                },
            }
        ),
        encoding="utf-8",
    )
    python_rows = [
        {**_row(1, "python"), "_map_root": str(root)},
        {**_row(518, "python"), "_map_root": str(root)},
    ]
    java_rows = [
        {**_row(task_id, "java"), "_map_root": str(root)}
        for task_id in (640, 959, 1061, 1357, 2000, 2001)
    ]
    for language, rows in (
        ("python", python_rows),
        ("java", java_rows),
    ):
        task_ids = [str(row["index"]) for row in rows]
        reasons = {
            task_id: (
                "incomplete_evidence"
                if language == "java" and task_id == "2000"
                else "observed_finding"
            )
            for task_id in task_ids
        }
        (root / f"screening_{language}.json").write_text(
            json.dumps(
                {
                    "artifact_type": "population_screening_manifest",
                    "evidence_status": "final",
                    "policy": SCREENING_POLICY,
                    "language": language,
                    "temperature": 0.6,
                    "screening_mode": "single_block_20_seeds",
                    "source_population_total": len(rows),
                    "retained_population_total": len(rows),
                    "excluded_never_vulnerable_total": 0,
                    "retained_task_ids": task_ids,
                    "retention_reason_by_task": reasons,
                }
            ),
            encoding="utf-8",
        )
    for model in ("qwen", "llama"):
        python_map = _screened_map(python_rows, model=model)
        java_map = _screened_map(java_rows, model=model)
        _write_map(root / f"final_consensus_map_{model}_python.json", python_map)
        _write_map(root / f"final_consensus_map_{model}_java.json", java_map)
        _write_map(
            root / f"final_consensus_map_{model}.json",
            combine_screened_language_maps(
                python_map,
                java_map,
                model=model,
            ),
        )
    norules_python = _screened_map(
        [
            {
                **_row(1, "python", with_rules=False),
                "_map_root": str(root),
            },
            {
                **_row(518, "python", with_rules=False),
                "_map_root": str(root),
            },
        ],
        model=None,
    )
    norules_java = _screened_map(
        [
            {
                **_row(task_id, "java", with_rules=False),
                "_map_root": str(root),
            }
            for task_id in (640, 959, 1061, 1357, 2000, 2001)
        ],
        model=None,
    )
    _write_map(
        root / "final_norules_map.json",
        combine_screened_language_maps(
            norules_python,
            norules_java,
            model="norules",
        ),
    )
    return root


def _qualification_run(
    root: Path,
    map_dir: Path,
    *,
    model: str,
    language: str,
    excluded_ids: set[str],
) -> Path:
    source_map = map_dir / f"final_consensus_map_{model}_{language}.json"
    mappings = json.loads(source_map.read_text())["mappings"]
    valid = [row for row in mappings if str(row["index"]) not in excluded_ids]
    run_dir = root / f"qual_{model}_{language}"
    run_dir.mkdir()
    manifest = {
        "artifact_type": "qualification_manifest",
        "mode": "qualification",
        "status": "COMPLETE",
        "model": MODEL_IDS[model],
        "provider": "fake",
        "temperature": 0.0,
        "prompt_contract_sha256": prompt_contract_sha256(),
        "analysis_languages": [language],
        "total_prompts": len(mappings),
        "valid_prompts": len(valid),
        "excluded_prompts": len(excluded_ids),
        "valid_task_ids": [str(row["index"]) for row in valid],
        "excluded": [
            {
                "test_case_id": task_id,
                "analysis_language": language,
                "status": "syntax_invalid",
                "reason": "fixture",
                "finish_reason": "stop",
            }
            for task_id in sorted(excluded_ids, key=int)
        ],
        "qualified_population_fingerprint": _population_fingerprint(valid),
    }
    manifest_path = run_dir / "qualification_manifest.json"
    manifest_path.write_text(json.dumps(manifest))
    run_config = {
        "artifact_type": "qualification_run_config",
        "git_commit_sha": "1" * 40,
        "slurm_job_id": f"{model}-{language}",
        "args": {
            "run_mode": "qualification",
            "backend": "delftblue",
            "dry_run": False,
            "temperature": 0.0,
            "prompt_contract_sha256": prompt_contract_sha256(),
            "max_output_tokens": 4096,
            "model": MODEL_IDS[model],
            "model_revision": ("4" if model == "qwen" else "5") * 40,
            "torch_version": "2.12.0",
            "transformers_version": "5.9.0",
            "rules_map_sha256": _sha(source_map),
            "semgrep_rules_source_commit": "2" * 40,
            "semgrep_rules_sha256": "3" * 64,
            "semgrep_version": "1.85.0",
        },
    }
    run_config_path = run_dir / "run_config.json"
    run_config_path.write_text(json.dumps(run_config))
    generations_path = run_dir / "qualification_generations.jsonl"
    generations_path.write_text("fixture\n")
    intermediate_path = run_dir / "intermediate" / "qualification_tasks.jsonl"
    intermediate_path.parent.mkdir()
    intermediate_path.write_text("fixture\n")
    debug_path = run_dir / "semgrep_debug" / "semgrep_debug.jsonl"
    debug_path.parent.mkdir()
    debug_path.write_text("fixture\n")
    artifact_paths = {
        "run_config": run_config_path,
        "qualification_manifest": manifest_path,
        "qualification_generations": generations_path,
        "qualification_tasks": intermediate_path,
        "semgrep_debug": debug_path,
        "evaluation_failures": run_dir / "evaluation_failures.jsonl",
    }
    (run_dir / "qualification_validation.json").write_text(
        json.dumps(
            {
                "artifact_type": "qualification_validation",
                "status": "VALID",
                "manifest_sha256": _sha(manifest_path),
                "artifact_sha256": {
                    name: (_sha(path) if path.is_file() else None)
                    for name, path in artifact_paths.items()
                },
            }
        )
    )
    return manifest_path


def test_materializer_intersects_models_and_writes_frozen_maps(tmp_path: Path) -> None:
    map_dir = _create_map_dir(tmp_path / "maps")

    qwen_python = _qualification_run(
        tmp_path, map_dir, model="qwen", language="python", excluded_ids=set()
    )
    llama_python = _qualification_run(
        tmp_path, map_dir, model="llama", language="python", excluded_ids={"518"}
    )
    qwen_java = _qualification_run(
        tmp_path, map_dir, model="qwen", language="java", excluded_ids={"1357"}
    )
    llama_java = _qualification_run(
        tmp_path,
        map_dir,
        model="llama",
        language="java",
        excluded_ids={"640", "959", "1061", "1357"},
    )
    output_dir = tmp_path / "qualified"
    args = SimpleNamespace(
        qwen_python_manifest=qwen_python,
        llama_python_manifest=llama_python,
        qwen_java_manifest=qwen_java,
        llama_java_manifest=llama_java,
        map_dir=map_dir,
        output_dir=output_dir,
        overwrite=False,
    )

    result = materialize(args)

    assert result["artifact_type"] == "qualified_population_manifest"
    assert result["evidence_status"] == "final"
    assert result["policy"] == FINAL_SEARCH_POPULATION_POLICY
    assert result["language_counts"] == {"python": 1, "java": 1}
    assert set(result["exclusions"]) == {
        "518",
        "640",
        "959",
        "1061",
        "1357",
        "2000",
    }
    assert result["exclusions"]["2000"]["reason"] == (
        "no_observed_finding_with_incomplete_screening_evidence"
    )
    for model in ("qwen", "llama"):
        python_map = json.loads(
            (output_dir / f"final_search_map_{model}_python.json").read_text()
        )
        java_map = json.loads(
            (output_dir / f"final_search_map_{model}_java.json").read_text()
        )
        combined = json.loads(
            (output_dir / f"final_search_map_{model}.json").read_text()
        )
        assert len(python_map["mappings"]) == 1
        assert len(java_map["mappings"]) == 1
        assert len(combined["mappings"]) == 2
        assert combined["artifact_type"] == "qualified_rule_map"
        assert combined["metadata"]["evidence_status"] == "final"
        assert (
            combined["metadata"]["search_qualification"]["evidence_status"]
            == "final"
        )
        assert (
            combined["metadata"]["search_qualification"]["policy"]
            == FINAL_SEARCH_POPULATION_POLICY
        )
    norules = json.loads((output_dir / "final_search_norules_map.json").read_text())
    assert len(norules["mappings"]) == 2
    assert len(
        json.loads((output_dir / "final_search_norules_map_python.json").read_text())[
            "mappings"
        ]
    ) == 1
    assert len(
        json.loads((output_dir / "final_search_norules_map_java.json").read_text())[
            "mappings"
        ]
    ) == 1


def test_materializer_rejects_validation_after_evidence_changes(tmp_path: Path) -> None:
    map_dir = _create_map_dir(tmp_path / "maps")
    manifests = {
        (model, language): _qualification_run(
            tmp_path,
            map_dir,
            model=model,
            language=language,
            excluded_ids=set(),
        )
        for model in ("qwen", "llama")
        for language in ("python", "java")
    }
    stale_evidence = (
        manifests[("qwen", "python")].parent
        / "intermediate"
        / "qualification_tasks.jsonl"
    )
    stale_evidence.write_text("changed after validation\n")
    args = SimpleNamespace(
        qwen_python_manifest=manifests[("qwen", "python")],
        llama_python_manifest=manifests[("llama", "python")],
        qwen_java_manifest=manifests[("qwen", "java")],
        llama_java_manifest=manifests[("llama", "java")],
        map_dir=map_dir,
        output_dir=tmp_path / "qualified",
        overwrite=False,
    )

    with pytest.raises(ValueError, match="stale validation for qualification_tasks"):
        materialize(args)


def test_materializer_rejects_unscreened_source_map(tmp_path: Path) -> None:
    map_dir = _create_map_dir(tmp_path / "maps")
    source = map_dir / "final_consensus_map_qwen_python.json"
    payload = json.loads(source.read_text())
    payload["artifact_type"] = "retrieval_consensus_map"
    _write_map(source, payload)
    args = SimpleNamespace(
        qwen_python_manifest=tmp_path / "unused-qwen-python.json",
        llama_python_manifest=tmp_path / "unused-llama-python.json",
        qwen_java_manifest=tmp_path / "unused-qwen-java.json",
        llama_java_manifest=tmp_path / "unused-llama-java.json",
        map_dir=map_dir,
        output_dir=tmp_path / "qualified",
        overwrite=False,
    )

    with pytest.raises(ValueError, match="not a screened_population_map"):
        materialize(args)
