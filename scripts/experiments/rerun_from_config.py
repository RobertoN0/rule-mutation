#!/usr/bin/env python3
"""
Reproduce an experiment from its ``run_config.json``.

A run's ``run_config.json`` already captures every CLI argument plus provenance,
so it is the single source of truth for reproduction. This tool reads it and
dispatches to the right launcher:

* **API backends** (``claude`` / ``openai``)  → re-invoke
  ``scripts/experiments/run_experiment.py`` directly with the recorded args.
* **DelftBlue** (``delftblue``)               → map the args to the environment
  variables understood by the recorded model's SLURM wrapper and ``sbatch`` it
  (reusing the wrappers' proven #SBATCH structure instead of duplicating it).

Usage::

    # Reproduce however the run was originally executed (auto from backend):
    python scripts/experiments/rerun_from_config.py path/to/run_config.json

    # A run directory also works (its run_config.json is located automatically):
    python scripts/experiments/rerun_from_config.py path/to/run_dir

    # Just print the command, don't execute:
    python scripts/experiments/rerun_from_config.py run_config.json --print

    # Force a target (e.g. a run done locally on the API, re-run on DelftBlue):
    python scripts/experiments/rerun_from_config.py run_config.json --as delftblue

    # Override the API output dir:
    python scripts/experiments/rerun_from_config.py run_config.json --output-dir experiments/results/rerun_X
"""

from __future__ import annotations

import argparse
import json
import os
import shlex
import subprocess
import sys
from pathlib import Path


def _resolve_project_root() -> Path:
    this_file = Path(__file__).resolve()
    for parent in [this_file.parent, *this_file.parents]:
        if (parent / "src").is_dir() and (parent / "scripts").is_dir():
            return parent
    raise RuntimeError("Could not resolve project root from script location")


PROJECT_ROOT = _resolve_project_root()
ENTRYPOINT = "scripts/experiments/run_experiment.py"
SLURM_WRAPPERS_BY_MODEL = {
    "Qwen/Qwen2.5-Coder-32B-Instruct": "scripts/slurm/slurm_ea_qwen32b.sh",
    "meta-llama/Llama-3.3-70B-Instruct": "scripts/slurm/slurm_ea_llama70b.sh",
}

# Schema-4 (2026-07-12) renamed/removed several args; older run_configs cannot
# be replayed against the current entrypoint without manual translation.
MIN_SCHEMA_VERSION = 4


def _slurm_wrapper_for_model(model: str | None) -> str:
    """Return the model-specific DelftBlue wrapper, rejecting unknown models."""
    try:
        return SLURM_WRAPPERS_BY_MODEL[str(model)]
    except KeyError as exc:
        supported = ", ".join(sorted(SLURM_WRAPPERS_BY_MODEL))
        raise ValueError(
            f"Unsupported DelftBlue model {model!r}; no matching SLURM wrapper. "
            f"Supported models: {supported}"
        ) from exc


def _build_api_command(args: dict, output_dir: str) -> list[str]:
    """Reconstruct the python entrypoint command for an API-backend run."""
    cmd = [
        sys.executable, ENTRYPOINT,
        "--backend", str(args["backend"]),
        "--model", str(args["model"]),
        "--temperature", str(args.get("temperature", 0.0)),
    ]
    if args["backend"] == "delftblue" and args.get("quantization"):
        cmd += ["--quantization", str(args["quantization"])]
    if args["backend"] == "delftblue" and args.get("bnb_compute_dtype"):
        cmd += ["--bnb-compute-dtype", str(args["bnb_compute_dtype"])]
    cmd += ["--rules-map", str(args["rules_map"])]
    if args.get("n_cases") is not None:
        cmd += ["--n-cases", str(args["n_cases"])]
    cmd += [
        "--iterations", str(args["iterations"]),
        "--seed", str(args["seed"]),
        "--selection", str(args["selection"]),
    ]
    if args.get("languages"):
        cmd += ["--languages", *[str(x) for x in args["languages"]]]
    cmd += ["--mutators", *[str(x) for x in args["mutators"]]]
    cmd += [
        "--optimizer", str(args["optimizer"]),
        "--objective-direction", str(args.get("objective_direction", "minimize")),
        "--archive-cap", str(args["archive_cap"]),
        "--restart-h", str(args["restart_h"]),
        "--max-depth", str(args["max_depth"]),
        "--random-max-changes", str(args.get("random_max_changes", 10)),
        "--ea-n-mutations", str(args.get("ea_n_mutations", 1)),
        "--ea-init-samples", str(args.get("ea_init_samples", 10)),
        "--ea-injection-every", str(args.get("ea_injection_every", 10)),
        "--ea-move", str(args.get("ea_move", "local")),
        "--order-move-weight", str(args.get("order_move_weight", 0.1)),
    ]
    cmd += (
        ["--ea-origin-parent"]
        if args.get("ea_origin_parent", True)
        else ["--no-ea-origin-parent"]
    )
    if args.get("enable_validation"):
        cmd += ["--enable-validation"]
        if args.get("enable_perplexity"):
            cmd += ["--enable-perplexity"]
    if not args.get("enable_eval_cache", True):
        cmd += ["--no-eval-cache"]
    cmd += [
        "--semgrep-config", str(args["semgrep_config"]),
        "--semgrep-timeout-seconds", str(args["semgrep_timeout_seconds"]),
        "--semgrep-jobs", str(args["semgrep_jobs"]),
        "--output-dir", output_dir,
    ]
    return cmd


def _build_slurm_env(args: dict) -> dict[str, str]:
    """Map run_config args to env vars consumed by the DelftBlue wrappers."""
    env: dict[str, str] = {
        "OPTIMIZER": str(args["optimizer"]),
        "OBJECTIVE_DIRECTION": str(args.get("objective_direction", "minimize")),
        "TEMPERATURE": str(args.get("temperature", 0.0)),
        "N_ITERATIONS": str(args["iterations"]),
        "SEED": str(args["seed"]),
        "SELECTION": str(args["selection"]),
        "ARCHIVE_CAP": str(args["archive_cap"]),
        "RESTART_H": str(args["restart_h"]),
        "MAX_DEPTH": str(args["max_depth"]),
        "RANDOM_MAX_CHANGES": str(args.get("random_max_changes", 10)),
        "EA_N_MUTATIONS": str(args.get("ea_n_mutations", 1)),
        "EA_INIT_SAMPLES": str(args.get("ea_init_samples", 10)),
        "EA_INJECTION_EVERY": str(args.get("ea_injection_every", 10)),
        "EA_MOVE": str(args.get("ea_move", "local")),
        "ORDER_MOVE_WEIGHT": str(args.get("order_move_weight", 0.1)),
        "EA_ORIGIN_PARENT": "true" if args.get("ea_origin_parent", True) else "false",
        "MUTATORS": " ".join(str(x) for x in args["mutators"]),
        "ENABLE_VALIDATION": "1" if args.get("enable_validation") else "0",
        "ENABLE_PERPLEXITY": "1" if args.get("enable_perplexity") else "0",
        "ENABLE_EVAL_CACHE": "1" if args.get("enable_eval_cache", True) else "0",
        "SEMGREP_RULESET": str(args["semgrep_config"]),
        "SEMGREP_TIMEOUT_SECONDS": str(args["semgrep_timeout_seconds"]),
        "SEMGREP_JOBS": str(args["semgrep_jobs"]),
        "RULES_MAP": str(args["rules_map"]),
    }
    if args.get("quantization"):
        env["QUANTIZATION"] = str(args["quantization"])
    if args.get("bnb_compute_dtype"):
        env["BNB_COMPUTE_DTYPE"] = str(args["bnb_compute_dtype"])
    if args.get("languages"):
        env["LANGUAGES"] = " ".join(str(x) for x in args["languages"])
    if args.get("n_cases") is not None:
        env["N_CASES"] = str(args["n_cases"])
    return env


def main() -> int:
    parser = argparse.ArgumentParser(description="Reproduce a run from its run_config.json")
    parser.add_argument("config", type=Path,
                        help="Path to run_config.json, or a run directory containing it")
    parser.add_argument("--as", dest="target", choices=["auto", "api", "delftblue"],
                        default="auto", help="Force a reproduction target (default: auto from backend)")
    parser.add_argument("--print", dest="print_only", action="store_true",
                        help="Print the reproduction command without executing it")
    parser.add_argument("--output-dir", default=None,
                        help="Override the API output dir (default: a sibling rerun_<ts> dir)")
    opts = parser.parse_args()

    config_path = opts.config / "run_config.json" if opts.config.is_dir() else opts.config
    if not config_path.exists():
        print(f"❌ run_config.json not found: {config_path}", file=sys.stderr)
        return 1
    config = json.loads(config_path.read_text(encoding="utf-8"))
    if config.get("schema_version", 0) < MIN_SCHEMA_VERSION:
        print(f"❌ run_config schema_version={config.get('schema_version')} predates the "
              f"2026-07-12 search redesign (schema {MIN_SCHEMA_VERSION}); its args no longer "
              f"map onto the current entrypoint. Reconstruct the command manually.",
              file=sys.stderr)
        return 1
    args = config.get("args", {})
    backend = args.get("backend", "delftblue")

    target = opts.target
    if target == "auto":
        target = "delftblue" if backend == "delftblue" else "api"

    if target == "delftblue":
        try:
            slurm_wrapper = _slurm_wrapper_for_model(args.get("model"))
        except ValueError as err:
            print(f"❌ {err}", file=sys.stderr)
            return 1
        env = _build_slurm_env(args)
        if "N_CASES" not in env:
            print(f"⚠️  Original run used all cases (n_cases=null); {slurm_wrapper} "
                  "requires N_CASES. Set it explicitly before submitting.", file=sys.stderr)
        env_str = " ".join(f"{k}={shlex.quote(v)}" for k, v in env.items())
        sbatch_cmd = f"{env_str} sbatch {slurm_wrapper}"
        print(f"# DelftBlue reproduction (from {config_path}):")
        print(sbatch_cmd)
        if opts.print_only:
            return 0
        full_env = {**os.environ, **env}
        return subprocess.run(["sbatch", slurm_wrapper], cwd=PROJECT_ROOT, env=full_env).returncode

    # API path
    out_dir = opts.output_dir or os.environ.get("OUTPUT_DIR") or str(args.get("output_dir", "experiments/results/rerun"))
    cmd = _build_api_command(args, out_dir)
    print(f"# API reproduction (from {config_path}):")
    print(" ".join(shlex.quote(c) for c in cmd))
    if opts.print_only:
        return 0
    return subprocess.run(cmd, cwd=PROJECT_ROOT).returncode


if __name__ == "__main__":
    sys.exit(main())
