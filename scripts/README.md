# Scripts layout (rule-mutation)

This folder is now grouped by script type.

## experiments/
- run_with_rules_map.py: Main experiment runner (current production path).
- run_batched_experiment.py: Batch-oriented runner (useful for broader sweeps; currently secondary).
- run_mvp.py: Early MVP runner based on Groq flow (keep for regression/baseline checks).

Run as:
- `python scripts/experiments/run_with_rules_map.py`
- `python scripts/experiments/run_batched_experiment.py`
- `python scripts/experiments/run_mvp.py`

Why needed:
- Keeps core experiment entry points separate from validation and ops utilities.

## slurm/
- slurm_rules_map_qwen32b.sh: Main SBATCH launcher for local DelftBlue execution.

Why needed:
- Encapsulates cluster resource config and reproducible runtime setup.

## setup/
- download_semgrep_security_audit_rules.sh: One-time/periodic local Semgrep rules bootstrap.

Why needed:
- Required for offline/consistent Semgrep scans on compute nodes.

## validation/
- test_components.py: Quick component sanity checks.
- validate_groq.py: Groq API validation and limits sanity check.

Run as:
- `python scripts/validation/test_components.py`
- `python scripts/validation/validate_groq.py`

Why needed / not needed:
- test_components.py is useful pre-flight after refactors.
- validate_groq.py is optional if running only local models; keep for API baseline comparisons.

## slurm/
- slurm_rules_map_qwen32b.sh: SLURM launcher for local DelftBlue runs.

Run as:
- `sbatch scripts/slurm/slurm_rules_map_qwen32b.sh`
