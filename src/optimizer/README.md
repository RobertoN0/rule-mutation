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

The origin scores (0, 1.0, 0). Admission is **standard Pareto admission**: a
candidate is kept unless the origin or a front member dominates it. An
objective-*equal* variant (e.g. an order-only change scoring (0, 1.0, 0)) is not
dominated, so it is admitted and can act as a neutral stepping-stone parent
(neutral drift).

`best()` reports the origin unless some candidate *strictly* improves f1, so
neutral drift never pollutes the reported best repair (RQ3's `best_f1`). Under
cap overflow the archive evicts **lexicographically by f1**
(lowest f1 first, ties → f2+f3, then oldest), so an over-cap archive never drops
its best repair to keep a near-baseline variant; the just-added child is
protected.

## Random search (`run_random_search`)

Every iteration is **independent** — no carry-forward:

```
evaluate(origin)                                    # baseline
iter = 0
while iter < budget:
  child = copy(origin)                              # fresh every iteration
  n_changes = random(1 to K)                        # K = 10

  for i = 1 to n_changes:
    if random(0 to 1) < reorder_prob:               # bump one rule's order priority
      rule_index = random(1 to 21)
      direction  = random(front, back)
      child = reorder(child, rule_index, direction)  # applied to the CURRENT child, not to origin
    else:                                            # apply one unused mutator
      rule_index = random(1 to 21)                   # among rules with room + an unused mutator
      mutation   = random(unused_mutators[rule_index])
      child = mutate(child, rule_index, mutation)    # stacks on the CURRENT child, not on origin

  run(child)
  save(child)                                        # next iteration starts fresh from origin
  iter = iter + 1

best = argmax f1 over all saved children (origin = floor)
```

## (1+1) EA (`run_ea`)

```
evaluate(origin)                                    # baseline
iter = 0
while iter < 10:                                    # phase = "init"
    child = random_sample(origin, K=10)              # exactly the random-search algorithm above, one shot
    evaluate(child)
    archive.try_add(child)
    iter = iter + 1

stagnation_counter = 0
reseed_remaining = 0                                    # >0 while re-seeding after a stagnation wipe
while iter < budget:
    if reseed_remaining > 0:
        phase = "restart"                               # reseeding after a stagnation-cap wipe
    elif (iter - 9) % 10 == 0:                          # every 10th iter AFTER init
        phase = "injection"
    else:
        phase = "ea"
        if stagnation_counter >= restart_h:             # no accepted child for restart_h "ea"-phase attempts
            archive.front = {}                            # WIPED outright (ARIEL-style restart-on-stagnation)
            origin.tried  = {}                            # origin (the only parent left) re-opened too
            reseed_remaining = init_random_samples        # this iter + the next N-1 reseed like "init"
            stagnation_counter = 0
            phase = "restart"

    if phase in ("injection", "restart"):
        if phase == "restart":
            reseed_remaining = reseed_remaining - 1       # this iter consumes one reseed slot
        child = random_sample(origin, K=10)
    else:                                                # phase == "ea"
        parent = random(archive ∪ {origin})               # origin included iff ea_origin_parent flag is on
        move = draw {mutate 0.9, reorder 0.1}
        if move == reorder:
            rule_index = random(1 to 21)
            direction  = random(front, back)
            child = reorder(parent, rule_index, direction)
        else:
            rule_index = random(1 to 21)                  # among parent's rules with room
            if rule_index has no room left (saturated):
                child = revert(parent, rule_index)         # drop back to the ORIGINAL rule text
            else:
                mutation = random(unused_mutators[rule_index])
                child = mutate(parent, rule_index, mutation)  # stacks on parent's CURRENT allele

    accepted = archive.try_add(child)                    # standard Pareto admission
    if accepted:
        stagnation_counter = 0                            # ANY accepted child resets the clock
    elif phase == "ea":                                   # init/injection/restart rejections don't count
        stagnation_counter = stagnation_counter + 1
    iter = iter + 1
```

**Budget & records.** `max_iterations` counts *distinct candidate evaluations*,
not proposals. An identity/no-op proposal (renders exactly like its base → a
free cache hit that measures nothing new) is logged and retried at the same
budget index without consuming it (an internal safety cap fails loud on a
degenerate all-no-op mutator pool). In practice the real runs
are **wall-time-bounded** (SLURM SIGUSR1), so `max_iterations` is a soft cap.
Each `iterations.jsonl` record carries `iter` (budget index), `attempt` (global
proposal id), `budget_consumed`, a `phase` field (`init` / `injection` / `ea` /
`restart` / `random`), and `n_requested_changes ≥ n_attempted_changes ≥
n_effective_changes` (requested slots → operators actually drawn → operations
that changed the chromosome). A stagnation restart (`restart_h` consecutive
rejected "ea"-phase attempts) wipes the front outright and spends the next
`init_random_samples` iterations reseeding it from fresh origin-based random
samples, exactly like `init` (ARIEL-style restart-on-stagnation, not a mere
tried-set reopen); an `"exhausted"` restart (no eligible parent has any move
left) still only reopens tried-move sets, front kept. Rejected
init/injection/restart samples do not advance local-EA stagnation.

### Rule-order operator

Rules carry a global integer **priority offset** (default 0); each prompt renders
its rules by descending offset via a *stable* sort, so equal offsets keep the
original retrieval order. The order operator is deliberately minimal: **one move
sends one rule to an extreme** — front (`max+1`) or back (`min−1`) of the current
offsets — and leaves every other rule's relative order untouched. This is
hill-climbable and any target permutation
is reachable by composing several such moves. Both arms share this same operator, fired with probability `order_move_weight`.

### Ablation knobs (not the main design)

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
