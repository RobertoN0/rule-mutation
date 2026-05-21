"""
Per-rule Pareto archive for the (1+1) EA optimizer.

Architecture (locked 2026-05-08 supervisor meeting):
    Objectives (all maximised):
        f1 = total_semgrep_delta          (sum of per-prompt composite scores)
        f2 = proportion_divergent         (n_divergent_prompts / num_prompts)
        f3 = conditional_mean_divergence  (total_code_divergence / n_divergent_prompts)

    Each :class:`ArchiveEntry` carries the rule_text that produced its fitness
    plus per-entry state used by the (1+1) EA's parent sampler:

        depth           — number of mutations from the original (cap = max_depth)
        tried_mutators  — set of mutator names already applied to *this* entry
                          (strict per-name dedup; stochastic mutators get one shot)

Restart triggers (any of):
    1. ``h`` consecutive *attempts on this archive* without an insertion
       (stagnation). The counter is per-archive: it only advances when
       ``try_add`` is called on this rule's archive (i.e. this rule was
       picked AND the mutator produced text). With N rules and uniform
       parent sampling, each archive sees ~``max_iterations/N`` attempts
       in a full run, so ``restart_h`` should be set as a fraction of that
       envelope, NOT as a raw EA loop length.
    2. all entries have ``depth >= max_depth``                   (depth_saturated)
    3. all entries have ``len(tried_mutators) == n_mutators``    (mutator_exhausted)

On restart the archive snapshots its state into ``restart_history`` and
re-seeds with a single depth-0 entry holding the original rule + baseline
fitness.
"""

from __future__ import annotations

import hashlib
import random
from dataclasses import dataclass, field
from typing import Any

from ..evaluation.fitness import AggregatedFitness


# Tolerance for Pareto dominance comparisons. Matches the existing tol convention
# in optimizer/hill_climber.py (_dominates).
_TOL: float = 1e-9


@dataclass
class ArchiveEntry:
    """One Pareto-front member for a rule."""

    rule_text: str
    f1: float                           # total_semgrep_delta
    f2: float                           # proportion_divergent
    f3: float                           # conditional_mean_divergence
    depth: int
    tried_mutators: set[str] = field(default_factory=set)
    iteration_added: int = 0
    mutation_path: list[str] = field(default_factory=list)
    fitness: AggregatedFitness | None = None

    def score_sum(self) -> float:
        """f1+f2+f3 — used as the eviction key on archive overflow."""
        return self.f1 + self.f2 + self.f3

    def dominates(self, other: "ArchiveEntry") -> bool:
        """True iff self Pareto-dominates other on (f1, f2, f3) maximised."""
        ge1 = self.f1 >= other.f1 - _TOL
        ge2 = self.f2 >= other.f2 - _TOL
        ge3 = self.f3 >= other.f3 - _TOL
        if not (ge1 and ge2 and ge3):
            return False
        # Strict on at least one axis
        return (
            self.f1 > other.f1 + _TOL
            or self.f2 > other.f2 + _TOL
            or self.f3 > other.f3 + _TOL
        )

    def is_depth_saturated(self, max_depth: int) -> bool:
        return self.depth >= max_depth

    def is_mutator_exhausted(self, n_mutators: int) -> bool:
        return len(self.tried_mutators) >= n_mutators

    def is_parent_eligible(self, max_depth: int, n_mutators: int) -> bool:
        return not (
            self.is_depth_saturated(max_depth) or self.is_mutator_exhausted(n_mutators)
        )

    def snapshot(self) -> dict[str, Any]:
        """Full JSON-serialisable archive entry — includes rule_text so the
        post-run JSON contains the complete archive without needing to
        reconstruct rule texts from per-iteration mutated_rules/ files."""
        return {
            "f1": round(self.f1, 6),
            "f2": round(self.f2, 6),
            "f3": round(self.f3, 6),
            "depth": self.depth,
            "tried_mutators": sorted(self.tried_mutators),
            "iteration_added": self.iteration_added,
            "mutation_path": list(self.mutation_path),
            "rule_text": self.rule_text,
            "rule_text_length": len(self.rule_text),
        }


class ParetoArchive:
    """Per-rule Pareto archive for the (1+1) EA + uniform-random parent baseline.

    Invariants
    ----------
    * No two members dominate each other.
    * ``len(self.entries) <= cap`` (eviction triggers when an insert exceeds cap).
    * After ``__init__`` and after every ``restart()``, the archive holds exactly
      one depth-0 entry whose ``rule_text`` is the original rule.

    Parameters
    ----------
    original_text :
        The unmutated rule. Seeds the archive and is re-injected on restart.
    baseline_fitness :
        Aggregated fitness for the rule's original text. Its (f1, f2, f3) is
        always (0, 0, 0) by construction — composite_score is zero-delta vs
        itself and divergence is zero against the baseline code.
    cap :
        Maximum archive size before eviction.
    restart_h :
        Number of consecutive non-inserting *attempts on this archive* that
        triggers a stagnation restart. Counted only when ``try_add`` is
        invoked on this archive — NOT once per EA loop iteration.
    max_depth :
        Cap on per-entry depth (mutations from original).
    n_mutators :
        Total number of mutators in the pool. Required for mutator-exhaustion
        detection. Set by the EA runner at construction time.
    rng :
        Random source. Must be the same RNG shared with the EA runner so a
        single seed reproduces the full run.
    """

    def __init__(
        self,
        original_text: str,
        baseline_fitness: AggregatedFitness,
        *,
        cap: int,
        restart_h: int,
        max_depth: int,
        n_mutators: int,
        rng: random.Random,
    ) -> None:
        if cap < 1:
            raise ValueError(f"cap must be >= 1, got {cap}")
        if restart_h < 1:
            raise ValueError(f"restart_h must be >= 1, got {restart_h}")
        if max_depth < 1:
            raise ValueError(f"max_depth must be >= 1, got {max_depth}")
        if n_mutators < 1:
            raise ValueError(f"n_mutators must be >= 1, got {n_mutators}")

        self._original_text = original_text
        self._baseline_fitness = baseline_fitness
        self.cap = cap
        self.restart_h = restart_h
        self.max_depth = max_depth
        self.n_mutators = n_mutators
        self._rng = rng

        self.entries: list[ArchiveEntry] = []
        # Count of try_add calls on THIS archive since its last successful
        # insert. NOT a count of EA loop iterations — see class docstring.
        self._attempts_since_insert: int = 0
        self.restart_history: list[dict[str, Any]] = []
        self.n_inserts: int = 0
        self.n_rejected: int = 0
        self.n_identity_rejected: int = 0

        self._seed_with_original(iteration=0)

    # ------------------------------------------------------------------
    # Seeding / restart
    # ------------------------------------------------------------------

    def _seed_with_original(self, iteration: int) -> None:
        """Reset to a single depth-0 entry holding the original rule."""
        self.entries = [
            ArchiveEntry(
                rule_text=self._original_text,
                f1=self._baseline_fitness.total_semgrep_delta,
                f2=self._baseline_fitness.proportion_divergent,
                f3=self._baseline_fitness.conditional_mean_divergence,
                depth=0,
                tried_mutators=set(),
                iteration_added=iteration,
                mutation_path=[],
                fitness=self._baseline_fitness,
            )
        ]
        self._attempts_since_insert = 0

    def restart(self, current_iteration: int, reason: str) -> None:
        """Snapshot pre-reset state into restart_history, then re-seed."""
        self.restart_history.append({
            "iteration": current_iteration,
            "reason": reason,
            "archive_size_before_reset": len(self.entries),
            "entries_before_reset": [e.snapshot() for e in self.entries],
        })
        self._seed_with_original(iteration=current_iteration)

    def should_restart(self) -> tuple[bool, str | None]:
        """Check restart triggers in priority order.

        Returns
        -------
        (True, reason) where reason is one of
            "stagnation"          — h consecutive non-inserts
            "depth_saturated"     — every entry at depth >= max_depth
            "mutator_exhausted"   — every entry has tried every mutator
            "fully_exhausted"     — every entry blocked for any reason
        or (False, None) when at least one entry is still parent-eligible.
        """
        if self._attempts_since_insert >= self.restart_h:
            return True, "stagnation"

        eligible = [e for e in self.entries if e.is_parent_eligible(self.max_depth, self.n_mutators)]
        if eligible:
            return False, None

        # No parent-eligible entry — classify the reason
        all_depth = all(e.is_depth_saturated(self.max_depth) for e in self.entries)
        all_mutator = all(e.is_mutator_exhausted(self.n_mutators) for e in self.entries)
        if all_depth and not all_mutator:
            return True, "depth_saturated"
        if all_mutator and not all_depth:
            return True, "mutator_exhausted"
        return True, "fully_exhausted"

    # ------------------------------------------------------------------
    # Parent / mutator sampling
    # ------------------------------------------------------------------

    def sample_parent(self) -> ArchiveEntry | None:
        """Uniform random sample from parent-eligible entries.

        Returns None when no entry is eligible (caller should restart).
        """
        eligible = [e for e in self.entries if e.is_parent_eligible(self.max_depth, self.n_mutators)]
        if not eligible:
            return None
        return self._rng.choice(eligible)

    def available_mutators(self, entry: ArchiveEntry, all_mutator_names: list[str]) -> list[str]:
        """Mutator names not yet tried on ``entry``."""
        return [m for m in all_mutator_names if m not in entry.tried_mutators]

    def mark_tried(self, entry: ArchiveEntry, mutator_name: str) -> None:
        """Record that ``mutator_name`` has been applied to ``entry``.

        Must be called after every application regardless of whether the
        offspring entered the archive — otherwise rejected offspring would let
        the same (parent, mutator) pair be retried forever.
        """
        entry.tried_mutators.add(mutator_name)

    # ------------------------------------------------------------------
    # Insertion
    # ------------------------------------------------------------------

    def try_add(
        self,
        candidate_text: str,
        candidate_fitness: AggregatedFitness,
        iteration: int,
        parent: ArchiveEntry,
        mutator_name: str,
    ) -> bool:
        """Offer a candidate to the archive.

        Returns True iff the candidate entered the archive (i.e. was not
        dominated by any existing member). On entry, any existing members it
        dominates are evicted; if the resulting size exceeds ``cap``, the
        member with the lowest f1+f2+f3 is evicted.

        Notes
        -----
        Does NOT mark the parent's mutator as tried — the EA runner must call
        ``mark_tried`` separately, because that bookkeeping is required even
        for rejected offspring.
        """
        candidate_hash = hashlib.sha256(candidate_text.encode("utf-8")).digest()
        for existing in self.entries:
            existing_hash = hashlib.sha256(existing.rule_text.encode("utf-8")).digest()
            if existing_hash == candidate_hash and existing.rule_text == candidate_text:
                self._attempts_since_insert += 1
                self.n_rejected += 1
                self.n_identity_rejected += 1
                return False

        candidate = ArchiveEntry(
            rule_text=candidate_text,
            f1=candidate_fitness.total_semgrep_delta,
            f2=candidate_fitness.proportion_divergent,
            f3=candidate_fitness.conditional_mean_divergence,
            depth=parent.depth + 1,
            tried_mutators=set(),
            iteration_added=iteration,
            mutation_path=list(parent.mutation_path) + [mutator_name],
            fitness=candidate_fitness,
        )

        # Reject if any existing member dominates the candidate
        for existing in self.entries:
            if existing.dominates(candidate):
                self._attempts_since_insert += 1
                self.n_rejected += 1
                return False

        # Accept — evict members the candidate dominates
        survivors = [e for e in self.entries if not candidate.dominates(e)]
        survivors.append(candidate)

        # Overflow eviction: drop the lowest-sum entry. Never drop the candidate
        # we just added (its sum is what justified the insert) — break ties by
        # preferring to keep newer entries.
        if len(survivors) > self.cap:
            # Find min by score_sum; on tie keep newer (later iteration_added)
            evict_idx = min(
                range(len(survivors)),
                key=lambda i: (survivors[i].score_sum(), survivors[i].iteration_added),
            )
            survivors.pop(evict_idx)

        self.entries = survivors
        self._attempts_since_insert = 0
        self.n_inserts += 1
        return True

    # ------------------------------------------------------------------
    # Inspection
    # ------------------------------------------------------------------

    def __len__(self) -> int:
        return len(self.entries)

    def snapshot(self) -> dict[str, Any]:
        """Full serialisable state for hillclimb_per_rule_*.json."""
        return {
            "cap": self.cap,
            "restart_h": self.restart_h,
            "max_depth": self.max_depth,
            "n_mutators": self.n_mutators,
            # JSON key kept as "iterations_since_insert" for backward compat with
            # historical hillclimb_per_rule_*.json consumers. The semantic name
            # is "attempts since insert" — see ParetoArchive docstring.
            "iterations_since_insert": self._attempts_since_insert,
            "attempts_since_insert": self._attempts_since_insert,
            "n_inserts": self.n_inserts,
            "n_rejected": self.n_rejected,
            "n_identity_rejected": self.n_identity_rejected,
            "current_entries": [e.snapshot() for e in self.entries],
            "restart_history": list(self.restart_history),
        }
