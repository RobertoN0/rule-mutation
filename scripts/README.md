# Scripts layout (rule-mutation)

This folder is grouped by script type.

## experiments/
- run_experiment.py: Main experiment runner (current production path).

Run as:
- `python scripts/experiments/run_experiment.py`

Why needed:
- Keeps core experiment entry point separate from validation and ops utilities.

## experiments/ (reproduction)
- rerun_from_config.py: reproduce a run from its `run_config.json` (API backend →
  re-invoke the python entrypoint; delftblue → `sbatch` the SLURM wrapper). Accepts a
  run directory or a `run_config.json` path.

## slurm/
- slurm_ea_qwen32b.sh / slurm_ea_llama70b.sh: SBATCH launchers for the (1+1) EA and random_search optimizers (Qwen / Llama backends).
- slurm_rule_retrieval_local.sh: SBATCH launcher for the rule-retrieval pipeline.

Run as:
- `sbatch scripts/slurm/slurm_ea_qwen32b.sh`

Why needed:
- Encapsulates cluster resource config and reproducible runtime setup.

## analyze/ (report figures + tables — needs the `analysis` extra)

> **Legacy status:** these tools currently target `schema_version: 2` runs and
> do not yet consume the active whole-chromosome `schema_version: 4` artifacts.
> See [`analyze/README.md`](analyze/README.md) before using them.

- analyze_run.py: single run → RQ1 (per-rule + per-prompt baseline-vs-best,
  Wilcoxon/McNemar), RQ2 (per-mutator effective rate + bootstrap CI), convergence,
  cost + cache/search hygiene.
- analyze_search.py: one or many runs → RQ3 (per-run efficiency, best f1,
  time-to-best, restart breakdown; EA-vs-random comparison + convergence with
  multiple runs).
- validation_audit.py: per-criterion fail rate, per-mutator pass rate, what-if-gated
  (needs `--enable-validation` runs).
- migrate_legacy_run.py: bridge a pre-schema-2 run so the above can read it
  (reconstructs iterations.jsonl + intermediate/; RQ1/RQ3 only).
- loaders.py / stats.py: shared loaders + scipy stat helpers.

For a compatible legacy run (install once: `uv sync --extra analysis`):
- `python scripts/analyze/analyze_run.py <run_dir>`

## setup/
- download_semgrep_security_audit_rules.sh: One-time/periodic local Semgrep rules bootstrap.

Why needed:
- Required for offline/consistent Semgrep scans on compute nodes.
