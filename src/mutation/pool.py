"""
Multi-mutator pool with configurable selection strategies.

Supports random, round-robin, UCB1-bandit, and greedy-batch selection
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
    UCB1_BANDIT = "ucb1"
    GREEDY_BATCH = "greedy_batch"


@dataclass
class ArmStats:
    """Bandit statistics for a single (rule_id, mutator_name) arm."""

    pulls: int = 0
    total_reward: float = 0.0

    @property
    def mean_reward(self) -> float:
        return self.total_reward / self.pulls if self.pulls > 0 else 0.0


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
    ucb1_exploration : float
        Exploration constant *c* for UCB1 (default √2 ≈ 1.41).
    """

    def __init__(
        self,
        mutators: list[Mutator],
        strategy: MutatorSelectionStrategy = MutatorSelectionStrategy.ROUND_ROBIN,
        seed: int | None = None,
        ucb1_exploration: float = 1.41,
    ) -> None:
        if not mutators:
            raise ValueError("MutatorPool requires at least one mutator")

        self.mutators = list(mutators)
        self.strategy = strategy
        self.seed = seed
        self.ucb1_exploration = ucb1_exploration

        self._by_name: dict[str, Mutator] = {m.name: m for m in self.mutators}
        self._rng = random.Random(seed)

        # Round-robin state
        self._rr_index: int = 0

        # UCB1 state
        self._arm_stats: dict[tuple[str, str], ArmStats] = {}
        self._total_pulls: int = 0

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
        elif self.strategy is MutatorSelectionStrategy.UCB1_BANDIT:
            return self._select_ucb1(rule_ids)
        elif self.strategy is MutatorSelectionStrategy.GREEDY_BATCH:
            return self._select_greedy_batch()
        else:
            raise ValueError(f"Unknown strategy: {self.strategy}")

    def update_reward(self, rule_id: str, mutator_name: str, reward: float) -> None:
        """Record the reward for a pulled arm."""
        key = (rule_id, mutator_name)
        if key not in self._arm_stats:
            self._arm_stats[key] = ArmStats()
        self._arm_stats[key].pulls += 1
        self._arm_stats[key].total_reward += reward
        self._total_pulls += 1

    def get_arm_summary(self) -> dict:
        """Serializable summary of all arm statistics."""
        return {
            "strategy": self.strategy.value,
            "total_pulls": self._total_pulls,
            "arms": {
                f"{rule_id}::{mutator_name}": {
                    "pulls": stats.pulls,
                    "total_reward": round(stats.total_reward, 6),
                    "mean_reward": round(stats.mean_reward, 6),
                }
                for (rule_id, mutator_name), stats in sorted(self._arm_stats.items())
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
        return self.strategy is MutatorSelectionStrategy.UCB1_BANDIT

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

    def _select_ucb1(self, rule_ids: list[str]) -> tuple[str, Mutator]:
        """UCB1 selection over (rule_id, mutator_name) arms."""
        pairs = [(rid, m) for rid in rule_ids for m in self.mutators]

        # Explore: pull any arm that hasn't been tried yet
        for rule_id, mutator in pairs:
            key = (rule_id, mutator.name)
            if key not in self._arm_stats or self._arm_stats[key].pulls == 0:
                return rule_id, mutator

        # Exploit: pick arm with highest UCB1 score
        best_score = -math.inf
        best_pair: tuple[str, Mutator] | None = None
        ln_total = math.log(self._total_pulls)

        for rule_id, mutator in pairs:
            stats = self._arm_stats[(rule_id, mutator.name)]
            ucb1 = stats.mean_reward + self.ucb1_exploration * math.sqrt(
                ln_total / stats.pulls
            )
            if ucb1 > best_score:
                best_score = ucb1
                best_pair = (rule_id, mutator)

        assert best_pair is not None
        return best_pair

    def _select_greedy_batch(self) -> tuple[None, Mutator]:
        """GREEDY_BATCH: pick a mutator to apply to all rules."""
        mutator = self.mutators[self._rr_index % len(self.mutators)]
        self._rr_index += 1
        return None, mutator
