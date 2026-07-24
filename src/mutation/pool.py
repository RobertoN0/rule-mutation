"""
Mutator container for the archive EA and random-search optimizers.

Both optimizers do their own constrained random selection — the EA samples a
parent-eligible archive entry then an untried mutator; the random baseline
samples ``n`` distinct mutators per iteration — so they bypass any pool-level
selection. This class is therefore just a holder for the mutator list and the
RNG seed shared across a run.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .base import Mutator


class MutatorPool:
    """Holds the set of mutators and the RNG seed shared across a run.

    Parameters
    ----------
    mutators : list[Mutator]
        Available mutation operators (at least one).
    seed : int | None
        RNG seed, shared with the EA / random-baseline runner so a single
        seed reproduces the full run.
    """

    def __init__(
        self,
        mutators: list[Mutator],
        seed: int | None = None,
    ) -> None:
        if not mutators:
            raise ValueError("MutatorPool requires at least one mutator")

        self.mutators = list(mutators)
        self.seed = seed

    @property
    def mutator_names(self) -> list[str]:
        return [m.name for m in self.mutators]
