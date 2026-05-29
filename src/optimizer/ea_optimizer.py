"""
(1+1) EA + Pareto archive optimizer and pure-random-walk baseline.

Both runners share the same evaluation seam — ``evaluate_fn`` — which is a
closure provided by :class:`HillClimber`. They bypass :class:`MutatorPool`
entirely because their selection logic (parent eligibility + per-entry
mutator dedup) doesn't fit the pool's blind ``select()`` API.

Top-level entry points
----------------------
* :func:`run_ea`             — (1+1) EA over per-rule :class:`ParetoArchive`
* :func:`run_random_baseline` — stateless per-iteration multi-mutation sampler
"""

from __future__ import annotations

import random
import time
from dataclasses import dataclass, field
from typing import Any, Callable, TYPE_CHECKING

from ..evaluation.fitness import AggregatedFitness
from ..mutation import Mutator
from ..mutation.base import MutationResult
from .pareto_archive import ArchiveEntry, ParetoArchive

if TYPE_CHECKING:
    from .hill_climber import IterationResult, PerRuleResult


# evaluate_fn signature contract — mirrors the eval seam from
# HillClimber._evaluate_with_per_prompt_rules so callers can plug it in directly.
# mutation_chain is the full ordered list of mutator names that produced the
# candidate (EA: parent lineage + this mutator; random: the sampled chain). It is
# threaded through so mutated_rules/*/meta.json can record it.
EvaluateFn = Callable[
    [str, str, Mutator, int, str, "list[str]"],   # (target_rule_id, parent_text, mutator, iteration, phase, mutation_chain)
    tuple[AggregatedFitness, list[Any], list[str], dict[str, Any], "str | None"],
]


# ============================================================================
# Result objects
# ============================================================================

@dataclass
class EARunResult:
    """What the EA / random-baseline runner returns to HillClimber."""

    iterations: list["IterationResult"]
    per_rule_results: list["PerRuleResult"]
    archives_snapshot: dict[str, dict[str, Any]] = field(default_factory=dict)
    """Per-rule archive state, keyed by rule_id (EA only). Stored on
    HillClimbResult.compounding_state. Empty for random_baseline (no archive)."""

    rate_limit_hit: bool = False
    """True iff a rate-limit exception aborted the loop early."""

    # For HillClimbResult compatibility
    best_rule_id: str | None = None
    best_rule_text: str = ""
    best_fitness: AggregatedFitness | None = None
    """Highest-f1 archive entry across all rules (ties broken by f1+f2+f3)."""

    per_rule_best_delta: dict[str, float] = field(default_factory=dict)
    per_rule_best_code_divergence: dict[str, float] = field(default_factory=dict)

    mutator_stats: dict[str, dict[str, int]] = field(default_factory=dict)
    """Per-mutator counters. Shape differs by strategy (reporting plan RQ2):

    EA (last-mutator credit):
      - ``attempts``        : times this mutator was applied to a parent.
      - ``archive_adds``    : true archive insertions (passed the Pareto check).
      - ``archive_adds_f1`` : subset where the candidate's ``total_semgrep_delta``
                              strictly exceeded its parent's f1.

    random_baseline (whole-chain credit):
      - ``applications``               : times this mutator appeared in a chain.
      - ``applications_f1_advancing``  : of those, how many were in a chain whose
                                         final candidate had f1 > baseline."""

    restart_reason_counts: dict[str, int] = field(default_factory=dict)
    """Total restart events bucketed by reason across all rules (EA only;
    empty for random_baseline, which has no restarts)."""


# ============================================================================
# (1+1) EA over per-rule Pareto archives
# ============================================================================

def run_ea(
    *,
    prompts_with_rules: list[Any],
    all_rule_ids: list[str],
    rule_originals: dict[str, str],
    baseline_fitness: AggregatedFitness,
    mutators: list[Mutator],
    evaluate_fn: EvaluateFn,
    iteration_result_factory: Callable[..., "IterationResult"],
    per_rule_result_factory: Callable[..., "PerRuleResult"],
    max_iterations: int,
    archive_cap: int,
    restart_h: int,
    max_depth: int,
    seed: int | None,
    log: Callable[[str], None],
    iter_record_fn: Callable[[dict], None] | None = None,
    archive_snapshot_fn: Callable[[int, dict[str, dict]], None] | None = None,
    snapshot_every: int = 20,
) -> EARunResult:
    """Run the (1+1) EA + Pareto archive optimization.

    Each iteration:
      1. Pick a rule uniformly at random from rules whose archive still has
         at least one parent-eligible entry. If none → all rules done, break.
      2. Sample a parent uniformly from that rule's eligible archive entries.
      3. Sample a mutator uniformly from mutators not yet tried on the parent.
      4. Apply the mutator, evaluate, mark the (parent, mutator) pair tried.
      5. Offer the offspring to the archive.
      6. Check restart triggers (stagnation / depth / mutator-exhausted); reset
         the rule's archive if needed.

    All RNG draws use a single :class:`random.Random` seeded from ``seed`` so
    that a fixed seed reproduces the full run.

    bd-3wa Phase 1 (augment-first): ``iter_record_fn`` is invoked once per EA
    loop iteration with a strategy-agnostic record (see hill_climber._append_
    iteration_record docstring). ``archive_snapshot_fn`` is invoked every
    ``snapshot_every`` iterations with the current per-rule archive snapshot
    dict (inline rule_text per §9.1 Q3). Both are no-ops when None — keeps the
    runner usable without an output directory.
    """
    import time as _time
    from datetime import datetime as _dt
    rng = random.Random(seed)
    n_mutators = len(mutators)
    mutator_names = [m.name for m in mutators]
    mutator_by_name: dict[str, Mutator] = {m.name: m for m in mutators}

    # Build per-rule archives. All share the global baseline_fitness — the
    # baseline (f1, f2, f3) is (0, 0, 0) by composite-score definition, so any
    # non-trivial candidate dominates the seed entry on first insert.
    archives: dict[str, ParetoArchive] = {
        rid: ParetoArchive(
            original_text=rule_originals[rid],
            baseline_fitness=baseline_fitness,
            cap=archive_cap,
            restart_h=restart_h,
            max_depth=max_depth,
            n_mutators=n_mutators,
            rng=rng,
        )
        for rid in all_rule_ids
    }

    iterations: list["IterationResult"] = []
    per_rule_results: list["PerRuleResult"] = []
    per_rule_best_delta: dict[str, float] = {rid: 0.0 for rid in all_rule_ids}
    per_rule_best_div: dict[str, float] = {rid: 0.0 for rid in all_rule_ids}
    rate_limit_hit = False

    # Mutator effectiveness counters — for end-of-run summary + future bandit ablation.
    # archive_adds_f1 is the subset of archive_adds where f1 strictly improved over
    # the parent's f1. Separates "moved the primary metric" from "advanced the
    # f2/f3 Pareto trade-off only" — see ANALYSIS_2026-05-21.md F6.
    mutator_stats: dict[str, dict[str, int]] = {
        m.name: {"attempts": 0, "archive_adds": 0, "archive_adds_f1": 0} for m in mutators
    }
    # Restart-reason counters across all rules
    restart_reason_counts: dict[str, int] = {
        "stagnation": 0, "depth_saturated": 0,
        "mutator_exhausted": 0, "fully_exhausted": 0,
    }

    for i in range(max_iterations):
        # Track per-iter selection_meta state for the iterations.jsonl record.
        restarts_this_iter: list[dict[str, Any]] = []

        # ---- 0. Restart any rule whose triggers fired since last iteration
        for rid, arc in archives.items():
            should, reason = arc.should_restart()
            if should:
                log(f"   ↻ rule={rid.replace('codeguard-', 'cg-')} restart: {reason} "
                    f"(archive_size={len(arc)})")
                arc.restart(current_iteration=i + 1, reason=reason)
                if reason in restart_reason_counts:
                    restart_reason_counts[reason] += 1
                restarts_this_iter.append({"rule_id": rid, "reason": reason})

        # ---- 1. Pick rule uniformly from those with at least one eligible entry
        eligible_rids = [
            rid for rid, arc in archives.items()
            if arc.sample_parent() is not None
        ]
        if not eligible_rids:
            # Should never happen — restart above guarantees at least one entry
            # is always seeded. Defensive break.
            log("\n⏹️  No EA-eligible rules remaining — stopping early")
            break

        rule_id = rng.choice(eligible_rids)
        archive = archives[rule_id]

        parent = archive.sample_parent()
        assert parent is not None, "sample_parent returned None after eligibility filter"

        # ---- 2. Pick mutator uniformly from those not yet tried on this parent
        available = archive.available_mutators(parent, mutator_names)
        if not available:
            # Should be caught by restart trigger; defensive guard
            archive.restart(current_iteration=i + 1, reason="mutator_exhausted")
            continue
        mutator_name = rng.choice(available)
        mutator = mutator_by_name[mutator_name]

        num_affected = sum(1 for pwr in prompts_with_rules if rule_id in pwr.rule_ids)
        log(f"\n🧬 Iteration {i+1}/{max_iterations} "
            f"— rule={rule_id.replace('codeguard-', 'cg-')} "
            f"depth={parent.depth} mutator={mutator_name} "
            f"archive_size={len(archive)} {num_affected}/{len(prompts_with_rules)} prompts")

        # ---- 3. Evaluate via the supplied closure (wraps HillClimber's pipeline)
        # mutation_chain = parent lineage + this iteration's mutator (last element).
        mutation_chain = parent.mutation_path + [mutator_name]
        try:
            (candidate_fitness, candidate_results, mutation_changes,
             val_metadata, iter_mutated_text) = evaluate_fn(
                rule_id, parent.rule_text, mutator, i + 1,
                f"ea_iter{i+1:04d}",
                mutation_chain,
            )
        except Exception as e:
            if "rate_limit" in str(e).lower() or "429" in str(e) or "413" in str(e):
                log(f"\n⚠️  Rate limit hit at EA iteration {i+1}: {e}")
                rate_limit_hit = True
                break
            raise

        if iter_mutated_text is None:
            # Validation rejected the mutation (or no rule text produced) —
            # still mark the (parent, mutator) pair as tried so we don't retry
            # the same dead-end forever, and skip the archive insert.
            archive.mark_tried(parent, mutator_name)
            log(f"   ⚠️ No mutated text produced; marked {mutator_name} tried for parent")
            if iter_record_fn is not None:
                iter_record_fn({
                    "iter": i + 1,
                    "timestamp": _dt.utcnow().isoformat() + "Z",
                    "strategy": "ea",
                    "rule_id": rule_id,
                    "mutation_chain": mutation_chain,
                    "chain_length": len(mutation_chain),
                    "mutation_identity": None,
                    "validation_passed": False,
                    "f1": None, "f2": None, "f3": None,
                    "f1_advance": False,
                    "accepted": False,
                    "num_prompts_affected": num_affected,
                    "llm_calls_total": None,
                    "input_tokens_total": None,
                    "output_tokens_total": None,
                    "validation_metadata": val_metadata or {},
                    "selection_meta": {
                        "parent_iter": parent.iteration_added,
                        "parent_f1": parent.f1,
                        "parent_depth": parent.depth,
                        "archive_size_before": len(archive),
                        "archive_size_after": len(archive),
                        "attempts_since_insert": archive._attempts_since_insert,
                        "n_eligible_rules": len(eligible_rids),
                        "restarts_this_iter": restarts_this_iter,
                    },
                })
            continue

        # ---- 4. Mark tried (regardless of archive outcome) ---------------
        archive.mark_tried(parent, mutator_name)
        mutator_stats[mutator_name]["attempts"] += 1

        # bd-3wa: capture mutation_identity flag BEFORE archive insertion
        # (post-6ac526b try_add rejects identity, but the event is still
        # observable for analysis).
        mutation_identity = (iter_mutated_text == parent.rule_text)
        archive_size_before = len(archive)

        # ---- 5. Offer offspring to the archive ---------------------------
        accepted = archive.try_add(
            candidate_text=iter_mutated_text,
            candidate_fitness=candidate_fitness,
            iteration=i + 1,
            parent=parent,
            mutator_name=mutator_name,
        )
        if accepted:
            mutator_stats[mutator_name]["archive_adds"] += 1
            if candidate_fitness.total_semgrep_delta > parent.f1:
                mutator_stats[mutator_name]["archive_adds_f1"] += 1
            log(f"   ✅ archive add: f1={candidate_fitness.total_semgrep_delta:+.2f} "
                f"f2={candidate_fitness.proportion_divergent:.3f} "
                f"f3={candidate_fitness.conditional_mean_divergence:.3f} "
                f"(archive_size={len(archive)})")
        else:
            _tol = 1e-9
            _cf1 = candidate_fitness.total_semgrep_delta
            _cf2 = candidate_fitness.proportion_divergent
            _cf3 = candidate_fitness.conditional_mean_divergence
            _dom = next(
                (e for e in archive.entries
                 if (e.f1 >= _cf1 - _tol and e.f2 >= _cf2 - _tol and e.f3 >= _cf3 - _tol
                     and (e.f1 > _cf1 + _tol or e.f2 > _cf2 + _tol or e.f3 > _cf3 + _tol))),
                None,
            )
            if _dom is not None:
                log(f"   ✗ rejected: cand(f1={_cf1:+.2f}, f2={_cf2:.3f}, f3={_cf3:.3f})"
                    f" — dominated by entry[iter={_dom.iteration_added}, depth={_dom.depth}]"
                    f" (f1={_dom.f1:+.2f}, f2={_dom.f2:.3f}, f3={_dom.f3:.3f})"
                    f" [archive_size={len(archive)}/cap={archive.cap},"
                    f" stagnation={archive._attempts_since_insert}/{archive.restart_h}]")
            else:
                log(f"   ✗ rejected (identity): cand(f1={_cf1:+.2f}, f2={_cf2:.3f}, f3={_cf3:.3f})"
                    f" [archive_size={len(archive)}/cap={archive.cap},"
                    f" stagnation={archive._attempts_since_insert}/{archive.restart_h}]")

        # ---- 6. Track best-per-rule for HillClimbResult compatibility
        fitness_delta = candidate_fitness.total_semgrep_delta
        if fitness_delta > per_rule_best_delta[rule_id]:
            per_rule_best_delta[rule_id] = fitness_delta
        if candidate_fitness.mean_code_divergence > per_rule_best_div[rule_id]:
            per_rule_best_div[rule_id] = candidate_fitness.mean_code_divergence

        # ---- 7. Build iteration + per-rule result entries
        iterations.append(iteration_result_factory(
            iteration=i,
            rule_text=f"[ea: {rule_id}@iter{i+1}]",
            aggregated_fitness=candidate_fitness,
            individual_results=candidate_results,
            is_improvement=accepted,
            mutation_changes=mutation_changes,
            validation_metadata=val_metadata,
        ))
        per_rule_results.append(per_rule_result_factory(
            rule_id=rule_id,
            iteration=i,
            fitness_delta=fitness_delta,
            aggregated_fitness=candidate_fitness,
            mutation_changes=mutation_changes,
            is_improvement=accepted,
            num_prompts_affected=num_affected,
        ))

        # ---- 8. Periodic archive snapshot (every 20 iterations) -------------
        if (i + 1) % snapshot_every == 0:
            _log_archive_snapshot(log=log, archives=archives, iteration=i + 1)
            if archive_snapshot_fn is not None:
                archive_snapshot_fn(
                    i + 1,
                    {rid: arc.snapshot() for rid, arc in archives.items()},
                )

        # ---- 9. bd-3wa: emit per-iter record into iterations.jsonl -----------
        if iter_record_fn is not None:
            iter_record_fn({
                "iter": i + 1,
                "timestamp": _dt.utcnow().isoformat() + "Z",
                "strategy": "ea",
                "rule_id": rule_id,
                "mutation_chain": mutation_chain,
                "chain_length": len(mutation_chain),
                "mutation_identity": mutation_identity,
                "validation_passed": True,
                "f1": candidate_fitness.total_semgrep_delta,
                "f2": candidate_fitness.proportion_divergent,
                "f3": candidate_fitness.conditional_mean_divergence,
                "f1_advance": accepted and (candidate_fitness.total_semgrep_delta > parent.f1),
                "accepted": accepted,
                "num_prompts_affected": num_affected,
                "llm_calls_total": None,    # populated by hill_climber from its counters if needed
                "input_tokens_total": None,
                "output_tokens_total": None,
                "validation_metadata": val_metadata or {},
                "selection_meta": {
                    "parent_iter": parent.iteration_added,
                    "parent_f1": parent.f1,
                    "parent_depth": parent.depth,
                    "archive_size_before": archive_size_before,
                    "archive_size_after": len(archive),
                    "attempts_since_insert": archive._attempts_since_insert,
                    "n_eligible_rules": len(eligible_rids),
                    "restarts_this_iter": restarts_this_iter,
                },
            })

    # ---- Final archive snapshot (unconditional — covers the last iterations
    # when max_iterations is not a multiple of snapshot_every) ----------------
    if archive_snapshot_fn is not None and max_iterations > 0:
        archive_snapshot_fn(
            max_iterations,
            {rid: arc.snapshot() for rid, arc in archives.items()},
        )

    # ---- Final: collect archive snapshots + global best ---------------------
    archives_snapshot = {rid: arc.snapshot() for rid, arc in archives.items()}
    best_rule_id, best_entry = _global_best_entry(archives)

    _log_ea_summary(
        log=log,
        all_rule_ids=all_rule_ids,
        archives=archives,
        per_rule_results=per_rule_results,
        mutator_stats=mutator_stats,
        restart_reason_counts=restart_reason_counts,
        best_rule_id=best_rule_id,
        best_entry=best_entry,
    )

    return EARunResult(
        iterations=iterations,
        per_rule_results=per_rule_results,
        archives_snapshot=archives_snapshot,
        rate_limit_hit=rate_limit_hit,
        best_rule_id=best_rule_id,
        best_rule_text=best_entry.rule_text if best_entry else "",
        best_fitness=best_entry.fitness if best_entry else None,
        per_rule_best_delta=per_rule_best_delta,
        per_rule_best_code_divergence=per_rule_best_div,
        mutator_stats=mutator_stats,
        restart_reason_counts=restart_reason_counts,
    )


def _global_best_entry(
    archives: dict[str, ParetoArchive],
) -> tuple[str | None, ArchiveEntry | None]:
    """Pick the archive entry with highest f1 across all rules; ties → highest sum."""
    best_rid: str | None = None
    best_entry: ArchiveEntry | None = None
    for rid, arc in archives.items():
        for entry in arc.entries:
            if best_entry is None or (
                entry.f1 > best_entry.f1
                or (entry.f1 == best_entry.f1 and entry.score_sum() > best_entry.score_sum())
            ):
                best_rid = rid
                best_entry = entry
    return best_rid, best_entry


# ============================================================================
# Stateless random baseline (per-iteration multi-mutation sampler)
# ============================================================================

class _ChainMutator(Mutator):
    """Applies a fixed ordered chain of mutators as one mutation.

    ``mutate(text)`` runs each mutator in turn, feeding the previous output
    forward (cumulative). Identity outcomes still count toward the chain. The
    chain is always applied in full. Exposes ``mutator_names`` so the runner can
    record which mutators ran.
    """

    def __init__(self, mutators: list[Mutator]):
        super().__init__(seed=None)
        self._mutators = list(mutators)
        self._name = "+".join(m.name for m in self._mutators)

    @property
    def name(self) -> str:
        return self._name

    @property
    def mutator_names(self) -> list[str]:
        return [m.name for m in self._mutators]

    def mutate(self, text: str) -> MutationResult:
        original = text
        current = text
        changes: list[str] = []
        for m in self._mutators:
            res = m.mutate(current)
            current = res.mutated
            changes.extend(res.changes)
        return MutationResult(
            original=original,
            mutated=current,
            mutation_type=self._name,
            changes=changes,
        )


def run_random_baseline(
    *,
    prompts_with_rules: list[Any],
    all_rule_ids: list[str],
    rule_originals: dict[str, str],
    mutators: list[Mutator],
    evaluate_fn: EvaluateFn,
    iteration_result_factory: Callable[..., "IterationResult"],
    per_rule_result_factory: Callable[..., "PerRuleResult"],
    max_iterations: int,
    max_mutations_per_iter: int,
    seed: int | None,
    log: Callable[[str], None],
    iter_record_fn: Callable[[dict], None] | None = None,
) -> EARunResult:
    """Stateless per-iteration multi-mutation sampler (no archive, no state).

    Each iteration is independent:
      1. pick a rule uniformly at random,
      2. sample n in [1, max_mutations_per_iter] inclusive,
      3. sample n DISTINCT mutators (rng.sample -- no repeats within the chain),
      4. apply the chain cumulatively to the ORIGINAL rule text,
      5. validate (observational) + evaluate the FINAL candidate,
      6. log the record.

    No acceptance test, no restart, no cross-iteration state. Same iteration
    budget T as the EA -> one code-generation call per iteration (LLM-call
    parity). mutator_stats use whole-chain credit (reporting plan RQ2).
    """
    from datetime import datetime as _dt
    rng = random.Random(seed)
    n_mutators = len(mutators)
    # n is drawn from [1, K]; K cannot exceed the pool size (sample needs n distinct).
    k = max(1, min(max_mutations_per_iter, n_mutators))

    iterations: list["IterationResult"] = []
    per_rule_results: list["PerRuleResult"] = []
    per_rule_best_delta: dict[str, float] = {rid: 0.0 for rid in all_rule_ids}
    per_rule_best_div: dict[str, float] = {rid: 0.0 for rid in all_rule_ids}
    rate_limit_hit = False

    best_rule_id: str | None = None
    best_fitness: AggregatedFitness | None = None
    best_rule_text: str = ""

    # Whole-chain credit: every mutator in a chain whose final candidate had
    # f1 > baseline is credited.
    mutator_stats: dict[str, dict[str, int]] = {
        m.name: {"applications": 0, "applications_f1_advancing": 0} for m in mutators
    }

    for i in range(max_iterations):
        rule_id = rng.choice(all_rule_ids)
        n = rng.randint(1, k)
        chain = rng.sample(mutators, n)          # n distinct mutators, in order
        chain_names = [m.name for m in chain]
        chain_mutator = _ChainMutator(chain)

        num_affected = sum(1 for pwr in prompts_with_rules if rule_id in pwr.rule_ids)
        log(f"\n\U0001f3b2 Iteration {i+1}/{max_iterations} "
            f"-- rule={rule_id.replace('codeguard-', 'cg-')} "
            f"n={n} chain={'+'.join(chain_names)} "
            f"{num_affected}/{len(prompts_with_rules)} prompts")

        try:
            (candidate_fitness, candidate_results, mutation_changes,
             val_metadata, iter_mutated_text) = evaluate_fn(
                rule_id, rule_originals[rule_id], chain_mutator, i + 1,
                f"rand_iter{i+1:04d}",
                chain_names,
            )
        except Exception as e:
            if "rate_limit" in str(e).lower() or "429" in str(e) or "413" in str(e):
                log(f"\n⚠️  Rate limit hit at random-baseline iteration {i+1}: {e}")
                rate_limit_hit = True
                break
            raise

        has_text = iter_mutated_text is not None
        f1 = candidate_fitness.total_semgrep_delta
        f1_advance = has_text and f1 > 0.0
        mutation_identity = (iter_mutated_text == rule_originals[rule_id]) if has_text else None

        # whole-chain credit: every mutator in the chain gets an application; the
        # f1-advancing tally is credited only when the final candidate beat baseline.
        for name in chain_names:
            mutator_stats[name]["applications"] += 1
            if f1_advance:
                mutator_stats[name]["applications_f1_advancing"] += 1

        if f1 > per_rule_best_delta[rule_id]:
            per_rule_best_delta[rule_id] = f1
        if candidate_fitness.mean_code_divergence > per_rule_best_div[rule_id]:
            per_rule_best_div[rule_id] = candidate_fitness.mean_code_divergence
        if best_fitness is None or f1 > best_fitness.total_semgrep_delta:
            best_fitness = candidate_fitness
            best_rule_id = rule_id
            best_rule_text = iter_mutated_text or rule_originals[rule_id]

        iterations.append(iteration_result_factory(
            iteration=i,
            rule_text=f"[random: {rule_id}@iter{i+1}]",
            aggregated_fitness=candidate_fitness,
            individual_results=candidate_results,
            is_improvement=True,            # random always "accepts"
            mutation_changes=mutation_changes,
            validation_metadata=val_metadata,
        ))
        per_rule_results.append(per_rule_result_factory(
            rule_id=rule_id,
            iteration=i,
            fitness_delta=f1,
            aggregated_fitness=candidate_fitness,
            mutation_changes=mutation_changes,
            is_improvement=True,
            num_prompts_affected=num_affected,
        ))

        if iter_record_fn is not None:
            iter_record_fn({
                "iter": i + 1,
                "timestamp": _dt.utcnow().isoformat() + "Z",
                "strategy": "random_baseline",
                "rule_id": rule_id,
                "mutation_chain": chain_names,
                "chain_length": n,
                "mutation_identity": mutation_identity,
                "validation_passed": has_text,
                "f1": f1 if has_text else None,
                "f2": candidate_fitness.proportion_divergent if has_text else None,
                "f3": candidate_fitness.conditional_mean_divergence if has_text else None,
                "f1_advance": f1_advance,
                "accepted": True,           # random_baseline always accepts
                "num_prompts_affected": num_affected,
                "llm_calls_total": None,
                "input_tokens_total": None,
                "output_tokens_total": None,
                "validation_metadata": val_metadata or {},
                "selection_meta": {},
            })

    _log_random_summary(
        log=log,
        all_rule_ids=all_rule_ids,
        per_rule_results=per_rule_results,
        per_rule_best_delta=per_rule_best_delta,
        mutator_stats=mutator_stats,
        best_rule_id=best_rule_id,
        best_fitness=best_fitness,
    )

    return EARunResult(
        iterations=iterations,
        per_rule_results=per_rule_results,
        archives_snapshot={},                # random baseline keeps no archive
        rate_limit_hit=rate_limit_hit,
        best_rule_id=best_rule_id,
        best_rule_text=best_rule_text,
        best_fitness=best_fitness,
        per_rule_best_delta=per_rule_best_delta,
        per_rule_best_code_divergence=per_rule_best_div,
        mutator_stats=mutator_stats,
        restart_reason_counts={},            # random baseline has no restarts
    )


# ============================================================================
# End-of-run summary helpers (logging only — no behavioral impact)
# ============================================================================

def _short_rid(rid: str) -> str:
    return rid.replace("codeguard-", "cg-")


def _log_archive_snapshot(
    *,
    log: Callable[[str], None],
    archives: dict[str, "ParetoArchive"],
    iteration: int,
) -> None:
    """Print a compact archive state table every N iterations."""
    log(f"\n   📦 Archive snapshot @ iter {iteration}")
    log(f"   {'Rule':<38} {'size':>4} {'streak':>7} {'bestF1':>7} {'bestF2':>7} {'bestF3':>7}")
    for rid, arc in archives.items():
        if arc.entries:
            best_f1 = max(e.f1 for e in arc.entries)
            best_f2 = max(e.f2 for e in arc.entries)
            best_f3 = max(e.f3 for e in arc.entries)
        else:
            best_f1 = best_f2 = best_f3 = 0.0
        streak_str = f"{arc._attempts_since_insert}/{arc.restart_h}"
        log(f"   {_short_rid(rid):<38} {len(arc):>4} {streak_str:>7} "
            f"{best_f1:>+7.2f} {best_f2:>7.3f} {best_f3:>7.3f}")


def _log_ea_summary(
    *,
    log: Callable[[str], None],
    all_rule_ids: list[str],
    archives: dict[str, ParetoArchive],
    per_rule_results: list["PerRuleResult"],
    mutator_stats: dict[str, dict[str, int]],
    restart_reason_counts: dict[str, int],
    best_rule_id: str | None,
    best_entry: ArchiveEntry | None,
) -> None:
    """Print the per-rule / per-mutator / restart summary at end of an EA run."""
    sep = "═" * 88
    line = "─" * 88

    log(f"\n{sep}")
    log("📊  EA per-rule summary")
    log(sep)
    log(f"{'Rule':<40} {'iters':>5} {'size':>4} {'ins':>4} {'rej':>4} "
        f"{'rsts':>4} {'bestF1':>8} {'bestF2':>8} {'bestF3':>8}")
    log(line)
    for rid in all_rule_ids:
        arc = archives[rid]
        iters = sum(1 for r in per_rule_results if r.rule_id == rid)
        n_rsts = len(arc.restart_history)
        if arc.entries:
            best_f1 = max(e.f1 for e in arc.entries)
            best_f2 = max(e.f2 for e in arc.entries)
            best_f3 = max(e.f3 for e in arc.entries)
        else:
            best_f1 = best_f2 = best_f3 = 0.0
        log(f"{_short_rid(rid):<40} {iters:>5} {len(arc):>4} "
            f"{arc.n_inserts:>4} {arc.n_rejected:>4} {n_rsts:>4} "
            f"{best_f1:>+8.2f} {best_f2:>8.3f} {best_f3:>8.3f}")
    log(line)

    log("\n↻  Restart breakdown (totals across all rules):")
    for reason, count in restart_reason_counts.items():
        log(f"    {reason:<20} {count}")

    log("\n🧬  Mutator effectiveness (EA archive inserts):")
    log(f"{'mutator':<30} {'attempts':>10} {'inserts':>10} {'ins_f1':>10} {'ins%':>8} {'f1%':>8}")
    log("─" * 80)
    # Sort by ins_f1 desc, then inserts desc, then attempts desc for stable order
    for name, stats in sorted(
        mutator_stats.items(),
        key=lambda kv: (-kv[1].get("archive_adds_f1", 0), -kv[1]["archive_adds"],
                        -kv[1]["attempts"], kv[0]),
    ):
        att = stats["attempts"]
        ins = stats["archive_adds"]
        ins_f1 = stats.get("archive_adds_f1", 0)
        rate = (100.0 * ins / att) if att > 0 else 0.0
        rate_f1 = (100.0 * ins_f1 / att) if att > 0 else 0.0
        log(f"{name:<30} {att:>10} {ins:>10} {ins_f1:>10} {rate:>7.1f}% {rate_f1:>7.1f}%")

    log("\n🏛  Final archive contents (3 best entries per rule by f1):")
    for rid in all_rule_ids:
        arc = archives[rid]
        if not arc.entries:
            continue
        sorted_entries = sorted(arc.entries, key=lambda e: -e.f1)[:3]
        log(f"  {_short_rid(rid)}  (size={len(arc)}, inserts={arc.n_inserts}):")
        for e in sorted_entries:
            path_str = "→".join(e.mutation_path) if e.mutation_path else "(seed)"
            log(f"     [it={e.iteration_added:>4} d={e.depth}] "
                f"f1={e.f1:>+6.2f} f2={e.f2:.3f} f3={e.f3:.3f}  {path_str}")

    if best_entry is not None:
        log(f"\n🏆 Global best: rule={_short_rid(best_rule_id or '?')} "
            f"f1={best_entry.f1:+.2f} f2={best_entry.f2:.3f} f3={best_entry.f3:.3f} "
            f"depth={best_entry.depth} path={'→'.join(best_entry.mutation_path) or '(seed)'}")
    log(sep + "\n")


def _log_random_summary(
    *,
    log: Callable[[str], None],
    all_rule_ids: list[str],
    per_rule_results: list["PerRuleResult"],
    per_rule_best_delta: dict[str, float],
    mutator_stats: dict[str, dict[str, int]],
    best_rule_id: str | None,
    best_fitness: AggregatedFitness | None,
) -> None:
    """Print the per-rule / per-mutator summary for the random baseline."""
    sep = "═" * 80
    line = "─" * 80

    log(f"\n{sep}")
    log("📊  Random-baseline per-rule summary")
    log(sep)
    log(f"{'Rule':<40} {'iters':>10} {'bestF1':>10}")
    log(line)
    for rid in all_rule_ids:
        iters = sum(1 for r in per_rule_results if r.rule_id == rid)
        log(f"{_short_rid(rid):<40} {iters:>10} "
            f"{per_rule_best_delta.get(rid, 0.0):>+10.2f}")
    log(line)

    log("\n🎲  Mutator application counts (whole-chain credit):")
    log(f"{'mutator':<30} {'applications':>13} {'f1_advancing':>13} {'f1%':>8}")
    log("─" * 70)
    for name, stats in sorted(
        mutator_stats.items(),
        key=lambda kv: (-kv[1].get("applications_f1_advancing", 0),
                        -kv[1].get("applications", 0), kv[0]),
    ):
        apps = stats.get("applications", 0)
        adv = stats.get("applications_f1_advancing", 0)
        rate = (100.0 * adv / apps) if apps > 0 else 0.0
        log(f"{name:<30} {apps:>13} {adv:>13} {rate:>7.1f}%")

    if best_fitness is not None:
        log(f"\n🏆 Global best candidate: rule={_short_rid(best_rule_id or '?')} "
            f"f1={best_fitness.total_semgrep_delta:+.2f} "
            f"f2={best_fitness.proportion_divergent:.3f} "
            f"f3={best_fitness.conditional_mean_divergence:.3f}")
    log(sep + "\n")
