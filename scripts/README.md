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

## analyze/ (run validation + retained historical reports)

- validate_schema5_run.py: strict schema-5 run reconciliation after each SLURM
  search.
- analyze_final_schema4.py / analyze_partial_schema4.py / final_schema4/: frozen
  historical analyzers for the already completed schema-4 reports.
- analyze_replicates.py / stats.py: temp>0 baseline-harness replicate summaries.

The old schema-2 report stack was removed from the working tree to avoid
accidentally analyzing current schema-5 runs with incompatible metrics.

## experiments/ (run and output hygiene)

- filter_semgrep_debug.py: compact and audit `semgrep_debug.jsonl` after a run;
  the search SLURM wrappers call it automatically before schema-5 validation.

## setup/
- download_semgrep_security_audit_rules.sh: One-time local Semgrep rules bootstrap;
  requires an immutable upstream commit and records it in `SOURCE_COMMIT`.
- qualify_final_maps.py: Idempotently materializes the declared task-1301
  exclusion in the final search maps and reconciles their derived metadata.

Why needed:
- Required for offline/consistent Semgrep scans on compute nodes.
