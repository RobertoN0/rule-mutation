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
from src.optimizer.search import run_ea
from src.optimizer.engine import IterationResult


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
        # Pure local-EA core by default: init/injection/order are exercised by
        # their own dedicated tests below.
        init_random_samples=0, random_injection_every=0, order_move_weight=0.0,
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

    def test_records_have_schema4_fields(self):
        recs, snaps = [], []
        def ev(chromo, iter_id):
            return _fit(float(len(chromo.mutated_rule_ids()))), [], 1, 2
        _run(ev, iter_record_fn=recs.append, archive_snapshot_fn=lambda it, s: snaps.append(it),
             snapshot_every=3, max_iterations=6)
        assert recs and all(r["strategy"] == "ea" for r in recs)
        real = [r for r in recs if not r["mutation_identity"]]
        assert real and all("chromosome_id" in r and "mutated_rule_ids" in r for r in real)
        assert all("attempt" in r and r["budget_consumed"] for r in real)
        assert all("priority_rule_ids" in r and "priority_offset_count" in r for r in real)
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

    def test_multi_mutation_chain_ablation(self):
        """ea_n_mutations>1 (ablation knob): a move applies a 1..n chain, so a gene
        can reach depth>1 in a single move; respects the depth cap; still climbs."""
        seen_depths = []
        def ev(chromo, iter_id):
            for g in chromo.genes.values():
                seen_depths.append(g.depth)
            return _fit(float(len(chromo.mutated_rule_ids()))), [], 0, 0
        res = _run(ev, ea_n_mutations=3, max_depth=4, max_iterations=30, seed=3)
        assert max(seen_depths, default=0) >= 2          # a multi-mutator chain landed
        assert max(seen_depths, default=0) <= 4          # depth cap respected
        assert res.best_chromosome.f1 > 0

    def test_default_chain_length_is_one(self):
        """Main design: every local text move applies exactly ONE mutator."""
        recs = []
        def ev(chromo, iter_id):
            return _fit(float(len(chromo.mutated_rule_ids()))), [], 0, 0
        _run(ev, iter_record_fn=recs.append, max_iterations=20, seed=5)
        mutates = [r for r in recs if r["move_type"] == "mutate" and not r["mutation_identity"]]
        assert mutates and all(r["chain_length"] == 1 for r in mutates)


class TestInitAndInjection:
    def test_init_phase_samples_from_origin_then_ea(self):
        recs = []
        def ev(chromo, iter_id):
            return _fit(float(len(chromo.mutated_rule_ids()))), [], 0, 0
        _run(ev, init_random_samples=4, max_iterations=12, seed=2,
             iter_record_fn=recs.append)
        assert [r["phase"] for r in recs[:4]] == ["init"] * 4
        assert all(r["move_type"] == "init_random" for r in recs[:4])
        origin_cid = _space().origin().cid
        # init children are built from the ORIGIN, whatever the front holds
        evaluated_init = [r for r in recs[:4] if not r["mutation_identity"]]
        assert evaluated_init
        assert all(r["parent_chromosome_id"] == origin_cid for r in recs[:4])
        assert all(r["phase"] == "ea" for r in recs[4:])

    def test_init_counts_against_budget(self):
        recs = []
        def ev(chromo, iter_id):
            return _fit(1.0), [], 0, 0
        res = _run(ev, init_random_samples=10, max_iterations=6, seed=2,
                   iter_record_fn=recs.append)
        assert len(recs) <= 6                       # init never exceeds the budget
        assert all(r["phase"] == "init" for r in recs)

    def test_injection_cadence(self):
        recs = []
        def ev(chromo, iter_id):
            return _fit(float(len(chromo.mutated_rule_ids()))), [], 0, 0
        _run(ev, init_random_samples=2, random_injection_every=3,
             max_iterations=14, seed=4, iter_record_fn=recs.append)
        phases = {r["iter"]: r["phase"] for r in recs}
        # init at iters 1-2; ea steps 1..; every 3rd ea step is an injection:
        # iters 5, 8, 11, 14
        assert phases[1] == "init" and phases[2] == "init"
        for it in (5, 8, 11, 14):
            assert phases[it] == "injection", (it, phases)
        for it in (3, 4, 6, 7, 9, 10, 12, 13):
            assert phases[it] == "ea", (it, phases)

    def test_injection_children_come_from_origin(self):
        recs = []
        def ev(chromo, iter_id):
            return _fit(float(len(chromo.mutated_rule_ids()))), [], 0, 0
        _run(ev, init_random_samples=2, random_injection_every=2,
             max_iterations=16, seed=8, iter_record_fn=recs.append)
        origin_cid = _space().origin().cid
        inj = [r for r in recs if r["phase"] == "injection"]
        assert inj
        assert all(r["parent_chromosome_id"] == origin_cid for r in inj)
        assert all(r["move_type"] == "injection_random" for r in inj)

    def test_archive_never_wiped_by_injection(self):
        """Injected candidates enter only via dominance; the front survives."""
        def ev(chromo, iter_id):
            n = len(chromo.mutated_rule_ids())
            return _fit(float(n)), [], 0, 0
        res = _run(ev, init_random_samples=3, random_injection_every=2,
                   max_iterations=20, seed=6)
        assert res.archive_snapshot["n_inserts"] >= 1
        assert res.best_chromosome.f1 > 0


class TestRandomBuilderMove:
    def test_random_builder_moves_derive_from_archive_parents(self):
        recs = []
        def ev(chromo, iter_id):
            return _fit(float(len(chromo.mutated_rule_ids()))), [], 0, 0
        _run(ev, ea_move="random_builder", random_max_changes=3,
             init_random_samples=2, max_iterations=15, seed=9,
             iter_record_fn=recs.append)
        moves = [r for r in recs if r["phase"] == "ea" and not r["mutation_identity"]]
        assert moves and all(r["move_type"] == "random_builder" for r in moves)
        assert all(1 <= r["n_changes"] <= 3 for r in moves)

    def test_rejects_unknown_ea_move(self):
        def ev(chromo, iter_id):
            return _fit(0.0), [], 0, 0
        with pytest.raises(ValueError, match="ea_move"):
            _run(ev, ea_move="bogus")
