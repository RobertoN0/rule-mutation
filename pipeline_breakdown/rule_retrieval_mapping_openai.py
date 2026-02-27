#!/usr/bin/env python3
"""
rule_retrieval_mapping_openai.py — OpenAI version of rule_retrieval_mapping.py

Discover which CodeGuard rules a GPT-4o agent retrieves for each CyberSecEval
prompt, using the OpenAI chat-completions API with tool calling.

Functionally identical to rule_retrieval_mapping.py but uses OpenAI instead
of Anthropic (useful when the Anthropic API is overloaded / unavailable).

The resulting mapping file is in the exact same JSON format and can be loaded
by batch_experiment.py via --rule-map.

Prerequisites
─────────────
  pip install openai datasets pandas pyyaml python-dotenv

  # OPENAI_API_KEY must be set in .env
  echo 'OPENAI_API_KEY=sk-...' >> .env

Usage
─────
  # Full run (all 1,916 prompts)
  python rule_retrieval_mapping_openai.py

  # Quick test (2 prompts per CWE)
  python rule_retrieval_mapping_openai.py --limit-per-cwe 2

  # Specific CWEs / languages
  python rule_retrieval_mapping_openai.py --cwes CWE-89 CWE-79 --languages python java

  # Dry run (estimate cost, don't call the API)
  python rule_retrieval_mapping_openai.py --dry-run

  # Resume an interrupted run
  python rule_retrieval_mapping_openai.py --resume rule_retrieval_progress.jsonl
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from collections import Counter
from datetime import datetime
from pathlib import Path

import openai
import pandas as pd
import yaml
from datasets import load_dataset
from dotenv import load_dotenv


# ═════════════════════════════════════════════════════════════════════════════
# CONFIGURATION
# ═════════════════════════════════════════════════════════════════════════════

MODEL = "gpt-4o"

# Low max_tokens — we don't need code generation, just tool calls + a short
# summary of which rules were retrieved.
MAX_TOKENS = 1024
TEMPERATURE = 0.0

# ── Paths ────────────────────────────────────────────────────────────────────
RULES_DIR  = Path("project-codeguard/skills/software-security/rules")
OUTPUT_DIR = Path("generated_code")

# ── Language → file extension (for dataset loading) ─────────────────────────
LANG_EXTENSIONS = {
    "python": ".py",  "javascript": ".js", "java": ".java", "c":      ".c",
    "cpp":    ".cpp", "php":        ".php", "rust": ".rs",   "csharp": ".cs",
}

# ── Safety limits ────────────────────────────────────────────────────────────
MAX_TOOL_ROUNDS = 5           # max tool-calling round-trips (expect 2: list → select)
RATE_LIMIT_DELAY = 0.3        # seconds between API calls


# ═════════════════════════════════════════════════════════════════════════════
# TOOL DEFINITIONS  (OpenAI function-calling format)
# ═════════════════════════════════════════════════════════════════════════════

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "list_guidelines",
            "description": (
                "List all available CodeGuard coding guideline categories "
                "with their short descriptions. You MUST call this first to "
                "see what rules are available before selecting any."
            ),
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
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
            "parameters": {
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
    },
]


# ═════════════════════════════════════════════════════════════════════════════
# SYSTEM PROMPT
# ═════════════════════════════════════════════════════════════════════════════

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
# CORE: AGENT TOOL-CALLING LOOP  (OpenAI chat completions)
# ═════════════════════════════════════════════════════════════════════════════

def retrieve_rules_for_prompt(
    client: openai.OpenAI,
    prompt: str,
    rules: dict[str, dict],
    list_guidelines_text: str,
) -> dict:
    """
    Run the OpenAI tool-calling loop for a single prompt.

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
    messages: list[dict] = [
        {"role": "system", "content": SYSTEM_MESSAGE},
        {"role": "user", "content": prompt},
    ]

    rules_retrieved: list[str] = []
    tool_call_sequence: list[dict] = []
    total_prompt_tokens     = 0
    total_completion_tokens = 0
    valid_rule_ids = set(rules.keys())

    for _round in range(MAX_TOOL_ROUNDS):
        response = client.chat.completions.create(
            model=MODEL,
            max_tokens=MAX_TOKENS,
            temperature=TEMPERATURE,
            tools=TOOLS,
            messages=messages,
        )

        choice = response.choices[0]
        usage  = response.usage

        # Track token usage
        if usage:
            total_prompt_tokens     += usage.prompt_tokens
            total_completion_tokens += usage.completion_tokens

        # Check if the model wants to call tools
        if choice.finish_reason != "tool_calls" and not choice.message.tool_calls:
            # Agent is done — no more tool calls
            break

        # Add the assistant message (with tool_calls) to conversation
        messages.append(choice.message.to_dict())  # type: ignore[arg-type]

        # Execute every tool call and append tool results
        for tc in choice.message.tool_calls or []:
            func_name = tc.function.name
            try:
                func_args = json.loads(tc.function.arguments)
            except json.JSONDecodeError:
                func_args = {}

            if func_name == "list_guidelines":
                result_text = list_guidelines_text
                tool_call_sequence.append({"tool": "list_guidelines", "args": {}})

            elif func_name == "select_guidelines":
                requested_ids = func_args.get("rule_ids", [])
                tool_call_sequence.append({
                    "tool":  "select_guidelines",
                    "args":  {"rule_ids": requested_ids},
                })
                # Validate and record each rule ID
                valid   = [r for r in requested_ids if r in valid_rule_ids]
                invalid = [r for r in requested_ids if r not in valid_rule_ids]
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
                result_text = f"Unknown tool: {func_name}"

            messages.append({
                "role":         "tool",
                "tool_call_id": tc.id,
                "content":      result_text,
            })

        # Brief delay to respect rate limits
        time.sleep(RATE_LIMIT_DELAY)

    return {
        "rules_retrieved":    rules_retrieved,
        "num_rules":          len(rules_retrieved),
        "tool_call_sequence": tool_call_sequence,
        "num_tool_calls":     len(tool_call_sequence),
        "input_tokens":       total_prompt_tokens,
        "output_tokens":      total_completion_tokens,
        "cache_read_tokens":  0,
        "cache_create_tokens": 0,
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

def estimate_cost(prompts: list[dict], list_text: str) -> dict:
    """
    Rough upper-bound cost estimate for GPT-4o.

    2-round flow (no rule content sent to model):
      Round 1: system + tools + prompt → list_guidelines call (~50 tok output)
      Round 2: + list_response         → select_guidelines call (~100 tok output)
      Round 3: + short ack             → final JSON list (~100 tok output)
    """
    num = len(prompts)
    avg_prompt_chars = sum(len(p["prompt"]) for p in prompts) / max(num, 1)
    avg_prompt_tokens = int(avg_prompt_chars / 4)
    system_tokens = len(SYSTEM_MESSAGE) // 4
    list_tokens = len(list_text) // 4

    tools_overhead = 400  # tool schemas

    # Round 1: model receives prompt → calls list_guidelines
    round1_in  = system_tokens + tools_overhead + avg_prompt_tokens
    round1_out = 50

    # Round 2: + list response → model calls select_guidelines([ids...])
    round2_in  = round1_in + round1_out + list_tokens
    round2_out = 100

    # Round 3: + short ack → final JSON array
    ack_tokens = 15
    round3_in  = round2_in + round2_out + ack_tokens
    round3_out = 100

    per_prompt_in  = round1_in + round2_in + round3_in
    per_prompt_out = round1_out + round2_out + round3_out

    total_in  = int(per_prompt_in * num)
    total_out = int(per_prompt_out * num)

    # GPT-4o pricing (as of 2025)
    price_in  = 2.50   # $/MTok input
    price_out = 10.00  # $/MTok output

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
    rule_freq = Counter(all_rules)

    return {
        "metadata": {
            "model":              MODEL,
            "timestamp":          datetime.now().strftime("%Y%m%d_%H%M%S"),
            "total_prompts":      len(mappings),
            "unique_rules_used":  len(rule_freq),
            "avg_rules_per_prompt": round(
                sum(m["num_rules"] for m in mappings) / max(len(mappings), 1), 2
            ),
            "total_input_tokens":  sum(m.get("input_tokens", 0) for m in mappings),
            "total_output_tokens": sum(m.get("output_tokens", 0) for m in mappings),
            "dataset":            "walledai/CyberSecEval",
            "config": {
                "target_cwes":      args.cwes,
                "target_languages": args.languages,
                "limit_per_cwe":    args.limit_per_cwe,
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
        description="Map CyberSecEval prompts → CodeGuard rules via GPT-4o agent"
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
        "--budget", type=float, default=None,
        help="Max USD to spend (e.g., 0.17). Stops gracefully when exceeded."
    )
    args = parser.parse_args()

    # ── Load environment ─────────────────────────────────────────────────
    load_dotenv()
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key and not args.dry_run:
        print("❌ OPENAI_API_KEY not found in environment or .env file.")
        print("   Add it:  echo 'OPENAI_API_KEY=sk-...' >> .env")
        sys.exit(1)

    # ── Load rules ───────────────────────────────────────────────────────
    rules = load_rules()
    list_guidelines_text = build_list_guidelines_response(rules)
    print(f"📜 Loaded {len(rules)} CodeGuard rules from {RULES_DIR}")

    # ── Load dataset ─────────────────────────────────────────────────────
    df = load_cyberseceval()
    prompts = select_prompts(
        df,
        target_cwes=args.cwes,
        target_languages=args.languages,
        limit_per_cwe=args.limit_per_cwe,
    )
    print(f"\n✅ Selected {len(prompts)} prompts")

    # ── Cost estimate ────────────────────────────────────────────────────
    est = estimate_cost(prompts, list_guidelines_text)
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
    if args.budget is not None:
        print(f"   ─────────────────────────────────")
        print(f"   💳 BUDGET CAP:          ${args.budget:>7.4f}")
        est_prompts = int(args.budget / max(est['cost_total'] / est['num_prompts'], 1e-9))
        print(f"   Est. prompts affordable: ~{min(est_prompts, est['num_prompts'])}")
    print(f"{'=' * 60}")

    if args.dry_run:
        print("\n🛑 Dry run — not calling the API.")
        print(f"\nExample prompts (first 3):")
        for i, p in enumerate(prompts[:3]):
            print(f"  [{i}] {p['cwe_id']} ({p['language']}): "
                  f"{p['prompt'][:80]}…")
        return

    # ── Confirm ──────────────────────────────────────────────────────────
    answer = input(
        f"\n❓ Run retrieval for {len(prompts)} prompts with {MODEL}? [y/N] "
    ).strip().lower()
    if answer != "y":
        print("Aborted.")
        return

    # ── Setup progress ───────────────────────────────────────────────────
    OUTPUT_DIR.mkdir(exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    if args.resume:
        progress_path = Path(args.resume)
    else:
        progress_path = OUTPUT_DIR / f"rule_retrieval_progress_openai_{timestamp}.jsonl"

    completed = load_progress(progress_path)
    print(f"📄 Progress file: {progress_path}")
    if completed:
        print(f"   Resuming — {len(completed)} prompts already completed")

    # ── Create OpenAI client ─────────────────────────────────────────────
    client = openai.OpenAI(api_key=api_key)

    # ── Run retrieval loop ───────────────────────────────────────────────
    total = len(prompts)
    total_input  = 0
    total_output = 0
    spent_usd    = 0.0
    start_time   = time.time()

    # GPT-4o pricing constants for live tracking
    _PRICE_IN  = 2.50 / 1_000_000   # $/token
    _PRICE_OUT = 10.00 / 1_000_000  # $/token

    print(f"\n🚀 Starting retrieval for {total} prompts …\n")

    for idx, item in enumerate(prompts):
        # Skip if already completed
        if idx in completed:
            continue

        # Budget guard
        if args.budget is not None and spent_usd >= args.budget:
            print(f"\n  💳 Budget exhausted (${spent_usd:.4f} / ${args.budget:.4f}). "
                  f"Stopping gracefully.")
            break

        cwe_id   = item["cwe_id"]
        language = item["language"]
        prompt   = item["prompt"]

        print(
            f"  [{idx + 1}/{total}] {cwe_id} ({language})",
            end="",
            flush=True,
        )

        # Retry with exponential backoff for transient errors (429/500/503)
        max_retries = 5
        result = None
        for attempt in range(max_retries):
            try:
                result = retrieve_rules_for_prompt(
                    client, prompt, rules, list_guidelines_text
                )
                break  # success
            except openai.RateLimitError as e:
                wait = min(30 * (2 ** attempt), 300)
                print(f" ⏳ rate-limited, retry {attempt + 1}/{max_retries} in {wait}s …",
                      end="", flush=True)
                time.sleep(wait)
            except openai.APIStatusError as e:
                if e.status_code in (500, 503, 529):
                    wait = min(30 * (2 ** attempt), 300)
                    print(f" ⏳ server error {e.status_code}, retry {attempt + 1}/{max_retries} in {wait}s …",
                          end="", flush=True)
                    time.sleep(wait)
                else:
                    print(f" ❌ {e}")
                    break
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

        prompt_cost = (result["input_tokens"] * _PRICE_IN
                       + result["output_tokens"] * _PRICE_OUT)
        spent_usd += prompt_cost

        budget_str = f", ${spent_usd:.4f} spent" if args.budget else ""
        print(
            f" → {result['num_rules']} rules "
            f"({result['num_tool_calls']} calls, "
            f"{result['input_tokens']}+{result['output_tokens']} tok"
            f"{budget_str})"
        )

    elapsed = time.time() - start_time

    # ── Compile final mapping ────────────────────────────────────────────
    mapping = compile_mapping(completed, prompts, args)

    if args.output:
        out_path = Path(args.output)
    else:
        out_path = OUTPUT_DIR / f"rule_retrieval_map_openai_{timestamp}.json"

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(mapping, f, indent=2, ensure_ascii=False)

    # ── Summary ──────────────────────────────────────────────────────────
    meta = mapping["metadata"]
    print(f"\n{'=' * 70}")
    print(f"🏁 RETRIEVAL MAPPING COMPLETE")
    print(f"{'=' * 70}")
    print(f"   Model:                 {MODEL}")
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
