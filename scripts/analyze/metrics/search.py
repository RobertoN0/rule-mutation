"""
Search-behaviour analysis (G3 / RQ3): how efficiently the (1+1) EA climbs, how
its Pareto archives fill, and why it restarts. The restart breakdown is also the
bd-qfm gate evidence (stagnation never firing under restart_h=8).

Pure compute: returns row lists, never writes or plots.
"""

from __future__ import annotations

import loaders as L
from metrics.outcomes import lang_key

EFFICIENCY_HEADER = [
    "run", "strategy", "language", "seed", "iterations", "best_fitness",
    "iter_to_first_best", "positive_iteration_rate", "acceptance_rate", "identity_rate",
]
RESTART_HEADER = ["reason", "count"]
FRONT_HEADER = [
    "rule", "front_size", "min_f1", "max_f1", "max_f2", "max_f3", "max_depth",
    "n_inserts", "n_rejected", "n_identity_rejected",
]


def efficiency_row(run: L.RunData) -> list:
    vi = L.valid_iters(run)
    n = len(vi)
    positive = sum(1 for it in vi if float(it.get("f1") or 0.0) > 0)
    accepted = sum(1 for it in vi if it.get("accepted"))
    first_best = L.iter_to_first_best(run)
    return [
        run.run_dir.name,
        run.strategy,
        lang_key(run),
        run.seed,
        n,
        L.best_f1(run),
        first_best if first_best is not None else "",
        round(positive / n, 4) if n else 0.0,
        round(accepted / n, 4) if n else 0.0,
        round(L.identity_rate(run), 4),
    ]


def restart_rows(run: L.RunData) -> list[list]:
    counts = L.restart_reason_counts(run)
    order = ["stagnation", "depth_saturated", "mutator_exhausted", "fully_exhausted"]
    keys = order + [k for k in counts if k not in order]
    return [[k, int(counts.get(k, 0) or 0)] for k in keys]


def final_front_rows(run: L.RunData) -> list[list]:
    archive = run.final_archive()

    # schema 3: single archive of full chromosomes. One row per chromosome; the
    # "rule" column carries the chromosome id and "front_size" its mutated-gene
    # count (columns reused to keep the FRONT_HEADER shape stable).
    if "chromosomes" in archive:
        n_ins = int(archive.get("n_inserts") or 0)
        n_rej = int(archive.get("n_rejected") or 0)
        n_dup = int(archive.get("n_dup_rejected") or 0)
        rows = []
        for ch in archive.get("chromosomes") or []:
            genes = ch.get("genes") or {}
            depth = max((int(g.get("depth") or 0) for g in genes.values()), default=0)
            f1 = float(ch.get("f1") or 0.0)
            rows.append([
                ch.get("cid", "?"), len(genes), f1, f1,
                float(ch.get("f2") or 0.0), round(float(ch.get("f3") or 0.0), 4), depth,
                n_ins, n_rej, n_dup,
            ])
        rows.sort(key=lambda r: r[3], reverse=True)
        return rows

    # schema 2: per-rule archives.
    rows = []
    for rule_id, rule_archive in (archive.get("archives") or {}).items():
        entries = rule_archive.get("current_entries") or []
        if not entries:
            continue
        f1s = [float(e.get("f1") or 0.0) for e in entries]
        f2s = [float(e.get("f2") or 0.0) for e in entries]
        f3s = [float(e.get("f3") or 0.0) for e in entries]
        depths = [int(e.get("depth") or 0) for e in entries]
        rows.append([
            rule_id.replace("codeguard-", "cg-"),
            len(entries), min(f1s), max(f1s), max(f2s), round(max(f3s), 4), max(depths),
            int(rule_archive.get("n_inserts") or 0),
            int(rule_archive.get("n_rejected") or 0),
            int(rule_archive.get("n_identity_rejected") or 0),
        ])
    rows.sort(key=lambda r: (r[2], r[1]), reverse=True)
    return rows
