"""Smoke tests for run_ea and run_random_baseline.

These bypass the LLM/Semgrep pipeline by stubbing evaluate_fn. They verify
the runner's iteration logic, archive integration, and restart behavior in
isolation.
"""

import pytest

from src.evaluation.fitness import AggregatedFitness
from src.evaluation.rule_mapping import PromptWithRules
from src.mutation.base import Mutator, MutationResult
from src.optimizer.ea_optimizer import run_ea, run_random_baseline
from src.optimizer.hill_climber import IterationResult, PerRuleResult


# ---------------------------------------------------------------------------
# Stubs
# ---------------------------------------------------------------------------

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
        return MutationResult(
            original=text,
            mutated=out,
            mutation_type=self._name,
            changes=[f"applied {self._name}"],
        )


def _fit(f1: float = 0.0, f2: float = 0.0, f3: float = 0.0) -> AggregatedFitness:
    return AggregatedFitness(
        total_fitness=f1,
        mean_fitness=f1,
        max_fitness=f1,
        num_prompts=2,
        num_vulnerable=int(f1 > 0),
        individual_results=[],
        total_semgrep_delta=f1,
        total_code_divergence=f3 * 2,
        n_divergent_prompts=int(f2 * 2),
        mean_code_divergence=f3,
        proportion_divergent=f2,
        conditional_mean_divergence=f3,
    )


def _make_prompts(rule_ids_per_prompt: list[list[str]]) -> list[PromptWithRules]:
    out = []
    for i, rids in enumerate(rule_ids_per_prompt):
        individual = {rid: f"ORIGINAL[{rid}]" for rid in rids}
        out.append(PromptWithRules(
            prompt=f"prompt-{i}",
            language="python",
            cwe_id="cwe-079",
            rule_ids=rids,
            combined_rules="\n---\n".join(individual.values()),
            individual_rules=individual,
            metadata={"test_case_id": f"tc{i}"},
        ))
    return out


def _silent_log(_: str) -> None:
    pass


# ═══════════════════════════════════════════════════════════════════════════════
# (1+1) EA
# ═══════════════════════════════════════════════════════════════════════════════

class TestRunEA:

    def test_completes_and_returns_archives(self):
        prompts = _make_prompts([["r1", "r2"], ["r1"]])
        all_rids = sorted({rid for p in prompts for rid in p.rule_ids})
        mutators = [FakeMutator("m0"), FakeMutator("m1"), FakeMutator("m2")]
        rule_originals = {rid: f"ORIGINAL[{rid}]" for rid in all_rids}

        # Counter for monotonically improving fitness — every offspring strictly
        # dominates its parent on f1, ensuring archive inserts happen.
        counter = {"i": 0}
        def stub_eval(target_rid, parent_text, mutator, iteration, phase):
            counter["i"] += 1
            f = float(counter["i"])
            return (
                _fit(f1=f, f2=min(0.1 * f, 1.0), f3=min(0.05 * f, 1.0)),
                [], [f"stub change for {mutator.name}"], {}, f"{parent_text}|{mutator.name}",
            )

        result = run_ea(
            prompts_with_rules=prompts,
            all_rule_ids=all_rids,
            rule_originals=rule_originals,
            baseline_fitness=_fit(0, 0, 0),
            mutators=mutators,
            evaluate_fn=stub_eval,
            iteration_result_factory=IterationResult,
            per_rule_result_factory=PerRuleResult,
            max_iterations=10,
            archive_cap=3,
            restart_h=8,
            max_depth=4,
            seed=42,
            log=_silent_log,
        )

        assert len(result.iterations) == 10
        assert len(result.per_rule_results) == 10
        # Every rule should have a snapshot
        for rid in all_rids:
            assert rid in result.archives_snapshot
            snap = result.archives_snapshot[rid]
            assert snap["cap"] == 3
            assert snap["max_depth"] == 4
        # Some inserts must have happened (monotone improvement guarantees it)
        total_inserts = sum(s["n_inserts"] for s in result.archives_snapshot.values())
        assert total_inserts >= 1
        # Best fitness must be set
        assert result.best_fitness is not None
        assert result.best_fitness.total_semgrep_delta > 0

    def test_archive_dedup_eventually_restarts(self):
        prompts = _make_prompts([["r1"]])
        mutators = [FakeMutator("m0"), FakeMutator("m1")]
        # max_depth small + only 2 mutators → mutator-exhausted restart should fire
        result = run_ea(
            prompts_with_rules=prompts,
            all_rule_ids=["r1"],
            rule_originals={"r1": "ORIGINAL[r1]"},
            baseline_fitness=_fit(0, 0, 0),
            mutators=mutators,
            evaluate_fn=lambda rid, pt, m, it, ph: (
                _fit(0.0, 0.0, 0.0),  # never improves → never inserts → stagnation
                [], [], {}, f"{pt}|{m.name}",
            ),
            iteration_result_factory=IterationResult,
            per_rule_result_factory=PerRuleResult,
            max_iterations=20,
            archive_cap=3,
            restart_h=4,  # short — should trigger stagnation fast
            max_depth=2,
            seed=0,
            log=_silent_log,
        )
        # We expect at least one restart in r1's history
        r1_snap = result.archives_snapshot["r1"]
        assert len(r1_snap["restart_history"]) >= 1
        # All restart reasons should be one of the documented triggers
        for h in r1_snap["restart_history"]:
            assert h["reason"] in {"stagnation", "depth_saturated", "mutator_exhausted", "fully_exhausted"}


# ═══════════════════════════════════════════════════════════════════════════════
# Random baseline
# ═══════════════════════════════════════════════════════════════════════════════

class TestRandomBaseline:

    def test_logs_every_candidate(self):
        prompts = _make_prompts([["r1"]])
        mutators = [FakeMutator("m0"), FakeMutator("m1"), FakeMutator("m2")]
        counter = {"i": 0}
        def stub_eval(target_rid, parent_text, mutator, iteration, phase):
            counter["i"] += 1
            return (
                _fit(f1=float(counter["i"]), f2=0.5, f3=0.3),
                [], [], {}, f"{parent_text}|{mutator.name}",
            )

        result = run_random_baseline(
            prompts_with_rules=prompts,
            all_rule_ids=["r1"],
            rule_originals={"r1": "ORIGINAL[r1]"},
            mutators=mutators,
            evaluate_fn=stub_eval,
            iteration_result_factory=IterationResult,
            per_rule_result_factory=PerRuleResult,
            max_iterations=10,
            max_depth=4,
            seed=0,
            log=_silent_log,
        )
        assert len(result.iterations) == 10
        r1_snap = result.archives_snapshot["r1"]
        assert r1_snap["mode"] == "random_baseline"
        # All 10 candidates logged
        assert len(r1_snap["all_candidates"]) == 10
        # Every candidate's f1 is positive (stub increments monotonically)
        f1_values = [c["f1"] for c in r1_snap["all_candidates"]]
        assert all(v > 0 for v in f1_values)

    def test_depth_cap_restart(self):
        prompts = _make_prompts([["r1"]])
        # Enough mutators that mutator-exhaustion won't pre-empt depth-cap
        mutators = [FakeMutator(f"m{i}") for i in range(10)]
        def stub_eval(target_rid, parent_text, mutator, iteration, phase):
            return (
                _fit(f1=1.0, f2=0.5, f3=0.3),
                [], [], {}, f"{parent_text}|{mutator.name}",
            )

        result = run_random_baseline(
            prompts_with_rules=prompts,
            all_rule_ids=["r1"],
            rule_originals={"r1": "ORIGINAL[r1]"},
            mutators=mutators,
            evaluate_fn=stub_eval,
            iteration_result_factory=IterationResult,
            per_rule_result_factory=PerRuleResult,
            max_iterations=20,
            max_depth=3,  # short — depth_cap should fire
            seed=0,
            log=_silent_log,
        )
        r1_snap = result.archives_snapshot["r1"]
        depth_restarts = [h for h in r1_snap["restart_history"] if h["reason"] == "depth_cap"]
        assert len(depth_restarts) >= 1
        # Each depth_cap restart should record depth_at_reset == max_depth
        for h in depth_restarts:
            assert h["depth_at_reset"] == 3
