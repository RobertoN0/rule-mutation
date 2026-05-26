"""
(1+1) EA + Pareto archive optimizer and pure-random-walk baseline.

Both runners share the same evaluation seam — ``evaluate_fn`` — which is a
closure provided by :class:`HillClimber`. They bypass :class:`MutatorPool`
entirely because their selection logic (parent eligibility + per-entry
mutator dedup) doesn't fit the pool's blind ``select()`` API.

Top-level entry points
----------------------
* :func:`run_ea`             — (1+1) EA over per-rule :class:`ParetoArchive`
* :func:`run_random_baseline` — uniform random walk with depth-cap restart
"""

from __future__ import annotations

import random
import time
from dataclasses import dataclass, field
from typing import Any, Callable, TYPE_CHECKING

from ..evaluation.fitness import AggregatedFitness
from ..mutation import Mutator
from .pareto_archive import ArchiveEntry, ParetoArchive

if TYPE_CHECKING:
    from .hill_climber import IterationResult, PerRuleResult


# evaluate_fn signature contract — mirrors the 5-tuple from
# HillClimber._evaluate_with_per_prompt_rules so callers can plug it in directly.
EvaluateFn = Callable[
    [str, str, Mutator, int, str],   # (target_rule_id, parent_text, mutator, iteration, phase)
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
    """Per-rule archive state. Keyed by rule_id. Written into
    HillClimbResult.compounding_state for hillclimb_per_rule_*.json output."""

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
    """Per-mutator counters: {name: {"attempts": N, "archive_adds": M, "archive_adds_f1": K}}.

    - ``attempts``         : number of times this mutator was invoked.
    - ``archive_adds``     : EA → true archive insertions (passes Pareto check);
                             random_baseline → "produced a logged candidate"
                             (mutation succeeded).
    - ``archive_adds_f1``  : subset of ``archive_adds`` where the candidate's
                             ``total_semgrep_delta`` was strictly greater than its
                             parent's f1. Lets you distinguish mutators that move
                             the primary fitness signal from mutators that only
                             advance the f2/f3 (divergence) trade-off axes."""

    restart_reason_counts: dict[str, int] = field(default_factory=dict)
    """Total restart events bucketed by reason across all rules."""


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
        try:
            (candidate_fitness, candidate_results, mutation_changes,
             val_metadata, iter_mutated_text) = evaluate_fn(
                rule_id, parent.rule_text, mutator, i + 1,
                f"ea_iter{i+1}_{rule_id.replace('codeguard-', 'cg-')}",
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
                    "rule_id": rule_id,
                    "mutator": mutator_name,
                    "parent_depth": parent.depth,
                    "candidate_depth": None,
                    "mutation_identity": None,
                    "validation_passed": False,
                    "f1": None, "f2": None, "f3": None,
                    "accepted": False,
                    "f1_advance": False,
                    "num_prompts_affected": num_affected,
                    "llm_calls_total": None,
                    "input_tokens_total": None,
                    "output_tokens_total": None,
                    "selection_meta": {
                        "parent_iter": parent.iteration_added,
                        "parent_f1": parent.f1,
                        "archive_size_before": len(archive),
                        "archive_size_after": len(archive),
                        "attempts_since_insert": archive._attempts_since_insert,
                        "n_eligible_rules": len(eligible_rids),
                        "restarts_this_iter": restarts_this_iter,
                    },
                    "validation_metadata": val_metadata or {},
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
                "rule_id": rule_id,
                "mutator": mutator_name,
                "parent_depth": parent.depth,
                "candidate_depth": parent.depth + 1,
                "mutation_identity": mutation_identity,
                "validation_passed": True,
                "f1": candidate_fitness.total_semgrep_delta,
                "f2": candidate_fitness.proportion_divergent,
                "f3": candidate_fitness.conditional_mean_divergence,
                "accepted": accepted,
                "f1_advance": accepted and (candidate_fitness.total_semgrep_delta > parent.f1),
                "num_prompts_affected": num_affected,
                "llm_calls_total": None,    # populated by hill_climber from its counters if needed
                "input_tokens_total": None,
                "output_tokens_total": None,
                "selection_meta": {
                    "parent_iter": parent.iteration_added,
                    "parent_f1": parent.f1,
                    "archive_size_before": archive_size_before,
                    "archive_size_after": len(archive),
                    "attempts_since_insert": archive._attempts_since_insert,
                    "n_eligible_rules": len(eligible_rids),
                    "restarts_this_iter": restarts_this_iter,
                },
                "validation_metadata": val_metadata or {},
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
# Pure random walk baseline (no archive, no acceptance test)
# ============================================================================

@dataclass
class _RandomWalkRuleState:
    """Per-rule state for the random-walk baseline."""

    current_text: str
    current_f1: float = 0.0
    """f1 (= total_semgrep_delta) of ``current_text``. Baseline is 0 by
    construction. Used to credit ``archive_adds_f1`` when a step advances f1."""
    depth: int = 0
    tried_for_current: set[str] = field(default_factory=set)
    restart_history: list[dict[str, Any]] = field(default_factory=list)
    all_candidates: list[dict[str, Any]] = field(default_factory=list)


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
    max_depth: int,
    seed: int | None,
    log: Callable[[str], None],
    iter_record_fn: Callable[[dict], None] | None = None,
) -> EARunResult:
    """Random walk with depth-cap restart, no archive, no acceptance.

    Each iteration: pick a random rule, pick a random untried mutator for that
    rule's current_text, apply, replace current_text with offspring, increment
    depth, log the candidate. If depth hits ``max_depth`` (or all mutators have
    been tried on current_text), reset to the original. Log every candidate's
    3-vector for post-hoc EA-vs-random distribution analysis.

    bd-3wa Phase 1: ``iter_record_fn`` is invoked once per iteration with a
    strategy-agnostic record (selection_meta.strategy="random_baseline").
    """
    from datetime import datetime as _dt
    rng = random.Random(seed)
    n_mutators = len(mutators)
    mutator_names = [m.name for m in mutators]
    mutator_by_name: dict[str, Mutator] = {m.name: m for m in mutators}

    states: dict[str, _RandomWalkRuleState] = {
        rid: _RandomWalkRuleState(current_text=rule_originals[rid])
        for rid in all_rule_ids
    }

    iterations: list["IterationResult"] = []
    per_rule_results: list["PerRuleResult"] = []
    per_rule_best_delta: dict[str, float] = {rid: 0.0 for rid in all_rule_ids}
    per_rule_best_div: dict[str, float] = {rid: 0.0 for rid in all_rule_ids}
    rate_limit_hit = False

    best_rule_id: str | None = None
    best_fitness: AggregatedFitness | None = None
    best_rule_text: str = ""

    # Per-mutator stats and per-reason restart counts (parallel to run_ea shape).
    # archive_adds_f1 = "produced a candidate whose f1 > the walk's current f1"
    # (since random_baseline always advances, this measures strict f1 gains).
    mutator_stats: dict[str, dict[str, int]] = {
        m.name: {"attempts": 0, "archive_adds": 0, "archive_adds_f1": 0} for m in mutators
    }
    restart_reason_counts: dict[str, int] = {"depth_cap": 0, "mutator_exhausted": 0}

    for i in range(max_iterations):
        rule_id = rng.choice(all_rule_ids)
        state = states[rule_id]

        restart_triggered: str | None = None
        # Restart triggers BEFORE picking a mutator
        if state.depth >= max_depth:
            state.restart_history.append({
                "iteration": i, "reason": "depth_cap", "depth_at_reset": state.depth,
            })
            state.current_text = rule_originals[rule_id]
            state.current_f1 = 0.0
            state.depth = 0
            state.tried_for_current = set()
            restart_reason_counts["depth_cap"] += 1
            restart_triggered = "depth_cap"
            log(f"   ↻ rule={rule_id.replace('codeguard-', 'cg-')} restart: depth_cap")
        elif len(state.tried_for_current) >= n_mutators:
            state.restart_history.append({
                "iteration": i, "reason": "mutator_exhausted", "depth_at_reset": state.depth,
            })
            state.current_text = rule_originals[rule_id]
            state.current_f1 = 0.0
            state.depth = 0
            state.tried_for_current = set()
            restart_reason_counts["mutator_exhausted"] += 1
            restart_triggered = "mutator_exhausted"
            log(f"   ↻ rule={rule_id.replace('codeguard-', 'cg-')} restart: mutator_exhausted")

        available = [m for m in mutator_names if m not in state.tried_for_current]
        mutator_name = rng.choice(available)
        mutator = mutator_by_name[mutator_name]

        num_affected = sum(1 for pwr in prompts_with_rules if rule_id in pwr.rule_ids)
        log(f"\n🎲 Iteration {i+1}/{max_iterations} "
            f"— rule={rule_id.replace('codeguard-', 'cg-')} "
            f"depth={state.depth} mutator={mutator_name} "
            f"{num_affected}/{len(prompts_with_rules)} prompts")

        try:
            (candidate_fitness, candidate_results, mutation_changes,
             val_metadata, iter_mutated_text) = evaluate_fn(
                rule_id, state.current_text, mutator, i + 1,
                f"rand_iter{i+1}_{rule_id.replace('codeguard-', 'cg-')}",
            )
        except Exception as e:
            if "rate_limit" in str(e).lower() or "429" in str(e) or "413" in str(e):
                log(f"\n⚠️  Rate limit hit at random-baseline iteration {i+1}: {e}")
                rate_limit_hit = True
                break
            raise

        # Mark mutator tried even if validation produced no text — avoids retrying
        state.tried_for_current.add(mutator_name)
        mutator_stats[mutator_name]["attempts"] += 1
        walk_depth_before = state.depth

        if iter_mutated_text is None:
            log(f"   ⚠️ No mutated text; marked {mutator_name} tried for this version")
            if iter_record_fn is not None:
                iter_record_fn({
                    "iter": i + 1,
                    "timestamp": _dt.utcnow().isoformat() + "Z",
                    "rule_id": rule_id,
                    "mutator": mutator_name,
                    "parent_depth": walk_depth_before,
                    "candidate_depth": None,
                    "mutation_identity": None,
                    "validation_passed": False,
                    "f1": None, "f2": None, "f3": None,
                    "accepted": False,
                    "f1_advance": False,
                    "num_prompts_affected": num_affected,
                    "selection_meta": {
                        "strategy": "random_baseline",
                        "walk_depth_before": walk_depth_before,
                        "walk_depth_after": walk_depth_before,
                        "restart_triggered": restart_triggered,
                        "parent_f1": state.current_f1,
                    },
                    "validation_metadata": val_metadata or {},
                })
            continue

        # bd-3wa: capture mutation_identity BEFORE advancing the walk
        mutation_identity = (iter_mutated_text == state.current_text)

        # No acceptance test — always advance the walk
        parent_f1 = state.current_f1
        state.current_text = iter_mutated_text
        state.current_f1 = candidate_fitness.total_semgrep_delta
        state.depth += 1
        state.tried_for_current = set()  # new version → fresh slate
        mutator_stats[mutator_name]["archive_adds"] += 1  # "produced a candidate"
        if candidate_fitness.total_semgrep_delta > parent_f1:
            mutator_stats[mutator_name]["archive_adds_f1"] += 1

        # Log candidate's 3-vector for post-hoc analysis
        state.all_candidates.append({
            "iteration": i,
            "f1": candidate_fitness.total_semgrep_delta,
            "f2": candidate_fitness.proportion_divergent,
            "f3": candidate_fitness.conditional_mean_divergence,
            "mutator": mutator_name,
            "depth_after": state.depth,
        })

        # Track per-rule + global best
        fitness_delta = candidate_fitness.total_semgrep_delta
        if fitness_delta > per_rule_best_delta[rule_id]:
            per_rule_best_delta[rule_id] = fitness_delta
        if candidate_fitness.mean_code_divergence > per_rule_best_div[rule_id]:
            per_rule_best_div[rule_id] = candidate_fitness.mean_code_divergence

        if best_fitness is None or candidate_fitness.total_semgrep_delta > best_fitness.total_semgrep_delta:
            best_fitness = candidate_fitness
            best_rule_id = rule_id
            best_rule_text = iter_mutated_text

        iterations.append(iteration_result_factory(
            iteration=i,
            rule_text=f"[random: {rule_id}@iter{i+1}]",
            aggregated_fitness=candidate_fitness,
            individual_results=candidate_results,
            is_improvement=True,  # walk always advances
            mutation_changes=mutation_changes,
            validation_metadata=val_metadata,
        ))
        per_rule_results.append(per_rule_result_factory(
            rule_id=rule_id,
            iteration=i,
            fitness_delta=fitness_delta,
            aggregated_fitness=candidate_fitness,
            mutation_changes=mutation_changes,
            is_improvement=True,
            num_prompts_affected=num_affected,
        ))

        # bd-3wa: emit per-iter record into iterations.jsonl
        if iter_record_fn is not None:
            iter_record_fn({
                "iter": i + 1,
                "timestamp": _dt.utcnow().isoformat() + "Z",
                "rule_id": rule_id,
                "mutator": mutator_name,
                "parent_depth": walk_depth_before,
                "candidate_depth": state.depth,
                "mutation_identity": mutation_identity,
                "validation_passed": True,
                "f1": candidate_fitness.total_semgrep_delta,
                "f2": candidate_fitness.proportion_divergent,
                "f3": candidate_fitness.conditional_mean_divergence,
                "accepted": True,  # random_baseline always advances
                "f1_advance": candidate_fitness.total_semgrep_delta > parent_f1,
                "num_prompts_affected": num_affected,
                "selection_meta": {
                    "strategy": "random_baseline",
                    "walk_depth_before": walk_depth_before,
                    "walk_depth_after": state.depth,
                    "restart_triggered": restart_triggered,
                    "parent_f1": parent_f1,
                },
                "validation_metadata": val_metadata or {},
            })

    # Build snapshot dict mirroring archive snapshot shape (consistent JSON)
    snapshot = {
        rid: {
            "mode": "random_baseline",
            "current_text": s.current_text,
            "current_depth": s.depth,
            "current_tried_mutators": sorted(s.tried_for_current),
            "restart_history": s.restart_history,
            "all_candidates": s.all_candidates,
            "n_candidates_logged": len(s.all_candidates),
            "n_restarts": len(s.restart_history),
        }
        for rid, s in states.items()
    }

    _log_random_summary(
        log=log,
        all_rule_ids=all_rule_ids,
        states=states,
        mutator_stats=mutator_stats,
        restart_reason_counts=restart_reason_counts,
        per_rule_best_delta=per_rule_best_delta,
        best_rule_id=best_rule_id,
        best_fitness=best_fitness,
    )

    return EARunResult(
        iterations=iterations,
        per_rule_results=per_rule_results,
        archives_snapshot=snapshot,
        rate_limit_hit=rate_limit_hit,
        best_rule_id=best_rule_id,
        best_rule_text=best_rule_text,
        best_fitness=best_fitness,
        per_rule_best_delta=per_rule_best_delta,
        per_rule_best_code_divergence=per_rule_best_div,
        mutator_stats=mutator_stats,
        restart_reason_counts=restart_reason_counts,
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
    states: dict[str, _RandomWalkRuleState],
    mutator_stats: dict[str, dict[str, int]],
    restart_reason_counts: dict[str, int],
    per_rule_best_delta: dict[str, float],
    best_rule_id: str | None,
    best_fitness: AggregatedFitness | None,
) -> None:
    """Print the per-rule / per-mutator / restart summary for random_baseline."""
    sep = "═" * 80
    line = "─" * 80

    log(f"\n{sep}")
    log("📊  Random-baseline per-rule summary")
    log(sep)
    log(f"{'Rule':<40} {'candidates':>10} {'restarts':>9} {'bestF1':>10}")
    log(line)
    for rid in all_rule_ids:
        s = states[rid]
        log(f"{_short_rid(rid):<40} {len(s.all_candidates):>10} "
            f"{len(s.restart_history):>9} {per_rule_best_delta.get(rid, 0.0):>+10.2f}")
    log(line)

    log("\n↻  Restart breakdown (totals across all rules):")
    for reason, count in restart_reason_counts.items():
        log(f"    {reason:<20} {count}")

    log("\n🎲  Mutator attempt counts (random_baseline walk):")
    log(f"{'mutator':<30} {'attempts':>10} {'produced':>10} {'f1_gain':>10} {'f1%':>8}")
    log("─" * 75)
    for name, stats in sorted(
        mutator_stats.items(),
        key=lambda kv: (-kv[1].get("archive_adds_f1", 0), -kv[1]["attempts"], kv[0]),
    ):
        att = stats["attempts"]
        prod = stats["archive_adds"]
        f1_gain = stats.get("archive_adds_f1", 0)
        rate_f1 = (100.0 * f1_gain / att) if att > 0 else 0.0
        log(f"{name:<30} {att:>10} {prod:>10} {f1_gain:>10} {rate_f1:>7.1f}%")

    if best_fitness is not None:
        log(f"\n🏆 Global best candidate: rule={_short_rid(best_rule_id or '?')} "
            f"f1={best_fitness.total_semgrep_delta:+.2f} "
            f"f2={best_fitness.proportion_divergent:.3f} "
            f"f3={best_fitness.conditional_mean_divergence:.3f}")
    log(sep + "\n")
