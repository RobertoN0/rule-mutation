#!/usr/bin/env python3
"""
rule_retrieval_mapping_local.py — Local (DelftBlue) version of rule retrieval mapping.

Uses a locally-hosted model (e.g., Qwen2.5-Coder-32B-Instruct) on DelftBlue GPU
nodes to map CyberSecEval prompts to CodeGuard rules.  No cloud API required.

Unlike the Claude/OpenAI versions that use multi-round tool calling, this script
uses a single-turn prompt with the guidelines list embedded directly.  This is
functionally equivalent: the tool-calling loop always follows the same 2-step
pattern (list -> select), so we skip the round-trip by providing the list upfront.

Output format is compatible with run_with_rules_map.py --rules-map.

Prerequisites
─────────────
  conda activate sbst
  # Model must be pre-cached in /scratch/$USER/models

Usage
─────
  # On a SLURM GPU node (recommended):
  sbatch scripts/slurm/slurm_rule_retrieval_local.sh

  # Direct (on a GPU node with sbst env active):
  python pipeline_breakdown/rule_retrieval_mapping_local.py --limit-per-cwe 5

  # Expand coverage, skipping already-mapped prompts:
  python pipeline_breakdown/rule_retrieval_mapping_local.py \\
      --limit-per-cwe 10 \\
      --exclude-map pipeline_breakdown/rule_retrieval_output/prev_run.json

  # Dry run:
  python pipeline_breakdown/rule_retrieval_mapping_local.py --dry-run
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import time
from collections import Counter
from datetime import datetime
from pathlib import Path

import pandas as pd
import yaml
from datasets import load_dataset


# ── Project root resolution (same pattern as run_with_rules_map.py) ─────────
def _resolve_project_root() -> Path:
    """Resolve repository root by searching upward for src/ and scripts/ dirs."""
    this_file = Path(__file__).resolve()
    for parent in [this_file.parent, *this_file.parents]:
        if (parent / "src").is_dir() and (parent / "scripts").is_dir():
            return parent
    raise RuntimeError("Could not resolve project root from script location")


PROJECT_ROOT = _resolve_project_root()
sys.path.insert(0, str(PROJECT_ROOT))

from src.llm_backends.delftblue_local_backend import DelftBlueLocalBackend
from src.llm_backends.base import LLMConfig, LLMError, LLMResponse


# ═════════════════════════════════════════════════════════════════════════════
# CONFIGURATION
# ═════════════════════════════════════════════════════════════════════════════

DEFAULT_MODEL = "Qwen/Qwen2.5-Coder-32B-Instruct"
MAX_TOKENS = 1024
TEMPERATURE = 0.0

# ── Paths ────────────────────────────────────────────────────────────────────
RULES_DIR = PROJECT_ROOT / "project-codeguard" / "skills" / "software-security" / "rules"
OUTPUT_DIR = PROJECT_ROOT / "pipeline_breakdown" / "rule_retrieval_output"

# ── Language -> file extension (for dataset loading) ─────────────────────────
LANG_EXTENSIONS = {
    "python": ".py", "javascript": ".js", "java": ".java", "c": ".c",
    "cpp": ".cpp", "php": ".php", "rust": ".rs", "csharp": ".cs",
}

# ── Prompt template version tag ──────────────────────────────────────────────
PROMPT_TEMPLATE_VERSION = "v1_with_reasoning"


# ═════════════════════════════════════════════════════════════════════════════
# SYSTEM PROMPT
# ═════════════════════════════════════════════════════════════════════════════
# Single-turn equivalent of the Cisco CodeGuard MCP tool-calling flow.
# The guidelines list is embedded directly so no tool round-trip is needed.
#
# Framing follows Cisco's neutral approach: "coding guideline tools" (not
# "security rules") to avoid priming the model toward security-biased output.
#
# v1_with_reasoning: one sentence per rule + JSON array of IDs.
# Future v2_ids_only: JSON array only (no reasoning).

SYSTEM_MESSAGE_TEMPLATE = """\
You are a software engineer with access to coding guideline tools.
Before writing code, check the available guidelines for any relevant coding \
guidelines applicable to the task.

{guidelines_list}

For the given code-generation prompt, select ALL guidelines that you would \
consult before writing code.
For each selected guideline, write one sentence explaining why it is relevant.
Then output a JSON array containing ONLY the selected rule IDs on its own line.

Example output:
- codeguard-0-input-validation-injection: The prompt handles user input that \
needs validation.
- codeguard-0-framework-and-languages: Python-specific framework guidance applies.

["codeguard-0-input-validation-injection", "codeguard-0-framework-and-languages"]

Do NOT generate any code. Just identify, explain briefly, and select the \
relevant guidelines.\
"""


# ═════════════════════════════════════════════════════════════════════════════
# RULE LOADING
# ═════════════════════════════════════════════════════════════════════════════

def load_rules() -> dict[str, dict]:
    """Load all rule files -> {rule_id: {description, content}}."""
    rules: dict[str, dict] = {}
    for rf in sorted(RULES_DIR.glob("*.md")):
        content = rf.read_text(encoding="utf-8")
        rule_id = rf.stem
        description = ""
        if content.startswith("---"):
            parts = content.split("---", 2)
            if len(parts) >= 3:
                try:
                    meta = yaml.safe_load(parts[1])
                    description = meta.get("description", "")
                except Exception:
                    pass
        rules[rule_id] = {"description": description, "content": content}
    return rules


def build_list_guidelines_response(rules: dict[str, dict]) -> str:
    """Produce the guidelines list (same text the MCP list_available_guidelines returns)."""
    lines: list[str] = ["Available Guidelines:\n"]
    for rule_id, data in rules.items():
        lines.append(f"- {rule_id}: {data['description']}")
    return "\n".join(lines)


# ═════════════════════════════════════════════════════════════════════════════
# DATASET LOADING
# ═════════════════════════════════════════════════════════════════════════════

def load_cyberseceval() -> pd.DataFrame:
    """Load walledai/CyberSecEval instruct dataset (all 8 languages)."""
    print("Loading CyberSecEval dataset...")
    dataset = load_dataset("walledai/CyberSecEval", "instruct")
    frames = []
    for lang in LANG_EXTENSIONS:
        if lang in dataset:  # type: ignore[operator]
            lang_df = pd.DataFrame(dataset[lang])  # type: ignore[index]
            lang_df["language"] = lang
            frames.append(lang_df)
            print(f"   {lang:<12} -> {len(lang_df):>4} prompts")
    df = pd.concat(frames, ignore_index=True)
    print(f"   Total: {len(df)} prompts, "
          f"{df['cwe_identifier'].nunique()} CWEs, "
          f"{df['language'].nunique()} languages")

    cwe_stats = df.groupby("cwe_identifier").agg(
        prompts=("prompt", "count"),
        languages=("language", "nunique"),
        lang_list=("language", lambda x: sorted(x.unique().tolist())),
    ).sort_index()
    print(f"\n   {'CWE':<12} {'Prompts':>8} {'Languages':>10}  Languages")
    print(f"   {'-' * 60}")
    for cwe_id, row in cwe_stats.iterrows():
        print(f"   {cwe_id:<12} {row['prompts']:>8} {row['languages']:>10}  "
              f"{', '.join(row['lang_list'])}")

    return df


def select_prompts(
    df: pd.DataFrame,
    target_cwes: list[str] | None,
    target_languages: list[str] | None,
    limit_per_cwe: int | None,
    total_limit: int | None,
    exclude_hashes: set[str] | None = None,
) -> list[dict]:
    """Filter and flatten the dataset into a list of prompt dicts."""
    cwe_list = (
        sorted(df["cwe_identifier"].unique().tolist())
        if target_cwes is None
        else target_cwes
    )
    selected: list[dict] = []
    excluded_count = 0

    for cwe_id in cwe_list:
        subset = df[df["cwe_identifier"] == cwe_id]
        if target_languages:
            subset = subset[subset["language"].isin(target_languages)]

        cwe_count = 0
        for _, row in subset.iterrows():
            prompt_hash = hashlib.sha256(row["prompt"].encode()).hexdigest()[:16]

            if exclude_hashes and prompt_hash in exclude_hashes:
                excluded_count += 1
                continue

            selected.append({
                "cwe_id": cwe_id,
                "language": row["language"],
                "prompt": row["prompt"],
                "prompt_hash": prompt_hash,
            })
            cwe_count += 1

            if limit_per_cwe and cwe_count >= limit_per_cwe:
                break

    if total_limit and len(selected) > total_limit:
        selected = selected[:total_limit]

    if exclude_hashes and excluded_count > 0:
        print(f"   Excluded {excluded_count} prompts already in existing mapping")

    return selected


def load_exclude_hashes(exclude_map_path: Path) -> set[str]:
    """Load prompt hashes from an existing mapping file to skip."""
    with open(exclude_map_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    hashes = set()
    for entry in data.get("mappings", []):
        if "prompt_hash" in entry:
            hashes.add(entry["prompt_hash"])
    print(f"   Loaded {len(hashes)} existing prompt hashes from {exclude_map_path}")
    return hashes


# ═════════════════════════════════════════════════════════════════════════════
# RESPONSE PARSING
# ═════════════════════════════════════════════════════════════════════════════

def parse_rule_ids(
    raw_response: str,
    valid_rule_ids: set[str],
) -> tuple[list[str], str]:
    """
    Extract rule IDs from the model's raw response.

    Returns (rule_ids, parse_method) where parse_method is one of:
      - "json": clean JSON array found and parsed
      - "regex_fallback": fell back to regex extraction
      - "failed": could not extract any valid rule IDs
    """
    # Strategy 1: find JSON array(s) in the response, try the last one first
    json_arrays = re.findall(
        r'\[(?:[^\[\]]*"[^"]*"[^\[\]]*(?:,[^\[\]]*"[^"]*"[^\[\]]*)*)\]',
        raw_response,
    )

    for candidate in reversed(json_arrays):
        try:
            parsed = json.loads(candidate)
            if isinstance(parsed, list) and all(isinstance(x, str) for x in parsed):
                valid = [r for r in parsed if r in valid_rule_ids]
                if valid:
                    return valid, "json"
        except (json.JSONDecodeError, TypeError):
            continue

    # Strategy 2: regex fallback -- find known rule IDs mentioned in the text
    found = []
    for rule_id in valid_rule_ids:
        if rule_id in raw_response:
            found.append(rule_id)

    if found:
        found.sort(key=lambda r: raw_response.index(r))
        return found, "regex_fallback"

    return [], "failed"


# ═════════════════════════════════════════════════════════════════════════════
# CORE: SINGLE-TURN RETRIEVAL
# ═════════════════════════════════════════════════════════════════════════════

def retrieve_rules_for_prompt(
    backend: DelftBlueLocalBackend,
    prompt: str,
    valid_rule_ids: set[str],
    system_message: str,
) -> dict:
    """
    Run single-turn rule retrieval for one prompt.

    Returns a dict with rules_retrieved, raw_response, parse_method,
    token counts and latency.
    """
    messages = [{"role": "user", "content": prompt}]

    response: LLMResponse = backend.generate(
        system=system_message,
        messages=messages,
    )

    rules_retrieved, parse_method = parse_rule_ids(
        response.content, valid_rule_ids
    )

    return {
        "rules_retrieved": rules_retrieved,
        "num_rules": len(rules_retrieved),
        "raw_response": response.content,
        "parse_method": parse_method,
        "input_tokens": response.input_tokens,
        "output_tokens": response.output_tokens,
        "latency_ms": response.latency_ms,
    }


# ═════════════════════════════════════════════════════════════════════════════
# PROGRESS FILE (for resume capability)
# ═════════════════════════════════════════════════════════════════════════════

def load_progress(progress_path: Path) -> dict[int, dict]:
    """Load completed entries from a JSONL progress file -> {index: entry}."""
    completed: dict[int, dict] = {}
    if progress_path.exists():
        with open(progress_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    entry = json.loads(line)
                    completed[entry["index"]] = entry
    return completed


def append_progress(progress_path: Path, entry: dict) -> None:
    """Append one completed entry to the JSONL progress file."""
    with open(progress_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


# ═════════════════════════════════════════════════════════════════════════════
# COMPILE FINAL OUTPUT
# ═════════════════════════════════════════════════════════════════════════════

def compile_mapping(
    completed: dict[int, dict],
    args: argparse.Namespace,
    model_id: str,
    system_message: str,
    model_config: dict | None = None,
) -> dict:
    """Build the final JSON mapping from completed progress entries."""
    mappings = list(completed[idx] for idx in sorted(completed.keys()))

    all_rules = [r for m in mappings for r in m["rules_retrieved"]]
    rule_freq = Counter(all_rules)
    parse_methods = Counter(m.get("parse_method", "unknown") for m in mappings)

    return {
        "metadata": {
            "model": model_id,
            "timestamp": datetime.now().strftime("%Y%m%d_%H%M%S"),
            "total_prompts": len(mappings),
            "unique_rules_used": len(rule_freq),
            "avg_rules_per_prompt": round(
                sum(m["num_rules"] for m in mappings) / max(len(mappings), 1), 2
            ),
            "total_input_tokens": sum(m.get("input_tokens", 0) for m in mappings),
            "total_output_tokens": sum(m.get("output_tokens", 0) for m in mappings),
            "total_latency_ms": round(
                sum(m.get("latency_ms", 0) for m in mappings), 1
            ),
            "avg_latency_ms": round(
                sum(m.get("latency_ms", 0) for m in mappings)
                / max(len(mappings), 1),
                1,
            ),
            "dataset": "walledai/CyberSecEval",
            "config": {
                "target_cwes": args.cwes,
                "target_languages": args.languages,
                "limit_per_cwe": args.limit_per_cwe,
                "total_limit": args.total_limit,
                "exclude_map": str(args.exclude_map) if args.exclude_map else None,
            },
            "model_config": model_config,
            "prompt_template_version": PROMPT_TEMPLATE_VERSION,
            "system_prompt": system_message,
            "parse_method_stats": dict(parse_methods),
        },
        "rule_frequency": dict(rule_freq.most_common()),
        "mappings": mappings,
    }


# ═════════════════════════════════════════════════════════════════════════════
# MAIN
# ═════════════════════════════════════════════════════════════════════════════

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Map CyberSecEval prompts -> CodeGuard rules via local model on DelftBlue"
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Show prompt selection and exit without running inference.",
    )
    parser.add_argument(
        "--cwes", nargs="+", default=None,
        help="CWE IDs to include (default: all).",
    )
    parser.add_argument(
        "--languages", nargs="+", default=None,
        help="Languages to include (default: all).",
    )
    parser.add_argument(
        "--limit-per-cwe", type=int, default=None,
        help="Max prompts per CWE (default: all).",
    )
    parser.add_argument(
        "--total-limit", type=int, default=None,
        help="Hard cap on total prompts across all CWEs.",
    )
    parser.add_argument(
        "--exclude-map", type=Path, default=None,
        help="Path to existing retrieval map JSON -- skip prompts already mapped.",
    )
    parser.add_argument(
        "--resume", type=str, default=None, metavar="PROGRESS_FILE",
        help="Resume from an existing progress JSONL file.",
    )
    parser.add_argument(
        "--output", type=str, default=None,
        help="Output JSON file path (default: auto-generated in output dir).",
    )
    parser.add_argument(
        "--model", default=DEFAULT_MODEL,
        help=f"HuggingFace model ID (default: {DEFAULT_MODEL}).",
    )
    parser.add_argument(
        "--quantization", default="fp16", choices=["fp16", "4bit"],
        help="Quantization mode (default: fp16).",
    )
    parser.add_argument(
        "--max-tokens", type=int, default=MAX_TOKENS,
        help=f"Max output tokens per prompt (default: {MAX_TOKENS}).",
    )
    parser.add_argument(
        "--yes", "-y", action="store_true",
        help="Skip confirmation prompt (for non-interactive SLURM jobs).",
    )
    args = parser.parse_args()

    # ── Load rules ───────────────────────────────────────────────────────
    rules = load_rules()
    guidelines_text = build_list_guidelines_response(rules)
    valid_rule_ids = set(rules.keys())
    print(f"Loaded {len(rules)} CodeGuard rules from {RULES_DIR}")

    system_message = SYSTEM_MESSAGE_TEMPLATE.format(guidelines_list=guidelines_text)

    # ── Load exclusion set ───────────────────────────────────────────────
    exclude_hashes: set[str] | None = None
    if args.exclude_map:
        if not args.exclude_map.exists():
            print(f"ERROR: Exclude map not found: {args.exclude_map}")
            sys.exit(1)
        exclude_hashes = load_exclude_hashes(args.exclude_map)

    # ── Load dataset ─────────────────────────────────────────────────────
    df = load_cyberseceval()
    prompts = select_prompts(
        df,
        target_cwes=args.cwes,
        target_languages=args.languages,
        limit_per_cwe=args.limit_per_cwe,
        total_limit=args.total_limit,
        exclude_hashes=exclude_hashes,
    )
    print(f"\nSelected {len(prompts)} prompts")

    if args.dry_run:
        print("\nDry run -- not running inference.")
        print(f"\nExample prompts (first 3):")
        for i, p in enumerate(prompts[:3]):
            print(f"  [{i}] {p['cwe_id']} ({p['language']}): "
                  f"{p['prompt'][:80]}...")
        print(f"\nSystem message length: {len(system_message)} chars")
        print(f"Template version: {PROMPT_TEMPLATE_VERSION}")
        return

    if not prompts:
        print("No prompts to process.")
        return

    # ── Confirm ──────────────────────────────────────────────────────────
    if not args.yes:
        answer = input(
            f"\nRun retrieval for {len(prompts)} prompts with {args.model}? [y/N] "
        ).strip().lower()
        if answer != "y":
            print("Aborted.")
            return

    # ── Setup progress ───────────────────────────────────────────────────
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    if args.resume:
        progress_path = Path(args.resume)
    else:
        progress_path = OUTPUT_DIR / f"rule_retrieval_progress_local_{timestamp}.jsonl"

    completed = load_progress(progress_path)
    print(f"Progress file: {progress_path}")
    if completed:
        print(f"   Resuming -- {len(completed)} prompts already completed")

    # ── Initialize backend ───────────────────────────────────────────────
    print(f"\nInitializing local backend: {args.model}")
    print(f"   Quantization: {args.quantization}")

    config = LLMConfig(
        model=args.model,
        temperature=TEMPERATURE,
        max_tokens=args.max_tokens,
        extra={
            "quantization": args.quantization,
            "local_files_only": True,
            "trust_remote_code": True,
        },
    )

    try:
        backend = DelftBlueLocalBackend(config)
        if not backend.is_available():
            print("ERROR: Model not found in local cache or CUDA unavailable")
            print("   Hint: Set HF_HOME=/scratch/$USER/models")
            sys.exit(1)
        print("   Model found in local cache")
    except LLMError as e:
        print(f"ERROR initializing backend: {e}")
        sys.exit(1)

    # ── Run retrieval loop ───────────────────────────────────────────────
    total = len(prompts)
    start_time = time.time()
    model_config_captured: dict | None = None

    print(f"\nStarting retrieval for {total} prompts...\n")

    for idx, item in enumerate(prompts):
        if idx in completed:
            continue

        cwe_id = item["cwe_id"]
        language = item["language"]
        prompt = item["prompt"]
        prompt_hash = item["prompt_hash"]

        print(
            f"  [{idx + 1}/{total}] {cwe_id} ({language})",
            end="",
            flush=True,
        )

        try:
            result = retrieve_rules_for_prompt(
                backend, prompt, valid_rule_ids, system_message
            )
        except LLMError as e:
            print(f" ERROR: {e}")
            continue

        if model_config_captured is None:
            model_config_captured = {
                "quantization": args.quantization,
                "model": args.model,
                "max_tokens": args.max_tokens,
                "temperature": TEMPERATURE,
            }

        entry = {
            "index": idx,
            "cwe_id": cwe_id,
            "language": language,
            "prompt_hash": prompt_hash,
            "prompt": prompt,
            "rules_retrieved": result["rules_retrieved"],
            "num_rules": result["num_rules"],
            "raw_response": result["raw_response"],
            "parse_method": result["parse_method"],
            "input_tokens": result["input_tokens"],
            "output_tokens": result["output_tokens"],
            "latency_ms": round(result["latency_ms"], 1),
        }

        append_progress(progress_path, entry)
        completed[idx] = entry

        print(
            f" -> {result['num_rules']} rules "
            f"[{result['parse_method']}] "
            f"({result['input_tokens']}+{result['output_tokens']} tok, "
            f"{result['latency_ms']:.0f}ms)"
        )

    elapsed = time.time() - start_time

    # ── Compile final mapping ────────────────────────────────────────────
    mapping = compile_mapping(
        completed, args,
        model_id=args.model,
        system_message=system_message,
        model_config=model_config_captured,
    )

    if args.output:
        out_path = Path(args.output)
    else:
        model_short = args.model.split("/")[-1].lower().replace("-", "_")
        out_path = OUTPUT_DIR / f"retrieval_map_local_{model_short}_{timestamp}.json"

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(mapping, f, indent=2, ensure_ascii=False)

    # ── Summary ──────────────────────────────────────────────────────────
    meta = mapping["metadata"]
    print(f"\n{'=' * 70}")
    print(f"RETRIEVAL MAPPING COMPLETE")
    print(f"{'=' * 70}")
    print(f"   Model:                 {args.model}")
    print(f"   Quantization:          {args.quantization}")
    print(f"   Prompt template:       {PROMPT_TEMPLATE_VERSION}")
    print(f"   Prompts processed:     {meta['total_prompts']}")
    print(f"   Unique rules used:     {meta['unique_rules_used']} / {len(rules)}")
    print(f"   Avg rules per prompt:  {meta['avg_rules_per_prompt']}")
    print(f"   Avg latency:           {meta['avg_latency_ms']:.0f}ms")
    print(f"   Total input tokens:    {meta['total_input_tokens']:,}")
    print(f"   Total output tokens:   {meta['total_output_tokens']:,}")
    print(f"   Elapsed time:          {elapsed / 60:.1f} min")
    print(f"   Parse methods:         {meta['parse_method_stats']}")
    print(f"\n   Mapping saved: {out_path}")
    print(f"   Progress file: {progress_path}")

    print(f"\nRule frequency (top 10):")
    for rule_id, count in list(mapping["rule_frequency"].items())[:10]:
        print(f"   {rule_id:<50} {count:>5}x")

    print(f"\n{'=' * 70}")
    print(f"Next step: use this mapping in the SBST pipeline:")
    print(f"  python scripts/experiments/run_with_rules_map.py --rules-map {out_path}")
    print(f"{'=' * 70}")


if __name__ == "__main__":
    main()
