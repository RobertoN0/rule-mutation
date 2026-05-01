"""Unit tests for MutatorPool after Change 4 (D-UCB, mutator-only arms).

Covers:
  C-D1  ROUND_ROBIN cycles deterministically through (rule, mutator) pairs
  C-D2  RANDOM_UNIFORM returns uniformly-distributed picks
  C-D3  DUCB_BANDIT: explore then exploit; mutator-only arms; discount decay
  C-D4  GREEDY_BATCH returns (None, mutator) with rotating mutator
  C-D9  update_reward + ArmStats
  C-D10 get_arm_summary is serialisable
"""

import math
from collections import Counter

import pytest

from src.mutation.base import Mutator, MutationResult
from src.mutation.pool import ArmStats, DecayingArmStats, MutatorPool, MutatorSelectionStrategy


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
    gamma: float = 1.0,
) -> tuple[MutatorPool, list[str]]:
    """Build a pool with *n_mutators* fake mutators and 2 rule_ids."""
    mutators = [FakeMutator(f"m{i}") for i in range(n_mutators)]
    pool = MutatorPool(
        mutators,
        strategy=MutatorSelectionStrategy(strategy),
        seed=seed,
        gamma=gamma,
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

        selections = []
        for _ in range(12):
            rid, mut = pool.select(rule_ids)
            selections.append((rid, mut.name))

        expected_cycle = [
            ("rule-A", "m0"), ("rule-A", "m1"), ("rule-A", "m2"),
            ("rule-B", "m0"), ("rule-B", "m1"), ("rule-B", "m2"),
        ]
        assert selections[:6] == expected_cycle
        assert selections[6:12] == expected_cycle

    def test_adapts_to_rule_removal(self):
        """Round-robin rebuilds product on each call, so removing a rule shrinks the cycle."""
        pool, _ = _make_pool(n_mutators=2, strategy="round_robin")
        rid1, _ = pool.select(["rule-A", "rule-B"])
        assert rid1 == "rule-A"
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

        for key, count in counts.items():
            assert 350 < count < 650, f"{key} got {count}, expected ~500"


# ═══════════════════════════════════════════════════════════════════════════════
# C-D3  DUCB_BANDIT: explore then exploit, mutator-only arms, discount decay
# ═══════════════════════════════════════════════════════════════════════════════

class TestDUCB:

    def test_explore_all_mutators_first(self):
        """C-D3: every mutator is pulled once before any is pulled twice (γ=1)."""
        pool, rids = _make_pool(n_mutators=3, strategy="ducb", gamma=1.0)
        n_arms = 3  # mutator-only arms

        seen_mutators: set[str] = set()
        for i in range(n_arms):
            rid, mut = pool.select(rids)
            assert mut.name not in seen_mutators, \
                f"Mutator {mut.name} pulled twice during exploration (pull {i})"
            seen_mutators.add(mut.name)
            pool.update_reward(rid, mut.name, reward=0.1 * (i + 1))

        assert len(seen_mutators) == n_arms

    def test_exploration_covers_only_mutators_not_rules(self):
        """C-D3: arm count equals number of mutators, not rules × mutators."""
        pool, rids = _make_pool(n_mutators=2, strategy="ducb", gamma=1.0)
        # With 2 rules and 2 mutators, old UCB1 needed 4 pulls for exploration.
        # D-UCB needs only 2 (mutator-only arms).
        seen_mutators: set[str] = set()
        for _ in range(2):
            rid, mut = pool.select(rids)
            seen_mutators.add(mut.name)
            pool.update_reward(rid, mut.name, reward=0.0)
        assert len(seen_mutators) == 2

    def test_exploit_picks_highest_reward_mutator(self):
        """C-D3: after exploration, D-UCB selects the mutator with highest UCB score."""
        pool, rids = _make_pool(n_mutators=2, strategy="ducb", gamma=1.0)

        # Exploration: pull each mutator once
        for _ in range(2):
            rid, mut = pool.select(rids)
            pool.update_reward(rid, mut.name, reward=0.0)

        # Give m0 a very high reward
        pool.update_reward("rule-A", "m0", reward=100.0)

        # Manual UCB score for m0: mean_reward is dominant
        stats_m0 = pool._arm_stats["m0"]
        ln_N = math.log(pool._total_pulls)
        expected = stats_m0.mean_reward + 1.41 * math.sqrt(ln_N / stats_m0.pulls)

        rid, mut = pool.select(rids)
        assert mut.name == "m0", f"Expected m0 (high reward) but got {mut.name}"

    def test_rule_selected_uniformly(self):
        """C-D3: rule selection is uniform random (both rules appear over many calls)."""
        pool, rids = _make_pool(n_mutators=1, strategy="ducb", gamma=1.0, seed=0)
        rules_seen: Counter[str] = Counter()
        for _ in range(100):
            rid, mut = pool.select(rids)
            pool.update_reward(rid, mut.name, reward=0.0)
            rules_seen[rid] += 1
        # Both rules should appear
        assert len(rules_seen) == 2
        # Roughly equal (allow wide margin)
        assert 20 < rules_seen["rule-A"] < 80

    def test_discount_decays_old_rewards(self):
        """C-D3: with γ < 1, old rewards decay and recent rewards dominate."""
        pool, rids = _make_pool(n_mutators=2, strategy="ducb", gamma=0.5)

        # First: give m0 a high reward in early rounds
        pool.update_reward("rule-A", "m0", reward=10.0)
        pool.update_reward("rule-A", "m1", reward=0.0)

        stats_m0_after_2 = pool._arm_stats["m0"].total_reward

        # Now give m1 a high reward after many more updates (decay should reduce m0's lead)
        for _ in range(5):
            pool.update_reward("rule-A", "m1", reward=8.0)

        # m0's reward should have decayed substantially
        # After 5 more updates with γ=0.5: m0's reward decays by 0.5^5 = 0.03125
        m0_reward = pool._arm_stats["m0"].total_reward
        assert m0_reward < stats_m0_after_2, "Discount should reduce m0's stored reward over time"

    def test_gamma_one_equals_undiscounted(self):
        """With γ=1.0, pulls accumulate exactly (no decay)."""
        pool, rids = _make_pool(n_mutators=2, strategy="ducb", gamma=1.0)
        for _ in range(3):
            pool.update_reward("rule-A", "m0", reward=1.0)
        # 3 pulls, each undiscounted → total_reward = 3.0
        assert pool._arm_stats["m0"].total_reward == pytest.approx(3.0)
        assert pool._arm_stats["m0"].pulls == pytest.approx(3.0)

    def test_arms_are_mutator_only_not_rule_mutator(self):
        """C-D3: arm keys are mutator names, not (rule_id, mutator_name) tuples."""
        pool, rids = _make_pool(n_mutators=2, strategy="ducb", gamma=1.0)
        pool.update_reward("rule-A", "m0", reward=1.0)
        pool.update_reward("rule-B", "m0", reward=2.0)
        # Both rewards should go to the same 'm0' arm
        assert "m0" in pool._arm_stats
        assert pool._arm_stats["m0"].pulls == pytest.approx(2.0)
        assert pool._arm_stats["m0"].total_reward == pytest.approx(3.0)


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
        names = [pool.select(rids)[1].name for _ in range(6)]
        assert names == ["m0", "m1", "m2", "m0", "m1", "m2"]


# ═══════════════════════════════════════════════════════════════════════════════
# C-D9  update_reward + ArmStats
# ═══════════════════════════════════════════════════════════════════════════════

class TestRewardUpdate:

    def test_update_reward_creates_and_accumulates(self):
        """C-D9: update_reward creates ArmStats on first call and accumulates (γ=1)."""
        pool, _ = _make_pool(strategy="ducb", gamma=1.0)

        pool.update_reward("r1", "m0", 1.5)
        pool.update_reward("r1", "m0", 2.5)
        pool.update_reward("r1", "m1", 0.0)

        stats_m0 = pool._arm_stats["m0"]
        assert stats_m0.pulls == pytest.approx(2.0)
        assert stats_m0.total_reward == pytest.approx(4.0)
        assert stats_m0.mean_reward == pytest.approx(2.0)

        stats_m1 = pool._arm_stats["m1"]
        assert stats_m1.pulls == pytest.approx(1.0)
        assert stats_m1.total_reward == pytest.approx(0.0)

        assert pool._total_pulls == pytest.approx(3.0)

    def test_arm_stats_mean_reward_zero_pulls(self):
        """ArmStats.mean_reward returns 0.0 when pulls ≈ 0."""
        stats = ArmStats()
        assert stats.mean_reward == 0.0


# ═══════════════════════════════════════════════════════════════════════════════
# C-D10  get_arm_summary is serialisable
# ═══════════════════════════════════════════════════════════════════════════════

class TestArmSummary:

    def test_serialisable(self):
        """C-D10: get_arm_summary returns a JSON-serialisable dict."""
        import json

        pool, rids = _make_pool(n_mutators=2, strategy="ducb", gamma=0.9)
        pool.update_reward("rule-A", "m0", 1.0)
        pool.update_reward("rule-B", "m1", 0.5)

        summary = pool.get_arm_summary()

        json_str = json.dumps(summary)
        assert isinstance(json_str, str)

        assert summary["strategy"] == "ducb"
        assert "gamma" in summary
        assert "m0" in summary["arms"]
        assert summary["arms"]["m0"]["mean_reward"] == pytest.approx(1.0, abs=0.1)

    def test_arm_keys_are_mutator_names(self):
        """C-D10: arm keys are plain mutator names, not rule::mutator format."""
        pool, rids = _make_pool(n_mutators=2, strategy="ducb")
        pool.update_reward("rule-A", "m0", 1.0)
        summary = pool.get_arm_summary()
        assert "m0" in summary["arms"]
        assert "rule-A::m0" not in summary["arms"]


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
        pool, _ = _make_pool(n_mutators=2, strategy="ducb")
        assert pool.mutator_names == ["m0", "m1"]
        assert pool.is_bandit is True
        assert pool.is_batch is False

        pool2, _ = _make_pool(strategy="greedy_batch")
        assert pool2.is_batch is True
        assert pool2.is_bandit is False


# ═══════════════════════════════════════════════════════════════════════════════
# DECAYING_UCB — per-arm decay strategy
# ═══════════════════════════════════════════════════════════════════════════════

class TestDecayingUCB:

    def test_explore_all_mutators_first(self):
        """Every mutator pulled once before any is pulled twice."""
        pool, rids = _make_pool(n_mutators=3, strategy="decaying_ucb", gamma=0.9)
        seen: set[str] = set()
        for _ in range(3):
            rid, mut = pool.select(rids)
            assert mut.name not in seen, f"{mut.name} pulled twice during exploration"
            seen.add(mut.name)
            pool.update_reward(rid, mut.name, reward=0.5)
        assert len(seen) == 3

    def test_rule_selected_round_robin(self):
        """Rule selection cycles in round-robin order (decoupled from bandit)."""
        pool, rids = _make_pool(n_mutators=1, strategy="decaying_ucb", seed=0)
        # With 2 rules round-robin: A, B, A, B, ...
        selections = [pool.select(rids)[0] for _ in range(4)]
        assert selections == ["rule-A", "rule-B", "rule-A", "rule-B"]

    def test_per_arm_decay_only_affects_updated_arm(self):
        """Per-arm decay: unupdated arm stats are NOT changed on other arm's update."""
        pool, rids = _make_pool(n_mutators=2, strategy="decaying_ucb", gamma=0.5)

        # Pull m0 once
        pool.update_reward("rule-A", "m0", reward=1.0)
        pulls_m0_before = pool._decay_stats["m0"].pulls   # should be 1.0

        # Pull m1 — m0 should NOT be decayed by this
        pool.update_reward("rule-A", "m1", reward=1.0)

        assert pool._decay_stats["m0"].pulls == pytest.approx(pulls_m0_before), \
            "m0 should not decay when m1 is updated (per-arm decay)"

    def test_per_arm_decay_formula(self):
        """DecayingArmStats.update(): pulls = γ*pulls+1, total_reward = γ*reward+reward."""
        stats = DecayingArmStats(gamma=0.5)
        stats.update(1.0)
        # First pull: pulls = 0.5*0 + 1 = 1.0; reward = 0.5*0 + 1.0 = 1.0
        assert stats.pulls == pytest.approx(1.0)
        assert stats.total_reward == pytest.approx(1.0)

        stats.update(0.0)
        # Second pull: pulls = 0.5*1 + 1 = 1.5; reward = 0.5*1.0 + 0.0 = 0.5
        assert stats.pulls == pytest.approx(1.5)
        assert stats.total_reward == pytest.approx(0.5)

    def test_exploit_picks_highest_reward_after_exploration(self):
        """After exploration, selects the mutator with highest UCB score."""
        pool, rids = _make_pool(n_mutators=2, strategy="decaying_ucb", gamma=0.9)

        # Exploration: pull each mutator once
        for _ in range(2):
            rid, mut = pool.select(rids)
            pool.update_reward(rid, mut.name, reward=0.0)

        # Give m0 a very high reward
        pool.update_reward("rule-A", "m0", reward=100.0)

        rid, mut = pool.select(rids)
        assert mut.name == "m0"

    def test_is_bandit_true_for_decaying_ucb(self):
        """is_bandit returns True for DECAYING_UCB strategy."""
        pool, _ = _make_pool(n_mutators=2, strategy="decaying_ucb")
        assert pool.is_bandit is True

    def test_arm_summary_uses_decay_stats(self):
        """get_arm_summary reflects _decay_stats for DECAYING_UCB."""
        pool, _ = _make_pool(n_mutators=2, strategy="decaying_ucb", gamma=0.9)
        pool.update_reward("rule-A", "m0", reward=1.0)
        summary = pool.get_arm_summary()
        assert summary["strategy"] == "decaying_ucb"
        assert "m0" in summary["arms"]
        assert summary["arms"]["m0"]["pulls"] == pytest.approx(1.0)

    def test_negative_reward_not_clipped(self):
        """Negative rewards are stored as-is — no max(0, ...) clipping."""
        pool, rids = _make_pool(n_mutators=2, strategy="decaying_ucb", gamma=0.9)
        pool.update_reward("rule-A", "m0", reward=-0.5)
        assert pool._decay_stats["m0"].total_reward < 0.0, \
            "Negative reward must be stored (signed); clipping to 0 is incorrect"

    def test_negative_reward_ducb_not_clipped(self):
        """DUCB_BANDIT also stores negative rewards without clipping."""
        pool, rids = _make_pool(n_mutators=2, strategy="ducb", gamma=1.0)
        pool.update_reward("rule-A", "m0", reward=-1.0)
        assert pool._arm_stats["m0"].total_reward < 0.0, \
            "Negative reward must be stored for DUCB_BANDIT too"
