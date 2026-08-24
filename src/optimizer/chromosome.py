"""
Full rule-set chromosome + single Pareto archive.

The unit of search is the ENTIRE rule set (a *chromosome*). A chromosome carries,
for every rule used in the experiment:

* a **text allele** — the original on-disk rule text or a mutated variant
* a global **rule-ordering policy** — per-rule integer priority offsets that
  re-rank the rules inside each prompt's system prompt (default 0 ⇒ the prompt's
  original retrieval order is preserved via a stable sort).

Only *deviations* from the original are stored: ``genes`` holds mutated rules
only, ``order_priority`` holds bumped rules only. Everything else falls back to
the originals held by :class:`RuleSetSpace`.

Objectives — the conservative set (all maximised by :class:`ChromosomeArchive`):
    f1 = Semgrep-finding reduction
    f2 = textual similarity (mean SBERT versus authored originals; stored as
         ``rule_fidelity`` for schema compatibility)
    f3 = −parsimony (negated count of mutated rules)

"""

from __future__ import annotations

import hashlib
import random
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Callable

if TYPE_CHECKING:
    from ..evaluation.fitness import AggregatedFitness


# Tolerance for Pareto dominance float comparisons.
_TOL: float = 1e-9


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# ============================================================================
# Genes
# ============================================================================

@dataclass
class GeneState:
    """One rule's allele inside a chromosome."""

    rule_id: str
    text: str
    mutation_path: list[str] = field(default_factory=list)
    """Ordered mutator names that produced ``text`` from the authored rule.
    Empty ⇒ the gene retains the authored text."""

    @property
    def depth(self) -> int:
        return len(self.mutation_path)

    @property
    def is_mutated(self) -> bool:
        return bool(self.mutation_path)

    def snapshot(self) -> dict[str, Any]:
        return {
            "mutation_path": list(self.mutation_path),
            "depth": self.depth,
            "text_length": len(self.text),
        }


# ============================================================================
# Chromosome (pure value + search bookkeeping; no originals needed)
# ============================================================================

@dataclass
class RuleSetChromosome:
    """A point in the rule-set search space: text-allele overrides + order offsets.

    Objectives and lineage are attached after evaluation. ``cid`` (content hash)
    is stamped by :class:`RuleSetSpace` and used for archive dedup + as a stable
    output label. ``tried`` records the moves already attempted *on this entry as
    a parent* (per-entry dedup — a fresh child starts with an empty set).
    """

    genes: dict[str, GeneState] = field(default_factory=dict)          # mutated rules only
    order_priority: dict[str, int] = field(default_factory=dict)       # bumped rules only

    f1: float = 0.0
    f2: float = 0.0
    f3: float = 0.0
    fitness: "AggregatedFitness | None" = None

    evaluation_added: int = 0
    evaluation_index: int = 0
    parent_id: str | None = None
    cid: str = ""                                                      # stamped by the space
    tried: set = field(default_factory=set)                           # moves tried as a parent

    # ---- read-only views --------------------------------------------------

    def gene_depth(self, rid: str) -> int:
        g = self.genes.get(rid)
        return g.depth if g else 0

    def mutated_rule_ids(self) -> set[str]:
        return set(self.genes)

    def render_order(self, prompt_rule_ids: list[str]) -> list[str]:
        """Prompt's rules re-ranked by descending priority offset.

        Python's ``sorted`` is stable, so rules with equal priority (the common
        case — default 0) keep their original retrieval order. ⇒ an all-zero
        chromosome renders each prompt in its exact retrieval order.
        """
        return sorted(prompt_rule_ids, key=lambda r: -self.order_priority.get(r, 0))

    def score_sum(self) -> float:
        return self.f1 + self.f2 + self.f3

    @property
    def invalid_prompt_count(self) -> int:
        """Per-task generation failures in this evaluation (tiebreaker only)."""
        return self.fitness.num_invalid_prompts if self.fitness is not None else 0

    # ---- moves (return a fresh child; objectives reset, cid re-stamped by caller)
    def _child(
        self,
        genes: dict[str, GeneState],
        order_priority: dict[str, int],
    ) -> "RuleSetChromosome":
        return RuleSetChromosome(
            genes=genes,
            order_priority=order_priority,
            parent_id=self.cid or None,
        )

    def with_gene(self, rid: str, new_text: str, mutator_name: str) -> "RuleSetChromosome":
        """EA text move: stack one mutation on rid's CURRENT allele (depth += 1)."""
        parent_gene = self.genes.get(rid)
        path = (list(parent_gene.mutation_path) if parent_gene else []) + [mutator_name]
        genes = dict(self.genes)
        genes[rid] = GeneState(rule_id=rid, text=new_text, mutation_path=path)
        return self._child(genes, dict(self.order_priority))

    def with_reverted(self, rid: str) -> "RuleSetChromosome":
        """Gated reverse move: restore rid to its original text (drop the override)."""
        genes = dict(self.genes)
        genes.pop(rid, None)
        return self._child(genes, dict(self.order_priority))

    def with_priority(self, rid: str, new_priority: int) -> "RuleSetChromosome":
        """Order move: set rid's global priority offset (0 ⇒ drop the override).

        ``render_order`` sorts each prompt's rules by descending offset, so a
        higher offset renders the rule earlier. Callers move a rule to an extreme
        (``max+1`` = front, ``min-1`` = back); repeated moves compose into any
        ordering. The offset is global — one gene reorders every prompt at once.
        """
        op = dict(self.order_priority)
        if new_priority == 0:
            op.pop(rid, None)
        else:
            op[rid] = new_priority
        return self._child(dict(self.genes), op)

    # ---- serialisation ----------------------------------------------------

    def snapshot(self) -> dict[str, Any]:
        return {
            "cid": self.cid,
            "f1": round(self.f1, 6),
            "f2": round(self.f2, 6),
            "f3": round(self.f3, 6),
            "mutated_rule_ids": sorted(self.genes),
            "order_priority": dict(self.order_priority),
            "genes": {rid: g.snapshot() for rid, g in sorted(self.genes.items())},
            "evaluation_added": self.evaluation_added,
            "evaluation_index": self.evaluation_index,
            "parent_id": self.parent_id,
            "num_invalid_prompts": self.invalid_prompt_count,
        }


def dominates(a: RuleSetChromosome, b: RuleSetChromosome) -> bool:
    """True iff ``a`` Pareto-dominates ``b`` on (f1, f2, f3) maximised."""
    ge = (
        a.f1 >= b.f1 - _TOL
        and a.f2 >= b.f2 - _TOL
        and a.f3 >= b.f3 - _TOL
    )
    if not ge:
        return False
    return (
        a.f1 > b.f1 + _TOL
        or a.f2 > b.f2 + _TOL
        or a.f3 > b.f3 + _TOL
    )


# ============================================================================
# Space (genome definition — owns originals + rendering)
# ============================================================================

@dataclass
class RuleSetSpace:
    """The genome definition: the full rule id set, their original texts, and the
    prompt separator. Owns every operation that needs the originals (allele
    resolution, prompt rendering, cache signature, chromosome id).

    ``all_rule_ids`` must be a stable (sorted) list so ``chromosome_id`` is
    independent of dict insertion order.
    """

    all_rule_ids: list[str]
    originals: dict[str, str]
    separator: str = "\n\n---\n\n"

    def origin(self) -> RuleSetChromosome:
        """The seed chromosome: all rules original, retrieval order, objectives 0."""
        return self.stamp(RuleSetChromosome())

    def allele(self, chromo: RuleSetChromosome, rid: str) -> str:
        g = chromo.genes.get(rid)
        return g.text if g else self.originals[rid]

    def render_prompt(self, chromo: RuleSetChromosome, prompt_rule_ids: list[str]) -> str:
        """The exact rule block fed to the model for one prompt (order-aware)."""
        order = chromo.render_order(prompt_rule_ids)
        return self.separator.join(self.allele(chromo, rid) for rid in order)

    def prompt_signature(self, chromo: RuleSetChromosome, prompt_rule_ids: list[str]) -> str:
        """Cache-key body: ordered ``(rule_id, sha(text))`` list for one prompt.

        Encodes rule identity + version + order without concatenation ambiguity
        (rule bodies can contain ``---``). Two chromosomes that render a prompt
        identically share this signature — a correct cache hit under temp=0.
        """
        order = chromo.render_order(prompt_rule_ids)
        body = "\x1e".join(f"{rid}:{_sha(self.allele(chromo, rid))}" for rid in order)
        return _sha(body)

    def chromosome_id(self, chromo: RuleSetChromosome) -> str:
        """Stable 16-hex content hash over the full ordered gene set + priorities."""
        body = "|".join(
            f"{rid}:{chromo.order_priority.get(rid, 0)}:{_sha(self.allele(chromo, rid))}"
            for rid in self.all_rule_ids
        )
        return _sha(body)[:16]

    def stamp(self, chromo: RuleSetChromosome) -> RuleSetChromosome:
        """Compute + attach ``cid`` (call after every move, before archive offer)."""
        chromo.cid = self.chromosome_id(chromo)
        return chromo


# ============================================================================
# Single Pareto archive of chromosomes
# ============================================================================

class ChromosomeArchive:
    """One Pareto archive over full-chromosome objectives (f1, f2, f3).

    The all-original chromosome is kept only as the evaluation baseline and
    best-result reporting floor. It is not a front member, a parent, or an
    admission threshold. The initial random candidates create the front among
    themselves.

    Admission is standard Pareto admission against the current front. The
    archive is never cleared. When it exceeds its configured capacity, one
    member is removed by the explicit overflow policy below.
    """

    def __init__(
        self,
        origin: RuleSetChromosome,
        *,
        cap: int,
        rng: random.Random,
    ) -> None:
        if cap < 1:
            raise ValueError(f"cap must be >= 1, got {cap}")
        self.origin = origin
        self.cap = cap
        self._rng = rng

        self.entries: list[RuleSetChromosome] = []
        self.n_inserts = 0
        self.n_rejected = 0
        self.n_dup_rejected = 0
        self.n_neutral_inserts = 0
        self._best_ever = origin
        self.best_ever_evaluation = 0

    # ---- parent selection -------------------------------------------------
    def parents(self) -> list[RuleSetChromosome]:
        """Sampleable parents are exactly the current Pareto-front members."""
        return list(self.entries)

    def sample_parent(
        self,
        is_eligible: Callable[[RuleSetChromosome], bool],
        *,
        exclude_cids: set[str] | None = None,
    ) -> RuleSetChromosome | None:
        """Uniformly sample an eligible front parent not already tried this slot."""
        excluded = exclude_cids or set()
        candidates = [
            chromosome
            for chromosome in self.entries
            if chromosome.cid not in excluded and is_eligible(chromosome)
        ]
        if not candidates:
            return None
        return self._rng.choice(candidates)

    def mark_tried(self, parent: RuleSetChromosome, move: tuple) -> None:
        """Record ``move`` as attempted on ``parent`` (call regardless of outcome)."""
        parent.tried.add(move)

    # ---- insertion --------------------------------------------------------
    def try_add(
        self,
        child: RuleSetChromosome,
        evaluation_index: int,
    ) -> tuple[bool, str]:
        """Offer ``child`` to the archive. Returns ``(accepted, reason)``.

        Rejected if its ``cid`` duplicates an existing member (incl. origin) or
        if it is dominated by a front member. On accept it evicts every front
        member it dominates and, on overflow, the lowest-f1 member
        (lexicographic: f1, then f2+f3, then age; the just-added child is safe).
        """
        child.evaluation_index = evaluation_index
        self._consider_best_ever(child, evaluation_index)

        if child.cid == self.origin.cid or any(child.cid == e.cid for e in self.entries):
            self.n_rejected += 1
            self.n_dup_rejected += 1
            return False, "duplicate"

        if any(dominates(e, child) for e in self.entries):
            self.n_rejected += 1
            return False, "dominated"

        child.evaluation_added = evaluation_index
        survivors = [e for e in self.entries if not dominates(child, e)]
        survivors.append(child)  # child is always last

        if len(survivors) > self.cap:
            old = survivors[:-1]  # protect the just-added child from eviction
            # Lexicographic eviction (f1 primary). Drop the lowest-f1 member
            # first: f1 is the repair objective, so an over-cap archive must
            # never sacrifice its best repair to keep a near-baseline variant
            # (the failure mode of a raw f1+f2+f3 sum, whose mixed scales let a
            # low-f1/high-f3 entry outrank a high-f1/low-f3 one). Ties break on
            # the remaining objectives (f2+f3), then age (oldest evicted first).
            evict_idx = min(
                range(len(old)),
                key=lambda i: (
                    old[i].f1,
                    old[i].f2 + old[i].f3,
                    -old[i].invalid_prompt_count,
                    old[i].evaluation_added,
                ),
            )
            survivors.pop(evict_idx)

        self.entries = survivors
        self.n_inserts += 1
        if abs(child.f1 - self.origin.f1) <= _TOL:
            self.n_neutral_inserts += 1
        return True, "accepted"

    # ---- inspection -------------------------------------------------------

    @staticmethod
    def _reporting_key(chromosome: RuleSetChromosome) -> tuple[float, int, float]:
        return (
            chromosome.f1,
            -chromosome.invalid_prompt_count,
            chromosome.f2 + chromosome.f3,
        )

    def _consider_best_ever(
        self,
        child: RuleSetChromosome,
        evaluation_index: int,
    ) -> None:
        if child.f1 <= self.origin.f1 + _TOL:
            return
        if self._best_ever is self.origin or self._reporting_key(child) > self._reporting_key(
            self._best_ever
        ):
            self._best_ever = child
            self.best_ever_evaluation = evaluation_index

    def best(self) -> RuleSetChromosome:
        """Best raw-count repair evaluated anywhere in the run.

        This record survives bounded-front overflow eviction. The origin is
        returned unless a candidate strictly improves raw f1; invalid-output
        count and the remaining objectives only break equal-f1 ties.
        """
        return self._best_ever

    def __len__(self) -> int:
        return len(self.entries)

    def snapshot(self) -> dict[str, Any]:
        return {
            "cap": self.cap,
            "origin": {
                "cid": self.origin.cid,
                "f1": round(self.origin.f1, 6),
                "f2": round(self.origin.f2, 6),
                "f3": round(self.origin.f3, 6),
            },
            "n_inserts": self.n_inserts,
            "n_rejected": self.n_rejected,
            "n_dup_rejected": self.n_dup_rejected,
            "n_neutral_inserts": self.n_neutral_inserts,
            "best_ever_evaluation": self.best_ever_evaluation,
            "best_ever": self._best_ever.snapshot(),
            "entries": [c.snapshot() for c in self.entries],
        }
