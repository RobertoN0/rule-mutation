# Optimizer

The optimizer searches over whole mapped rule sets.

| File | Responsibility |
|---|---|
| `chromosome.py` | Chromosome representation, rendering space, Pareto archive |
| `search.py` | Archive-based EA, independent random search, shared sampler |
| `initialization.py` | Strict shared-prefix bundles and RNG/cache restoration |
| `engine.py` | Baseline, candidate evaluation, persistence, dispatch |

## Chromosome

A chromosome contains text overrides for mutated rules and global rule-order
priorities. Unchanged rules resolve through `RuleSetSpace.originals`. Only rules
that occur in the frozen task-to-rule mapping belong to the space.

The origin is the all-original configuration. It is evaluated as the baseline
and remains the reporting floor, but it is not a front member, admission
threshold, or EA parent.

## Objectives

The archive maximizes:

- f1: raw Semgrep-finding reduction from the origin;
- f2: mean SBERT fidelity of mutated rules;
- f3: negative number of mutated rules.

## Shared initialization

Both strategies begin with five independent origin-based random candidates.
They are outside the main-loop budget, so total logical evaluations equal
`5 + main_loop_budget`.

Final matched runs load the same strictly keyed initialization bundle. The
bundle restores candidate evidence, search/mutator/Torch RNG states, and the
evaluation cache at the five-candidate boundary.

## EA

The five candidates create the initial Pareto front. For main-loop evaluation
`t`:

```text
if t is an injection point:
    child = independent origin-based random sample
else:
    parent = deep copy of a uniformly sampled front member
    draw mutate with probability 0.9, reorder with probability 0.1
    mutate:
        sample from all mapped rules
        apply one lineage-unused mutator when available
        revert a saturated mutated rule
    if no render-changing move:
        try another rule on the same parent
        then another front parent
        then an origin-based random sample
evaluate child
offer child to the Pareto archive
```

Identity proposals are recorded but do not consume an evaluation.

### Archive contract

The archive is never cleared and its capacity (`--archive-cap`) is **six** for
the final matrix. `ParetoArchive.try_add` applies, in order:

1. **duplicate** — reject if the child's `cid` already exists (including the
   origin);
2. **dominated** — reject if any front member dominates the child;
3. **accept** — evict every front member the child dominates;
4. **overflow** — if the front still exceeds the cap, evict the weakest member
   by lexicographic `(f1, f2 + f3, −invalid_count, age)`.

The just-added child is **structurally protected from overflow eviction**: the
child is appended last and eviction only ever selects from `survivors[:-1]`, so
the candidate that was just paid for with an evaluation can never be discarded
in the same step. Every accept and eviction is logged and each evaluation writes
an `archive_snapshots/evaluation_NNNN.json` with the front, the cap, and the
running insert/reject counters.

`_consider_best_ever` runs **before** any of the above, so a candidate counts
towards the reported best fitness even when the archive rejects it as a
duplicate or as dominated — this is also what makes the five shared
initialization candidates eligible to be the reported best.

## Random search

After the same five candidates, every main-loop candidate is an independent
sample from the origin. There is no archive and no carry-forward. The best
evaluated candidate is reported, with the origin as floor.

## Records

`evaluations.jsonl` distinguishes:

- `evaluation_index` from proposal `attempt_index`;
- initialization from main-loop evaluations;
- completion time within the main loop;
- evaluated candidates from identity retries;
- new evaluations from initialization-bundle or cache reuse.

The field-level contract is in
[IMPLEMENTATION.md](../../IMPLEMENTATION.md#output-schema).
