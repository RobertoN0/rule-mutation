"""Behavior tests for the final EA structure."""

from __future__ import annotations

import random
from copy import deepcopy

from src.evaluation.fitness import AggregatedFitness
from src.evaluation.rule_mapping import PromptWithRules
from src.mutation.base import MutationResult, Mutator
from src.optimizer.engine import IterationResult
from src.optimizer.chromosome import RuleSetSpace
from src.optimizer.search import (
    INITIALIZATION_SAMPLES,
    PrecomputedInitializationCandidate,
    _choose_and_build_move,
    run_ea,
    run_random_search,
)


class FakeMutator(Mutator):
    def __init__(self, name: str):
        super().__init__(0)
        self._name = name

    @property
    def name(self) -> str:
        return self._name

    def mutate(self, text: str) -> MutationResult:
        return MutationResult(
            original=text,
            mutated=f"{text}|{self.name}",
            mutation_type=self.name,
            changes=[f"+{self.name}"],
        )


def _fit(f1: float, *, fidelity: float = 0.8, parsimony: int = 1) -> AggregatedFitness:
    return AggregatedFitness(
        total_fitness=f1,
        mean_fitness=f1,
        max_fitness=f1,
        num_prompts=1,
        num_vulnerable=int(f1 > 0),
        individual_results=[],
        total_raw_reduction=f1,
        total_raw_count=max(0, 10 - int(f1)),
        num_valid_prompts=1,
        rule_fidelity=fidelity,
        parsimony=parsimony,
    )


def _space() -> RuleSetSpace:
    return RuleSetSpace(
        all_rule_ids=["r1", "r2", "r3"],
        originals={"r1": "R1", "r2": "R2", "r3": "R3"},
    )


def _prompts() -> list[PromptWithRules]:
    return [
        PromptWithRules(
            prompt="p",
            language="python",
            cwe_id="c",
            rule_ids=["r1", "r2", "r3"],
            combined_rules="",
            individual_rules={"r1": "R1", "r2": "R2", "r3": "R3"},
            metadata={"test_case_id": "tc0"},
        )
    ]


def _origin(space: RuleSetSpace):
    origin = space.origin()
    origin.f1, origin.f2, origin.f3 = 0.0, 1.0, 0.0
    origin.fitness = _fit(0.0, fidelity=1.0, parsimony=0)
    return origin


def _run_ea(*, main_loop_budget=6, seed=42, records=None, **overrides):
    space = _space()

    def evaluate(chromosome, _iter_id):
        depth = sum(g.depth for g in chromosome.genes.values())
        return _fit(float(depth), parsimony=len(chromosome.genes)), [], 0, 1

    kwargs = {
        "space": space,
        "origin": _origin(space),
        "prompts_with_rules": _prompts(),
        "mutators": [FakeMutator("m0"), FakeMutator("m1"), FakeMutator("m2")],
        "evaluate_chromosome_fn": evaluate,
        "iteration_result_factory": IterationResult,
        "main_loop_budget": main_loop_budget,
        "archive_cap": 6,
        "max_depth": 3,
        "random_injection_every": 10,
        "random_max_changes": 3,
        "order_move_weight": 0.0,
        "seed": seed,
        "log": lambda _message: None,
        "iter_record_fn": records.append if records is not None else None,
    }
    kwargs.update(overrides)
    return run_ea(**kwargs)


def test_total_budget_is_five_plus_main_loop_budget():
    result = _run_ea(main_loop_budget=7)
    assert len(result.iterations) == INITIALIZATION_SAMPLES + 7
    assert result.initialization_evaluations == 5
    assert result.main_loop_evaluations == 7


def test_initial_candidates_create_front_without_origin_threshold():
    space = _space()

    def evaluate(_chromosome, _iter_id):
        return _fit(-1.0, fidelity=0.5, parsimony=2), [], 0, 1

    result = run_ea(
        space=space,
        origin=_origin(space),
        prompts_with_rules=_prompts(),
        mutators=[FakeMutator("m")],
        evaluate_chromosome_fn=evaluate,
        iteration_result_factory=IterationResult,
        main_loop_budget=0,
        archive_cap=6,
        max_depth=1,
        random_injection_every=10,
        random_max_changes=1,
        order_move_weight=0.0,
        seed=1,
        log=lambda _message: None,
    )
    assert result.archive_snapshot["entries"]
    assert result.best_chromosome.cid == _origin(space).cid


def test_initialization_and_injection_phases_use_expected_indices():
    records: list[dict] = []
    _run_ea(
        main_loop_budget=6,
        random_injection_every=3,
        records=records,
    )
    evaluated = [record for record in records if record["evaluation_consumed"]]
    assert [record["phase"] for record in evaluated[:5]] == ["initialization"] * 5
    main = evaluated[5:]
    assert [record["main_loop_iteration"] for record in main] == [1, 2, 3, 4, 5, 6]
    assert [record["phase"] for record in main] == [
        "ea",
        "ea",
        "injection",
        "ea",
        "ea",
        "injection",
    ]


def test_ea_and_random_share_the_same_seeded_five_candidate_prefix():
    ea_records: list[dict] = []
    random_records: list[dict] = []
    _run_ea(main_loop_budget=0, seed=9, records=ea_records)

    space = _space()

    def evaluate(chromosome, _iter_id):
        return _fit(float(len(chromosome.genes))), [], 0, 1

    run_random_search(
        space=space,
        origin=_origin(space),
        prompts_with_rules=_prompts(),
        mutators=[FakeMutator("m0"), FakeMutator("m1"), FakeMutator("m2")],
        evaluate_chromosome_fn=evaluate,
        iteration_result_factory=IterationResult,
        main_loop_budget=0,
        max_changes=3,
        max_depth=3,
        order_move_prob=0.0,
        seed=9,
        log=lambda _message: None,
        iter_record_fn=random_records.append,
    )
    ea_cids = [
        record["chromosome_id"]
        for record in ea_records
        if record["evaluation_consumed"]
    ]
    random_cids = [
        record["chromosome_id"]
        for record in random_records
        if record["evaluation_consumed"]
    ]
    assert ea_cids == random_cids


def test_precomputed_prefix_restores_the_same_next_ea_candidate():
    source_records: list[dict] = []
    source_candidates = []

    def capture_candidate(**kwargs):
        source_candidates.append(
            (
                deepcopy(kwargs["child"]),
                list(kwargs["changes"]),
                dict(kwargs.get("validation_metadata") or {}),
            )
        )

    source = _run_ea(
        main_loop_budget=0,
        seed=17,
        records=source_records,
        save_move_fn=capture_candidate,
    )
    evaluated_source = [
        row for row in source_records if row["evaluation_consumed"]
    ]
    prepared = [
        PrecomputedInitializationCandidate(
            child=child,
            fitness=iteration.aggregated_fitness,
            n_requested_changes=row["n_requested_changes"],
            n_attempted_changes=row["n_attempted_changes"],
            n_effective_changes=row["n_effective_changes"],
            attempted_operators=row["attempted_operators"],
            attempted_mutators=row["attempted_mutators"],
            effective_mutators=row["mutation_chain"],
            changes=changes,
            validation_metadata=validation,
        )
        for (child, changes, validation), iteration, row in zip(
            source_candidates,
            source.iterations,
            evaluated_source,
        )
    ]

    normal_records: list[dict] = []
    _run_ea(main_loop_budget=1, seed=17, records=normal_records)
    reused_records: list[dict] = []
    evaluations = 0

    def evaluate_main(chromosome, _iter_id):
        nonlocal evaluations
        evaluations += 1
        depth = sum(g.depth for g in chromosome.genes.values())
        return _fit(float(depth), parsimony=len(chromosome.genes)), [], 0, 1

    _run_ea(
        main_loop_budget=1,
        seed=17,
        records=reused_records,
        evaluate_chromosome_fn=evaluate_main,
        precomputed_initialization=prepared,
        runner_random_state_after_initialization=(
            source.runner_random_state_after_initialization
        ),
    )

    normal_sixth = [
        row for row in normal_records if row["evaluation_consumed"]
    ][5]
    reused_sixth = [
        row for row in reused_records if row["evaluation_consumed"]
    ][5]
    assert evaluations == 1
    assert reused_sixth["chromosome_id"] == normal_sixth["chromosome_id"]
    assert all(
        row["initialization_source"] == "precomputed_bundle"
        for row in reused_records[:5]
    )


def test_local_text_move_applies_exactly_one_mutator():
    records: list[dict] = []
    _run_ea(main_loop_budget=12, records=records, random_injection_every=0)
    local_mutations = [
        record
        for record in records
        if record["phase"] == "ea"
        and record["move_type"] == "mutate"
        and record["evaluation_consumed"]
    ]
    assert local_mutations
    assert all(record["chain_length"] == 1 for record in local_mutations)


def test_saturated_mutated_rule_reverts_to_origin():
    space = RuleSetSpace(all_rule_ids=["r1"], originals={"r1": "R1"})
    parent = space.stamp(space.origin().with_gene("r1", "R1|m", "m"))
    move = _choose_and_build_move(
        parent,
        space,
        _prompts(),
        [FakeMutator("m")],
        random.Random(0),
        1,
        1.0,
        0.0,
    )
    assert move is not None
    child, _keys, move_type, rule_id, *_rest = move
    assert move_type == "revert"
    assert rule_id == "r1"
    assert child.mutated_rule_ids() == set()


def test_attempted_local_move_is_not_offered_again_on_same_parent():
    space = RuleSetSpace(all_rule_ids=["r1"], originals={"r1": "R1"})
    parent = space.origin()
    mutator = FakeMutator("m")
    move = _choose_and_build_move(
        parent,
        space,
        _prompts(),
        [mutator],
        random.Random(0),
        4,
        1.0,
        0.0,
    )
    assert move is not None
    parent.tried.add(move[1])
    assert _choose_and_build_move(
        parent,
        space,
        _prompts(),
        [mutator],
        random.Random(0),
        4,
        1.0,
        0.0,
    ) is None


def test_archive_is_never_wiped_and_origin_is_not_a_parent():
    records: list[dict] = []
    result = _run_ea(
        main_loop_budget=20,
        records=records,
        random_injection_every=0,
    )
    assert "restart_history" not in result.archive_snapshot
    origin_cid = _space().origin().cid
    local = [
        record
        for record in records
        if record["phase"] == "ea" and record["evaluation_consumed"]
    ]
    assert local
    assert all(record["parent_chromosome_id"] != origin_cid for record in local)
