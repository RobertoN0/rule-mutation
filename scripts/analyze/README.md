# `scripts/analyze/` — Current Analysis Entrypoints

New search runs use schema 5. This directory now keeps only the analysis code
that is still expected to be run from the current branch, the frozen schema-4
analyzer needed to reproduce already completed historical reports, and a tiny
schema-2 compatibility helper layer still imported by retained utilities. The
older schema-2 trajectory/report CLIs, plotting modules, and migration tooling
were removed; recover them from git only if an old artifact must be reprocessed.

## Current Schema-5 Validation

Run this after every successful SLURM search and again after syncing results
locally:

```bash
.venv/bin/python scripts/analyze/validate_schema5_run.py --write <run_dir>
```

The validator reconciles the exact task set, baseline rows, candidate rows,
prompt-local imputation, raw f1, weighted diagnostics, persistent best,
summary totals, map/rules provenance, Semgrep-debug coverage, and fatal failure
artifacts. It exits non-zero when a completed run should not be trusted.

Semgrep debug compaction is an experiment-output hygiene step, not a statistical
analysis step. It now lives at:

```bash
.venv/bin/python scripts/experiments/filter_semgrep_debug.py --in-place <run_dir>
```

The SLURM search wrappers run the filter automatically before schema-5
validation when `semgrep_debug/semgrep_debug.jsonl` exists.

## Frozen Schema-4 Reports

These files are retained only for the historical schema-4 experiments already
analyzed for the thesis:

- `analyze_final_schema4.py`
- `analyze_partial_schema4.py`
- `final_schema4/`

Do not extend these tools for schema 5. Use them only to reproduce or audit the
old schema-4 reports with their explicit manifests.

## Temp>0 Baseline Replicates

`baseline_harness.py` still writes replicate-style outputs. The small helper
set kept for those runs is:

- `analyze_replicates.py`
- `stats.py`
- `loaders.py`, `records.py`, `labels.py` only where retained historical helpers
  still import them

This path is separate from search-trajectory analysis. It reports replicate
means, bootstrap confidence intervals, and paired with-rules versus no-rules
effects for baseline harness outputs.

## Removed Legacy Toolkit

The previous schema-2 report stack (`analyze_run.py`, `analyze_search.py`,
`validation_audit.py`, `metrics/`, `report/`, `viz/`, migration helpers, and
related plotting/report CLIs) is intentionally gone from the working tree. The
current schema-5 artifacts carry a different fitness contract: raw finding count
is the primary objective, while severity weighting and validation metadata are
diagnostics. Keeping the old scripts in-tree made it too easy to run an
incompatible analyzer on current results.
