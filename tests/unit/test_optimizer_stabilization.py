"""Focused retry and budget tests for the final optimizer."""

from __future__ import annotations

import pytest

from src.evaluation.fitness import AggregatedFitness
from src.evaluation.rule_mapping import PromptWithRules
from src.mutation.base import MutationResult, Mutator
from src.optimizer.chromosome import RuleSetSpace
from src.optimizer.engine import IterationResult
from src.optimizer.search import (
    IdentityRetryLimitExceeded,
    run_ea,
    run_random_search,
)


class IdentityMutator(Mutator):
    @property
    def name(self) -> str:
        return "identity"

    def mutate(self, text: str) -> MutationResult:
        return MutationResult(text, text, self.name, [])


def _fit() -> AggregatedFitness:
    return AggregatedFitness(
        total_fitness=0,
        mean_fitness=0,
        max_fitness=0,
        num_prompts=1,
        num_vulnerable=0,
        individual_results=[],
        total_raw_reduction=0,
        total_raw_count=0,
        num_valid_prompts=1,
        rule_fidelity=1,
        parsimony=0,
    )


def _inputs():
    space = RuleSetSpace(all_rule_ids=["r1"], originals={"r1": "R1"})
    origin = space.origin()
    origin.fitness = _fit()
    prompts = [
        PromptWithRules(
            prompt="p",
            language="python",
            cwe_id="c",
            rule_ids=["r1"],
            combined_rules="",
            individual_rules={"r1": "R1"},
            metadata={"test_case_id": "tc"},
        )
    ]
    return space, origin, prompts


@pytest.mark.parametrize("strategy", ["ea", "random_search"])
def test_identity_attempts_do_not_consume_evaluations(strategy):
    space, origin, prompts = _inputs()
    records: list[dict] = []
    common = {
        "space": space,
        "origin": origin,
        "prompts_with_rules": prompts,
        "mutators": [IdentityMutator()],
        "evaluate_chromosome_fn": lambda *_args: (_fit(), [], 0, 0),
        "iteration_result_factory": IterationResult,
        "main_loop_budget": 1,
        "max_depth": 1,
        "identity_retry_limit": 3,
        "seed": 1,
        "log": lambda _message: None,
        "iter_record_fn": records.append,
    }
    with pytest.raises(IdentityRetryLimitExceeded):
        if strategy == "ea":
            run_ea(
                **common,
                archive_cap=3,
                random_injection_every=10,
                random_max_changes=1,
                order_move_weight=0,
            )
        else:
            run_random_search(
                **common,
                max_changes=1,
                order_move_prob=0,
            )
    assert records
    assert all(not record["evaluation_consumed"] for record in records)
    assert all(record["evaluation_index"] == 1 for record in records)
