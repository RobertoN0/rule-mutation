#!/usr/bin/env python3
"""Qualify one complete search map at temperature zero."""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path


def _resolve_project_root() -> Path:
    this_file = Path(__file__).resolve()
    for parent in [this_file.parent, *this_file.parents]:
        if (parent / "src").is_dir() and (parent / "scripts").is_dir():
            return parent
    raise RuntimeError("Could not resolve project root from script location")


PROJECT_ROOT = _resolve_project_root()
sys.path.insert(0, str(PROJECT_ROOT))

from scripts.experiments.run_experiment import (  # noqa: E402
    BACKEND_DEFAULT_MODELS,
    RULES_DIR,
    _git_commit_sha,
    _model_revision,
    _provenance_path,
    configure_semgrep_from_args,
    create_backend,
    install_pretimeout_handler,
    load_prompts_with_rules,
    seed_everything,
    setup_run_logging,
)
from src.evaluation import create_rule_loader  # noqa: E402
from src.evaluation.generation_contract import (  # noqa: E402
    MAX_OUTPUT_TOKENS,
    prompt_contract_sha256,
)
from src.evaluation.output_validation import normalize_language  # noqa: E402
from src.evaluation.qualification import (  # noqa: E402
    QualificationInfrastructureError,
    qualify_search_population,
)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rules-map", "-r", type=Path, required=True)
    parser.add_argument(
        "--languages",
        nargs=1,
        choices=["python", "java"],
        required=True,
        metavar="LANG",
    )
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--model", "-m", default=None)
    parser.add_argument(
        "--backend",
        "-b",
        choices=["claude", "openai", "delftblue"],
        default="delftblue",
    )
    parser.add_argument(
        "--quantization",
        choices=["fp16", "4bit"],
        default="fp16",
    )
    parser.add_argument(
        "--bnb-compute-dtype",
        choices=["float16", "bfloat16"],
        default="float16",
    )
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--semgrep-config",
        default=os.getenv("SEMGREP_RULESET"),
    )
    parser.add_argument(
        "--semgrep-timeout-seconds",
        type=int,
        default=int(os.getenv("SEMGREP_TIMEOUT_SECONDS", "180")),
    )
    parser.add_argument(
        "--semgrep-jobs",
        type=int,
        default=int(os.getenv("SEMGREP_JOBS", "1")),
    )
    parser.add_argument("--output-dir", "-o", type=Path, required=True)
    args = parser.parse_args(argv)
    args.temperature = 0.0
    args.selection = "first"
    args.n_cases = None
    if args.model is None:
        args.model = BACKEND_DEFAULT_MODELS[args.backend]
    return args


def _load_source_map(args: argparse.Namespace) -> dict:
    if not args.rules_map.is_file():
        raise ValueError(f"Rules map file not found: {args.rules_map}")
    payload = json.loads(args.rules_map.read_text(encoding="utf-8"))
    mappings = payload.get("mappings")
    if not isinstance(mappings, list) or not mappings:
        raise ValueError("Qualification source map has no mappings")
    requested = normalize_language(args.languages[0])
    map_languages = {
        normalize_language(str(row.get("language", "")))
        for row in mappings
        if isinstance(row, dict)
    }
    if map_languages != {requested}:
        raise ValueError(
            f"Qualification requires one language-specific source map; "
            f"requested {requested}, map contains {sorted(map_languages, key=str)}"
        )
    return payload


def _save_run_config(
    args: argparse.Namespace,
    semgrep_config: dict,
    *,
    n_prompts: int,
) -> None:
    git_commit_sha = _git_commit_sha()
    if re.fullmatch(r"[0-9a-fA-F]{40}", str(git_commit_sha or "")) is None:
        raise ValueError("Qualification cannot resolve an exact Git commit SHA")
    run_config = {
        "artifact_type": "qualification_run_config",
        "argv": sys.argv,
        "args": {
            "backend": args.backend,
            "dry_run": args.dry_run,
            "model": args.model,
            "model_revision": _model_revision(args),
            "torch_version": importlib.metadata.version("torch"),
            "transformers_version": importlib.metadata.version("transformers"),
            "quantization": args.quantization,
            "bnb_compute_dtype": args.bnb_compute_dtype,
            "temperature": 0.0,
            "run_mode": "qualification",
            "prompt_contract_sha256": prompt_contract_sha256(),
            "rules_map": _provenance_path(args.rules_map),
            "rules_map_sha256": hashlib.sha256(args.rules_map.read_bytes()).hexdigest(),
            "n_cases": n_prompts,
            "n_cases_requested": None,
            "seed": args.seed,
            "selection": "first",
            "languages": args.languages,
            "max_output_tokens": MAX_OUTPUT_TOKENS,
            "semgrep_config": str(semgrep_config["rule_config"]),
            "semgrep_timeout_seconds": semgrep_config[
                "subprocess_timeout_seconds"
            ],
            "semgrep_jobs": semgrep_config["jobs"],
            "semgrep_version": semgrep_config["semgrep_version"],
            "semgrep_rule_config_kind": semgrep_config["rule_config_kind"],
            "semgrep_rules_sha256": semgrep_config["rule_config_sha256"],
            "semgrep_rule_file_count": semgrep_config["rule_file_count"],
            "semgrep_rules_source_commit": semgrep_config["rule_source_commit"],
            "output_dir": str(args.output_dir),
        },
        "timestamp": datetime.now().strftime("%Y%m%d_%H%M%S"),
        "git_commit_sha": git_commit_sha,
        "slurm_job_id": os.getenv("SLURM_JOB_ID"),
        "hostname": os.getenv("HOSTNAME") or __import__("socket").gethostname(),
    }
    (args.output_dir / "run_config.json").write_text(
        json.dumps(run_config, indent=2) + "\n",
        encoding="utf-8",
    )


def _validate_semgrep_provenance(config: dict) -> None:
    if config.get("rule_config_kind") != "local":
        raise ValueError("Real qualification requires a pinned local Semgrep ruleset")
    if re.fullmatch(
        r"[0-9a-fA-F]{40}",
        str(config.get("rule_source_commit") or ""),
    ) is None:
        raise ValueError("Local Semgrep rules must contain a 40-hex SOURCE_COMMIT")
    if config.get("semgrep_version") != "1.85.0":
        raise ValueError(
            "Comparative qualification requires Semgrep 1.85.0; found "
            f"{config.get('semgrep_version')}"
        )


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    existing = [
        name
        for name in (
            "run.log",
            "run_config.json",
            "qualification_generations.jsonl",
            "qualification_manifest.json",
        )
        if (args.output_dir / name).exists()
    ]
    if existing:
        print(
            "❌ Error: qualification output directory is not fresh; existing "
            f"artifacts: {existing}"
        )
        return 1

    try:
        _load_source_map(args)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"❌ Error: {exc}")
        return 1

    seed_everything(args.seed)
    setup_run_logging(args.output_dir)
    should_stop = install_pretimeout_handler()

    print("=" * 70)
    print("🔬 Temperature-zero search-population qualification")
    print("=" * 70)
    print(f"   Prompt contract: {prompt_contract_sha256()}")
    print(f"   Model: {args.model}")
    print(f"   Language: {args.languages[0]}")

    rule_loader = create_rule_loader(RULES_DIR)
    prompts = load_prompts_with_rules(
        rules_map_path=args.rules_map,
        rule_loader=rule_loader,
        n_cases=None,
        languages=args.languages,
        selection="first",
        seed=args.seed,
    )
    if not prompts:
        print("❌ Error: no prompts loaded")
        return 1

    semgrep_config = configure_semgrep_from_args(args)
    try:
        if not args.dry_run:
            _validate_semgrep_provenance(semgrep_config)
        _save_run_config(args, semgrep_config, n_prompts=len(prompts))
    except ValueError as exc:
        print(f"❌ Error: {exc}")
        return 1

    backend = create_backend(args)
    try:
        summary = qualify_search_population(
            backend,
            prompts,
            output_dir=args.output_dir,
            temperature=0.0,
            model_id=args.model,
            should_stop_fn=should_stop,
        )
    except QualificationInfrastructureError as exc:
        print(f"\n❌ Qualification infrastructure failure: {exc}")
        return 1

    print(
        f"\n✅ Qualification complete: {summary.valid_prompts}/"
        f"{summary.total_prompts} valid, {summary.excluded_prompts} excluded"
    )
    print(f"   Prompt contract: {summary.prompt_contract_sha256}")
    print(f"   Population fingerprint: {summary.population_fingerprint}")
    print(f"   Manifest: {summary.manifest_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
