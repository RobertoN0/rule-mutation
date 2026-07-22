"""Regression tests for the 2026-07-12 optimizer stabilization pass.

These tests pin down experimental-design contracts that are easy to blur:

* archive admission uses standard Pareto dominance with neutral drift,
* stagnation restarts wipe and reseed the archive front, and
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
from src.optimizer.engine import IterationResult
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
        total_raw_reduction=f1,
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


class TestArchiveAdmission:
    def _order_only_equal_candidate(self, space, origin):
        # r2 is moved ahead of r1, so this is a distinct genotype and render,
        # but it has exactly the origin objective vector (0, 1, 0).
        child = space.stamp(origin.with_priority("r2", 1))
        child.f1, child.f2, child.f3 = origin.f1, origin.f2, origin.f3
        return child

    def test_objective_equal_order_candidate_is_admitted_as_neutral_drift(self):
        # Standard Pareto admission (the only policy): a candidate whose
        # objective vector ties the origin is not dominated, so it is admitted
        # as a neutral-drift stepping stone.
        space = _space()
        origin = _origin(space)
        archive = ChromosomeArchive(
            origin, cap=6, restart_h=8, rng=random.Random(0),
        )

        accepted, reason = archive.try_add(
            self._order_only_equal_candidate(space, origin), iteration=1,
        )

        assert accepted and reason == "accepted"
        assert len(archive) == 1
        assert archive.snapshot()["n_neutral_inserts"] == 1
        # Neutral drift affects parent selection, not the reported best repair.
        assert archive.best() is origin

    def test_absolute_best_survives_stagnation_front_wipe(self):
        space = _space()
        origin = _origin(space)
        archive = ChromosomeArchive(origin, cap=2, restart_h=2, rng=random.Random(0))
        elite = space.stamp(origin.with_gene("r1", "elite", "m"))
        elite.f1, elite.f2, elite.f3 = 4.0, 0.7, -1.0
        elite.fitness = _fit(4.0, fidelity=0.7, parsimony=1)
        accepted, _ = archive.try_add(elite, iteration=3)
        assert accepted

        archive.restart(iteration=4, reason="stagnation", wipe_front=True)

        assert archive.entries == []
        assert archive.best() is elite
        assert archive.best_ever_iteration == 3
        assert archive.snapshot()["best_ever"]["cid"] == elite.cid


class TestTriedMoveBookkeeping:
    def test_tried_move_is_filtered_until_restart_reopens_it(self):
        space = _space(("r1",))
        parent = _origin(space)
        archive = ChromosomeArchive(
            parent, cap=3, restart_h=8, rng=random.Random(0),
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
        # With the empty-front safe net, the exhausted-restart path is reached
        # only once the front holds an elite: origin-parent OFF + a single seeded
        # parent whose sole (max-depth) move gets tried, so the next ea iteration
        # finds no untried move and must restart (reopen the tried set), not stall.
        space = _space(("r1",))
        calls: list[str] = []

        def evaluate(_child, iter_id):
            calls.append(iter_id)
            # Accept the first (init) sample to seed the front; reject the rest so
            # they never become parents but keep exploiting the one seeded elite.
            return _fit(1.0 if len(calls) == 1 else -1.0), [], 0, 0

        result = search.run_ea(
            space=space,
            origin=_origin(space),
            prompts_with_rules=_prompt(("r1",)),
            mutators=[_AppendMutator()],
            evaluate_chromosome_fn=evaluate,
            iteration_result_factory=IterationResult,
            max_iterations=3,
            archive_cap=3,
            restart_h=10,
            max_depth=1,
            init_random_samples=1,
            random_injection_every=0,
            order_move_weight=0.0,
            ea_origin_parent=False,
            identity_retry_limit=8,
            seed=0,
            log=lambda _msg: None,
        )

        assert calls == ["ea_iter0001", "ea_iter0002", "ea_iter0003"]
        assert len(result.iterations) == 3  # ran to budget; no early stop
        assert result.restart_reason_counts["exhausted"] == 1
        assert len(result.archive_snapshot["entries"]) == 1  # the seeded elite

    def test_local_move_records_requested_attempted_effective_counts(self):
        # The ea phase takes a local move only on a non-empty front (an empty one
        # would take the no_parent_fallback sampler), so seed one accepted init
        # sample, then check the following ea local move's change counts (1/1/1).
        space = _space(("r1",))
        records: list[dict] = []

        search.run_ea(
            space=space,
            origin=_origin(space),
            prompts_with_rules=_prompt(("r1",)),
            mutators=[_AppendMutator("m0"), _AppendMutator("m1"), _AppendMutator("m2")],
            evaluate_chromosome_fn=lambda *_args: (_fit(1.0), [], 0, 0),
            iteration_result_factory=IterationResult,
            max_iterations=2,
            archive_cap=3,
            restart_h=10,
            max_depth=3,
            init_random_samples=1,
            random_injection_every=0,
            order_move_weight=0.0,
            identity_retry_limit=5,
            seed=0,
            log=lambda _msg: None,
            iter_record_fn=records.append,
        )

        ea_moves = [r for r in records if r["budget_consumed"] and r["phase"] == "ea"]
        assert len(ea_moves) == 1
        assert ea_moves[0]["move_type"] == "mutate"
        assert ea_moves[0]["n_requested_changes"] == 1
        assert ea_moves[0]["n_attempted_changes"] == 1
        assert ea_moves[0]["n_effective_changes"] == 1


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
                    order_move_weight=0.0,                )
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
            identity_retry_limit=5,
            seed=0,
            log=lambda _msg: None,
        )

    def test_rejected_init_samples_do_not_preload_local_stagnation(self):
        # Two rejected init samples. With H=1, counting them toward local
        # stagnation would fire should_restart at the first post-init iteration;
        # that iteration is instead a no_parent_fallback (empty front) and no
        # stagnation restart fires — init rejections never accrue.
        result = self._run_all_rejected(init_samples=2, injection_every=0, restart_h=1)
        assert result.restart_reason_counts["stagnation"] == 0

    def test_rejected_injection_does_not_advance_local_stagnation(self):
        # Seed one accepted init sample so the ea phase takes real LOCAL moves,
        # then reject the rest. With H=2 and injection every 2, the restart fires
        # only after two "ea" rejections (evals 2 and 4); the interleaved
        # injection rejections (evals 3, 5) must NOT advance the local streak, so
        # the wipe lands at eval 6 — not eval 4, as it would if injection counted.
        space = _space(("r1",))
        calls = 0

        def evaluate(_child, _iter_id):
            nonlocal calls
            calls += 1
            return _fit(1.0 if calls == 1 else -1.0), [], 0, 0

        records: list[dict] = []
        result = search.run_ea(
            space=space,
            origin=_origin(space),
            prompts_with_rules=_prompt(("r1",)),
            mutators=[_AppendMutator("m0"), _AppendMutator("m1"), _AppendMutator("m2")],
            evaluate_chromosome_fn=evaluate,
            iteration_result_factory=IterationResult,
            max_iterations=6,
            archive_cap=3,
            restart_h=2,
            max_depth=3,
            init_random_samples=1,
            random_injection_every=2,
            random_max_changes=1,
            order_move_weight=0.0,
            identity_retry_limit=5,
            seed=0,
            log=lambda _msg: None,
            iter_record_fn=records.append,
        )

        evaluated = [r["phase"] for r in records if r["budget_consumed"]]
        assert evaluated == ["init", "ea", "injection", "ea", "injection", "restart"]
        assert result.restart_reason_counts["stagnation"] == 1


class TestStagnationCapWipesFrontAndReseeds:
    def test_stagnation_restart_wipes_front_and_forces_a_random_reseed(self):
        """Hitting restart_h no longer just reopens tried-sets: it wipes the
        front outright and forces the next iteration(s) through the same
        random-sample-from-origin path as init/injection (ARIEL-style
        restart-on-stagnation)."""
        space = _space(("r1",))
        calls = 0

        def evaluate(_child, _iter_id):
            nonlocal calls
            calls += 1
            # First candidate repairs (accepted); everything after is
            # dominated by the origin (rejected) to drive up the stagnation
            # streak deterministically.
            return _fit(1.0 if calls == 1 else -1.0), [], 0, 0

        records: list[dict] = []
        result = search.run_ea(
            space=space,
            origin=_origin(space),
            prompts_with_rules=_prompt(("r1",)),
            mutators=[_AppendMutator("m0"), _AppendMutator("m1"), _AppendMutator("m2")],
            evaluate_chromosome_fn=evaluate,
            iteration_result_factory=IterationResult,
            max_iterations=5,
            archive_cap=3,
            restart_h=2,
            max_depth=3,
            init_random_samples=0,
            random_injection_every=0,
            random_max_changes=1,
            order_move_weight=0.0,
            identity_retry_limit=5,
            seed=0,
            log=lambda _msg: None,
            iter_record_fn=records.append,
        )

        assert result.restart_reason_counts["stagnation"] == 1
        evaluated = [r for r in records if r["budget_consumed"]]
        # eval 1 seeds the front from the empty archive (no_parent_fallback);
        # evals 2-3 exploit it and stagnate; eval 4 wipes+reseeds (restart); the
        # wipe empties the front again, so eval 5 is another no_parent_fallback.
        assert [r["phase"] for r in evaluated] == [
            "no_parent_fallback", "ea", "ea", "restart", "no_parent_fallback"]
        assert evaluated[3]["move_type"] == "restart_random"

        snap = result.archive_snapshot
        assert snap["entries"] == []  # the one accepted entry was wiped, not just re-opened
        stagnation_events = [h for h in snap["restart_history"] if h["reason"] == "stagnation"]
        assert len(stagnation_events) == 1
        assert stagnation_events[0]["wiped_front"] is True
        assert stagnation_events[0]["front_size"] == 1  # pre-wipe size

    def test_restart_identity_retry_does_not_consume_reseed_slot(self, monkeypatch):
        space = _space(("r1",))
        builder_calls = 0

        def scripted_builder(space, base, mutators, _rng, **_kwargs):
            nonlocal builder_calls
            builder_calls += 1
            name = mutators[0].name
            # call 1 seeds the front (init); call 2 is an identity during the
            # restart reseed — it must retry WITHOUT consuming the reseed slot;
            # call 3 is the actual restart reseed sample.
            if builder_calls == 2:
                return search.RandomBuildResult(
                    base, 1, 1, 0, [f"mutator:{name}:r1"], [name], [], ["identity"]
                )
            gene = "R1|seed" if builder_calls == 1 else "R1|restart"
            child = space.stamp(base.with_gene("r1", gene, name))
            return search.RandomBuildResult(
                child, 1, 1, 1, [f"mutator:{name}:r1"], [name], [name], ["changed"]
            )

        monkeypatch.setattr(search, "build_random_chromosome", scripted_builder)
        evaluations = 0

        def evaluate(_child, _iter_id):
            nonlocal evaluations
            evaluations += 1
            # Accept the seed, then reject the local move so H=1 triggers a wipe
            # before evaluation 3.
            return _fit(1.0 if evaluations == 1 else -1.0), [], 0, 0

        records: list[dict] = []
        search.run_ea(
            space=space,
            origin=_origin(space),
            prompts_with_rules=_prompt(("r1",)),
            mutators=[_AppendMutator("m0"), _AppendMutator("m1"), _AppendMutator("m2")],
            evaluate_chromosome_fn=evaluate,
            iteration_result_factory=IterationResult,
            max_iterations=3,
            archive_cap=3,
            restart_h=1,
            max_depth=3,
            init_random_samples=1,
            random_injection_every=0,
            random_max_changes=1,
            order_move_weight=0.0,
            identity_retry_limit=5,
            seed=0,
            log=lambda _msg: None,
            iter_record_fn=records.append,
        )

        evaluated = [r for r in records if r["budget_consumed"]]
        identities = [r for r in records if not r["budget_consumed"]]
        assert [r["phase"] for r in evaluated] == ["init", "ea", "restart"]
        assert [(r["iter"], r["phase"]) for r in identities] == [(3, "restart")]
        assert builder_calls == 3


class TestEmptyArchiveSafeNet:
    """When the EA reaches the ``ea`` phase but the archive front is empty, it
    falls back to a fresh origin-based random sample (``no_parent_fallback``
    phase / move) instead of trying to pick a parent. This keeps
    ``--no-ea-origin-parent`` runs from stopping early on a persistently empty
    front, and resumes normal local exploitation once a candidate is admitted."""

    def test_empty_front_falls_back_to_random_without_early_stop(self):
        # ea_origin_parent=False + every candidate dominated by the origin: the
        # front never fills. Without the safe net, sample_parent() returns None,
        # the exhausted restart also returns None, and run_ea breaks early. With
        # it, post-init iterations sample from the origin and the budget is spent.
        space = _space(("r1",))

        def evaluate(_child, _iter_id):
            return _fit(-1.0), [], 0, 0  # dominated by the origin → never admitted

        records: list[dict] = []
        result = search.run_ea(
            space=space,
            origin=_origin(space),
            prompts_with_rules=_prompt(("r1",)),
            mutators=[_AppendMutator("m0"), _AppendMutator("m1"), _AppendMutator("m2")],
            evaluate_chromosome_fn=evaluate,
            iteration_result_factory=IterationResult,
            max_iterations=5,
            archive_cap=3,
            restart_h=20,  # high enough that stagnation never fires here
            max_depth=3,
            init_random_samples=2,
            random_injection_every=0,
            random_max_changes=1,
            order_move_weight=0.0,
            ea_origin_parent=False,
            identity_retry_limit=5,
            seed=0,
            log=lambda _msg: None,
            iter_record_fn=records.append,
        )

        # Reached the full budget — did NOT break early.
        assert len(result.iterations) == 5
        assert result.restart_reason_counts.get("exhausted", 0) == 0
        evaluated = [r for r in records if r["budget_consumed"]]
        # init covers iterations 1-2; iterations 3-5 all land in the fallback
        # because every candidate is dominated, so the front never fills.
        assert [r["phase"] for r in evaluated] == [
            "init", "init", "no_parent_fallback", "no_parent_fallback", "no_parent_fallback",
        ]
        assert all(r["move_type"] == "no_parent_fallback" for r in evaluated[2:])
        # fallback samples are origin-based, so stagnation never accrues.
        assert result.archive_snapshot["entries"] == []

    def test_exploitation_resumes_after_first_insert(self):
        # First candidate repairs (admitted → front non-empty); everything after
        # is dominated. Once the front holds an elite, the ea phase must take a
        # local move on it (phase "ea", not the "no_parent_fallback").
        space = _space(("r1",))
        calls = 0

        def evaluate(_child, _iter_id):
            nonlocal calls
            calls += 1
            return _fit(1.0 if calls == 1 else -1.0), [], 0, 0

        records: list[dict] = []
        result = search.run_ea(
            space=space,
            origin=_origin(space),
            prompts_with_rules=_prompt(("r1",)),
            mutators=[_AppendMutator("m0"), _AppendMutator("m1"), _AppendMutator("m2")],
            evaluate_chromosome_fn=evaluate,
            iteration_result_factory=IterationResult,
            max_iterations=4,
            archive_cap=3,
            restart_h=20,
            max_depth=3,
            init_random_samples=1,
            random_injection_every=0,
            random_max_changes=1,
            order_move_weight=0.0,
            ea_origin_parent=False,
            identity_retry_limit=5,
            seed=0,
            log=lambda _msg: None,
            iter_record_fn=records.append,
        )

        evaluated = [r for r in records if r["budget_consumed"]]
        assert evaluated[0]["phase"] == "init"  # the accepted seed
        assert len(result.archive_snapshot["entries"]) == 1  # elite to exploit
        ea_moves = [r for r in evaluated[1:] if r["phase"] == "ea"]
        assert ea_moves  # exploitation resumed on the non-empty front
        assert ea_moves[0]["move_type"] == "mutate"  # a local move, not a sample
