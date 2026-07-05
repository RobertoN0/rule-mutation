"""Smoke + behaviour tests for the chromosome run_ea.

The LLM/Semgrep pipeline is bypassed via a stub ``evaluate_chromosome_fn`` that
scores a chromosome from its mutated-gene set, so we exercise the runner's move
selection, archive integration, interaction stacking, and graceful stop in
isolation.
"""
from __future__ import annotations

import pytest

from src.evaluation.fitness import AggregatedFitness
from src.evaluation.rule_mapping import PromptWithRules
from src.mutation.base import Mutator, MutationResult
from src.optimizer.chromosome import RuleSetSpace
from src.optimizer.ea_optimizer import run_ea
from src.optimizer.hill_climber import IterationResult


class FakeMutator(Mutator):
    """Deterministic mutator that appends its name (always non-identity)."""

    def __init__(self, name: str):
        super().__init__(0)
        self._n = name

    @property
    def name(self) -> str:
        return self._n

    def mutate(self, text: str) -> MutationResult:
        return MutationResult(text, f"{text}|{self._n}", self._n, [f"+{self._n}"])


def _fit(f1: float, f2: float = 0.0, f3: float = 0.0) -> AggregatedFitness:
    return AggregatedFitness(
        total_fitness=f1, mean_fitness=f1, max_fitness=f1, num_prompts=2,
        num_vulnerable=int(f1 > 0), individual_results=[], total_semgrep_delta=f1,
        total_code_divergence=f3 * 2, n_divergent_prompts=int(f2 * 2),
        mean_code_divergence=f3, proportion_divergent=f2, conditional_mean_divergence=f3,
    )


def _space() -> RuleSetSpace:
    return RuleSetSpace(all_rule_ids=["r1", "r2"], originals={"r1": "R1", "r2": "R2"})


def _prompts():
    def mk(i, rids):
        return PromptWithRules(prompt=f"p{i}", language="python", cwe_id="c", rule_ids=rids,
                               combined_rules="", individual_rules={r: f"R{r}" for r in rids},
                               metadata={"test_case_id": f"tc{i}"})
    return [mk(0, ["r1", "r2"]), mk(1, ["r1"])]


def _origin(space):
    o = space.origin()
    o.f1 = o.f2 = o.f3 = 0.0
    o.fitness = _fit(0.0)
    return o


def _silent(_: str) -> None:
    pass


def _run(evaluate, **kw):
    space = _space()
    defaults = dict(
        space=space, origin=_origin(space), prompts_with_rules=_prompts(),
        mutators=[FakeMutator("m0"), FakeMutator("m1"), FakeMutator("m2")],
        evaluate_chromosome_fn=evaluate, iteration_result_factory=IterationResult,
        max_iterations=10, archive_cap=3, restart_h=8, max_depth=4, seed=42, log=_silent,
    )
    defaults.update(kw)
    return run_ea(**defaults)


class TestRunEA:
    def test_climbs_and_snapshots(self):
        def ev(chromo, iter_id):
            n = len(chromo.mutated_rule_ids())
            return _fit(float(n), min(0.1 * n, 1.0), min(0.05 * n, 1.0)), [], 0, 0
        res = _run(ev)
        assert len(res.iterations) <= 10
        assert res.best_chromosome.f1 > 0
        assert "entries" in res.archive_snapshot
        assert res.archive_snapshot["n_inserts"] >= 1

    def test_reaches_interaction_only_solution(self):
        """R1' alone = 0, R2' alone = 0, R1'+R2' = 1 — impossible under per-rule search."""
        def ev(chromo, iter_id):
            m = chromo.mutated_rule_ids()
            f1 = 1.0 if {"r1", "r2"} <= m else 0.0
            return _fit(f1, 0.5 if f1 else 0.0, 0.0), [], 0, 0
        res = _run(ev, max_iterations=60, seed=1)
        assert res.best_chromosome.f1 == 1.0
        assert {"r1", "r2"} <= res.best_chromosome.mutated_rule_ids()

    def test_records_have_schema3_fields(self):
        recs, snaps = [], []
        def ev(chromo, iter_id):
            return _fit(float(len(chromo.mutated_rule_ids()))), [], 1, 2
        _run(ev, iter_record_fn=recs.append, archive_snapshot_fn=lambda it, s: snaps.append(it),
             snapshot_every=3, max_iterations=6)
        assert recs and all(r["strategy"] == "ea" for r in recs)
        real = [r for r in recs if not r["mutation_identity"]]
        assert real and all("chromosome_id" in r and "mutated_rule_ids" in r for r in real)
        assert all(r["n_prompts_rerun"] == 2 and r["n_prompts_reused"] == 1 for r in real)
        assert snaps  # at least the final snapshot fired

    def test_graceful_stop_limits_iterations(self):
        recs = []
        def ev(chromo, iter_id):
            return _fit(float(len(chromo.mutated_rule_ids()))), [], 0, 0
        res = _run(ev, iter_record_fn=recs.append,
                   should_stop_fn=lambda: len([r for r in recs if not r["mutation_identity"]]) >= 3,
                   max_iterations=10)
        assert len(res.iterations) <= 3

    def test_reproducible_under_fixed_seed(self):
        def ev(chromo, iter_id):
            return _fit(float(len(chromo.mutated_rule_ids()))), [], 0, 0
        a = _run(ev, seed=7)
        b = _run(ev, seed=7)
        assert a.best_chromosome.cid == b.best_chromosome.cid

    def test_design_b_multi_mutation_chain(self):
        """ea_n_mutations>1 (Design B): a move applies a 1..n chain, so a gene can
        reach depth>1 in a single move; respects the depth cap; still climbs."""
        seen_depths = []
        def ev(chromo, iter_id):
            for g in chromo.genes.values():
                seen_depths.append(g.depth)
            return _fit(float(len(chromo.mutated_rule_ids()))), [], 0, 0
        res = _run(ev, ea_n_mutations=3, max_depth=4, max_iterations=30, seed=3)
        assert max(seen_depths, default=0) >= 2          # a multi-mutator chain landed
        assert max(seen_depths, default=0) <= 4          # depth cap respected
        assert res.best_chromosome.f1 > 0
