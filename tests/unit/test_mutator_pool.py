"""Topic D — MutatorPool unit tests (C-D1 to C-D4, C-D9, C-D10).

Validates selection strategies (ROUND_ROBIN, RANDOM_UNIFORM, UCB1_BANDIT,
GREEDY_BATCH), reward tracking, and arm summary serialisation.
"""

import math
from collections import Counter

import pytest

from src.mutation.base import Mutator, MutationResult
from src.mutation.pool import ArmStats, MutatorPool, MutatorSelectionStrategy


# ---------------------------------------------------------------------------
# Helpers — lightweight fake mutators
# ---------------------------------------------------------------------------

class FakeMutator(Mutator):
    """Minimal Mutator stub with a configurable name."""

    def __init__(self, fake_name: str, seed: int | None = None):
        super().__init__(seed)
        self._name = fake_name

    @property
    def name(self) -> str:
        return self._name

    def mutate(self, text: str) -> MutationResult:
        return MutationResult(
            original=text,
            mutated=f"[{self._name}]{text}",
            mutation_type=self._name,
            changes=[f"applied {self._name}"],
        )


def _make_pool(
    n_mutators: int = 3,
    strategy: str = "round_robin",
    seed: int = 42,
) -> tuple[MutatorPool, list[str]]:
    """Build a pool with *n_mutators* fake mutators and 2 rule_ids."""
    mutators = [FakeMutator(f"m{i}") for i in range(n_mutators)]
    pool = MutatorPool(
        mutators,
        strategy=MutatorSelectionStrategy(strategy),
        seed=seed,
    )
    rule_ids = ["rule-A", "rule-B"]
    return pool, rule_ids


# ═══════════════════════════════════════════════════════════════════════════════
# C-D1  ROUND_ROBIN cycles deterministically through (rule, mutator) pairs
# ═══════════════════════════════════════════════════════════════════════════════

class TestRoundRobin:

    def test_deterministic_cycle(self):
        """C-D1: 2 rules × 3 mutators = 6 pairs, then cycles."""
        pool, rule_ids = _make_pool(n_mutators=3, strategy="round_robin")

        # Collect first 12 selections (2 full cycles)
        selections = []
        for _ in range(12):
            rid, mut = pool.select(rule_ids)
            selections.append((rid, mut.name))

        # First 6 should be the full product in order
        expected_cycle = [
            ("rule-A", "m0"), ("rule-A", "m1"), ("rule-A", "m2"),
            ("rule-B", "m0"), ("rule-B", "m1"), ("rule-B", "m2"),
        ]
        assert selections[:6] == expected_cycle
        # Second cycle is identical
        assert selections[6:12] == expected_cycle

    def test_adapts_to_rule_removal(self):
        """Round-robin rebuilds product on each call, so removing a rule shrinks the cycle."""
        pool, _ = _make_pool(n_mutators=2, strategy="round_robin")

        # First call with 2 rules
        rid1, _ = pool.select(["rule-A", "rule-B"])
        assert rid1 == "rule-A"

        # Second call with only 1 rule — should still work
        rid2, mut2 = pool.select(["rule-B"])
        assert rid2 == "rule-B"


# ═══════════════════════════════════════════════════════════════════════════════
# C-D2  RANDOM_UNIFORM returns uniformly-distributed picks
# ═══════════════════════════════════════════════════════════════════════════════

class TestRandomUniform:

    def test_deterministic_with_seed(self):
        """C-D2: same seed → same sequence."""
        pool_a, rids = _make_pool(n_mutators=3, strategy="random", seed=123)
        pool_b, _ = _make_pool(n_mutators=3, strategy="random", seed=123)

        seq_a = [pool_a.select(rids) for _ in range(20)]
        seq_b = [pool_b.select(rids) for _ in range(20)]

        assert [(r, m.name) for r, m in seq_a] == [(r, m.name) for r, m in seq_b]

    def test_roughly_uniform(self):
        """C-D2: over many calls, distribution is approximately uniform."""
        pool, rids = _make_pool(n_mutators=2, strategy="random", seed=0)
        N = 2000
        counts: Counter[tuple[str, str]] = Counter()
        for _ in range(N):
            rid, mut = pool.select(rids)
            counts[(rid, mut.name)] += 1

        # 2 rules × 2 mutators = 4 bins, expect ~500 each
        for key, count in counts.items():
            assert 350 < count < 650, f"{key} got {count}, expected ~500"


# ═══════════════════════════════════════════════════════════════════════════════
# C-D3  UCB1_BANDIT: explore then exploit
# ═══════════════════════════════════════════════════════════════════════════════

class TestUCB1:

    def test_explore_all_arms_first(self):
        """C-D3: every arm is pulled once before any is pulled twice."""
        pool, rids = _make_pool(n_mutators=3, strategy="ucb1")
        n_arms = len(rids) * 3  # 6 arms

        seen_keys: set[tuple[str, str]] = set()
        for i in range(n_arms):
            rid, mut = pool.select(rids)
            key = (rid, mut.name)
            assert key not in seen_keys, f"Arm {key} pulled twice during exploration (pull {i})"
            seen_keys.add(key)
            # Record a reward so UCB1 has data
            pool.update_reward(rid, mut.name, reward=0.1 * (i + 1))

        assert len(seen_keys) == n_arms

    def test_ucb1_formula_exploit(self):
        """C-D3: after exploration, UCB1 selects the arm with highest score."""
        pool, rids = _make_pool(n_mutators=2, strategy="ucb1")
        n_arms = len(rids) * 2  # 4 arms

        # Pull each arm once (exploration)
        for _ in range(n_arms):
            rid, mut = pool.select(rids)
            pool.update_reward(rid, mut.name, reward=0.0)

        # Now give one arm a very high reward
        pool.update_reward("rule-A", "m0", reward=100.0)
        pool._arm_stats[("rule-A", "m0")].pulls += 1  # manual increment
        pool._total_pulls += 1

        # Manual UCB1 calculation for (rule-A, m0):
        stats = pool._arm_stats[("rule-A", "m0")]
        ln_total = math.log(pool._total_pulls)
        expected_score = stats.mean_reward + 1.41 * math.sqrt(ln_total / stats.pulls)

        # Next selection should pick the high-reward arm
        rid, mut = pool.select(rids)
        # It should be (rule-A, m0) because it has the highest UCB1 score
        assert (rid, mut.name) == ("rule-A", "m0"), \
            f"Expected (rule-A, m0) but got ({rid}, {mut.name})"


# ═══════════════════════════════════════════════════════════════════════════════
# C-D4  GREEDY_BATCH returns (None, mutator) with rotating mutator
# ═══════════════════════════════════════════════════════════════════════════════

class TestGreedyBatch:

    def test_returns_none_rule_id(self):
        """C-D4: rule_id is None for GREEDY_BATCH."""
        pool, rids = _make_pool(n_mutators=3, strategy="greedy_batch")
        rid, mut = pool.select(rids)
        assert rid is None

    def test_rotates_mutators(self):
        """C-D4: mutator rotates through the pool in order."""
        pool, rids = _make_pool(n_mutators=3, strategy="greedy_batch")

        names = []
        for _ in range(6):
            _, mut = pool.select(rids)
            names.append(mut.name)

        assert names == ["m0", "m1", "m2", "m0", "m1", "m2"]


# ═══════════════════════════════════════════════════════════════════════════════
# C-D9  update_reward + ArmStats
# ═══════════════════════════════════════════════════════════════════════════════

class TestRewardUpdate:

    def test_update_reward_creates_and_accumulates(self):
        """C-D9: update_reward creates ArmStats on first call and accumulates."""
        pool, _ = _make_pool(strategy="ucb1")

        pool.update_reward("r1", "m0", 1.5)
        pool.update_reward("r1", "m0", 2.5)
        pool.update_reward("r1", "m1", 0.0)

        stats_m0 = pool._arm_stats[("r1", "m0")]
        assert stats_m0.pulls == 2
        assert stats_m0.total_reward == pytest.approx(4.0)
        assert stats_m0.mean_reward == pytest.approx(2.0)

        stats_m1 = pool._arm_stats[("r1", "m1")]
        assert stats_m1.pulls == 1
        assert stats_m1.total_reward == pytest.approx(0.0)

        assert pool._total_pulls == 3

    def test_arm_stats_mean_reward_zero_pulls(self):
        """ArmStats.mean_reward returns 0.0 when pulls == 0."""
        stats = ArmStats()
        assert stats.mean_reward == 0.0


# ═══════════════════════════════════════════════════════════════════════════════
# C-D10  get_arm_summary is serialisable
# ═══════════════════════════════════════════════════════════════════════════════

class TestArmSummary:

    def test_serialisable(self):
        """C-D10: get_arm_summary returns a JSON-serialisable dict."""
        import json

        pool, rids = _make_pool(n_mutators=2, strategy="ucb1")
        pool.update_reward("rule-A", "m0", 1.0)
        pool.update_reward("rule-B", "m1", 0.5)

        summary = pool.get_arm_summary()

        # Must serialise without error
        json_str = json.dumps(summary)
        assert isinstance(json_str, str)

        # Structure checks
        assert summary["strategy"] == "ucb1"
        assert summary["total_pulls"] == 2
        assert "rule-A::m0" in summary["arms"]
        assert summary["arms"]["rule-A::m0"]["pulls"] == 1
        assert summary["arms"]["rule-A::m0"]["mean_reward"] == pytest.approx(1.0)


# ═══════════════════════════════════════════════════════════════════════════════
# Edge cases
# ═══════════════════════════════════════════════════════════════════════════════

class TestPoolEdgeCases:

    def test_empty_mutators_raises(self):
        with pytest.raises(ValueError, match="at least one mutator"):
            MutatorPool([], strategy=MutatorSelectionStrategy.ROUND_ROBIN)

    def test_empty_rule_ids_raises(self):
        pool, _ = _make_pool()
        with pytest.raises(ValueError, match="No active rule_ids"):
            pool.select([])

    def test_properties(self):
        pool, _ = _make_pool(n_mutators=2, strategy="ucb1")
        assert pool.mutator_names == ["m0", "m1"]
        assert pool.is_bandit is True
        assert pool.is_batch is False

        pool2, _ = _make_pool(strategy="greedy_batch")
        assert pool2.is_batch is True
        assert pool2.is_bandit is False
