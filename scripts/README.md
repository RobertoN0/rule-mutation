# Scripts layout (rule-mutation)

This folder is grouped by script type.

## experiments/
- run_with_rules_map.py: Main experiment runner (current production path).

Run as:
- `python scripts/experiments/run_with_rules_map.py`

Why needed:
- Keeps core experiment entry point separate from validation and ops utilities.

## slurm/
- slurm_bandit_qwen32b.sh: SBATCH launcher for the legacy lex / D-UCB / round-robin path.
- slurm_ea_qwen32b.sh: SBATCH launcher for the (1+1) EA and random_baseline optimizers.

Run as:
- `sbatch scripts/slurm/slurm_bandit_qwen32b.sh`
- `sbatch scripts/slurm/slurm_ea_qwen32b.sh`

Why needed:
- Encapsulates cluster resource config and reproducible runtime setup.

## setup/
- download_semgrep_security_audit_rules.sh: One-time/periodic local Semgrep rules bootstrap.

Why needed:
- Required for offline/consistent Semgrep scans on compute nodes.
