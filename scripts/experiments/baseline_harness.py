#!/usr/bin/env python3
"""Replicate harness: load the model once, then run N temp>0 replicates of a
fixed rule configuration (code generation + Semgrep) under chosen seeds, for one
(model, language). General-purpose tool for any run that needs repetitions under
different seeds at temperature>0.

A run produces a schema_version-2 run directory that the ``scripts/analyze``
toolkit (``loaders.py`` / ``stats.py``) can read:

    run_config.json                  provenance + args (schema_version 2)
    replicates.jsonl                 one aggregate record per replicate (APPEND mode)
    replicate_summary.json           per-metric mean +/- bootstrap CI across seeds
                                     (+ paired effect vs --baseline-ref)
    intermediate/<condtag>_seed<NNNN>.jsonl
                                     per-prompt records WITH generated_code
                                     (canonical ExperimentEngine._build_intermediate_record schema)

Single-condition selection (one condition per job, to keep jobs short):
  * ``--condition norules``  -> uses ``--norules-map``
  * ``--condition withrules`` -> uses ``--withrules-map``
  * ``--rules-override-dir`` -> override mode: inject mutated rule text on top of
    the with-rules map (the EA's ``mutated_rules/iter<NNN>/`` layout; ``rule_short``
    is the rule_id with the ``codeguard-`` prefix rewritten to ``cg-``). Labelled
    by ``--condition-label``.

Seeds: ``--seeds 47,48,49,50,51`` runs exactly those; otherwise
``seed_base + range(replicates)``. ``replicates.jsonl`` is append-mode and seeds
already recorded are skipped, so re-running only the missing seeds completes a
truncated run in-place.

``--baseline-ref <run_dir>`` loads a prior run's ``replicates.jsonl`` and writes
the paired effect (this condition minus the baseline condition) into
``replicate_summary.json`` so the effect of the rules is visible in the output.
"""
from __future__ import annotations

import argparse
import json
import os
import socket
import subprocess
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from scripts.experiments.run_experiment import (  # noqa: E402
    load_prompts_with_rules, create_rule_loader, RULES_DIR,
)
from scripts.analyze import stats as S  # noqa: E402
from src.llm_backends import LLMConfig  # noqa: E402
from src.llm_backends.delftblue_local_backend import DelftBlueLocalBackend  # noqa: E402
from src.mutation.base import Mutator, MutationResult  # noqa: E402
from src.optimizer.engine import ExperimentEngine, SearchConfig  # noqa: E402
from src.optimizer.chromosome import RuleSetSpace  # noqa: E402
from src.evaluation.composite_fitness import CompositeFitnessEvaluator  # noqa: E402
from src.evaluation.semgrep_runner import configure_semgrep  # noqa: E402

METRICS = ("raw_findings", "vulnerable_cases", "weighted_fitness")


class _NoopMutator(Mutator):
    """Identity mutator — the baseline harness only evaluates the origin
    chromosome, so no mutation is ever applied; this just satisfies the
    ExperimentEngine's required mutator pool."""

    @property
    def name(self) -> str:
        return "noop"

    def mutate(self, text: str) -> MutationResult:
        return MutationResult(original=text, mutated=text,
                              mutation_type="noop", changes=[])


def _rule_short(rule_id: str) -> str:
    """rule_id → mutated_rules file stem (mirrors ExperimentEngine persistence)."""
    return rule_id.replace("codeguard-", "cg-")


def _load_override_texts(override_dir: Path) -> dict[str, str]:
    """Map ``<rule_short>`` → mutated rule text for every ``*.md`` in the dir."""
    files = sorted(override_dir.glob("*.md"))
    if not files:
        raise SystemExit(f"❌ No *.md override files in {override_dir}")
    texts = {f.stem: f.read_text(encoding="utf-8") for f in files}
    print(f"   Loaded {len(texts)} override rule file(s): {', '.join(sorted(texts))}",
          flush=True)
    return texts


def _apply_overrides(prompts, override_texts: dict[str, str]) -> set[str]:
    """Swap mutated text into each prompt's rules in place; rebuild combined_rules."""
    matched: set[str] = set()
    for pwr in prompts:
        changed = False
        for rid in pwr.rule_ids:
            short = _rule_short(rid)
            if short in override_texts:
                pwr.individual_rules[rid] = override_texts[short]
                matched.add(rid)
                changed = True
        if changed:
            pwr.combined_rules = "\n\n---\n\n".join(
                pwr.individual_rules[rid]
                for rid in pwr.rule_ids
                if rid in pwr.individual_rules
            )
    matched_shorts = {_rule_short(r) for r in matched}
    unused = sorted(set(override_texts) - matched_shorts)
    if unused:
        print(f"   ⚠️  {len(unused)} override file(s) matched no prompt rule: "
              f"{', '.join(unused)}", flush=True)
    return matched


# ---------------------------------------------------------------------------
# Seed / replicate-file helpers
# ---------------------------------------------------------------------------

def _parse_seeds(args) -> list[int]:
    """Explicit --seeds list wins; else seed_base + range(replicates)."""
    if args.seeds:
        out: list[int] = []
        for tok in args.seeds.split(","):
            tok = tok.strip()
            if tok:
                out.append(int(tok))
        if not out:
            raise SystemExit("❌ --seeds parsed to an empty list")
        return out
    return [args.seed_base + i for i in range(args.replicates)]


def _replicates_path(run_dir: Path) -> Path:
    """Resolve a run dir's aggregate file, tolerating the legacy filename."""
    new = run_dir / "replicates.jsonl"
    if new.exists():
        return new
    legacy = run_dir / "baseline_replicates.jsonl"
    return legacy if legacy.exists() else new


def _load_replicates(run_dir: Path, condition: str | None = None) -> list[dict]:
    """Load aggregate replicate records from a run dir (optionally one condition)."""
    path = _replicates_path(run_dir)
    if not path.exists():
        return []
    recs = [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    if condition is not None:
        recs = [r for r in recs if r.get("condition") == condition]
    return recs


def _git_sha() -> str | None:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=str(PROJECT_ROOT),
            stderr=subprocess.DEVNULL,
        ).decode().strip()
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Summary + baseline-effect
# ---------------------------------------------------------------------------

def _metric_summary(records: list[dict]) -> dict:
    """Per-metric mean + bootstrap CI across replicate records, keyed by seed."""
    out: dict = {"n": len(records), "seeds": sorted(r["seed"] for r in records)}
    for m in METRICS:
        vals = [float(r[m]) for r in sorted(records, key=lambda r: r["seed"])]
        point, lo, hi = S.bootstrap_ci(vals) if vals else (float("nan"),) * 3
        out[m] = {
            "mean": point, "ci_lo": lo, "ci_hi": hi,
            "min": (min(vals) if vals else None), "max": (max(vals) if vals else None),
            "per_seed": {r["seed"]: r[m] for r in sorted(records, key=lambda r: r["seed"])},
        }
    return out


def _baseline_effect(this_recs: list[dict], base_recs: list[dict],
                     run_dir: Path, base_dir: Path,
                     this_condtag: str, base_condtag: str) -> dict:
    """Paired (this - baseline) effect across common seeds, reusing analyze/stats."""
    this_by = {r["seed"]: r for r in this_recs}
    base_by = {r["seed"]: r for r in base_recs}
    common = sorted(set(this_by) & set(base_by))
    eff: dict = {"baseline_ref": str(base_dir), "baseline_condition": base_condtag,
                 "common_seeds": common, "n_common": len(common)}
    if not common:
        eff["note"] = "no common seeds between this run and the baseline reference"
        return eff
    for m in METRICS:
        deltas = [this_by[s][m] - base_by[s][m] for s in common]
        point, lo, hi = S.bootstrap_ci(deltas)
        st = S.sign_test(deltas)
        eff[m] = {
            "delta_mean": point, "delta_ci_lo": lo, "delta_ci_hi": hi,
            "sign_test_p": st.p, "sign_test_note": st.note,
            "this_mean": sum(this_by[s][m] for s in common) / len(common),
            "baseline_mean": sum(base_by[s][m] for s in common) / len(common),
        }
    # Per-prompt RQ1 tests on the lowest common seed (same sampling on both sides).
    s0 = common[0]
    this_pp = _load_intermediate(run_dir, f"{this_condtag}_seed{s0:04d}")
    base_pp = _load_intermediate(base_dir, f"{base_condtag}_seed{s0:04d}", legacy_baseline=True)
    if this_pp and base_pp:
        ids = sorted(set(this_pp) & set(base_pp))
        b = [base_pp[i] for i in ids]
        t = [this_pp[i] for i in ids]
        wil = S.wilcoxon_paired(b, t)
        mc = S.mcnemar_binary([x > 0 for x in b], [x > 0 for x in t])
        eff["per_prompt_seed"] = s0
        eff["per_prompt_n"] = len(ids)
        eff["wilcoxon_raw_findings"] = {"stat": wil.statistic, "p": wil.p, "note": wil.note}
        eff["mcnemar_has_finding"] = {"stat": mc.statistic, "p": mc.p, "note": mc.note}
    else:
        eff["per_prompt_note"] = ("per-prompt tests skipped (no matching intermediate "
                                  f"files for seed {s0})")
    return eff


def _load_intermediate(run_dir: Path, iter_id: str, legacy_baseline: bool = False
                       ) -> dict[str, int]:
    """{test_case_id: raw_count} for one replicate's per-prompt file, if present.

    legacy_baseline: old runs stored only aggregate data (no per-prompt files);
    return {} so the caller skips per-prompt tests.
    """
    path = run_dir / "intermediate" / f"{iter_id}.jsonl"
    if not path.exists():
        return {}
    out: dict[str, int] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        r = json.loads(line)
        if "fitness" in r:
            out[str(r["test_case_id"])] = int(r["fitness"]["raw_count"])
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--model", required=True)
    ap.add_argument("--backend", default="delftblue", choices=["delftblue"])
    ap.add_argument("--quantization", default="fp16", choices=["fp16", "4bit"])
    ap.add_argument("--bnb-compute-dtype", default="float16", choices=["float16", "bfloat16"])
    ap.add_argument("--language", required=True)
    ap.add_argument("--n-cases", type=int, required=True)
    ap.add_argument("--selection", default="random", choices=["first", "random"])
    ap.add_argument("--temperature", type=float, default=0.6)
    # Replicate / seed control.
    ap.add_argument("--replicates", type=int, default=10,
                    help="Number of seeds when --seeds is not given (seed_base..+N-1).")
    ap.add_argument("--seed-base", type=int, default=42)
    ap.add_argument("--seeds", default=None,
                    help="Explicit comma-separated seed list (e.g. 47,48,49). Overrides "
                         "--replicates/--seed-base. Use to run only the missing seeds.")
    # Condition selection (single condition per run).
    ap.add_argument("--condition", choices=["norules", "withrules"], default=None,
                    help="Which map to evaluate. Ignored in override mode.")
    ap.add_argument("--norules-map", default=None,
                    help="Required when --condition norules.")
    ap.add_argument("--withrules-map", default=None,
                    help="Required when --condition withrules or in override mode.")
    ap.add_argument("--rules-override-dir", type=Path, default=None,
                    help="Dir of <rule_short>.md mutated rules (e.g. an EA "
                         "mutated_rules/iter<NNN>/). Enables override mode.")
    ap.add_argument("--condition-label", default="override",
                    help="Condition label written to records in override mode.")
    ap.add_argument("--only-overridden-prompts", action="store_true",
                    help="Override mode only: evaluate just the prompts that use an "
                         "overridden rule (the exact subset the EA scored).")
    # Baseline reference for the effect-of-rules summary.
    ap.add_argument("--baseline-ref", type=Path, default=None,
                    help="Prior run dir; its replicates are loaded as the baseline and "
                         "the paired effect is written into replicate_summary.json.")
    ap.add_argument("--baseline-condition", default="norules",
                    help="Which condition in --baseline-ref to compare against (default norules).")
    # Semgrep / output.
    ap.add_argument("--semgrep-config", required=True)
    ap.add_argument("--semgrep-timeout-seconds", type=int, default=180)
    ap.add_argument("--semgrep-jobs", type=int, default=4)
    ap.add_argument("--output-dir", type=Path, required=True)
    args = ap.parse_args()

    # ---- Resolve the single condition --------------------------------------
    override_mode = args.rules_override_dir is not None
    if override_mode:
        if not args.withrules_map:
            ap.error("--withrules-map is required (override injects on top of it)")
        if not args.rules_override_dir.is_dir():
            ap.error(f"--rules-override-dir not a directory: {args.rules_override_dir}")
        condtag = args.condition_label
        rules_map = args.withrules_map
    else:
        if args.condition is None:
            ap.error("--condition {norules,withrules} is required "
                     "(or pass --rules-override-dir for override mode)")
        condtag = args.condition
        rules_map = args.norules_map if args.condition == "norules" else args.withrules_map
        if not rules_map:
            ap.error(f"--{args.condition}-map is required for --condition {args.condition}")

    seeds = _parse_seeds(args)

    try:
        from transformers import set_seed as _set_seed
    except Exception:  # pragma: no cover
        _set_seed = None

    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "intermediate").mkdir(parents=True, exist_ok=True)
    configure_semgrep(
        rule_config=args.semgrep_config,
        subprocess_timeout_seconds=args.semgrep_timeout_seconds,
        jobs=args.semgrep_jobs,
    )

    # ---- Provenance: schema_version-2 run_config.json ----------------------
    # On resume (a prior chunk wrote into this dir) UNION the seed lists and
    # accumulate contributing job ids, so the final run_config faithfully records
    # the whole accumulated set rather than just the last chunk's subset.
    cfg_path = args.output_dir / "run_config.json"
    prior_cfg: dict = {}
    if cfg_path.exists():
        try:
            prior_cfg = json.loads(cfg_path.read_text())
        except Exception:
            prior_cfg = {}
    prior_seeds = set(prior_cfg.get("args", {}).get("seeds", []))
    all_seeds = sorted(prior_seeds | set(seeds))
    this_job = os.environ.get("SLURM_JOB_ID")
    job_ids = list(prior_cfg.get("slurm_job_ids", []))
    if this_job and this_job not in job_ids:
        job_ids.append(this_job)
    run_config = {
        "schema_version": 2,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "first_timestamp": prior_cfg.get("first_timestamp")
                           or prior_cfg.get("timestamp")
                           or datetime.now(timezone.utc).isoformat(),
        "git_sha": _git_sha(),
        "hostname": socket.gethostname(),
        "slurm_job_id": this_job,
        "slurm_job_ids": job_ids,
        "argv": sys.argv,
        "args": {
            "optimizer": "replicate_harness",
            "model": args.model,
            "quantization": args.quantization,
            "languages": [args.language],
            "n_cases": args.n_cases,
            "selection": args.selection,
            "temperature": args.temperature,
            "condition": condtag,
            "seeds": all_seeds,            # cumulative across chunks
            "seeds_this_chunk": seeds,     # what this invocation was asked to run
            "seed": args.seed_base,
            "rules_map": str(rules_map),
            "rules_override_dir": (str(args.rules_override_dir) if override_mode else None),
            "only_overridden_prompts": bool(args.only_overridden_prompts) if override_mode else False,
            "baseline_ref": (str(args.baseline_ref) if args.baseline_ref else None),
        },
    }
    cfg_path.write_text(json.dumps(run_config, indent=2))

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
        print("❌ Backend unavailable (model not cached / no CUDA)")
        sys.exit(1)
    print("   ✅ Model ready", flush=True)

    rule_loader = create_rule_loader(RULES_DIR)
    print(f"\n=== Condition: {condtag}  (map={Path(rules_map).name}) ===", flush=True)
    prompts = load_prompts_with_rules(
        Path(rules_map), rule_loader, n_cases=args.n_cases,
        languages=[args.language], selection=args.selection, seed=args.seed_base,
    )
    overridden_rule_ids: list[str] = []
    if override_mode:
        override_texts = _load_override_texts(args.rules_override_dir)
        overridden_rule_ids = sorted(_apply_overrides(prompts, override_texts))
        print(f"   Injected mutated text into {len(overridden_rule_ids)} rule(s)", flush=True)
        if args.only_overridden_prompts:
            ov = set(overridden_rule_ids)
            before = len(prompts)
            prompts = [p for p in prompts if any(r in ov for r in p.rule_ids)]
            print(f"   Restricted to {len(prompts)}/{before} prompts using an "
                  f"overridden rule", flush=True)
    print(f"   {len(prompts)} prompts", flush=True)

    # Rule-set space (genome definition) over the possibly-overridden rule texts.
    _originals: dict[str, str] = {}
    for _p in prompts:
        for _rid, _txt in _p.individual_rules.items():
            _originals.setdefault(_rid, _txt)
    _space = RuleSetSpace(all_rule_ids=sorted(_originals), originals=_originals)

    # ---- Resume: skip seeds already recorded -------------------------------
    rep_path = args.output_dir / "replicates.jsonl"
    done_seeds = {r["seed"] for r in _load_replicates(args.output_dir, condition=condtag)}
    todo = [s for s in seeds if s not in done_seeds]
    if done_seeds:
        print(f"   Resume: {sorted(done_seeds & set(seeds))} already present, "
              f"running {todo}", flush=True)

    n_written = 0
    with open(rep_path, "a") as out:
        for seed in todo:
            if _set_seed is not None:
                _set_seed(seed)
            iter_id = f"{condtag}_seed{seed:04d}"
            hc = ExperimentEngine(
                backend, _NoopMutator(),
                config=SearchConfig(
                    max_iterations=0, output_dir=args.output_dir, verbose=False,
                    save_intermediate=False, enable_validation=False,
                    enable_eval_cache=False,
                ),
                composite_evaluator=CompositeFitnessEvaluator(reference_codes={}, lang=args.language),
            )
            # Schema-3 seam: render the (possibly overridden) rule set as the
            # origin chromosome. intermediate/{iter_id}.jsonl (with generated_code)
            # is written inside _evaluate_chromosome.
            agg, *_rest = hc._evaluate_chromosome(
                _space.origin(), _space, prompts, iter_id=iter_id,
            )

            per_case = [r.raw_count for r in agg.individual_results]
            cases_per_check: Counter = Counter()
            for r in agg.individual_results:
                for cid in r.details.get("check_ids", []):
                    cases_per_check[cid.split(".")[-1]] += 1
            rec = {
                "condition": condtag, "model": args.model, "language": args.language,
                "seed": seed, "temperature": args.temperature,
                "n_cases": len(prompts),
                "raw_findings": int(sum(per_case)),
                "vulnerable_cases": int(agg.num_vulnerable),
                "weighted_fitness": float(agg.total_fitness),
                "per_case_raw": per_case,
                "cases_per_check_id": dict(cases_per_check),
                "rules_override_dir": (str(args.rules_override_dir) if override_mode else None),
                "overridden_rule_ids": overridden_rule_ids,
                "intermediate_file": f"intermediate/{iter_id}.jsonl",
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
            out.write(json.dumps(rec) + "\n")
            out.flush()
            n_written += 1
            print(f"   [{condtag} seed{seed}] raw={rec['raw_findings']} "
                  f"vuln={rec['vulnerable_cases']}/{rec['n_cases']} "
                  f"wfit={rec['weighted_fitness']:.1f}", flush=True)

    # ---- Summary (+ baseline effect) over the FULL set in this dir ---------
    all_recs = _load_replicates(args.output_dir, condition=condtag)
    summary: dict = {
        "condition": condtag, "model": args.model, "language": args.language,
        "temperature": args.temperature, "n_cases": (all_recs[0]["n_cases"] if all_recs else None),
        "metrics": _metric_summary(all_recs),
    }
    if args.baseline_ref is not None:
        base_recs = _load_replicates(args.baseline_ref, condition=args.baseline_condition)
        if base_recs:
            summary["effect_vs_baseline"] = _baseline_effect(
                all_recs, base_recs, args.output_dir, args.baseline_ref,
                condtag, args.baseline_condition,
            )
        else:
            summary["effect_vs_baseline"] = {
                "baseline_ref": str(args.baseline_ref),
                "note": f"no '{args.baseline_condition}' records found in baseline-ref",
            }
    (args.output_dir / "replicate_summary.json").write_text(json.dumps(summary, indent=2))

    print(f"\n✅ Wrote {n_written} new replicate(s); {len(all_recs)} total → {rep_path}", flush=True)
    print(f"   Summary → {args.output_dir / 'replicate_summary.json'}", flush=True)


if __name__ == "__main__":
    main()
