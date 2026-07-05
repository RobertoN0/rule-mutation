"""Tests for the redesigned random-walk baseline (chromosome-level).

Each iteration picks a rule, samples n∈[1,K] distinct mutators, applies the chain
to the ORIGINAL rule text, overwrites that gene in the carried-forward chromosome,
and evaluates the whole rule set. No archive, no acceptance test, no restart.
"""
from __future__ import annotations

import pytest

from src.evaluation.fitness import AggregatedFitness
from src.evaluation.rule_mapping import PromptWithRules
from src.mutation.base import Mutator, MutationResult
from src.optimizer.chromosome import RuleSetSpace
from src.optimizer.ea_optimizer import run_random_baseline
from src.optimizer.hill_climber import IterationResult


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


def _run(mutators, *, max_iterations, K, seed, ev=None, **kw):
    space = _space()
    if ev is None:
        def ev(chromo, iter_id):
            return _fit(1.0), [], 0, 0
    return run_random_baseline(
        space=space, origin=_origin(space), prompts_with_rules=_prompts(),
        mutators=mutators, evaluate_chromosome_fn=ev,
        iteration_result_factory=IterationResult, max_iterations=max_iterations,
        max_mutations_per_iter=K, max_depth=4, seed=seed, log=_silent, **kw,
    )


def _muts(n):
    return [FakeMutator(f"m{i}") for i in range(n)]


class TestWalk:
    def test_carries_forward_accumulates_breadth(self):
        seen = []
        def ev(chromo, iter_id):
            seen.append(sorted(chromo.mutated_rule_ids()))
            return _fit(1.0), [], 0, 0
        _run(_muts(3), max_iterations=25, K=2, seed=3, ev=ev)
        sizes = [len(s) for s in seen]
        # the mutated-gene set only grows (chromosome is carried forward)
        assert sizes == sorted(sizes)
        assert sizes[-1] >= 1

    def test_gene_re_derived_from_original(self):
        """Re-picking a gene overwrites from ORIGINAL — depth never exceeds one chain."""
        depths = []
        def ev(chromo, iter_id):
            depths.append(max((g.depth for g in chromo.genes.values()), default=0))
            return _fit(1.0), [], 0, 0
        _run(_muts(3), max_iterations=40, K=3, seed=5, ev=ev)
        # each gene = one fresh chain of ≤ K mutators from original, so depth ≤ K
        assert max(depths) <= 3

    def test_identity_chain_does_not_advance(self):
        recs = []
        res = _run([IdentityMutator()], max_iterations=6, K=1, seed=1,
                   iter_record_fn=recs.append)
        assert all(r["mutation_identity"] for r in recs)
        assert res.best_chromosome.mutated_rule_ids() == set()  # never advanced
        assert len(res.iterations) == 0

    def test_no_archive_snapshot(self):
        res = _run(_muts(2), max_iterations=10, K=2, seed=2)
        assert res.archive_snapshot == {}
        assert res.restart_reason_counts == {}

    def test_reproducible_and_seed_sensitive(self):
        a = _run(_muts(3), max_iterations=15, K=3, seed=11)
        b = _run(_muts(3), max_iterations=15, K=3, seed=11)
        c = _run(_muts(3), max_iterations=15, K=3, seed=99)
        assert a.best_chromosome.cid == b.best_chromosome.cid
        assert a.best_chromosome.cid != c.best_chromosome.cid

    def test_records_are_random_strategy_with_empty_selection_meta(self):
        recs = []
        _run(_muts(2), max_iterations=8, K=2, seed=4, iter_record_fn=recs.append)
        real = [r for r in recs if not r["mutation_identity"]]
        assert real and all(r["strategy"] == "random_baseline" for r in real)
        assert all(r["selection_meta"] == {} and r["accepted"] for r in real)
