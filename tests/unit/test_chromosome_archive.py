"""Contract tests for the final bounded Pareto archive."""

from __future__ import annotations

import random

import pytest

from src.optimizer.chromosome import ChromosomeArchive, RuleSetSpace


@pytest.fixture
def space() -> RuleSetSpace:
    return RuleSetSpace(
        all_rule_ids=["a", "b", "c", "d"],
        originals={rid: rid.upper() for rid in ["a", "b", "c", "d"]},
    )


def _mk(space, rid, text, f1, f2, f3):
    child = space.stamp(space.origin().with_gene(rid, text, "m"))
    child.f1, child.f2, child.f3 = f1, f2, f3
    return child


def _archive(space, cap=6, seed=0):
    return ChromosomeArchive(space.origin(), cap=cap, rng=random.Random(seed))


def test_initial_candidate_is_not_rejected_by_origin(space):
    archive = _archive(space)
    accepted, reason = archive.try_add(
        _mk(space, "a", "A!", -2.0, 0.0, -1.0),
        1,
    )
    assert accepted and reason == "accepted"
    assert len(archive) == 1


def test_front_member_dominance_and_duplicate_rejection(space):
    archive = _archive(space)
    elite = _mk(space, "a", "A!", 2.0, 0.5, -1.0)
    archive.try_add(elite, 1)

    accepted, reason = archive.try_add(
        _mk(space, "b", "B!", 1.0, 0.4, -2.0),
        2,
    )
    assert not accepted and reason == "dominated"

    accepted, reason = archive.try_add(
        _mk(space, "a", "A!", 2.0, 0.5, -1.0),
        3,
    )
    assert not accepted and reason == "duplicate"


def test_origin_content_is_rejected_as_duplicate(space):
    archive = _archive(space)
    accepted, reason = archive.try_add(space.origin(), 1)
    assert not accepted and reason == "duplicate"


def test_bounded_overflow_keeps_highest_f1_under_current_policy(space):
    archive = _archive(space, cap=2)
    high_f1 = _mk(space, "a", "A!", 1.0, 0.3, -1.0)
    low_f1 = _mk(space, "b", "B!", 0.1, 0.9, 0.0)
    newcomer = _mk(space, "c", "C!", 0.5, 0.8, -0.5)
    for iteration, child in enumerate((high_f1, low_f1, newcomer), 1):
        archive.try_add(child, iteration)

    cids = {entry.cid for entry in archive.entries}
    assert len(archive) == 2
    assert high_f1.cid in cids
    assert newcomer.cid in cids
    assert low_f1.cid not in cids


def test_parent_sampling_uses_front_only_and_can_exclude_tried_parent(space):
    archive = _archive(space)
    assert archive.sample_parent(lambda _candidate: True) is None

    first = _mk(space, "a", "A!", 1.0, 0.2, -1.0)
    second = _mk(space, "b", "B!", 0.5, 0.9, -1.0)
    archive.try_add(first, 1)
    archive.try_add(second, 2)

    selected = archive.sample_parent(
        lambda _candidate: True,
        exclude_cids={first.cid},
    )
    assert selected is second
    assert archive.origin not in archive.parents()


def test_best_ever_uses_origin_only_as_reporting_floor(space):
    archive = _archive(space)
    worse = _mk(space, "a", "A!", -2.0, 0.9, -1.0)
    better = _mk(space, "b", "B!", 3.0, 0.2, -1.0)
    archive.try_add(worse, 1)
    assert archive.best() is archive.origin
    archive.try_add(better, 2)
    assert archive.best() is better
    assert archive.best_ever_evaluation == 2


def test_archive_has_no_restart_or_wipe_api(space):
    archive = _archive(space)
    assert not hasattr(archive, "restart")
    assert not hasattr(archive, "should_restart")
    assert "restart_history" not in archive.snapshot()
