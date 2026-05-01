"""
Multi-mutator pool with configurable selection strategies.

Supports random, round-robin, D-UCB-bandit, and greedy-batch selection
of (rule_id, mutator) pairs for the hill-climbing optimizer.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .base import Mutator


class MutatorSelectionStrategy(Enum):
    """How the pool picks the next (rule, mutator) pair."""

    RANDOM_UNIFORM = "random"
    ROUND_ROBIN = "round_robin"
    DUCB_BANDIT = "ducb"
    GREEDY_BATCH = "greedy_batch"
    DECAYING_UCB = "decaying_ucb"


@dataclass
class ArmStats:
    """Bandit statistics for a single mutator arm (D-UCB).

    ``pulls`` and ``total_reward`` are floats because the discount factor γ
    produces fractional counts after repeated decay steps.
    """

    pulls: float = 0.0
    total_reward: float = 0.0

    @property
    def mean_reward(self) -> float:
        return self.total_reward / self.pulls if self.pulls > 1e-9 else 0.0


@dataclass
class DecayingArmStats:
    """Per-arm decaying statistics for the DECAYING_UCB strategy.

    Unlike the global-decay ``ArmStats`` used by ``DUCB_BANDIT``, decay here is
    applied only to the arm being updated (per-pull decay), which is the standard
    formulation from Kocsis & Szepesvári (2006) sliding-window UCB.
    """

    gamma: float = 0.9
    pulls: float = 0.0
    total_reward: float = 0.0

    def update(self, reward: float) -> None:
        """Decay this arm's statistics then record the new observation."""
        self.pulls = self.gamma * self.pulls + 1.0
        self.total_reward = self.gamma * self.total_reward + reward

    @property
    def mean_reward(self) -> float:
        return self.total_reward / self.pulls if self.pulls > 1e-9 else 0.0


class MutatorPool:
    """Manages a set of mutators and selects among them per iteration.

    Parameters
    ----------
    mutators : list[Mutator]
        Available mutation operators.
    strategy : MutatorSelectionStrategy
        Selection algorithm.
    seed : int | None
        RNG seed for reproducibility.
    exploration : float
        Exploration constant *c* for D-UCB (default √2 ≈ 1.41).
    gamma : float
        Discount factor γ ∈ (0, 1] for D-UCB.  Each call to
        ``update_reward`` multiplies all stored arm statistics by γ before
        recording the new observation.  γ = 1.0 recovers standard UCB1.
        Ignored for non-bandit strategies.
    """

    def __init__(
        self,
        mutators: list[Mutator],
        strategy: MutatorSelectionStrategy = MutatorSelectionStrategy.ROUND_ROBIN,
        seed: int | None = None,
        exploration: float = 1.41,
        gamma: float = 0.9,
    ) -> None:
        if not mutators:
            raise ValueError("MutatorPool requires at least one mutator")

        self.mutators = list(mutators)
        self.strategy = strategy
        self.seed = seed
        self.exploration = exploration
        self.gamma = gamma

        self._by_name: dict[str, Mutator] = {m.name: m for m in self.mutators}
        self._rng = random.Random(seed)

        # Round-robin state (shared by ROUND_ROBIN and DECAYING_UCB rule selection)
        self._rr_index: int = 0

        # DUCB_BANDIT state: mutator-name → ArmStats (global decay)
        self._arm_stats: dict[str, ArmStats] = {}
        self._total_pulls: float = 0.0

        # DECAYING_UCB state: mutator-name → DecayingArmStats (per-arm decay)
        self._decay_stats: dict[str, DecayingArmStats] = {}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def select(self, rule_ids: list[str]) -> tuple[str | None, Mutator]:
        """Pick the next (rule_id, mutator) pair.

        Returns
        -------
        (rule_id, mutator) where rule_id is ``None`` only for GREEDY_BATCH
        (meaning "mutate all rules with this mutator").
        """
        if not rule_ids:
            raise ValueError("No active rule_ids to select from")

        if self.strategy is MutatorSelectionStrategy.RANDOM_UNIFORM:
            return self._select_random(rule_ids)
        elif self.strategy is MutatorSelectionStrategy.ROUND_ROBIN:
            return self._select_round_robin(rule_ids)
        elif self.strategy is MutatorSelectionStrategy.DUCB_BANDIT:
            return self._select_ducb(rule_ids)
        elif self.strategy is MutatorSelectionStrategy.GREEDY_BATCH:
            return self._select_greedy_batch()
        elif self.strategy is MutatorSelectionStrategy.DECAYING_UCB:
            return self._select_decaying_ucb(rule_ids)
        else:
            raise ValueError(f"Unknown strategy: {self.strategy}")

    def update_reward(self, rule_id: str, mutator_name: str, reward: float) -> None:
        """Record the reward for the selected mutator arm.

        For ``DUCB_BANDIT``: applies global discount (all arms decayed each step).
        For ``DECAYING_UCB``: applies per-arm decay (only the updated arm decays).
        Both strategies ignore ``rule_id`` — arms are indexed by mutator name only.
        """
        if self.strategy is MutatorSelectionStrategy.DECAYING_UCB:
            if mutator_name not in self._decay_stats:
                self._decay_stats[mutator_name] = DecayingArmStats(gamma=self.gamma)
            self._decay_stats[mutator_name].update(reward)
            self._total_pulls += 1.0
            return

        # DUCB_BANDIT (and other strategies): global discount step
        for stats in self._arm_stats.values():
            stats.pulls *= self.gamma
            stats.total_reward *= self.gamma
        self._total_pulls *= self.gamma

        if mutator_name not in self._arm_stats:
            self._arm_stats[mutator_name] = ArmStats()
        self._arm_stats[mutator_name].pulls += 1.0
        self._arm_stats[mutator_name].total_reward += reward
        self._total_pulls += 1.0

    def get_arm_summary(self) -> dict:
        """Serializable summary of all mutator arm statistics."""
        if self.strategy is MutatorSelectionStrategy.DECAYING_UCB:
            arms_source = self._decay_stats
        else:
            arms_source = self._arm_stats  # type: ignore[assignment]
        return {
            "strategy": self.strategy.value,
            "gamma": self.gamma,
            "total_pulls": round(self._total_pulls, 4),
            "arms": {
                mutator_name: {
                    "pulls": round(stats.pulls, 4),
                    "total_reward": round(stats.total_reward, 6),
                    "mean_reward": round(stats.mean_reward, 6),
                }
                for mutator_name, stats in sorted(arms_source.items())
            },
        }

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def mutator_names(self) -> list[str]:
        return [m.name for m in self.mutators]

    @property
    def is_bandit(self) -> bool:
        return self.strategy in (
            MutatorSelectionStrategy.DUCB_BANDIT,
            MutatorSelectionStrategy.DECAYING_UCB,
        )

    @property
    def is_batch(self) -> bool:
        return self.strategy is MutatorSelectionStrategy.GREEDY_BATCH

    # ------------------------------------------------------------------
    # Selection implementations
    # ------------------------------------------------------------------

    def _select_random(self, rule_ids: list[str]) -> tuple[str, Mutator]:
        rule_id = self._rng.choice(rule_ids)
        mutator = self._rng.choice(self.mutators)
        return rule_id, mutator

    def _select_round_robin(self, rule_ids: list[str]) -> tuple[str, Mutator]:
        # Build the full (rule, mutator) product and cycle through it
        pairs = [(rid, m) for rid in rule_ids for m in self.mutators]
        idx = self._rr_index % len(pairs)
        self._rr_index += 1
        rule_id, mutator = pairs[idx]
        return rule_id, mutator

    def _select_ducb(self, rule_ids: list[str]) -> tuple[str, Mutator]:
        """D-UCB over mutator-only arms; rule is chosen uniformly at random.

        Exploration phase: any mutator with discounted pull count below
        threshold is tried first (round-robin order).
        Exploitation phase: select the mutator with the highest UCB score.
        """
        # Exploration: pull any mutator not yet tried (or decayed to near-zero)
        for mutator in self.mutators:
            if self._arm_stats.get(mutator.name, ArmStats()).pulls < 1e-6:
                rule_id = self._rng.choice(rule_ids)
                return rule_id, mutator

        # Exploitation: UCB score = mean_reward + c * sqrt(ln(N) / n_i)
        best_score = -math.inf
        best_mutator: Mutator | None = None
        ln_N = math.log(max(self._total_pulls, 1e-9))

        for mutator in self.mutators:
            stats = self._arm_stats[mutator.name]
            n = max(stats.pulls, 1e-9)
            score = stats.mean_reward + self.exploration * math.sqrt(ln_N / n)
            if score > best_score:
                best_score = score
                best_mutator = mutator

        assert best_mutator is not None
        rule_id = self._rng.choice(rule_ids)
        return rule_id, best_mutator

    def _select_decaying_ucb(self, rule_ids: list[str]) -> tuple[str, Mutator]:
        """DECAYING_UCB over mutator-only arms; rule selected round-robin.

        Uses per-arm decay: only the updated arm's statistics are discounted on
        each pull (standard sliding-window UCB formulation).  Rule selection is
        decoupled from the bandit — rules rotate in round-robin order.
        """
        # Rule: round-robin (decoupled from bandit)
        rule_id = rule_ids[self._rr_index % len(rule_ids)]
        self._rr_index += 1

        # Explore: pull any mutator not yet tried
        for mutator in self.mutators:
            if mutator.name not in self._decay_stats or self._decay_stats[mutator.name].pulls < 1e-9:
                return rule_id, mutator

        # Exploit: highest UCB score
        best_score = -math.inf
        best_mutator: Mutator | None = None
        ln_N = math.log(max(self._total_pulls, 1e-9))

        for mutator in self.mutators:
            stats = self._decay_stats[mutator.name]
            n = max(stats.pulls, 1e-9)
            score = stats.mean_reward + self.exploration * math.sqrt(ln_N / n)
            if score > best_score:
                best_score = score
                best_mutator = mutator

        assert best_mutator is not None
        return rule_id, best_mutator

    def _select_greedy_batch(self) -> tuple[None, Mutator]:
        """GREEDY_BATCH: pick a mutator to apply to all rules."""
        mutator = self.mutators[self._rr_index % len(self.mutators)]
        self._rr_index += 1
        return None, mutator
