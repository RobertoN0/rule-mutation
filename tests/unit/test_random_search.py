"""Tests for the i.i.d. random-search baseline (corrected design, 2026-07-10).

Every iteration builds an INDEPENDENT chromosome: a fresh copy of the origin
with n ∈ [1, K] random changes stacked on it (one mutator per change, rule
picked uniformly with repeats allowed), evaluated as a whole rule set. No
parent carry-forward, no archive, best-of-budget.
"""
from __future__ import annotations

import pytest

from src.evaluation.fitness import AggregatedFitness
from src.evaluation.rule_mapping import PromptWithRules
from src.mutation.base import Mutator, MutationResult
from src.optimizer.chromosome import RuleSetSpace
from src.optimizer.search import build_random_chromosome, run_random_search
import src.optimizer.search as search
from src.optimizer.engine import IterationResult

import random


class FakeMutator(Mutator):
    def __init__(self, name: str):
        super().__init__(0)
        self._n = name

    @property
    def name(self) -> str:
        return self._n

    def mutate(self, text: str) -> MutationResult:
        return MutationResult(text, f"{text}|{self._n}", self._n, [f"+{self._n}"])


class IdentityMutator(Mutator):
    @property
    def name(self) -> str:
        return "identity"

    def mutate(self, text: str) -> MutationResult:
        return MutationResult(text, text, "identity", [])


def _fit(f1: float) -> AggregatedFitness:
    return AggregatedFitness(
        total_fitness=f1, mean_fitness=f1, max_fitness=f1, num_prompts=1,
        num_vulnerable=int(f1 > 0), individual_results=[], total_semgrep_delta=f1,
        total_code_divergence=0.0, n_divergent_prompts=0, mean_code_divergence=0.0,
        proportion_divergent=0.0, conditional_mean_divergence=0.0,
    )


def _space():
    return RuleSetSpace(all_rule_ids=["r1", "r2", "r3"],
                        originals={"r1": "R1", "r2": "R2", "r3": "R3"})


def _prompts():
    return [PromptWithRules(prompt="p", language="python", cwe_id="c",
                            rule_ids=["r1", "r2", "r3"], combined_rules="",
                            individual_rules={r: r.upper() for r in ["r1", "r2", "r3"]},
                            metadata={"test_case_id": "tc0"})]


def _origin(space):
    o = space.origin()
    o.fitness = _fit(0.0)
    return o


def _silent(_: str) -> None:
    pass


def _run(mutators, *, max_iterations, K, seed, ev=None, order_move_prob=0.0, **kw):
    space = _space()
    if ev is None:
        def ev(chromo, iter_id):
            return _fit(1.0), [], 0, 0
    return run_random_search(
        space=space, origin=_origin(space), prompts_with_rules=_prompts(),
        mutators=mutators, evaluate_chromosome_fn=ev,
        iteration_result_factory=IterationResult, max_iterations=max_iterations,
        max_changes=K, max_depth=4, order_move_prob=order_move_prob,
        seed=seed, log=_silent, **kw,
    )


def _muts(n):
    return [FakeMutator(f"m{i}") for i in range(n)]


class TestBuilder:
    def test_base_never_modified_and_child_parented(self):
        space = _space()
        origin = _origin(space)
        rng = random.Random(0)
        sample = build_random_chromosome(
            space, origin, _muts(3), rng, max_changes=4, max_depth=4)
        child = sample.child
        assert origin.mutated_rule_ids() == set()          # base untouched
        assert 1 <= sample.n_requested_changes <= 4
        assert child.parent_id == origin.cid
        assert child.cid and child.cid != origin.cid

    def test_change_count_bounds_and_stacking(self):
        """Total stacked mutations across genes ≤ n_changes; same rule may stack."""
        space = _space()
        origin = _origin(space)
        for seed in range(30):
            rng = random.Random(seed)
            sample = build_random_chromosome(
                space, origin, _muts(4), rng, max_changes=6, max_depth=4)
            child = sample.child
            total_depth = sum(child.gene_depth(r) for r in child.mutated_rule_ids())
            assert total_depth <= sample.n_requested_changes
            assert len(sample.effective_mutators) == total_depth
            assert sample.n_effective_changes <= sample.n_attempted_changes
            assert sample.n_attempted_changes <= sample.n_requested_changes

    def test_no_repeat_mutator_per_rule_and_depth_cap(self):
        space = _space()
        origin = _origin(space)
        for seed in range(30):
            rng = random.Random(seed)
            sample = build_random_chromosome(
                space, origin, _muts(3), rng, max_changes=10, max_depth=2)
            child = sample.child
            for g in child.genes.values():
                assert len(g.mutation_path) == len(set(g.mutation_path))  # no repeats
                assert g.depth <= 2                                       # cap respected

    def test_noop_attempt_is_still_no_repeat_and_accounted(self):
        space = RuleSetSpace(all_rule_ids=["r1"], originals={"r1": "R1"})
        origin = _origin(space)
        sample = build_random_chromosome(
            space, origin, [IdentityMutator()], random.Random(5),
            max_changes=10, max_depth=4,
        )
        assert sample.n_requested_changes > 1
        assert sample.n_attempted_changes == 1
        assert sample.n_effective_changes == 0
        assert sample.attempted_mutators == ["identity"]
        assert sample.effective_mutators == []
        assert sample.child is origin

    def test_order_only_changes_possible(self):
        space = _space()
        origin = _origin(space)
        rng = random.Random(1)
        sample = build_random_chromosome(
            space, origin, _muts(2), rng, max_changes=4, max_depth=4,
            order_move_prob=1.0)
        assert sample.effective_mutators == []               # no text mutations
        assert sample.child.genes == {}
        assert all(c.startswith("order ") for c in sample.changes)


class TestRandomSearch:
    def test_iterations_are_independent(self):
        """Every evaluated sample is built from the ORIGIN — the mutated-gene
        set does NOT accumulate across iterations (the old walk bug)."""
        seen_parents, seen_sizes = [], []
        def ev(chromo, iter_id):
            seen_parents.append(chromo.parent_id)
            seen_sizes.append(len(chromo.mutated_rule_ids()))
            return _fit(1.0), [], 0, 0
        _run(_muts(4), max_iterations=25, K=3, seed=3, ev=ev)
        origin_cid = RuleSetSpace(all_rule_ids=["r1", "r2", "r3"],
                                  originals={"r1": "R1", "r2": "R2", "r3": "R3"}).origin().cid
        assert all(p == origin_cid for p in seen_parents)
        # sizes bounded by K=3 forever — no accumulation toward all 3 rules on
        # every sample (the walk would monotonically grow to 3 and stay there)
        assert max(seen_sizes) <= 3
        assert min(seen_sizes) >= 1
        assert seen_sizes != sorted(seen_sizes) or len(set(seen_sizes)) == 1

    def test_n_changes_recorded_and_bounded(self):
        recs = []
        _run(_muts(3), max_iterations=20, K=5, seed=7, iter_record_fn=recs.append)
        assert recs
        assert all(1 <= r["n_changes"] <= 5 for r in recs)
        assert all(r["n_requested_changes"] == r["n_changes"] for r in recs)
        assert all(0 <= r["n_effective_changes"] <= r["n_attempted_changes"] <= r["n_changes"]
                   for r in recs)
        assert all(len(r["attempted_operators"]) == r["n_attempted_changes"] for r in recs)
        assert all(r["phase"] == "random" for r in recs)

    def test_identity_sample_hits_guard_without_consuming_budget(self):
        recs = []
        with pytest.raises(search.IdentityRetryLimitExceeded, match="identity retry limit"):
            _run([IdentityMutator()], max_iterations=6, K=2, seed=1,
                 identity_retry_limit=3, iter_record_fn=recs.append)
        assert all(r["mutation_identity"] for r in recs)
        assert len(recs) == 3
        assert all(r["iter"] == 1 and not r["budget_consumed"] for r in recs)
        assert all(r["attempted_mutators"] and set(r["attempted_mutators"]) == {"identity"}
                   for r in recs)
        assert all(r["n_attempted_changes"] == len(r["attempted_mutators"])
                   and r["n_effective_changes"] == 0 for r in recs)

    def test_no_archive_snapshot(self):
        res = _run(_muts(2), max_iterations=10, K=2, seed=2)
        assert res.archive_snapshot == {}
        assert res.restart_reason_counts == {}

    def test_best_is_argmax_with_origin_floor(self):
        scores = iter([0.5, 3.0, 1.0, 2.0, 0.1])
        best_seen = {}
        def ev(chromo, iter_id):
            f1 = next(scores)
            best_seen[chromo.cid] = f1
            return _fit(f1), [], 0, 0
        res = _run(_muts(3), max_iterations=5, K=2, seed=9, ev=ev)
        assert res.best_chromosome.f1 == 3.0

        def ev_neg(chromo, iter_id):
            return _fit(-2.0), [], 0, 0
        res2 = _run(_muts(3), max_iterations=5, K=2, seed=9, ev=ev_neg)
        assert res2.best_chromosome.mutated_rule_ids() == set()  # origin wins

    def test_reproducible_and_seed_sensitive(self):
        a = _run(_muts(3), max_iterations=15, K=3, seed=11)
        b = _run(_muts(3), max_iterations=15, K=3, seed=11)
        c = _run(_muts(3), max_iterations=15, K=3, seed=99)
        assert a.best_chromosome.cid == b.best_chromosome.cid
        assert a.best_chromosome.cid != c.best_chromosome.cid

    def test_records_are_random_search_strategy_with_empty_selection_meta(self):
        recs = []
        _run(_muts(2), max_iterations=8, K=2, seed=4, iter_record_fn=recs.append)
        real = [r for r in recs if not r["mutation_identity"]]
        assert real and all(r["strategy"] == "random_search" for r in real)
        assert all(r["selection_meta"] == {} and r["accepted"] for r in real)
        assert all(r["move_type"] == "sample" for r in real)

    def test_order_moves_reach_evaluation(self):
        """With order_move_prob=1 every change is an order bump; a bump that
        re-ranks the prompt's rules must be evaluated (not identity-skipped)."""
        recs = []
        _run(_muts(2), max_iterations=10, K=3, seed=6, order_move_prob=1.0,
             iter_record_fn=recs.append)
        real = [r for r in recs if not r["mutation_identity"]]
        assert real  # at least one reorder changed a render and was evaluated
        assert all(r["mutation_chain"] == [] for r in real)
