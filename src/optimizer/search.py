"""
Search algorithms over full rule-set chromosomes: an archive-based EA with random
initialisation + periodic random injection, and an i.i.d. random-search baseline.

The unit of search is the whole rule set (a :class:`RuleSetChromosome`): rule-text
alleles + a global rule-ordering policy. Both runners share one evaluation seam —
``evaluate_chromosome_fn(chromosome, iter_id) -> (AggregatedFitness, results,
n_reused, n_rerun)`` — a closure provided by the engine that renders every prompt
from the chromosome and scores the whole rule set.

Objectives — the "conservative" set (adopted 2026-07-10), all MAXIMISED by the
Pareto archive:
    f1 = Semgrep-finding reduction (sign set by
         the engine's ``objective_direction``)
    f2 = textual similarity (mean SBERT similarity versus authored originals;
         stored as ``rule_fidelity`` for schema compatibility)
    f3 = −parsimony (negated count of mutated rules — prefer the smaller edit)

Top-level entry points
----------------------
* :func:`run_ea` — five independent origin-based candidates initialise one
  :class:`ChromosomeArchive`; the main loop alternates local archive moves with
  periodic origin-based injections.
* :func:`run_random_search` — the same five-candidate prefix followed by
  independent origin-based samples (no carry-forward, no archive).
* :func:`build_random_chromosome` — the one shared sampler behind random search,
  EA initialisation, and EA injection, so "initialised exactly like random"
  holds by construction.
"""

from __future__ import annotations

import random
import time
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, TYPE_CHECKING

from ..evaluation.fitness import AggregatedFitness
from ..mutation import Mutator
from .chromosome import ChromosomeArchive, RuleSetChromosome, RuleSetSpace, dominates

if TYPE_CHECKING:
    from .engine import IterationResult


class WallTimeStop(BaseException):
    """Raised to abort the IN-FLIGHT iteration when SLURM's pre-timeout signal
    fires, so we don't wait out a (possibly long) iteration before saving.

    Subclasses ``BaseException`` (not ``Exception``) on purpose: the evaluation
    hot path wraps eval in ``except Exception`` (rate-limit handling) and must
    NOT swallow the stop. Raised from a controlled checkpoint (the per-prompt
    loop in the engine's ``_evaluate_chromosome``), never from the async signal
    handler. The runners catch it and fall through to finalization.
    """


class IdentityRetryLimitExceeded(RuntimeError):
    """Raised when one budgeted evaluation cannot produce a non-identity.

    Identity/no-op attempts sit outside the evaluation budget, so an all-no-op
    mutator configuration would otherwise loop forever without advancing the
    budget. This internal guard turns that degenerate case into a loud failure.
    """


# Internal safety cap on consecutive identity proposals per pending evaluation.
# Not an experiment knob — a run never hits it under a non-degenerate mutator
# pool; it only prevents a silent infinite loop on a misconfigured pool.
_IDENTITY_RETRY_LIMIT = 100
INITIALIZATION_SAMPLES = 5


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
    """What a runner returns to the engine."""

    iterations: list["IterationResult"]
    archive_snapshot: dict[str, Any]
    """Final single-archive snapshot (EA) or ``{}`` (random search). Stored on
    SearchResult.compounding_state."""

    best_chromosome: RuleSetChromosome
    best_fitness: AggregatedFitness | None

    n_accepted: int = 0
    rate_limit_hit: bool = False

    mutator_stats: dict[str, dict[str, int]] = field(default_factory=dict)
    initialization_evaluations: int = 0
    main_loop_evaluations: int = 0
    initialization_time_seconds: float = 0.0
    main_loop_time_seconds: float = 0.0
    termination_reason: str = "evaluation_budget_complete"
    runner_random_state_after_initialization: object | None = None


@dataclass
class PrecomputedInitializationCandidate:
    """One fully evaluated shared-prefix candidate loaded from a bundle."""

    child: RuleSetChromosome
    fitness: AggregatedFitness
    n_requested_changes: int
    n_attempted_changes: int
    n_effective_changes: int
    attempted_operators: list[str]
    attempted_mutators: list[str]
    effective_mutators: list[str]
    changes: list[str]
    validation_metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class RandomBuildResult:
    """One shared-sampler proposal with requested/attempted/effective accounting."""

    child: RuleSetChromosome
    n_requested_changes: int
    n_attempted_changes: int
    n_effective_changes: int
    attempted_operators: list[str]
    attempted_mutators: list[str]
    effective_mutators: list[str]
    changes: list[str]


# ============================================================================
# Objectives (conservative set — the only objective mapping)
# ============================================================================

def _objectives(agg: AggregatedFitness) -> tuple[float, float, float]:
    """Map an AggregatedFitness to the archive's (f1, f2, f3), all maximised.

    f1 = Semgrep-finding reduction (``total_raw_reduction``; positive means fewer findings),
    f2 = textual similarity (mean SBERT versus authored originals; stored as
         ``rule_fidelity``; 1.0 = unchanged),
    f3 = −parsimony (fewer mutated rules is better; negated so maximizing works).
    """
    return agg.total_raw_reduction, agg.rule_fidelity, -float(agg.parsimony)


# ============================================================================
# Move helpers
# ============================================================================

def _unused_mutators(parent: RuleSetChromosome, rid: str, mutators: list[Mutator]) -> list[Mutator]:
    """Mutators not yet in ``rid``'s cumulative ``mutation_path``.

    Enforces "each mutator at most once per rule": re-applying the same operator
    to a rule just re-does the same class of transformation (a wasted eval), so a
    gene's reachable variants are the distinct-mutator subsets.
    """
    g = parent.genes.get(rid)
    used = set(g.mutation_path) if g else set()
    return [m for m in mutators if m.name not in used]


def _untried_mutators(
    parent: RuleSetChromosome,
    rid: str,
    mutators: list[Mutator],
) -> list[Mutator]:
    """Lineage-unused mutators not yet attempted on this exact parent/rule.

    Tried keys are atomic (``("mut", rule_id, mutator_name)``). This gives each
    parent a finite, interpretable neighbourhood.
    """
    return [
        m for m in _unused_mutators(parent, rid, mutators)
        if ("mut", rid, m.name) not in parent.tried
    ]


def _eligible_genes(
    parent: RuleSetChromosome,
    all_rule_ids: list[str],
    mutators: list[Mutator],
    max_depth: int,
) -> list[str]:
    """Rules that still admit a text-mutation move on ``parent``.

    A gene is eligible when its depth is below ``max_depth`` and it still has ≥1
    unused mutator. With the no-repeat rule the two limits coincide once every
    mutator has been applied, so a gene saturates naturally at ``len(mutators)``.
    """
    out: list[str] = []
    for rid in all_rule_ids:
        if parent.gene_depth(rid) >= max_depth:
            continue
        if not _unused_mutators(parent, rid, mutators):
            continue
        out.append(rid)
    return out


def _mutate_candidates(
    parent: RuleSetChromosome,
    all_rule_ids: list[str],
    mutators: list[Mutator],
    max_depth: int,
) -> tuple[list[str], list[str]]:
    """Split the genes a mutate move may act on by what happens to them.

    * ``stackable`` — depth < max_depth and ≥1 unused mutator → stack a mutation.
    * ``saturated`` — a *mutated* gene with no room left → revert to original.

    Together they span every rule (an unmutated rule is always stackable), so the
    mutate move's uniform pick can land on a saturated gene and ablate it rather
    than skipping it — a deterministic test of whether its stacked mutations still
    earn their place.
    """
    stackable = _eligible_genes(parent, all_rule_ids, mutators, max_depth)
    stack_set = set(stackable)
    saturated = [r for r in sorted(parent.mutated_rule_ids()) if r not in stack_set]
    return stackable, saturated


def _order_extreme(parent: RuleSetChromosome, op: str) -> int:
    """Priority that moves ONE rule to the front (max+1) or back (min-1).

    This is the whole rule-order operator: a single move sends one rule to an
    extreme of the global priority ranking and leaves every other rule's
    relative order untouched (a minimal, hill-climbable edit — the EA
    accumulates good bumps on a parent and any target permutation is reachable by
    composing several). It is the ONE seam a richer order operator would replace:
    a swap/insertion neighbourhood, or a whole-order shuffle, would swap this
    front/back choice for its own move set inside :func:`_available_local_moves`
    (EA) and :func:`build_random_chromosome` (sampler). Note a shuffle is a global
    non-incremental move (it discards the parent's order), so it suits a random
    sampler but not the incremental EA; keep the two arms' order operators
    identical to preserve the selection-only contrast.
    """
    vals = list(parent.order_priority.values()) or [0]
    return (max(vals) + 1) if op == "front" else (min(vals) - 1)


def _order_changes_any_prompt(parent, child, prompts_with_rules) -> bool:
    """True iff the reorder changes at least one prompt's rendered order."""
    for pwr in prompts_with_rules:
        if parent.render_order(pwr.rule_ids) != child.render_order(pwr.rule_ids):
            return True
    return False


def _is_render_identity(
    space: RuleSetSpace,
    base: RuleSetChromosome,
    child: RuleSetChromosome,
    prompts_with_rules: list[Any],
) -> bool:
    """True iff ``child`` renders every prompt exactly like ``base``.

    Covers both identity cases: no gene text differs AND no priority change
    re-ranks any prompt's rules. Identity attempts are recorded but retried at
    the same budget index because nothing new was evaluated.
    """
    if child is base or (child.cid and child.cid == base.cid):
        return True
    if child.genes != base.genes:
        return False
    return not _order_changes_any_prompt(base, child, prompts_with_rules)


# ============================================================================
# The shared random-chromosome sampler
# ============================================================================

def build_random_chromosome(
    space: RuleSetSpace,
    base: RuleSetChromosome,
    mutators: list[Mutator],
    rng: random.Random,
    *,
    max_changes: int,
    max_depth: int,
    order_move_prob: float = 0.0,
) -> RandomBuildResult:
    """Sample one random chromosome by stacking 1..``max_changes`` random changes
    on a copy of ``base`` (supervisor's random-search sampler, 2026-07-10).

    Per change: with probability ``order_move_prob`` bump a uniformly chosen
    rule's order priority (front/back); otherwise pick a rule uniformly among
    those with room (repeats allowed — a re-picked rule stacks, honouring the
    no-repeat-mutator rule and the per-rule ``max_depth`` cap) and apply exactly
    ONE mutator to the rule's CURRENT allele in the solution under construction.

    ``base`` is never modified. The returned child is stamped and its
    ``parent_id`` points at ``base``; when every change was a no-op the ``base``
    object itself is returned (callers detect identity via
    :func:`_is_render_identity`). Requested slots, actually attempted operators,
    and state-changing operations are recorded separately. A sampler-local
    ``(rule, mutator)`` set enforces no-repeat even when a mutator is a no-op or
    reverts the gene and therefore leaves no surviving mutation-path marker.
    """
    child = base
    n_requested = rng.randint(1, max(1, max_changes))
    n_attempted = 0
    n_effective = 0
    attempted_pairs: set[tuple[str, str]] = set()
    attempted_operators: list[str] = []
    attempted_mutators: list[str] = []
    effective_mutators: list[str] = []
    changes: list[str] = []
    for _ in range(n_requested):
        if order_move_prob > 0 and rng.random() < order_move_prob:
            rid = rng.choice(space.all_rule_ids)
            op = rng.choice(["front", "back"])
            n_attempted += 1
            attempted_operators.append(f"order:{op}:{rid}")
            next_child = child.with_priority(rid, _order_extreme(child, op))
            if next_child.order_priority != child.order_priority:
                n_effective += 1
            child = next_child
            changes.append(f"order {op}:{rid}")
            continue

        available_by_rule: dict[str, list[Mutator]] = {}
        for rid in space.all_rule_ids:
            if child.gene_depth(rid) >= max_depth:
                continue
            available = [
                m for m in _unused_mutators(child, rid, mutators)
                if (rid, m.name) not in attempted_pairs
            ]
            if available:
                available_by_rule[rid] = available
        candidates = list(available_by_rule)
        if not candidates:
            break  # requested slots can exceed the remaining no-repeat neighbourhood
        rid = rng.choice(candidates)
        m = rng.choice(available_by_rule[rid])
        attempted_pairs.add((rid, m.name))
        n_attempted += 1
        attempted_operators.append(f"mutator:{m.name}:{rid}")
        attempted_mutators.append(m.name)
        current = space.allele(child, rid)
        res = m.mutate(current)
        if res.mutated == current:
            changes.append(f"identity {m.name}:{rid}")
            continue
        if res.mutated == space.originals[rid]:
            # The mutator reproduced the original text — functionally a revert.
            if rid in child.genes:
                n_effective += 1
            child = child.with_reverted(rid)
            changes.append(f"reverted-to-original {m.name}:{rid}")
            continue
        child = child.with_gene(rid, res.mutated, m.name)
        n_effective += 1
        effective_mutators.append(m.name)
        changes.extend(res.changes)
    if child is base:
        final_child = base
    else:
        final_child = space.stamp(child)
        final_child.parent_id = base.cid or None
    return RandomBuildResult(
        child=final_child,
        n_requested_changes=n_requested,
        n_attempted_changes=n_attempted,
        n_effective_changes=n_effective,
        attempted_operators=attempted_operators,
        attempted_mutators=attempted_mutators,
        effective_mutators=effective_mutators,
        changes=changes,
    )


# Moves built by the shared sampler touch many rules at once, so a flat
# rule=/mutator=/depth= triple would misreport them as one chain on one rule.
_SAMPLE_MOVE_TYPES = frozenset(
    {
        "initialization_random",
        "injection_random",
        "origin_fallback_random",
        "sample",
    }
)


def _count_order_ops(attempted_operators: list[str]) -> int:
    """Order moves among a proposal's attempted operators (``order:<op>:<rid>``)."""
    return sum(1 for op in attempted_operators if op.startswith("order:"))


def _sample_detail(
    n_requested: int | None,
    n_effective: int | None,
    n_rules_changed: int,
    n_order_moves: int,
) -> str:
    """Log fragment for a sampler-built proposal, in sampler accounting terms."""
    return (
        f"random sample requested={n_requested} effective={n_effective} "
        f"rules_changed={n_rules_changed} order_moves={n_order_moves}"
    )


def _validate_genes(
    validate_move_fn: Callable[..., dict] | None,
    space: RuleSetSpace,
    base: RuleSetChromosome,
    child: RuleSetChromosome,
) -> dict[str, dict]:
    """Run the (observational) quality validator on every gene that differs
    between ``base`` and ``child``. Returns ``{rule_id: quality_meta}``."""
    if validate_move_fn is None:
        return {}
    out: dict[str, dict] = {}
    for rid in sorted(child.mutated_rule_ids() | base.mutated_rule_ids()):
        base_text = space.allele(base, rid)
        new_text = space.allele(child, rid)
        if new_text == base_text:
            continue
        g = child.genes.get(rid)
        chain = list(g.mutation_path) if g else []
        meta = validate_move_fn(rid, base_text, new_text, chain, [])
        if meta:  # {} when validation is disabled — keep the record field empty
            out[rid] = meta
    return out


# ============================================================================
# Archive-based EA with random initialisation + periodic random injection
# ============================================================================

def run_ea(
    *,
    space: RuleSetSpace,
    origin: RuleSetChromosome,
    prompts_with_rules: list[Any],
    mutators: list[Mutator],
    evaluate_chromosome_fn: EvaluateChromosomeFn,
    iteration_result_factory: Callable[..., "IterationResult"],
    main_loop_budget: int,
    archive_cap: int,
    max_depth: int,
    random_injection_every: int = 10,
    random_max_changes: int = 10,
    order_move_weight: float = 0.1,
    identity_retry_limit: int = _IDENTITY_RETRY_LIMIT,
    seed: int | None,
    log: Callable[[str], None],
    iter_record_fn: Callable[[dict], None] | None = None,
    archive_snapshot_fn: Callable[[int, dict], None] | None = None,
    save_move_fn: Callable[..., None] | None = None,
    validate_move_fn: Callable[..., dict] | None = None,
    snapshot_every: int = 20,
    should_stop_fn: Callable[[], bool] | None = None,
    precomputed_initialization: list[PrecomputedInitializationCandidate] | None = None,
    runner_random_state_after_initialization: object | None = None,
    load_precomputed_evidence_fn: Callable[[int], None] | None = None,
    restore_precomputed_state_fn: Callable[[], None] | None = None,
) -> ChromosomeRunResult:
    """Run the final EA: five shared initial samples, then ``main_loop_budget``.

    Initialisation evaluations are outside the main-loop budget but remain part
    of the total evaluation count. The origin is the baseline and reporting
    reference only; the five initial candidates create the Pareto front.

    Main-loop slots are periodic origin-based injections or local archive moves.
    A local slot retries at three levels without consuming an evaluation: another
    move on the same parent, another front parent, then an origin-based random
    sample when the whole front has no usable move. The archive is never cleared.
    """
    if main_loop_budget < 0:
        raise ValueError(f"main_loop_budget must be >= 0, got {main_loop_budget}")
    if identity_retry_limit < 1:
        raise ValueError(
            f"identity_retry_limit must be >= 1, got {identity_retry_limit}"
        )
    if precomputed_initialization is not None and len(precomputed_initialization) != (
        INITIALIZATION_SAMPLES
    ):
        raise ValueError(
            f"precomputed initialisation must contain {INITIALIZATION_SAMPLES} candidates"
        )
    if (
        precomputed_initialization is not None
        and runner_random_state_after_initialization is None
    ):
        raise ValueError("precomputed initialisation lacks the runner random state")

    rng = random.Random(seed)
    archive = ChromosomeArchive(
        origin,
        cap=archive_cap,
        rng=rng,
    )

    iterations: list["IterationResult"] = []
    mutator_stats: dict[str, dict[str, int]] = {
        m.name: {"attempts": 0, "archive_adds": 0, "archive_adds_f1": 0} for m in mutators
    }
    n_accepted = 0
    rate_limit_hit = False
    mutate_weight = max(0.0, 1.0 - order_move_weight)

    def _is_eligible(parent: RuleSetChromosome) -> bool:
        stackable, saturated, order_moves = _available_local_moves(
            parent, space, prompts_with_rules, mutators, max_depth, order_move_weight
        )
        return bool(stackable or saturated or order_moves)

    total_evaluated = 0
    main_loop_evaluated = 0
    attempt_count = 0
    last_completed = 0
    run_stopped = False
    termination_reason = "evaluation_budget_complete"
    initialization_started = time.perf_counter()
    initialization_finished: float | None = None
    main_loop_started: float | None = None
    captured_runner_state: object | None = None

    def _evaluate_proposal(
        *,
        phase: str,
        main_loop_iteration: int | None,
        parent: RuleSetChromosome,
        child: RuleSetChromosome,
        move_type: str,
        rule_id: str | None,
        chain_names: list[str],
        changes: list[str],
        n_changes: int | None,
        n_attempted_changes: int | None,
        n_effective_changes: int | None,
        attempted_operators: list[str],
        attempted_mutators: list[str],
        attempt_in_evaluation: int,
        elapsed_main_loop_seconds: float | None,
    ) -> bool:
        nonlocal total_evaluated, last_completed, n_accepted
        nonlocal rate_limit_hit, run_stopped, termination_reason

        evaluation_index = total_evaluated + 1
        space.stamp(child)
        gene_depth = child.gene_depth(rule_id) if rule_id else max(
            (child.gene_depth(rid) for rid in child.mutated_rule_ids()),
            default=0,
        )
        if move_type in _SAMPLE_MOVE_TYPES:
            move_detail = _sample_detail(
                n_changes,
                n_effective_changes,
                len(child.mutated_rule_ids()),
                _count_order_ops(attempted_operators),
            )
        else:
            move_detail = (
                f"local {move_type} rule={(rule_id or '-').replace('codeguard-', 'cg-')} "
                f"mutator={'+'.join(chain_names) or '-'} depth={gene_depth}"
            )
        header = (
            f"\n🧬 Evaluation {evaluation_index}/"
            f"{INITIALIZATION_SAMPLES + main_loop_budget} [{phase}] — {move_detail}"
        )
        if phase == "ea":
            header += (
                f" | parent={parent.cid or '-'} parent_f1={parent.f1:+.2f} "
                f"parent_nmut={len(parent.mutated_rule_ids())} front={len(archive)}"
            )
        log(header)

        validation_metadata = _validate_genes(validate_move_fn, space, parent, child)
        try:
            agg, _results, n_reused, n_rerun = evaluate_chromosome_fn(
                child, f"evaluation_{evaluation_index:04d}"
            )
        except WallTimeStop:
            log(
                f"\n⏱️  Pre-timeout during evaluation {evaluation_index} — "
                f"discarding in-flight; finalizing from {last_completed} completed evaluations."
            )
            run_stopped = True
            termination_reason = "wall_time_limit"
            return False
        except Exception as exc:  # noqa: BLE001
            if "rate_limit" in str(exc).lower() or "429" in str(exc) or "413" in str(exc):
                log(f"\n⚠️  Rate limit hit at evaluation {evaluation_index}: {exc}")
                rate_limit_hit = True
                run_stopped = True
                termination_reason = "rate_limit"
                return False
            raise

        child.f1, child.f2, child.f3 = _objectives(agg)
        child.fitness = agg
        child.evaluation_index = evaluation_index

        front_before_entries = list(archive.entries)
        front_before = {entry.cid for entry in front_before_entries}
        parent_f1 = parent.f1
        size_before = len(archive)
        accepted, reason = archive.try_add(
            child,
            evaluation_index=evaluation_index,
        )
        evicted = front_before - {entry.cid for entry in archive.entries}
        evicted_dominated = {
            entry.cid
            for entry in front_before_entries
            if entry.cid in evicted and dominates(child, entry)
        }
        evicted_overflow = evicted - evicted_dominated
        if accepted:
            n_accepted += 1
            credited = (
                chain_names
                if move_type in _SAMPLE_MOVE_TYPES
                else chain_names[-1:]
            )
            for name in credited:
                mutator_stats[name]["archive_adds"] += 1
                if child.f1 > parent_f1:
                    mutator_stats[name]["archive_adds_f1"] += 1
            log(
                f"   ✅ archive add: f1={child.f1:+.2f} f2={child.f2:.3f} "
                f"f3={child.f3:.3f} (front={len(archive)}/{archive.cap}, cid={child.cid})"
            )
            if evicted_dominated:
                log(f"   ⤷ evicted_dominated={', '.join(sorted(evicted_dominated))}")
            if evicted_overflow:
                log(f"   ⤷ evicted_overflow={', '.join(sorted(evicted_overflow))}")
            if len(archive) < size_before:
                log(f"   ↧ front shrank {size_before} → {len(archive)}")
        else:
            log(
                f"   ✗ rejected ({reason}): f1={child.f1:+.2f} "
                f"f2={child.f2:.3f} f3={child.f3:.3f} "
                f"[front={len(archive)}/{archive.cap}]"
            )

        if save_move_fn is not None:
            save_move_fn(
                evaluation_index=evaluation_index,
                child=child,
                space=space,
                move_type=move_type,
                rule_id=rule_id,
                chain_names=chain_names,
                changes=changes,
                validation_metadata=validation_metadata,
                accepted=accepted,
            )

        iterations.append(
            iteration_result_factory(
                iteration=total_evaluated,
                rule_text=f"[ea: {child.cid}]",
                aggregated_fitness=agg,
                individual_results=[],
                is_improvement=accepted,
                mutation_changes=changes,
                validation_metadata=validation_metadata,
            )
        )
        _emit_record(
            iter_record_fn,
            evaluation_index,
            "ea",
            parent,
            child=child,
            move_type=move_type,
            rule_id=rule_id,
            chain_names=chain_names,
            agg=agg,
            accepted=accepted,
            identity=False,
            gene_depth=gene_depth,
            n_reused=n_reused,
            n_rerun=n_rerun,
            eligible=len(space.all_rule_ids),
            parent_f1=parent_f1,
            validation_metadata=validation_metadata,
            phase=phase,
            n_changes=n_changes,
            attempt=attempt_count,
            attempt_in_iter=attempt_in_evaluation,
            budget_consumed=True,
            attempted_operators=attempted_operators,
            attempted_mutators=attempted_mutators,
            n_attempted_changes=n_attempted_changes,
            n_effective_changes=n_effective_changes,
            main_loop_iteration=main_loop_iteration,
            elapsed_main_loop_seconds=(
                time.perf_counter() - main_loop_started
                if main_loop_iteration is not None
                and main_loop_started is not None
                else elapsed_main_loop_seconds
            ),
        )
        total_evaluated += 1
        last_completed = total_evaluated
        if total_evaluated % snapshot_every == 0 and archive_snapshot_fn is not None:
            archive_snapshot_fn(total_evaluated, archive.snapshot())
        return True

    initialization_identity_retries = 0
    if precomputed_initialization is not None:
        for index, prepared in enumerate(precomputed_initialization, 1):
            child = deepcopy(prepared.child)
            space.stamp(child)
            if child.cid != prepared.child.cid:
                raise ValueError(
                    f"precomputed initialisation candidate {index} content hash differs"
                )
            child.f1, child.f2, child.f3 = _objectives(prepared.fitness)
            child.fitness = prepared.fitness
            child.evaluation_index = index
            accepted, _reason = archive.try_add(
                child,
                evaluation_index=index,
            )
            if accepted:
                n_accepted += 1
            for name in prepared.attempted_mutators:
                mutator_stats[name]["attempts"] += 1
            if accepted:
                for name in prepared.effective_mutators:
                    mutator_stats[name]["archive_adds"] += 1
                    if child.f1 > origin.f1:
                        mutator_stats[name]["archive_adds_f1"] += 1
            if load_precomputed_evidence_fn is not None:
                load_precomputed_evidence_fn(index)
            if save_move_fn is not None:
                save_move_fn(
                    evaluation_index=index,
                    child=child,
                    space=space,
                    move_type="initialization_random",
                    rule_id=None,
                    chain_names=prepared.effective_mutators,
                    changes=prepared.changes,
                    validation_metadata=prepared.validation_metadata,
                    accepted=accepted,
                )
            iterations.append(
                iteration_result_factory(
                    iteration=index - 1,
                    rule_text=f"[ea: {child.cid}]",
                    aggregated_fitness=prepared.fitness,
                    individual_results=[],
                    is_improvement=accepted,
                    mutation_changes=prepared.changes,
                    validation_metadata=prepared.validation_metadata,
                )
            )
            _emit_record(
                iter_record_fn,
                index,
                "ea",
                origin,
                child=child,
                move_type="initialization_random",
                rule_id=None,
                chain_names=prepared.effective_mutators,
                agg=prepared.fitness,
                accepted=accepted,
                identity=False,
                gene_depth=max(
                    (child.gene_depth(rid) for rid in child.mutated_rule_ids()),
                    default=0,
                ),
                n_reused=len(prompts_with_rules),
                n_rerun=0,
                eligible=len(space.all_rule_ids),
                phase="initialization",
                n_changes=prepared.n_requested_changes,
                attempt=index,
                attempt_in_iter=1,
                budget_consumed=True,
                attempted_operators=prepared.attempted_operators,
                attempted_mutators=prepared.attempted_mutators,
                n_attempted_changes=prepared.n_attempted_changes,
                n_effective_changes=prepared.n_effective_changes,
                main_loop_iteration=None,
                initialization_source="precomputed_bundle",
            )
        total_evaluated = INITIALIZATION_SAMPLES
        last_completed = INITIALIZATION_SAMPLES
        rng.setstate(runner_random_state_after_initialization)
        if restore_precomputed_state_fn is not None:
            restore_precomputed_state_fn()

    while total_evaluated < INITIALIZATION_SAMPLES:
        if should_stop_fn is not None and should_stop_fn():
            log(
                "\n⏹️  Graceful stop during initialisation — stopping after "
                f"{last_completed}/{INITIALIZATION_SAMPLES} initialisation evaluations"
            )
            termination_reason = "wall_time_limit"
            break
        attempt_count += 1
        attempt_in_evaluation = initialization_identity_retries + 1
        sample = build_random_chromosome(
            space,
            origin,
            mutators,
            rng,
            max_changes=random_max_changes,
            max_depth=max_depth,
            order_move_prob=order_move_weight,
        )
        for name in sample.attempted_mutators:
            mutator_stats[name]["attempts"] += 1
        if _is_render_identity(space, origin, sample.child, prompts_with_rules):
            initialization_identity_retries += 1
            _emit_record(
                iter_record_fn,
                total_evaluated + 1,
                "ea",
                origin,
                child=origin,
                move_type="initialization_random",
                rule_id=None,
                chain_names=sample.effective_mutators,
                agg=None,
                accepted=False,
                identity=True,
                gene_depth=0,
                n_reused=0,
                n_rerun=0,
                eligible=len(space.all_rule_ids),
                phase="initialization",
                n_changes=sample.n_requested_changes,
                attempt=attempt_count,
                attempt_in_iter=attempt_in_evaluation,
                budget_consumed=False,
                attempted_operators=sample.attempted_operators,
                attempted_mutators=sample.attempted_mutators,
                n_attempted_changes=sample.n_attempted_changes,
                n_effective_changes=sample.n_effective_changes,
                main_loop_iteration=None,
            )
            if initialization_identity_retries >= identity_retry_limit:
                raise IdentityRetryLimitExceeded(
                    "EA initialisation identity retry limit exceeded"
                )
            continue
        initialization_identity_retries = 0
        if not _evaluate_proposal(
            phase="initialization",
            main_loop_iteration=None,
            parent=origin,
            child=sample.child,
            move_type="initialization_random",
            rule_id=None,
            chain_names=sample.effective_mutators,
            changes=sample.changes,
            n_changes=sample.n_requested_changes,
            n_attempted_changes=sample.n_attempted_changes,
            n_effective_changes=sample.n_effective_changes,
            attempted_operators=sample.attempted_operators,
            attempted_mutators=sample.attempted_mutators,
            attempt_in_evaluation=attempt_in_evaluation,
            elapsed_main_loop_seconds=None,
        ):
            break

    captured_runner_state = rng.getstate()
    initialization_finished = time.perf_counter()

    if total_evaluated < INITIALIZATION_SAMPLES:
        best = archive.best()
        return ChromosomeRunResult(
            iterations=iterations,
            archive_snapshot=archive.snapshot(),
            best_chromosome=best,
            best_fitness=best.fitness,
            n_accepted=n_accepted,
            rate_limit_hit=rate_limit_hit,
            mutator_stats=mutator_stats,
            initialization_evaluations=total_evaluated,
            main_loop_evaluations=0,
            initialization_time_seconds=(
                initialization_finished - initialization_started
            ),
            main_loop_time_seconds=0.0,
            termination_reason=termination_reason,
            runner_random_state_after_initialization=captured_runner_state,
        )
    if not archive.entries:
        raise RuntimeError("EA initialisation completed without creating a Pareto front")

    main_loop_started = time.perf_counter()
    while main_loop_evaluated < main_loop_budget:
        if should_stop_fn is not None and should_stop_fn():
            log(
                f"\n⏹️  Graceful stop — completed {main_loop_evaluated}/"
                f"{main_loop_budget} main-loop evaluations"
            )
            termination_reason = "wall_time_limit"
            break

        main_loop_iteration = main_loop_evaluated + 1
        phase = (
            "injection"
            if random_injection_every > 0
            and main_loop_iteration % random_injection_every == 0
            else "ea"
        )
        excluded_parent_cids: set[str] = set()
        retry_parent: RuleSetChromosome | None = None
        attempt_in_evaluation = 0

        while True:
            attempt_count += 1
            attempt_in_evaluation += 1
            if attempt_in_evaluation > identity_retry_limit:
                raise IdentityRetryLimitExceeded(
                    f"EA proposal retry limit exceeded for main-loop evaluation "
                    f"{main_loop_iteration}"
                )

            if phase == "injection":
                parent = origin
                sample = build_random_chromosome(
                    space,
                    origin,
                    mutators,
                    rng,
                    max_changes=random_max_changes,
                    max_depth=max_depth,
                    order_move_prob=order_move_weight,
                )
                child = sample.child
                move_type = "injection_random"
                rule_id = None
                chain_names = sample.effective_mutators
                changes = sample.changes
                n_changes = sample.n_requested_changes
                n_attempted_changes = sample.n_attempted_changes
                n_effective_changes = sample.n_effective_changes
                attempted_operators = sample.attempted_operators
                attempted_mutators = sample.attempted_mutators
                is_identity = _is_render_identity(
                    space, origin, child, prompts_with_rules
                )
            else:
                parent_entry = (
                    retry_parent
                    if retry_parent is not None and _is_eligible(retry_parent)
                    else archive.sample_parent(
                        _is_eligible,
                        exclude_cids=excluded_parent_cids,
                    )
                )
                retry_parent = None
                if parent_entry is None:
                    phase = "origin_fallback"
                    parent = origin
                    sample = build_random_chromosome(
                        space,
                        origin,
                        mutators,
                        rng,
                        max_changes=random_max_changes,
                        max_depth=max_depth,
                        order_move_prob=order_move_weight,
                    )
                    child = sample.child
                    move_type = "origin_fallback_random"
                    rule_id = None
                    chain_names = sample.effective_mutators
                    changes = sample.changes
                    n_changes = sample.n_requested_changes
                    n_attempted_changes = sample.n_attempted_changes
                    n_effective_changes = sample.n_effective_changes
                    attempted_operators = sample.attempted_operators
                    attempted_mutators = sample.attempted_mutators
                    is_identity = _is_render_identity(
                        space, origin, child, prompts_with_rules
                    )
                else:
                    parent = parent_entry
                    parent_value = deepcopy(parent_entry)
                    move = _choose_and_build_move(
                        parent_value,
                        space,
                        prompts_with_rules,
                        mutators,
                        rng,
                        max_depth,
                        mutate_weight,
                        order_move_weight,
                    )
                    if move is None:
                        excluded_parent_cids.add(parent_entry.cid)
                        continue
                    (
                        child,
                        move_key,
                        move_type,
                        rule_id,
                        chain_names,
                        changes,
                        is_identity,
                    ) = move
                    archive.mark_tried(parent_entry, move_key)
                    attempted_mutators = list(chain_names)
                    attempted_operators = (
                        [f"mutator:{chain_names[0]}:{rule_id}"]
                        if move_type == "mutate"
                        else [move_type]
                    )
                    n_attempted_changes = 1
                    n_effective_changes = 0 if is_identity else 1
                    n_changes = 1
                    if is_identity:
                        retry_parent = parent_entry

            for name in attempted_mutators:
                mutator_stats[name]["attempts"] += 1

            if is_identity:
                _emit_record(
                    iter_record_fn,
                    total_evaluated + 1,
                    "ea",
                    parent,
                    child=parent,
                    move_type=move_type,
                    rule_id=rule_id,
                    chain_names=chain_names,
                    agg=None,
                    accepted=False,
                    identity=True,
                    gene_depth=(
                        parent.gene_depth(rule_id)
                        if rule_id
                        else max(
                            (
                                parent.gene_depth(rid)
                                for rid in parent.mutated_rule_ids()
                            ),
                            default=0,
                        )
                    ),
                    n_reused=0,
                    n_rerun=0,
                    eligible=len(space.all_rule_ids),
                    phase=phase,
                    n_changes=n_changes,
                    attempt=attempt_count,
                    attempt_in_iter=attempt_in_evaluation,
                    budget_consumed=False,
                    attempted_operators=attempted_operators,
                    attempted_mutators=attempted_mutators,
                    n_attempted_changes=n_attempted_changes,
                    n_effective_changes=n_effective_changes,
                    main_loop_iteration=main_loop_iteration,
                    elapsed_main_loop_seconds=time.perf_counter() - main_loop_started,
                )
                continue

            completed = _evaluate_proposal(
                phase=phase,
                main_loop_iteration=main_loop_iteration,
                parent=parent,
                child=child,
                move_type=move_type,
                rule_id=rule_id,
                chain_names=chain_names,
                changes=changes,
                n_changes=n_changes,
                n_attempted_changes=n_attempted_changes,
                n_effective_changes=n_effective_changes,
                attempted_operators=attempted_operators,
                attempted_mutators=attempted_mutators,
                attempt_in_evaluation=attempt_in_evaluation,
                elapsed_main_loop_seconds=time.perf_counter() - main_loop_started,
            )
            if completed:
                main_loop_evaluated += 1
            break
        if run_stopped:
            break

    if archive_snapshot_fn is not None and last_completed > 0:
        archive_snapshot_fn(last_completed, archive.snapshot())

    best = archive.best()
    _log_ea_summary(log, archive, mutator_stats, best)
    return ChromosomeRunResult(
        iterations=iterations,
        archive_snapshot=archive.snapshot(),
        best_chromosome=best,
        best_fitness=best.fitness,
        n_accepted=n_accepted,
        rate_limit_hit=rate_limit_hit,
        mutator_stats=mutator_stats,
        initialization_evaluations=min(total_evaluated, INITIALIZATION_SAMPLES),
        main_loop_evaluations=main_loop_evaluated,
        initialization_time_seconds=(
            (initialization_finished or time.perf_counter()) - initialization_started
        ),
        main_loop_time_seconds=(
            time.perf_counter() - main_loop_started
            if main_loop_started is not None
            else 0.0
        ),
        termination_reason=termination_reason,
        runner_random_state_after_initialization=captured_runner_state,
    )


def _choose_and_build_move(
    parent: RuleSetChromosome,
    space: RuleSetSpace,
    prompts_with_rules: list[Any],
    mutators: list[Mutator],
    rng: random.Random,
    max_depth: int,
    mutate_weight: float,
    order_weight: float,
):
    """Pick a local move type by weight and build the child chromosome.

    Returns ``(child, move_key, move_type, rule_id, chain_names, changes,
    is_identity)`` or ``None`` when no untried move is realizable. The key is
    recorded in ``parent.tried`` regardless of outcome.
    """
    stackable, saturated, order_moves = _available_local_moves(
        parent, space, prompts_with_rules, mutators, max_depth, order_weight
    )
    move_type = _weighted_move_type(
        rng,
        can_mutate=bool(stackable or saturated),
        can_order=bool(order_moves),
        mutate_weight=mutate_weight,
        order_weight=order_weight,
    )
    if move_type is None:
        return None

    if move_type == "order":
        move_key, child, rid, op = rng.choice(order_moves)
        return child, move_key, "order", rid, [], [f"{op}:{rid}"], False

    stackable_set = set(stackable)
    saturated_set = set(saturated)
    for rid in rng.sample(space.all_rule_ids, len(space.all_rule_ids)):
        if rid in saturated_set:
            child = parent.with_reverted(rid)
            return (
                child,
                ("rev", rid),
                "revert",
                rid,
                [],
                [f"reverted {rid} (saturated)"],
                False,
            )
        if rid not in stackable_set:
            continue
        available = _untried_mutators(parent, rid, mutators)
        if not available:
            continue
        chosen = rng.choice(available)
        result = chosen.mutate(space.allele(parent, rid))
        is_identity = result.mutated == space.allele(parent, rid)
        child = (
            parent
            if is_identity
            else parent.with_gene(rid, result.mutated, chosen.name)
        )
        return (
            child,
            ("mut", rid, chosen.name),
            "mutate",
            rid,
            [chosen.name],
            list(result.changes),
            is_identity,
        )
    return None


def _available_local_moves(
    parent: RuleSetChromosome,
    space: RuleSetSpace,
    prompts_with_rules: list[Any],
    mutators: list[Mutator],
    max_depth: int,
    order_weight: float,
) -> tuple[list[str], list[str], list[tuple[tuple, RuleSetChromosome, str, str]]]:
    """Return untried text/revert rules and effective order moves.

    Order changes that do not alter any prompt rendering are excluded before
    sampling. Text mutators are tracked atomically per parent/rule, so rejected
    or identity-producing operators are not immediately repeated on that parent.
    """
    stackable: list[str] = []
    saturated: list[str] = []
    for rid in space.all_rule_ids:
        lineage_saturated = (
            parent.gene_depth(rid) >= max_depth
            or not _unused_mutators(parent, rid, mutators)
        )
        if lineage_saturated:
            if rid in parent.genes and ("rev", rid) not in parent.tried:
                saturated.append(rid)
            continue
        if _untried_mutators(parent, rid, mutators):
            stackable.append(rid)

    order_moves: list[tuple[tuple, RuleSetChromosome, str, str]] = []
    if order_weight > 0:
        for rid in space.all_rule_ids:
            for op in ("front", "back"):
                key = ("order", rid, op)
                if key in parent.tried:
                    continue
                child = parent.with_priority(rid, _order_extreme(parent, op))
                if _order_changes_any_prompt(parent, child, prompts_with_rules):
                    order_moves.append((key, child, rid, op))
    return stackable, saturated, order_moves


def _weighted_move_type(
    rng,
    *,
    can_mutate: bool,
    can_order: bool,
    mutate_weight: float,
    order_weight: float,
):
    """Choose an available move type by weight; fall back to any available one."""
    options = []
    if can_mutate:
        options.append(("mutate", mutate_weight))
    if can_order:
        options.append(("order", order_weight))
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


# ============================================================================
# Random search (i.i.d. baseline — every iteration independent of all others)
# ============================================================================

def run_random_search(
    *,
    space: RuleSetSpace,
    origin: RuleSetChromosome,
    prompts_with_rules: list[Any],
    mutators: list[Mutator],
    evaluate_chromosome_fn: EvaluateChromosomeFn,
    iteration_result_factory: Callable[..., "IterationResult"],
    main_loop_budget: int,
    max_changes: int,
    max_depth: int,
    order_move_prob: float = 0.1,
    identity_retry_limit: int = _IDENTITY_RETRY_LIMIT,
    seed: int | None,
    log: Callable[[str], None],
    iter_record_fn: Callable[[dict], None] | None = None,
    save_move_fn: Callable[..., None] | None = None,
    validate_move_fn: Callable[..., dict] | None = None,
    should_stop_fn: Callable[[], bool] | None = None,
    precomputed_initialization: list[PrecomputedInitializationCandidate] | None = None,
    runner_random_state_after_initialization: object | None = None,
    load_precomputed_evidence_fn: Callable[[int], None] | None = None,
    restore_precomputed_state_fn: Callable[[], None] | None = None,
) -> ChromosomeRunResult:
    """Run random search with the same five-candidate prefix as the EA.

    The five initialisation evaluations are outside ``main_loop_budget`` but
    remain part of the total evaluation count. Every candidate, including the
    subsequent main-loop candidates, is an independent origin-based sample.
    """
    if main_loop_budget < 0:
        raise ValueError(f"main_loop_budget must be >= 0, got {main_loop_budget}")
    if identity_retry_limit < 1:
        raise ValueError(
            f"identity_retry_limit must be >= 1, got {identity_retry_limit}"
        )
    if precomputed_initialization is not None and len(precomputed_initialization) != (
        INITIALIZATION_SAMPLES
    ):
        raise ValueError(
            f"precomputed initialisation must contain {INITIALIZATION_SAMPLES} candidates"
        )
    if (
        precomputed_initialization is not None
        and runner_random_state_after_initialization is None
    ):
        raise ValueError("precomputed initialisation lacks the runner random state")
    rng = random.Random(seed)

    iterations: list["IterationResult"] = []
    mutator_stats: dict[str, dict[str, int]] = {
        m.name: {"applications": 0, "applications_f1_advancing": 0} for m in mutators
    }
    best = origin
    best_fitness = origin.fitness
    rate_limit_hit = False
    termination_reason = "evaluation_budget_complete"

    evaluated_count = 0
    attempt_count = 0
    identity_retries = 0
    last_completed = 0
    initialization_started = time.perf_counter()
    initialization_finished: float | None = None
    main_loop_started: float | None = None
    total_evaluation_budget = INITIALIZATION_SAMPLES + main_loop_budget
    captured_runner_state: object | None = None

    if precomputed_initialization is not None:
        for index, prepared in enumerate(precomputed_initialization, 1):
            child = deepcopy(prepared.child)
            space.stamp(child)
            if child.cid != prepared.child.cid:
                raise ValueError(
                    f"precomputed initialisation candidate {index} content hash differs"
                )
            child.f1, child.f2, child.f3 = _objectives(prepared.fitness)
            child.fitness = prepared.fitness
            child.evaluation_index = index
            f1_advance = child.f1 > 0.0
            for name in prepared.attempted_mutators:
                mutator_stats[name]["applications"] += 1
                if f1_advance:
                    mutator_stats[name]["applications_f1_advancing"] += 1
            if (
                child.f1 > best.f1
                or (
                    abs(child.f1 - best.f1) <= 1e-9
                    and (
                        child.invalid_prompt_count,
                        -(child.f2 + child.f3),
                    )
                    < (
                        best.invalid_prompt_count,
                        -(best.f2 + best.f3),
                    )
                )
            ):
                best, best_fitness = child, prepared.fitness
            if load_precomputed_evidence_fn is not None:
                load_precomputed_evidence_fn(index)
            if save_move_fn is not None:
                save_move_fn(
                    evaluation_index=index,
                    child=child,
                    space=space,
                    move_type="initialization_random",
                    rule_id=None,
                    chain_names=prepared.effective_mutators,
                    changes=prepared.changes,
                    validation_metadata=prepared.validation_metadata,
                    accepted=True,
                )
            iterations.append(
                iteration_result_factory(
                    iteration=index - 1,
                    rule_text=f"[random: {child.cid}]",
                    aggregated_fitness=prepared.fitness,
                    individual_results=[],
                    is_improvement=True,
                    mutation_changes=prepared.changes,
                    validation_metadata=prepared.validation_metadata,
                )
            )
            _emit_record(
                iter_record_fn,
                index,
                "random_search",
                origin,
                child=child,
                move_type="initialization_random",
                rule_id=None,
                chain_names=prepared.effective_mutators,
                agg=prepared.fitness,
                accepted=True,
                identity=False,
                gene_depth=max(
                    (child.gene_depth(rid) for rid in child.mutated_rule_ids()),
                    default=0,
                ),
                n_reused=len(prompts_with_rules),
                n_rerun=0,
                phase="initialization",
                n_changes=prepared.n_requested_changes,
                attempt=index,
                attempt_in_iter=1,
                budget_consumed=True,
                attempted_operators=prepared.attempted_operators,
                attempted_mutators=prepared.attempted_mutators,
                n_attempted_changes=prepared.n_attempted_changes,
                n_effective_changes=prepared.n_effective_changes,
                main_loop_iteration=None,
                initialization_source="precomputed_bundle",
            )
        evaluated_count = INITIALIZATION_SAMPLES
        last_completed = INITIALIZATION_SAMPLES
        initialization_finished = time.perf_counter()
        main_loop_started = initialization_finished
        rng.setstate(runner_random_state_after_initialization)
        if restore_precomputed_state_fn is not None:
            restore_precomputed_state_fn()
        captured_runner_state = rng.getstate()

    while evaluated_count < total_evaluation_budget:
        if should_stop_fn is not None and should_stop_fn():
            log(
                "\n⏹️  Graceful stop (SLURM pre-timeout) — stopping after "
                f"{last_completed}/{total_evaluation_budget} evaluations"
            )
            termination_reason = "wall_time_limit"
            break

        evaluation_index = evaluated_count + 1
        phase = (
            "initialization"
            if evaluation_index <= INITIALIZATION_SAMPLES
            else "random"
        )
        main_loop_iteration = (
            None
            if phase == "initialization"
            else evaluation_index - INITIALIZATION_SAMPLES
        )
        if phase == "random" and main_loop_started is None:
            initialization_finished = time.perf_counter()
            main_loop_started = initialization_finished
        attempt_count += 1
        attempt_in_iter = identity_retries + 1

        sample = build_random_chromosome(
            space, origin, mutators, rng,
            max_changes=max_changes, max_depth=max_depth,
            order_move_prob=order_move_prob,
        )
        child = sample.child
        n_changes = sample.n_requested_changes
        chain_names = sample.effective_mutators
        changes = sample.changes

        if _is_render_identity(space, origin, child, prompts_with_rules):
            identity_retries += 1
            # effective>0 with an identity render means the draws cancelled out
            # (e.g. a mutator reproduced the original text), not that all were no-ops.
            log(
                f"\n⏭️  Evaluation {evaluation_index}/{total_evaluation_budget} "
                f"[{phase}] — identity: "
                + _sample_detail(n_changes, sample.n_effective_changes,
                                 len(child.mutated_rule_ids()),
                                 _count_order_ops(sample.attempted_operators))
                + f" attempt={attempt_count} — renders as the origin; no evaluation; "
                  f"retry {identity_retries}/{identity_retry_limit}")
            for name in sample.attempted_mutators:
                mutator_stats[name]["applications"] += 1
            _emit_record(iter_record_fn, evaluation_index, "random_search",
                         parent=origin, child=origin,
                         move_type="sample", rule_id=None, chain_names=chain_names, agg=None,
                         accepted=False, identity=True, gene_depth=0,
                         n_reused=0, n_rerun=0, phase=phase, n_changes=n_changes,
                         attempt=attempt_count, attempt_in_iter=attempt_in_iter,
                         budget_consumed=False,
                         attempted_operators=sample.attempted_operators,
                         attempted_mutators=sample.attempted_mutators,
                         n_attempted_changes=sample.n_attempted_changes,
                         n_effective_changes=sample.n_effective_changes,
                         main_loop_iteration=main_loop_iteration,
                         elapsed_main_loop_seconds=(
                             time.perf_counter() - main_loop_started
                             if main_loop_started is not None
                             else None
                         ))
            if identity_retries >= identity_retry_limit:
                raise IdentityRetryLimitExceeded(
                    "random-search identity retry limit exceeded for evaluation "
                    f"{evaluation_index} after {identity_retries} attempts"
                )
            continue

        identity_retries = 0
        # ---- header → validation → evaluate ---------------------------------
        log(f"\n🎲 Evaluation {evaluation_index}/{total_evaluation_budget} [{phase}] — "
            + _sample_detail(n_changes, sample.n_effective_changes,
                             len(child.mutated_rule_ids()),
                             _count_order_ops(sample.attempted_operators)))

        # Observational quality validation of every changed gene.
        validation_metadata: dict = _validate_genes(validate_move_fn, space, origin, child)
        try:
            agg, _results, n_reused, n_rerun = evaluate_chromosome_fn(
                child, f"evaluation_{evaluation_index:04d}"
            )
        except WallTimeStop:
            log(
                f"\n⏹️  Pre-timeout mid-eval — stopping after "
                f"{last_completed} evaluations"
            )
            termination_reason = "wall_time_limit"
            break
        except Exception as e:  # noqa: BLE001
            if "rate_limit" in str(e).lower() or "429" in str(e) or "413" in str(e):
                log(f"\n⚠️  Rate limit hit at random evaluation {evaluation_index}: {e}")
                rate_limit_hit = True
                termination_reason = "rate_limit"
                break
            raise

        child.f1, child.f2, child.f3 = _objectives(agg)
        child.fitness = agg
        child.evaluation_index = evaluation_index

        f1_advance = child.f1 > 0.0
        for name in sample.attempted_mutators:
            mutator_stats[name]["applications"] += 1
            if f1_advance:
                mutator_stats[name]["applications_f1_advancing"] += 1

        if (
            child.f1 > best.f1
            or (
                abs(child.f1 - best.f1) <= 1e-9
                and (
                    child.invalid_prompt_count,
                    -(child.f2 + child.f3),
                )
                < (
                    best.invalid_prompt_count,
                    -(best.f2 + best.f3),
                )
            )
        ):
            best, best_fitness = child, agg

        if save_move_fn is not None:
            save_move_fn(evaluation_index=evaluation_index, child=child, space=space,
                         move_type="sample",
                         rule_id=None, chain_names=chain_names, changes=changes,
                         validation_metadata=validation_metadata, accepted=True)

        iterations.append(iteration_result_factory(
            iteration=evaluated_count, rule_text=f"[random: {child.cid}]", aggregated_fitness=agg,
            individual_results=[], is_improvement=True, mutation_changes=changes,
            validation_metadata=validation_metadata,
        ))
        _emit_record(iter_record_fn, evaluation_index, "random_search",
                     parent=origin, child=child,
                     move_type="sample", rule_id=None, chain_names=chain_names, agg=agg,
                     accepted=True, identity=False,
                     gene_depth=max((child.gene_depth(r) for r in child.mutated_rule_ids()),
                                    default=0),
                     n_reused=n_reused, n_rerun=n_rerun, validation_metadata=validation_metadata,
                     phase=phase, n_changes=n_changes, attempt=attempt_count,
                     attempt_in_iter=attempt_in_iter, budget_consumed=True,
                     attempted_operators=sample.attempted_operators,
                     attempted_mutators=sample.attempted_mutators,
                     n_attempted_changes=sample.n_attempted_changes,
                     n_effective_changes=sample.n_effective_changes,
                     main_loop_iteration=main_loop_iteration,
                     elapsed_main_loop_seconds=(
                         time.perf_counter() - main_loop_started
                         if main_loop_started is not None
                         else None
                     ))
        evaluated_count += 1
        last_completed = evaluated_count
        if (
            evaluated_count == INITIALIZATION_SAMPLES
            and initialization_finished is None
        ):
            initialization_finished = time.perf_counter()
            captured_runner_state = rng.getstate()

    # best includes the origin floor (f1 >= 0): if no sample beat baseline,
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
        initialization_evaluations=min(evaluated_count, INITIALIZATION_SAMPLES),
        main_loop_evaluations=max(0, evaluated_count - INITIALIZATION_SAMPLES),
        initialization_time_seconds=(
            (initialization_finished or time.perf_counter()) - initialization_started
        ),
        main_loop_time_seconds=(
            time.perf_counter() - main_loop_started
            if main_loop_started is not None
            else 0.0
        ),
        termination_reason=termination_reason,
        runner_random_state_after_initialization=captured_runner_state,
    )


# ============================================================================
# Records + logging
# ============================================================================

def _emit_record(
    iter_record_fn, iteration, strategy, parent, child, move_type, rule_id, chain_names,
    agg, accepted, identity, gene_depth, n_reused, n_rerun,
    eligible: int = 0, parent_f1: float | None = None,
    validation_metadata: dict | None = None, phase: str = "ea",
    n_changes: int | None = None,
    attempt: int | None = None,
    attempt_in_iter: int = 1,
    budget_consumed: bool = True,
    attempted_operators: list[str] | None = None,
    attempted_mutators: list[str] | None = None,
    n_attempted_changes: int | None = None,
    n_effective_changes: int | None = None,
    main_loop_iteration: int | None = None,
    elapsed_main_loop_seconds: float | None = None,
    initialization_source: str | None = None,
):
    if iter_record_fn is None:
        return
    if agg is not None:
        f1, f2, f3 = _objectives(agg)
        fidelity = agg.rule_fidelity
        parsimony = agg.parsimony
    else:
        f1 = f2 = f3 = None
        fidelity = parsimony = None
    p_f1 = parent_f1 if parent_f1 is not None else (parent.f1 if parent is not None else None)
    rec = {
        "evaluation_index": iteration,
        "main_loop_iteration": main_loop_iteration,
        "elapsed_main_loop_seconds": elapsed_main_loop_seconds,
        "attempt_index": attempt if attempt is not None else iteration,
        "attempt_in_evaluation": attempt_in_iter,
        "evaluation_consumed": budget_consumed,
        "timestamp": _utcnow(),
        "strategy": strategy,
        "phase": phase,
        "initialization_source": initialization_source,
        "chromosome_id": child.cid if child is not None else None,
        "parent_chromosome_id": (parent.cid if parent is not None else None),
        "move_type": move_type,
        "rule_id": rule_id,
        "mutation_chain": list(chain_names),
        "chain_length": len(chain_names),
        "n_changes": n_changes,
        "n_requested_changes": n_changes,
        "n_attempted_changes": n_attempted_changes,
        "n_effective_changes": n_effective_changes,
        "attempted_operators": list(attempted_operators or []),
        "attempted_mutators": list(attempted_mutators or []),
        "mutation_identity": identity,
        "mutated_rule_ids": sorted(child.mutated_rule_ids()) if child is not None else [],
        "priority_rule_ids": sorted(child.order_priority) if child is not None else [],
        "priority_offset_count": len(child.order_priority) if child is not None else 0,
        "gene_depth": gene_depth,
        "objective_mode": "conservative",
        "f1": f1, "f2": f2, "f3": f3,
        "security_neutral": bool(f1 is not None and abs(f1) <= 1e-9),
        "rule_fidelity": fidelity,
        "parsimony": parsimony,
        "total_fitness": agg.total_fitness if agg is not None else None,
        "mean_fitness": agg.mean_fitness if agg is not None else None,
        "max_fitness": agg.max_fitness if agg is not None else None,
        "num_prompts": agg.num_prompts if agg is not None else None,
        "num_vulnerable": agg.num_vulnerable if agg is not None else None,
        "num_valid_prompts": agg.num_valid_prompts if agg is not None else None,
        "num_prompts_affected": (
            agg.num_prompts_affected if agg is not None else None
        ),
        "num_invalid_prompts": agg.num_invalid_prompts if agg is not None else None,
        "failure_counts": agg.failure_counts if agg is not None else {},
        "total_raw_findings": agg.total_raw_count if agg is not None else None,
        "total_weighted_score": agg.total_weighted_score if agg is not None else None,
        "weighted_reduction": agg.total_weighted_reduction if agg is not None else None,
        "f1_advance": bool(accepted and f1 is not None and p_f1 is not None and f1 > p_f1),
        "accepted": accepted,
        "n_prompts_rerun": n_rerun,
        "n_prompts_reused": n_reused,
        "validation_metadata": validation_metadata or {},
        "selection_meta": (
            {} if strategy == "random_search" else {
                "parent_f1": p_f1,
                "n_rules_in_space": eligible,
            }
        ),
    }
    iter_record_fn(rec)


def _log_ea_summary(log, archive, mutator_stats, best):
    sep = "═" * 80
    log(f"\n{sep}\n📊  EA chromosome-archive summary\n{sep}")
    log(f"   front_size={len(archive)}  inserts={archive.n_inserts}  "
        f"rejected={archive.n_rejected} (dup={archive.n_dup_rejected})")
    log(f"   best: f1={best.f1:+.2f} f2={best.f2:.3f} f3={best.f3:.3f} "
        f"mutated={sorted(best.mutated_rule_ids())} cid={best.cid}")
    log("\n🧬  Mutator effectiveness (local moves: last-mutator credit; "
        "sampler children: shared credit):")
    for name, s in sorted(mutator_stats.items(), key=lambda kv: -kv[1]["archive_adds"]):
        att, ins = s["attempts"], s["archive_adds"]
        rate = (100.0 * ins / att) if att else 0.0
        log(f"   {name:<26} attempts={att:>4} adds={ins:>4} ({rate:4.1f}%)")
    log(sep + "\n")


def _log_random_summary(log, mutator_stats, best):
    sep = "═" * 80
    log(f"\n{sep}\n📊  Random-search summary\n{sep}")
    log(f"   best: f1={best.f1:+.2f} f2={best.f2:.3f} f3={best.f3:.3f} "
        f"mutated={sorted(best.mutated_rule_ids())} cid={best.cid}")
    log("\n🎲  Mutator applications (whole-sample credit):")
    for name, s in sorted(mutator_stats.items(), key=lambda kv: -kv[1]["applications"]):
        apps, adv = s["applications"], s["applications_f1_advancing"]
        rate = (100.0 * adv / apps) if apps else 0.0
        log(f"   {name:<26} apps={apps:>4} f1_adv={adv:>4} ({rate:4.1f}%)")
    log(sep + "\n")
