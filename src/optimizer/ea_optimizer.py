"""
(1+1) EA over a single full-chromosome Pareto archive + a stateful random-walk
baseline.

The unit of search is the whole rule set (a :class:`RuleSetChromosome`): rule-text
alleles + a global rule-ordering policy. Both runners share one evaluation seam —
``evaluate_chromosome_fn(chromosome, iter_id) -> (AggregatedFitness, results,
n_reused, n_rerun)`` — a closure provided by :class:`HillClimber` that renders every
prompt from the chromosome and scores the whole rule set.

Top-level entry points
----------------------
* :func:`run_ea`             — (1+1) EA over one :class:`ChromosomeArchive`
* :func:`run_random_baseline` — persistent single-chromosome random walk (no archive)

See ``CHROMOSOME_RESTRUCTURE_PLAN.md`` for the design + decision ledger.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, TYPE_CHECKING

from ..evaluation.fitness import AggregatedFitness
from ..mutation import Mutator
from .chromosome import ChromosomeArchive, RuleSetChromosome, RuleSetSpace

if TYPE_CHECKING:
    from .hill_climber import IterationResult


class WallTimeStop(BaseException):
    """Raised to abort the IN-FLIGHT iteration when SLURM's pre-timeout signal
    fires, so we don't wait out a (possibly long) iteration before saving.

    Subclasses ``BaseException`` (not ``Exception``) on purpose: the evaluation
    hot path wraps eval in ``except Exception`` (rate-limit handling) and must
    NOT swallow the stop. Raised from a controlled checkpoint (the per-prompt
    loop in ``HillClimber._evaluate_chromosome``), never from the async signal
    handler. The runners catch it and fall through to finalization.
    """


# Seam contract: (chromosome, iter_id) -> (fitness, per_prompt_results, n_reused, n_rerun)
EvaluateChromosomeFn = Callable[
    [RuleSetChromosome, str],
    "tuple[AggregatedFitness, list[Any], int, int]",
]


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


# ============================================================================
# Result object
# ============================================================================

@dataclass
class ChromosomeRunResult:
    """What a runner returns to :class:`HillClimber`."""

    iterations: list["IterationResult"]
    archive_snapshot: dict[str, Any]
    """Final single-archive snapshot (EA) or ``{}`` (random). Stored on
    HillClimbResult.compounding_state."""

    best_chromosome: RuleSetChromosome
    best_fitness: AggregatedFitness | None

    n_accepted: int = 0
    rate_limit_hit: bool = False

    mutator_stats: dict[str, dict[str, int]] = field(default_factory=dict)
    restart_reason_counts: dict[str, int] = field(default_factory=dict)


# ============================================================================
# Move helpers (EA)
# ============================================================================

def _untried_mutators(parent: RuleSetChromosome, rid: str, mutators: list[Mutator]) -> list[Mutator]:
    return [m for m in mutators if ("mut", rid, m.name) not in parent.tried]


def _eligible_genes(
    parent: RuleSetChromosome,
    all_rule_ids: list[str],
    mutators: list[Mutator],
    max_depth: int,
    ea_n_mutations: int,
) -> list[str]:
    """Rules that still admit a text-mutation move on ``parent``.

    A gene is eligible when its depth is below ``max_depth`` and (for the
    single-mutation default) it has ≥1 untried mutator. For multi-mutation
    (Design B) any below-cap gene is eligible — chains are re-drawable, and the
    archive's cid dedup rejects exact repeats.
    """
    out: list[str] = []
    for rid in all_rule_ids:
        if parent.gene_depth(rid) >= max_depth:
            continue
        if ea_n_mutations == 1 and not _untried_mutators(parent, rid, mutators):
            continue
        out.append(rid)
    return out


def _apply_chain(mutators: list[Mutator], text: str) -> tuple[str, list[str], list[str]]:
    """Apply mutators in order (cumulative). Returns (new_text, names, changes)."""
    cur = text
    names: list[str] = []
    changes: list[str] = []
    for m in mutators:
        res = m.mutate(cur)
        cur = res.mutated
        names.append(m.name)
        changes.extend(res.changes)
    return cur, names, changes


# ============================================================================
# (1+1) EA over one chromosome archive
# ============================================================================

def run_ea(
    *,
    space: RuleSetSpace,
    origin: RuleSetChromosome,
    prompts_with_rules: list[Any],
    mutators: list[Mutator],
    evaluate_chromosome_fn: EvaluateChromosomeFn,
    iteration_result_factory: Callable[..., "IterationResult"],
    max_iterations: int,
    archive_cap: int,
    restart_h: int,
    max_depth: int,
    ea_n_mutations: int = 1,
    order_move_weight: float = 0.0,
    reverse_move_weight: float = 0.0,
    seed: int | None,
    log: Callable[[str], None],
    iter_record_fn: Callable[[dict], None] | None = None,
    archive_snapshot_fn: Callable[[int, dict], None] | None = None,
    save_move_fn: Callable[..., None] | None = None,
    validate_move_fn: Callable[..., dict] | None = None,
    snapshot_every: int = 20,
    should_stop_fn: Callable[[], bool] | None = None,
) -> ChromosomeRunResult:
    """(1+1) EA over a single full-chromosome Pareto archive.

    Each iteration: pick a parent chromosome from the archive (origin always
    available), pick a move (text-mutate one gene, or — when enabled — reorder /
    revert a gene), build the child chromosome, evaluate the WHOLE chromosome,
    and offer it to the archive by Pareto dominance over (f1, f2, f3).

    ``ea_n_mutations`` = mutators applied per text move (default 1 = Design A;
    >1 samples a 1..n chain to match the random baseline's move — Design B).
    ``order_move_weight`` / ``reverse_move_weight`` gate the order/reverse moves
    (0 by default). RNG draws use one seeded ``random.Random`` for reproducibility.
    """
    rng = random.Random(seed)
    archive = ChromosomeArchive(origin, cap=archive_cap, restart_h=restart_h, rng=rng)

    iterations: list["IterationResult"] = []
    mutator_stats: dict[str, dict[str, int]] = {
        m.name: {"attempts": 0, "archive_adds": 0, "archive_adds_f1": 0} for m in mutators
    }
    restart_reason_counts: dict[str, int] = {"stagnation": 0}
    n_accepted = 0
    rate_limit_hit = False
    mutate_weight = max(0.0, 1.0 - order_move_weight - reverse_move_weight)

    def _is_eligible(parent: RuleSetChromosome) -> bool:
        if _eligible_genes(parent, space.all_rule_ids, mutators, max_depth, ea_n_mutations):
            return True
        if reverse_move_weight > 0 and parent.mutated_rule_ids():
            return True
        if order_move_weight > 0:
            return True
        return False

    last_completed = 0
    for i in range(max_iterations):
        if should_stop_fn is not None and should_stop_fn():
            log(f"\n⏹️  Graceful stop (SLURM pre-timeout) — stopping after "
                f"{last_completed}/{max_iterations} iterations")
            break

        # ---- 0. restart on stagnation (option b: re-open, never wipe) --------
        restarts_this_iter: list[dict[str, Any]] = []
        if archive.should_restart():
            archive.restart(iteration=i + 1, reason="stagnation")
            restart_reason_counts["stagnation"] += 1
            restarts_this_iter.append({"reason": "stagnation"})
            log(f"   ↻ archive restart: stagnation (front_size={len(archive)})")

        # ---- 1. pick a parent (restart re-opens exploration if all exhausted)
        parent = archive.sample_parent(_is_eligible)
        if parent is None:
            archive.restart(iteration=i + 1, reason="exhausted")
            restart_reason_counts["exhausted"] = restart_reason_counts.get("exhausted", 0) + 1
            restarts_this_iter.append({"reason": "exhausted"})
            parent = archive.sample_parent(_is_eligible)
            if parent is None:
                log("\n⏹️  No eligible parent even after restart — stopping early")
                break

        # ---- 2. choose + build a move ---------------------------------------
        move = _choose_and_build_move(
            parent, space, prompts_with_rules, mutators, rng, max_depth, ea_n_mutations,
            mutate_weight, order_move_weight, reverse_move_weight,
        )
        if move is None:
            # Parent had no realizable move (should be filtered by eligibility);
            # mark a defensive stagnation tick and continue.
            archive._attempts_since_insert += 1
            continue

        child, move_key, move_type, rule_id, chain_names, changes, is_identity = move
        for name in chain_names:
            mutator_stats.setdefault(name, {"attempts": 0, "archive_adds": 0, "archive_adds_f1": 0})
            mutator_stats[name]["attempts"] += 1
        archive.mark_tried(parent, move_key)

        gene_depth = child.gene_depth(rule_id) if rule_id else 0

        # ---- 3. identity moves consume the slot but are not evaluated -------
        if is_identity:
            archive._attempts_since_insert += 1
            # Own header block (leading blank line) so it reads as a distinct
            # iteration rather than being squished onto the previous one.
            log(f"\n⏭️  Iteration {i+1}/{max_iterations} — identity {move_type} "
                f"rule={(rule_id or '-').replace('codeguard-', 'cg-')} "
                f"mutator={'+'.join(chain_names) or rule_id} "
                f"— no change vs parent, slot consumed (no eval)")
            # Record the (unchanged) chromosome: an identity candidate equals its
            # parent, so chromosome_id = parent.cid (never null) with f1=None.
            _emit_record(iter_record_fn, i + 1, "ea", parent, child=parent, move_type=move_type,
                         rule_id=rule_id, chain_names=chain_names, agg=None, accepted=False,
                         identity=True, gene_depth=gene_depth, n_reused=0, n_rerun=0,
                         eligible=len(space.all_rule_ids), restarts=restarts_this_iter)
            last_completed = i + 1
            continue

        space.stamp(child)

        # ---- 4. header → validation → evaluate ------------------------------
        # Header first so both the validation line and the per-prompt generation
        # lines nest under this iteration. Validation is computed before code
        # generation, so its log line must precede the generation lines.
        log(f"\n🧬 Iteration {i+1}/{max_iterations} — {move_type} "
            f"rule={(rule_id or '-').replace('codeguard-', 'cg-')} "
            f"mutator={'+'.join(chain_names) or '-'} depth={gene_depth} "
            f"parent_f1={parent.f1:+.2f} front={len(archive)}")

        # Optional quality validation of the mutation (observational; never refuses).
        validation_metadata: dict = {}
        if move_type == "mutate" and validate_move_fn is not None:
            validation_metadata = validate_move_fn(
                rule_id, space.allele(parent, rule_id), space.allele(child, rule_id),
                chain_names, changes,
            )

        try:
            agg, _results, n_reused, n_rerun = evaluate_chromosome_fn(child, f"ea_iter{i+1:04d}")
        except WallTimeStop:
            log(f"\n⏱️  Pre-timeout during iteration {i+1} — discarding in-flight; "
                f"finalizing from {last_completed} completed iterations.")
            break
        except Exception as e:  # noqa: BLE001 — rate-limit handling only
            if "rate_limit" in str(e).lower() or "429" in str(e) or "413" in str(e):
                log(f"\n⚠️  Rate limit hit at EA iteration {i+1}: {e}")
                rate_limit_hit = True
                break
            raise

        child.f1, child.f2, child.f3 = (
            agg.total_semgrep_delta, agg.proportion_divergent, agg.conditional_mean_divergence,
        )
        child.fitness = agg

        # ---- 5. offer to the archive ----------------------------------------
        parent_f1 = parent.f1
        front_before = {e.cid for e in archive.entries}
        size_before = len(archive)
        accepted, reason = archive.try_add(child, iteration=i + 1)
        evicted = front_before - {e.cid for e in archive.entries}
        if accepted:
            n_accepted += 1
            if chain_names:
                mutator_stats[chain_names[-1]]["archive_adds"] += 1
                if child.f1 > parent_f1:
                    mutator_stats[chain_names[-1]]["archive_adds_f1"] += 1
            log(f"   ✅ archive add: f1={child.f1:+.2f} f2={child.f2:.3f} f3={child.f3:.3f} "
                f"(front={len(archive)}/{archive.cap}, cid={child.cid})")
            if evicted:
                log(f"   ⤷ evicted from front (dominated or cap-overflow): "
                    f"{', '.join(sorted(evicted))}")
            if len(archive) < size_before:
                log(f"   ↧ front shrank {size_before} → {len(archive)}")
        else:
            log(f"   ✗ rejected ({reason}): f1={child.f1:+.2f} f2={child.f2:.3f} f3={child.f3:.3f} "
                f"[front={len(archive)}/{archive.cap}, "
                f"stagnation={archive._attempts_since_insert}/{restart_h}]")

        # Persist this iteration's mutated rule(s) regardless of archive outcome,
        # so mutated_rules/iterNNN/ documents every evaluated candidate. An
        # accepted chromosome's genes live at its accept iteration — exactly what
        # the archive snapshot's text_ref points to.
        if save_move_fn is not None:
            save_move_fn(iteration=i + 1, child=child, space=space, move_type=move_type,
                         rule_id=rule_id, chain_names=chain_names, changes=changes,
                         validation_metadata=validation_metadata, accepted=accepted)

        iterations.append(iteration_result_factory(
            iteration=i,
            rule_text=f"[ea: {child.cid}]",
            aggregated_fitness=agg,
            individual_results=[],
            is_improvement=accepted,
            mutation_changes=changes,
            validation_metadata=validation_metadata,
        ))

        _emit_record(iter_record_fn, i + 1, "ea", parent, child=child, move_type=move_type,
                     rule_id=rule_id, chain_names=chain_names, agg=agg, accepted=accepted,
                     identity=False, gene_depth=gene_depth, n_reused=n_reused, n_rerun=n_rerun,
                     eligible=len(space.all_rule_ids), restarts=restarts_this_iter,
                     parent_f1=parent_f1, validation_metadata=validation_metadata)

        if (i + 1) % snapshot_every == 0 and archive_snapshot_fn is not None:
            archive_snapshot_fn(i + 1, archive.snapshot())

        last_completed = i + 1

    if archive_snapshot_fn is not None and last_completed > 0:
        archive_snapshot_fn(last_completed, archive.snapshot())

    best = archive.best()
    _log_ea_summary(log, archive, mutator_stats, restart_reason_counts, best)
    return ChromosomeRunResult(
        iterations=iterations,
        archive_snapshot=archive.snapshot(),
        best_chromosome=best,
        best_fitness=best.fitness,
        n_accepted=n_accepted,
        rate_limit_hit=rate_limit_hit,
        mutator_stats=mutator_stats,
        restart_reason_counts=restart_reason_counts,
    )


def _choose_and_build_move(
    parent: RuleSetChromosome,
    space: RuleSetSpace,
    prompts_with_rules: list[Any],
    mutators: list[Mutator],
    rng: random.Random,
    max_depth: int,
    ea_n_mutations: int,
    mutate_weight: float,
    order_weight: float,
    reverse_weight: float,
):
    """Pick a move type by weight and build the child chromosome.

    Returns ``(child, move_key, move_type, rule_id, chain_names, changes,
    is_identity)`` or ``None`` when no move is realizable. ``move_key`` is the
    hashable token recorded in ``parent.tried``.
    """
    move_type = _weighted_move_type(rng, parent, space, mutators, max_depth, ea_n_mutations,
                                    mutate_weight, order_weight, reverse_weight)
    if move_type is None:
        return None

    if move_type == "reverse":
        rid = rng.choice(sorted(parent.mutated_rule_ids()))
        child = parent.with_reverted(rid)
        return child, ("rev", rid), "reverse", rid, [], [f"reverted {rid}"], False

    if move_type == "order":
        rid = rng.choice(space.all_rule_ids)
        op = rng.choice(["front", "back"])
        child = parent.with_priority(rid, _order_extreme(parent, op))
        # E1: an order move that changes no prompt's render is an identity.
        is_identity = not _order_changes_any_prompt(parent, child, prompts_with_rules)
        return child, ("order", rid, op), "order", rid, [], [f"{op}:{rid}"], is_identity

    # text mutation (default)
    genes = _eligible_genes(parent, space.all_rule_ids, mutators, max_depth, ea_n_mutations)
    if not genes:
        return None
    rid = rng.choice(genes)
    depth = parent.gene_depth(rid)
    if ea_n_mutations == 1:
        chosen = [rng.choice(_untried_mutators(parent, rid, mutators))]
    else:
        room = max(1, min(ea_n_mutations, max_depth - depth, len(mutators)))
        chosen = rng.sample(mutators, rng.randint(1, room))
    new_text, names, changes = _apply_chain(chosen, space.allele(parent, rid))
    is_identity = new_text == space.allele(parent, rid)
    child = parent if is_identity else parent.with_gene_chain(rid, new_text, names)
    return child, ("mut", rid, tuple(names)), "mutate", rid, names, changes, is_identity


def _weighted_move_type(rng, parent, space, mutators, max_depth, ea_n_mutations,
                        mutate_weight, order_weight, reverse_weight):
    """Choose an available move type by weight; fall back to any available one."""
    can_mutate = bool(_eligible_genes(parent, space.all_rule_ids, mutators, max_depth, ea_n_mutations))
    can_reverse = reverse_weight > 0 and bool(parent.mutated_rule_ids())
    can_order = order_weight > 0
    options = []
    if can_mutate:
        options.append(("mutate", mutate_weight))
    if can_order:
        options.append(("order", order_weight))
    if can_reverse:
        options.append(("reverse", reverse_weight))
    options = [(t, w) for t, w in options if w > 0] or [(t, 1.0) for t, _ in options]
    if not options:
        return None
    total = sum(w for _, w in options)
    r = rng.random() * total
    acc = 0.0
    for t, w in options:
        acc += w
        if r <= acc:
            return t
    return options[-1][0]


def _order_extreme(parent: RuleSetChromosome, op: str) -> int:
    """Priority that moves a rule to the front (max+1) or back (min-1)."""
    vals = list(parent.order_priority.values()) or [0]
    return (max(vals) + 1) if op == "front" else (min(vals) - 1)


def _order_changes_any_prompt(parent, child, prompts_with_rules) -> bool:
    """True iff the reorder changes at least one prompt's rendered order (E1)."""
    for pwr in prompts_with_rules:
        if parent.render_order(pwr.rule_ids) != child.render_order(pwr.rule_ids):
            return True
    return False


# ============================================================================
# Random-walk baseline (persistent single chromosome, no archive)
# ============================================================================

def run_random_baseline(
    *,
    space: RuleSetSpace,
    origin: RuleSetChromosome,
    prompts_with_rules: list[Any],
    mutators: list[Mutator],
    evaluate_chromosome_fn: EvaluateChromosomeFn,
    iteration_result_factory: Callable[..., "IterationResult"],
    max_iterations: int,
    max_mutations_per_iter: int,
    max_depth: int,
    seed: int | None,
    log: Callable[[str], None],
    iter_record_fn: Callable[[dict], None] | None = None,
    save_move_fn: Callable[..., None] | None = None,
    validate_move_fn: Callable[..., dict] | None = None,
    should_stop_fn: Callable[[], bool] | None = None,
) -> ChromosomeRunResult:
    """Persistent single-chromosome random walk over full rule sets.

    Each iteration: pick a rule uniformly, sample n∈[1, K] distinct mutators,
    apply that chain **to the ORIGINAL rule text**, overwrite that gene in the
    carried-forward chromosome, evaluate the whole chromosome, and keep going.
    No archive, no acceptance, no restart, no guided selection.
    """
    rng = random.Random(seed)
    k_cap = max(1, min(max_mutations_per_iter, len(mutators), max_depth))

    iterations: list["IterationResult"] = []
    mutator_stats: dict[str, dict[str, int]] = {
        m.name: {"applications": 0, "applications_f1_advancing": 0} for m in mutators
    }
    current = origin
    best = origin
    best_fitness = origin.fitness
    rate_limit_hit = False

    last_completed = 0
    for i in range(max_iterations):
        if should_stop_fn is not None and should_stop_fn():
            log(f"\n⏹️  Graceful stop (SLURM pre-timeout) — stopping after "
                f"{last_completed}/{max_iterations} iterations")
            break

        rid = rng.choice(space.all_rule_ids)
        n = rng.randint(1, k_cap)
        chain = rng.sample(mutators, n)
        chain_names = [m.name for m in chain]
        new_text, _names, changes = _apply_chain(chain, space.originals[rid])

        # E2: identity is measured against the ORIGINAL — a no-op chain must not
        # advance the walk (and must not revert an already-mutated gene).
        if new_text == space.originals[rid]:
            # Own header block (leading blank line) so it reads as a distinct
            # iteration rather than being squished onto the previous one.
            log(f"\n⏭️  Iteration {i+1}/{max_iterations} — identity chain "
                f"rule={rid.replace('codeguard-', 'cg-')} "
                f"chain={'+'.join(chain_names)} "
                f"— chain was a no-op vs original, walk not advanced (no eval)")
            for name in chain_names:
                mutator_stats[name]["applications"] += 1
            _emit_record(iter_record_fn, i + 1, "random_baseline", parent=None, child=current,
                         move_type="mutate", rule_id=rid, chain_names=chain_names, agg=None,
                         accepted=False, identity=True, gene_depth=current.gene_depth(rid),
                         n_reused=0, n_rerun=0)
            continue

        child = space.stamp(current.with_gene_from_original(rid, new_text, chain_names))

        # Optional quality validation (observational). Random re-derives from the
        # ORIGINAL, so the validated parent text is the original rule.
        validation_metadata: dict = {}
        if validate_move_fn is not None:
            validation_metadata = validate_move_fn(
                rid, space.originals[rid], new_text, chain_names, changes,
            )

        log(f"\n🎲 Iteration {i+1}/{max_iterations} — rule="
            f"{rid.replace('codeguard-', 'cg-')} n={n} chain={'+'.join(chain_names)} "
            f"mutated_genes={len(child.mutated_rule_ids())}")
        try:
            agg, _results, n_reused, n_rerun = evaluate_chromosome_fn(child, f"rand_iter{i+1:04d}")
        except WallTimeStop:
            log(f"\n⏹️  Pre-timeout mid-eval — stopping after {last_completed} iterations")
            break
        except Exception as e:  # noqa: BLE001
            if "rate_limit" in str(e).lower() or "429" in str(e) or "413" in str(e):
                log(f"\n⚠️  Rate limit hit at random iteration {i+1}: {e}")
                rate_limit_hit = True
                break
            raise

        child.f1, child.f2, child.f3 = (
            agg.total_semgrep_delta, agg.proportion_divergent, agg.conditional_mean_divergence,
        )
        child.fitness = agg
        current = child  # carry forward — always persisted

        f1_advance = child.f1 > 0.0
        for name in chain_names:
            mutator_stats[name]["applications"] += 1
            if f1_advance:
                mutator_stats[name]["applications_f1_advancing"] += 1

        if best_fitness is None or child.f1 > best.f1:
            best, best_fitness = child, agg

        if save_move_fn is not None:
            save_move_fn(iteration=i + 1, child=child, space=space, move_type="mutate",
                         rule_id=rid, chain_names=chain_names, changes=changes,
                         validation_metadata=validation_metadata, accepted=True)

        iterations.append(iteration_result_factory(
            iteration=i, rule_text=f"[random: {child.cid}]", aggregated_fitness=agg,
            individual_results=[], is_improvement=True, mutation_changes=changes,
            validation_metadata=validation_metadata,
        ))
        _emit_record(iter_record_fn, i + 1, "random_baseline", parent=None, child=child,
                     move_type="mutate", rule_id=rid, chain_names=chain_names, agg=agg,
                     accepted=True, identity=False, gene_depth=child.gene_depth(rid),
                     n_reused=n_reused, n_rerun=n_rerun, validation_metadata=validation_metadata)
        last_completed = i + 1

    # best includes the origin floor (f1 >= 0): if no walk step beat baseline,
    # report the origin.
    if best.f1 < origin.f1:
        best, best_fitness = origin, origin.fitness
    _log_random_summary(log, mutator_stats, best)
    return ChromosomeRunResult(
        iterations=iterations,
        archive_snapshot={},
        best_chromosome=best,
        best_fitness=best_fitness,
        n_accepted=len(iterations),
        rate_limit_hit=rate_limit_hit,
        mutator_stats=mutator_stats,
        restart_reason_counts={},
    )


# ============================================================================
# Records + logging
# ============================================================================

def _emit_record(
    iter_record_fn, iteration, strategy, parent, child, move_type, rule_id, chain_names,
    agg, accepted, identity, gene_depth, n_reused, n_rerun,
    eligible: int = 0, restarts: list | None = None, parent_f1: float | None = None,
    validation_metadata: dict | None = None,
):
    if iter_record_fn is None:
        return
    f1 = agg.total_semgrep_delta if agg is not None else None
    f2 = agg.proportion_divergent if agg is not None else None
    f3 = agg.conditional_mean_divergence if agg is not None else None
    p_f1 = parent_f1 if parent_f1 is not None else (parent.f1 if parent is not None else None)
    rec = {
        "iter": iteration,
        "timestamp": _utcnow(),
        "strategy": strategy,
        "chromosome_id": child.cid if child is not None else None,
        "parent_chromosome_id": (parent.cid if parent is not None else None),
        "move_type": move_type,
        "rule_id": rule_id,
        "mutation_chain": list(chain_names),
        "chain_length": len(chain_names),
        "mutation_identity": identity,
        "mutated_rule_ids": sorted(child.mutated_rule_ids()) if child is not None else [],
        "gene_depth": gene_depth,
        "f1": f1, "f2": f2, "f3": f3,
        "f1_advance": bool(accepted and f1 is not None and p_f1 is not None and f1 > p_f1),
        "accepted": accepted,
        "n_prompts_rerun": n_rerun,
        "n_prompts_reused": n_reused,
        "validation_metadata": validation_metadata or {},
        "selection_meta": (
            {} if strategy == "random_baseline" else {
                "parent_f1": p_f1,
                "n_eligible_rules": eligible,
                "restarts_this_iter": restarts or [],
            }
        ),
    }
    iter_record_fn(rec)


def _log_ea_summary(log, archive, mutator_stats, restart_reason_counts, best):
    sep = "═" * 80
    log(f"\n{sep}\n📊  EA chromosome-archive summary\n{sep}")
    log(f"   front_size={len(archive)}  inserts={archive.n_inserts}  "
        f"rejected={archive.n_rejected} (dup={archive.n_dup_rejected})  "
        f"restarts={len(archive.restart_history)}")
    log(f"   best: f1={best.f1:+.2f} f2={best.f2:.3f} f3={best.f3:.3f} "
        f"mutated={sorted(best.mutated_rule_ids())} cid={best.cid}")
    log("\n🧬  Mutator effectiveness (last-mutator credit):")
    for name, s in sorted(mutator_stats.items(), key=lambda kv: -kv[1]["archive_adds"]):
        att, ins = s["attempts"], s["archive_adds"]
        rate = (100.0 * ins / att) if att else 0.0
        log(f"   {name:<26} attempts={att:>4} adds={ins:>4} ({rate:4.1f}%)")
    log(sep + "\n")


def _log_random_summary(log, mutator_stats, best):
    sep = "═" * 80
    log(f"\n{sep}\n📊  Random-walk summary\n{sep}")
    log(f"   best: f1={best.f1:+.2f} f2={best.f2:.3f} f3={best.f3:.3f} "
        f"mutated={sorted(best.mutated_rule_ids())} cid={best.cid}")
    log("\n🎲  Mutator applications (whole-chain credit):")
    for name, s in sorted(mutator_stats.items(), key=lambda kv: -kv[1]["applications"]):
        apps, adv = s["applications"], s["applications_f1_advancing"]
        rate = (100.0 * adv / apps) if apps else 0.0
        log(f"   {name:<26} apps={apps:>4} f1_adv={adv:>4} ({rate:4.1f}%)")
    log(sep + "\n")
