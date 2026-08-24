# Evidence map

This document answers one question: **given a number, table, or figure in the
thesis, where is the artifact that produced it?**

It also states plainly which parts of the study are in this repository, which
parts are archived outside it, and which revision of the code actually produced
the reported results.

Related documents: [ARCHITECTURE.md](ARCHITECTURE.md) (design),
[IMPLEMENTATION.md](IMPLEMENTATION.md) (modules and output schema),
[WORKFLOW.md](WORKFLOW.md) (running experiments),
[REPLICATION.md](REPLICATION.md) (reviewer reproduction).

---

## 1. Which code produced the results

This is the single most important distinction in the repository.

| Revision | What it produced |
|---|---|
| `09b6b963d47abbf1348f8dab10b5dbc97813c5ce` | **The executed system.** All 80 Phase-2 search arms and the Phase-3 candidate replays. Every `run_config.json` records this under `git_commit_sha`. |
| `20cba85b61c029a3665a03af16417299662b9b77` | The Phase-3 authored-rules and no-rules baselines, which were produced earlier and reused unchanged. A provenance audit confirmed identical model revisions, generation-contract hash, PyTorch/Transformers/Semgrep versions, and scanner-rule hash across both, with no intervening change to generation or sampling behaviour. |
| Commits after `09b6b96` | **Post-hoc tooling only.** The safe-zone audit, the Phase-3 sanitiser, the fail-closed masking fix in the live mutators, and their tests. None of this ran during Phase 2. |

Phase 2 specified a structural contract over each rule (frontmatter, fenced code
blocks, and inline code spans must stay byte-identical to the authored original)
but did not enforce it fail-closed. Candidates that broke it were evaluated and
archived. The audit and sanitiser under `scripts/analyze/` were written after
Phase 2 to measure and repair that, and the mutators were subsequently made
fail-closed. **Filtering stored trajectories identifies admissible candidates a
run visited; it does not reconstruct the trajectory a correctly constrained
search would have taken.** Every reported result distinguishes the executed
system from the intended-contract sensitivity view.

---

## 2. Report objects to artifacts

Figure and table numbers refer to the thesis PDF. Analysis JSON lives in
[`analysis/results/`](analysis/results/); the scripts that write it live in
[`analysis/scripts/`](analysis/scripts/).

### Main text

| Report object | Produced by | Canonical artifact |
|---|---|---|
| Figure 1 — three-phase framework | hand-drawn (draw.io) | figure source lives with the report, not here |
| Table 1 — mutation operators | source of truth is the code | [`src/mutation/rule_based.py`](src/mutation/rule_based.py), [`src/mutation/llm_based.py`](src/mutation/llm_based.py) |
| Table 2, Figure 2 — RQ1 magnitude | `rq1_magnitude.py` | `analysis/results/rq1_magnitude.{json,md}`, `analysis/figures/fig1_rq1_magnitude.{pdf,png}` |
| §5.1 — per-task spread behind the summed objective | extracted from the archived search trees | `analysis/results/rq1_per_task_distribution.json` |
| Table 3 — RQ2 paired EA vs random | `rq2_safe_zone_tiers.py`, `rq_wilcoxon_effect_sizes.py` | `analysis/results/rq2_safe_zone_tiers.{json,md}` for medians and intervals; `analysis/results/rq_wilcoxon_effect_sizes.json` for Wilcoxon p-values, Vargha-Delaney A12 and Holm decisions |
| Figure 3 — RQ2 across admissibility lenses | `rq2_safe_zone_tiers.py` + `rq_wilcoxon_effect_sizes.py` + `make_figures.py` | `analysis/results/rq2_safe_zone_tiers.{json,md}` for medians and intervals; `analysis/results/rq_wilcoxon_effect_sizes.json` for the p-values and Holm decisions the markers encode; `analysis/figures/fig2_rq2_safe_zone_tiers.{pdf,png}` |
| Table 4 — RQ3 move families | `rq3_mutators.py` | `analysis/results/rq3_mutators.{json,md}` |
| Figure 4 — RQ4 candidates vs authored rules | `rq5_three_way_baseline.py` + `make_figures.py` | `analysis/results/rq5_three_way_baseline_comparison.{json,md}`, `analysis/figures/fig7_rq4_survival.{pdf,png}`. The temperature-0 tick is the deterministic gain from `rq4_phase3_safe_comparison.json` |
| §5.4 — RQ4 three-way comparison (no rules, authored, candidate) | `rq5_three_way_baseline.py` | `analysis/results/rq5_three_way_baseline_comparison.{json,md}` |

### Appendices

| Report object | Produced by | Canonical artifact |
|---|---|---|
| Table 5 — rule coverage in final maps | Phase-1 map construction | [`rule_maps/qualified/`](rule_maps/qualified/) |
| Table 6 — population construction funnel | Phase-1 audit and screening | `rule_maps/qualified/source_population.json`, `analysis/results/analysis_readiness.{json,md}` |
| Table 7 — search parameters | recorded per run | any `run_config.json` in the archived tree; see §4 |
| Table 8 — sign test vs Wilcoxon by lens | `rq_wilcoxon_effect_sizes.py` | `analysis/results/rq_wilcoxon_effect_sizes.json` |
| Table 9 — evaluations admitted by each lens | `audit_search_safe_zones.py` | `analysis/results/search_safe_zone_audit.json` |
| Table 10 — non-compliant evaluations by broken component | `audit_search_safe_zones.py` | `analysis/results/search_safe_zone_audit.json` |
| Figure 5 — RQ3 detail | `rq3_mutators.py` + `make_figures.py` | `analysis/figures/fig4_rq3_operators_effectiveness.{pdf,png}` |
| Table 11 — RQ4 selected candidates | `rq5_three_way_baseline.py` | `analysis/results/rq5_three_way_baseline_comparison.{json,md}` |
| Appendix D — prompt templates | source of truth is the code | [`src/retrieval/rule_retrieval_mapping.py`](src/retrieval/rule_retrieval_mapping.py), [`src/evaluation/generation_contract.py`](src/evaluation/generation_contract.py), [`src/mutation/llm_based.py`](src/mutation/llm_based.py) |

The report's own consistency checker (`verify_report_numbers.py`, kept with the
report sources) validates every number printed in the thesis against these JSON
files.

**Statistical procedure.** The thesis reports Wilcoxon signed-rank tests with
Vargha-Delaney A12 effect sizes. p-values are exact, computed by enumerating the
permutation null over all 2^n sign assignments rather than by normal
approximation, which matters at n=10 with tied absolute differences. The exact
sign test used in an earlier version of this analysis is retained in
`rq_wilcoxon_effect_sizes.json` under `sign_test_p_superseded`, so the change of
procedure stays traceable. `rq5_three_way_baseline_comparison.json` supersedes
`rq4_phase3_safe_comparison.json` for every candidate-versus-authored number the
thesis prints, because it scores all conditions on one shared task set per
stratum and seed. The older artifact is kept unchanged for provenance only: no task count, drop
rate, median or p-value printed in the thesis is taken from it, with the single
exception of the temperature-0 tick in Figure 4.

---

## 3. Pipeline to artifacts

```
Phase 1  population + retrieval maps        -> rule_maps/qualified/              [in repo]
Phase 2  80 search arms (EA vs random)      -> experiments/03_search_runs/       [archived, §4]
         post-hoc structural audit          -> analysis/results/search_safe_zone_audit.json
Phase 3  candidate selection                -> analysis/results/phase3_selection_topk.{json,md}
         selected rule sets (20)            -> artifacts/phase3_selected/raw/
         sanitised rule sets (12)           -> artifacts/phase3_selected/sanitized/
         resampling at T=0.6                -> experiments/05_phase3_resampling/ [archived, §4]
         sanitised validation               -> experiments/06_safe_zone_validation/ [archived, §4]
         pairwise comparison (superseded)   -> analysis/results/rq4_phase3_safe_comparison.{json,md}
         three-way final comparison         -> analysis/results/rq5_three_way_baseline_comparison.{json,md}
```

Supporting checks, all in `analysis/results/`:

- `analysis_readiness.{json,md}` — completeness gate before any analysis was run.
- `baseline_reconciliation.{json,md}` — reconciles the reused Phase-3 baselines
  with the final task population.
- `phase3_order_priority_check.json` — verifies the rule ordering carried by
  each selected candidate's derived retrieval map.
- `safe_zone_validation.json` — compares each sanitised candidate's
  temperature-0 rerun with its immutable raw source evaluation.

---

## 4. What is here, and what is archived outside

The published repository contains the framework, the frozen Phase-1 inputs, the
compact analysis package, and the selected rule sets. It deliberately does not
contain the raw run trees, which total about **8.4 GB**.

**In this repository**

| Path | Contents | Size |
|---|---|---|
| `src/`, `scripts/`, `tests/` | the framework, launchers, validators, analysis entry points, 303 unit and contract tests | ~3 MB |
| `rule_maps/qualified/` | frozen task population and the four final retrieval maps | ~3 MB |
| `analysis/scripts/` | the canonical read-only analyses and the figure builder | ~350 KB |
| `analysis/results/` | every JSON/Markdown result the thesis cites | ~2 MB |
| `analysis/figures/` | regenerated PDF and PNG figures | ~1 MB |
| `artifacts/phase3_selected/` | the 20 selected rule sets, the 12 sanitised ones, their maps and manifests | ~6 MB |
| `project-codeguard/` | the authored rule library, as a submodule pinned at `8ec52cf4591bad0a541e3ee5ee6979522ee99757` | submodule |

**Archived outside the repository** (retained on DelftBlue under
`/scratch/rnegro`; not present in this workspace and not deposited publicly)

| Path | Contents | Size |
|---|---|---|
| `experiments/03_search_runs/` | 80 arms across 156 job directories: `run_config.json`, `evaluations.jsonl`, `search_summary.json`, `search_validation.json`, `evaluation_manifest.json`, archive snapshots, every mutated rule set, Semgrep debug output | 6.6 GB |
| `experiments/05_phase3_resampling/` | 17 job directories of temperature-0.6 candidate replays with per-task records | 352 MB |
| `experiments/06_safe_zone_validation/` | 21 job directories validating the sanitised candidates | 202 MB |
| `experiments/01_population_and_maps/` | Phase-1 retrieval sweeps and the Phase-3 screening baselines | 314 MB |
| `experiments/00_population_audit/`, `02_readiness_validation/` | source-population audit and readiness checks | 46 MB |
| `experiments/99_superseded/` | superseded waves, kept for provenance only | 969 MB |
| `logs/`, scheduler stdout and stderr | SLURM job output | — |

The generated code itself and the scheduler logs are the bulk of that volume.
Everything the thesis reports is derived from these trees by the scripts in
`analysis/scripts/`, and the derived results are published here in full.

---

## 5. Pinned resources

Every run records these; the values below come from the Phase-2 run
configurations and are identical across arms unless noted.

| Resource | Identifier |
|---|---|
| Framework revision (executed) | `09b6b963d47abbf1348f8dab10b5dbc97813c5ce` |
| CodeGuard rule corpus | submodule `8ec52cf4591bad0a541e3ee5ee6979522ee99757` |
| Generation contract | SHA-256 `feea801014f402f38ebbaacd06e144f5eca99e312e4668ffee58a22e98feec6e` |
| Retrieval template | version `v2_reframed_user_turn` |
| Qwen2.5-Coder-32B-Instruct | revision `381fc969f78efac66bc87ff7ddeadb7e73c218a7`, `float16` |
| Llama-3.3-70B-Instruct | revision `6f6073b423013f6a7d4d9f39144961bfbfbc386b`, 4-bit NF4 with `bfloat16` compute |
| Semgrep | 1.85.0; rule pack SHA-256 `94d988978252e3e2ea94a029055ba0a5c46aeb3058ff6e442a0794e8786a11ba`, source commit `5978684181e186dcbd85808ca98d51197caff5c5` |
| Sentence encoder | `all-mpnet-base-v2`, revision `e8c3b32edf54` |
| Runtime | PyTorch `2.12.0+cu126`, Transformers `5.9.0`, one NVIDIA A100 80 GB per run |
| Benchmark carrier | `walledai/CyberSecEval`, `instruct` configuration, revision `62dba0bb39c450c375aff453d3396fa8f2338eee` |
| Frozen source carrier | `full_prompt_carrier.json`, SHA-256 `92fc854e2f264a7c2e5e963267d623ffd80af1587fd8d05d21b49b3e0b05881d` |

Two resources are recorded less completely than the rest: the run configuration
does not store the full sentence-encoder revision or a hash of the staged
WordNet data, and while it records the resolved generation-model revision, the
backend did not pass that revision explicitly when loading. A replay should
verify both against the recorded artifacts rather than resolving the names anew.

---

## 6. Re-running the analyses

The analysis suite is read-only with respect to the experiment tree. Point it at
an unpacked copy of the archived runs:

```bash
export RULE_MUTATION_REPO=/path/to/checkout-with-unpacked-experiments
export ANALYSIS_OUT=/path/to/output/dir

.venv/bin/python analysis/scripts/check_analysis_readiness.py
.venv/bin/python analysis/scripts/baseline_reconcile.py
.venv/bin/python scripts/analyze/audit_search_safe_zones.py \
  --search-root "$RULE_MUTATION_REPO/experiments/03_search_runs" \
  --original-rules project-codeguard/skills/software-security/rules \
  --output "$ANALYSIS_OUT/search_safe_zone_audit.json"
.venv/bin/python analysis/scripts/rq1_magnitude.py
.venv/bin/python analysis/scripts/rq2_ea_vs_random.py
.venv/bin/python analysis/scripts/rq2_safe_zone_tiers.py
.venv/bin/python analysis/scripts/rq3_mutators.py
.venv/bin/python analysis/scripts/rq4_phase3_safe_compare.py
.venv/bin/python analysis/scripts/rq5_three_way_baseline.py
.venv/bin/python analysis/scripts/rq_wilcoxon_effect_sizes.py \
  analysis/results analysis/results/rq_wilcoxon_effect_sizes.json
```

`make_figures.py` needs `matplotlib`, which is deliberately absent from the
frozen environment. The committed figures use Matplotlib 3.10.9. From a
separate plotting environment, run it without path overrides to read
`analysis/results/` and write `analysis/figures/`. `ANALYSIS_BASE` remains
available for the historical `report/` plus `figures/` layout.

Without the archived experiment tree the scripts have nothing to read. The
published JSON in `analysis/results/` is the record of what they produced.

---

## 7. Known limitations of this package

- The structural contract was not enforced fail-closed during Phase 2 (§1).
- Bitwise reproduction of the DelftBlue runs is not promised. Generation used
  greedy temperature-0 decoding, but GPU determinism was not explicitly
  enforced, and the synonym augmenter drew from process-global Python and NumPy
  streams that were seeded at process start but not captured in the
  initialisation bundle.
- Semgrep findings are a proxy. A match may be a false positive and an absent
  finding may be a false negative. A lower count is not evidence of fewer
  vulnerabilities, of secure code, or of functional correctness.
- Semantic equivalence between a mutated rule and its authored original was
  never verified, and several operators deliberately weaken security guidance.
- Raw and sanitised Phase-3 candidates are kept in separate directories and
  their results are never mixed.
