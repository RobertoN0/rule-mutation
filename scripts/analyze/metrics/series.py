"""
Field-agnostic time-series extraction over a run's iterations and archive
snapshots. This is the engine behind the fitness-variation plots: it turns any
numeric field that varies over the search into per-rule (one curve per archive)
or global series, so f1/f2/f3, archive growth, divergence drift, restart cadence
and token burn all flow through one code path.

Pure compute: returns ``Series`` objects, never plots or writes files.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field as dc_field
from pathlib import Path

import loaders as L
import records as R

GLOBAL_KEY = "__global__"

# Known iteration fields (iterations.jsonl) with dotted paths + nice labels.
# Any other dotted path can still be passed through directly.
ITER_FIELDS: dict[str, tuple[str, str]] = {
    "f1": ("f1", "f1 (security delta)"),
    "f2": ("f2", "f2 (proportion divergent)"),
    "f3": ("f3", "f3 (cond. mean divergence)"),
    "num_prompts_affected": ("num_prompts_affected", "prompts affected"),
    "chain_length": ("chain_length", "mutation chain length"),
    "archive_size_after": ("selection_meta.archive_size_after", "archive size"),
    "attempts_since_insert": ("selection_meta.attempts_since_insert", "attempts since insert"),
    "parent_f1": ("selection_meta.parent_f1", "parent f1"),
    "input_tokens_total": ("input_tokens_total", "cumulative input tokens"),
    "output_tokens_total": ("output_tokens_total", "cumulative output tokens"),
}

# Archive-snapshot fields. Objective fields aggregate over the front (max);
# the rest read straight off the per-rule archive record.
ARCHIVE_OBJECTIVE_FIELDS = {"f1", "f2", "f3"}
ARCHIVE_SCALAR_FIELDS = {
    "size": "size of Pareto front",
    "n_inserts": "archive inserts",
    "n_rejected": "archive rejections",
    "n_identity_rejected": "identity rejections",
    "attempts_since_insert": "attempts since insert",
}

AGGREGATIONS = ("value", "best_so_far", "worst_so_far", "running_mean")


@dataclass
class Series:
    """One labelled curve: ``ys[i]`` observed at iteration ``xs[i]``."""

    key: str
    xs: list[int] = dc_field(default_factory=list)
    ys: list[float] = dc_field(default_factory=list)
    label: str = ""

    def add(self, x: int, y: float) -> None:
        self.xs.append(int(x))
        self.ys.append(float(y))

    def __len__(self) -> int:
        return len(self.xs)

    def is_flat(self, eps: float = 0.0) -> bool:
        """True if the curve never varies (constant, or a single point)."""
        if len(self.ys) <= 1:
            return True
        return (max(self.ys) - min(self.ys)) <= eps


def field_label(field: str, source: str = "iterations") -> str:
    if source == "archive":
        if field in ARCHIVE_OBJECTIVE_FIELDS:
            return f"{field} (front best)"
        return ARCHIVE_SCALAR_FIELDS.get(field, field)
    return ITER_FIELDS.get(field, (field, field))[1]


def available_fields(source: str = "iterations") -> list[str]:
    if source == "archive":
        return sorted(ARCHIVE_OBJECTIVE_FIELDS | set(ARCHIVE_SCALAR_FIELDS))
    return list(ITER_FIELDS)


# ---------------------------------------------------------------------------
# Iteration-log series (dense: every iteration)
# ---------------------------------------------------------------------------

def _apply_agg(ys: list[float], agg: str) -> list[float]:
    if agg == "value":
        return ys
    out: list[float] = []
    if agg == "best_so_far":
        best = float("-inf")
        for y in ys:
            best = max(best, y)
            out.append(best)
        return out
    if agg == "worst_so_far":
        worst = float("inf")
        for y in ys:
            worst = min(worst, y)
            out.append(worst)
        return out
    if agg == "running_mean":
        total = 0.0
        for i, y in enumerate(ys, start=1):
            total += y
            out.append(total / i)
        return out
    raise ValueError(f"unknown aggregation: {agg!r} (expected one of {AGGREGATIONS})")


def iteration_series(
    run: L.RunData,
    field: str = "f1",
    by: str = "rule",
    agg: str = "value",
) -> list[Series]:
    """Per-rule (``by='rule'``) or single global (``by='global'``) series of an
    iteration field, optionally aggregated (raw value / best-so-far / running mean).
    """
    path = ITER_FIELDS.get(field, (field, field))[0]
    label = field_label(field)
    rows = sorted(L.valid_iters(run), key=R.iter_num)

    if by == "global":
        s = Series(key=GLOBAL_KEY, label=label)
        xs = [R.iter_num(it) for it in rows]
        ys = _apply_agg([R.get_number(it, path) for it in rows], agg)
        for x, y in zip(xs, ys):
            s.add(x, y)
        return [s]

    if by != "rule":
        raise ValueError(f"unknown grouping: {by!r} (expected 'rule' or 'global')")

    grouped: dict[str, list[tuple[int, float]]] = {}
    for it in rows:
        rid = R.rule_id(it)
        if rid is None:
            continue
        grouped.setdefault(rid, []).append((R.iter_num(it), R.get_number(it, path)))

    series: list[Series] = []
    for rid, pairs in grouped.items():
        pairs.sort(key=lambda p: p[0])
        ys = _apply_agg([y for _, y in pairs], agg)
        s = Series(key=rid, label=R.short_rule(rid))
        for (x, _), y in zip(pairs, ys):
            s.add(x, y)
        series.append(s)
    series.sort(key=lambda s: s.key)
    return series


# ---------------------------------------------------------------------------
# Archive-snapshot series (sparse: every snapshot, authoritative front state)
# ---------------------------------------------------------------------------

def _snapshot_paths(run: L.RunData) -> list[Path]:
    return sorted((run.run_dir / "archive_snapshots").glob("iter*.json"))


def _archive_value(archive: dict, field: str, reduce: str = "max") -> float | None:
    entries = archive.get("current_entries") or []
    if field in ARCHIVE_OBJECTIVE_FIELDS:
        if not entries:
            return None
        vals = [float(e.get(field) or 0.0) for e in entries]
        return min(vals) if reduce == "min" else max(vals)
    if field == "size":
        return float(len(entries))
    return float(archive.get(field) or 0.0)


def archive_series(run: L.RunData, field: str = "f1", reduce: str = "max") -> list[Series]:
    """Per-rule series of a front-level field across the archive snapshots.

    For objective fields, ``reduce`` picks the front extreme: ``max`` = the
    most-adversarial kept entry (higher f1), ``min`` = the most-defensive
    (lower / negative f1 — the safer direction).
    """
    label = field_label(field, source="archive")
    grouped: dict[str, Series] = {}
    for path in _snapshot_paths(run):
        try:
            snap = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        snap_iter = int(snap.get("iter", 0))
        for rid, archive in (snap.get("archives") or {}).items():
            value = _archive_value(archive, field, reduce)
            if value is None:
                continue
            s = grouped.setdefault(rid, Series(key=rid, label=R.short_rule(rid)))
            s.add(snap_iter, value)
    return [grouped[k] for k in sorted(grouped)]
