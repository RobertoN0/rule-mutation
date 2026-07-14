# `src/optimizer` — where the search lives

Map for reviewing the search implementation:

| File | What it contains |
|---|---|
| **`search.py`** | **The algorithms.** `run_ea` — (1+1) EA with random initialization + periodic random injection. `run_random_search` — the i.i.d. random-search baseline. `build_random_chromosome` — the one shared random sampler both use. |
| **`engine.py`** | Everything around the algorithms: baseline evaluation, the whole-chromosome evaluation seam (LLM code generation + Semgrep, per-prompt cache under temperature=0), objective aggregation, and all result persistence (`iterations.jsonl`, `archive_snapshots/`, `mutated_rules/`, run summary). `ExperimentEngine.run_search` is the entry called by `scripts/experiments/run_experiment.py`. |
| **`chromosome.py`** | The representation: `RuleSetChromosome` (rule-text alleles + global rule-order priorities), `RuleSetSpace` (originals + prompt rendering + content-hash ids), `ChromosomeArchive` (single Pareto archive). |

## Objectives (conservative set — all maximized by the archive)

- **f1** — vulnerability reduction: severity-weighted Semgrep delta vs baseline
  (`objective_direction="minimize"` negates the raw delta, so positive f1 =
  fewer vulnerabilities = a repair).
- **f2** — rule fidelity: mean SBERT similarity of each mutated rule vs its
  original (1.0 = unchanged). Requires the quality validator (SBERT).
- **f3** — −parsimony: negated count of mutated rules (prefer the smaller edit).

The origin scores (0, 1.0, 0). Admission is a configurable ablation
(`archive_admission`):

- **`neutral_drift`** (default) — standard Pareto admission: a candidate is kept
  unless the origin or a front member dominates it. An objective-*equal* variant
  (e.g. an order-only change scoring (0, 1.0, 0)) is not dominated, so it is
  admitted and can act as a neutral stepping-stone parent.
- **`strict_repair`** — adds a hard security gate: a candidate must strictly
  improve f1 over the origin before Pareto admission is considered.

In **both** modes `best()` reports the origin unless some candidate *strictly*
improves f1, so neutral drift never pollutes the reported best repair (RQ3's
`best_f1`). Under cap overflow the archive evicts **lexicographically by f1**
(lowest f1 first, ties → f2+f3, then oldest), so an over-cap archive never drops
its best repair to keep a near-baseline variant; the just-added child is
protected.

## Random search (`run_random_search`)

Every iteration is **independent** — no carry-forward:

```
for iter in 1..budget:
    solution  = copy(origin)                     # fresh every iteration
    n_changes = random(1, K)                     # K = 10
    for i in n_changes:
        with prob 0.1: bump a random rule's order priority (front/back)
        else:          pick a rule uniformly (repeats allowed)
                       apply ONE random unused mutator to its CURRENT allele
    evaluate(solution) 
    record(solution)         # next iteration starts fresh (record only)
best = argmax f1 over all recorded solutions (origin = floor)

Iter = 0
parent = copy(origin)
n_changes = random(1, K)
while (iter < budget):
	n_changes = random(1, 10) 
	for i = 1 to n_changes
	        rule_index = random(1 to 21)
		solution = mutate(solution-rule[rule_index], 1) always apply 1 mutation to that rule.
		
	run(solution)
	save(solution) -> record the result, but next iter starts from scratch.
```

## (1+1) EA (`run_ea`)

```
evaluate(origin)                                  # baseline
for iter in 1..10:                                # phase = "init"
    child = build_random_chromosome(origin, K=10) # exactly the random sampler
    evaluate(child)
    archive.try_add(child)
for iter in 11..budget:
    if iter % 10 == 0:                      # phase = "injection"
        child = build_random_chromosome(origin, K=10)   # diversity
    else:                                         # phase = "ea"
        parent = uniform pick from front ∪ {origin}
        move   = draw {text-mutation 0.9, order-bump 0.1}
        child  = mutate ONE gene of parent        # 1 mutator, stacking (depth ≤ 4);
                                                  # a saturated gene reverts instead
    evaluate(child); archive.try_add(child)       # admission policy decides
```

**Budget & records.** `max_iterations` counts *distinct candidate evaluations*,
not proposals. An identity/no-op proposal (renders exactly like its base → a
free cache hit that measures nothing new) is logged and retried at the same
budget index without consuming it (an internal safety cap fails loud on a
degenerate all-no-op mutator pool). In practice the real runs
are **wall-time-bounded** (SLURM SIGUSR1), so `max_iterations` is a soft cap.
Each `iterations.jsonl` record carries `iter` (budget index), `attempt` (global
proposal id), `budget_consumed`, a `phase` field (`init` / `injection` / `ea` /
`random`), and `n_requested_changes ≥ n_attempted_changes ≥ n_effective_changes`
(requested slots → operators actually drawn → operations that changed the
chromosome). Stagnation restarts (`restart_h`) only clear per-parent tried-move
sets — the front is never wiped; rejected init/injection samples do not advance
local-EA stagnation.

### Rule-order operator

Rules carry a global integer **priority offset** (default 0); each prompt renders
its rules by descending offset via a *stable* sort, so equal offsets keep the
original retrieval order. The order operator is deliberately minimal: **one move
sends one rule to an extreme** — front (`max+1`) or back (`min−1`) of the current
offsets — and leaves every other rule's relative order untouched. This is
hill-climbable (the EA stacks good bumps on a parent) and any target permutation
is reachable by composing several such moves. Both arms share this same operator
(fired with probability `order_move_weight`), so random search and the EA differ
only in *selection*, not in the move set. A richer neighbourhood (adjacent swap,
insertion, or a whole-order shuffle) would replace `_order_extreme` +
`_available_local_moves`; note a full shuffle is a global, non-incremental move
(it discards the parent's order) — fine for the random sampler, but it removes
the EA's ability to *learn* an order incrementally, so it is not a drop-in for
the local move.

### Ablation knobs (not the main design)

- `archive_admission="strict_repair"` — require a strict f1 improvement to admit
  (vs the `neutral_drift` default); isolates the value of neutral drift.
- `ea_move="random_builder"` — the EA move becomes the random sampler applied
  to the archive parent, isolating *selection* as the only difference vs
  random search.
- `ea_n_mutations>1` — the local move stacks a 1..n mutator chain instead of
  exactly one mutation. (Chain atoms are marked tried individually, so >1 does
  not enumerate every chain ordering on a parent.)
- `ea_origin_parent=false` (`--no-ea-origin-parent`) — the origin stops being a
  *sampleable* local-move parent, so EA depth builds only on front members;
  isolates the value of the minimal parsimony-1 anchor. The origin still anchors
  dominance and `best()` either way.
