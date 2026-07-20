#!/usr/bin/env python3
"""
rule_retrieval_mapping_reframed.py — reframed-prompt variant of the local
(DelftBlue) rule retrieval mapping.

Identical in behaviour to ``rule_retrieval_mapping_local.py`` EXCEPT for how the
per-prompt message is built. Every leaf helper (rule loading, prompt loading,
response parsing, progress files, output compilation, seeding, backends) is
imported and reused from that module -- only the prompt STRUCTURE differs here.

Why this exists
───────────────
The original single-turn framing puts the raw code-generation prompt (e.g.
"Write a Python function that ...") in the USER turn and the "select guidelines,
do NOT write code" instruction in the SYSTEM turn. Qwen2.5-Coder-32B follows
this correctly, but Llama-3.3-70B resolves the conflict ("write code" vs "don't
write code") in favour of the explicit user request and just writes the code --
returning 0 rules on every prompt.

The reframe (root cause fix): move the "do NOT write code / select guidelines"
instruction into the USER turn and wrap the original prompt as delimited *data*
between ``<task>`` and ``</task>``. The user turn then no longer reads as a bare
imperative to write code, so both models perform the analysis task. The
guidelines list stays in the system message (``build_list_guidelines_response``).

Output format is byte-compatible with the original script; ``prompt_template_version``
in the metadata records that the reframed framing produced the map, and
``user_prompt_template`` stores the exact user-turn template for provenance.

Usage
─────
  # Temperature/seed sweep over a FIXED prompt set (as with the original script):
  python src/retrieval/rule_retrieval_mapping_reframed.py \\
      --from-map rule_maps/old_maps/map_qwen32b_vulnerable_py.json \\
      --temperature 0.6 --seed-start 1 --repetitions 20 \\
      --output-dir rule_maps/temp_sweep_reframed/python

  # Dry run:
  python src/retrieval/rule_retrieval_mapping_reframed.py --dry-run \\
      --from-map rule_maps/old_maps/map_qwen32b_vulnerable_py.json
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path


# ── Project root resolution (same pattern as the original script) ────────────
def _resolve_project_root() -> Path:
    """Resolve repository root by searching upward for src/ and scripts/ dirs."""
    this_file = Path(__file__).resolve()
    for parent in [this_file.parent, *this_file.parents]:
        if (parent / "src").is_dir() and (parent / "scripts").is_dir():
            return parent
    raise RuntimeError("Could not resolve project root from script location")


PROJECT_ROOT = _resolve_project_root()
sys.path.insert(0, str(PROJECT_ROOT))

# ── Reuse ALL leaf helpers from the original local script ────────────────────
# (Everything except how the per-prompt message is built is imported, so the two
#  scripts share one implementation of loading/parsing/progress/compile/output.)
from src.retrieval.rule_retrieval_mapping_local import (  # noqa: E402
    DEFAULT_MODEL,
    MAX_TOKENS,
    OUTPUT_DIR,
    RULES_DIR,
    TEMPERATURE,
    append_progress,
    build_list_guidelines_response,
    compile_mapping,
    load_cyberseceval,
    load_exclude_hashes,
    load_progress,
    load_prompts_from_maps,
    load_rules,
    parse_rule_ids,
    seed_everything,
    select_prompts,
)
from src.llm_backends.delftblue_local_backend import DelftBlueLocalBackend  # noqa: E402
from src.llm_backends.base import LLMConfig, LLMError, LLMResponse  # noqa: E402


# ═════════════════════════════════════════════════════════════════════════════
# PROMPT STRUCTURE (the ONLY thing that differs from the original script)
# ═════════════════════════════════════════════════════════════════════════════
# v2_reframed_user_turn: the "do NOT write code / select guidelines" instruction
# lives in the USER turn and the original code-generation prompt is wrapped as
# delimited data between <task> and </task>. This stops instruction-following
# models (Llama-3.3-70B) from treating the prompt as a bare "write code" command.

PROMPT_TEMPLATE_VERSION = "v2_reframed_user_turn"

# The guidelines list is still supplied in the system message (reused
# build_list_guidelines_response). The system message no longer contains the raw
# "for the given code-generation prompt ..." imperative -- that moves to the user
# turn -- but keeps the role framing and the JSON output-format anchor/example.
SYSTEM_MESSAGE_TEMPLATE = """\
You are a security code reviewer with access to a catalog of coding guidelines.
You review code-generation tasks and decide which of these guidelines a developer \
should consult before writing code. You never write, complete, or output code \
yourself.

{guidelines_list}

For each task you are given, list every relevant guideline with a one-sentence \
reason, then output a JSON array containing ONLY the selected rule IDs on its own \
line.

Example output:
- codeguard-0-input-validation-injection: The task handles user input that needs \
validation.
- codeguard-0-framework-and-languages: Python-specific framework guidance applies.

["codeguard-0-input-validation-injection", "codeguard-0-framework-and-languages"]\
"""

# The reframed USER turn. The original prompt is inserted verbatim between
# <task> and </task> so it reads as data to be analysed, not an instruction to
# obey. "the coding guidelines listed above" refers to the system-message list.
USER_PROMPT_TEMPLATE = """\
A developer has been given the following code-generation task, shown between \
<task> and </task>. Do NOT write, complete, or output any code. Your ONLY job is \
to decide which of the coding guidelines listed above the developer should review \
before starting this task.

<task>
{prompt}
</task>

List each relevant guideline with a one-sentence reason, then output a JSON array \
containing ONLY the selected rule IDs, on its own line."""


def build_reframed_user_content(prompt: str) -> str:
    """Wrap the original code-generation prompt in the reframed user-turn template."""
    return USER_PROMPT_TEMPLATE.format(prompt=prompt)


def retrieve_rules_for_prompt(
    backend: DelftBlueLocalBackend,
    prompt: str,
    valid_rule_ids: set[str],
    system_message: str,
) -> dict:
    """Run single-turn rule retrieval for one prompt using the reframed user turn.

    Same contract/return shape as the original script's helper -- the ONLY
    difference is that the user message is the reframed <task>-wrapped content
    rather than the bare prompt.
    """
    user_content = build_reframed_user_content(prompt)
    messages = [{"role": "user", "content": user_content}]

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
# MAIN — mirrors rule_retrieval_mapping_local.main(), reusing its helpers.
# Differences vs the original: (1) new SYSTEM_MESSAGE_TEMPLATE + reframed user
# turn, (2) default --output-dir is temp_sweep_reframed (never the old dir),
# (3) prompt_template_version / user_prompt_template injected into metadata.
# ═════════════════════════════════════════════════════════════════════════════

def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Map CyberSecEval prompts -> CodeGuard rules via local model on "
            "DelftBlue, using the v2 reframed user-turn prompt structure."
        )
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
        "--from-map", nargs="+", type=Path, default=None, metavar="MAP_JSON",
        help=(
            "Load a FIXED prompt set directly from existing retrieval map JSON(s), "
            "bypassing CyberSecEval + --cwes/--languages/--limit-per-cwe/--total-limit "
            "selection entirely. Reuses each entry's prompt/prompt_hash verbatim so "
            "the set is byte-identical to the source map(s). Mutually exclusive with "
            "the CWE-selection flags and --exclude-map."
        ),
    )
    parser.add_argument(
        "--resume", type=str, default=None, metavar="PROGRESS_FILE",
        help="Resume from an existing progress JSONL file (--repetitions 1 only; "
             "a repetition sweep resumes automatically -- see --repetitions).",
    )
    parser.add_argument(
        "--output", type=str, default=None,
        help="Output JSON file path (--repetitions 1 only; default: auto-generated).",
    )
    parser.add_argument(
        "--output-dir", type=Path, default=None,
        help="Directory for repetition-sweep output files "
             "(default: rule_maps/temp_sweep_reframed). Ignored when --repetitions 1 "
             "and --output is given.",
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
        "--bnb-compute-dtype", default="float16", choices=["float16", "bfloat16"],
        help=(
            "4-bit (NF4) dequant compute dtype. Only used with --quantization 4bit. "
            "Default float16; use bfloat16 for bf16-native models (e.g. Llama-3.3) "
            "to avoid fp16 overflow."
        ),
    )
    parser.add_argument(
        "--max-tokens", type=int, default=MAX_TOKENS,
        help=f"Max output tokens per prompt (default: {MAX_TOKENS}).",
    )
    parser.add_argument(
        "--temperature", type=float, default=TEMPERATURE,
        help=(
            f"Sampling temperature (default: {TEMPERATURE} = deterministic greedy). "
            ">0 enables sampling (do_sample=True); combine with --repetitions/"
            "--seed-start for a seed sweep at fixed temperature."
        ),
    )
    parser.add_argument(
        "--seed-start", type=int, default=1,
        help="First seed value for a repetition sweep (default: 1).",
    )
    parser.add_argument(
        "--repetitions", type=int, default=1,
        help=(
            "Number of seeded repetitions to run in this invocation (default: 1). "
            "Seeds used are seed_start .. seed_start+repetitions-1. The model is "
            "loaded ONCE and reused across all repetitions. Each repetition's "
            "compiled mapping is written as soon as it finishes; a seed whose "
            "output already exists on disk is skipped, so resubmitting after a "
            "wall-time kill continues rather than restarting."
        ),
    )
    parser.add_argument(
        "--yes", "-y", action="store_true",
        help="Skip confirmation prompt (for non-interactive SLURM jobs).",
    )
    args = parser.parse_args()

    if args.from_map and any([
        args.cwes, args.languages, args.limit_per_cwe, args.total_limit, args.exclude_map,
    ]):
        parser.error(
            "--from-map cannot be combined with --cwes/--languages/--limit-per-cwe/"
            "--total-limit/--exclude-map -- it reuses a prompt set verbatim rather "
            "than deriving one."
        )
    if args.repetitions < 1:
        parser.error("--repetitions must be >= 1.")
    if args.repetitions > 1 and args.resume:
        parser.error(
            "--resume is for a single-repetition run; a --repetitions sweep resumes "
            "automatically via its deterministic per-seed output/progress paths."
        )
    if args.repetitions > 1 and args.temperature <= 0.0:
        print(
            "⚠️  --repetitions > 1 with --temperature <= 0.0 (deterministic greedy) -- "
            "every repetition will produce an identical result."
        )

    # ── Load rules ───────────────────────────────────────────────────────
    rules = load_rules()
    guidelines_text = build_list_guidelines_response(rules)
    valid_rule_ids = set(rules.keys())
    print(f"Loaded {len(rules)} CodeGuard rules from {RULES_DIR}")
    print(f"Prompt template version: {PROMPT_TEMPLATE_VERSION}")

    system_message = SYSTEM_MESSAGE_TEMPLATE.format(guidelines_list=guidelines_text)

    # ── Load exclusion set ───────────────────────────────────────────────
    exclude_hashes: set[str] | None = None
    if args.exclude_map:
        if not args.exclude_map.exists():
            print(f"ERROR: Exclude map not found: {args.exclude_map}")
            sys.exit(1)
        exclude_hashes = load_exclude_hashes(args.exclude_map)

    # ── Load prompt set: fixed (--from-map) or CWE-derived selection ─────
    if args.from_map:
        prompts = load_prompts_from_maps(args.from_map)
        print(f"\nLoaded {len(prompts)} prompts from --from-map "
              f"(CWE-based selection bypassed)")
    else:
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

    seeds = list(range(args.seed_start, args.seed_start + args.repetitions))

    if args.dry_run:
        print("\nDry run -- not running inference.")
        print(f"\nExample reframed user turn (first prompt):")
        if prompts:
            print("-" * 70)
            print(build_reframed_user_content(prompts[0]["prompt"]))
            print("-" * 70)
        print(f"\nSystem message length: {len(system_message)} chars")
        print(f"Temperature: {args.temperature}")
        print(f"Seeds: {seeds} ({len(seeds)} repetition(s))")
        print(f"Total LLM calls implied: {len(prompts)} prompts x {len(seeds)} "
              f"seeds = {len(prompts) * len(seeds)}")
        return

    if not prompts:
        print("No prompts to process.")
        return

    # ── Confirm ──────────────────────────────────────────────────────────
    if not args.yes:
        answer = input(
            f"\nRun REFRAMED retrieval for {len(prompts)} prompts x {len(seeds)} "
            f"seed(s) with {args.model} (temperature={args.temperature})? [y/N] "
        ).strip().lower()
        if answer != "y":
            print("Aborted.")
            return

    # ── Initialize backend ONCE -- reused across every repetition ────────
    print(f"\nInitializing local backend: {args.model}")
    print(f"   Quantization: {args.quantization}"
          + (f" (compute_dtype={args.bnb_compute_dtype})" if args.quantization == "4bit" else ""))
    print(f"   Temperature: {args.temperature}")

    config = LLMConfig(
        model=args.model,
        temperature=args.temperature,
        max_tokens=args.max_tokens,
        extra={
            "quantization": args.quantization,
            "local_files_only": True,
            "trust_remote_code": True,
            "bnb_4bit_compute_dtype": args.bnb_compute_dtype,
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

    # ── Output layout ─────────────────────────────────────────────────────
    model_short = args.model.split("/")[-1].lower().replace("-", "_")
    temp_tag = f"t{args.temperature:g}".replace(".", "p").replace("-", "neg")
    # Prompt-set discriminator: runs over DIFFERENT prompt sets (e.g. the py vs
    # java maps) share the same (model, temperature, seed) and would otherwise
    # write to identical filenames -- which silently clobbered the java sweep
    # with the python one. Derive a stable tag from the source: the --from-map
    # basename(s), or the CWE-selection language filter.
    if args.from_map:
        set_tag = "+".join(
            p.stem.replace("retrieval_map_", "").replace("map_", "")
            for p in args.from_map
        )
    else:
        set_tag = (
            "cwe_" + "-".join(sorted(args.languages)) if args.languages else "cwe_all"
        )
    output_dir = args.output_dir or (OUTPUT_DIR / "temp_sweep_reframed")

    # Safety net: never write reframed maps into the OLD (old-framing) temp_sweep
    # dirs -- those must be preserved for comparison.
    old_dir = (OUTPUT_DIR / "temp_sweep").resolve()
    resolved_out = output_dir.resolve()
    if resolved_out == old_dir or old_dir in resolved_out.parents:
        parser.error(
            f"--output-dir {output_dir} resolves inside the old-framing "
            f"{old_dir} tree; reframed maps must go to a distinct location "
            f"(e.g. rule_maps/temp_sweep_reframed/...)."
        )

    output_dir.mkdir(parents=True, exist_ok=True)

    total_prompts = len(prompts)

    # ── Repetition loop: one seed = one full pass over the prompt set ────
    for rep_idx, seed in enumerate(seeds):
        tag = f"{model_short}_{set_tag}_{temp_tag}_seed{seed}"

        if len(seeds) == 1 and args.output:
            out_path = Path(args.output)
        else:
            out_path = output_dir / f"retrieval_map_{tag}.json"

        if out_path.exists():
            print(f"\n[{rep_idx + 1}/{len(seeds)}] seed={seed}: {out_path} already "
                  f"exists -- skipping (delete it to force a re-run)")
            continue

        if len(seeds) == 1 and args.resume:
            progress_path = Path(args.resume)
        else:
            progress_path = output_dir / f".progress_{tag}.jsonl"

        print(f"\n{'=' * 70}")
        print(f"[{rep_idx + 1}/{len(seeds)}] Repetition seed={seed} "
              f"(temperature={args.temperature})")
        print(f"{'=' * 70}")

        seed_everything(seed)

        completed = load_progress(progress_path)
        print(f"Progress file: {progress_path}")
        if completed:
            print(f"   Resuming -- {len(completed)} prompts already completed")

        start_time = time.time()
        model_config_captured: dict | None = None

        print(f"\nStarting reframed retrieval for {total_prompts} prompts...\n")

        for idx, item in enumerate(prompts):
            if idx in completed:
                continue

            cwe_id = item["cwe_id"]
            language = item["language"]
            prompt = item["prompt"]
            prompt_hash = item["prompt_hash"]

            print(
                f"  [{idx + 1}/{total_prompts}] {cwe_id} ({language})",
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
                    "bnb_4bit_compute_dtype": (
                        args.bnb_compute_dtype if args.quantization == "4bit" else None
                    ),
                    "model": args.model,
                    "max_tokens": args.max_tokens,
                    "temperature": args.temperature,
                    "seed": seed,
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

        # ── Compile + write THIS repetition's mapping immediately ────────
        mapping = compile_mapping(
            completed, args,
            model_id=args.model,
            system_message=system_message,
            model_config=model_config_captured,
            seed=seed,
            from_map=args.from_map,
        )
        # Record which framing produced this map (the imported compile_mapping
        # does not know about the reframe). prompt_template_version discriminates
        # v2 reframed maps from v1 old-framing ones; user_prompt_template stores
        # the exact user-turn wording for full provenance.
        mapping["metadata"]["prompt_template_version"] = PROMPT_TEMPLATE_VERSION
        mapping["metadata"]["user_prompt_template"] = USER_PROMPT_TEMPLATE

        out_path.parent.mkdir(parents=True, exist_ok=True)
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(mapping, f, indent=2, ensure_ascii=False)

        meta = mapping["metadata"]
        print(f"\n   seed={seed} complete: {meta['total_prompts']} prompts, "
              f"{meta['unique_rules_used']} unique rules, "
              f"avg_latency={meta['avg_latency_ms']:.0f}ms, "
              f"elapsed={elapsed / 60:.1f}min")
        print(f"   parse_method_stats: {meta['parse_method_stats']}")
        print(f"   Mapping saved: {out_path}")

        # A completed repetition's progress file is redundant with its output
        # JSON and only useful for resuming a KILLED repetition; drop it once
        # the compiled mapping is safely on disk.
        progress_path.unlink(missing_ok=True)

    # ── Batch summary ──────────────────────────────────────────────────────
    print(f"\n{'=' * 70}")
    print(f"REFRAMED RETRIEVAL SWEEP COMPLETE: {len(seeds)} seed(s), "
          f"{total_prompts} prompts each")
    print(f"{'=' * 70}")
    print(f"   Model:           {args.model}")
    print(f"   Quantization:    {args.quantization}")
    print(f"   Temperature:     {args.temperature}")
    print(f"   Seeds:           {seeds}")
    print(f"   Template:        {PROMPT_TEMPLATE_VERSION}")
    print(f"   Output dir:      {output_dir if len(seeds) > 1 or not args.output else Path(args.output).parent}")
    print(f"{'=' * 70}")


if __name__ == "__main__":
    main()
