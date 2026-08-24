#!/usr/bin/env python3
"""Replicate runner: load the model once, then run N temp>0 replicates of a
fixed rule configuration (code generation + Semgrep) under chosen seeds, for one
(model, language). General-purpose tool for any run that needs repetitions under
different seeds at temperature>0.

A run produces one final replicate-run directory:

    run_config.json                  provenance + arguments
    replicates.jsonl                 one aggregate record per replicate (APPEND mode)
    replicate_summary.json           per-metric mean +/- bootstrap CI across seeds
                                     (+ paired effect vs --baseline-ref)
    intermediate/<condtag>_seed<NNNN>.jsonl
                                     per-prompt records WITH generated_code
                                     (canonical ExperimentEngine._build_intermediate_record schema)

Single-condition selection (one condition per job, to keep jobs short):
  * ``--condition norules``  -> uses ``--norules-map``
  * ``--condition withrules`` -> authored-rules condition; uses ``--withrules-map``
  * ``--rules-override-dir`` -> override mode: inject mutated rule text on top of
    the authored-rules map (the search run's
    ``mutated_rules/evaluation_NNNN/`` layout; ``rule_short``
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
import hashlib
import importlib.metadata
import json
import os
import re
import socket
import subprocess
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from scripts.experiments.run_experiment import (  # noqa: E402
    RULES_DIR,
    _provenance_path,
    create_rule_loader,
    load_prompts_with_rules,
)
from scripts.analyze import stats as S  # noqa: E402
from scripts.analyze.validate_replicate_run import validate_replicate_run  # noqa: E402
from src.llm_backends import LLMConfig  # noqa: E402
from src.evaluation.generation_contract import (  # noqa: E402
    MAX_OUTPUT_TOKENS,
    prompt_contract_sha256,
)
from src.evaluation.population_screening import (  # noqa: E402
    FINAL_SEARCH_POPULATION_POLICY,
)
from src.llm_backends.delftblue_local_backend import DelftBlueLocalBackend  # noqa: E402
from src.evaluation.qualification import (  # noqa: E402
    QualificationInfrastructureError,
    population_fingerprint,
    qualify_search_population,
)
from src.evaluation.semgrep_runner import (  # noqa: E402
    configure_semgrep,
    configure_semgrep_debug,
    get_semgrep_config,
)

METRICS = (
    "raw_findings_per_valid_prompt",
    "vulnerable_rate_valid",
    "weighted_score_per_valid_prompt",
    "invalid_outputs",
)


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


def _override_corpus_sha256(override_dir: Path) -> str:
    """Hash override filenames and bytes in deterministic order."""
    digest = hashlib.sha256()
    for path in sorted(override_dir.glob("*.md")):
        digest.update(path.name.encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


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


def _load_replicates(run_dir: Path, condition: str | None = None) -> list[dict]:
    """Load aggregate replicate records from a run dir (optionally one condition)."""
    path = run_dir / "replicates.jsonl"
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


def _git_commit_sha() -> str | None:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=str(PROJECT_ROOT),
            stderr=subprocess.DEVNULL,
        ).decode().strip()
    except Exception:
        return None


def _cached_model_revision(model: str) -> str:
    """Resolve the immutable revision of the locally cached model."""
    from transformers import AutoConfig

    config = AutoConfig.from_pretrained(
        model,
        local_files_only=True,
        trust_remote_code=True,
    )
    revision = getattr(config, "_commit_hash", None)
    if re.fullmatch(r"[0-9a-fA-F]{40}", str(revision or "")) is None:
        raise SystemExit(
            f"Could not resolve an exact cached model revision for {model}"
        )
    return str(revision)


# ---------------------------------------------------------------------------
# Summary + baseline-effect
# ---------------------------------------------------------------------------

def _metric_summary(records: list[dict]) -> dict:
    """Per-metric mean + bootstrap CI across replicate records, keyed by seed."""
    out: dict = {"n": len(records), "seeds": sorted(r["seed"] for r in records)}
    for m in METRICS:
        available = [
            r for r in sorted(records, key=lambda r: r["seed"])
            if r.get(m) is not None
        ]
        vals = [float(r[m]) for r in available]
        point, lo, hi = S.bootstrap_ci(vals) if vals else (float("nan"),) * 3
        out[m] = {
            "n": len(vals),
            "mean": point, "ci_lo": lo, "ci_hi": hi,
            "min": (min(vals) if vals else None), "max": (max(vals) if vals else None),
            "per_seed": {r["seed"]: r[m] for r in available},
        }
    return out


def _baseline_effect(this_recs: list[dict], base_recs: list[dict],
                     run_dir: Path, base_dir: Path,
                     this_condtag: str, base_condtag: str) -> dict:
    """Paired (this - baseline) effect across common seeds.

    Replicate aggregates use their explicit valid-output denominators. The
    prompt-level comparison is stricter: within every seed it retains only
    prompts valid in both conditions, computes one mean effect for that seed,
    and then treats seeds as the inferential units. Pooling every seed-prompt
    row into one significance test would pseudo-replicate prompts.
    """
    this_by = {r["seed"]: r for r in this_recs}
    base_by = {r["seed"]: r for r in base_recs}
    common = sorted(set(this_by) & set(base_by))
    eff: dict = {"baseline_ref": str(base_dir), "baseline_condition": base_condtag,
                 "common_seeds": common, "n_common": len(common)}
    if not common:
        eff["note"] = "no common seeds between this run and the baseline reference"
        return eff
    for m in METRICS:
        metric_seeds = [
            s for s in common
            if this_by[s].get(m) is not None and base_by[s].get(m) is not None
        ]
        deltas = [this_by[s][m] - base_by[s][m] for s in metric_seeds]
        if not deltas:
            eff[m] = {"note": "no paired non-missing replicate values"}
            continue
        point, lo, hi = S.bootstrap_ci(deltas)
        st = S.sign_test(deltas)
        eff[m] = {
            "paired_seeds": metric_seeds,
            "delta_mean": point, "delta_ci_lo": lo, "delta_ci_hi": hi,
            "sign_test_p": st.p, "sign_test_note": st.note,
            "this_mean": sum(this_by[s][m] for s in metric_seeds) / len(metric_seeds),
            "baseline_mean": sum(base_by[s][m] for s in metric_seeds) / len(metric_seeds),
        }
    paired_seed_rows: list[dict] = []
    for seed in common:
        this_pp = _load_intermediate(run_dir, f"{this_condtag}_seed{seed:04d}")
        base_pp = _load_intermediate(
            base_dir,
            f"{base_condtag}_seed{seed:04d}",
        )
        ids = sorted(set(this_pp) & set(base_pp))
        if not ids:
            continue
        raw_deltas = [this_pp[task_id] - base_pp[task_id] for task_id in ids]
        vulnerable_deltas = [
            int(this_pp[task_id] > 0) - int(base_pp[task_id] > 0)
            for task_id in ids
        ]
        paired_seed_rows.append(
            {
                "seed": seed,
                "paired_valid_prompts": len(ids),
                "raw_findings_per_prompt_delta": sum(raw_deltas) / len(ids),
                "has_finding_rate_delta": sum(vulnerable_deltas) / len(ids),
            }
        )

    if paired_seed_rows:
        paired_effect: dict = {
            "analysis_unit": "seed",
            "within_seed_policy": "intersection_of_prompts_valid_in_both_conditions",
            "n_seeds": len(paired_seed_rows),
            "total_prompt_pairs_descriptive": sum(
                row["paired_valid_prompts"] for row in paired_seed_rows
            ),
            "per_seed": paired_seed_rows,
            "note": (
                "Prompt pairs calculate one effect per seed and are not pooled as "
                "independent observations. Negative deltas favor this condition."
            ),
        }
        for metric in ("raw_findings_per_prompt_delta", "has_finding_rate_delta"):
            deltas = [row[metric] for row in paired_seed_rows]
            point, lo, hi = S.bootstrap_ci(deltas)
            st = S.sign_test(deltas)
            paired_effect[metric] = {
                "delta_mean": point,
                "delta_ci_lo": lo,
                "delta_ci_hi": hi,
                "sign_test_p": st.p,
                "sign_test_note": st.note,
            }
        eff["paired_valid_prompt_effect"] = paired_effect
    else:
        eff["paired_valid_prompt_effect"] = {
            "analysis_unit": "seed",
            "n_seeds": 0,
            "note": "no common seed had matching valid per-prompt intermediate records",
        }
    return eff


def _load_intermediate(run_dir: Path, evaluation_id: str) -> dict[str, int]:
    """{test_case_id: raw_count} for one replicate's per-prompt file, if present.
    """
    path = run_dir / "intermediate" / f"{evaluation_id}.jsonl"
    if not path.exists():
        return {}
    out: dict[str, int] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        r = json.loads(line)
        if isinstance(r.get("fitness"), dict) and r.get("qualification_status", "valid") == "valid":
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
    ap.add_argument(
        "--n-cases",
        type=int,
        default=None,
        help="Optional diagnostic subset size; default uses the full filtered map population.",
    )
    ap.add_argument("--selection", default="first", choices=["first", "random"])
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
                         "mutated_rules/evaluation_NNNN/). Enables override mode.")
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
    ap.add_argument(
        "--allow-unqualified-map",
        action="store_true",
        help="Explicitly allow a non-final map for diagnostic replicate runs.",
    )
    args = ap.parse_args()

    current_git_commit_sha = _git_commit_sha()
    if re.fullmatch(
        r"[0-9a-fA-F]{40}",
        str(current_git_commit_sha or ""),
    ) is None:
        raise SystemExit("Replicate runner cannot resolve an exact code commit")
    model_revision = _cached_model_revision(args.model)
    torch_version = importlib.metadata.version("torch")
    transformers_version = importlib.metadata.version("transformers")

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

    map_payload = json.loads(Path(rules_map).read_text(encoding="utf-8"))
    map_qualification = map_payload.get("metadata", {}).get("search_qualification", {})
    if (
        not args.allow_unqualified_map
        and (
            map_qualification.get("policy")
            != FINAL_SEARCH_POPULATION_POLICY
            or map_qualification.get("evidence_status") != "final"
        )
    ):
        ap.error(
            "replicate runs require a frozen cross-model temperature-zero map; "
            "use --allow-unqualified-map only for an explicit diagnostic"
        )
    if (
        not args.allow_unqualified_map
        and map_qualification.get("prompt_contract_sha256")
        != prompt_contract_sha256()
    ):
        ap.error(
            "replicate prompt contract differs from the contract recorded by "
            "the qualified map"
        )

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
    configure_semgrep_debug(args.output_dir / "semgrep_debug")
    semgrep_config = get_semgrep_config()
    if semgrep_config.get("rule_config_kind") != "local" or re.fullmatch(
        r"[0-9a-fA-F]{40}", str(semgrep_config.get("rule_source_commit") or "")
    ) is None:
        raise SystemExit("Replicate runner requires pinned local Semgrep rules with SOURCE_COMMIT")
    if semgrep_config.get("semgrep_version") != "1.85.0":
        raise SystemExit(
            f"Replicate runner requires Semgrep 1.85.0, found "
            f"{semgrep_config.get('semgrep_version')}"
        )

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
    if not prompts:
        raise SystemExit("No prompts remain after map/language/override selection")
    population_rows = [
        {
            "test_case_id": str(prompt.metadata.get("test_case_id")),
            "analysis_language": str(prompt.language).lower(),
            "prompt_hash": prompt.metadata.get("prompt_hash"),
        }
        for prompt in prompts
    ]
    actual_population_fingerprint = population_fingerprint(population_rows)
    expected_population_fingerprint = map_qualification.get(
        "qualified_population_fingerprint"
    )
    full_frozen_population = (
        args.n_cases is None
        and not args.only_overridden_prompts
        and len(prompts) == map_qualification.get("qualified_population_total")
        and actual_population_fingerprint == expected_population_fingerprint
    )
    if (
        not args.allow_unqualified_map
        and not override_mode
        and args.n_cases is None
        and not full_frozen_population
    ):
        raise SystemExit(
            "Full baseline population does not match the frozen map fingerprint; "
            "use a language-specific final map in deterministic order"
        )
    print(f"   {len(prompts)} prompts", flush=True)

    if args.baseline_ref is not None:
        baseline_validation = validate_replicate_run(args.baseline_ref)
        if baseline_validation["status"] != "VALID":
            raise SystemExit(
                "Baseline reference failed replicate validation: "
                + "; ".join(baseline_validation["issues"][:5])
            )
        baseline_config = json.loads(
            (args.baseline_ref / "run_config.json").read_text(encoding="utf-8")
        )
        baseline_args = baseline_config.get("args", {})
        comparison_contract = {
            "model": args.model,
            "model_revision": model_revision,
            "torch_version": torch_version,
            "transformers_version": transformers_version,
            "bnb_compute_dtype": args.bnb_compute_dtype,
            "languages": [args.language],
            "temperature": args.temperature,
            "prompt_contract_sha256": prompt_contract_sha256(),
            "n_cases": len(prompts),
            "evaluated_population_fingerprint": actual_population_fingerprint,
            "semgrep_version": semgrep_config["semgrep_version"],
            "semgrep_rules_source_commit": semgrep_config["rule_source_commit"],
            "semgrep_rules_sha256": semgrep_config["rule_config_sha256"],
        }
        mismatches = {
            key: (baseline_args.get(key), expected)
            for key, expected in comparison_contract.items()
            if baseline_args.get(key) != expected
        }
        if baseline_args.get("condition") != args.baseline_condition:
            mismatches["condition"] = (
                baseline_args.get("condition"),
                args.baseline_condition,
            )
        if baseline_config.get("git_commit_sha") != current_git_commit_sha:
            mismatches["git_commit_sha"] = (
                baseline_config.get("git_commit_sha"),
                current_git_commit_sha,
            )
        if mismatches:
            raise SystemExit(f"Incompatible baseline reference: {mismatches}")

    # ---- Provenance --------------------------------------------------------
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
        if prior_cfg.get("artifact_type") != "replicate_run_config":
            raise SystemExit(
                "Refusing to resume a directory that is not a final replicate run"
            )
        prior_args = prior_cfg.get("args", {})
        resume_contract = {
            "model": args.model,
            "model_revision": model_revision,
            "torch_version": torch_version,
            "transformers_version": transformers_version,
            "bnb_compute_dtype": args.bnb_compute_dtype,
            "languages": [args.language],
            "temperature": args.temperature,
            "prompt_contract_sha256": prompt_contract_sha256(),
            "condition": condtag,
            "quantization": args.quantization,
            "n_cases": len(prompts),
            "n_cases_requested": args.n_cases,
            "selection": args.selection,
            "rules_map_sha256": hashlib.sha256(Path(rules_map).read_bytes()).hexdigest(),
            "evaluated_population_fingerprint": actual_population_fingerprint,
            "semgrep_rules_sha256": semgrep_config["rule_config_sha256"],
            "semgrep_rules_source_commit": semgrep_config["rule_source_commit"],
            "semgrep_version": semgrep_config["semgrep_version"],
            "rules_override_dir": (
                str(args.rules_override_dir) if override_mode else None
            ),
            "rules_override_sha256": (
                _override_corpus_sha256(args.rules_override_dir)
                if override_mode else None
            ),
            "only_overridden_prompts": (
                bool(args.only_overridden_prompts) if override_mode else False
            ),
        }
        mismatches = {
            key: (prior_args.get(key), expected)
            for key, expected in resume_contract.items()
            if prior_args.get(key) != expected
        }
        if mismatches:
            raise SystemExit(f"Refusing incompatible replicate-run resume: {mismatches}")
        if prior_cfg.get("git_commit_sha") != current_git_commit_sha:
            raise SystemExit(
                "Refusing replicate-run resume across different code commits: "
                f"{prior_cfg.get('git_commit_sha')} != {current_git_commit_sha}"
            )
    prior_seeds = set(prior_cfg.get("args", {}).get("seeds", []))
    all_seeds = sorted(prior_seeds | set(seeds))
    this_job = os.environ.get("SLURM_JOB_ID")
    job_ids = list(prior_cfg.get("slurm_job_ids", []))
    if this_job and this_job not in job_ids:
        job_ids.append(this_job)
    run_config = {
        "artifact_type": "replicate_run_config",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "first_timestamp": prior_cfg.get("first_timestamp")
                           or prior_cfg.get("timestamp")
                           or datetime.now(timezone.utc).isoformat(),
        "git_commit_sha": current_git_commit_sha,
        "hostname": socket.gethostname(),
        "slurm_job_id": this_job,
        "slurm_job_ids": job_ids,
        "argv": sys.argv,
        "args": {
            "run_mode": "replicate",
            "model": args.model,
            "model_revision": model_revision,
            "torch_version": torch_version,
            "transformers_version": transformers_version,
            "quantization": args.quantization,
            "bnb_compute_dtype": args.bnb_compute_dtype,
            "languages": [args.language],
            "n_cases": len(prompts),
            "n_cases_requested": args.n_cases,
            "selection": args.selection,
            "temperature": args.temperature,
            "prompt_contract_sha256": prompt_contract_sha256(),
            "condition": condtag,
            "seeds": all_seeds,            # cumulative across chunks
            "seeds_this_chunk": seeds,     # what this invocation was asked to run
            "seed": args.seed_base,
            "rules_map": _provenance_path(rules_map),
            "rules_map_sha256": hashlib.sha256(Path(rules_map).read_bytes()).hexdigest(),
            "max_output_tokens": MAX_OUTPUT_TOKENS,
            "invalid_output_policy": "missing_not_zero_with_explicit_denominator",
            "replicate_comparison_metrics": list(METRICS),
            "semgrep_config": str(semgrep_config["rule_config"]),
            "semgrep_timeout_seconds": semgrep_config["subprocess_timeout_seconds"],
            "semgrep_jobs": semgrep_config["jobs"],
            "semgrep_version": semgrep_config["semgrep_version"],
            "semgrep_rule_config_kind": semgrep_config["rule_config_kind"],
            "semgrep_rules_sha256": semgrep_config["rule_config_sha256"],
            "semgrep_rule_file_count": semgrep_config["rule_file_count"],
            "semgrep_rules_source_commit": semgrep_config["rule_source_commit"],
            "rules_override_dir": (str(args.rules_override_dir) if override_mode else None),
            "rules_override_sha256": (
                _override_corpus_sha256(args.rules_override_dir)
                if override_mode else None
            ),
            "only_overridden_prompts": bool(args.only_overridden_prompts) if override_mode else False,
            "baseline_ref": (str(args.baseline_ref) if args.baseline_ref else None),
            "allow_unqualified_map": args.allow_unqualified_map,
            "population_policy": map_qualification.get("policy"),
            "population_evidence_status": map_qualification.get(
                "evidence_status"
            ),
            "population_fingerprint": map_qualification.get(
                "qualified_population_fingerprint"
            ),
            "evaluated_population_fingerprint": actual_population_fingerprint,
            "full_frozen_population": full_frozen_population,
        },
    }
    cfg_path.write_text(json.dumps(run_config, indent=2))

    print(f"🤖 Loading model ONCE: {args.model} (quant={args.quantization}, T={args.temperature})",
          flush=True)
    llm_config = LLMConfig(
        model=args.model, temperature=args.temperature, max_tokens=MAX_OUTPUT_TOKENS,
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
            try:
                evaluation = qualify_search_population(
                    backend,
                    prompts,
                    output_dir=None,
                    temperature=args.temperature,
                    require_temperature_zero=False,
                    verbose=False,
                )
            except QualificationInfrastructureError as exc:
                raise SystemExit(
                    f"Baseline replicate {seed} aborted on infrastructure failure: {exc}"
                ) from exc

            intermediate_rows = []
            valid_rows = []
            invalid_counts: Counter = Counter()
            for row in evaluation.rows:
                durable = dict(row)
                durable["artifact_type"] = "replicate_task_evaluation"
                durable["iter_id"] = iter_id
                durable["condition"] = condtag
                intermediate_rows.append(durable)
                if row["qualification_status"] == "valid":
                    valid_rows.append(row)
                else:
                    invalid_counts[row["qualification_status"]] += 1
            intermediate_path = args.output_dir / "intermediate" / f"{iter_id}.jsonl"
            with intermediate_path.open("w", encoding="utf-8") as handle:
                for row in intermediate_rows:
                    handle.write(json.dumps(row) + "\n")

            raw_findings = sum(row["fitness"]["raw_count"] for row in valid_rows)
            vulnerable_cases = sum(
                row["fitness"]["raw_count"] > 0 for row in valid_rows
            )
            weighted_score = sum(
                row["fitness"]["weighted_score"] for row in valid_rows
            )
            n_valid = len(valid_rows)
            n_invalid = len(prompts) - n_valid
            cases_per_check: Counter = Counter()
            for row in valid_rows:
                for cid in row["fitness"].get("check_ids", []):
                    cases_per_check[cid.split(".")[-1]] += 1
            rec = {
                "artifact_type": "replicate_evaluation",
                "condition": condtag, "model": args.model, "language": args.language,
                "seed": seed, "temperature": args.temperature,
                "n_cases": len(prompts),
                "n_valid_outputs": n_valid,
                "invalid_outputs": n_invalid,
                "invalid_output_counts": dict(sorted(invalid_counts.items())),
                "raw_findings": int(raw_findings),
                "raw_findings_scope": (
                    "full_population" if n_invalid == 0 else "valid_outputs_only"
                ),
                "raw_findings_complete_population": (
                    int(raw_findings) if n_invalid == 0 else None
                ),
                "vulnerable_cases": int(vulnerable_cases),
                "weighted_fitness": float(weighted_score),
                "raw_findings_per_valid_prompt": raw_findings / n_valid if n_valid else None,
                "vulnerable_rate_valid": vulnerable_cases / n_valid if n_valid else None,
                "weighted_score_per_valid_prompt": weighted_score / n_valid if n_valid else None,
                "per_case_raw": {
                    row["test_case_id"]: row["fitness"]["raw_count"]
                    for row in valid_rows
                },
                "cases_per_check_id": dict(cases_per_check),
                "rules_override_dir": (str(args.rules_override_dir) if override_mode else None),
                "overridden_rule_ids": overridden_rule_ids,
                "intermediate_file": f"intermediate/{iter_id}.jsonl",
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
            out.write(json.dumps(rec) + "\n")
            out.flush()
            n_written += 1
            print(
                f"   [{condtag} seed{seed}] observed_raw={rec['raw_findings']} "
                f"finding_positive={rec['vulnerable_cases']}/{n_valid} valid "
                f"invalid={n_invalid} {rec['invalid_output_counts']} "
                f"wfit={rec['weighted_fitness']:.1f}",
                flush=True,
            )

    # ---- Summary (+ baseline effect) over the FULL set in this dir ---------
    all_recs = _load_replicates(args.output_dir, condition=condtag)
    summary: dict = {
        "artifact_type": "replicate_summary",
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
