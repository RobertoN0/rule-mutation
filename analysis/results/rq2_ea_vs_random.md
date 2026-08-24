# RQ2 - archive EA vs i.i.d. random search (equal 24 h wall clock)

> **Superseded inference.** The paired values and descriptive estimates remain
> valid, but the exact sign test and its Holm decisions below are provenance
> only. The submitted thesis uses the exact Wilcoxon signed-rank test and A12 in
> `rq_wilcoxon_effect_sizes.json`.

Unit of analysis: the paired run seed. Strata are never pooled.
Primary outcome: best raw Semgrep-finding reduction (`f1`).
The score is the best structurally compliant candidate observed within each
raw search. This post-hoc filter does not reconstruct constrained trajectories.

## Declared family

- **Family**: 4 strata x 1 primary outcome (best raw finding reduction)
- **Rationale**: Four pre-specified (not pre-registered) model/language strata. Raw p-values are shown, while Holm controls the four-test family.
- Holm thresholds attach to p-value rank, not to a fixed stratum.

## Historical result - paired effect size and superseded exact sign test

| stratum | n | median Δ [95% boot CI] | paired superiority | + / - / tie | sign p | Holm p-thr | Holm rejects |
|---|---:|---|---:|---:|---:|---:|:--:|
| llama_java | 10 | 1.5 [-0.5, 3.0] | 0.700 | 6 / 2 / 2 | 0.28906 | 0.0250 | no |
| llama_python | 10 | 3.0 [-5.0, 8.0] | 0.600 | 6 / 4 / 0 | 0.75391 | 0.0500 | no |
| qwen_java | 10 | 1.5 [0.0, 3.5] | 0.800 | 7 / 1 / 2 | 0.07031 | 0.0125 | no |
| qwen_python | 10 | 10.5 [0.0, 15.0] | 0.750 | 7 / 2 / 1 | 0.17969 | 0.0167 | no |

### Sign-flip sensitivity analysis

The sign-flip test uses magnitudes but its inferential reading assumes that
algorithm labels are exchangeable within a seed pair under the null.

| stratum | mean Δ | sign-flip p | Holm p-thr | Holm rejects |
|---|---:|---:|---:|:--:|
| llama_java | 1.20 | 0.16406 | 0.0250 | no |
| llama_python | 2.40 | 0.47461 | 0.0500 | no |
| qwen_java | 1.70 | 0.05469 | 0.0167 | no |
| qwen_python | 7.50 | 0.03125 | 0.0125 | no |

## Secondary descriptive check - severity-weighted reduction

This is the weighted score attached to each raw-f1-selected compliant
candidate; it was not separately selected as a weighted optimum.

| stratum | median Δ weighted [95% boot CI] | mean Δ weighted |
|---|---:|---:|
| llama_java | 2.0 [-1.0, 8.0] | 3.20 |
| llama_python | 2.0 [-12.0, 16.5] | 4.00 |
| qwen_java | 4.0 [1.5, 5.0] | 3.30 |
| qwen_python | 21.5 [-6.0, 29.5] | 14.70 |

## Diagnostic - evaluations completed (mediator, not an outcome)

| stratum | mean E (EA) | mean E (random) | ratio |
|---|---:|---:|---:|
| llama_java | 113 | 48 | 2.37× |
| llama_python | 88 | 35 | 2.51× |
| qwen_java | 357 | 135 | 2.65× |
| qwen_python | 220 | 83 | 2.65× |

## Per-seed detail

### llama_java (n=10)

| seed | origin | EA f1 | random f1 | Δ | EA E | random E |
|---:|---:|---:|---:|---:|---:|---:|
| 1 | 122 | 11 | 10 | +1 | 121 | 46 |
| 2 | 122 | 8 | 6 | +2 | 121 | 51 |
| 3 | 122 | 6 | 7 | -1 | 97 | 39 |
| 4 | 122 | 9 | 7 | +2 | 124 | 50 |
| 5 | 122 | 12 | 8 | +4 | 124 | 60 |
| 6 | 122 | 8 | 8 | +0 | 119 | 45 |
| 7 | 122 | 8 | 5 | +3 | 114 | 39 |
| 8 | 122 | 8 | 8 | +0 | 94 | 49 |
| 9 | 122 | 3 | 6 | -3 | 103 | 50 |
| 10 | 122 | 13 | 9 | +4 | 114 | 48 |

### llama_python (n=10)

| seed | origin | EA f1 | random f1 | Δ | EA E | random E |
|---:|---:|---:|---:|---:|---:|---:|
| 1 | 253 | 23 | 17 | +6 | 69 | 35 |
| 2 | 253 | 32 | 11 | +21 | 104 | 30 |
| 3 | 253 | 18 | 20 | -2 | 64 | 32 |
| 4 | 253 | 12 | 17 | -5 | 97 | 32 |
| 5 | 253 | 12 | 9 | +3 | 94 | 31 |
| 6 | 253 | 20 | 15 | +5 | 94 | 40 |
| 7 | 253 | 6 | 18 | -12 | 101 | 37 |
| 8 | 253 | 21 | 18 | +3 | 93 | 37 |
| 9 | 253 | 28 | 17 | +11 | 87 | 37 |
| 10 | 253 | 14 | 20 | -6 | 79 | 41 |

### qwen_java (n=10)

| seed | origin | EA f1 | random f1 | Δ | EA E | random E |
|---:|---:|---:|---:|---:|---:|---:|
| 1 | 107 | 8 | 5 | +3 | 374 | 128 |
| 2 | 107 | 7 | 6 | +1 | 353 | 137 |
| 3 | 107 | 9 | 8 | +1 | 364 | 146 |
| 4 | 107 | 11 | 6 | +5 | 364 | 124 |
| 5 | 107 | 5 | 5 | +0 | 351 | 139 |
| 6 | 107 | 3 | 5 | -2 | 297 | 142 |
| 7 | 107 | 5 | 5 | +0 | 384 | 135 |
| 8 | 107 | 8 | 6 | +2 | 388 | 128 |
| 9 | 107 | 11 | 6 | +5 | 345 | 132 |
| 10 | 107 | 8 | 6 | +2 | 354 | 137 |

### qwen_python (n=10)

| seed | origin | EA f1 | random f1 | Δ | EA E | random E |
|---:|---:|---:|---:|---:|---:|---:|
| 1 | 216 | 23 | 15 | +8 | 243 | 79 |
| 2 | 216 | 21 | 11 | +10 | 205 | 89 |
| 3 | 216 | 12 | 12 | +0 | 241 | 92 |
| 4 | 216 | 25 | 10 | +15 | 228 | 73 |
| 5 | 216 | 23 | 11 | +12 | 205 | 93 |
| 6 | 216 | 5 | 13 | -8 | 201 | 91 |
| 7 | 216 | 26 | 11 | +15 | 234 | 82 |
| 8 | 216 | 26 | 15 | +11 | 251 | 53 |
| 9 | 216 | 9 | 12 | -3 | 224 | 86 |
| 10 | 216 | 27 | 12 | +15 | 164 | 91 |
