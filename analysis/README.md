# Analysis package

This directory contains the read-only analyses behind the submitted thesis, the
canonical JSON and Markdown they produced, and figures built from that JSON.
See [`../EVIDENCE_MAP.md`](../EVIDENCE_MAP.md) for the report-object mapping and
the exact executed revisions.

## Layout

```text
analysis/
├── scripts/     canonical analyses and figure builder
├── results/     canonical JSON plus human-readable Markdown
└── figures/     regenerated PDF and PNG figures
```

## Canonical scripts and outputs

| Script | Status and output |
|---|---|
| `common.py` | Shared run loaders, bootstrap helpers, and legacy statistical helpers. |
| `check_analysis_readiness.py` | Completeness gate: `analysis_readiness.{json,md}`. |
| `baseline_reconcile.py` | Phase-3 baseline provenance: `baseline_reconciliation.{json,md}`. |
| `rq1_magnitude.py` | RQ1 full-contract estimates: `rq1_magnitude.{json,md}`. |
| `rq2_ea_vs_random.py` | Executed/full-contract paired data and descriptive estimates: `rq2_ea_vs_random.{json,md}`. Its sign-test decision is superseded. |
| `rq2_safe_zone_tiers.py` | RQ2 paired data, medians, and intervals across all three lenses: `rq2_safe_zone_tiers.{json,md}`. Its stored sign tests are provenance only. |
| `rq_wilcoxon_effect_sizes.py` | Final exact Wilcoxon, A12, and Holm results for RQ2 and RQ4: `rq_wilcoxon_effect_sizes.json`. It recomputes RQ4 from the final shared-task-set artifact. |
| `rq3_mutators.py` | RQ3 move-family associations: `rq3_mutators.{json,md}`. |
| `phase3_select_topk.py` | Selection of twenty candidates: `phase3_selection_topk.{json,md}`. |
| `rq4_phase3_safe_compare.py` | Superseded pairwise-task-set RQ4 artifact: `rq4_phase3_safe_comparison.{json,md}`. Retained for provenance and the Figure 4 temperature-zero ticks only. |
| `rq5_three_way_baseline.py` | Final RQ4 comparison on one shared task set per stratum and seed: `rq5_three_way_baseline_comparison.{json,md}`. The `rq5` filename is a historical development label; the thesis research question is RQ4. |
| `make_figures.py` | Rebuilds all PDF/PNG files in `figures/` from canonical JSON. |

The structural audit and Phase-3 sanitiser live in
[`../scripts/analyze/`](../scripts/analyze/) because they materialise repository
artifacts rather than only summarising them. The unpublished
`rq4_phase3_compare.py` mixed raw and sanitised candidates and is not a thesis
result.

## Final inference rules

- **RQ2:** ten matched EA/random seed pairs per model-language stratum. Use the
  exact two-sided Wilcoxon signed-rank p-value and Vargha–Delaney A12 from
  `rq_wilcoxon_effect_sizes.json`. Holm correction is separate within each
  four-stratum lens: executed system, fenced code, and full contract.
- **RQ4:** twenty generation seeds per candidate on a task set shared by the
  no-rules condition, authored rules, and all five candidates of the stratum.
  Use `rq5_three_way_baseline_comparison.json`. The candidate-versus-authored
  tests form one twenty-test Holm family.
- All exact Wilcoxon p-values enumerate the permutation null over every 2^n
  sign assignment. The normal approximation is diagnostic only.
- The exact sign tests in older JSON are explicitly superseded and retained for
  the thesis Appendix F comparison.

## Running

Analyses that read raw runs require an unpacked copy of the DelftBlue archive:

```bash
export RULE_MUTATION_REPO=/path/to/checkout-with-unpacked-experiments
export ANALYSIS_OUT=/path/to/output/dir
.venv/bin/python analysis/scripts/rq1_magnitude.py
```

The final Wilcoxon artifact can be reproduced from the published JSON alone:

```bash
.venv/bin/python analysis/scripts/rq_wilcoxon_effect_sizes.py \
  analysis/results /tmp/rq_wilcoxon_effect_sizes.json
```

`make_figures.py` needs Matplotlib, deliberately absent from the frozen project
environment. The committed figures use Matplotlib 3.10.9. Run it from a
separate plotting environment with `ANALYSIS_BASE` pointing to a directory
containing `report/` (the results) and `figures/`.

## Interpretation

The three nested lenses contain 10,789 executed, 8,492 fenced-code-admissible,
and 6,191 full-contract-admissible evaluations. The two filtered lenses were
defined after the Phase-2 enforcement defect was found. They are exploratory
sensitivity analyses and do not reconstruct a fail-closed search.

Eight selected candidates already met the structural contract; twelve were
sanitised and rescored. Raw and sanitised candidates are never pooled. A lower
Semgrep count is not evidence of fewer vulnerabilities, secure code, or
functional correctness, and semantic equivalence to the authored rules was not
verified.
