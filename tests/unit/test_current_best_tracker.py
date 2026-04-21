"""Topic D — CurrentBestTracker unit tests (C-D5 to C-D8).

Validates mutation compounding, depth tracking, saturation, and snapshot
serialisation for the per-rule best-text tracker.
"""

import json
from dataclasses import dataclass

import pytest

from src.optimizer.hill_climber import CurrentBestTracker


# ---------------------------------------------------------------------------
# Helpers — lightweight PromptWithRules stand-in
# ---------------------------------------------------------------------------

@dataclass
class FakePromptWithRules:
    """Minimal stand-in for PromptWithRules used by CurrentBestTracker.from_prompts."""
    individual_rules: dict[str, str]


def _make_tracker(max_depth: int = 4) -> CurrentBestTracker:
    """Build a tracker with 2 rules from 2 fake prompts."""
    prompts = [
        FakePromptWithRules(individual_rules={
            "rule-A": "Original text of rule A.",
            "rule-B": "Original text of rule B.",
        }),
        # Second prompt shares rule-A — should deduplicate
        FakePromptWithRules(individual_rules={
            "rule-A": "Original text of rule A.",
            "rule-C": "Original text of rule C.",
        }),
    ]
    return CurrentBestTracker.from_prompts(prompts, max_depth=max_depth)


# ═══════════════════════════════════════════════════════════════════════════════
# C-D5  from_prompts + accept_mutation
# ═══════════════════════════════════════════════════════════════════════════════

class TestFromPrompts:

    def test_initialises_originals_and_current(self):
        """C-D5: from_prompts populates _originals and _current_best identically."""
        tracker = _make_tracker()

        for rid in ["rule-A", "rule-B", "rule-C"]:
            assert tracker.get_original(rid) == tracker.get_current(rid)
            assert tracker.depth(rid) == 0

    def test_deduplicates_rules(self):
        """Rules appearing in multiple prompts are stored once."""
        tracker = _make_tracker()
        # rule-A appears in both prompts — should only be stored once
        snapshot = tracker.snapshot()
        assert "rule-A" in snapshot
        assert len(snapshot) == 3  # A, B, C

    def test_accept_mutation_updates_state(self):
        """C-D5: accept_mutation increments depth and updates current_best."""
        tracker = _make_tracker()

        tracker.accept_mutation("rule-A", "Mutated A v1", drift=0.15)
        assert tracker.get_current("rule-A") == "Mutated A v1"
        assert tracker.get_original("rule-A") == "Original text of rule A."
        assert tracker.depth("rule-A") == 1

        # Accept a second mutation — compounding
        tracker.accept_mutation("rule-A", "Mutated A v2", drift=0.25)
        assert tracker.get_current("rule-A") == "Mutated A v2"
        assert tracker.depth("rule-A") == 2

    def test_accept_mutation_drift_optional(self):
        """Drift is None by default until provided."""
        tracker = _make_tracker()

        snap_before = tracker.snapshot()
        assert snap_before["rule-A"]["sbert_drift"] is None

        tracker.accept_mutation("rule-A", "Mutated A", drift=None)
        assert tracker.snapshot()["rule-A"]["sbert_drift"] is None

        tracker.accept_mutation("rule-A", "Mutated A v2", drift=0.3)
        assert tracker.snapshot()["rule-A"]["sbert_drift"] == pytest.approx(0.3)


# ═══════════════════════════════════════════════════════════════════════════════
# C-D6  is_saturated at max_depth
# ═══════════════════════════════════════════════════════════════════════════════

class TestSaturation:

    def test_saturates_at_max_depth(self):
        """C-D6: is_saturated returns True once depth == max_depth."""
        tracker = _make_tracker(max_depth=2)

        assert not tracker.is_saturated("rule-A")

        tracker.accept_mutation("rule-A", "v1")
        assert not tracker.is_saturated("rule-A")  # depth=1 < 2

        tracker.accept_mutation("rule-A", "v2")
        assert tracker.is_saturated("rule-A")  # depth=2 == max_depth

    def test_other_rules_unaffected(self):
        """Saturating one rule does not affect others."""
        tracker = _make_tracker(max_depth=1)

        tracker.accept_mutation("rule-A", "v1")
        assert tracker.is_saturated("rule-A")
        assert not tracker.is_saturated("rule-B")


# ═══════════════════════════════════════════════════════════════════════════════
# C-D7  Compounding: iteration N mutates iteration N-1's accepted output
# ═══════════════════════════════════════════════════════════════════════════════

class TestCompounding:

    def test_get_current_returns_latest_accepted(self):
        """C-D7: get_current returns the last accepted text, not the original."""
        tracker = _make_tracker()

        tracker.accept_mutation("rule-B", "Mutated B depth=1")
        assert tracker.get_current("rule-B") == "Mutated B depth=1"

        tracker.accept_mutation("rule-B", "Mutated B depth=2 (based on depth=1)")
        assert tracker.get_current("rule-B") == "Mutated B depth=2 (based on depth=1)"

        # Original is still preserved
        assert tracker.get_original("rule-B") == "Original text of rule B."


# ═══════════════════════════════════════════════════════════════════════════════
# C-D8  snapshot is JSON-serialisable
# ═══════════════════════════════════════════════════════════════════════════════

class TestSnapshot:

    def test_snapshot_serialisable(self):
        """C-D8: snapshot is JSON-serialisable and has expected keys."""
        tracker = _make_tracker(max_depth=3)
        tracker.accept_mutation("rule-A", "v1", drift=0.1)
        tracker.accept_mutation("rule-A", "v2", drift=0.2)

        snap = tracker.snapshot()

        # Must serialise without error
        json_str = json.dumps(snap)
        assert isinstance(json_str, str)

        # Check structure for rule-A
        assert snap["rule-A"]["depth"] == 2
        assert snap["rule-A"]["sbert_drift"] == pytest.approx(0.2)
        assert snap["rule-A"]["saturated"] is False

        # Check untouched rule
        assert snap["rule-B"]["depth"] == 0
        assert snap["rule-B"]["saturated"] is False

    def test_snapshot_reflects_saturation(self):
        tracker = _make_tracker(max_depth=1)
        tracker.accept_mutation("rule-C", "v1")

        snap = tracker.snapshot()
        assert snap["rule-C"]["saturated"] is True
        assert snap["rule-C"]["depth"] == 1
