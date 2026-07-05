# Archive / Chromosome Restructure Plan (v2 — decisions folded in)

**Status:** planning (no code changed). Branch `rule-set-archive`. Target: code complete
**Mon 2026-07-06**, then validation runs, then scale out before the follow-up meeting.
**Trigger:** 2026-07-03 supervisor meeting — the per-rule archive does not match the
intended evolutionary-search interpretation.
Sources: `asr_audio_transcription/transcripts/meeting-0307/meeting-0307.summary.md`.

The change in intent: **the unit of search and the unit stored in the archive is the entire
rule set (a "chromosome") — its rule *texts* and their *insertion order* — not a single rule
("gene").**

> **v2 update:** folds in the 2026-07-04 decisions — rule *order* is now a first-class gene
> handled at structure + cache level; the random baseline keeps 1–4 mutations/iter but
> re-derives each picked gene from the original and carries the chromosome forward; the
> evaluator is refactored to a pure **"runner mutates → evaluator renders"** seam; schema 3
> is a clean break; archive cap locked at 6; restart = option b; reverse built-but-gated.

---

## 0. Decision ledger (settled 2026-07-04)

| # | Decision | Status |
|---|---|---|
| D1 | Chromosome = (per-gene rule text alleles) **+ (global rule order — see D13)** | settled |
| D2 | Cache key = per-prompt **structured signature** over ordered `(rule_id, text_hash)` | settled |
| D3 | Order handled in structure + cache **now**; order *mutator* built but **gated** | settled |
| D4 | Random baseline: 1–4 mutators/iter, **applied to the ORIGINAL** allele of the picked gene, overwrite that gene, carry the chromosome forward | settled |
| D5 | Evaluator refactored to `evaluate_chromosome(genes, order)` — **runner mutates, evaluator renders** | settled |
| D6 | EA + random both **start from the original chromosome**; comparability via equal budget (not equal move operator) | settled |
| D7 | Archive cap = **6** (2× objectives), locked | settled |
| D8 | Restart = **option b** (never wipe the front; origin always available; stagnation re-opens exploration) | settled |
| D9 | Reverse mutation: structure **now**, activation **gated** (EA-only, default prob 0) | settled |
| D10 | **Schema 3, clean break** — no schema-2 compatibility compromises | settled |
| D11 | Fields stay `f1/f2/f3`; report says "fitness" only when f1 shown alone | settled |
| D12 | EA mutations/iter: default **1** (Design A) exposed as config knob `ea_n_mutations`; Design B (EA=1–4) is a flag flip | settled |
| D13 | Order = per-rule **global priority offsets** (default 0). Baseline render = **exact retrieval order** via stable sort; mutations perturb priorities. No canonical-order approximation | settled (supersedes the earlier canonical-permutation idea) |
| D14 | `scripts/experiments/baseline_harness.py` (2nd consumer of the eval seam, `:431`) migrated to the new `evaluate_chromosome` seam | settled |
| D15 | Loose coupling: `should_stop_fn` passed explicitly (no `getattr(self,...)` stash); `reference_codes` set via a method, not external dict write | settled |

---

## 1. Intended new architecture

* **Gene** = one rule (`rule_id`) with a text allele (original or mutated).
* **Order gene** = one global permutation over `all_rule_ids`. Each prompt renders its own
  rules *filtered through* this global order. (Global, not per-prompt: we search for one
  generalizable ordering policy, consistent with the global-repair framing. Per-prompt order
  = state explosion + per-task customization → rejected.)
* **Chromosome** = the full rule set: `{rule_id → allele}` **plus** the global order. Rendered
  into each prompt's system prompt by joining that prompt's rules (in global-order) with
  `"\n\n---\n\n"`.
* **Archive** = a single Pareto set of chromosomes over (f1 = total semgrep delta, f2 =
  proportion divergent, f3 = conditional mean divergence). Dominance unchanged
  (`pareto_archive.py:66-78`). Cap = 6 (D7).
* **One EA iteration:** pick a parent chromosome → pick a move (mutate one gene's text /
  reorder / revert) → the runner builds the child chromosome → the evaluator renders every
  prompt and scores the whole chromosome → offer to the archive by Pareto dominance.
* **Random baseline:** one persistent chromosome; each iteration overwrites one gene with a
  fresh 1–4 chain from the original; always carried forward; no archive.
* **Deltas are always vs the original rule set** (baseline per-case Semgrep score + reference
  code captured at iteration 0, `hill_climber.py:1007-1017`) — preserved verbatim.

Thesis framing unchanged: global/generalizable rule repair (rule *wording* and rule *order*)
evaluated across all tasks that use those rules; the archive stores best **solutions**, not
best genes.

### 1.1 Rule order — confirmation of current behavior

Order today is the per-prompt **retrieval order** (`m.rules_retrieved`), concatenated into
`combined_rules`, and the cache hashes that concatenation. So order is *implicitly* in the
cache key but is **fixed** (nothing varies it) and **per-prompt** (globally inconsistent:
prompt A can want X before Y while prompt B wants Y before X). Nothing treats order as a
searchable dimension. Evidence: `run_with_rules_map.py:207-210`, `rule_mapping.py:307-309`,
cache key `hill_climber.py:769-772`.

### 1.2 Rule order — chosen design (per-rule global priority offsets, D13)

The real map (`map_qwen32b_python_java.json`: 22 rules, 580 prompts, avg 2.89 rules/prompt,
max 9, 14 single-rule + some 0-rule prompts) has **globally inconsistent** per-prompt
retrieval orders (a rule appears at different positions in different prompts). So a single
global permutation cannot reproduce the baseline. Instead:

1. The chromosome carries `order_priority: dict[rule_id → int]`, **default empty (all 0)**.
2. **Per-prompt render order = stable-sort the prompt's retrieval order by `-priority`**:
   `sorted(pwr.rule_ids, key=lambda r: -order_priority.get(r, 0))`. Python's stable sort
   keeps the retrieval order for equal priorities.
3. **All-0 (baseline, and every order-gated-off run) ⇒ render == exact retrieval order** —
   faithful, no approximation, no canonical-order decision. This *is* "the baseline's order
   for base ordering." It also means the gated-off base experiments render identically to the
   current pipeline.
4. **Order mutator** (chromosome-level — see §3/§4): move-to-front / move-to-back (bump a
   rule's priority above/below its neighbours — the primacy/recency probes), and swap (swap
   two rules' priorities). A move is **global and consistent** across every prompt containing
   the rule. This is the rule-scale analogue of `SectionReorderMutator` "degrade" (which
   reorders *within* one rule — a distinct operator, `rule_based.py:369-523`). Built now,
   **gated** (D3).
5. Affected prompts for an order move = prompts whose stable-sorted order changed. The cache
   decides hit/miss automatically via the per-prompt signature (§7). An order move that
   changes no prompt's render (e.g. swapping two never-co-occurring rules) is an **order
   identity** → skip (§Edge-cases E1).

---

## 2. Per-rule assumptions that must change

| # | Assumption | Location | Change |
|---|---|---|---|
| A1 | N archives, one per rule, seeded with the original rule | `ea_optimizer.py:166-177` | one archive of chromosomes; seed = original chromosome |
| A2 | Iteration picks a *rule* among rules with an eligible entry | `ea_optimizer.py:221-235` | pick a *chromosome* parent, then pick a *move* |
| A3 | `evaluate_fn(target_rule_id, parent_text, …)` — one rule's text | `ea_optimizer.py:51-54`, `hill_climber.py:1070-1088` | `evaluate_chromosome(genes, order, …)` — pure render+score (§5) |
| A4 | render: target rule replaced, **all others original** | `hill_climber.py:537-577` (esp. 567-575) | render every prompt from the child chromosome (all alleles + order) |
| A5 | `try_add` per rule; depth = that rule's mutations | `pareto_archive.py:274-341` | `try_add` per chromosome; per-gene depth inside the chromosome |
| A6 | `affected_indices` = prompts with the single target rule | `hill_climber.py:915-919` | prompts sharing **any mutated gene** (or reordered pair) |
| A7 | `attempted_children` = mutators tried on this single-rule entry | `pareto_archive.py:57,257-268` | tried `(move)` set per chromosome entry (gene,mutator) / order-op |
| A8 | restart re-seeds (wipes) the single-rule archive | `pareto_archive.py:205-241` | option b: never wipe; origin always available; re-open exploration (§4.6) |
| A9 | random baseline is stateless, re-mutates the original each iter | `ea_optimizer.py:565-643` | persistent chromosome, per-gene overwrite-from-original (§5b) |
| A10 | `archives_snapshot`/`compounding_state` keyed by rule_id | `ea_optimizer.py:477`, `hill_climber.py:1179` | single archive-of-chromosomes snapshot |
| A11 | `mutated_rules/iterNNN/<rule>.md` = one changed rule | `hill_climber.py:1193-1263` | changed-gene file + chromosome manifest (id, alleles, order) |
| A12 | iterations.jsonl is single-`rule_id`-centric | `ea_optimizer.py:432-463` | + chromosome_id, parent_id, mutated_rule_ids, move_type, order_sig |
| A13 | analysis reads per-rule archives | `loaders.py:194-216`, `metrics/search.py:52-71`, `metrics/mutators.py:157-210` | rewrite over the chromosome archive (§8) |
| A14 | `best_rule_id`/`best_rule_text` (single-gene best) | `ea_optimizer.py:75-78,506-520` | `best_chromosome` (whole rule set) |

---

## 3. Data structures (`src/optimizer/chromosome.py`, new)

```python
@dataclass
class GeneState:
    rule_id: str
    text: str                      # current allele
    mutation_path: list[str]       # [] = original; else the chain that produced `text`
    @property
    def depth(self) -> int: return len(self.mutation_path)

@dataclass
class RuleSetChromosome:
    genes: dict[str, GeneState]              # ONLY mutated rules stored; others = originals
    order_priority: dict[str, int]           # ONLY bumped rules stored; default 0 (D13)
    f1: float; f2: float; f3: float
    fitness: AggregatedFitness | None = None
    iteration_added: int = 0
    parent_id: str | None = None
    tried: set = field(default_factory=set)   # moves tried on THIS entry:
                                              #   ("mut", rule_id, mutator_name) | ("order", op, args)

    def allele(self, rid, originals) -> str:
        g = self.genes.get(rid);  return g.text if g else originals[rid]

    def render_order(self, prompt_rule_ids) -> list[str]:
        # stable sort of the prompt's retrieval order by descending priority (D13)
        return sorted(prompt_rule_ids, key=lambda r: -self.order_priority.get(r, 0))

    def mutated_rule_ids(self) -> set[str]: return set(self.genes)

    def prompt_signature(self, pwr, originals) -> str:
        parts = [f"{rid}:{sha256(self.allele(rid, originals))}"
                 for rid in self.render_order(pwr.rule_ids)]
        return sha256("\x1e".join(parts))           # cache key body (D2) — encodes version + order

    def chromosome_id(self, all_rule_ids, originals) -> str:
        # canonical enumeration over all_rule_ids so id is order-of-dict-insertion independent
        body = "|".join(f"{rid}:{self.order_priority.get(rid,0)}:{sha256(self.allele(rid, originals))}"
                        for rid in all_rule_ids)
        return sha256(body)[:16]                     # dedup / lineage / label key

    # ---- moves (produce a child; runner calls these) ----
    def with_gene(self, rid, new_text, mutator_name) -> "RuleSetChromosome": ...  # stacks on current allele (EA)
    def with_gene_from_original(self, rid, new_text, chain) -> "RuleSetChromosome": ...  # overwrite (random, D4)
    def with_reverted(self, rid) -> "RuleSetChromosome": ...                       # drop gene → original (gated)
    def with_priority(self, rid, new_priority) -> "RuleSetChromosome": ...         # order move (gated)
```

Why these choices:
* **Overrides-only `genes`** (unmutated rules come from the existing `rule_originals` map,
  `hill_climber.py:1058-1062`) → small memory, trivial "which are mutated", trivial revert.
* **`prompt_signature`** is the cache key body: ordered `(rule_id, text_hash)` list per
  prompt. Encodes identity + version + order, collision-proof (unlike hashing raw
  concatenation, which is ambiguous because rule bodies can contain `---`). This is exactly
  "mix the rule-text hashings with the order."
* **`chromosome_id`** = content hash over the full ordered gene set → archive dedup key
  (replaces `pareto_archive.py:295-302`), lineage key, stable output label.
* **`with_gene` vs `with_gene_from_original`** encodes the EA/random asymmetry (D4): EA stacks
  on the parent allele (climbs depth); random overwrites from original (jumps).
* **`tried`** keyed by move (gene-mutation or order-op) → per-entry dedup generalizes the old
  per-name `attempted_children`.

`ChromosomeArchive` (reuses `pareto_archive.py` dominance/eviction): `entries` Pareto-set on
(f1,f2,f3); `try_add` rejects dominated or duplicate `chromosome_id`, evicts dominated, caps
at 6 by `f1+f2+f3`; **`origin` chromosome held separately, never evicted, always a selectable
parent** (D8); `sample_parent()` uniform over {entries with an untried move} ∪ {origin}.

Order is global, so it is *not* per-prompt state; the only new per-chromosome structure is the
sparse `order_priority` map (empty by default ⇒ retrieval order, D13).

---

## 4. EA iteration flow (runner mutates → evaluator renders, D5)

```
0. restart check on the single archive                              (§4.6)
1. parent = archive.sample_parent()                                  # RuleSetChromosome (or origin)
2. move = choose_move(parent, rng, weights)                          # {gene-mutate | order | revert}
3. child = build_child(parent, move):
     gene-mutate: new = mutator.mutate(parent.allele(rid)).mutated   # EA stacks on parent allele
                  if new == parent.allele(rid): identity → mark tried, skip  (§4.5)
                  child = parent.with_gene(rid, new, mutator.name)
     order      : child = parent.with_priority(rid, op(...))         # gated; skip if no prompt render changes (E1)
     revert     : child = parent.with_reverted(rid)                  # gated
   (validation / SBERT, if enabled, runs HERE on the changed gene — it's a property of the move)
4. fitness, per_prompt = evaluate_chromosome(child.genes, child.order_priority, iter, phase, should_stop_fn)   (§5a)
5. archive.mark_tried(parent, move)
6. accepted = archive.try_add(child)
7. emit iterations.jsonl record (+ periodic archive snapshot)
```

`choose_move` weights: default = 100% gene-mutate (order & revert gated at 0 for the first
runs, D3/D9). Number of mutators applied in a gene-mutate move = `ea_n_mutations` (default 1,
D12 — configurable so Design B is a flag flip).

### 4.a `evaluate_chromosome(genes, order_priority, iter, phase, should_stop_fn)` — pure render/score seam

Replaces `_evaluate_with_per_prompt_rules` + `_apply_targeted_mutation`. **No mutation, no
validation inside** — it only renders and scores. This is the D5 refactor. `should_stop_fn`
is an explicit parameter (no `getattr(self, "_should_stop_fn")` stash — D15). It is the *only*
eval entry point; both the EA/random runners and `baseline_harness.py` call it (D14).

* For each prompt: `render_order = sorted(pwr.rule_ids, key=-priority)` (D13);
  `assembled = SEPARATOR.join(allele(rid) for rid in render_order)` (empty ⇒ baseline system
  prompt, E3); `sig = prompt_signature(pwr)`; cache key = `(tc_id, sig)`.
  **The old "target rule not in prompt → return original combined text" short-circuit
  (`hill_climber.py:567-568`) is deleted** — every prompt must render *all* its alleles in
  the chromosome's order (else a prompt carrying an *other* mutated gene renders stale text →
  unsafe cache hit; §7.1).
* Cache hit (unchanged signature) → reuse `(code, semgrep_result)`; miss → generate +
  Semgrep. Per-prompt delta vs the fixed iter-0 baseline is unchanged
  (`composite_fitness.evaluate`, `hill_climber.py:841-860`; sign flip under `minimize`
  preserved, `:854-858`).
* Aggregate whole-chromosome with `affected_indices` = prompts sharing ≥1 mutated gene (or a
  changed order pair). `aggregate_fitness` reused unchanged (`fitness.py:177-245`).
* Returns `(AggregatedFitness, per_prompt_results, n_reused, n_rerun)`; the runner owns
  everything else (mutated-rule file save, records).

### 4.6 Restart — option b (what changes vs old)

Old (`pareto_archive.py:205-241`): on stagnation/saturation, **wipe** the rule's front back
to a single original entry — accumulated solutions lost.

New: the **origin chromosome is permanently available** as a parent (held aside from the
Pareto front — it's (0,0,0) so it cannot survive normal dominance admission — and never
evicted), so fresh lineages are always startable *without* wiping. A stagnation trigger (`h`
consecutive non-inserts on the archive) just **re-opens exploration**: clear the `tried` move
sets on current entries so exhausted parents become eligible again. The elite front is never
discarded. Restart events still logged for analysis. (Depth/mutator-exhaustion triggers become
per-(entry, gene); for the MVP, stagnation-only is sufficient.)

---

## 5. The two runners

### 5a. Shared evaluator
Both strategies call the same `evaluate_chromosome` (§4.a). Both **seed from the original
chromosome** (empty overrides, canonical baseline order), evaluated live at iter 0.

### 5b. Random baseline (D4 — corrected)

```
current = original_chromosome                       # genes = {}, order = canonical
for i in range(T):
    rid   = rng.choice(all_rule_ids)
    n     = rng.randint(1, 4)                        # UNCHANGED 1..4 chain
    chain = rng.sample(mutators, n)                  # n distinct mutators
    new   = apply_chain(chain, ORIGINAL[rid])        # ← from ORIGINAL allele, NOT current
    if new == ORIGINAL[rid]: record identity; continue   # chain was a no-op vs ORIGINAL — do not advance/revert (E2)
    current = current.with_gene_from_original(rid, new, [m.name for m in chain])  # overwrite gene
    fitness, per_prompt = evaluate_chromosome(current.genes, current.order, i, phase)
    record; carry `current` forward                  # persisted (breadth accumulates across genes)
best = argmax over visited chromosomes of f1
```

vs current `run_random_baseline` (`ea_optimizer.py:565-772`): today it applies the chain to
`rule_originals[rid]` and **throws the result away each iteration** (stateless, `:640-643`).
New: the result is **written into a persistent chromosome** and carried forward; only the
*picked* gene changes each step, always re-derived from original (per-gene depth ≤ 4, no
cross-iteration stacking on a single gene). No archive, no acceptance, no restart.

### 5c. Coupling / loose-coupling targets (P3 → D14/D15)

The current `_evaluate_with_per_prompt_rules` does six jobs (mutate, render, generate+Semgrep,
aggregate, save files, check stop). The refactor splits them so the seam stays loosely coupled:

* **Mutation + SBERT validation → the runner** (they are properties of the *move*, not the
  render). `evaluate_chromosome` becomes pure render→score.
* **File saving (`_save_mutated_rule`, intermediate JSONL) → the runner/caller**, invoked via
  the already-injected callbacks (`iter_record_fn`, `archive_snapshot_fn`) — the good pattern
  to preserve (`hill_climber.py:1113-1114`).
* **`should_stop_fn` → explicit parameter** of `evaluate_chromosome`, not
  `getattr(self, "_should_stop_fn")` (`hill_climber.py:723,955,1115,1131`). Removes the
  instance-attr stash CLAUDE.md forbids.
* **`reference_codes` → a `set_reference(tc_id, code)` method** on the composite evaluator,
  not the external dict write `self.composite_evaluator.reference_codes[...] =`
  (`hill_climber.py:1012`). `_baseline_fitness_per_case` stays (legit per-run state) but is
  populated by the runner from iter-0 results, not stashed mid-eval.
* **Second consumer — `baseline_harness.py:431`** calls the old seam with `target_rule_id=None`
  to score a fixed rule set (with optional overrides, `:100-107`). Migrate it to
  `evaluate_chromosome(genes=<overrides>, order_priority={})` so there is exactly **one** eval
  path. This is part of the active pipeline, so it must not be left calling a deleted method.

---

## 6. Comparable EA vs random — resolution

**Initialization:** both start from the **original chromosome** (identical), evaluated at
iter 0. No random pre-mutation needed. (My earlier "both 1 mutation/iter" conflated init with
per-iteration logic — corrected.)

**Is identical move logic required for a fair comparison? No.** Fair comparison of guided vs
random search requires identical **search space + fitness + starting point + evaluation
budget T** (Arcuri & Briand, *statistical tests for randomized algorithms in SE* — equal
budget, seeded repetitions, Mann-Whitney U + Vargha-Delaney Â₁₂, which is already the RQ3
stack). Random-search-as-baseline at equal budget is the SBSE convention. So EA=1/iter vs
random=1–4/iter, both budget-T, both from original, both depth-capped 4, is valid.

**But** the meeting's specific confound ("random gets depth from iter 1; EA must climb") is
*not* removed by equal budget — random can reach a depth-4 gene in one sample; EA needs 4
accepted steps. Two defensible designs:

* **Design A** (EA=1, random=1–4): "guided local search vs random sampling at equal budget."
  Valid, but the depth confound remains and must be *explained* in the report.
* **Design B** (EA=1–4, random=1–4): move operator identical, **only selection differs** —
  the clean controlled experiment that eliminates the confound and directly answers "does the
  archive/guidance help." Strongest claim.

**Recommendation (D12):** default EA to 1 mutation/iter but make the count a **config knob
(`ea_n_mutations`)**. First validation run = Design A (EA=1); headline comparison = flip to
Design B (EA=1–4) with no code change. This is the "implement once" path. **Confirm:** knob
(recommended) vs hard EA=1.

Per-gene depth cap = 4 for both (locked). Both max a single gene at depth 4 (EA climbs there;
random jumps there) — consistent.

---

## 7. Cache-safety design

1. **Always render from the chromosome** (all alleles, in chromosome order). Deleting the
   original-fallback path (`hill_climber.py:567-568`) is mandatory — it is the one path that
   could hash stale (original) text for a prompt that carries another mutated gene → unsafe
   hit. **This is the only scientifically-unsafe reuse to remove.**
2. **Key = `(tc_id, sha256(prompt_signature))`** where the signature is the ordered
   `(rule_id, text_hash)` list (§3, D2). Encodes rule identity + version + order; collision-
   proof; order-mutation-safe (reorder ⇒ different signature ⇒ correct miss) with zero
   special-casing.
3. Two chromosomes that yield the same per-prompt signature *should* share the entry (same
   model input under temperature 0 ⇒ same output) — a correct hit, not a bug.
4. **Baseline invariance**: reference code + baseline score captured once at iter 0 for the
   original set (`hill_climber.py:1007-1017`); never recomputed from a mutated chromosome.
5. **Logging**: per-iteration `n_prompts_reused` (cache hits) vs `n_prompts_rerun` (misses),
   plus per-prompt `eval_cache_hit` (already recorded, `hill_climber.py:1314`).

Cache stays per-run in-memory (`hill_climber.py:352`); more distinct chromosomes ⇒ more keys,
bounded by (#prompts × #distinct signatures). Fine at ≤~170 prompts; no disk cache.

---

## 8. Schema 3 (clean break, D10)

Bump `SCHEMA_VERSION` 2 → **3** (`run_with_rules_map.py:120`). No schema-2 compatibility
shims. The analysis toolkit gets a schema-3 reader; the schema-2 reader is **frozen** (kept
only to regenerate old figures if ever needed, not maintained). Old `experiments/final/` runs
are a separate cohort, not pooled.

| Artifact | Schema-3 shape |
|---|---|
| `run_config.json` | `schema_version: 3`; add `ea_n_mutations`, `max_mutations_per_iter` (random), `order_mutation_enabled`, `reverse_enabled`, `baseline_order` (the canonical order + how derived) |
| `iterations.jsonl` | `iter, strategy, chromosome_id, parent_chromosome_id, move` `{type: mutate|order|revert, rule_id?, mutator(s)?, order_op?}`, `mutated_rule_ids[]`, `gene_depth`, `f1,f2,f3`, `accepted`, `n_prompts_rerun`, `n_prompts_reused`, `selection_meta{parent_f1,archive_size,...}` |
| `archive_snapshots/iterNNNN.json` | `{config, origin_f1_f2_f3, chromosomes:[{chromosome_id, f1,f2,f3, mutated_rule_ids, order, genes:{rid:{mutation_path, depth, text_ref}}, iteration_added, parent_id}]}` — one list, not per-rule |
| `mutated_rules/iterNNN/` | changed gene's `<rule>.md` + `meta.json{chromosome_id, mutated_rule_ids, per-gene mutation_path, order}` |
| `intermediate/{iter}.jsonl` | per-prompt: add `chromosome_id`, `rules_used.mutated_rule_ids`, `render_order`, `prompt_affected` (shares ≥1 mutated gene / changed order), `eval_cache_hit` |
| `hillclimb_summary_*.json` | keep `pool_arm_stats.mutator_stats`; add `best_chromosome{id, mutated_rule_ids, order, f1,f2,f3}` |

Analysis (`scripts/analyze/`), schema-3 path:
* **RQ3 / search** (`metrics/search.py::efficiency_row`, `loaders.best_f1/convergence/
  iter_to_first_best`): read `iterations.jsonl.f1` — **logic unchanged** (f1 is now the whole
  chromosome — exactly what RQ3 compares). Mann-Whitney U + Vargha-Delaney Â₁₂ EA-vs-random on
  `best_f1` stays valid. `final_front_rows` (`metrics/search.py:52-71`) reads `archives[rule]`
  → **rewrite** over `chromosomes[]`.
* **RQ2 / mutators** (`metrics/mutators.py`): `lineage_steps` (`:67-90`) uses
  `selection_meta.parent_f1` + `mutation_chain[-1]`; per-step delta becomes the **marginal
  whole-chromosome effect of a mutator applied in the parent's context** (more meaningful) —
  keep + relabel. `combination_counts`, `per_rule_best_path/safest_path` (`:157-210`) read
  `archives[rule]` → **rewrite** over `chromosomes[]` (per-rule best path = best chromosome
  that mutates rule R, from `genes`).
* **loaders `per_rule_best/worst`** (`loaders.py:194-216`) group iterations by `rule_id`:
  semantics shift to "best iteration whose *changed gene* was R"; the `per_rule_fitness.png`
  caption (`analyze_run.py:150-178`) must be rewritten (no longer a rule's isolated effect).
* **Repair/outcome** (`metrics/outcomes.py`, `metrics/repair.py`): to report the best
  chromosome's per-prompt findings, pick the best-f1 iteration and read its
  `intermediate/{iter}.jsonl`. Add the meeting's **counts over initially-vulnerable tasks**
  (denominator = baseline-vulnerable tasks, `loaders.baseline_findings:277-283`), excluding
  always-safe cases.
* **Naming (D11):** fields stay `f1/f2/f3`; report/plot layer prints "fitness" only when f1 is
  shown alone.

---

## 9. Minimal first implementation (by Mon 2026-07-06)

**MUST DO NOW:**
1. `src/optimizer/chromosome.py`: `GeneState`, `RuleSetChromosome` (incl. `order`,
   `prompt_signature`, all four move builders), `ChromosomeArchive` (cap 6, origin-aside,
   dedup by `chromosome_id`).
2. Rewrite `run_ea` to the §4 chromosome loop with `choose_move` (gene-mutate default;
   order/revert wired but weight 0) and `ea_n_mutations` knob (default 1, D12).
3. Rewrite `run_random_baseline` to §5b (1–4 from original, per-gene overwrite, carried
   forward).
4. **`evaluate_chromosome` refactor (D5/D14/D15)**: strip mutation+validation+file-saving out
   of `_evaluate_with_per_prompt_rules`; input = `(genes, order_priority, iter, phase,
   should_stop_fn)`; render via `prompt_signature`; **delete the original-fallback path**
   (`hill_climber.py:567-568`); `affected_indices` = mutated-gene ∪ changed-order prompts.
   Move mutation + SBERT + file writes to the runner; pass `should_stop_fn` explicitly;
   `reference_codes` via `set_reference()`. **Migrate `baseline_harness.py:431`** to the new
   seam (D14) — it is the second consumer and part of the active pipeline.
5. Both seed from the **original chromosome** (canonical baseline order, D13); per-gene depth
   cap 4 both.
6. **Signature cache (§7)** — swap the key from concatenation-hash to `prompt_signature`.
7. Schema 3 writes (§8) sufficient to load + compare: chromosome fields in `iterations.jsonl`,
   single-archive snapshot, `mutated_rule_ids`/`render_order` in `intermediate/`.
8. Minimum analysis repair: fix hard breaks (`final_front_rows`, `combination_counts`,
   `per_rule_best_path/safest_path`) so `analyze_search` (RQ3) + one sanity table run.
9. Tests (§10).

**BUILT NOW BUT GATED (structure in, activation off):**
* Order mutator (`RuleOrderMutator`) — weight 0 by default (D3).
* Reverse move (`with_reverted`) — EA-only, weight 0 by default (D9).

**DEFERRED:**
* Probabilistic mutations-per-iter schedule (meeting `alpha≈1.2/1.5`) — the knob exists (D12);
  only the schedule is deferred.
* Rule-selection bias (mutate impactful rules more often).
* Full analysis re-theming (per-rule figure relabels, repair denominators) beyond the minimum.

---

## 10. Test plan

Deterministic fakes (mirror `test_eval_cache.py` `_FakeLLMBackend`/`_semgrep_stub`,
`test_pareto_archive.py` structure):

* **Chromosome mechanics** (`test_chromosome.py`): `with_gene` stacks + extends
  `mutation_path`; `with_gene_from_original` overwrites (depth = chain len); `with_reverted`
  drops the gene; `with_order` permutes; `prompt_signature` stable under an unrelated gene's
  change, changes under an allele change **or** an order change of a contained pair.
* **Archive dominance** (`test_chromosome_archive.py`, mirrors
  `test_pareto_archive.py:90-341`): non-dominated survive; dominated child rejected; duplicate
  `chromosome_id` rejected; cap-6 eviction by `f1+f2+f3`; origin always sampleable, never
  evicted; restart re-opens `tried` without wiping the front.
* **Interaction regression** (the whole point): scripted eval where R2′ alone = +0, R7′ alone
  = +0, R2′+R7′ = +1 → the archive can reach the +1 chromosome (impossible under per-rule).
* **Cache reuse across a one-gene move**: 3-prompt fixture, rule R in prompt 0 only, parent
  already mutated rule Q (prompt 2). Assert prompts 1 & 2 hit, prompt 0 reruns, whole-
  chromosome f1 reflects both Q and R.
* **Order-move cache** (gated-on for the test): swapping two rules reruns only prompts
  containing both; prompts with ≤1 hit; an order move that changes no prompt's render is
  detected as an order-identity and skipped (E1).
* **Cache PARITY (your ask)** — the correctness proof that cache == rerun:
  * *unit*: fake deterministic backend, run the same seeded EA twice, once
    `enable_eval_cache=True` and once `False`; assert **identical** `f1/f2/f3` per iteration
    **and** identical per-prompt scores. (Mutation lives in the runner, so both runs issue the
    same `mutate()` sequence ⇒ identical chromosomes ⇒ cache must only *reuse*, never alter.)
  * *paired smoke*: tiny real run, same seed, `--no-eval-cache` vs default; diff
    `iterations.jsonl` (f1/f2/f3) and `intermediate/*.jsonl` (per-prompt `raw_count`,
    `composite_score`, `code_divergence`) → must match exactly under temperature 0. A mismatch
    means a signature bug (stale hit) or a hidden non-determinism.
* **Random walk (D4)**: gene re-pick re-derives from original (not current); other genes
  persist; identity iters don't advance; no archive object.
* **Init parity**: both produce the depth-0 original chromosome as their iter-0 reference.
* **Fitness-sign guard**: under `minimize`, a chromosome that *reduces* findings → **positive**
  f1; under `maximize`, an increase → positive f1 (targets the meeting's "sign may be
  inverted" risk).
* **Determinism**: same seed ⇒ identical `chromosome_id` lineage.
* **Smoke** (`--dry-run`, 2 rules, 3 prompts, 5 iters, EA + random): schema-3 artifacts write;
  `analyze_search` loads without error.

---

## E. Edge-case catalog (must be handled in the implementation)

| # | Edge case | Handling |
|---|---|---|
| E1 | **Order no-op**: swapping two rules that never co-occur (common — 22 rules, avg 2.89/prompt) changes `chromosome_id` but renders identically everywhere | detect "no prompt signature changed" → treat as identity, mark tried, **skip eval** (else the archive fills with render-equivalent duplicates) |
| E2 | **Random identity-from-original**: a 1–4 chain that yields the original text | identity is `new == ORIGINAL[rid]` (not `== current allele`), else it silently reverts an already-mutated gene; skip, don't advance |
| E3 | **0-rule prompts** (present in the map, size min = 0) | empty `render_order` ⇒ `assembled = ""` ⇒ `_build_system_prompt(None)` baseline path; never affected by any move; always cache-hit after baseline |
| E4 | **Single-rule prompts** (14) | order moves can never affect them (need ≥2 rules); gene moves do |
| E5 | **Invariant**: every `pwr.rule_id` must be renderable | assert `all_rule_ids ⊇ ⋃ pwr.rule_ids`; assert no duplicate ids within a prompt (map has 0 dupes today — keep the assert) |
| E6 | **`sample_parent` must never return None** | the always-available origin guarantees ≥1 parent; the old defensive "no eligible rules" break (`ea_optimizer.py:226-230`) becomes an assert |
| E7 | **Baseline must use the render seam** | iter-0 baseline = `evaluate_chromosome(origin)`; it captures reference codes + baseline scores under the identical render and primes the cache with origin signatures that later-unaffected prompts hit (E7 ⇒ the whole incremental cache story) |
| E8 | **Whole-chromosome `affected_indices` grows** as the random walk accumulates mutated genes (up to all prompts) | correct denominator for f2/f3; not a bug — document it |
| E9 | **Duplicate `chromosome_id`** (a stochastic mutator reproduces an existing entry, or a move round-trips) | `try_add` rejects on `chromosome_id` dedup (replaces the text-hash check `pareto_archive.py:295-302`) |
| E10 | **Stochastic mutators advance their own RNG** — re-applying the same (gene,mutator) can yield new text | keep the "one shot per (parent,gene,mutator)" dedup via `tried`; restart (§4.6) clears `tried` to allow a fresh draw; the shared run RNG order must stay fixed for determinism |
| E11 | **Depth cap interaction** | a gene at depth 4 is excluded from further gene-mutate moves on that parent (EA); random's fresh 1–4 chain is inherently ≤ 4 |
| E12 | **`minimize` sign** | a worsening chromosome (negative f1) is dominated by origin on f1 but can still enter the front via f2/f3 (Pareto trade-off) — intended; the fitness-sign guard test (§10) protects against an inverted delta |

## 11. Experiment sanity checks

**First (correctness gate): the cache-parity paired run** — same seed, `--no-eval-cache` vs
default, tiny `--n-cases`; diff `iterations.jsonl` + `intermediate/` scores → must be
identical. This validates the signature cache + schema before any interpretation of results.

Then: one EA + one random small run (`--dry-run` or tiny `--n-cases`), same seed.

**Logically correct if:** EA `best_f1` ≥ random on average (guidance helps) and reaches a
given f1 in fewer iterations; `best_f1 ≥ 0` under `minimize`, monotone best-so-far
(`loaders.convergence`); best chromosome has **>1 mutated gene** on some seeds with ≥1 case
fixed only by co-mutation (the interaction the portfolio check hinted at); cache reuse high
(`n_prompts_reused ≫ n_prompts_rerun`).

**Fitness sign/objective still wrong if:** random ≥ EA even after the fix (meeting's explicit
warning → inspect `objective_direction` plumbing `hill_climber.py:854-858` and the f1 maximise
direction); f1 up while `raw_count` up under `minimize` (delta sign inverted); archive fills
with high-f1 chromosomes whose per-prompt `raw_count` did not drop (objective decoupled from
outcome).

---

## 12. Report / documentation updates

* `ARCHITECTURE.md`, `IMPLEMENTATION.md`, `DEPENDENCIES_AND_FLOW.md`,
  `scripts/analyze/README.md`: chromosome-archive language; new snapshot schema; **rule order
  as a searched dimension**.
* Thesis: the meeting's **algorithm figure** (full rule set as chromosome → gene/order choice
  → mutation → whole-set evaluation → archive update); explicit definitions of chromosome /
  gene / order / archive entry / mutation / random baseline; the "why global/generalizable"
  paragraph; cite the supervisor's 1+1/archive paper. Note schema-3 supersedes schema-2 runs.
* Reporting change (meeting): vulnerability reductions as **counts** and **fixed-fraction over
  initially-vulnerable tasks**, excluding always-safe cases.

---

## 13. Remaining open items

All code-shaping decisions are settled (§0 ledger, D1–D15). The only outstanding item is a
run-time choice, not a blocker for implementation:

1. **First-run matrix:** which seeds/languages for the validation burst — mirror the schema-2
   `ea/rand × py/ja × seeds 42–46` layout, or a smaller smoke first? (Decide when the code +
   smoke tests are green; does not affect the build.)

---

### Appendix — key file references

* EA loop / per-rule archives: `src/optimizer/ea_optimizer.py:106-503`; per-rule archive
  `src/optimizer/pareto_archive.py` (dominance `:66-78`, seed/restart `:188-241`, try_add
  `:274-341`).
* Isolated render (core issue): `src/optimizer/hill_climber.py:537-577` (fallback `:567-568`),
  eval `:579-933`, cache key `:769-772`, baseline reset `:1007-1017`, seam `:1070-1088`,
  snapshot `:417-476`.
* Fitness: `src/evaluation/fitness.py:177-245` (affected scoping `:217-229`); delta/sign
  `src/evaluation/composite_fitness.py:137`, `hill_climber.py:854-858`.
* Prompt→rules + order: `src/evaluation/rule_mapping.py:243-319` (order = `rule_ids`,
  `:307-309`); entrypoint `scripts/experiments/run_with_rules_map.py:205-228`, schema `:120`.
* Within-rule reorder (distinct from prompt order): `src/mutation/rule_based.py:369-523`.
* Random baseline (stateless today): `src/optimizer/ea_optimizer.py:565-772`.
* Analysis breakage: `scripts/analyze/loaders.py:194-216`, `metrics/search.py:52-71`,
  `metrics/mutators.py:157-210`, `records.py:100-125,154-162`.
```
