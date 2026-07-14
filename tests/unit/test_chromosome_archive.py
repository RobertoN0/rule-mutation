"""Unit tests for the single chromosome Pareto archive.

Covers admission (dominance + origin-dominance + dedup), lexicographic-f1 cap
eviction with just-added-child protection, origin-aside parent sampling (incl.
the ea_origin_parent knob), restart, and origin-inclusive best(). No LLM, no
Semgrep.
"""
from __future__ import annotations

import random

import pytest

from src.optimizer.chromosome import ChromosomeArchive, RuleSetSpace


@pytest.fixture
def space() -> RuleSetSpace:
    return RuleSetSpace(
        all_rule_ids=["a", "b", "c", "d"],
        originals={k: k.upper() for k in ["a", "b", "c", "d"]},
    )


def _mk(space, rid, text, f1, f2, f3):
    """A distinct-content chromosome with explicit objectives."""
    c = space.stamp(space.origin().with_gene(rid, text, "m"))
    c.f1, c.f2, c.f3 = f1, f2, f3
    return c


def _archive(space, cap=6, restart_h=8, seed=0):
    return ChromosomeArchive(space.origin(), cap=cap, restart_h=restart_h, rng=random.Random(seed))


# ---------------------------------------------------------------------------
class TestAdmission:
    def test_improver_admitted(self, space):
        arc = _archive(space)
        ok, why = arc.try_add(_mk(space, "a", "A!", 1.0, 0.1, 0.1), 1)
        assert ok and why == "accepted" and len(arc) == 1

    def test_worse_than_baseline_rejected_by_origin(self, space):
        arc = _archive(space)
        # dominated by origin (0,0,0): worse on f1, no divergence
        ok, why = arc.try_add(_mk(space, "a", "A!", -2.0, 0.0, 0.0), 1)
        assert not ok and why == "dominated" and len(arc) == 0

    def test_divergent_but_worse_is_a_tradeoff_and_admitted(self, space):
        arc = _archive(space)
        # origin does NOT dominate: child wins on f2
        ok, why = arc.try_add(_mk(space, "a", "A!", -2.0, 0.5, 0.0), 1)
        assert ok and len(arc) == 1

    def test_dominated_by_existing_rejected(self, space):
        arc = _archive(space)
        arc.try_add(_mk(space, "a", "A!", 2.0, 0.5, 0.5), 1)
        ok, why = arc.try_add(_mk(space, "b", "B!", 1.0, 0.4, 0.4), 2)
        assert not ok and why == "dominated"

    def test_duplicate_cid_rejected(self, space):
        arc = _archive(space)
        c = _mk(space, "a", "A!", 1.0, 0.1, 0.1)
        arc.try_add(c, 1)
        dup = _mk(space, "a", "A!", 1.0, 0.1, 0.1)  # same content ⇒ same cid
        ok, why = arc.try_add(dup, 2)
        assert not ok and why == "duplicate" and arc.n_dup_rejected == 1

    def test_origin_content_child_rejected_as_duplicate(self, space):
        arc = _archive(space)
        ok, why = arc.try_add(space.origin(), 1)  # reverting everything = baseline
        assert not ok and why == "duplicate"


# ---------------------------------------------------------------------------
class TestCapEviction:
    def test_cap_evicts_lowest_f1_not_lowest_sum(self, space):
        """Lexicographic-f1 eviction protects the best repair.

        X (high-f1/low-f3) and Y (low-f1/high-f3) have equal f1+f2+f3, so a raw
        score_sum tie-break would evict the OLDER one — here X, the better
        repair. Lexicographic f1 must evict Y (the lower-f1 member) instead.
        """
        arc = _archive(space, cap=2)
        X = _mk(space, "a", "A!", 1.0, 0.3, 0.0)  # sum 1.3, HIGH f1
        Y = _mk(space, "b", "B!", 0.1, 0.3, 0.9)  # sum 1.3, LOW f1
        Z = _mk(space, "c", "C!", 0.5, 0.9, 0.5)  # protected just-added child
        for i, c in enumerate((X, Y, Z)):
            arc.try_add(c, i + 1)
        cids = {e.cid for e in arc.entries}
        assert len(arc) == 2
        assert Y.cid not in cids       # lowest f1 evicted (not the older X)
        assert X.cid in cids           # best repair survives
        assert Z.cid in cids           # just-added child never evicted

    def test_f1_tie_breaks_on_secondary_then_age(self, space):
        """Equal f1 ⇒ evict the weaker f2+f3; equal there ⇒ the oldest."""
        arc = _archive(space, cap=2)
        P = _mk(space, "a", "A!", 0.5, 0.9, 0.1)  # f1 tie, f2+f3 = 1.0
        Q = _mk(space, "b", "B!", 0.5, 0.2, 0.5)  # f1 tie, f2+f3 = 0.7 → evicted
        R = _mk(space, "c", "C!", 0.7, 0.3, 0.3)  # protected just-added child
        for i, c in enumerate((P, Q, R)):
            arc.try_add(c, i + 1)
        cids = {e.cid for e in arc.entries}
        assert len(arc) == 2
        assert Q.cid not in cids       # equal f1, lower f2+f3 evicted
        assert P.cid in cids


# ---------------------------------------------------------------------------
class TestParentSampling:
    def test_origin_always_sampleable(self, space):
        arc = _archive(space)
        # empty front ⇒ only the origin is a parent
        p = arc.sample_parent(is_eligible=lambda c: True)
        assert p is arc.origin

    def test_eligibility_filter(self, space):
        arc = _archive(space)
        arc.try_add(_mk(space, "a", "A!", 1.0, 0.1, 0.1), 1)
        # only the origin is eligible ⇒ it is returned even with a front present
        p = arc.sample_parent(is_eligible=lambda c: c is arc.origin)
        assert p is arc.origin

    def test_none_when_nothing_eligible(self, space):
        arc = _archive(space)
        assert arc.sample_parent(is_eligible=lambda c: False) is None

    def test_include_origin_false_excludes_origin(self, space):
        """ea_origin_parent=off ⇒ the origin is not a sampleable parent."""
        arc = _archive(space)
        entry = _mk(space, "a", "A!", 1.0, 0.1, 0.1)
        arc.try_add(entry, 1)
        # only front members are drawn; the origin is skipped
        p = arc.sample_parent(is_eligible=lambda c: True, include_origin=False)
        assert p is entry
        # with an empty front and origin excluded, there is nothing to sample
        empty = _archive(space)
        assert empty.sample_parent(is_eligible=lambda c: True, include_origin=False) is None


# ---------------------------------------------------------------------------
class TestRestart:
    def test_restart_keeps_front_and_clears_tried(self, space):
        arc = _archive(space, restart_h=1)
        e = _mk(space, "a", "A!", 1.0, 0.1, 0.1)
        arc.try_add(e, 1)
        e.tried.add(("mut", "a", "m"))
        arc.origin.tried.add(("mut", "b", "m"))
        # force stagnation: one rejected attempt
        arc.try_add(_mk(space, "a", "A!", 1.0, 0.1, 0.1), 2)  # dup ⇒ attempts_since_insert++
        assert arc.should_restart()
        arc.restart(iteration=3)
        assert len(arc) == 1                     # front preserved
        assert e.tried == set()                  # exploration re-opened
        assert arc.origin.tried == set()
        assert arc.restart_history[-1]["front_size"] == 1


# ---------------------------------------------------------------------------
class TestBest:
    def test_best_includes_origin_floor(self, space):
        arc = _archive(space)
        # only a divergent-but-worse (f1<0) entry on the front
        arc.try_add(_mk(space, "a", "A!", -2.0, 0.5, 0.0), 1)
        assert arc.best() is arc.origin          # doing nothing (f1=0) beats f1=-2
        assert arc.best().f1 == 0.0

    def test_best_picks_highest_f1(self, space):
        arc = _archive(space)
        arc.try_add(_mk(space, "a", "A!", 2.0, 0.1, 0.1), 1)
        arc.try_add(_mk(space, "b", "B!", 1.0, 0.9, 0.1), 2)
        assert arc.best().f1 == 2.0
