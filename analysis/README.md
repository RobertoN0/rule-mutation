# Analysis package

The read-only analyses behind the thesis results, the JSON and Markdown they
produce, and the figures built from that JSON.

Nothing here writes to the experiment tree. Each script opens run directories
for reading and writes a single result file.

See [EVIDENCE_MAP.md](../EVIDENCE_MAP.md) for the mapping from each table and
figure in the thesis to the artifact below that produced it.

## Layout

```
analysis/
├── scripts/     the canonical analyses + the figure builder
├── results/     every JSON/Markdown result the thesis cites
└── figures/     regenerated PDF + PNG figures
```

## Scripts

| Script | Produces |
|---|---|
| `common.py` | shared loaders, the arm index, and the statistics helpers used by every analysis |
| `check_analysis_readiness.py` | `analysis_readiness.{json,md}` — completeness gate; run before anything else |
| `baseline_reconcile.py` | `baseline_reconciliation.{json,md}` — reconciles the reused Phase-3 baselines against the final task population |
| `rq1_magnitude.py` | `rq1_magnitude.{json,md}` — RQ1 estimation |
| `rq2_ea_vs_random.py` | `rq2_ea_vs_random.{json,md}` — RQ2 paired EA vs random |
| `rq2_safe_zone_tiers.py` | `rq2_safe_zone_tiers.{json,md}` — RQ2 across the three admissibility lenses |
| `rq3_mutators.py` | `rq3_mutators.{json,md}` — RQ3 move-family associations |
| `phase3_select_topk.py` | `phase3_selection_topk.{json,md}` — the 20 selected candidates |
| `rq4_phase3_safe_compare.py` | `rq4_phase3_safe_comparison.{json,md}` — RQ4 under resampling |
| `make_figures.py` | everything in `figures/` |

The structural audit and the Phase-3 sanitizer live in
[`../scripts/analyze/`](../scripts/analyze/) rather than here, because they read
and write repository artifacts rather than only summarising them.

One script is deliberately **not** published: `rq4_phase3_compare.py` analyses
the historical raw Phase-3 mixture. It is a diagnostic, it mixes raw and
sanitized candidates, and it is not the thesis result.

## Running

```bash
export RULE_MUTATION_REPO=/path/to/checkout-with-unpacked-experiments
export ANALYSIS_OUT=/path/to/output/dir
.venv/bin/python analysis/scripts/rq1_magnitude.py
```

Both variables default to the paths this study ran under, so the scripts behave
identically to the recorded runs when neither is set. They need the archived
experiment tree described in [EVIDENCE_MAP.md](../EVIDENCE_MAP.md) §4; without
it there is nothing to read, and `results/` is the record of what they produced.

`make_figures.py` needs `matplotlib`, which is intentionally absent from the
frozen environment. Run it from a separate plotting environment and set
`ANALYSIS_BASE` to the directory containing `report/` and `figures/`.

## Reading the results

Each `.md` file is a human-readable rendering of its `.json` sibling; the JSON is
canonical. Two conventions matter when reading them:

- **Admissibility lenses.** Results are reported under three nested lenses:
  *executed system* (every candidate that ran), *fenced code* (fenced blocks
  match the authored original, inline code may drift), and *full contract*
  (inline code preserved too). The two filtered lenses were defined after the
  Phase-2 enforcement defect was found and are sensitivity analyses, not
  reconstructions of a fail-closed search.
- **Raw versus sanitized candidates.** Eight of the twenty selected candidates
  already satisfied the structural contract; twelve were repaired and rescored.
  The two are never pooled. `candidate_kind` distinguishes them in
  `rq4_phase3_safe_comparison.json`.
