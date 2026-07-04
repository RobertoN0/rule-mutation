# `scripts/analyze/` — SBST results-analysis toolkit

Everything here turns a finished experiment run (the `schema_version: 2` output
of `scripts/experiments/run_with_rules_map.py`) into **figures, tables, and
Markdown reports** for the thesis. Nothing here runs the model or Semgrep — it
only *reads* the artifacts a run already wrote, so it is cheap, offline, and
re-runnable. Every result the model produced (`generated_code`, `check_ids`,
the full mutated rule text, every objective value) is persisted, so essentially
any retrospective metric is recomputable here without re-running anything.

- [Quick start](#quick-start)
- [What the tools read](#what-the-tools-read)
- [Core concepts](#core-concepts)
- [Architecture](#architecture)
- [File-by-file reference](#file-by-file-reference)
- [The analyses (every CLI)](#the-analyses-every-cli)
- [Gotchas](#gotchas)
- [Extending the toolkit](#extending-the-toolkit)

---

## Quick start

```bash
# from the repo root; matplotlib/numpy live in the [analysis] extra
uv sync --extra analysis
VPY=.venv/bin/python          # call the venv python directly (see Gotchas)

# analyse ONE run into its own analysis/ dir:
R=experiments/results/<run>; A=$R/analysis
$VPY scripts/analyze/analyze_run.py          $R --out $A/run          # RQ1 significance + per-rule fitness + RQ2 + hygiene
$VPY scripts/analyze/outcome_distribution.py $R --out $A/outcomes     # degraded / safer / unchanged across scopes
$VPY scripts/analyze/fitness_trajectories.py $R --out $A/trajectories # per-rule f1 envelope over the search
$VPY scripts/analyze/analyze_mutators.py     $R --out $A/mutators     # RQ2 lineage (which mutators / chains)
$VPY scripts/analyze/analyze_security.py     $R --out $A/security     # named CWE / Semgrep-check flips
$VPY scripts/analyze/analyze_search.py       $R --out $A/search       # efficiency / restarts / Pareto front
$VPY scripts/analyze/analyze_cost.py         $R --out $A/cost         # tokens / cache / budget-matched

# merge into one curated quick-read, with a Source link to each full report:
$VPY scripts/analyze/collect_reports.py      $A                       # → $A/REPORT.md
```

Outputs go under whatever `--out` you pass (`analysis_output/` is gitignored; a
run's own `analysis/` dir is too). Pass **several run dirs or a parent directory**
to any CLI for a cross-run view — `collect_reports` then builds a cross-run REPORT
(highlights + a per-run index). For migrated Qwen runs, point at `$R/schema2`.

---

## What the tools read

A run directory contains:

| Path | Content used by the toolkit |
|---|---|
| `run_config.json` | args (optimizer, languages, seed, archive-cap, …), git sha, schema_version |
| `hillclimb_summary_*.json` | run totals: best/original fitness, wall time, tokens, `pool_arm_stats.mutator_stats`, `restart_reason_counts`, `eval_cache_stats` |
| `iterations.jsonl` | one row per search iteration: `rule_id`, `mutation_chain`, `f1/f2/f3`, `f1_advance`, `accepted`, `selection_meta.parent_f1`, … |
| `intermediate/baseline.jsonl` | per-prompt scan of the **original** (unmutated) rules — the reference point |
| `intermediate/ea_iterNNNN.jsonl` | per-prompt records for each iteration: `fitness{weighted_score, raw_count, error/warning_count, check_ids, code_divergence}`, `rules_used`, `generated_code`, latency, tokens |
| `archive_snapshots/iterNNNN.json` | per-rule Pareto archive every 20 iters: front entries with `f1/f2/f3`, `depth`, `mutation_chain`, `restart_history` (the **true** chains) |
| `mutated_rules/iterN/` | the mutated rule Markdown + `meta.json` |

### The three objectives (the EA always *maximises* f1 internally, over the prompts that use the rule)

- **f1 = the security fitness** (weights **ERROR=3, WARNING=1, INFO=0**), the primary signal.
  ⚠️ **Its sign depends on `objective_direction`** (recorded in `run_config.json`), because f1 is
  negated at search time so the EA can always maximise:
  - **`minimize` (the repair runs — all 20 final runs):** `f1 = baseline − mutated findings`, so
    **higher f1 = SAFER** (fewer vulnerabilities), negative f1 = more vulnerable.
  - **`maximize` (the legacy adversarial runs):** `f1 = mutated − baseline` (`total_semgrep_delta`), so
    **higher f1 = MORE vulnerable**, negative f1 = safer.
  Reporting resolves this via `loaders.direction_terms(run.objective_direction)` — never assume a sign
  from the raw value alone.
- **f2 = `proportion_divergent`** — fraction of affected prompts whose generated
  code changed at all (`code_divergence > 0`).
- **f3 = `conditional_mean_divergence`** — mean CodeBLEU divergence among those
  that changed.

f2/f3 are the *behavioural* axis (did the output move?), reported separately
from security so "different code" is never conflated with "more vulnerable code."

---

## Core concepts

**Scope / denominator.** Every rate can be computed over a different unit, and
the choice changes the headline number, so the toolkit reports all of them:

- **prompt** — one unit per test case, collapsed over every observed rephrasing
  of every retrieved rule (the readable "did this prompt ever get worse/safer?").
- **applicable** — one unit per `(rule, prompt)` where the rule was actually
  retrieved for that prompt (rule-faithful).
- **all_prompt_rules** — every mutated rule × every prompt, counting
  non-applicable pairs as unchanged (conservative, dilutes the rates).
- **micro** = pooled over units; **macro** = mean of per-rule rates.

**Outcome of a unit** (collapsed over all rephrasings, vs. baseline):
`degraded` (findings ever ↑), `safer` (ever ↓), `unchanged`, and the orthogonal
`code_changed` (output ever differed).

**Negative fitness is first-class.** Because mutations frequently make the model
write *safer* code (large negative f1, especially on Python), the toolkit
reports both directions wherever it summarises f1: the trajectory **envelope**
(max + min per rule), the per-rule **safest path**, the search front **min_f1**,
the **safer** outcome category, and the signed per-mutator **delta**.

**Migrated vs. native runs.** Pre-2026-05-29 runs were migrated into a
`schema2/` subfolder — **point the CLIs at `<run>/schema2`**. Their
`iterations.jsonl` is a reconstruction (`chain_length` is always 1, no
`parent_f1`), so the iteration-level lineage in `analyze_mutators` comes out
empty for them; use `analyze_run`'s RQ2 (and the archive-based combinations /
safest-paths, which still work) instead. Native runs (point at the run dir
directly) support everything.

---

## Architecture

Four layers, strictly one job per file, so adding a metric never grows an
existing file:

```
load  →  compute (metrics/)  →  present (viz/ + report/)  →  orchestrate (CLIs)
```

- A **metrics** module never plots or writes files — it returns dataclasses /
  row lists, so it is unit-testable.
- A **viz** module only draws (the single place that imports `matplotlib`).
- A **report** module only serialises (CSV + Markdown).
- A **CLI** only wires `loaders → metrics → viz/report` (each ≤ ~120 lines).

```
scripts/analyze/
  loaders.py            IO + lightweight derivations (RunData, discover_runs, …)
  records.py            typed accessors for the 3 granularities
  stats.py              statistics primitives (Wilcoxon, McNemar, sign, bootstrap, Wilson)
  metrics/
    outcomes.py         outcome-state core (UnitState, build_run_outcome)
    outcome_rows.py     outcome CSV/Markdown row builders + headers
    series.py           field-agnostic iteration/archive time-series engine
    mutators.py         RQ2 lineage: per-mutator delta, composition, paths
    security.py         per-CWE, Semgrep-check flips, severity shifts
    search.py           efficiency, restart reasons, Pareto front
    cost.py             tokens, cache, latency, budget-matching
  viz/
    style.py            backend, palettes, grid/savefig helpers (only matplotlib config)
    distributions.py    stacked outcome bars
    trajectories.py     per-rule grid / overlay / envelope
    mutators.py         per-mutator delta bar, position heatmap
    security.py         check-flip bar, per-CWE bar
    search.py           restart bar, convergence overlay
  report/
    tables.py           shared write_csv / md_table / fmt_pct / fmt_ci
    outcomes.py mutators.py security.py search.py cost.py   per-family CSV+MD assembly
  <CLIs>                outcome_distribution, fitness_trajectories, analyze_mutators,
                        analyze_security, analyze_search, analyze_cost, collect_reports,
                        analyze_run, compare_runs (legacy), validation_audit, migrate_legacy_run
```

---

## File-by-file reference

### Foundation

- **`loaders.py`** — the only file that touches the filesystem. `RunData` lazily
  exposes a run; `load_run` / `discover_runs` find runs from a dir or parent dir;
  `read_jsonl` tolerates a truncated final line. Plus pure derivations used
  across the toolkit: `valid_iters`, `best_iteration`, `per_rule_best`,
  `per_rule_worst`, `convergence`, `best_f1`, `iter_to_first_best`,
  `baseline_findings`, `iteration_findings`, `mutator_stats`,
  `per_mutator_outcomes`, `cache_stats`, `restart_reason_counts`, `identity_rate`.
- **`records.py`** — typed accessors so no module hand-parses nested dicts:
  `get_path` (dotted access), prompt getters (`weighted_score`, `raw_count`,
  `error_count`, `code_divergence`, `check_ids`, `is_applicable`, …), iteration
  getters (`mutation_chain`, `objectives`, …), `short_rule`.
- **`stats.py`** — `wilcoxon_paired`, `mcnemar_binary`, `sign_test`,
  `bootstrap_ci`, `wilson_ci`; all degrade gracefully (return `p=None` + a note
  instead of raising on tiny/degenerate samples).

### `metrics/` (pure compute)

- **`outcomes.py`** — `UnitState` (collapses one prompt / rule-prompt over all
  rephrasings: tracks ever-up/ever-down, min/max findings, code-changed),
  `build_run_outcome`, `states_for_scope`, `distribution`, `lang_key`,
  `run_label`.
- **`outcome_rows.py`** — owns the outcome CSV schemas (header constants) and
  the micro/macro/per-rule/envelope/summary/pair row builders.
- **`series.py`** — `iteration_series(run, field, by, agg)` and
  `archive_series(run, field, reduce)` turn any numeric field that varies over
  the search into per-rule or global `Series`. `agg ∈ {value, best_so_far,
  worst_so_far, running_mean}`; `reduce ∈ {max, min}` picks the front extreme.
- **`mutators.py`** — `lineage_steps` (each step = `f1 − parent_f1` credited to
  the last chain mutator), `per_mutator_delta` (position-aware), `position_table`,
  `composition_compare` (LLM / structural / mixed), `combination_counts`,
  `per_rule_best_path`, `per_rule_safest_path`, `insert_rate_rows`. `LLM_MUTATORS`
  = {negation_injection, voice_change, paraphrase}.
- **`security.py`** — `cwe_rows`, `severity_rows`, `check_flip_rows` (which exact
  Semgrep checks a rephrasing made appear/disappear).
- **`search.py`** — `efficiency_row`, `restart_rows`, `final_front_rows`
  (per-rule front with `min_f1`/`max_f1`).
- **`cost.py`** — `cost_row`, `latency_row`, `best_f1_at`, `budget_rows`,
  `matched_budgets`.

### `viz/` (plotting) and `report/` (serialisation)

`viz/style.py` configures the Agg backend and owns the palettes (`OUTCOME_COLORS`,
`OBJECTIVE_COLORS`), `grid_dims`, `distinct_colors`, and `savefig`; the other
`viz/*` modules each draw one family's figures. `report/tables.py` holds the
shared `write_csv` / `md_table` / `fmt_pct` / `fmt_ci`; each `report/<family>.py`
assembles that family's CSVs + Markdown (and triggers its figures).

---

## The analyses (every CLI)

All CLIs accept one or more run dirs **or** a parent dir, and `--out <dir>`
(default under `analysis_output/`). Reports render inline if you open the `*.md`.

### `analyze_run.py` — single-run RQ1 + RQ2 + hygiene
**What.** The classic one-run report. **Why.** The fastest "what happened in
this run?" — answers RQ1 and RQ2 for one run without needing a baseline arm.
**Produces:** `summary.md` plus
- **RQ1 significance** — paired **Wilcoxon + McNemar** on baseline-vs-best findings over all prompts;
- the **per-rule fitness reach** figure (`per_rule_fitness.png`) — most-vulnerable (red) vs safest (green) f1 per rule, the headline visual;
- RQ1 detail `rq1_per_rule.csv` — per rule: baseline→best findings, Δ, winning chain, **`safest_f1` + `safest_chain`**;
- RQ2 `rq2_per_mutator.csv` + `rq2_mutator_effective_rate.png` — per-mutator f1-advancing rate + 95% bootstrap CI;
- `convergence.png` (secondary, best-so-far f1 over iterations).
**Run.** `analyze_run.py <run_dir> [--out <dir>]` (one run only; default out is
`<run>/analysis`). Works on migrated runs (use the `schema2` subdir).

### `outcome_distribution.py` — the bd-7kr results framing (RQ1 / RQ3)
**What.** Per-prompt headline + rule-prompt backing view across the three scopes.
**Why.** "Best fitness" is the wrong summary for a multi-rule, multi-objective
search; this is the prompt-level paired view (Cisco-blog intuition) adapted to
the experiment, and the agreed framing for the Results chapter. **Produces:** per run — `prompt_outcomes`,
`rule_prompt_outcomes_{applicable,all_prompt_rules}`, `per_rule_*`,
`micro_summary`, `macro_summary`, `prompt_envelope_totals` (baseline vs
worst/best observed), `outcome_distribution.{md,png}`; across runs —
`runs_summary`, `aggregate_by_strategy_language`, `rq3_prompt_pairs` (McNemar
EA-vs-random), `outcome_comparison.md` (with a **field-reference glossary**).
**Run.** `outcome_distribution.py <run_or_parent> [--out] [--code-divergence-threshold 0.0]`.

### `fitness_trajectories.py` — per-rule fitness variation over the search
**What.** How a field evolves per rule (one curve per archive, ~21) as a
small-multiples grid + an overlay. **Why.** A single best-f1 number hides the
dynamics; this shows convergence, which rules drive gains, and — via the
**envelope** — how far the search pushed each rule to higher and lower fitness.
Colours follow `objective_direction` (see `direction_terms`): under **minimize**
(the repair runs) the high-fitness extreme is the *safer* one (green) and the
low-fitness extreme is *more vulnerable* (red); under maximize the colours flip.
**Produces:** `grid_*`/`overlay_*` PNGs,
`series_long.csv`, `trajectories.md`.
**Run.** `fitness_trajectories.py <run_or_parent>`
- `--source iterations` (dense, every iteration) | `archive` (authoritative front state)
- `--fields f1,f2,f3,archive_size_after,…` (any numeric iteration field)
- `--direction best|worst|envelope` — default **auto**: envelope for f1 (so
  negatives show), best for f2/f3 (which are ≥0)
- `--agg value|best_so_far|worst_so_far|running_mean`, `--keep-flat`
(flat, never-changing rules are dropped from the overlay and listed beneath it).

### `analyze_mutators.py` — RQ2 mutation × fitness lineage (bd-03k.1)
**What.** Which mutators (and chains, and orders) actually move security.
**Why.** RQ2; turns the abstract objective into "this mutator, at this depth,
changed f1 by this much." **Produces:** per run — `lineage_steps`,
`per_mutator_delta` (signed, position-aware), `position_table`,
`composition_compare` (LLM vs structural vs mixed), `combinations`,
`per_rule_best_path`, **`per_rule_safest_path`**, `insert_rates`, a signed
`per_mutator_delta.png` bar + a `position_heatmap.png`; with several runs, a
`_pooled/` multi-seed view. **Run.** `analyze_mutators.py <runs_or_parent>
[--no-pooled]`. (Iteration-lineage parts are empty on migrated runs — see Core
concepts; the archive-based paths still populate.)

### `analyze_security.py` — named CWEs and Semgrep checks (RQ1 detail)
**What.** Turns f1 deltas into concrete vulnerabilities. **Why.** The Results
chapter needs "which vulnerability appeared," not just a number. **Produces:**
`cwe_table` (per-CWE degraded/safer), `check_flips` (which exact checks a
rephrasing added/removed, per prompt), `severity_shift` (error/warning gains and
losses), `check_flips.png`, `cwe_outcomes.png`, `security.md`.
**Run.** `analyze_security.py <run_or_parent> [--code-divergence-threshold 0.0]`.

### `analyze_search.py` — search behaviour (RQ3 + the EA mechanics)
**What.** How efficiently the (1+1) EA climbs and how its archives behave.
**Why.** RQ3 (EA vs random efficiency) and methodology validation — e.g. the
restart breakdown is the evidence that `stagnation` never fires under
`restart_h=8` (bd-qfm). **Produces:** per run — `efficiency` (best_f1,
time-to-best, positive/acceptance/identity rates), `restart_reasons` (+ bar),
`final_front` (per-rule `min_f1`/`max_f1`, depth, insert/reject counts),
`search.md`; with several runs — `_comparison/efficiency_comparison` + a
`convergence.png` overlay. **Run.** `analyze_search.py <runs_or_parent>
[--no-comparison]`.

### `analyze_cost.py` — operational + fair comparison
**What.** Wall time, LLM calls, token burn, eval-cache hit rate, per-prompt
latency, and **budget-matched** best-f1. **Why.** Reporting cost, and comparing
runs (e.g. Qwen vs Llama) only at **equal iteration budgets** — never at raw
unmatched iteration counts. **Produces:** `cost`, `latency`, `budget_matched`
(best-f1 at matched-quartile budgets), `cost.md`. **Run.** `analyze_cost.py
<runs_or_parent> [--budgets 33,78,136]` (default: matched quartiles of the
shortest run). Token-over-iteration curves come from `fitness_trajectories
--fields input_tokens_total`.

### `compare_runs.py` — legacy cross-run (RQ3 + multi-seed)
**What.** Per-seed best-f1, paired EA-vs-random sign/Wilcoxon, convergence bands
(median + IQR across seeds), cross-strategy per-mutator rate, multi-seed
aggregation. **Why.** The original RQ3 view; complements
`outcome_distribution`'s prompt-level pairs. **Run.** `compare_runs.py
<runs_or_parent> [--out]`.

### `collect_reports.py` — one quick-read `REPORT.md`
**What.** Merges the `*.md` under a directory into one `REPORT.md` (TOC, one
`Source:` link per section, image links rewritten so PNGs render), curated to the
headlines so the CSV/PNG clutter stays out of view. **It adapts to run count:**
- **single run** → the per-run reports (summary, outcomes, security, mutators,
  trajectories, search, cost), each trimmed to its headline tables/figures.
- **multiple runs** → the cross-run highlights (outcome comparison + RQ3, pooled
  mutators, efficiency comparison, cost), then a per-run index linking each run's
  detail reports (not inlined, to stay short).

**Why.** Read results top-to-bottom without opening 15 files; drill into any full
report via its `Source:` link. **Run.** `collect_reports.py [root=analysis_output]
[--out PATH] [--full]` (`--full` inlines every report verbatim, no curation).

### `validation_audit.py` — quality-gate audit (validation runs only)
**What.** For `--enable-validation` runs: per-criterion fail rate, per-mutator
pass rate, and a "what if we had gated" simulation. **Run.** `validation_audit.py
<val_run> [--sbert-threshold 0.75] [--perplexity-threshold 2.5] [--keyword-threshold 0.70]`.

### `migrate_legacy_run.py` — one-off schema upgrade
Converts a pre-`schema_version: 2` run into a self-contained `schema2/` folder.
Only needed for old runs; native runs already conform.

---

## Gotchas

- **Use `.venv/bin/python` directly.** `matplotlib`/`numpy` are in the
  `[analysis]` extra (`uv sync --extra analysis`); the system Python lacks them.
- **The shell is zsh.** Unquoted `$VAR` does **not** word-split, so a
  space-joined variable of run paths becomes one bad argument. Pass run dirs as
  literal args, a glob (`experiments/results/job1006582*`), or a zsh array.
- **Migrated runs:** point at `<run>/schema2`, and expect empty iteration-lineage
  in `analyze_mutators` (use `analyze_run` RQ2 there).
- **Outputs are gitignored** (`analysis_output/`). Only the scripts are version
  controlled; regenerate reports anytime.
- **No random baseline?** Everything except RQ3 (EA-vs-random) still works — the
  within-run reference is the *original rule*, not the random strategy. Cross-run
  Qwen-vs-Llama / Python-vs-Java comparisons are EA-vs-EA and fully valid.

---

## Extending the toolkit

To add an analysis: write `metrics/<family>.py` (pure functions returning row
lists), optionally `viz/<family>.py` (drawing only) and `report/<family>.py`
(CSV+MD), then a thin `analyze_<family>.py` CLI that calls
`loaders.discover_runs` → metrics → report. Reuse `records` for field access,
`stats` for tests, `report.tables` for serialisation, and `viz.style` for
figures. Keep compute out of viz/report and IO out of metrics so each piece
stays testable.

