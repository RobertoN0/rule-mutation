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
    lines.append("**What this report answers.** At the level of a *coding task (prompt)*, did rephrasing the "
                 "rules make the model's code worse, safer, or unmoved on security — and did the code change at "
                 "all? This is the prompt-level companion to the run's fitness numbers.")
    lines.append("\n## Overview")
    lines.append(f"- strategy: **{run.strategy}** | language: {OC.lang_key(run)} | seed: {run.seed}")
    lines.append(f"- prompts: {len(prompt_states)} | mutated rules: {len({s.rule_id for s in all_scope_states})}")
    lines.append(f"- applicable rule-prompt exposures: {len(applicable_states)} | all-prompt-rule exposures: {len(all_scope_states)}")
    lines.append(
        "\n_Each unit is labelled by its outcome over every rephrasing of its rules: **degraded** = it ever "
        "produced MORE findings than the original rule, **safer** = ever FEWER, **unchanged** = never moved. "
        "**code_changed** is separate — the generated code differed at all. ⚠️ **Interpretation caveat:** the "
        "label is degraded-FIRST — a prompt that at some point went up AND at another point went down is counted "
        "as `degraded`, so `safer` here is a LOWER BOUND. For the clean repair count (safest result kept per "
        "prompt) use the `repair/` report, not this rate._")
    lines.append("\n## Prompt-level outcome (the headline)")
    lines.append("**What & why.** One unit per prompt, collapsed over all rephrasings of its rules — the main "
                 "prompt-level result. **How to read:** compare `degraded` vs `safer` (net push toward more- or "
                 "less-vulnerable code) and watch for **high `code_changed` with low degraded+safer** = the model "
                 "rewrote the code but its security didn't move (rephrasing perturbs behaviour more than security).")
    lines.append(md_table(OR.MICRO_HEADER, [micro_rows[0]]))
    lines.append("\n### Worst / best finding envelopes")
    lines.append("**What & why.** Not a single treatment: each prompt contributes its worst (most findings) and "
                 "its best (fewest) observed rephrasing, summed across prompts. **How to read:** the gap between "
                 "the baseline column and the 'best' column is the repair headroom the search reached; the gap to "
                 "'worst' is how much damage a bad rephrasing could do — both directions exist under one search.")
    lines.append(md_table(OR.ENVELOPE_HEADER, envelope_rows))
    lines.append("\n## The three counting scopes")
    lines.append("**What & why.** The same degraded/safer/unchanged split, counted three ways — they differ "
                 "**only in the denominator**, so the same effect looks bigger or smaller. Report the one that "
                 "matches the claim:")
    lines.append("- **prompt** — one unit per test case (the headline above); the readable 'did this task move?'.")
    lines.append("- **applicable** — one unit per (rule, prompt) pair where that rule was actually retrieved; "
                 "rule-faithful, since a prompt often uses several rules.")
    lines.append("- **all_prompt_rules** — every mutated rule × every prompt; pairs where the rule was not used "
                 "count as unchanged, so the rates shrink (a deliberately conservative denominator).")
    lines.append("\n_micro = pooled over all units; macro = mean of per-rule rates (so a few prompt-heavy rules "
                 "don't dominate). If micro ≫ macro, the effect is concentrated in high-fan-out rules._")
    lines.append("\n### Micro (pooled) at the rule-prompt scopes")
    lines.append(md_table(OR.MICRO_HEADER, micro_rows[1:]))
    lines.append("\n### Macro (mean of per-rule rates)")
    lines.append(md_table(OR.MACRO_HEADER, macro_rows))
    lines.append("\n## Distribution figure (the three scopes side by side)")
    lines.append("_What: the degraded/unchanged/safer split as stacked bars, one group per scope. How to read: "
                 "left→right the denominator widens (prompt→applicable→all_prompt_rules) so the coloured bars "
                 "shrink; the **shape** (degraded vs safer share) is the takeaway, not the absolute height. A tall "
                 "grey 'unchanged' band is expected here — most prompts never move._")
    lines.append(f"![Outcome distribution]({fig.name})")
    lines.append("\n## Per-rule applicable rates")
    lines.append("_Which rules, when rephrased, actually move their prompts. Use it to spot the few high-leverage "
                 "rules behind the pooled numbers._")
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

    lines = ["# Cross-run outcome distribution\n", f"Runs: {len(outcomes)}\n",
             "**What this report answers.** Pooled across seeds, what share of prompts each strategy pushed "
             "worse / safer / left unchanged, and (with matched EA+random) whether the two search methods move "
             "the SAME prompts. Rows are grouped by strategy × language.\n"]
    lines.append("## Mean rates by strategy and language")
    lines.append("_Each cell is the mean over that group's seeds. **How to read:** compare `prompt_degraded_rate` "
                 "vs `prompt_safer_rate` for the net direction; a large `prompt_code_changed_rate` next to small "
                 "degraded+safer means rephrasing changed the code but not its security. EA vs random rows that "
                 "look alike = no strategy effect (RQ3). Column definitions are in the reference at the bottom._")
    pretty_agg = []
    display_cols = [
        "prompt_degraded_rate", "prompt_safer_rate", "prompt_code_changed_rate",
        "applicable_micro_degraded_rate", "applicable_micro_code_changed_rate",
        "all_micro_degraded_rate", "all_micro_code_changed_rate",
        "positive_iteration_rate", "best_fitness",
    ]
    display_indices = [aggregate_header.index(col) for col in display_cols]
    for row in aggregate_rows:
        pretty_agg.append([row[0], row[1], row[2]] + [
            f"{row[idx]:.4f}" if display_cols[i] == "best_fitness" else fmt_pct(float(row[idx]))
            for i, idx in enumerate(display_indices)
        ])
    lines.append(md_table(["strategy", "language", "n_runs"] + display_cols, pretty_agg))
    if pair_rows:
        lines.append("\n## RQ3 prompt-level EA vs random pairs")
        lines.append("**What & why.** For each seed, take the 351/229 prompts and cross-tabulate whether EA and "
                     "random each *degraded* that prompt. This asks a different RQ3 question than best-fitness: do "
                     "the two methods act on the SAME prompts, or different ones? **How to read the columns:** "
                     "`both` = degraded by both, `ea_only`/`random_only` = the discordant prompts (degraded by one "
                     "method only), `neither` = untouched. **`mcnemar_p`** is McNemar's test on the discordant "
                     "pairs: **p < 0.05** = the two methods systematically degrade *different* prompts (a real "
                     "behavioural difference); **p ≥ 0.05** = no asymmetry. Note the small-count floor — if "
                     "`ea_only + random_only` is tiny, McNemar can't be significant regardless. `lost_vuln` / "
                     "`newly_vuln` in the note count the discordant directions.")
        pretty_pairs = []
        for row in pair_rows:
            pretty_pairs.append(row[:9] + [f"{row[9]:.4g}" if row[9] != "" else "", row[10], row[11], row[12]])
        lines.append(md_table(OR.PAIR_HEADER, pretty_pairs))

    direction = outcomes[0].run.objective_direction if outcomes else "minimize"
    lines.append(_field_reference(direction))
    (out_dir / "outcome_comparison.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _field_reference(objective_direction: str) -> str:
    """The column glossary, worded for the run's objective direction (minimize = repair)."""
    from loaders import direction_terms
    t = direction_terms(objective_direction)
    return f"""
## How to read this table (column reference)

Every number is a **rate**: the share of "units" in a given outcome. A unit is counted three ways
(same split, different denominator — see the per-run report):

- **prompt** — one per test case (the headline). **applicable** — one per (rule, prompt) actually used.
  **all** — every rule × every prompt; unused pairs count as unchanged, so these rates look smaller.

A prompt falls into exactly one **outcome**: **degraded** = ever produced MORE findings than the original
rule; **safer** = ever FEWER; **unchanged** = never moved. The label is **degraded-first**, so `safer` is a
lower bound (a prompt that moved both ways is called degraded) — use the `repair/` report for the clean
repair count. **code_changed** is separate — the generated code differed at all, even with the same findings.

Columns:
- `*_degraded_rate` / `*_safer_rate` — share of units that got worse / safer. Good sign for the repair story:
  safer ≥ degraded. On this data they are near-equal (python) or degraded > safer (java = rules backfire).
- `*_code_changed_rate` — share whose generated code changed at all. Expect this to be HIGH (~80%) while the
  security rates are LOW — rephrasing perturbs behaviour far more than security.
- `positive_iteration_rate` — fraction of search iterations that {t['positive_iter_label']} (fitness improved).
  Under the **{t['goal']}** objective a "positive" iteration is a SAFER one. Higher = the search was productive
  more often.
- `best_fitness` — the single best iteration reached; here {t['best_f1_label']} (weighted findings, ERROR=3,
  WARNING=1). Larger = safer. The opposite extreme is in the trajectory / mutator reports.
"""
