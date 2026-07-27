"""Shared data, parsing, progress, and output helpers for local rule retrieval."""

from __future__ import annotations

import argparse
import hashlib
import json
import random
import re
from collections import Counter
from datetime import datetime
from pathlib import Path

import pandas as pd
import yaml
from datasets import load_dataset


def _resolve_project_root() -> Path:
    """Resolve the repository root from this module's location."""
    this_file = Path(__file__).resolve()
    for parent in [this_file.parent, *this_file.parents]:
        if (parent / "src").is_dir() and (parent / "scripts").is_dir():
            return parent
    raise RuntimeError("Could not resolve project root from script location")


PROJECT_ROOT = _resolve_project_root()
DEFAULT_MODEL = "Qwen/Qwen2.5-Coder-32B-Instruct"
MAX_TOKENS = 1024
TEMPERATURE = 0.0
RULES_DIR = (
    PROJECT_ROOT
    / "project-codeguard"
    / "skills"
    / "software-security"
    / "rules"
)
OUTPUT_DIR = PROJECT_ROOT / "rule_maps"

LANG_EXTENSIONS = {
    "python": ".py",
    "javascript": ".js",
    "java": ".java",
    "c": ".c",
    "cpp": ".cpp",
    "php": ".php",
    "rust": ".rs",
    "csharp": ".cs",
}


def seed_everything(seed: int) -> None:
    """Seed the local generation stack once for a complete retrieval repetition."""
    try:
        from transformers import set_seed

        set_seed(seed)
    except Exception as err:
        random.seed(seed)
        print(
            "⚠️  transformers.set_seed unavailable "
            f"({err}); seeded stdlib random only"
        )


def load_rules() -> dict[str, dict]:
    """Load CodeGuard rule files keyed by their rule identifiers."""
    rules: dict[str, dict] = {}
    for rule_file in sorted(RULES_DIR.glob("*.md")):
        content = rule_file.read_text(encoding="utf-8")
        description = ""
        if content.startswith("---"):
            parts = content.split("---", 2)
            if len(parts) >= 3:
                try:
                    metadata = yaml.safe_load(parts[1])
                    description = metadata.get("description", "")
                except Exception:
                    pass
        rules[rule_file.stem] = {
            "description": description,
            "content": content,
        }
    return rules


def build_list_guidelines_response(rules: dict[str, dict]) -> str:
    """Format the guideline catalog embedded in the retrieval system message."""
    lines: list[str] = ["Available Guidelines:\n"]
    for rule_id, data in rules.items():
        lines.append(f"- {rule_id}: {data['description']}")
    return "\n".join(lines)


def load_cyberseceval() -> pd.DataFrame:
    """Load all language splits of the CyberSecEval instruct dataset."""
    print("Loading CyberSecEval dataset...")
    dataset = load_dataset("walledai/CyberSecEval", "instruct")
    frames = []
    for language in LANG_EXTENSIONS:
        if language in dataset:  # type: ignore[operator]
            language_frame = pd.DataFrame(dataset[language])  # type: ignore[index]
            language_frame["language"] = language
            frames.append(language_frame)
            print(f"   {language:<12} -> {len(language_frame):>4} prompts")

    frame = pd.concat(frames, ignore_index=True)
    print(
        f"   Total: {len(frame)} prompts, "
        f"{frame['cwe_identifier'].nunique()} CWEs, "
        f"{frame['language'].nunique()} languages"
    )

    cwe_stats = (
        frame.groupby("cwe_identifier")
        .agg(
            prompts=("prompt", "count"),
            languages=("language", "nunique"),
            lang_list=("language", lambda values: sorted(values.unique().tolist())),
        )
        .sort_index()
    )
    print(f"\n   {'CWE':<12} {'Prompts':>8} {'Languages':>10}  Languages")
    print(f"   {'-' * 60}")
    for cwe_id, row in cwe_stats.iterrows():
        print(
            f"   {cwe_id:<12} {row['prompts']:>8} {row['languages']:>10}  "
            f"{', '.join(row['lang_list'])}"
        )
    return frame


def select_prompts(
    frame: pd.DataFrame,
    target_cwes: list[str] | None,
    target_languages: list[str] | None,
    limit_per_cwe: int | None,
    total_limit: int | None,
    exclude_hashes: set[str] | None = None,
) -> list[dict]:
    """Filter the dataset and return the selected prompt records."""
    cwe_list = (
        sorted(frame["cwe_identifier"].unique().tolist())
        if target_cwes is None
        else target_cwes
    )
    selected: list[dict] = []
    excluded_count = 0

    for cwe_id in cwe_list:
        subset = frame[frame["cwe_identifier"] == cwe_id]
        if target_languages:
            subset = subset[subset["language"].isin(target_languages)]

        cwe_count = 0
        for _, row in subset.iterrows():
            prompt_hash = hashlib.sha256(row["prompt"].encode()).hexdigest()[:16]
            if exclude_hashes and prompt_hash in exclude_hashes:
                excluded_count += 1
                continue

            selected.append(
                {
                    "cwe_id": cwe_id,
                    "language": row["language"],
                    "prompt": row["prompt"],
                    "prompt_hash": prompt_hash,
                }
            )
            cwe_count += 1
            if limit_per_cwe and cwe_count >= limit_per_cwe:
                break

    if total_limit and len(selected) > total_limit:
        selected = selected[:total_limit]
    if exclude_hashes and excluded_count > 0:
        print(f"   Excluded {excluded_count} prompts already in existing mapping")
    return selected


def load_prompts_from_maps(map_paths: list[Path]) -> list[dict]:
    """Load the exact ordered prompt population stored in existing maps."""
    selected: list[dict] = []
    for map_path in map_paths:
        data = json.loads(Path(map_path).read_text(encoding="utf-8"))
        mappings = data.get("mappings", [])
        for entry in mappings:
            selected.append(
                {
                    "index": entry["index"],
                    "cwe_id": entry["cwe_id"],
                    "language": entry["language"],
                    "prompt": entry["prompt"],
                    "prompt_hash": entry["prompt_hash"],
                }
            )
        print(f"   Loaded {len(mappings)} prompts from {map_path}")
    return selected


def load_exclude_hashes(exclude_map_path: Path) -> set[str]:
    """Load prompt hashes from a map that must be excluded."""
    data = json.loads(exclude_map_path.read_text(encoding="utf-8"))
    hashes = {
        entry["prompt_hash"]
        for entry in data.get("mappings", [])
        if "prompt_hash" in entry
    }
    print(f"   Loaded {len(hashes)} existing prompt hashes from {exclude_map_path}")
    return hashes


def parse_rule_ids(
    raw_response: str,
    valid_rule_ids: set[str],
) -> tuple[list[str], str]:
    """Extract valid rule IDs from a retrieval response."""
    json_arrays = re.findall(
        r'\[(?:[^\[\]]*"[^"]*"[^\[\]]*(?:,[^\[\]]*"[^"]*"[^\[\]]*)*)\]',
        raw_response,
    )
    for candidate in reversed(json_arrays):
        try:
            parsed = json.loads(candidate)
            if isinstance(parsed, list) and all(
                isinstance(value, str) for value in parsed
            ):
                valid = [rule_id for rule_id in parsed if rule_id in valid_rule_ids]
                if valid:
                    return valid, "json"
        except (json.JSONDecodeError, TypeError):
            continue

    found = [
        rule_id for rule_id in valid_rule_ids if rule_id in raw_response
    ]
    if found:
        found.sort(key=lambda rule_id: raw_response.index(rule_id))
        return found, "regex_fallback"
    return [], "failed"


def load_progress(progress_path: Path) -> dict[int, dict]:
    """Load completed progress records keyed by sweep position."""
    completed: dict[int, dict] = {}
    if progress_path.exists():
        with progress_path.open("r", encoding="utf-8") as progress_file:
            for line in progress_file:
                if line := line.strip():
                    entry = json.loads(line)
                    position = entry.get("_progress_position", entry["index"])
                    completed[int(position)] = entry
    return completed


def append_progress(progress_path: Path, entry: dict) -> None:
    """Append one completed prompt record to a JSONL progress file."""
    with progress_path.open("a", encoding="utf-8") as progress_file:
        progress_file.write(json.dumps(entry, ensure_ascii=False) + "\n")


def compile_mapping(
    completed: dict[int, dict],
    args: argparse.Namespace,
    model_id: str,
    system_message: str,
    model_config: dict | None = None,
    seed: int | None = None,
    from_map: list[Path] | None = None,
) -> dict:
    """Build one retrieval-map artifact from completed prompt records."""
    mappings = []
    for position in sorted(completed):
        entry = dict(completed[position])
        entry.pop("_progress_position", None)
        mappings.append(entry)

    rule_frequency = Counter(
        rule_id for mapping in mappings for rule_id in mapping["rules_retrieved"]
    )
    parse_methods = Counter(
        mapping.get("parse_method", "unknown") for mapping in mappings
    )
    total_latency_ms = sum(
        mapping.get("latency_ms", 0) for mapping in mappings
    )

    return {
        "metadata": {
            "model": model_id,
            "timestamp": datetime.now().strftime("%Y%m%d_%H%M%S"),
            "seed": seed,
            "temperature": args.temperature,
            "total_prompts": len(mappings),
            "unique_rules_used": len(rule_frequency),
            "avg_rules_per_prompt": round(
                sum(mapping["num_rules"] for mapping in mappings)
                / max(len(mappings), 1),
                2,
            ),
            "total_input_tokens": sum(
                mapping.get("input_tokens", 0) for mapping in mappings
            ),
            "total_output_tokens": sum(
                mapping.get("output_tokens", 0) for mapping in mappings
            ),
            "total_latency_ms": round(total_latency_ms, 1),
            "avg_latency_ms": round(total_latency_ms / max(len(mappings), 1), 1),
            "dataset": "walledai/CyberSecEval",
            "config": {
                "from_map": [str(path) for path in from_map] if from_map else None,
                "target_cwes": args.cwes,
                "target_languages": args.languages,
                "limit_per_cwe": args.limit_per_cwe,
                "total_limit": args.total_limit,
                "exclude_map": (
                    str(args.exclude_map) if args.exclude_map else None
                ),
            },
            "model_config": model_config,
            "system_prompt": system_message,
            "parse_method_stats": dict(parse_methods),
        },
        "rule_frequency": dict(rule_frequency.most_common()),
        "mappings": mappings,
    }
