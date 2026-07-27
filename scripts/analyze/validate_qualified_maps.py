#!/usr/bin/env python3
"""Validate the final qualified task-to-rule maps and their provenance index."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from src.evaluation.population_screening import (  # noqa: E402
    FINAL_SEARCH_POPULATION_POLICY,
)
from src.retrieval.population import population_fingerprint  # noqa: E402


MODELS = ("qwen", "llama")
LANGUAGES = ("python", "java")
EXPECTED_MAPS = {
    *(f"final_search_map_{model}.json" for model in MODELS),
    *(
        f"final_search_map_{model}_{language}.json"
        for model in MODELS
        for language in LANGUAGES
    ),
    "final_search_norules_map.json",
    *(f"final_search_norules_map_{language}.json" for language in LANGUAGES),
}


def _json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path}: expected a JSON object")
    return payload


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _task_ids(payload: dict[str, Any]) -> list[str]:
    mappings = payload.get("mappings")
    if not isinstance(mappings, list):
        raise ValueError("map lacks a mappings list")
    task_ids = [str(row.get("index")) for row in mappings]
    if len(task_ids) != len(set(task_ids)):
        raise ValueError("map contains duplicate task IDs")
    return task_ids


def _task_content(payload: dict[str, Any]) -> dict[str, tuple[Any, ...]]:
    return {
        str(row["index"]): (
            row.get("prompt_hash"),
            row.get("prompt"),
            row.get("cwe_id"),
            str(row.get("language", "")).lower(),
        )
        for row in payload["mappings"]
    }


def validate_qualified_maps(map_dir: Path) -> dict[str, Any]:
    map_dir = map_dir.resolve()
    issues: list[str] = []
    counts: dict[str, int] = {}
    try:
        manifest_path = map_dir / "final_search_population_manifest.json"
        manifest = _json(manifest_path)
        if manifest.get("artifact_type") != "qualified_population_manifest":
            issues.append("population manifest has the wrong artifact_type")
        if manifest.get("evidence_status") != "final":
            issues.append("population manifest is not final")
        if manifest.get("policy") != FINAL_SEARCH_POPULATION_POLICY:
            issues.append("population manifest uses the wrong selection policy")

        manifest_task_ids: dict[str, list[str]] = {}
        for language in LANGUAGES:
            ids = [
                str(task_id)
                for task_id in manifest.get("task_ids", {}).get(language, [])
            ]
            if len(ids) != len(set(ids)):
                issues.append(f"manifest has duplicate {language} task IDs")
            if manifest.get("language_counts", {}).get(language) != len(ids):
                issues.append(f"manifest {language} count does not reconcile")
            manifest_task_ids[language] = ids
            counts[language] = len(ids)
        if set(manifest_task_ids["python"]) & set(manifest_task_ids["java"]):
            issues.append("Python and Java task IDs overlap")

        outputs = manifest.get("outputs")
        if not isinstance(outputs, dict) or set(outputs) != EXPECTED_MAPS:
            issues.append("population manifest does not index all nine final maps")
            outputs = outputs if isinstance(outputs, dict) else {}

        maps: dict[str, dict[str, Any]] = {}
        for filename in EXPECTED_MAPS:
            path = map_dir / filename
            if not path.is_file():
                issues.append(f"missing final map: {filename}")
                continue
            payload = _json(path)
            maps[filename] = payload
            indexed = outputs.get(filename, {})
            if indexed.get("sha256") != _sha256(path):
                issues.append(f"{filename}: SHA-256 differs from population manifest")
            if payload.get("artifact_type") != "qualified_rule_map":
                issues.append(f"{filename}: wrong artifact_type")
            metadata = payload.get("metadata")
            if not isinstance(metadata, dict):
                issues.append(f"{filename}: metadata is missing")
                continue
            qualification = metadata.get("search_qualification")
            if not isinstance(qualification, dict):
                issues.append(f"{filename}: search qualification is missing")
                continue
            if (
                metadata.get("evidence_status") != "final"
                or qualification.get("evidence_status") != "final"
            ):
                issues.append(f"{filename}: map evidence is not final")
            if qualification.get("policy") != FINAL_SEARCH_POPULATION_POLICY:
                issues.append(f"{filename}: wrong final population policy")
            ids = _task_ids(payload)
            if indexed.get("prompts") != len(ids):
                issues.append(f"{filename}: prompt count differs from manifest")
            fingerprint = population_fingerprint(payload["mappings"])
            if (
                indexed.get("population_fingerprint") != fingerprint
                or qualification.get("qualified_population_fingerprint")
                != fingerprint
            ):
                issues.append(f"{filename}: population fingerprint mismatch")

            if filename.endswith("_python.json"):
                expected_ids = manifest_task_ids["python"]
            elif filename.endswith("_java.json"):
                expected_ids = manifest_task_ids["java"]
            else:
                expected_ids = (
                    manifest_task_ids["python"] + manifest_task_ids["java"]
                )
            if ids != expected_ids:
                issues.append(f"{filename}: task IDs/order differ from manifest")
            if "norules" in filename and any(
                row.get("rules_retrieved") for row in payload["mappings"]
            ):
                issues.append(f"{filename}: no-rules map contains retrieved rules")

        for language in LANGUAGES:
            qwen_name = f"final_search_map_qwen_{language}.json"
            llama_name = f"final_search_map_llama_{language}.json"
            if qwen_name in maps and llama_name in maps:
                if _task_content(maps[qwen_name]) != _task_content(
                    maps[llama_name]
                ):
                    issues.append(
                        f"Qwen/Llama {language} task content differs"
                    )

        supporting = manifest.get("supporting_artifacts")
        if not isinstance(supporting, dict):
            issues.append("population manifest lacks supporting artifacts")
        else:
            for label, reference in supporting.items():
                if not isinstance(reference, dict):
                    issues.append(f"invalid supporting-artifact entry: {label}")
                    continue
                filename = reference.get("filename")
                if not isinstance(filename, str) or Path(filename).name != filename:
                    issues.append(f"unsafe supporting-artifact filename: {label}")
                    continue
                path = map_dir / filename
                if not path.is_file():
                    issues.append(f"missing supporting artifact: {filename}")
                elif reference.get("sha256") != _sha256(path):
                    issues.append(
                        f"supporting artifact hash mismatch: {filename}"
                    )
    except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
        issues.append(str(exc))

    return {
        "artifact_type": "qualified_maps_validation",
        "map_dir": str(map_dir),
        "status": "VALID" if not issues else "INVALID",
        "issues": issues,
        "counts": counts,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "map_dir",
        nargs="?",
        type=Path,
        default=PROJECT_ROOT / "rule_maps" / "qualified",
    )
    args = parser.parse_args()
    result = validate_qualified_maps(args.map_dir)
    print(json.dumps(result, indent=2))
    return 0 if result["status"] == "VALID" else 1


if __name__ == "__main__":
    raise SystemExit(main())
