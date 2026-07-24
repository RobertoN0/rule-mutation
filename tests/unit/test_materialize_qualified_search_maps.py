from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts.setup.materialize_qualified_search_maps import (
    MODEL_IDS,
    _population_fingerprint,
    materialize,
)
from src.evaluation.generation_contract import (
    CURRENT_LANGUAGE_COMPLETE,
    prompt_contract_sha256,
)


SOURCE_NAMES = [
    "final_consensus_map_qwen_python.json",
    "final_consensus_map_llama_python.json",
    "final_consensus_map_qwen_java.json",
    "final_consensus_map_llama_java.json",
    "final_consensus_map_qwen.json",
    "final_consensus_map_llama.json",
    "final_norules_map.json",
]


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


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
        "prompt_profile": CURRENT_LANGUAGE_COMPLETE,
        "prompt_contract_sha256": prompt_contract_sha256(
            CURRENT_LANGUAGE_COMPLETE
        ),
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
            "prompt_profile": CURRENT_LANGUAGE_COMPLETE,
            "prompt_contract_sha256": prompt_contract_sha256(
                CURRENT_LANGUAGE_COMPLETE
            ),
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
    map_dir = tmp_path / "maps"
    map_dir.mkdir()
    for name in SOURCE_NAMES:
        shutil.copy2(Path("rule_maps") / name, map_dir / name)

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
    assert result["language_counts"] == {"python": 183, "java": 109}
    assert set(result["exclusions"]) == {"518", "640", "959", "1061", "1357"}
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
        assert len(python_map["mappings"]) == 183
        assert len(java_map["mappings"]) == 109
        assert len(combined["mappings"]) == 292
        assert combined["artifact_type"] == "qualified_rule_map"
        assert (
            combined["metadata"]["search_qualification"]["evidence_status"]
            == "final"
        )
        assert (
            combined["metadata"]["search_qualification"]["policy"]
            == "frozen_cross_model_temp0_intersection"
        )
    norules = json.loads((output_dir / "final_search_norules_map.json").read_text())
    assert len(norules["mappings"]) == 292
    assert len(
        json.loads((output_dir / "final_search_norules_map_python.json").read_text())[
            "mappings"
        ]
    ) == 183
    assert len(
        json.loads((output_dir / "final_search_norules_map_java.json").read_text())[
            "mappings"
        ]
    ) == 109


def test_materializer_rejects_validation_after_evidence_changes(tmp_path: Path) -> None:
    map_dir = tmp_path / "maps"
    map_dir.mkdir()
    for name in SOURCE_NAMES:
        shutil.copy2(Path("rule_maps") / name, map_dir / name)
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
