"""
Multi-mutator pool with configurable selection strategies.

Supports round-robin, D-UCB-bandit, and greedy-batch selection
of (rule_id, mutator) pairs for the hill-climbing optimizer.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .base import Mutator


class MutatorSelectionStrategy(Enum):
    """How the pool picks the next (rule, mutator) pair."""

    ROUND_ROBIN = "round_robin"
    DUCB_BANDIT = "ducb"
    GREEDY_BATCH = "greedy_batch"


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

        # Round-robin state
        self._rr_index: int = 0

        # DUCB_BANDIT state: mutator-name → ArmStats (global decay)
        self._arm_stats: dict[str, ArmStats] = {}
        self._total_pulls: float = 0.0

        # Cold-start guard: arm names that have ever received a pull. Independent
        # of the discounted pull count so that decayed arms are not re-cold-started.
        self._pulled_ever: set[str] = set()

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

        if self.strategy is MutatorSelectionStrategy.ROUND_ROBIN:
            return self._select_round_robin(rule_ids)
        elif self.strategy is MutatorSelectionStrategy.DUCB_BANDIT:
            return self._select_ducb(rule_ids)
        elif self.strategy is MutatorSelectionStrategy.GREEDY_BATCH:
            return self._select_greedy_batch()
        else:
            raise ValueError(f"Unknown strategy: {self.strategy}")

    def update_reward(self, rule_id: str, mutator_name: str, reward: float) -> None:
        """Record the reward for the selected mutator arm (D-UCB global decay).

        Applies global discount to all arms, then increments the pulled arm.
        ``rule_id`` is unused — arms are indexed by mutator name only.
        """
        for stats in self._arm_stats.values():
            stats.pulls *= self.gamma
            stats.total_reward *= self.gamma
        self._total_pulls *= self.gamma

        if mutator_name not in self._arm_stats:
            self._arm_stats[mutator_name] = ArmStats()
        self._arm_stats[mutator_name].pulls += 1.0
        self._arm_stats[mutator_name].total_reward += reward
        self._total_pulls += 1.0
        self._pulled_ever.add(mutator_name)

    def get_arm_summary(self) -> dict:
        """Serializable summary of all mutator arm statistics."""
        return {
            "strategy": self.strategy.value,
            "gamma": self.gamma,
            "total_pulls": round(self._total_pulls, 6),
            "arms": {
                mutator_name: {
                    "pulls": round(stats.pulls, 6),
                    "total_reward": round(stats.total_reward, 6),
                    "mean_reward": round(stats.mean_reward, 6),
                }
                for mutator_name, stats in sorted(self._arm_stats.items())
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
        return self.strategy is MutatorSelectionStrategy.DUCB_BANDIT

    @property
    def is_batch(self) -> bool:
        return self.strategy is MutatorSelectionStrategy.GREEDY_BATCH

    # ------------------------------------------------------------------
    # Selection implementations
    # ------------------------------------------------------------------

    def _select_round_robin(self, rule_ids: list[str]) -> tuple[str, Mutator]:
        # Build the full (rule, mutator) product and cycle through it
        pairs = [(rid, m) for rid in rule_ids for m in self.mutators]
        idx = self._rr_index % len(pairs)
        self._rr_index += 1
        rule_id, mutator = pairs[idx]
        return rule_id, mutator

    def _select_ducb(self, rule_ids: list[str]) -> tuple[str, Mutator]:
        """D-UCB over mutator-only arms; rule is chosen uniformly at random.

        Exploration phase: any mutator never pulled before is tried first.
        Exploitation phase: select the mutator with the highest UCB score.
        """
        # Exploration: pull any mutator never tried before. Decayed arms stay in the
        # exploitation path — their large UCB bonus already prefers them.
        for mutator in self.mutators:
            if mutator.name not in self._pulled_ever:
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

    def _select_greedy_batch(self) -> tuple[None, Mutator]:
        """GREEDY_BATCH: pick a mutator to apply to all rules."""
        mutator = self.mutators[self._rr_index % len(self.mutators)]
        self._rr_index += 1
        return None, mutator
