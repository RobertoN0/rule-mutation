"""
Mutator-effectiveness analysis (RQ2 / bd-03k.1). Lineage-aware: each search
iteration applies one further mutator (``mutation_chain[-1]``) to a selected
parent entry, so the security effect of that step is ``f1 - parent_f1``. From
those steps we derive per-mutator deltas, position sensitivity, LLM-vs-structural
composition effects, recurring high-fitness combinations, and per-rule best paths.

Pure compute: returns row lists, never writes or plots.
"""

from __future__ import annotations

import statistics
from collections import Counter, defaultdict
from dataclasses import dataclass

import loaders as L
import records as R

# The three LLM-driven mutators; the rest are deterministic/structural.
LLM_MUTATORS = frozenset({"negation_injection", "voice_change", "paraphrase"})

PER_MUTATOR_HEADER = [
    "mutator", "kind", "steps", "mean_delta", "mean_delta_first", "mean_delta_later",
    "n_positive", "n_negative", "max_delta", "min_delta",
]
POSITION_HEADER = ["mutator", "position", "steps", "mean_delta", "n_positive"]
COMPOSITION_HEADER = ["composition", "steps", "mean_delta", "mean_f1_after", "n_positive", "n_negative"]
COMBINATION_HEADER = ["chain", "length", "occurrences", "mean_f1", "max_f1"]
BEST_PATH_HEADER = ["rule", "best_f1", "depth", "chain"]
SAFEST_PATH_HEADER = ["rule", "safest_f1", "depth", "chain"]
INSERT_RATE_HEADER = ["mutator", "kind", "attempts", "archive_adds", "archive_adds_f1", "add_rate", "f1_add_rate"]
STEPS_HEADER = ["rule_id", "iter", "mutator", "kind", "position", "chain", "f1_before", "f1_after", "delta", "accepted"]


def kind_of(mutator: str) -> str:
    return "llm" if mutator in LLM_MUTATORS else "structural"


def chain_composition(chain) -> str:
    """all-llm / all-structural / mixed for a full mutation chain."""
    kinds = {kind_of(m) for m in chain}
    if kinds == {"llm"}:
        return "llm"
    if kinds == {"structural"}:
        return "structural"
    return "mixed"


@dataclass
class LineageStep:
    rule_id: str
    iter: int
    mutator: str          # chain[-1] — the mutator applied this step
    position: int         # chain length / depth at this step
    chain: tuple[str, ...]
    f1_before: float      # parent_f1
    f1_after: float       # f1
    delta: float
    accepted: bool

    @property
    def kind(self) -> str:
        return kind_of(self.mutator)


def lineage_steps(run: L.RunData) -> list[LineageStep]:
    steps: list[LineageStep] = []
    for it in L.valid_iters(run):
        chain = R.mutation_chain(it)
        if not chain:
            continue
        before = R.get_path(it, "selection_meta.parent_f1")
        after = it.get("f1")
        if before is None or after is None:
            continue
        before = float(before)
        after = float(after)
        steps.append(LineageStep(
            rule_id=str(it.get("rule_id") or ""),
            iter=R.iter_num(it),
            mutator=chain[-1],
            position=len(chain),
            chain=tuple(chain),
            f1_before=before,
            f1_after=after,
            delta=after - before,
            accepted=bool(it.get("accepted")),
        ))
    return steps


def _mean(xs) -> float:
    xs = list(xs)
    return statistics.mean(xs) if xs else float("nan")


def step_rows(steps: list[LineageStep]) -> list[list]:
    return [
        [s.rule_id, s.iter, s.mutator, s.kind, s.position, "->".join(s.chain),
         s.f1_before, s.f1_after, s.delta, int(s.accepted)]
        for s in sorted(steps, key=lambda s: (s.rule_id, s.iter))
    ]


def per_mutator_delta(steps: list[LineageStep]) -> list[list]:
    by_mut: dict[str, list[LineageStep]] = defaultdict(list)
    for s in steps:
        by_mut[s.mutator].append(s)
    rows = []
    for mutator, group in by_mut.items():
        deltas = [s.delta for s in group]
        first = [s.delta for s in group if s.position == 1]
        later = [s.delta for s in group if s.position > 1]
        rows.append([
            mutator, kind_of(mutator), len(group),
            round(_mean(deltas), 4), round(_mean(first), 4), round(_mean(later), 4),
            sum(1 for d in deltas if d > 0), sum(1 for d in deltas if d < 0),
            max(deltas), min(deltas),
        ])
    rows.sort(key=lambda r: r[3], reverse=True)  # mean_delta desc; sign meaning is
    # direction-dependent: under 'minimize' +delta = safer (repair), under 'maximize' +delta = more vulnerable.
    return rows


def position_table(steps: list[LineageStep]) -> list[list]:
    by_key: dict[tuple[str, int], list[float]] = defaultdict(list)
    for s in steps:
        by_key[(s.mutator, s.position)].append(s.delta)
    rows = []
    for (mutator, position), deltas in sorted(by_key.items()):
        rows.append([
            mutator, position, len(deltas), round(_mean(deltas), 4),
            sum(1 for d in deltas if d > 0),
        ])
    return rows


def composition_compare(steps: list[LineageStep]) -> list[list]:
    """Does mixing LLM + structural mutators in a chain beat either alone?"""
    by_comp: dict[str, list[LineageStep]] = defaultdict(list)
    for s in steps:
        by_comp[chain_composition(s.chain)].append(s)
    order = {"structural": 0, "llm": 1, "mixed": 2}
    rows = []
    for comp in sorted(by_comp, key=lambda c: order.get(c, 9)):
        group = by_comp[comp]
        deltas = [s.delta for s in group]
        rows.append([
            comp, len(group), round(_mean(deltas), 4),
            round(_mean([s.f1_after for s in group]), 4),
            sum(1 for d in deltas if d > 0), sum(1 for d in deltas if d < 0),
        ])
    return rows


def combination_counts(run: L.RunData, min_length: int = 2, top_n: int = 20) -> list[list]:
    """Recurring multi-mutator chains among the surviving Pareto-front entries,
    with their fitness — which combinations end up in high-f1 lineages."""
    archive = run.final_archive()
    chains: dict[tuple[str, ...], list[float]] = defaultdict(list)
    for rule_archive in (archive.get("archives") or {}).values():
        for entry in rule_archive.get("current_entries") or []:
            chain = tuple(entry.get("mutation_chain") or [])
            if len(chain) >= min_length:
                chains[chain].append(float(entry.get("f1") or 0.0))
    rows = []
    for chain, f1s in chains.items():
        rows.append(["->".join(chain), len(chain), len(f1s), round(_mean(f1s), 4), max(f1s)])
    rows.sort(key=lambda r: (r[2], r[4]), reverse=True)  # by occurrences, then max_f1
    return rows[:top_n]


def per_rule_best_path(run: L.RunData) -> list[list]:
    """Highest-f1 surviving entry per rule and the chain that produced it."""
    archive = run.final_archive()
    rows = []
    for rule_id, rule_archive in (archive.get("archives") or {}).items():
        entries = rule_archive.get("current_entries") or []
        if not entries:
            continue
        best = max(entries, key=lambda e: float(e.get("f1") or 0.0))
        rows.append([
            R.short_rule(rule_id),
            float(best.get("f1") or 0.0),
            int(best.get("depth") or 0),
            "->".join(best.get("mutation_chain") or []),
        ])
    rows.sort(key=lambda r: r[1], reverse=True)
    return rows


def per_rule_safest_path(run: L.RunData) -> list[list]:
    """Lowest-f1 (most-defensive / safest) surviving entry per rule and its chain
    — the negative-f1 direction; this is where compounding safe-making chains show."""
    archive = run.final_archive()
    rows = []
    for rule_id, rule_archive in (archive.get("archives") or {}).items():
        entries = rule_archive.get("current_entries") or []
        if not entries:
            continue
        safest = min(entries, key=lambda e: float(e.get("f1") or 0.0))
        rows.append([
            R.short_rule(rule_id),
            float(safest.get("f1") or 0.0),
            int(safest.get("depth") or 0),
            "->".join(safest.get("mutation_chain") or []),
        ])
    rows.sort(key=lambda r: r[1])  # most-negative first
    return rows


def insert_rate_rows(run: L.RunData) -> list[list]:
    """Per-mutator attempt / archive-insertion rates from the run summary."""
    stats = L.mutator_stats(run)
    rows = []
    for mutator, s in stats.items():
        attempts = int(s.get("attempts", 0) or 0)
        adds = int(s.get("archive_adds", 0) or 0)
        adds_f1 = int(s.get("archive_adds_f1", 0) or 0)
        rows.append([
            mutator, kind_of(mutator), attempts, adds, adds_f1,
            round(adds / attempts, 4) if attempts else 0.0,
            round(adds_f1 / attempts, 4) if attempts else 0.0,
        ])
    rows.sort(key=lambda r: r[6], reverse=True)  # by f1_add_rate
    return rows
