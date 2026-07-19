"""
Search algorithms over full rule-set chromosomes: a (1+1) EA with random
initialization + periodic random injection, and an i.i.d. random-search baseline.

The unit of search is the whole rule set (a :class:`RuleSetChromosome`): rule-text
alleles + a global rule-ordering policy. Both runners share one evaluation seam —
``evaluate_chromosome_fn(chromosome, iter_id) -> (AggregatedFitness, results,
n_reused, n_rerun)`` — a closure provided by the engine that renders every prompt
from the chromosome and scores the whole rule set.

Objectives — the "conservative" set (adopted 2026-07-10), all MAXIMIZED by the
Pareto archive:
    f1 = vulnerability reduction (severity-weighted Semgrep delta; sign set by
         the engine's ``objective_direction``)
    f2 = rule fidelity (mean SBERT similarity of mutated rules vs originals)
    f3 = −parsimony (negated count of mutated rules — prefer the smaller edit)

Top-level entry points
----------------------
* :func:`run_ea` — (1+1) EA over one :class:`ChromosomeArchive`. It starts with
  ``init_random_samples`` independent random chromosomes offered to the archive
  and, every ``random_injection_every``-th iteration thereafter, injects one fresh
  random chromosome built from the origin. All other iterations take a small local
  step on an archive parent.
* :func:`run_random_search` — every iteration is an INDEPENDENT random
  chromosome built from the origin; best-of-budget (no carry-forward, no archive).
* :func:`build_random_chromosome` — the one shared sampler behind random search,
  EA initialization, and EA injection, so "initialized exactly like random"
  holds by construction.
"""

from __future__ import annotations

import random
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
    restart_reason_counts: dict[str, int] = field(default_factory=dict)


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
    """Map an AggregatedFitness to the archive's (f1, f2, f3), all maximized.

    f1 = vulnerability reduction (``total_semgrep_delta``; the engine negates the
    raw delta under ``objective_direction="minimize"`` so higher is always safer),
    f2 = rule fidelity (mean SBERT of mutated rules vs originals; 1.0 = unchanged),
    f3 = −parsimony (fewer mutated rules is better; negated so maximizing works).
    """
    return agg.total_semgrep_delta, agg.rule_fidelity, -float(agg.parsimony)


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

    Tried keys are atomic (``("mut", rule_id, mutator_name)``), including when
    an ablation applies a multi-mutator chain. This gives the tried/restart
    mechanism a finite, interpretable neighbourhood without enumerating every
    possible ordering of mutation chains.
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
        child = child.with_gene_chain(rid, res.mutated, [m.name])
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


# Moves built by the shared sampler: they touch many rules at once, so a flat
# rule=/mutator=/depth= triple would misreport them as one chain on one rule.
# ``restart_random`` is a stagnation-restart reseed and ``no_parent_fallback`` is
# the empty-front safe net — both use the same origin-based sampler as
# init/injection, so they log with the same accounting.
_SAMPLE_MOVE_TYPES = frozenset(
    {"init_random", "injection_random", "random_builder",
     "restart_random", "no_parent_fallback"}
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
# (1+1) EA with random initialization + periodic random injection
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
    ea_move: str = "local",
    init_random_samples: int = 10,
    random_injection_every: int = 10,
    random_max_changes: int = 10,
    order_move_weight: float = 0.1,
    ea_origin_parent: bool = True,
    identity_retry_limit: int = _IDENTITY_RETRY_LIMIT,
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

    Iteration phases consume one shared **candidate-evaluation** budget; identity
    proposals are recorded attempts and retried at the same budget index. Records
    carry a ``phase`` marker so analysis can split them:

    * ``init`` — the first ``init_random_samples`` iterations sample independent
      random chromosomes from the ORIGIN via :func:`build_random_chromosome`
      (exactly the random-search sampler) and offer each to the archive.
      Population-style seeding: the later 1+1 loop starts from their Pareto front.
    * ``injection`` — after init, every ``random_injection_every``-th iteration
      injects one more origin-based random chromosome (0 disables). Diversity
      maintenance: the archive is not wiped for this; dominance decides.
    * ``ea`` — pick a parent from the archive (the origin is also sampleable when
      ``ea_origin_parent`` is on, so a minimal parsimony-1 lineage can always be
      seeded), take a move, evaluate the WHOLE chromosome, offer it by Pareto
      dominance.
    * ``restart`` — triggered when an "ea"-phase attempt hits ``restart_h``
      consecutive rejections (stagnation): the front is wiped
      (:meth:`ChromosomeArchive.restart` with ``wipe_front=True``) and the next
      ``init_random_samples`` iterations reseed it exactly like ``init``, one
      fresh origin-based random sample per iteration (ARIEL-style
      restart-on-stagnation), before normal ``injection``/``ea`` cadence resumes.

    The ``ea``-phase move depends on ``ea_move``:

    * ``"local"`` (default) — the (1+1) step: mutate ONE gene by stacking a
      1..``ea_n_mutations`` chain of distinct unused mutators on its current
      allele (default chain length 1 — the canonical small step); a saturated
      gene reverts to original instead (ablation of its stack); with weight
      ``order_move_weight`` the move is a rule-order bump instead.
    * ``"random_builder"`` — ablation arm: the move applies the random sampler
      to the ARCHIVE PARENT, so selection is the only difference vs random
      search. Not the main design; kept for the supervisor-requested ablation.
    """
    if ea_move not in ("local", "random_builder"):
        raise ValueError(f"ea_move must be 'local' or 'random_builder', got {ea_move!r}")
    if identity_retry_limit < 1:
        raise ValueError(
            f"identity_retry_limit must be >= 1, got {identity_retry_limit}"
        )

    rng = random.Random(seed)
    archive = ChromosomeArchive(
        origin,
        cap=archive_cap,
        restart_h=restart_h,
        rng=rng,
    )

    iterations: list["IterationResult"] = []
    mutator_stats: dict[str, dict[str, int]] = {
        m.name: {"attempts": 0, "archive_adds": 0, "archive_adds_f1": 0} for m in mutators
    }
    restart_reason_counts: dict[str, int] = {"stagnation": 0}
    n_accepted = 0
    rate_limit_hit = False
    mutate_weight = max(0.0, 1.0 - order_move_weight)
    init_n = max(0, min(init_random_samples, max_iterations))

    def _is_eligible(parent: RuleSetChromosome) -> bool:
        if ea_move == "random_builder":
            return True  # the sampler can always draw a change
        stackable, saturated, order_moves = _available_local_moves(
            parent, space, prompts_with_rules, mutators, max_depth, order_move_weight
        )
        return bool(stackable or saturated or order_moves)

    evaluated_count = 0
    attempt_count = 0
    identity_retries = 0
    last_completed = 0
    reseed_remaining = 0  # iterations left in an active stagnation reseed burst
    while evaluated_count < max_iterations:
        if should_stop_fn is not None and should_stop_fn():
            log(f"\n⏹️  Graceful stop (SLURM pre-timeout) — stopping after "
                f"{last_completed}/{max_iterations} iterations")
            break

        # ``budget_iter`` advances only after evaluate_chromosome_fn succeeds.
        # Proposal attempts (including identities) get a separate monotonic id.
        budget_iter = evaluated_count + 1
        attempt_count += 1
        attempt_in_iter = identity_retries + 1

        restarts_this_iter: list[dict[str, Any]] = []

        if evaluated_count < init_n:
            phase = "init"
        elif reseed_remaining > 0:
            phase = "restart"
        elif (
            random_injection_every > 0
            and (evaluated_count - init_n + 1) % random_injection_every == 0
        ):
            phase = "injection"
        else:
            phase = "ea"
            # ---- stagnation cap: wipe the front, reseed like init/injection --
            if archive.should_restart():
                front_size_before_restart = len(archive)
                archive.restart(iteration=budget_iter, reason="stagnation", wipe_front=True)
                restart_reason_counts["stagnation"] += 1
                restarts_this_iter.append({"reason": "stagnation", "wiped_front": True})
                reseed_remaining = max(1, init_n)  # always reseed >=1 even if init_n==0
                log(f"   ↻ archive restart: stagnation — wiping front (was "
                    f"{front_size_before_restart}) and reseeding "
                    f"{reseed_remaining} random samples")
                phase = "restart"
            elif not archive.entries:
                # SAFE NET: no parents available to exploit, so fall back to a
                # random sample from the origin.
                phase = "no_parent_fallback"

        n_changes: int | None = None
        n_attempted_changes: int | None = None
        n_effective_changes: int | None = None
        attempted_operators: list[str] = []
        attempted_mutators: list[str] = []

        if phase in ("init", "injection", "restart", "no_parent_fallback"):
            # ---- random sample from the ORIGIN (never from the front) --------
            parent = archive.origin
            sample = build_random_chromosome(
                space, origin, mutators, rng,
                max_changes=random_max_changes, max_depth=max_depth,
                order_move_prob=order_move_weight,
            )
            child = sample.child
            n_changes = sample.n_requested_changes
            n_attempted_changes = sample.n_attempted_changes
            n_effective_changes = sample.n_effective_changes
            attempted_operators = sample.attempted_operators
            attempted_mutators = sample.attempted_mutators
            chain_names = sample.effective_mutators
            changes = sample.changes
            move_type = {
                "init": "init_random", "injection": "injection_random",
                "restart": "restart_random", "no_parent_fallback": "no_parent_fallback",
            }[phase]
            rule_id = None
            is_identity = _is_render_identity(space, origin, child, prompts_with_rules)
        else:
            # ---- 1. pick a parent (restart re-opens exploration if exhausted)
            parent = archive.sample_parent(_is_eligible, include_origin=ea_origin_parent)
            if parent is None:
                archive.restart(iteration=budget_iter, reason="exhausted")
                restart_reason_counts["exhausted"] = restart_reason_counts.get("exhausted", 0) + 1
                restarts_this_iter.append({"reason": "exhausted"})
                parent = archive.sample_parent(_is_eligible, include_origin=ea_origin_parent)
                if parent is None:
                    log("\n⏹️  No eligible parent even after restart — stopping early")
                    break

            # ---- 2. choose + build the move ----------------------------------
            if ea_move == "random_builder":
                sample = build_random_chromosome(
                    space, parent, mutators, rng,
                    max_changes=random_max_changes, max_depth=max_depth,
                    order_move_prob=order_move_weight,
                )
                child = sample.child
                n_changes = sample.n_requested_changes
                n_attempted_changes = sample.n_attempted_changes
                n_effective_changes = sample.n_effective_changes
                attempted_operators = sample.attempted_operators
                attempted_mutators = sample.attempted_mutators
                chain_names = sample.effective_mutators
                changes = sample.changes
                move_type, rule_id = "random_builder", None
                is_identity = _is_render_identity(space, parent, child, prompts_with_rules)
            else:
                move = _choose_and_build_move(
                    parent, space, prompts_with_rules, mutators, rng, max_depth,
                    ea_n_mutations, mutate_weight, order_move_weight,
                )
                if move is None:
                    # Eligibility and construction use the same move inventory;
                    # if stochastic state still makes it empty, re-open and retry
                    # this evaluation slot without charging the budget.
                    archive.restart(iteration=budget_iter, reason="exhausted")
                    restart_reason_counts["exhausted"] = (
                        restart_reason_counts.get("exhausted", 0) + 1
                    )
                    continue
                child, move_keys, move_type, rule_id, chain_names, changes, is_identity = move
                archive.mark_tried(parent, move_keys)
                attempted_mutators = list(chain_names)
                if move_type == "mutate":
                    attempted_operators = [f"mutator:{name}:{rule_id}" for name in chain_names]
                    n_attempted_changes = len(chain_names)
                else:
                    attempted_operators = [move_type]
                    n_attempted_changes = 1
                # Local search requests exactly the move(s) it then attempts.
                # Keeping this populated (rather than ``None``) makes the
                # requested >= attempted >= effective contract uniform across
                # local EA, initialization/injection, and random search.
                n_changes = n_attempted_changes
                n_effective_changes = 0 if is_identity else 1

        for name in attempted_mutators:
            mutator_stats.setdefault(name, {"attempts": 0, "archive_adds": 0, "archive_adds_f1": 0})
            mutator_stats[name]["attempts"] += 1

        gene_depth = child.gene_depth(rule_id) if rule_id else max(
            (child.gene_depth(r) for r in child.mutated_rule_ids()), default=0
        )

        if move_type in _SAMPLE_MOVE_TYPES:
            move_detail = _sample_detail(
                n_changes, n_effective_changes, len(child.mutated_rule_ids()),
                _count_order_ops(attempted_operators),
            )
        else:
            move_detail = (
                f"local {move_type} rule={(rule_id or '-').replace('codeguard-', 'cg-')} "
                f"mutator={'+'.join(chain_names) or '-'} depth={gene_depth}"
            )

        # ---- 3. identity attempts are visible but do NOT consume budget -----
        if is_identity:
            identity_retries += 1
            log(f"\n⏭️  Iteration {budget_iter}/{max_iterations} [{phase}] — identity: "
                f"{move_detail} attempt={attempt_count} "
                f"— no evaluation; retry {identity_retries}/{identity_retry_limit}")
            _emit_record(iter_record_fn, budget_iter, "ea", parent, child=parent, move_type=move_type,
                         rule_id=rule_id, chain_names=chain_names, agg=None, accepted=False,
                         identity=True, gene_depth=gene_depth, n_reused=0, n_rerun=0,
                         eligible=len(space.all_rule_ids), restarts=restarts_this_iter,
                         phase=phase, n_changes=n_changes, attempt=attempt_count,
                         attempt_in_iter=attempt_in_iter, budget_consumed=False,
                         attempted_operators=attempted_operators,
                         attempted_mutators=attempted_mutators,
                         n_attempted_changes=n_attempted_changes,
                         n_effective_changes=n_effective_changes)
            if identity_retries >= identity_retry_limit:
                raise IdentityRetryLimitExceeded(
                    "EA identity retry limit exceeded for evaluation "
                    f"{budget_iter} after {identity_retries} attempts"
                )
            continue

        identity_retries = 0
        space.stamp(child)

        # ---- 4. header → validation → evaluate ------------------------------
        header = f"\n🧬 Iteration {budget_iter}/{max_iterations} [{phase}] — {move_detail}"
        if phase == "ea":
            # init/injection always sample from the origin; only in the EA phase is
            # the parent a choice, and origin-vs-front is what ea_origin_parent turns.
            parent_label = "ORIGIN" if parent.cid == archive.origin.cid else (parent.cid or "-")
            header += (
                f" | parent={parent_label} parent_f1={parent.f1:+.2f} "
                f"parent_nmut={len(parent.mutated_rule_ids())} front={len(archive)}"
            )
        log(header)

        # Observational quality validation of every changed gene (never refuses).
        validation_metadata: dict = _validate_genes(validate_move_fn, space, parent, child)

        try:
            agg, _results, n_reused, n_rerun = evaluate_chromosome_fn(
                child, f"ea_iter{budget_iter:04d}"
            )
        except WallTimeStop:
            log(f"\n⏱️  Pre-timeout during iteration {budget_iter} — discarding in-flight; "
                f"finalizing from {last_completed} completed iterations.")
            break
        except Exception as e:  # noqa: BLE001 — rate-limit handling only
            if "rate_limit" in str(e).lower() or "429" in str(e) or "413" in str(e):
                log(f"\n⚠️  Rate limit hit at EA iteration {budget_iter}: {e}")
                rate_limit_hit = True
                break
            raise

        child.f1, child.f2, child.f3 = _objectives(agg)
        child.fitness = agg

        # ---- 5. offer to the archive ----------------------------------------
        parent_f1 = parent.f1
        front_before_entries = list(archive.entries)
        front_before = {e.cid for e in front_before_entries}
        size_before = len(archive)
        accepted, reason = archive.try_add(
            child,
            iteration=budget_iter,
            count_rejection_for_stagnation=(phase == "ea"),
        )
        evicted = front_before - {e.cid for e in archive.entries}
        # Two eviction sources fire inside one try_add: members the child
        # dominates, and (on cap overflow) the single lowest-f1 survivor. Split
        # them for the log — the overflow set is whatever left that the child
        # did not dominate.
        evicted_dominated = {
            e.cid for e in front_before_entries if e.cid in evicted and dominates(child, e)
        }
        evicted_overflow = evicted - evicted_dominated
        if accepted:
            n_accepted += 1
            if chain_names:
                # Local moves credit the chain's last mutator; sampler-built
                # children (init/injection/random_builder) share the credit
                # across every applied mutator. Per-mutator marginal analysis
                # should therefore filter to phase == "ea" local moves.
                credited = chain_names if move_type != "mutate" else [chain_names[-1]]
                for name in credited:
                    mutator_stats[name]["archive_adds"] += 1
                    if child.f1 > parent_f1:
                        mutator_stats[name]["archive_adds_f1"] += 1
            log(f"   ✅ archive add: f1={child.f1:+.2f} f2={child.f2:.3f} f3={child.f3:.3f} "
                f"(front={len(archive)}/{archive.cap}, cid={child.cid})")
            if evicted_dominated:
                log(f"   ⤷ evicted_dominated={', '.join(sorted(evicted_dominated))}")
            if evicted_overflow:
                log(f"   ⤷ evicted_overflow={', '.join(sorted(evicted_overflow))}")
            if len(archive) < size_before:
                log(f"   ↧ front shrank {size_before} → {len(archive)}")
        else:
            log(f"   ✗ rejected ({reason}): f1={child.f1:+.2f} f2={child.f2:.3f} f3={child.f3:.3f} "
                f"[front={len(archive)}/{archive.cap}, "
                f"stagnation={archive._attempts_since_insert}/{restart_h}]")

        # Persist this iteration's mutated rule(s) regardless of archive outcome,
        # so mutated_rules/iterNNN/ documents every evaluated candidate.
        if save_move_fn is not None:
            save_move_fn(iteration=budget_iter, child=child, space=space, move_type=move_type,
                         rule_id=rule_id, chain_names=chain_names, changes=changes,
                         validation_metadata=validation_metadata, accepted=accepted)

        iterations.append(iteration_result_factory(
            iteration=evaluated_count,
            rule_text=f"[ea: {child.cid}]",
            aggregated_fitness=agg,
            individual_results=[],
            is_improvement=accepted,
            mutation_changes=changes,
            validation_metadata=validation_metadata,
        ))

        _emit_record(iter_record_fn, budget_iter, "ea", parent, child=child, move_type=move_type,
                     rule_id=rule_id, chain_names=chain_names, agg=agg, accepted=accepted,
                     identity=False, gene_depth=gene_depth, n_reused=n_reused, n_rerun=n_rerun,
                     eligible=len(space.all_rule_ids), restarts=restarts_this_iter,
                     parent_f1=parent_f1, validation_metadata=validation_metadata,
                     phase=phase, n_changes=n_changes, attempt=attempt_count,
                     attempt_in_iter=attempt_in_iter, budget_consumed=True,
                     attempted_operators=attempted_operators,
                     attempted_mutators=attempted_mutators,
                     n_attempted_changes=n_attempted_changes,
                     n_effective_changes=n_effective_changes)

        # A restart slot is an evaluated random sample, not merely a proposal.
        # Identity attempts retry in the same phase without consuming the
        # evaluation budget or shortening the reseed burst.
        if phase == "restart":
            reseed_remaining -= 1

        evaluated_count += 1
        last_completed = evaluated_count

        if evaluated_count % snapshot_every == 0 and archive_snapshot_fn is not None:
            archive_snapshot_fn(evaluated_count, archive.snapshot())

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
):
    """Pick a local move type by weight and build the child chromosome.

    Returns ``(child, move_keys, move_type, rule_id, chain_names, changes,
    is_identity)`` or ``None`` when no untried move is realizable. Every key in
    ``move_keys`` is recorded in ``parent.tried`` regardless of outcome.
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
        return child, (move_key,), "order", rid, [], [f"{op}:{rid}"], False

    # Text move: pick uniformly across all genes. A gene with room gets a
    # 1..ea_n_mutations chain of distinct unused mutators stacked on its CURRENT
    # allele (chain length 1 = the canonical (1+1) step); a saturated gene (no
    # room left) is reverted to original instead — an ablation of its stacked
    # mutations, kept or dropped by the archive's dominance check.
    candidates = stackable + saturated
    if not candidates:
        return None
    rid = rng.choice(candidates)
    if rid in saturated:
        child = parent.with_reverted(rid)
        move_key = ("rev", rid)
        return child, (move_key,), "reverse", rid, [], [f"reverted {rid} (saturated)"], False
    avail = _untried_mutators(parent, rid, mutators)
    depth = parent.gene_depth(rid)
    room = max(1, min(ea_n_mutations, max_depth - depth, len(avail)))
    chosen = rng.sample(avail, rng.randint(1, room))
    new_text, names, changes = _apply_chain(chosen, space.allele(parent, rid))
    is_identity = new_text == space.allele(parent, rid)
    child = parent if is_identity else parent.with_gene_chain(rid, new_text, names)
    move_keys = tuple(("mut", rid, name) for name in names)
    return child, move_keys, "mutate", rid, names, changes, is_identity


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
    or identity-producing operators are not immediately repeated; restart
    clears the parent's set and deliberately makes them available again.
    """
    stackable = [
        rid for rid in space.all_rule_ids
        if parent.gene_depth(rid) < max_depth
        and _untried_mutators(parent, rid, mutators)
    ]
    stackable_set = set(stackable)
    saturated = [
        rid for rid in sorted(parent.mutated_rule_ids())
        if rid not in stackable_set and ("rev", rid) not in parent.tried
    ]

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
    max_iterations: int,
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
) -> ChromosomeRunResult:
    """i.i.d. random search over full rule sets (the corrected baseline,
    2026-07-10).

    Every budgeted iteration evaluates an INDEPENDENT chromosome — a fresh copy of the
    origin with 1..``max_changes`` random changes stacked on it
    (:func:`build_random_chromosome`) — evaluates the whole rule set, and
    records it. No parent carry-forward, no archive, no acceptance, no revert
    operator. The reported best is the best-of-budget sample, with the origin
    as floor (doing nothing is always available). Identity proposals are logged
    and retried without consuming an evaluation.
    """
    if identity_retry_limit < 1:
        raise ValueError(
            f"identity_retry_limit must be >= 1, got {identity_retry_limit}"
        )
    rng = random.Random(seed)

    iterations: list["IterationResult"] = []
    mutator_stats: dict[str, dict[str, int]] = {
        m.name: {"applications": 0, "applications_f1_advancing": 0} for m in mutators
    }
    best = origin
    best_fitness = origin.fitness
    rate_limit_hit = False

    evaluated_count = 0
    attempt_count = 0
    identity_retries = 0
    last_completed = 0
    while evaluated_count < max_iterations:
        if should_stop_fn is not None and should_stop_fn():
            log(f"\n⏹️  Graceful stop (SLURM pre-timeout) — stopping after "
                f"{last_completed}/{max_iterations} iterations")
            break

        budget_iter = evaluated_count + 1
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
            log(f"\n⏭️  Iteration {budget_iter}/{max_iterations} [random] — identity: "
                + _sample_detail(n_changes, sample.n_effective_changes,
                                 len(child.mutated_rule_ids()),
                                 _count_order_ops(sample.attempted_operators))
                + f" attempt={attempt_count} — renders as the origin; no evaluation; "
                  f"retry {identity_retries}/{identity_retry_limit}")
            for name in sample.attempted_mutators:
                mutator_stats[name]["applications"] += 1
            _emit_record(iter_record_fn, budget_iter, "random_search", parent=origin, child=origin,
                         move_type="sample", rule_id=None, chain_names=chain_names, agg=None,
                         accepted=False, identity=True, gene_depth=0,
                         n_reused=0, n_rerun=0, phase="random", n_changes=n_changes,
                         attempt=attempt_count, attempt_in_iter=attempt_in_iter,
                         budget_consumed=False,
                         attempted_operators=sample.attempted_operators,
                         attempted_mutators=sample.attempted_mutators,
                         n_attempted_changes=sample.n_attempted_changes,
                         n_effective_changes=sample.n_effective_changes)
            if identity_retries >= identity_retry_limit:
                raise IdentityRetryLimitExceeded(
                    "random-search identity retry limit exceeded for evaluation "
                    f"{budget_iter} after {identity_retries} attempts"
                )
            continue

        identity_retries = 0
        # ---- header → validation → evaluate ---------------------------------
        log(f"\n🎲 Iteration {budget_iter}/{max_iterations} [random] — "
            + _sample_detail(n_changes, sample.n_effective_changes,
                             len(child.mutated_rule_ids()),
                             _count_order_ops(sample.attempted_operators)))

        # Observational quality validation of every changed gene.
        validation_metadata: dict = _validate_genes(validate_move_fn, space, origin, child)
        try:
            agg, _results, n_reused, n_rerun = evaluate_chromosome_fn(
                child, f"rand_iter{budget_iter:04d}"
            )
        except WallTimeStop:
            log(f"\n⏹️  Pre-timeout mid-eval — stopping after {last_completed} iterations")
            break
        except Exception as e:  # noqa: BLE001
            if "rate_limit" in str(e).lower() or "429" in str(e) or "413" in str(e):
                log(f"\n⚠️  Rate limit hit at random iteration {budget_iter}: {e}")
                rate_limit_hit = True
                break
            raise

        child.f1, child.f2, child.f3 = _objectives(agg)
        child.fitness = agg

        f1_advance = child.f1 > 0.0
        for name in sample.attempted_mutators:
            mutator_stats[name]["applications"] += 1
            if f1_advance:
                mutator_stats[name]["applications_f1_advancing"] += 1

        if child.f1 > best.f1:
            best, best_fitness = child, agg

        if save_move_fn is not None:
            save_move_fn(iteration=budget_iter, child=child, space=space, move_type="sample",
                         rule_id=None, chain_names=chain_names, changes=changes,
                         validation_metadata=validation_metadata, accepted=True)

        iterations.append(iteration_result_factory(
            iteration=evaluated_count, rule_text=f"[random: {child.cid}]", aggregated_fitness=agg,
            individual_results=[], is_improvement=True, mutation_changes=changes,
            validation_metadata=validation_metadata,
        ))
        _emit_record(iter_record_fn, budget_iter, "random_search", parent=origin, child=child,
                     move_type="sample", rule_id=None, chain_names=chain_names, agg=agg,
                     accepted=True, identity=False,
                     gene_depth=max((child.gene_depth(r) for r in child.mutated_rule_ids()),
                                    default=0),
                     n_reused=n_reused, n_rerun=n_rerun, validation_metadata=validation_metadata,
                     phase="random", n_changes=n_changes, attempt=attempt_count,
                     attempt_in_iter=attempt_in_iter, budget_consumed=True,
                     attempted_operators=sample.attempted_operators,
                     attempted_mutators=sample.attempted_mutators,
                     n_attempted_changes=sample.n_attempted_changes,
                     n_effective_changes=sample.n_effective_changes)
        evaluated_count += 1
        last_completed = evaluated_count

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
        restart_reason_counts={},
    )


# ============================================================================
# Records + logging
# ============================================================================

def _emit_record(
    iter_record_fn, iteration, strategy, parent, child, move_type, rule_id, chain_names,
    agg, accepted, identity, gene_depth, n_reused, n_rerun,
    eligible: int = 0, restarts: list | None = None, parent_f1: float | None = None,
    validation_metadata: dict | None = None, phase: str = "ea",
    n_changes: int | None = None,
    attempt: int | None = None,
    attempt_in_iter: int = 1,
    budget_consumed: bool = True,
    attempted_operators: list[str] | None = None,
    attempted_mutators: list[str] | None = None,
    n_attempted_changes: int | None = None,
    n_effective_changes: int | None = None,
):
    if iter_record_fn is None:
        return
    # f1/f2/f3 are the conservative archive objectives; the divergence components
    # are recorded alongside as diagnostics so older analyses stay comparable.
    if agg is not None:
        f1, f2, f3 = _objectives(agg)
        prop_div = agg.proportion_divergent
        cond_div = agg.conditional_mean_divergence
        fidelity = agg.rule_fidelity
        parsimony = agg.parsimony
    else:
        f1 = f2 = f3 = None
        prop_div = cond_div = fidelity = parsimony = None
    p_f1 = parent_f1 if parent_f1 is not None else (parent.f1 if parent is not None else None)
    rec = {
        "iter": iteration,
        "attempt": attempt if attempt is not None else iteration,
        "attempt_in_iter": attempt_in_iter,
        "budget_consumed": budget_consumed,
        "timestamp": _utcnow(),
        "strategy": strategy,
        "phase": phase,
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
        "proportion_divergent": prop_div,
        "conditional_mean_divergence": cond_div,
        "rule_fidelity": fidelity,
        "parsimony": parsimony,
        "f1_advance": bool(accepted and f1 is not None and p_f1 is not None and f1 > p_f1),
        "accepted": accepted,
        "n_prompts_rerun": n_rerun,
        "n_prompts_reused": n_reused,
        "validation_metadata": validation_metadata or {},
        "selection_meta": (
            {} if strategy == "random_search" else {
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
