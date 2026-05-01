# Scripts layout (rule-mutation)

This folder is grouped by script type.

## experiments/
- run_with_rules_map.py: Main experiment runner (current production path).

Run as:
- `python scripts/experiments/run_with_rules_map.py`

Why needed:
- Keeps core experiment entry point separate from validation and ops utilities.

## slurm/
- slurm_rules_map_qwen32b.sh: Main SBATCH launcher for local DelftBlue execution.

Run as:
- `sbatch scripts/slurm/slurm_rules_map_qwen32b.sh`

Why needed:
- Encapsulates cluster resource config and reproducible runtime setup.

## setup/
- download_semgrep_security_audit_rules.sh: One-time/periodic local Semgrep rules bootstrap.

Why needed:
- Required for offline/consistent Semgrep scans on compute nodes.
