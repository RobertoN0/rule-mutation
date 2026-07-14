"""Regression tests for the 2026-07-12 optimizer stabilization pass.

These tests pin down two experimental-design contracts that are easy to blur:

* archive admission is an explicit ablation (neutral drift vs strict repair),
* ``max_iterations`` is an evaluation budget, not a candidate-attempt budget.

No LLM or Semgrep process is used.
"""
from __future__ import annotations

import random

import pytest

from src.evaluation.fitness import AggregatedFitness
from src.evaluation.rule_mapping import PromptWithRules
from src.mutation.base import MutationResult, Mutator
from src.optimizer.chromosome import ChromosomeArchive, RuleSetSpace
from src.optimizer.engine import IterationResult, SearchConfig
import src.optimizer.search as search


class _AppendMutator(Mutator):
    def __init__(self, name: str = "append"):
        super().__init__(0)
        self._name = name

    @property
    def name(self) -> str:
        return self._name

    def mutate(self, text: str) -> MutationResult:
        return MutationResult(text, f"{text}|{self.name}", self.name, [f"+{self.name}"])


def _fit(f1: float, *, fidelity: float = 0.9, parsimony: int = 1) -> AggregatedFitness:
    return AggregatedFitness(
        total_fitness=f1,
        mean_fitness=f1,
        max_fitness=f1,
        num_prompts=1,
        num_vulnerable=int(f1 > 0),
        individual_results=[],
        total_semgrep_delta=f1,
        rule_fidelity=fidelity,
        parsimony=parsimony,
    )


def _space(rule_ids=("r1", "r2")) -> RuleSetSpace:
    ids = list(rule_ids)
    return RuleSetSpace(all_rule_ids=ids, originals={rid: rid.upper() for rid in ids})


def _prompt(rule_ids=("r1", "r2")) -> list[PromptWithRules]:
    ids = list(rule_ids)
    return [PromptWithRules(
        prompt="p",
        language="python",
        cwe_id="c",
        rule_ids=ids,
        combined_rules="",
        individual_rules={rid: rid.upper() for rid in ids},
        metadata={"test_case_id": "tc0"},
    )]


def _origin(space: RuleSetSpace):
    origin = space.origin()
    origin.f1, origin.f2, origin.f3 = 0.0, 1.0, 0.0
    origin.fitness = _fit(0.0, fidelity=1.0, parsimony=0)
    return origin


def _evaluated_record_contract(records: list[dict], budget: int) -> None:
    """Attempts are monotonic; evaluated records alone advance ``iter``."""
    assert [r["attempt"] for r in records] == list(range(1, len(records) + 1))
    assert [r["iter"] for r in records if r["budget_consumed"]] == list(range(1, budget + 1))
    assert all(r["budget_consumed"] is (not r["mutation_identity"]) for r in records)
    assert all(
        r["n_requested_changes"] >= r["n_attempted_changes"] >= r["n_effective_changes"]
        for r in records
    )


class TestArchiveAdmissionAblation:
    def _order_only_equal_candidate(self, space, origin):
        # r2 is moved ahead of r1, so this is a distinct genotype and render,
        # but it has exactly the origin objective vector (0, 1, 0).
        child = space.stamp(origin.with_priority("r2", 1))
        child.f1, child.f2, child.f3 = origin.f1, origin.f2, origin.f3
        return child

    def test_neutral_drift_accepts_objective_equal_order_candidate(self):
        space = _space()
        origin = _origin(space)
        archive = ChromosomeArchive(
            origin, cap=6, restart_h=8, rng=random.Random(0),
            archive_admission="neutral_drift",
        )

        accepted, reason = archive.try_add(
            self._order_only_equal_candidate(space, origin), iteration=1,
        )

        assert accepted and reason == "accepted"
        assert len(archive) == 1
        snap = archive.snapshot()
        assert snap["archive_admission"] == "neutral_drift"
        assert snap["n_neutral_inserts"] == 1
        # Neutral drift affects parent selection, not the reported best repair.
        assert archive.best() is origin

    def test_strict_repair_rejects_objective_equal_order_candidate(self):
        space = _space()
        origin = _origin(space)
        archive = ChromosomeArchive(
            origin, cap=6, restart_h=8, rng=random.Random(0),
            archive_admission="strict_repair",
        )

        accepted, reason = archive.try_add(
            self._order_only_equal_candidate(space, origin), iteration=1,
        )

        assert not accepted and reason == "not_strict_repair"
        assert len(archive) == 0

    def test_strict_repair_still_accepts_an_ordered_security_improver(self):
        space = _space()
        origin = _origin(space)
        archive = ChromosomeArchive(
            origin, cap=6, restart_h=8, rng=random.Random(0),
            archive_admission="strict_repair",
        )
        child = self._order_only_equal_candidate(space, origin)
        child.f1 = 0.25

        accepted, reason = archive.try_add(child, iteration=1)

        assert accepted and reason == "accepted"

    def test_unknown_policy_is_rejected(self):
        space = _space()
        with pytest.raises(ValueError, match="archive_admission"):
            ChromosomeArchive(
                _origin(space), cap=6, restart_h=8, rng=random.Random(0),
                archive_admission="unknown",
            )

    def test_search_config_exposes_admission_knob(self):
        assert SearchConfig().archive_admission == "neutral_drift"
        assert SearchConfig(archive_admission="strict_repair").archive_admission == "strict_repair"


class TestTriedMoveBookkeeping:
    def test_tried_move_is_filtered_until_restart_reopens_it(self):
        space = _space(("r1",))
        parent = _origin(space)
        archive = ChromosomeArchive(
            parent, cap=3, restart_h=8, rng=random.Random(0),
            archive_admission="neutral_drift",
        )
        args = (
            parent, space, _prompt(("r1",)), [_AppendMutator()], random.Random(0),
            1, 1, 1.0, 0.0,
        )

        first = search._choose_and_build_move(*args)
        assert first is not None
        move_key = first[1]
        archive.mark_tried(parent, move_key)
        assert search._choose_and_build_move(*args) is None

        archive.restart(iteration=1, reason="exhausted")
        reopened = search._choose_and_build_move(*args)
        assert reopened is not None and reopened[1] == move_key

    def test_exhausted_parent_restarts_before_reusing_its_only_move(self):
        space = _space(("r1",))
        calls: list[str] = []

        def evaluate(_child, iter_id):
            calls.append(iter_id)
            # Dominated by the origin, so the child never becomes another parent.
            return _fit(-1.0), [], 0, 0

        result = search.run_ea(
            space=space,
            origin=_origin(space),
            prompts_with_rules=_prompt(("r1",)),
            mutators=[_AppendMutator()],
            evaluate_chromosome_fn=evaluate,
            iteration_result_factory=IterationResult,
            max_iterations=2,
            archive_cap=3,
            restart_h=10,
            max_depth=1,
            init_random_samples=0,
            random_injection_every=0,
            order_move_weight=0.0,
            archive_admission="neutral_drift",
            identity_retry_limit=5,
            seed=0,
            log=lambda _msg: None,
        )

        assert calls == ["ea_iter0001", "ea_iter0002"]
        assert result.restart_reason_counts["exhausted"] == 1

    def test_local_move_records_requested_attempted_effective_counts(self):
        space = _space(("r1",))
        records: list[dict] = []

        search.run_ea(
            space=space,
            origin=_origin(space),
            prompts_with_rules=_prompt(("r1",)),
            mutators=[_AppendMutator()],
            evaluate_chromosome_fn=lambda *_args: (_fit(1.0), [], 0, 0),
            iteration_result_factory=IterationResult,
            max_iterations=1,
            archive_cap=3,
            restart_h=10,
            max_depth=1,
            init_random_samples=0,
            random_injection_every=0,
            order_move_weight=0.0,
            archive_admission="neutral_drift",
            identity_retry_limit=5,
            seed=0,
            log=lambda _msg: None,
            iter_record_fn=records.append,
        )

        assert len(records) == 1
        assert records[0]["n_requested_changes"] == 1
        assert records[0]["n_attempted_changes"] == 1
        assert records[0]["n_effective_changes"] == 1


class TestEvaluationBudget:
    def test_random_identities_retry_without_consuming_budget(self, monkeypatch):
        space = _space(("r1",))
        origin = _origin(space)
        builder_calls = 0

        def scripted_builder(space, base, mutators, _rng, **_kwargs):
            nonlocal builder_calls
            builder_calls += 1
            name = mutators[0].name
            if builder_calls in (1, 3):
                return search.RandomBuildResult(
                    base, 1, 1, 0, [f"mutator:{name}:r1"], [name], [], ["identity"]
                )
            child = space.stamp(base.with_gene("r1", f"R1|{builder_calls}", name))
            return search.RandomBuildResult(
                child, 1, 1, 1, [f"mutator:{name}:r1"], [name], [name], ["changed"]
            )

        monkeypatch.setattr(search, "build_random_chromosome", scripted_builder)
        records: list[dict] = []
        eval_ids: list[str] = []

        def evaluate(_child, iter_id):
            eval_ids.append(iter_id)
            return _fit(float(len(eval_ids))), [], 0, 0

        result = search.run_random_search(
            space=space,
            origin=origin,
            prompts_with_rules=_prompt(("r1",)),
            mutators=[_AppendMutator()],
            evaluate_chromosome_fn=evaluate,
            iteration_result_factory=IterationResult,
            max_iterations=2,
            max_changes=1,
            max_depth=1,
            order_move_prob=0.0,
            identity_retry_limit=5,
            seed=0,
            log=lambda _msg: None,
            iter_record_fn=records.append,
        )

        assert len(result.iterations) == 2
        assert eval_ids == ["rand_iter0001", "rand_iter0002"]
        assert [r["iter"] for r in records] == [1, 1, 2, 2]
        assert [r["budget_consumed"] for r in records] == [False, True, False, True]
        _evaluated_record_contract(records, budget=2)

    def test_ea_phase_schedule_advances_only_on_evaluation(self, monkeypatch):
        space = _space(("r1",))
        origin = _origin(space)
        builder_calls = 0

        def scripted_builder(space, base, mutators, _rng, **_kwargs):
            nonlocal builder_calls
            builder_calls += 1
            name = mutators[0].name
            # Identity in pending init evaluation 1 and pending injection
            # evaluation 4. The retries must stay in the same phase/index.
            if builder_calls in (1, 4):
                return search.RandomBuildResult(
                    base, 1, 1, 0, [f"mutator:{name}:r1"], [name], [], ["identity"]
                )
            child = space.stamp(base.with_gene("r1", f"R1|sample-{builder_calls}", name))
            return search.RandomBuildResult(
                child, 1, 1, 1, [f"mutator:{name}:r1"], [name], [name], ["changed"]
            )

        monkeypatch.setattr(search, "build_random_chromosome", scripted_builder)
        records: list[dict] = []
        eval_ids: list[str] = []

        def evaluate(_child, iter_id):
            eval_ids.append(iter_id)
            return _fit(float(len(eval_ids))), [], 0, 0

        result = search.run_ea(
            space=space,
            origin=origin,
            prompts_with_rules=_prompt(("r1",)),
            mutators=[_AppendMutator()],
            evaluate_chromosome_fn=evaluate,
            iteration_result_factory=IterationResult,
            max_iterations=5,
            archive_cap=6,
            restart_h=20,
            max_depth=2,
            init_random_samples=2,
            random_injection_every=2,
            random_max_changes=1,
            order_move_weight=0.0,
            archive_admission="neutral_drift",
            identity_retry_limit=5,
            seed=3,
            log=lambda _msg: None,
            iter_record_fn=records.append,
        )

        evaluated = [r for r in records if r["budget_consumed"]]
        identities = [r for r in records if not r["budget_consumed"]]
        assert len(result.iterations) == 5
        assert eval_ids == [f"ea_iter{i:04d}" for i in range(1, 6)]
        assert [r["phase"] for r in evaluated] == ["init", "init", "ea", "injection", "ea"]
        assert [(r["iter"], r["phase"]) for r in identities] == [
            (1, "init"), (4, "injection"),
        ]
        _evaluated_record_contract(records, budget=5)

    @pytest.mark.parametrize("runner", ["ea", "random_search"])
    def test_identity_retry_limit_fails_explicitly(self, monkeypatch, runner):
        space = _space(("r1",))
        origin = _origin(space)
        builder_calls = 0

        def always_identity(_space, base, mutators, _rng, **_kwargs):
            nonlocal builder_calls
            builder_calls += 1
            name = mutators[0].name
            return search.RandomBuildResult(
                base, 1, 1, 0, [f"mutator:{name}:r1"], [name], [], ["identity"]
            )

        monkeypatch.setattr(search, "build_random_chromosome", always_identity)
        records: list[dict] = []
        common = dict(
            space=space,
            origin=origin,
            prompts_with_rules=_prompt(("r1",)),
            mutators=[_AppendMutator()],
            evaluate_chromosome_fn=lambda *_args: pytest.fail("identity must not be evaluated"),
            iteration_result_factory=IterationResult,
            max_iterations=1,
            max_depth=1,
            identity_retry_limit=2,
            seed=0,
            log=lambda _msg: None,
            iter_record_fn=records.append,
        )

        with pytest.raises(search.IdentityRetryLimitExceeded, match="identity retry limit"):
            if runner == "ea":
                search.run_ea(
                    **common,
                    archive_cap=3,
                    restart_h=8,
                    init_random_samples=1,
                    random_injection_every=0,
                    random_max_changes=1,
                    order_move_weight=0.0,
                    archive_admission="neutral_drift",
                )
            else:
                search.run_random_search(
                    **common,
                    max_changes=1,
                    order_move_prob=0.0,
                )

        assert builder_calls == 2
        assert len(records) == 2
        assert [r["attempt"] for r in records] == [1, 2]
        assert all(r["iter"] == 1 and not r["budget_consumed"] for r in records)


class TestStagnationIsolation:
    def _run_all_rejected(self, *, init_samples: int, injection_every: int, restart_h: int):
        space = _space(("r1",))

        def evaluate(_child, _iter_id):
            return _fit(-1.0), [], 0, 0

        return search.run_ea(
            space=space,
            origin=_origin(space),
            prompts_with_rules=_prompt(("r1",)),
            mutators=[_AppendMutator("m0"), _AppendMutator("m1"), _AppendMutator("m2")],
            evaluate_chromosome_fn=evaluate,
            iteration_result_factory=IterationResult,
            max_iterations=3,
            archive_cap=3,
            restart_h=restart_h,
            max_depth=3,
            init_random_samples=init_samples,
            random_injection_every=injection_every,
            random_max_changes=1,
            order_move_weight=0.0,
            archive_admission="neutral_drift",
            identity_retry_limit=5,
            seed=0,
            log=lambda _msg: None,
        )

    def test_rejected_init_samples_do_not_preload_local_stagnation(self):
        # Two rejected init samples followed by the first local move. With H=1,
        # counting init rejection would force a spurious restart at that boundary.
        result = self._run_all_rejected(init_samples=2, injection_every=0, restart_h=1)
        assert result.restart_reason_counts["stagnation"] == 0

    def test_rejected_injection_does_not_advance_local_stagnation(self):
        # Eval 1 is a rejected local move (streak=1), eval 2 a rejected
        # injection, and eval 3 local again. With H=2, the injection must not
        # trigger a restart before eval 3.
        result = self._run_all_rejected(init_samples=0, injection_every=2, restart_h=2)
        assert result.restart_reason_counts["stagnation"] == 0
