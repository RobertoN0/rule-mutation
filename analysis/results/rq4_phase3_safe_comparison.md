# RQ4 - safe-zone-aware temperature-0.6 resampling

> **Superseded except for the temperature-zero selection gain.** Pairwise rows
> below use candidate-specific task sets and the earlier exact sign test. The
> submitted thesis's candidate-versus-authored values come from
> `rq4_three_way_baseline_comparison.{json,md}`, which uses one shared task set
> and exact Wilcoxon inference. This file remains for provenance and Figure 4's
> temperature-zero ticks.

Invalid selected candidates use sanitised replays; candidates already passing
the contract retain their existing replays. Authored-rules baselines are reused.
Positive delta means fewer Semgrep findings than the authored-rules baseline.

| stratum | rank | kind | seeds | T=0 gain | median T=0.6 delta [boot CI] | paired superiority | sign p | surviving |
|---|---:|---|---:|---:|---|---:|---:|---:|
| llama_java | 1 | raw_structurally_valid | 20 | 13.0 | 0.5 [-1.5, 5.0] | 0.550 | 0.81453 | 3.8% |
| llama_java | 2 | sanitized_after_structural_violation | 20 | 9.0 | 0.0 [-1.0, 4.5] | 0.525 | 1.00000 | 0.0% |
| llama_java | 3 | raw_structurally_valid | 20 | 12.0 | -0.5 [-1.5, 4.0] | 0.450 | 0.81453 | -4.2% |
| llama_java | 4 | sanitized_after_structural_violation | 20 | 13.0 | 3.5 [-0.5, 5.0] | 0.700 | 0.11532 | 26.9% |
| llama_java | 5 | raw_structurally_valid | 20 | 11.0 | 0.0 [-4.0, 2.5] | 0.500 | 1.00000 | 0.0% |
| llama_python | 1 | raw_structurally_valid | 20 | 32.0 | 10.0 [1.5, 15.5] | 0.725 | 0.06357 | 31.2% |
| llama_python | 2 | sanitized_after_structural_violation | 20 | 31.0 | -2.0 [-7.0, 5.0] | 0.425 | 0.64761 | -6.5% |
| llama_python | 3 | raw_structurally_valid | 20 | 28.0 | 7.0 [-0.5, 10.0] | 0.675 | 0.16707 | 25.0% |
| llama_python | 4 | sanitized_after_structural_violation | 20 | 25.0 | 5.0 [-1.5, 14.0] | 0.625 | 0.35928 | 20.0% |
| llama_python | 5 | sanitized_after_structural_violation | 20 | 25.0 | 5.0 [0.0, 12.0] | 0.700 | 0.11532 | 20.0% |
| qwen_java | 1 | sanitized_after_structural_violation | 20 | 12.0 | 2.0 [0.0, 5.0] | 0.700 | 0.09625 | 16.7% |
| qwen_java | 2 | sanitized_after_structural_violation | 20 | 11.0 | 2.0 [1.0, 4.0] | 0.775 | 0.01921 | 18.2% |
| qwen_java | 3 | raw_structurally_valid | 20 | 11.0 | 3.5 [3.0, 5.5] | 0.800 | 0.01182 | 31.8% |
| qwen_java | 4 | sanitized_after_structural_violation | 20 | 10.0 | 0.5 [-1.5, 5.0] | 0.575 | 0.62906 | 5.0% |
| qwen_java | 5 | sanitized_after_structural_violation | 20 | 10.0 | 2.0 [-1.0, 5.0] | 0.650 | 0.23788 | 20.0% |
| qwen_python | 1 | sanitized_after_structural_violation | 20 | 28.0 | 1.5 [-4.0, 6.0] | 0.550 | 0.82380 | 5.4% |
| qwen_python | 2 | sanitized_after_structural_violation | 20 | 23.0 | 7.0 [-2.0, 13.0] | 0.600 | 0.48068 | 30.4% |
| qwen_python | 3 | raw_structurally_valid | 20 | 27.0 | 7.5 [1.5, 12.5] | 0.725 | 0.06357 | 27.8% |
| qwen_python | 4 | sanitized_after_structural_violation | 20 | 27.0 | 6.0 [-2.0, 11.0] | 0.650 | 0.26318 | 22.2% |
| qwen_python | 5 | raw_structurally_valid | 20 | 26.0 | 0.5 [-2.0, 6.0] | 0.550 | 0.81453 | 1.9% |

Multiplicity status: final.
The historical Holm family contains all 20 candidate-versus-authored comparisons.

The five candidates per stratum come from different search seeds but share
the same tasks, baseline generations, model system, and selection procedure;
they are selected candidates, not independent repairs.
