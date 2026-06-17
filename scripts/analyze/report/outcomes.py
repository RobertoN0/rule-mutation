"""
Outcome-distribution report assembly: turns the ``metrics.outcomes`` core +
``metrics.outcome_rows`` builders into per-run and cross-run CSV + Markdown (and
triggers the distribution figure). This is the only outcome layer that writes files.
"""

from __future__ import annotations

import statistics
from collections import defaultdict
from pathlib import Path

from metrics import outcome_rows as OR
from metrics import outcomes as OC
from report.tables import fmt_pct, md_table, write_csv
from viz.distributions import outcome_distribution_figure


def write_run_report(outcome: OC.RunOutcome, out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    run = outcome.run

    prompt_states = OC.states_for_scope(outcome, "prompt")
    applicable_states = OC.states_for_scope(outcome, "applicable")
    all_scope_states = OC.states_for_scope(outcome, "all_prompt_rules")

    write_csv(out_dir / "prompt_outcomes.csv", OR.PROMPT_HEADER, OR.prompt_rows(prompt_states))

    write_csv(out_dir / "rule_prompt_outcomes_applicable.csv", OR.EXPOSURE_HEADER, OR.exposure_rows(applicable_states))
    write_csv(out_dir / "rule_prompt_outcomes_all_prompt_rules.csv", OR.EXPOSURE_HEADER, OR.exposure_rows(all_scope_states))

    applicable_rule_rows = OR.per_rule_rows(applicable_states)
    all_rule_rows = OR.per_rule_rows(all_scope_states)
    write_csv(out_dir / "per_rule_applicable.csv", OR.PER_RULE_HEADER, applicable_rule_rows)
    write_csv(out_dir / "per_rule_all_prompt_rules.csv", OR.PER_RULE_HEADER, all_rule_rows)

    micro_rows = [OR.micro_row(scope, OC.states_for_scope(outcome, scope)) for scope in OC.SCOPES]
    write_csv(out_dir / "micro_summary.csv", OR.MICRO_HEADER, micro_rows)

    macro_rows = [OR.macro_row(scope, OC.states_for_scope(outcome, scope)) for scope in ("applicable", "all_prompt_rules")]
    write_csv(out_dir / "macro_summary.csv", OR.MACRO_HEADER, macro_rows)

    envelope_rows = OR.prompt_envelope_rows(prompt_states)
    write_csv(out_dir / "prompt_envelope_totals.csv", OR.ENVELOPE_HEADER, envelope_rows)

    fig = outcome_distribution_figure(outcome, out_dir)

    lines: list[str] = [f"# Outcome distribution - {OC.run_label(run)}\n"]
    lines.append("## Overview")
    lines.append(f"- strategy: **{run.strategy}** | language: {OC.lang_key(run)} | seed: {run.seed}")
    lines.append(f"- prompts: {len(prompt_states)} | mutated rules: {len({s.rule_id for s in all_scope_states})}")
    lines.append(f"- applicable rule-prompt exposures: {len(applicable_states)} | all-prompt-rule exposures: {len(all_scope_states)}")
    lines.append(
        "\n_Each unit is labelled by its **worst observed outcome** over every rephrasing of its rules: "
        "**degraded** = it ever produced more findings than the original rule, **safer** = ever fewer, "
        "**unchanged** = never moved. **code_changed** is separate — the generated code differed at all. "
        "**What to look at:** compare degraded vs safer (is the net push toward more- or less-vulnerable code?), "
        "and watch for high code_changed with low degraded — the model rewrote the code without changing its security._")
    lines.append("\n## Prompt-level outcome (the headline)")
    lines.append("_One row, one unit per prompt, collapsed over all rephrasings of the rules it uses. This is the main result._")
    lines.append(md_table(OR.MICRO_HEADER, [micro_rows[0]]))
    lines.append("\n### Worst / best finding envelopes")
    lines.append("_Not a single treatment: each prompt contributes its worst (most findings) and its best (fewest) "
                 "observed rephrasing, summed across prompts — the spread the search could reach in either direction._")
    lines.append(md_table(OR.ENVELOPE_HEADER, envelope_rows))
    lines.append("\n## The three counting scopes")
    lines.append("_The same degraded/safer/unchanged split, counted three ways. They differ **only in the denominator**:_")
    lines.append("- **prompt** — one unit per test case (the headline above).")
    lines.append("- **applicable** — one unit per (rule, prompt) pair where that rule was actually retrieved for the prompt.")
    lines.append("- **all_prompt_rules** — every mutated rule x every prompt; pairs where the rule was not used count as "
                 "unchanged, so the rates shrink (a deliberately conservative view).")
    lines.append("\n_micro = pooled over units; macro = mean of per-rule rates (so a few prompt-heavy rules don't dominate)._")
    lines.append("\n### Micro (pooled) at the rule-prompt scopes")
    lines.append(md_table(OR.MICRO_HEADER, micro_rows[1:]))
    lines.append("\n### Macro (mean of per-rule rates)")
    lines.append(md_table(OR.MACRO_HEADER, macro_rows))
    lines.append("\n## Distribution figure (the three scopes side by side)")
    lines.append("_Left to right the denominator widens (prompt to applicable to all_prompt_rules), so the coloured bars "
                 "shrink; the **shape** (degraded vs safer share) is the takeaway, not the absolute height._")
    lines.append(f"![Outcome distribution]({fig.name})")
    lines.append("\n## Per-rule applicable rates")
    lines.append(md_table(OR.PER_RULE_HEADER, applicable_rule_rows) if applicable_rule_rows else "(no applicable rule-prompt exposures)")

    (out_dir / "outcome_distribution.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_cross_run_report(outcomes: list[OC.RunOutcome], out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    summary_rows = [OR.summary_row(outcome) for outcome in outcomes]
    write_csv(out_dir / "runs_summary.csv", OR.SUMMARY_HEADER, summary_rows)

    aggregate_rows = []
    groups: dict[tuple[str, str], list[list]] = defaultdict(list)
    for row in summary_rows:
        groups[(row[1], row[2])].append(row)
    rate_columns = list(range(8, len(OR.SUMMARY_HEADER)))
    for (strategy, language), rows in sorted(groups.items(), key=lambda kv: (kv[0][1], kv[0][0])):
        agg = [strategy, language, len(rows)]
        for idx in rate_columns:
            vals = [float(row[idx]) for row in rows]
            agg.append(statistics.mean(vals))
        aggregate_rows.append(agg)
    aggregate_header = ["strategy", "language", "n_runs"] + [OR.SUMMARY_HEADER[idx] for idx in rate_columns]
    write_csv(out_dir / "aggregate_by_strategy_language.csv", aggregate_header, aggregate_rows)

    pair_rows = OR.paired_rows(outcomes)
    write_csv(out_dir / "rq3_prompt_pairs.csv", OR.PAIR_HEADER, pair_rows)

    lines = ["# Cross-run outcome distribution\n", f"Runs: {len(outcomes)}\n"]
    lines.append("## Mean rates by strategy and language")
    pretty_agg = []
    display_cols = [
        "prompt_degraded_rate", "prompt_safer_rate", "prompt_code_changed_rate",
        "applicable_micro_degraded_rate", "applicable_micro_code_changed_rate",
        "all_micro_degraded_rate", "all_micro_code_changed_rate",
        "positive_iteration_rate", "best_f1",
    ]
    display_indices = [aggregate_header.index(col) for col in display_cols]
    for row in aggregate_rows:
        pretty_agg.append([row[0], row[1], row[2]] + [
            f"{row[idx]:.4f}" if display_cols[i] == "best_f1" else fmt_pct(float(row[idx]))
            for i, idx in enumerate(display_indices)
        ])
    lines.append(md_table(["strategy", "language", "n_runs"] + display_cols, pretty_agg))
    if pair_rows:
        lines.append("\n## RQ3 prompt-level EA vs random pairs")
        pretty_pairs = []
        for row in pair_rows:
            pretty_pairs.append(row[:9] + [f"{row[9]:.4g}" if row[9] != "" else "", row[10], row[11], row[12]])
        lines.append(md_table(OR.PAIR_HEADER, pretty_pairs))

    lines.append(_FIELD_REFERENCE)
    (out_dir / "outcome_comparison.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


_FIELD_REFERENCE = """
## How to read this table

Every number is a **rate**: the share of "units" that ended up in a given
outcome. A unit is counted three ways (each answers a slightly different
question, so all three are shown):

- **prompt** — one per test case: "did this prompt's code ever get worse, or
  safer, across any rephrasing of its rules?" This is the headline view.
- **applicable** — one per (rule, prompt) the rule was actually used on.
- **all** — every rule x every prompt; unused pairs count as unchanged, so these
  rates look smaller (a deliberately conservative denominator).

A prompt falls into exactly one **outcome**: **degraded** = produced more
findings than the original rule at least once; **safer** = fewer at least once;
**unchanged** = never moved. **code_changed** is separate — the generated code
differed at all, even if the finding count didn't.

Columns:
- `*_degraded_rate` / `*_safer_rate` — share of units that got worse / safer.
- `*_code_changed_rate` — share whose generated code changed at all.
- `positive_iteration_rate` — how often the search actually found a more-vulnerable
  rephrasing (fraction of iterations with f1 > 0).
- `best_f1` — the single most-vulnerable result reached (extra weighted findings;
  ERROR counts 3, WARNING 1). The opposite, *safer* extreme is shown in the
  trajectory and mutator reports.

RQ3 pair columns appear only with matched EA + random runs: **both_degraded /
ea_only / random_only / neither** compare the two search methods on the same
prompts, and **mcnemar_p** tests whether they degrade *different* prompts.
"""
