# Scripts layout

The executable workflow has three distinct phases: map construction and
qualification, the main search experiment, and targeted stochastic
replication.

## Phase 1 — Retrieve, qualify, and freeze maps

- `slurm/slurm_rule_retrieval.sh`: retrieve task-to-rule mappings with the
  final task-delimited request.
- `setup/materialize_retrieval_consensus.py`: validate exactly 20 retrievals
  and materialise the 11-of-20 consensus maps.
- `setup/materialize_eligible_population.py`: audit and apply reviewed,
  outcome-independent task exclusions.
- `analyze/analyze_population_screening.py`: reconcile the complete 20-seed,
  four-stratum temperature-0.6 screening block and materialise qualification
  inputs.
- `experiments/run_qualification.py`: generate and validate the
  temperature-zero search population for one model, language, and map.
- `slurm/slurm_qualification.sh`: DelftBlue launcher for the dedicated
  qualification entrypoint.
- `setup/materialize_qualified_search_maps.py`: combine the four validated
  model/language qualifications with the observed-finding gate and freeze a
  shared population per language.
- `analyze/validate_qualified_maps.py`: verify every final map, fingerprint,
  supporting-artifact hash, and task-order contract.
- `mapping/analyze_prompt_rule_maps.py`: stdlib-only inspection of the raw
  retrieval maps (`single`, `across`, `compare`, `all`). It reports the
  seed-to-seed selection stability that justifies the 11-of-20 consensus
  threshold; `setup/materialize_retrieval_consensus.py` is what actually writes
  the frozen maps.

Example:

```bash
sbatch scripts/slurm/slurm_rule_retrieval.sh
MODEL=qwen LANGUAGES=python RULES_MAP=<screened-qwen-python-map> \
  sbatch scripts/slurm/slurm_qualification.sh
```

## Phase 2 — Run the search experiment

- `experiments/run_experiment.py`: main EA/random-search entrypoint.
- `setup/materialize_initialization_bundle.py`: freeze the shared five-candidate
  initialisation, including the evaluator cache and random-generator states,
  from a validated zero-main-loop source run.
- `slurm/slurm_ea_qwen32b.sh`: Qwen search launcher.
- `slurm/slurm_ea_llama70b.sh`: Llama search launcher.
- `experiments/rerun_from_config.py`: reconstruct a search run from its
  `run_config.json`.

Every final EA/random pair must use the same map, selected task population,
seed, prompt contract, and initialisation bundle. The primary comparison uses
the same scheduler wall-time limit.

Validate every completed or gracefully stopped run with:

```bash
.venv/bin/python scripts/analyze/validate_search_run.py --write <search_run_dir>
```

## Phase 3 — Replicate selected configurations

- `experiments/run_replicates.py`: repeat no-rules, authored-rules (the internal
  condition key is `withrules`), or a selected chromosome at temperature
  greater than zero.
- `slurm/slurm_replicates.sh`: DelftBlue launcher for replicate runs.
- `analyze/validate_replicate_run.py`: reconcile one replicate run.
- `analyze/analyze_replicates.py`: summarise valid paired replicate evidence.

This phase supports baseline reporting and significance checks for selected
search outcomes; it is not part of the search budget.

## Analysis and output utilities

- `analyze/analyze_search_runs.py`: analyse validated matched search runs at the
  common wall-time endpoint and produce evaluation- and time-indexed incumbent
  curves.
- `analyze/stats.py`: shared bootstrap and paired-statistics helpers.
- `analyze/generate_safe_zone_jobs.py`: generate the completed Phase-3
  sanitised-candidate validation job plan; retained for provenance and reruns.
- `experiments/filter_semgrep_debug.py`: compact and audit
  `semgrep_debug.jsonl` before validation.
- `setup/download_semgrep_security_audit_rules.sh`: install a pinned Semgrep
  ruleset and record its immutable upstream commit in `SOURCE_COMMIT`.

The thesis-facing analyses live under `../analysis/scripts/`. In particular,
`rq_wilcoxon_effect_sizes.py` contains the final exact Wilcoxon/A12 procedure,
and `rq5_three_way_baseline.py` produces the final RQ4 shared-task-set
comparison. The older sign-test outputs and pairwise-task-set RQ4 artifact are
retained only for provenance.
