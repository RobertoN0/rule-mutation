"""
Search-behaviour (G3 / RQ3) report assembly: per-run efficiency / restart /
Pareto-front CSV + Markdown + plots, and a cross-run efficiency comparison
(EA vs random) with an overlaid convergence figure.
"""

from __future__ import annotations

import statistics
from pathlib import Path

import loaders as L
import stats as S
from metrics import search as SR
from report.tables import md_table, write_csv
from viz import search as VSR


def write_run_report(run: L.RunData, out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    restart = SR.restart_rows(run)
    front = SR.final_front_rows(run)

    write_csv(out_dir / "efficiency.csv", SR.EFFICIENCY_HEADER, [SR.efficiency_row(run)])
    write_csv(out_dir / "restart_reasons.csv", SR.RESTART_HEADER, restart)
    write_csv(out_dir / "final_front.csv", SR.FRONT_HEADER, front)

    VSR.restart_reason_bar(restart, out_dir / "restart_reasons.png", f"Restart reasons - {run.run_dir.name}")

    terms = L.direction_terms(run.objective_direction)
    lines = [
        f"# Search behaviour — {run.run_dir.name}",
        f"_Objective: **{terms['goal']}**. Within this run **higher fitness = {terms['high_label']}** "
        "(the security objective is negated at search time for the minimize direction, so a larger fitness "
        "always means safer code here). This report characterises HOW the search moved — it is a mechanism / "
        "sanity view, not the repair result (that is in the `repair/` report)._\n",
        "## Efficiency",
        "**What & why.** One row summarising how productively this run searched. Feeds RQ3 (is the search "
        "actually finding things?) and flags degenerate runs.",
        "**How to read each column:**",
        f"- `best_fitness` — the single best (safest) iteration reached; larger = {terms['high_label']}. This is "
        "the RQ3 response variable in the cross-run report.",
        "- `iter_to_first_best` — iteration at which that best first appeared (time-to-best); lower = peaked "
        "sooner. ⚠️ For the random baseline a very low value usually means one lucky early draw, not efficient "
        "convergence — read it together with the convergence-band figure, not on its own.",
        f"- `positive_iteration_rate` — share of iterations that {terms['positive_iter_label']} (fitness "
        "improved). Higher = the search more often found a productive rephrasing. Typical here: ~0.3–0.5 "
        "(python), ~0.05–0.13 (java, where the signal is much sparser).",
        "- `acceptance_rate` — share of candidates accepted into an archive. EA ≈ 0.8 (the Pareto archive keeps "
        "anything improving ANY of the 3 objectives, not just security), random = 1.0 (keeps everything). This "
        "is a **mechanism** stat, not a quality score — a high value is expected, not 'good'.",
        "- `identity_rate` — share of no-op mutations (a stochastic mutator returned the rule unchanged). "
        "Near 0 is good (few wasted iterations).",
        md_table(SR.EFFICIENCY_HEADER, [SR.efficiency_row(run)]),
        "\n## Restart reasons",
        "**What & why.** When the (1+1) hill-climb stalls on a rule it restarts; this counts why. It is the "
        "evidence for the bd-qfm methodology check: under `restart_h=8` the `stagnation` trigger should **never** "
        "fire, so restarts are driven by depth-saturation (a chain hit max depth), not by the search giving up early.",
        "**How to read.** Expect `stagnation` = 0. A non-zero `stagnation` would mean the horizon was too short "
        "and rules were abandoned prematurely — a red flag for the search configuration, not a result.",
        md_table(SR.RESTART_HEADER, restart),
        "\n![restart reasons](restart_reasons.png)\n",
        "## Final Pareto front per rule",
        "**What & why.** For each mutated rule, the surviving Pareto-archive entries — how far the search pushed "
        "that rule in each direction and how deep the mutation chains went. (Random has no archive, so this is "
        "EA-only.)",
        "**How to read** (this table shows f1/f2/f3 together = Pareto context, so the f-names are kept): "
        f"`min_f1` = {terms['low_label']} kept on the front, `max_f1` = {terms['high_label']} kept, "
        "`max_f2`/`max_f3` = how much the generated code diverged (behaviour axis, ≥0), `max_depth` = deepest "
        "chain reached, `n_inserts`/`n_rejected` = archive churn. A rule whose `max_f1` is well above 0 is one "
        "the search could meaningfully repair; a flat front (min≈max≈0) is an inert rule.",
        md_table(SR.FRONT_HEADER, front) if front else "(no archive — random baseline)",
    ]
    (out_dir / "search.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_comparison(runs: list[L.RunData], out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    rows = [SR.efficiency_row(run) for run in runs]
    write_csv(out_dir / "efficiency_comparison.csv", SR.EFFICIENCY_HEADER, rows)

    by_strat: dict[str, list[L.RunData]] = {}
    for r in runs:
        by_strat.setdefault(r.strategy, []).append(r)

    lines = ["# Search efficiency comparison\n", f"Runs: {len(runs)}\n",
             "**What this report answers (RQ3).** Does the guided (1+1) evolutionary search beat an "
             "unguided random search at finding rule rephrasings that reduce vulnerabilities? Both arms get "
             "the same budget on the same tasks (the Arcuri & Briand fair comparison), so any difference is "
             "the guidance, not the setup. One run = one seed; the arm is the population of seeds.\n",
             "_Per-column meaning of the table below is documented in each run's `search.md` "
             "(`best_fitness`, `iter_to_first_best`, `positive_iteration_rate`, `acceptance_rate`, "
             "`identity_rate`)._"]
    lines.append(md_table(SR.EFFICIENCY_HEADER, rows))

    # ---- RQ3: EA vs random on best fitness — independent samples (Arcuri & Briand) ----
    ea, rand = by_strat.get("ea", []), by_strat.get("random_baseline", [])
    if ea and rand:
        terms = L.direction_terms(ea[0].objective_direction)
        ea_bf = [L.best_f1(r) for r in ea]
        rd_bf = [L.best_f1(r) for r in rand]
        lines.append("\n## RQ3 — EA vs random (best fitness)")
        lines.append(f"**What & why.** `best fitness` = {terms['best_f1_label']} (the single safest iteration "
                     "each run reached). Per-seed runs at a fixed prompt set are **independent samples** (no "
                     "shared nuisance), so we use an **unpaired Mann-Whitney U** on the two sets of 5 values, "
                     "with **Vargha-Delaney Â₁₂** as the effect size. Caveat: best fitness is a single-rule "
                     "maximum and rewards sampling breadth — read it alongside the aggregate-repair view in the "
                     "`repair/` report.")
        lines.append(md_table(
            ["arm", "n", "best fitness (sorted)", "median"],
            [["ea", len(ea_bf), ", ".join(f"{v:+.1f}" for v in sorted(ea_bf, reverse=True)),
              f"{statistics.median(ea_bf):+.2f}"],
             ["random", len(rd_bf), ", ".join(f"{v:+.1f}" for v in sorted(rd_bf, reverse=True)),
              f"{statistics.median(rd_bf):+.2f}"]],
        ))
        mw = S.mann_whitney_u(ea_bf, rd_bf)
        a12, mag = S.vargha_delaney_a12(ea_bf, rd_bf)
        favours = "EA" if a12 > 0.5 else ("random" if a12 < 0.5 else "neither")
        lines.append(f"\n- {mw}")
        lines.append(f"- Vargha-Delaney Â₁₂ = **{a12:.3f}** ({mag}) — this is P(a random EA run scores above a "
                     f"random opposing run); it favours **{favours}**.")
        lines.append(_RQ3_INTERPRETATION)

    VSR.best_f1_box(by_strat, out_dir / "best_f1_box.png", "best fitness per run by strategy")
    lines.append("\n### Figure — best-fitness box plot")
    lines.append("_What: the distribution of the 5 per-seed best-fitness values per arm (box = median + IQR, "
                 "whiskers = range, dots = the individual seeds). How to read: if one arm's box sits clearly "
                 "above the other with little overlap, that arm finds safer rephrasings; heavy overlap (our "
                 "case) = no strategy advantage. Higher = safer._")
    lines.append("\n![best fitness box](best_f1_box.png)")
    VSR.convergence_band(by_strat, out_dir / "convergence_band.png",
                         f"Convergence — median + IQR ({len(runs)} runs)")
    lines.append("\n### Figure — convergence band")
    lines.append("_What: median best-so-far fitness vs iteration, one band per arm (shaded = IQR across seeds). "
                 "How to read: this is the honest 'time-to-best' view — an arm whose band rises faster is more "
                 "efficient at equal budget. A random band that jumps early then stays flat = lucky single "
                 "draws, not convergence; an EA band that climbs steadily but ends level with random = guidance "
                 "buys ordering, not a better endpoint._")
    lines.append("\n![convergence band](convergence_band.png)\n")
    (out_dir / "efficiency_comparison.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


_RQ3_INTERPRETATION = """
**How to interpret these two numbers (reference values):**
- **Mann-Whitney U p** — probability of a gap this large if the two arms were drawn from the same
  distribution. Significant at **p < 0.05**. Small-sample floor: with 5 vs 5 the smallest two-sided p
  reachable is **0.0079**, with 4 vs 4 it is 0.029, with 3 vs 3 it is 0.10 (so below n=4 per arm you
  **cannot** reach 0.05 — read the effect size instead). p ≥ 0.05 at n=5 means *no detectable difference*
  (which can be a true null OR simply underpowered — do not read it as "proven equal").
- **Vargha-Delaney Â₁₂** — 0.5 = no effect (the arms are interchangeable). Magnitude thresholds (|Â−0.5|):
  **small ≈ 0.56 / 0.44, medium ≈ 0.64 / 0.36, large ≈ 0.71 / 0.29**. Direction: **> 0.5 favours the EA,
  < 0.5 favours random.** Â₁₂ is meaningful even when p is not significant, so it is the primary read at
  this sample size.
- **What is "good" for the thesis here?** Not a particular direction — a *clear* result either way. A large
  Â far from 0.5 says guidance matters; Â ≈ 0.5 with p ≥ 0.05 is the honest finding that on this landscape a
  guided search is no better than random (still a valid RQ3 answer, since it shows the repairs are findable
  by sampling and the value lies in the search framing, not the guidance).
"""
