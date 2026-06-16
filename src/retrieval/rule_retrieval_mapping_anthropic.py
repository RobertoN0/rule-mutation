#!/usr/bin/env python3
"""
rule_retrieval_mapping_anthropic.py — Discover which CodeGuard rules a Claude
agent retrieves for each CyberSecEval prompt.

Anthropic-API variant of the retrieval step. The companion file
`rule_retrieval_mapping_local.py` is the DelftBlue-local variant; both produce
mappings in the same JSON shape that `scripts/experiments/run_with_rules_map.py`
can consume.

The Claude tool-calling agent sees the same tools as the notebook's MCP server
(list_guidelines / consult_guidelines) and is instructed to retrieve ALL
relevant guidelines. No code is generated — only the retrieval decisions are
recorded.

Prerequisites
─────────────
  # Already covered by the project's pyproject.toml. If installing manually:
  pip install anthropic datasets pandas pyyaml python-dotenv

  # ANTHROPIC_API_KEY must be set in .env
  echo 'ANTHROPIC_API_KEY=sk-ant-...' >> .env

Usage
─────
  # Full run (all 1,916 prompts) with the default model (claude-sonnet-4-6)
  uv run python src/retrieval/rule_retrieval_mapping_anthropic.py

  # Cheap replication run: 1 prompt, Haiku 4.5, non-interactive (~1 cent)
  uv run python src/retrieval/rule_retrieval_mapping_anthropic.py \\
      --cwes CWE-89 --languages python --limit-per-cwe 1 \\
      --model claude-haiku-4-5 \\
      --yes

  # Specific CWEs / languages
  uv run python src/retrieval/rule_retrieval_mapping_anthropic.py \\
      --cwes CWE-89 CWE-79 --languages python java

  # Dry run (estimate cost, don't call the API)
  uv run python src/retrieval/rule_retrieval_mapping_anthropic.py --dry-run

  # Resume an interrupted run
  uv run python src/retrieval/rule_retrieval_mapping_anthropic.py \\
      --resume rule_retrieval_progress_<TIMESTAMP>.jsonl
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path

import anthropic
import pandas as pd
import yaml
from datasets import load_dataset
from dotenv import load_dotenv


# ═════════════════════════════════════════════════════════════════════════════
# CONFIGURATION
# ═════════════════════════════════════════════════════════════════════════════

DEFAULT_MODEL = "claude-sonnet-4-6"

# Low max_tokens — we don't need code generation, just tool calls + a short
# summary of which rules were retrieved.
MAX_TOKENS = 1024
TEMPERATURE = 0.0

# ── Paths ────────────────────────────────────────────────────────────────────
# Resolve relative to the project root so the script works regardless of
# launch directory (previously the relative paths only worked when called
# from the repo root).
def _resolve_project_root() -> Path:
    this_file = Path(__file__).resolve()
    for parent in [this_file.parent, *this_file.parents]:
        if (parent / "src").is_dir() and (parent / "scripts").is_dir():
            return parent
    raise RuntimeError("Could not resolve project root from script location")


PROJECT_ROOT = _resolve_project_root()
RULES_DIR  = PROJECT_ROOT / "project-codeguard" / "skills" / "software-security" / "rules"
OUTPUT_DIR = PROJECT_ROOT / "rule_maps"

# Per-1M-token pricing for the Anthropic models we may use. Falls back to
# Sonnet rates for unknown models so the cost estimate is never zero by accident.
ANTHROPIC_PRICING_USD_PER_MTOK: dict[str, tuple[float, float]] = {
    "claude-haiku-4-5":  (1.00, 5.00),
    "claude-sonnet-4-6": (3.00, 15.00),
    "claude-opus-4-7":   (15.00, 75.00),
}

# ── Language → file extension (for dataset loading) ─────────────────────────
LANG_EXTENSIONS = {
    "python": ".py",  "javascript": ".js", "java": ".java", "c":      ".c",
    "cpp":    ".cpp", "php":        ".php", "rust": ".rs",   "csharp": ".cs",
}

# ── Safety limits ────────────────────────────────────────────────────────────
MAX_TOOL_ROUNDS = 5           # max tool-calling round-trips (expect 2: list → select)
RATE_LIMIT_DELAY = 0.5        # seconds between API calls (conservative)


# ═════════════════════════════════════════════════════════════════════════════
# TOOL DEFINITIONS  (match the notebook's LangChain tools / MCP server)
# ═════════════════════════════════════════════════════════════════════════════
# The tool names and descriptions mirror what the agent sees in the main
# experiment notebook (Cell 4).  The only change is in consult_guidelines'
# description: it now explicitly says to call for EACH relevant guideline.

TOOLS = [
    {
        "name": "list_guidelines",
        "description": (
            "List all available CodeGuard coding guideline categories "
            "with their short descriptions. You MUST call this first to "
            "see what rules are available before selecting any."
        ),
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    {
        "name": "select_guidelines",
        "description": (
            "Select ALL CodeGuard guidelines that are relevant to the "
            "given coding prompt.  You MUST call list_guidelines first, "
            "then call this function ONCE with the complete list of "
            "relevant rule IDs.  Choose rules based on their descriptions "
            "from list_guidelines.\n\n"
            "Args:\n"
            "    rule_ids: A list of rule IDs to select (e.g., "
            "['codeguard-0-input-validation-injection', "
            "'codeguard-0-framework-and-languages'])."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "rule_ids": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": (
                        "List of rule IDs to select as relevant. "
                        "Include ALL that apply to the prompt."
                    ),
                },
            },
            "required": ["rule_ids"],
        },
    },
]

# ═════════════════════════════════════════════════════════════════════════════
# SYSTEM PROMPT  (key change: forces multi-rule retrieval, no code gen)
# ═════════════════════════════════════════════════════════════════════════════
# Compared to the main experiment's TOOLS_SYSTEM_MESSAGE, this prompt:
#   1. Emphasises retrieving ALL relevant guidelines (not just one)
#   2. Tells the agent NOT to generate code
#   3. Asks for a brief JSON list at the end for easy parsing

SYSTEM_MESSAGE = """\
You are a software engineer with access to coding guideline tools.
Your task is to identify ALL coding guidelines that are relevant to the \
code-generation prompt you will receive.

INSTRUCTIONS:
1. Call list_guidelines to see every available guideline and its short \
description.
2. Carefully analyse the prompt — consider the programming language, the \
type of vulnerability or security concern (CWE), and every security domain \
that is involved.
3. Call select_guidelines ONCE with the complete list of ALL relevant rule \
IDs.  Choose rules based on their descriptions from list_guidelines.
4. Think broadly: a single prompt may touch input validation, framework \
guidance, data storage, authentication, cryptography, etc.  Include ALL \
rules that apply — do NOT limit yourself to just one or two.
5. After calling select_guidelines, respond with ONLY a JSON array of the \
rule IDs you selected, e.g.:
   ["codeguard-0-input-validation-injection", "codeguard-0-framework-and-languages"]

Do NOT generate any code.  Do NOT explain the guidelines.  Just identify \
and select them.\
"""


# ═════════════════════════════════════════════════════════════════════════════
# RULE LOADING  (mirrors mcp_codeguard_server.py)
# ═════════════════════════════════════════════════════════════════════════════

def load_rules() -> dict[str, dict]:
    """Load all rule files → {rule_id: {description, content}}."""
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
    """Produce the same text the MCP server's list_available_guidelines returns."""
    lines: list[str] = ["Available Guidelines:\n"]
    for rule_id, data in rules.items():
        lines.append(f"- {rule_id}: {data['description']}")
    return "\n".join(lines)


# ═════════════════════════════════════════════════════════════════════════════
# DATASET LOADING
# ═════════════════════════════════════════════════════════════════════════════

def load_cyberseceval() -> pd.DataFrame:
    """Load walledai/CyberSecEval instruct dataset (all 8 languages)."""
    print("📦 Loading CyberSecEval dataset …")
    dataset = load_dataset("walledai/CyberSecEval", "instruct")
    frames = []
    for lang in LANG_EXTENSIONS:
        if lang in dataset:  # type: ignore
            lang_df = pd.DataFrame(dataset[lang])  # type: ignore
            lang_df["language"] = lang
            frames.append(lang_df)
            print(f"   {lang:<12} → {len(lang_df):>4} prompts")
    df = pd.concat(frames, ignore_index=True)
    print(f"   Total: {len(df)} prompts, "
          f"{df['cwe_identifier'].nunique()} CWEs, "
          f"{df['language'].nunique()} languages")

    # ── Per-CWE breakdown ────────────────────────────────────────────────
    cwe_stats = df.groupby("cwe_identifier").agg(
        prompts=("prompt", "count"),
        languages=("language", "nunique"),
        lang_list=("language", lambda x: sorted(x.unique().tolist())),
    ).sort_index()
    print(f"\n   {'CWE':<12} {'Prompts':>8} {'Languages':>10}  Languages")
    print(f"   {'─' * 60}")
    for cwe_id, row in cwe_stats.iterrows():
        print(f"   {cwe_id:<12} {row['prompts']:>8} {row['languages']:>10}  "
              f"{', '.join(row['lang_list'])}")

    return df


def select_prompts_from_json(
    path: Path,
    target_cwes: list[str] | None,
    target_languages: list[str] | None,
) -> list[dict]:
    """Load prompts straight from an interesting_cases JSON.

    Used when --prompts-from-json is set. Avoids the (slow) full CyberSecEval
    download. The JSON shape produced by the batch experiment is:
        {"cases": [{"prompt": str, "language": str, "cwe_id": str, ...}, ...]}
    """
    data = json.loads(path.read_text(encoding="utf-8"))
    cases = data.get("cases") if isinstance(data, dict) else data
    if not isinstance(cases, list):
        raise ValueError(
            f"--prompts-from-json: expected a 'cases' list at the top of {path}, "
            f"got {type(cases).__name__}"
        )

    selected: list[dict] = []
    for c in cases:
        cwe_id = c.get("cwe_id") or c.get("cwe_identifier")
        language = c.get("language")
        prompt = c.get("prompt")
        if not prompt:
            continue
        if target_cwes and cwe_id not in target_cwes:
            continue
        if target_languages and language and language.lower() not in {
            lang.lower() for lang in target_languages
        }:
            continue
        selected.append({
            "cwe_id":   cwe_id,
            "language": language,
            "prompt":   prompt,
        })
    return selected


def select_prompts(
    df: pd.DataFrame,
    target_cwes: list[str] | None,
    target_languages: list[str] | None,
    limit_per_cwe: int | None,
) -> list[dict]:
    """Filter and flatten the dataset into a list of prompt dicts."""
    cwe_list = (
        sorted(df["cwe_identifier"].unique().tolist())
        if target_cwes is None
        else target_cwes
    )
    selected: list[dict] = []
    for cwe_id in cwe_list:
        subset = df[df["cwe_identifier"] == cwe_id]
        if target_languages:
            subset = subset[subset["language"].isin(target_languages)]
        if limit_per_cwe:
            subset = subset.head(limit_per_cwe)
        for _, row in subset.iterrows():
            selected.append({
                "cwe_id":   cwe_id,
                "language": row["language"],
                "prompt":   row["prompt"],
            })
    return selected


# ═════════════════════════════════════════════════════════════════════════════
# CORE: AGENT TOOL-CALLING LOOP
# ═════════════════════════════════════════════════════════════════════════════

def retrieve_rules_for_prompt(
    client: anthropic.Anthropic,
    prompt: str,
    rules: dict[str, dict],
    list_guidelines_text: str,
    model: str = DEFAULT_MODEL,
) -> dict:
    """
    Run the Claude tool-calling loop for a single prompt.

    Expected flow (2 rounds):
      Round 1: model calls list_guidelines → gets short descriptions
      Round 2: model calls select_guidelines with all relevant IDs → done

    No rule content is ever sent to the model — the selection is based
    purely on the short descriptions from list_guidelines.

    Returns a dict with:
      - rules_retrieved: ordered list of rule IDs the agent chose
      - tool_call_sequence: full log of every tool call
      - token counts
    """
    messages: list[dict] = [{"role": "user", "content": prompt}]

    rules_retrieved: list[str] = []
    tool_call_sequence: list[dict] = []
    total_input_tokens  = 0
    total_output_tokens = 0
    cache_read_tokens   = 0
    cache_create_tokens = 0
    valid_rule_ids = set(rules.keys())

    for _round in range(MAX_TOOL_ROUNDS):
        response = client.messages.create(
            model=model,
            max_tokens=MAX_TOKENS,
            temperature=TEMPERATURE,
            system=[
                {
                    "type": "text",
                    "text": SYSTEM_MESSAGE,
                    "cache_control": {"type": "ephemeral"},
                },
            ],
            tools=TOOLS, # type: ignore
            messages=messages, # type: ignore
        )

        # Track token usage
        total_input_tokens  += response.usage.input_tokens
        total_output_tokens += response.usage.output_tokens
        cache_read_tokens   += getattr(response.usage, "cache_read_input_tokens", 0) or 0
        cache_create_tokens += getattr(response.usage, "cache_creation_input_tokens", 0) or 0

        # Separate tool_use blocks from text blocks
        tool_use_blocks = [b for b in response.content if b.type == "tool_use"]

        if not tool_use_blocks:
            # Agent is done — no more tool calls
            break

        # Add assistant response to conversation
        messages.append({"role": "assistant", "content": response.content})

        # Execute every tool call and build tool_result entries
        tool_results: list[dict] = []
        for tu in tool_use_blocks:
            if tu.name == "list_guidelines":
                result_text = list_guidelines_text
                tool_call_sequence.append({"tool": "list_guidelines", "args": {}})

            elif tu.name == "select_guidelines":
                requested_ids = tu.input.get("rule_ids", [])
                tool_call_sequence.append({
                    "tool":  "select_guidelines",
                    "args":  {"rule_ids": requested_ids},
                })
                # Validate and record each rule ID
                valid   = [r for r in requested_ids if r in valid_rule_ids] # type: ignore
                invalid = [r for r in requested_ids if r not in valid_rule_ids] # type: ignore
                for rid in valid:
                    if rid not in rules_retrieved:
                        rules_retrieved.append(rid)

                # Short acknowledgment — no rule content sent back
                ack_parts = [f"Selected {len(valid)} guideline(s)."]
                if invalid:
                    ack_parts.append(
                        f"Unknown IDs (ignored): {', '.join(invalid)}"
                    )
                result_text = " ".join(ack_parts)

            else:
                result_text = f"Unknown tool: {tu.name}"

            tool_results.append({
                "type":        "tool_result",
                "tool_use_id": tu.id,
                "content":     result_text,
            })

        messages.append({"role": "user", "content": tool_results})

        # Brief delay to respect rate limits
        time.sleep(RATE_LIMIT_DELAY)

    return {
        "rules_retrieved":    rules_retrieved,
        "num_rules":          len(rules_retrieved),
        "tool_call_sequence": tool_call_sequence,
        "num_tool_calls":     len(tool_call_sequence),
        "input_tokens":       total_input_tokens,
        "output_tokens":      total_output_tokens,
        "cache_read_tokens":  cache_read_tokens,
        "cache_create_tokens": cache_create_tokens,
    }


# ═════════════════════════════════════════════════════════════════════════════
# PROGRESS FILE  (for resume capability)
# ═════════════════════════════════════════════════════════════════════════════

def load_progress(progress_path: Path) -> dict[int, dict]:
    """Load completed entries from a JSONL progress file → {index: entry}."""
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
# COST ESTIMATION
# ═════════════════════════════════════════════════════════════════════════════

def estimate_cost(prompts: list[dict], list_text: str, model: str = DEFAULT_MODEL) -> dict:
    """
    Rough upper-bound cost estimate.

    New 2-round flow (no rule content sent to model):
      Round 1: system + tools + prompt → list_guidelines call (~50 tok output)
      Round 2: + list_response + ack   → select_guidelines call (~100 tok output)
      Round 3: + short ack             → final JSON list (~100 tok output)

    Prompt caching saves ~90% on system+tools after the first prompt.
    """
    num = len(prompts)
    avg_prompt_chars = sum(len(p["prompt"]) for p in prompts) / max(num, 1)
    avg_prompt_tokens = int(avg_prompt_chars / 4)
    system_tokens = len(SYSTEM_MESSAGE) // 4
    list_tokens = len(list_text) // 4

    tools_overhead = 400  # tool schemas in the system prompt

    # Round 1: model receives prompt → calls list_guidelines
    round1_in  = system_tokens + tools_overhead + avg_prompt_tokens
    round1_out = 50   # tool_call message (small)

    # Round 2: + list response → model calls select_guidelines([ids...])
    round2_in  = round1_in + round1_out + list_tokens
    round2_out = 100  # tool_call with ~4 rule IDs in the array

    # Round 3: + short ack ("Selected N guidelines.") → final JSON array
    ack_tokens = 15   # "Selected 4 guideline(s)."
    round3_in  = round2_in + round2_out + ack_tokens
    round3_out = 100  # final JSON array response

    per_prompt_in  = round1_in + round2_in + round3_in
    per_prompt_out = round1_out + round2_out + round3_out

    # Apply ~90% cache discount on system+tools portion after first prompt
    cached_portion = system_tokens + tools_overhead
    effective_in = per_prompt_in - (cached_portion * 0.9)

    total_in  = int(effective_in * num)
    total_out = int(per_prompt_out * num)

    # Per-model pricing; fall back to Sonnet rates for unknown models so we
    # always report something rather than $0.
    price_in, price_out = ANTHROPIC_PRICING_USD_PER_MTOK.get(
        model, ANTHROPIC_PRICING_USD_PER_MTOK["claude-sonnet-4-6"]
    )

    cost_in  = total_in  / 1_000_000 * price_in
    cost_out = total_out / 1_000_000 * price_out

    return {
        "num_prompts":        num,
        "avg_prompt_tokens":  avg_prompt_tokens,
        "per_prompt_in":      int(per_prompt_in),
        "per_prompt_out":     int(per_prompt_out),
        "est_total_in":       total_in,
        "est_total_out":      total_out,
        "price_in_mtok":      price_in,
        "price_out_mtok":     price_out,
        "cost_in":            cost_in,
        "cost_out":           cost_out,
        "cost_total":         cost_in + cost_out,
    }


# ═════════════════════════════════════════════════════════════════════════════
# COMPILE FINAL OUTPUT
# ═════════════════════════════════════════════════════════════════════════════

def compile_mapping(
    completed: dict[int, dict],
    prompts: list[dict],
    args: argparse.Namespace,
) -> dict:
    """Build the final JSON mapping from completed progress entries."""
    mappings = []
    for idx in sorted(completed.keys()):
        entry = completed[idx]
        mappings.append(entry)

    # Compute summary statistics
    all_rules = [r for m in mappings for r in m["rules_retrieved"]]
    from collections import Counter
    rule_freq = Counter(all_rules)

    return {
        "metadata": {
            "model":              args.model,
            "timestamp":          datetime.now().strftime("%Y%m%d_%H%M%S"),
            "total_prompts":      len(mappings),
            "unique_rules_used":  len(rule_freq),
            "avg_rules_per_prompt": round(
                sum(m["num_rules"] for m in mappings) / max(len(mappings), 1), 2
            ),
            "total_input_tokens":  sum(m.get("input_tokens", 0) for m in mappings),
            "total_output_tokens": sum(m.get("output_tokens", 0) for m in mappings),
            "dataset":            (
                str(args.prompts_from_json)
                if getattr(args, "prompts_from_json", None) is not None
                else "walledai/CyberSecEval"
            ),
            "config": {
                "target_cwes":      args.cwes,
                "target_languages": args.languages,
                "limit_per_cwe":    args.limit_per_cwe,
                "limit_total":      getattr(args, "limit_total", None),
                "prompts_from_json": str(getattr(args, "prompts_from_json", None) or ""),
            },
        },
        "rule_frequency": dict(rule_freq.most_common()),
        "mappings": mappings,
    }


# ═════════════════════════════════════════════════════════════════════════════
# MAIN
# ═════════════════════════════════════════════════════════════════════════════

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Map CyberSecEval prompts → CodeGuard rules via Claude agent"
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Estimate cost and exit without calling the API."
    )
    parser.add_argument(
        "--cwes", nargs="+", default=None,
        help="CWE IDs to include (default: all)."
    )
    parser.add_argument(
        "--languages", nargs="+", default=None,
        help="Languages to include (default: all)."
    )
    parser.add_argument(
        "--limit-per-cwe", type=int, default=None,
        help="Max prompts per CWE (default: all)."
    )
    parser.add_argument(
        "--resume", type=str, default=None, metavar="PROGRESS_FILE",
        help="Resume from an existing progress JSONL file."
    )
    parser.add_argument(
        "--output", type=str, default=None,
        help="Output JSON file path (default: auto-generated in OUTPUT_DIR)."
    )
    parser.add_argument(
        "--model", type=str, default=DEFAULT_MODEL,
        help=f"Anthropic model identifier (default: {DEFAULT_MODEL}). "
             f"Set to claude-haiku-4-5 for cheap replication runs."
    )
    parser.add_argument(
        "--limit-total", type=int, default=None,
        help="Cap the total number of prompts AFTER all filters apply.",
    )
    parser.add_argument(
        "--prompts-from-json", type=Path, default=None,
        help=(
            "Load prompts directly from an interesting_cases JSON instead of "
            "downloading the full CyberSecEval dataset. The JSON must have a "
            "top-level 'cases' list with 'prompt', 'language', 'cwe_id' fields."
        ),
    )
    parser.add_argument(
        "--yes", "-y", action="store_true",
        help="Skip the interactive 'Run retrieval? [y/N]' confirmation prompt.",
    )
    args = parser.parse_args()

    # ── Load environment ─────────────────────────────────────────────────
    load_dotenv()
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key and not args.dry_run:
        print("❌ ANTHROPIC_API_KEY not found in environment or .env file.")
        print("   Add it:  echo 'ANTHROPIC_API_KEY=sk-ant-...' >> .env")
        sys.exit(1)

    # ── Load rules ───────────────────────────────────────────────────────
    rules = load_rules()
    list_guidelines_text = build_list_guidelines_response(rules)
    print(f"📜 Loaded {len(rules)} CodeGuard rules from {RULES_DIR}")

    # ── Load prompts ─────────────────────────────────────────────────────
    if args.prompts_from_json:
        print(f"📥 Loading prompts from JSON: {args.prompts_from_json}")
        prompts = select_prompts_from_json(
            args.prompts_from_json,
            target_cwes=args.cwes,
            target_languages=args.languages,
        )
    else:
        df = load_cyberseceval()
        prompts = select_prompts(
            df,
            target_cwes=args.cwes,
            target_languages=args.languages,
            limit_per_cwe=args.limit_per_cwe,
        )

    if args.limit_total and len(prompts) > args.limit_total:
        prompts = prompts[: args.limit_total]
        print(f"   Capped to first {args.limit_total} prompts (--limit-total)")

    print(f"\n✅ Selected {len(prompts)} prompts")

    # ── Cost estimate ────────────────────────────────────────────────────
    est = estimate_cost(prompts, list_guidelines_text, model=args.model)
    print(f"\n{'=' * 60}")
    print(f"💰 COST ESTIMATE (upper bound)")
    print(f"{'=' * 60}")
    print(f"   Prompts:              {est['num_prompts']:>10,}")
    print(f"   Avg prompt tokens:    {est['avg_prompt_tokens']:>10,}")
    print(f"   Est. input tokens:    {est['est_total_in']:>10,}")
    print(f"   Est. output tokens:   {est['est_total_out']:>10,}")
    print(f"   Input cost:           ${est['cost_in']:>9.4f}  "
          f"(${est['price_in_mtok']}/MTok)")
    print(f"   Output cost:          ${est['cost_out']:>9.4f}  "
          f"(${est['price_out_mtok']}/MTok)")
    print(f"   ─────────────────────────────────")
    print(f"   TOTAL:                ${est['cost_total']:>9.4f}")
    print(f"{'=' * 60}")

    if args.dry_run:
        print("\n🛑 Dry run — not calling the API.")
        # Show a few example prompts
        print(f"\nExample prompts (first 3):")
        for i, p in enumerate(prompts[:3]):
            print(f"  [{i}] {p['cwe_id']} ({p['language']}): "
                  f"{p['prompt'][:80]}…")
        return

    # ── Confirm ──────────────────────────────────────────────────────────
    if not args.yes:
        try:
            answer = input(
                f"\n❓ Run retrieval for {len(prompts)} prompts with {args.model}? [y/N] "
            ).strip().lower()
        except EOFError:
            answer = ""
        if answer != "y":
            print("Aborted.")
            return
    else:
        print(f"\n▶ --yes set: proceeding with {len(prompts)} prompts on {args.model}.")

    # ── Setup progress ───────────────────────────────────────────────────
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    if args.resume:
        progress_path = Path(args.resume)
    else:
        progress_path = OUTPUT_DIR / f"rule_retrieval_progress_{timestamp}.jsonl"

    completed = load_progress(progress_path)
    print(f"📄 Progress file: {progress_path}")
    if completed:
        print(f"   Resuming — {len(completed)} prompts already completed")

    # ── Create Anthropic client ──────────────────────────────────────────
    client = anthropic.Anthropic(api_key=api_key)

    # ── Run retrieval loop ───────────────────────────────────────────────
    total = len(prompts)
    total_input  = 0
    total_output = 0
    start_time   = time.time()

    print(f"\n🚀 Starting retrieval for {total} prompts …\n")

    for idx, item in enumerate(prompts):
        # Skip if already completed
        if idx in completed:
            continue

        cwe_id   = item["cwe_id"]
        language = item["language"]
        prompt   = item["prompt"]

        print(
            f"  [{idx + 1}/{total}] {cwe_id} ({language})",
            end="",
            flush=True,
        )

        # Retry with exponential backoff for transient errors (429/529)
        max_retries = 5
        result = None
        for attempt in range(max_retries):
            try:
                result = retrieve_rules_for_prompt(
                    client, prompt, rules, list_guidelines_text, model=args.model
                )
                break  # success
            except (anthropic.RateLimitError, anthropic.APIStatusError) as e:
                # Retry on 429 (rate-limit) and 529 (overloaded)
                is_retryable = isinstance(e, anthropic.RateLimitError) or (
                    isinstance(e, anthropic.APIStatusError) and e.status_code == 529
                )
                if not is_retryable:
                    print(f" ❌ {e}")
                    break
                wait = min(30 * (2 ** attempt), 300)  # 30s, 60s, 120s, 240s, 300s
                label = "rate-limited" if isinstance(e, anthropic.RateLimitError) else "overloaded"
                print(f" ⏳ {label}, retry {attempt + 1}/{max_retries} in {wait}s …",
                      end="", flush=True)
                time.sleep(wait)
            except Exception as e:
                print(f" ❌ {e}")
                break

        if result is None:
            print(f" ❌ all {max_retries} retries exhausted")
            continue

        # Build progress entry
        entry = {
            "index":              idx,
            "cwe_id":             cwe_id,
            "language":           language,
            "prompt_hash":        hashlib.sha256(prompt.encode()).hexdigest()[:16],
            "prompt":             prompt,
            "rules_retrieved":    result["rules_retrieved"],
            "num_rules":          result["num_rules"],
            "num_tool_calls":     result["num_tool_calls"],
            "tool_call_sequence": result["tool_call_sequence"],
            "input_tokens":       result["input_tokens"],
            "output_tokens":      result["output_tokens"],
            "cache_read_tokens":  result["cache_read_tokens"],
            "cache_create_tokens": result["cache_create_tokens"],
        }

        # Save incrementally
        append_progress(progress_path, entry)
        completed[idx] = entry

        total_input  += result["input_tokens"]
        total_output += result["output_tokens"]

        print(
            f" → {result['num_rules']} rules "
            f"({result['num_tool_calls']} calls, "
            f"{result['input_tokens']}+{result['output_tokens']} tok)"
        )

    elapsed = time.time() - start_time

    # ── Compile final mapping ────────────────────────────────────────────
    mapping = compile_mapping(completed, prompts, args)

    if args.output:
        out_path = Path(args.output)
    else:
        out_path = OUTPUT_DIR / f"rule_retrieval_map_{timestamp}.json"

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(mapping, f, indent=2, ensure_ascii=False)

    # ── Summary ──────────────────────────────────────────────────────────
    meta = mapping["metadata"]
    print(f"\n{'=' * 70}")
    print(f"🏁 RETRIEVAL MAPPING COMPLETE")
    print(f"{'=' * 70}")
    print(f"   Model:                 {args.model}")
    print(f"   Prompts processed:     {meta['total_prompts']}")
    print(f"   Unique rules used:     {meta['unique_rules_used']} / {len(rules)}")
    print(f"   Avg rules per prompt:  {meta['avg_rules_per_prompt']}")
    print(f"   Total input tokens:    {total_input:,}")
    print(f"   Total output tokens:   {total_output:,}")
    print(f"   Elapsed time:          {elapsed / 60:.1f} min")
    print(f"\n   📄 Mapping saved:      {out_path}")
    print(f"   📄 Progress file:      {progress_path}")

    print(f"\n📊 Rule frequency (top 10):")
    for rule_id, count in list(mapping["rule_frequency"].items())[:10]:
        print(f"   {rule_id:<50} {count:>5}×")

    print(f"\n{'=' * 70}")
    print(f"Next step: load this mapping in batch_experiment.py:")
    print(f"  python batch_experiment.py --rule-map {out_path}")
    print(f"{'=' * 70}")


if __name__ == "__main__":
    main()
