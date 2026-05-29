#!/usr/bin/env python3
"""
Reproduce an experiment from its ``run_config.json``.

A run's ``run_config.json`` already captures every CLI argument plus provenance,
so it is the single source of truth for reproduction. This tool reads it and
dispatches to the right launcher:

* **API backends** (``claude`` / ``openai``)  → re-invoke
  ``scripts/experiments/run_with_rules_map.py`` directly with the recorded args.
* **DelftBlue** (``delftblue``)               → map the args to the environment
  variables understood by ``scripts/slurm/slurm_ea_qwen32b.sh`` and ``sbatch`` it
  (reusing the wrapper's proven #SBATCH structure instead of duplicating it).

Usage::

    # Reproduce however the run was originally executed (auto from backend):
    python scripts/experiments/rerun_from_config.py path/to/run_config.json

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
SLURM_WRAPPER = "scripts/slurm/slurm_ea_qwen32b.sh"
ENTRYPOINT = "scripts/experiments/run_with_rules_map.py"


def _build_api_command(args: dict, output_dir: str) -> list[str]:
    """Reconstruct the python entrypoint command for an API-backend run."""
    cmd = [
        sys.executable, ENTRYPOINT,
        "--backend", str(args["backend"]),
        "--model", str(args["model"]),
    ]
    if args["backend"] == "delftblue" and args.get("quantization"):
        cmd += ["--quantization", str(args["quantization"])]
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
        "--archive-cap", str(args["archive_cap"]),
        "--restart-h", str(args["restart_h"]),
        "--max-depth-ea", str(args["max_depth_ea"]),
        "--max-mutations-per-iter", str(args.get("max_mutations_per_iter", 4)),
    ]
    if args.get("enable_validation"):
        cmd += ["--enable-validation",
                "--mutation-max-retries", str(args.get("mutation_max_retries", 2))]
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
    """Map run_config args to env vars consumed by slurm_ea_qwen32b.sh."""
    env: dict[str, str] = {
        "OPTIMIZER": str(args["optimizer"]),
        "N_ITERATIONS": str(args["iterations"]),
        "SEED": str(args["seed"]),
        "SELECTION": str(args["selection"]),
        "ARCHIVE_CAP": str(args["archive_cap"]),
        "RESTART_H": str(args["restart_h"]),
        "MAX_DEPTH_EA": str(args["max_depth_ea"]),
        "MAX_MUTATIONS_PER_ITER": str(args.get("max_mutations_per_iter", 4)),
        "MUTATORS": " ".join(str(x) for x in args["mutators"]),
        "ENABLE_VALIDATION": "1" if args.get("enable_validation") else "0",
        "ENABLE_PERPLEXITY": "1" if args.get("enable_perplexity") else "0",
        "MUTATION_MAX_RETRIES": str(args.get("mutation_max_retries", 2)),
        "ENABLE_EVAL_CACHE": "1" if args.get("enable_eval_cache", True) else "0",
        "SEMGREP_RULESET": str(args["semgrep_config"]),
        "SEMGREP_TIMEOUT_SECONDS": str(args["semgrep_timeout_seconds"]),
        "SEMGREP_JOBS": str(args["semgrep_jobs"]),
        "RULES_MAP": str(args["rules_map"]),
    }
    if args.get("quantization"):
        env["QUANTIZATION"] = str(args["quantization"])
    if args.get("languages"):
        env["LANGUAGES"] = " ".join(str(x) for x in args["languages"])
    if args.get("n_cases") is not None:
        env["N_CASES"] = str(args["n_cases"])
    return env


def main() -> int:
    parser = argparse.ArgumentParser(description="Reproduce a run from its run_config.json")
    parser.add_argument("config", type=Path, help="Path to run_config.json")
    parser.add_argument("--as", dest="target", choices=["auto", "api", "delftblue"],
                        default="auto", help="Force a reproduction target (default: auto from backend)")
    parser.add_argument("--print", dest="print_only", action="store_true",
                        help="Print the reproduction command without executing it")
    parser.add_argument("--output-dir", default=None,
                        help="Override the API output dir (default: a sibling rerun_<ts> dir)")
    opts = parser.parse_args()

    if not opts.config.exists():
        print(f"❌ run_config.json not found: {opts.config}", file=sys.stderr)
        return 1
    config = json.loads(opts.config.read_text(encoding="utf-8"))
    args = config.get("args", {})
    backend = args.get("backend", "delftblue")

    target = opts.target
    if target == "auto":
        target = "delftblue" if backend == "delftblue" else "api"

    if target == "delftblue":
        env = _build_slurm_env(args)
        if "N_CASES" not in env:
            print("⚠️  Original run used all cases (n_cases=null); slurm_ea_qwen32b.sh "
                  "requires N_CASES. Set it explicitly before submitting.", file=sys.stderr)
        env_str = " ".join(f"{k}={shlex.quote(v)}" for k, v in env.items())
        sbatch_cmd = f"{env_str} sbatch {SLURM_WRAPPER}"
        print(f"# DelftBlue reproduction (from {opts.config}):")
        print(sbatch_cmd)
        if opts.print_only:
            return 0
        full_env = {**os.environ, **env}
        return subprocess.run(["sbatch", SLURM_WRAPPER], cwd=PROJECT_ROOT, env=full_env).returncode

    # API path
    out_dir = opts.output_dir or os.environ.get("OUTPUT_DIR") or str(args.get("output_dir", "experiments/results/rerun"))
    cmd = _build_api_command(args, out_dir)
    print(f"# API reproduction (from {opts.config}):")
    print(" ".join(shlex.quote(c) for c in cmd))
    if opts.print_only:
        return 0
    return subprocess.run(cmd, cwd=PROJECT_ROOT).returncode


if __name__ == "__main__":
    sys.exit(main())
