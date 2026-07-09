# Review of ANALYSIS_PLAN.md — correctness pass (2026-07-09)

Read this alongside `ANALYSIS_PLAN.md`. The plan is **well-structured, its code references are accurate, and its statistics are sound** — but it was drafted before the objective redesign (fidelity/parsimony) and the 2×2 experiment, so its treatment of f2/f3 and of "RQ3 = EA vs random" is now **stale and must be reframed**. Below: what's verified-good, the one structural correction, section-by-section fixes, data-claim checks, and the literature assessment.

## Verified good (no change)
- **Code references are accurate.** Every cited function exists: `stats.py` has `mann_whitney_u`, `vargha_delaney_a12`, `wilcoxon_paired`, `mcnemar_binary`, `sign_test`, `friedman_test`, `cliffs_delta`, `bootstrap_ci`, `wilson_ci`; `metrics/mutators.py` has `lineage_steps`, `combination_counts`, `per_rule_best_path`, `per_rule_safest_path`; `loaders.py` has `per_rule_best/worst`, `convergence`, `best_f1`; `metrics/search.py` has `final_front_rows`. (Minor: the plan sometimes drops the suffix — it's `wilcoxon_paired`, `friedman_test`, `wilson_ci`.) The "entrypoints declare schema-2" claim is correct.
- **Statistics methodology (Part D) is correct** and matches SBSE practice: multiple runs, independent-sample MWU + Â₁₂, effect size always paired with a test, Holm for families, honesty about small n. Keep as-is.
- **Data claims that I could check are accurate:** C4 (185 tasks, 367→320 = 47 removed, 12.8%) matches run A s44; C8 move-mix (mutate 10.1% / order 9.1% / reverse 2.2% f1-advance) matches the sanity analysis; C11 depth-vs-drift (depth 4 ≈ 12% below 0.75) matches. **Caveat: all three came from divergence-mode / sanity runs — see below, they shift under option_b.**

## THE structural correction — the plan predates option_b + the 2×2

The plan assumes (i) f2/f3 are fixed **divergence** axes and (ii) the experiment is **EA vs random, 5 seeds, both languages**. Neither is now true:

1. **f2/f3 are no longer fixed, and the divergence definition in A.2 is the *buggy* one.** A.2/line 63 defines f2 as "fraction of **affected** prompts whose code diverges" — that affected-subset denominator was a bug (chromosome-dependent, incomparable across the archive); it's been fixed to the **full prompt set** (`n_total`). More importantly, the archive now has **two selectable objective sets**, and the experiment *compares them*:
   - `divergence`: f1 = findings removed, f2 = `proportion_divergent` (now /n_total), f3 = `conditional_mean_divergence`.
   - `option_b`: f1 = findings removed, **f2 = rule fidelity** (mean SBERT of mutated rules vs originals, maximised), **f3 = −parsimony** (−#mutated rules, i.e. minimise the edit).
   Every iteration record now carries `objective_mode` plus **raw** `rule_fidelity`, `parsimony`, `proportion_divergent`, `conditional_mean_divergence` regardless of mode — so the two sets are directly cross-comparable. **Rewrite A.2, and Decision #1 is now largely answered empirically** (we are testing, not just deciding, whether to keep divergence).

2. **The actual runs are a Python-only 2×2, with no random arm.** `experiments/matrix_2x2/{A_stack_div, B_orig_div, C_stack_optb, D_orig_optb}` × seeds 44/45(/46). The primary comparisons are **stacking vs from-original (A↔B, C↔D)** and **divergence vs option_b objectives (A↔C, B↔D)** — not EA vs random. The only random data is the older schema-2 `final_v3` (seeds 42+43, *different code version*). So **RQ3 as written (C1/C2/C3 EA-vs-random) is not directly runnable on this data** and must be either (a) reframed to the 2×2 comparisons, (b) run against `final_v3` random with an explicit cross-version caveat, or (c) deferred to a later sweep with a matched random arm. This is the single biggest edit the plan needs.

## Section-by-section fixes
- **A.2 / Decision #1:** replace the fixed-divergence framing with the two-objective-set framing above; note the f2 denominator fix. Decision #1 becomes "which objective set do we adopt as headline" — informed by A↔C/B↔D results.
- **Part B / RQ3:** re-title from "does guided search beat random?" to also cover "does stacking beat mutating-from-original?" and "do fidelity/parsimony objectives guide search to better repair than divergence?" Keep EA-vs-random as a secondary, caveated comparison vs `final_v3`.
- **C1–C3:** C1 (best-f1 MWU+Â₁₂) is the right *machinery*, but apply it to the 2×2 contrasts (A vs B, A vs C, …), not EA-vs-random on this data. C3 (EAF/hypervolume) actually becomes **more** relevant, not less: under option_b the front is a genuine effectiveness×fidelity×parsimony trade-off worth showing — but re-scope it to the option_b objectives (and/or a divergence-vs-option_b front-quality comparison), not the divergence f1×f2.
- **RQ2 headline & C9:** "best rule sets are multi-rule (5–6 genes)" is a **divergence-mode** observation; under option_b the parsimony objective actively shrinks #rules (we saw best chromosomes at 2–6 rules). So the interaction/combination story must be reported **per objective mode**, and #rules is itself an outcome that differs between A/B and C/D. The leave-one-out-via-ablation idea (C9) is still good, but note that with `reverse_weight=0` the reverts come from the **saturation ablation inside the mutate move** (`move_type=="reverse"` with the `(saturated)` change note), only in the *stack* arms (A, C) — from_original arms (B, D) have none.
- **C8 / C10 / C11 / C12:** all still valid and mostly computed already. C10 (reordering) and C11 (depth-drift) are clean secondary results. For C12 (saturated ablation) remember it exists **only in stack arms**; use it as the natural leave-one-out probe for C9 there.
- **C4/C5 (RQ1):** unchanged and correct — this is the headline repair number and is objective-mode-independent (f1 is the same in both modes). Build first.

## Literature assessment
- **Solid / safe to cite as-is:** Arcuri & Briand STVR 2014; Vargha & Delaney 2000; Demšar JMLR 2006; Hoos & Stützle 2004; López-Ibáñez/Paquete/Stützle EAF (Springer 2010) + the `eaf` package; Zitzler & Thiele 1999; Chen et al. pass@k (arXiv:2107.03374, 2021); Sclar et al. FormatSpread (arXiv:2310.11324, 2023); Pearce et al. "Asleep at the Keyboard" S&P 2022. These are real and correctly attributed.
- **Verify the exact IDs/venues before the thesis** (I could not web-check them here; the plan itself already flags this): the SLR "From Vulnerabilities to Remediation" (arXiv:2412.15004), "Can You Really Trust Code Copilots?" (arXiv:2505.10494), "The Order Effect" (arXiv:2502.04134), Mizrahi et al. TACL 2024, and López-Ibáñez et al. arXiv:2404.02031. The ~11%-repair statistic and the "generates insecure code even when instructed" claim should be quoted against the actual source before use.
- The prompt-order citations (C10) are the right family for the reordering result — a genuinely citable secondary contribution.

## Revised build order (given the 2×2)
1. **C4/C5 — RQ1 repair headline** over the vulnerable denominator (objective-mode-independent; unblocks the results section).
2. **2×2 contrasts on best_f1** (A↔B stacking, A↔C objectives, etc.) with MWU+Â₁₂ + anytime curves — this is what tomorrow's discussion needs.
3. **Objective-set behaviour:** show that option_b reaches comparable f1 at higher fidelity / fewer rules (the early signal) — a fidelity/parsimony-vs-f1 front (a re-scoped C3).
4. **C9 interactions + C8 move-type + C10 reordering + C11 depth-drift** — mechanism + design-justification.
5. EA-vs-random (C1/C2) only against `final_v3`, caveated, or as a later sweep.

## Bottom line
The plan is a strong foundation and most of it survives. The mandatory edits are: (1) rewrite the objectives section around the two selectable sets + the denominator fix, and (2) reframe RQ3/C1–C3 from "EA vs random" to the 2×2 contrasts (keeping EA-vs-random as a caveated secondary). Everything else is re-labelling and the new-dimension analyses the plan already scopes well.
