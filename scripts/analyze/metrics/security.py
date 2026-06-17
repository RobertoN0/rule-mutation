"""
Security-effect detail (G1): turns the abstract f1 deltas into named CWEs and
Semgrep checks. Per-CWE outcome rates, per-check "flip" counts (which specific
checks a rephrasing made appear or disappear), and severity shifts (error /
warning gains and losses). Reuses the prompt-level collapse from
``metrics.outcomes`` and adds a check-id pass.

Pure compute: returns row lists, never writes or plots.
"""

from __future__ import annotations

from collections import defaultdict

import loaders as L
import records as R
from metrics import outcomes as OC
from report.tables import fmt_ci

CWE_HEADER = [
    "cwe_id", "prompts", "degraded", "safer", "unchanged", "code_changed",
    "baseline_weighted", "worst_weighted", "best_weighted",
]
SEVERITY_HEADER = ["shift", "prompts", "rate_ci"]
CHECK_FLIP_HEADER = ["check", "check_id", "prompts_added", "prompts_removed", "net"]


def short_check(check_id: str) -> str:
    """Last path segment of a Semgrep check id (the rule name)."""
    return (check_id or "").rsplit(".", 1)[-1]


def cwe_rows(outcome: OC.RunOutcome) -> list[list]:
    groups: dict[str, list[OC.UnitState]] = defaultdict(list)
    for state in outcome.prompt_states.values():
        groups[state.cwe_id].append(state)
    rows = []
    for cwe, states in groups.items():
        n = len(states)
        degraded = sum(1 for s in states if s.outcome == "degraded")
        safer = sum(1 for s in states if s.outcome == "safer")
        rows.append([
            cwe, n, degraded, safer, n - degraded - safer,
            sum(1 for s in states if s.code_changed),
            sum(s.baseline_score for s in states),
            sum(float(s.max_score or 0.0) for s in states),
            sum(float(s.min_score or 0.0) for s in states),
        ])
    rows.sort(key=lambda r: (r[2], r[1]), reverse=True)  # most-degraded first
    return rows


def severity_rows(outcome: OC.RunOutcome) -> list[list]:
    states = list(outcome.prompt_states.values())
    n = len(states)
    cats = {
        "error_increased": sum(1 for s in states if int(s.max_error or 0) > s.baseline_error),
        "error_decreased": sum(1 for s in states if int(s.min_error or 0) < s.baseline_error),
        "warning_increased": sum(1 for s in states if int(s.max_warning or 0) > s.baseline_warning),
        "warning_decreased": sum(1 for s in states if int(s.min_warning or 0) < s.baseline_warning),
    }
    return [[name, count, fmt_ci(count, n)] for name, count in cats.items()]


def check_flip_rows(run: L.RunData) -> list[list]:
    """Per Semgrep check: in how many prompts a rephrasing ever made it appear
    (added = new finding) vs disappear (removed) relative to baseline."""
    base = {str(r["test_case_id"]): set(R.check_ids(r)) for r in run.baseline()}
    added: dict[str, set] = defaultdict(set)
    removed: dict[str, set] = defaultdict(set)
    for it in L.valid_iters(run):
        rule_id = str(it.get("rule_id"))
        iter_id = run.iter_id(int(it["iter"]))
        for rec in run.intermediate(iter_id):
            tc = str(rec.get("test_case_id"))
            if tc not in base or not R.is_applicable(rec, rule_id):
                continue
            mutated = set(R.check_ids(rec))
            for cid in mutated - base[tc]:
                added[cid].add(tc)
            for cid in base[tc] - mutated:
                removed[cid].add(tc)

    rows = []
    for cid in set(added) | set(removed):
        a, r = len(added[cid]), len(removed[cid])
        rows.append([short_check(cid), cid, a, r, a - r])
    rows.sort(key=lambda row: (row[2] + row[3], row[4]), reverse=True)
    return rows
