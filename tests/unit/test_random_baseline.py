"""Unit tests for the redesigned random baseline (stateless multi-mutation sampler).

The sampler bypasses the LLM/Semgrep pipeline via a stubbed evaluate_fn. Each
iteration must: pick a rule, sample n in [1, K], sample n DISTINCT mutators,
apply the chain to the ORIGINAL rule text, and log a record. No archive, no
restart, no cross-iteration state.
"""

import pytest

from src.evaluation.fitness import AggregatedFitness
from src.evaluation.rule_mapping import PromptWithRules
from src.mutation.base import Mutator, MutationResult
from src.optimizer.ea_optimizer import run_random_baseline
from src.optimizer.hill_climber import IterationResult, PerRuleResult


class FakeMutator(Mutator):
    """Deterministic mutator that appends its name to the input."""

    def __init__(self, fake_name: str, seed: int | None = None):
        super().__init__(seed)
        self._name = fake_name

    @property
    def name(self) -> str:
        return self._name

    def mutate(self, text: str) -> MutationResult:
        out = f"{text}|{self._name}"
        return MutationResult(original=text, mutated=out,
                              mutation_type=self._name, changes=[f"+{self._name}"])


def _fit(f1: float = 0.0) -> AggregatedFitness:
    return AggregatedFitness(
        total_fitness=f1, mean_fitness=f1, max_fitness=f1, num_prompts=1,
        num_vulnerable=int(f1 > 0), individual_results=[],
        total_semgrep_delta=f1, total_code_divergence=0.0, n_divergent_prompts=0,
        mean_code_divergence=0.0, proportion_divergent=0.0, conditional_mean_divergence=0.0,
    )


def _make_prompts(rule_ids):
    individual = {rid: f"ORIGINAL[{rid}]" for rid in rule_ids}
    return [PromptWithRules(
        prompt="p", language="python", cwe_id="cwe-079", rule_ids=rule_ids,
        combined_rules="\n---\n".join(individual.values()),
        individual_rules=individual, metadata={"test_case_id": "tc0"},
    )]


def _silent(_: str) -> None:
    pass


def _run(*, mutators, max_iterations, K, seed, f1=1.0, capture_parents=None):
    """Run the sampler with a stub evaluate_fn; returns (result, records)."""
    rule_originals = {"r1": "ORIGINAL[r1]"}
    records = []

    def stub(target_rid, parent_text, mutator, iteration, phase, mutation_chain):
        if capture_parents is not None:
            capture_parents.append(parent_text)
        final = mutator.mutate(parent_text).mutated
        return (_fit(f1=f1), [], ["c"], {}, final)

    result = run_random_baseline(
        prompts_with_rules=_make_prompts(["r1"]),
        all_rule_ids=["r1"],
        rule_originals=rule_originals,
        mutators=mutators,
        evaluate_fn=stub,
        iteration_result_factory=IterationResult,
        per_rule_result_factory=PerRuleResult,
        max_iterations=max_iterations,
        max_mutations_per_iter=K,
        seed=seed,
        log=_silent,
        iter_record_fn=records.append,
    )
    return result, records


def _mutators(n):
    return [FakeMutator(f"m{i}") for i in range(n)]


# ═══════════════════════════════════════════════════════════════════════════════
# Chain sampling
# ═══════════════════════════════════════════════════════════════════════════════

class TestChainSampling:

    def test_n_within_one_to_K(self):
        _, recs = _run(mutators=_mutators(8), max_iterations=200, K=4, seed=1)
        lengths = {r["chain_length"] for r in recs}
        assert lengths <= {1, 2, 3, 4}
        # With 200 iterations every value in [1,K] should appear.
        assert lengths == {1, 2, 3, 4}

    def test_chain_has_n_distinct_mutators(self):
        _, recs = _run(mutators=_mutators(8), max_iterations=100, K=4, seed=2)
        for r in recs:
            chain = r["mutation_chain"]
            assert len(chain) == r["chain_length"]
            assert len(set(chain)) == len(chain), f"chain has repeats: {chain}"

    def test_K_clamped_to_pool_size(self):
        # K=10 but only 3 mutators -> n can be at most 3 (sample needs distinct).
        _, recs = _run(mutators=_mutators(3), max_iterations=100, K=10, seed=3)
        assert {r["chain_length"] for r in recs} <= {1, 2, 3}

    def test_single_mutator_pool_gives_length_one(self):
        _, recs = _run(mutators=_mutators(1), max_iterations=20, K=4, seed=4)
        assert all(r["chain_length"] == 1 for r in recs)


# ═══════════════════════════════════════════════════════════════════════════════
# Statelessness / independence
# ═══════════════════════════════════════════════════════════════════════════════

class TestStateless:

    def test_each_iteration_starts_from_original(self):
        parents = []
        _run(mutators=_mutators(8), max_iterations=50, K=4, seed=5, capture_parents=parents)
        assert parents, "stub should have been called"
        assert all(p == "ORIGINAL[r1]" for p in parents), set(parents)

    def test_no_archive_and_no_restarts(self):
        result, _ = _run(mutators=_mutators(8), max_iterations=30, K=4, seed=6)
        assert result.archives_snapshot == {}
        assert result.restart_reason_counts == {}

    def test_accepted_always_true_and_selection_meta_empty(self):
        _, recs = _run(mutators=_mutators(8), max_iterations=30, K=4, seed=7)
        assert all(r["accepted"] is True for r in recs)
        assert all(r["selection_meta"] == {} for r in recs)
        assert all(r["strategy"] == "random_baseline" for r in recs)

    def test_fixed_seed_reproducible(self):
        _, recs_a = _run(mutators=_mutators(8), max_iterations=50, K=4, seed=42)
        _, recs_b = _run(mutators=_mutators(8), max_iterations=50, K=4, seed=42)
        assert [r["mutation_chain"] for r in recs_a] == [r["mutation_chain"] for r in recs_b]

    def test_different_seed_differs(self):
        _, recs_a = _run(mutators=_mutators(8), max_iterations=50, K=4, seed=1)
        _, recs_b = _run(mutators=_mutators(8), max_iterations=50, K=4, seed=2)
        assert [r["mutation_chain"] for r in recs_a] != [r["mutation_chain"] for r in recs_b]


# ═══════════════════════════════════════════════════════════════════════════════
# mutator_stats — whole-chain credit
# ═══════════════════════════════════════════════════════════════════════════════

class TestMutatorStats:

    def test_stats_shape(self):
        result, _ = _run(mutators=_mutators(8), max_iterations=20, K=4, seed=8)
        for stats in result.mutator_stats.values():
            assert set(stats.keys()) == {"applications", "applications_f1_advancing"}

    def test_whole_chain_credit_when_f1_positive(self):
        # Every iteration's final candidate has f1 > 0 -> every mutator in the
        # chain is credited an f1-advancing application.
        result, recs = _run(mutators=_mutators(8), max_iterations=60, K=4, seed=9, f1=1.0)
        for stats in result.mutator_stats.values():
            assert stats["applications_f1_advancing"] == stats["applications"]
        # applications total equals the sum of chain lengths.
        total_apps = sum(s["applications"] for s in result.mutator_stats.values())
        assert total_apps == sum(r["chain_length"] for r in recs)

    def test_no_credit_when_f1_zero(self):
        result, _ = _run(mutators=_mutators(8), max_iterations=40, K=4, seed=10, f1=0.0)
        for stats in result.mutator_stats.values():
            assert stats["applications_f1_advancing"] == 0
