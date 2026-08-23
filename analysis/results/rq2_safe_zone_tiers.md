# RQ2 safe-zone specification sensitivity

> **Statistical procedure updated.** The lens data, medians, and intervals in
> this file remain current. Its exact sign tests are superseded provenance. The
> submitted thesis uses exact Wilcoxon signed-rank p-values, A12, and
> lens-specific Holm decisions from `rq_wilcoxon_effect_sizes.json`.

Unit: one EA/random pair matched by search seed and initialisation bundle.
Outcome: best raw Semgrep-finding reduction (`f1`) observed in 24 hours.
Historical test within each tier: exact two-sided paired sign test; ties are
excluded. Holm correction covers the four model-language strata within
that tier. The sign-flip test is magnitude-sensitive secondary evidence.

> **Interpretation guardrail.** The core and full tiers are post-hoc
> filters over candidates visited by the historical searches. They do not
> reconstruct fail-closed constrained-search trajectories. The core tier
> is an exploratory component diagnostic and must not be selected as the
> primary result merely because it is more favourable.

## Three lenses

### Raw executed system

**Status:** system-level result. Best result reported by the mutation/search implementation that was actually executed.

| stratum | median EA−random [95% boot CI] | paired superiority | + / − / tie | sign p | Holm threshold | Holm rejects |
|---|---:|---:|---:|---:|---:|:--:|
| llama_java | 3.5 [1.0, 4.5] | 0.900 | 8 / 0 / 2 | 0.00781 | 0.0250 | YES |
| llama_python | 5.5 [3.0, 8.5] | 0.900 | 9 / 1 / 0 | 0.02148 | 0.0500 | YES |
| qwen_java | 4.0 [3.0, 5.0] | 1.000 | 10 / 0 / 0 | 0.00195 | 0.0125 | YES |
| qwen_python | 11.5 [8.0, 14.5] | 1.000 | 10 / 0 / 0 | 0.00195 | 0.0167 | YES |

Superseded sign-test Holm rejections: **4/4**.

### Core structural sensitivity

**Status:** post-hoc exploratory sensitivity. Best observed candidate preserving frontmatter and fenced-code structure; inline-code changes are allowed.

| stratum | median EA−random [95% boot CI] | paired superiority | + / − / tie | sign p | Holm threshold | Holm rejects |
|---|---:|---:|---:|---:|---:|:--:|
| llama_java | 2.0 [1.0, 4.0] | 0.950 | 9 / 0 / 1 | 0.00391 | 0.0125 | YES |
| llama_python | 4.5 [0.0, 11.0] | 0.750 | 7 / 2 / 1 | 0.17969 | 0.0500 | no |
| qwen_java | 3.5 [1.0, 5.0] | 0.900 | 9 / 1 / 0 | 0.02148 | 0.0250 | YES |
| qwen_python | 11.5 [6.5, 15.0] | 0.950 | 9 / 0 / 1 | 0.00391 | 0.0167 | YES |

Superseded sign-test Holm rejections: **3/4**.

### Full safe-zone sensitivity

**Status:** post-hoc conservative sensitivity. Best observed candidate preserving frontmatter, fenced-code blocks, and inline-code spans exactly.

| stratum | median EA−random [95% boot CI] | paired superiority | + / − / tie | sign p | Holm threshold | Holm rejects |
|---|---:|---:|---:|---:|---:|:--:|
| llama_java | 1.5 [-0.5, 3.0] | 0.700 | 6 / 2 / 2 | 0.28906 | 0.0250 | no |
| llama_python | 3.0 [-5.0, 8.0] | 0.600 | 6 / 4 / 0 | 0.75391 | 0.0500 | no |
| qwen_java | 1.5 [0.0, 3.5] | 0.800 | 7 / 1 / 2 | 0.07031 | 0.0125 | no |
| qwen_python | 10.5 [0.0, 15.0] | 0.750 | 7 / 2 / 1 | 0.17969 | 0.0167 | no |

Superseded sign-test Holm rejections: **0/4**.

## Why the full result changes

Across 10,789 completed evaluations, 4,598 (42.6%) failed the full contract. The core tier rejected 2,297 (21.3%); 2,301 evaluations (21.3%) were therefore excluded only by the inline-code requirement.

Issue counts overlap because one evaluation can have multiple problems:

- `fences`: 2,297 evaluations
- `inline`: 3,065 evaluations
- `triple_ticks`: 19 evaluations

## Thesis-safe synthesis

In the mutation space executed by the implementation, the archive EA
outperformed matched random search in all four model-language strata
after Holm correction. A post-hoc exploratory sensitivity analysis
retaining frontmatter and fenced-code structure preserved this conclusion
in three strata. Under the most conservative contract, which additionally
required exact inline-code preservation, the paired advantage remained
descriptively positive in all four strata but no comparison remained
significant after family-wise correction. Thus, the algorithmic advantage
is clear for the executed system but sensitive to the strictest
admissibility definition.

Do not infer from the full-tier non-rejections that EA and random are
equivalent. Also do not claim that a genuinely constrained EA would have
followed the post-hoc filtered trajectory; that counterfactual was not run.
