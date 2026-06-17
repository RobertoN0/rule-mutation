"""
CSV/Markdown row builders for the outcome-distribution metric. Consumes the
``UnitState`` / ``RunOutcome`` core from ``metrics.outcomes`` and owns the CSV
schemas (the header constants) plus the micro/macro/envelope/summary/pair rows.

Pure compute: returns row lists (some cells are pre-formatted CI strings so the
report layer is a straight serialization).
"""

from __future__ import annotations

import statistics
from collections import defaultdict

import loaders as L
import records as R
import stats as S
from metrics.outcomes import (
    OUTCOMES,
    RunOutcome,
    UnitState,
    distribution,
    lang_key,
    run_label,
    states_for_scope,
)
from report.tables import fmt_ci, fmt_pct

PROMPT_HEADER = [
    "test_case_id", "language", "cwe_id", "rules_used", "observations",
    "baseline_weighted", "best_weighted", "worst_weighted", "outcome", "code_changed",
    "baseline_raw", "best_raw", "worst_raw",
    "baseline_error", "best_error", "worst_error",
    "baseline_warning", "best_warning", "worst_warning",
]
EXPOSURE_HEADER = [
    "rule_short", "rule_id", "test_case_id", "language", "cwe_id", "observations",
    "baseline_weighted", "best_weighted", "worst_weighted", "outcome", "code_changed",
]
PER_RULE_HEADER = [
    "rule", "units", "units_with_observations",
    "degraded", "degraded_rate_ci", "unchanged", "unchanged_rate_ci",
    "safer", "safer_rate_ci", "code_changed", "code_changed_rate_ci",
]
MICRO_HEADER = [
    "scope", "n", "degraded", "degraded_rate_ci", "unchanged", "unchanged_rate_ci",
    "safer", "safer_rate_ci", "code_changed", "code_changed_rate_ci",
]
MACRO_HEADER = ["scope", "rules", "macro_degraded", "macro_unchanged", "macro_safer", "macro_code_changed"]
ENVELOPE_HEADER = [
    "condition", "prompts", "weighted_findings", "raw_findings",
    "error_findings", "warning_findings", "clean_prompts", "clean_rate_ci",
]
SUMMARY_HEADER = [
    "run", "strategy", "language", "seed", "prompts", "mutated_rules",
    "applicable_exposures", "all_prompt_rule_exposures",
    "prompt_degraded_rate", "prompt_unchanged_rate", "prompt_safer_rate", "prompt_code_changed_rate",
    "applicable_micro_degraded_rate", "applicable_micro_unchanged_rate",
    "applicable_micro_safer_rate", "applicable_micro_code_changed_rate",
    "applicable_macro_degraded_rate", "applicable_macro_unchanged_rate",
    "applicable_macro_safer_rate", "applicable_macro_code_changed_rate",
    "all_micro_degraded_rate", "all_micro_unchanged_rate", "all_micro_safer_rate", "all_micro_code_changed_rate",
    "all_macro_degraded_rate", "all_macro_unchanged_rate", "all_macro_safer_rate", "all_macro_code_changed_rate",
    "positive_iteration_rate", "best_f1",
]
PAIR_HEADER = [
    "language", "seed", "matched_prompts",
    "ea_degraded", "random_degraded", "both_degraded", "ea_only", "random_only", "neither",
    "mcnemar_p", "mcnemar_note",
    "ea_code_changed", "random_code_changed",
]


def micro_row(scope: str, states: list[UnitState]) -> list:
    n = len(states)
    counts = distribution(states)
    code_changed = sum(1 for state in states if state.code_changed)
    return [
        scope,
        n,
        counts["degraded"],
        fmt_ci(counts["degraded"], n),
        counts["unchanged"],
        fmt_ci(counts["unchanged"], n),
        counts["safer"],
        fmt_ci(counts["safer"], n),
        code_changed,
        fmt_ci(code_changed, n),
    ]


def macro_rates(states: list[UnitState]) -> dict[str, float]:
    by_rule: dict[str, list[UnitState]] = defaultdict(list)
    for state in states:
        if state.rule_id:
            by_rule[state.rule_id].append(state)
    if not by_rule:
        return {name: float("nan") for name in (*OUTCOMES, "code_changed")}

    per_rule = []
    for group in by_rule.values():
        n = len(group)
        counts = distribution(group)
        code_changed = sum(1 for state in group if state.code_changed)
        per_rule.append({
            "degraded": counts["degraded"] / n,
            "unchanged": counts["unchanged"] / n,
            "safer": counts["safer"] / n,
            "code_changed": code_changed / n,
        })
    return {
        name: statistics.mean(row[name] for row in per_rule)
        for name in ("degraded", "unchanged", "safer", "code_changed")
    }


def macro_row(scope: str, states: list[UnitState]) -> list:
    rates = macro_rates(states)
    n_rules = len({state.rule_id for state in states if state.rule_id})
    return [
        scope,
        n_rules,
        fmt_pct(rates["degraded"]),
        fmt_pct(rates["unchanged"]),
        fmt_pct(rates["safer"]),
        fmt_pct(rates["code_changed"]),
    ]


def per_rule_rows(states: list[UnitState]) -> list[list]:
    by_rule: dict[str, list[UnitState]] = defaultdict(list)
    for state in states:
        if state.rule_id:
            by_rule[state.rule_id].append(state)

    rows = []
    for rule_id, group in sorted(by_rule.items()):
        n = len(group)
        counts = distribution(group)
        code_changed = sum(1 for state in group if state.code_changed)
        prompts_with_obs = sum(1 for state in group if state.observations > 0)
        rows.append([
            R.short_rule(rule_id),
            n,
            prompts_with_obs,
            counts["degraded"],
            fmt_ci(counts["degraded"], n),
            counts["unchanged"],
            fmt_ci(counts["unchanged"], n),
            counts["safer"],
            fmt_ci(counts["safer"], n),
            code_changed,
            fmt_ci(code_changed, n),
        ])
    return rows


def prompt_rows(states: list[UnitState]) -> list[list]:
    rows = []
    for state in sorted(states, key=lambda s: s.test_case_id):
        rows.append([
            state.test_case_id,
            state.language,
            state.cwe_id,
            state.rules_used_count,
            state.observations,
            state.baseline_score,
            state.min_score,
            state.max_score,
            state.outcome,
            int(state.code_changed),
            state.baseline_raw,
            state.min_raw,
            state.max_raw,
            state.baseline_error,
            state.min_error,
            state.max_error,
            state.baseline_warning,
            state.min_warning,
            state.max_warning,
        ])
    return rows


def exposure_rows(states: list[UnitState]) -> list[list]:
    rows = []
    for state in sorted(states, key=lambda s: (s.rule_id, s.test_case_id)):
        rows.append([
            R.short_rule(state.rule_id),
            state.rule_id,
            state.test_case_id,
            state.language,
            state.cwe_id,
            state.observations,
            state.baseline_score,
            state.min_score,
            state.max_score,
            state.outcome,
            int(state.code_changed),
        ])
    return rows


def prompt_envelope_rows(states: list[UnitState]) -> list[list]:
    n = len(states)
    baseline_weighted = sum(state.baseline_score for state in states)
    worst_weighted = sum(float(state.max_score or 0.0) for state in states)
    best_weighted = sum(float(state.min_score or 0.0) for state in states)
    baseline_raw = sum(state.baseline_raw for state in states)
    worst_raw = sum(int(state.max_raw or 0) for state in states)
    best_raw = sum(int(state.min_raw or 0) for state in states)
    baseline_error = sum(state.baseline_error for state in states)
    worst_error = sum(int(state.max_error or 0) for state in states)
    best_error = sum(int(state.min_error or 0) for state in states)
    baseline_warning = sum(state.baseline_warning for state in states)
    worst_warning = sum(int(state.max_warning or 0) for state in states)
    best_warning = sum(int(state.min_warning or 0) for state in states)
    baseline_clean = sum(1 for state in states if state.baseline_score == 0)
    worst_clean = sum(1 for state in states if float(state.max_score or 0.0) == 0)
    best_clean = sum(1 for state in states if float(state.min_score or 0.0) == 0)
    return [
        ["baseline_original_rules", n, baseline_weighted, baseline_raw, baseline_error, baseline_warning, baseline_clean, fmt_ci(baseline_clean, n)],
        ["worst_observed_rephrasing_envelope", n, worst_weighted, worst_raw, worst_error, worst_warning, worst_clean, fmt_ci(worst_clean, n)],
        ["best_observed_rephrasing_envelope", n, best_weighted, best_raw, best_error, best_warning, best_clean, fmt_ci(best_clean, n)],
    ]


def summary_row(outcome: RunOutcome) -> list:
    run = outcome.run
    prompt = states_for_scope(outcome, "prompt")
    applicable = states_for_scope(outcome, "applicable")
    all_scope = states_for_scope(outcome, "all_prompt_rules")
    prompt_counts = distribution(prompt)
    app_counts = distribution(applicable)
    all_counts = distribution(all_scope)
    prompt_n = len(prompt)
    app_n = len(applicable)
    all_n = len(all_scope)
    positive_iters = sum(1 for it in L.valid_iters(run) if float(it.get("f1") or 0.0) > 0)
    n_iters = len(L.valid_iters(run))

    app_macro = macro_rates(applicable)
    all_macro = macro_rates(all_scope)

    return [
        run_label(run),
        run.strategy,
        lang_key(run),
        run.seed,
        prompt_n,
        len({state.rule_id for state in all_scope if state.rule_id}),
        app_n,
        all_n,
        prompt_counts["degraded"] / prompt_n if prompt_n else 0.0,
        prompt_counts["unchanged"] / prompt_n if prompt_n else 0.0,
        prompt_counts["safer"] / prompt_n if prompt_n else 0.0,
        sum(1 for state in prompt if state.code_changed) / prompt_n if prompt_n else 0.0,
        app_counts["degraded"] / app_n if app_n else 0.0,
        app_counts["unchanged"] / app_n if app_n else 0.0,
        app_counts["safer"] / app_n if app_n else 0.0,
        sum(1 for state in applicable if state.code_changed) / app_n if app_n else 0.0,
        app_macro["degraded"],
        app_macro["unchanged"],
        app_macro["safer"],
        app_macro["code_changed"],
        all_counts["degraded"] / all_n if all_n else 0.0,
        all_counts["unchanged"] / all_n if all_n else 0.0,
        all_counts["safer"] / all_n if all_n else 0.0,
        sum(1 for state in all_scope if state.code_changed) / all_n if all_n else 0.0,
        all_macro["degraded"],
        all_macro["unchanged"],
        all_macro["safer"],
        all_macro["code_changed"],
        positive_iters / n_iters if n_iters else 0.0,
        L.best_f1(run),
    ]


def paired_rows(outcomes: list[RunOutcome]) -> list[list]:
    by_key: dict[tuple[str, object, str], RunOutcome] = {}
    for outcome in outcomes:
        run = outcome.run
        by_key[(lang_key(run), run.seed, run.strategy)] = outcome

    rows = []
    for language, seed in sorted({(language, seed) for language, seed, _strategy in by_key}):
        ea = by_key.get((language, seed, "ea"))
        random = by_key.get((language, seed, "random_baseline"))
        if ea is None or random is None:
            continue
        prompt_ids = sorted(set(ea.prompt_states) & set(random.prompt_states))
        ea_deg = [ea.prompt_states[tc].outcome == "degraded" for tc in prompt_ids]
        rd_deg = [random.prompt_states[tc].outcome == "degraded" for tc in prompt_ids]
        ea_changed = [ea.prompt_states[tc].code_changed for tc in prompt_ids]
        rd_changed = [random.prompt_states[tc].code_changed for tc in prompt_ids]
        test = S.mcnemar_binary(rd_deg, ea_deg)
        rows.append([
            language,
            seed,
            len(prompt_ids),
            sum(ea_deg),
            sum(rd_deg),
            sum(1 for a, b in zip(ea_deg, rd_deg) if a and b),
            sum(1 for a, b in zip(ea_deg, rd_deg) if a and not b),
            sum(1 for a, b in zip(ea_deg, rd_deg) if b and not a),
            sum(1 for a, b in zip(ea_deg, rd_deg) if not a and not b),
            test.p if test.p is not None else "",
            test.note,
            sum(ea_changed),
            sum(rd_changed),
        ])
    return rows
