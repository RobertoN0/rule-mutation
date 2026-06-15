#!/usr/bin/env python3
"""Baseline harness: load the model once, then run N temp>0 replicates of the
iteration-0 baseline (code generation + Semgrep) over both conditions
(norules + withrules) for one (model, language).

Writes one record per (condition, replicate) to
``<output_dir>/baseline_replicates.jsonl`` with: raw_findings, vulnerable_cases,
weighted_fitness, per-case raw counts, and cases_per_check_id (number of cases
triggering each rule).
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from scripts.experiments.run_with_rules_map import (  # noqa: E402
    load_prompts_with_rules, create_rule_loader, RULES_DIR,
)
from src.llm_backends import LLMConfig  # noqa: E402
from src.llm_backends.delftblue_local_backend import DelftBlueLocalBackend  # noqa: E402
from src.mutation.base import Mutator, MutationResult  # noqa: E402
from src.optimizer.hill_climber import HillClimber, HillClimbConfig  # noqa: E402
from src.evaluation.composite_fitness import CompositeFitnessEvaluator  # noqa: E402
from src.evaluation.semgrep_runner import configure_semgrep  # noqa: E402


class _NoopMutator(Mutator):
    """Identity mutator — baseline (target_rule_id=None) never applies it."""

    @property
    def name(self) -> str:
        return "noop"

    def mutate(self, text: str) -> MutationResult:
        return MutationResult(original=text, mutated=text,
                              mutation_type="noop", changes=[])


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--model", required=True)
    ap.add_argument("--backend", default="delftblue", choices=["delftblue"])
    ap.add_argument("--quantization", default="fp16", choices=["fp16", "4bit"])
    ap.add_argument("--bnb-compute-dtype", default="float16", choices=["float16", "bfloat16"])
    ap.add_argument("--language", required=True)
    ap.add_argument("--n-cases", type=int, required=True)
    ap.add_argument("--selection", default="random", choices=["first", "random"])
    ap.add_argument("--temperature", type=float, default=0.6)
    ap.add_argument("--replicates", type=int, default=10)
    ap.add_argument("--seed-base", type=int, default=42)
    ap.add_argument("--norules-map", required=True)
    ap.add_argument("--withrules-map", required=True)
    ap.add_argument("--semgrep-config", required=True)
    ap.add_argument("--semgrep-timeout-seconds", type=int, default=180)
    ap.add_argument("--semgrep-jobs", type=int, default=4)
    ap.add_argument("--output-dir", type=Path, required=True)
    args = ap.parse_args()

    try:
        from transformers import set_seed as _set_seed
    except Exception:  # pragma: no cover
        _set_seed = None

    args.output_dir.mkdir(parents=True, exist_ok=True)
    configure_semgrep(
        rule_config=args.semgrep_config,
        subprocess_timeout_seconds=args.semgrep_timeout_seconds,
        jobs=args.semgrep_jobs,
    )

    print(f"🤖 Loading model ONCE: {args.model} (quant={args.quantization}, T={args.temperature})",
          flush=True)
    llm_config = LLMConfig(
        model=args.model, temperature=args.temperature, max_tokens=4096,
        extra={
            "quantization": args.quantization,
            "bnb_4bit_compute_dtype": args.bnb_compute_dtype,
            "local_files_only": True, "trust_remote_code": True,
        },
    )
    backend = DelftBlueLocalBackend(llm_config)
    if not backend.is_available():
        print("❌ Backend unavailable (model not cached / no CUDA)"); sys.exit(1)
    print("   ✅ Model ready", flush=True)

    rule_loader = create_rule_loader(RULES_DIR)
    conditions = [("norules", args.norules_map), ("withrules", args.withrules_map)]

    # Run config for provenance.
    (args.output_dir / "harness_config.json").write_text(json.dumps(vars(args), default=str, indent=2))

    out_path = args.output_dir / "baseline_replicates.jsonl"
    n_written = 0
    with open(out_path, "w") as out:
        for cond, mapp in conditions:
            print(f"\n=== Condition: {cond}  (map={Path(mapp).name}) ===", flush=True)
            prompts = load_prompts_with_rules(
                Path(mapp), rule_loader, n_cases=args.n_cases,
                languages=[args.language], selection=args.selection, seed=args.seed_base,
            )
            print(f"   {len(prompts)} prompts", flush=True)
            for rep in range(args.replicates):
                seed = args.seed_base + rep
                if _set_seed is not None:
                    _set_seed(seed)
                # Fresh climber + evaluator per replicate → no state leakage.
                hc = HillClimber(
                    backend, _NoopMutator(),
                    config=HillClimbConfig(
                        max_iterations=0, output_dir=args.output_dir, verbose=False,
                        save_intermediate=False, enable_validation=False,
                        enable_eval_cache=False,
                    ),
                    composite_evaluator=CompositeFitnessEvaluator(reference_codes={}, lang=args.language),
                )
                agg, _results, *_rest = hc._evaluate_with_per_prompt_rules(
                    prompts, target_rule_id=None, mutator_fn=None,
                    iteration=None, phase="baseline",
                )
                per_case = [r.raw_count for r in agg.individual_results]
                cases_per_check: Counter = Counter()
                for r in agg.individual_results:
                    for cid in r.details.get("check_ids", []):
                        cases_per_check[cid.split(".")[-1]] += 1
                rec = {
                    "condition": cond, "model": args.model, "language": args.language,
                    "replicate": rep, "seed": seed, "temperature": args.temperature,
                    "n_cases": len(prompts),
                    "raw_findings": int(sum(per_case)),
                    "vulnerable_cases": int(agg.num_vulnerable),
                    "weighted_fitness": float(agg.total_fitness),
                    "per_case_raw": per_case,
                    "cases_per_check_id": dict(cases_per_check),
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                }
                out.write(json.dumps(rec) + "\n"); out.flush()
                n_written += 1
                print(f"   [{cond} rep{rep} seed{seed}] raw={rec['raw_findings']} "
                      f"vuln={rec['vulnerable_cases']}/{rec['n_cases']} "
                      f"wfit={rec['weighted_fitness']:.1f}", flush=True)

    print(f"\n✅ Wrote {n_written} replicate records → {out_path}", flush=True)


if __name__ == "__main__":
    main()
