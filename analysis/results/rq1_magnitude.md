# RQ1 - to what extent can controlled rule mutations improve effectiveness?

Estimation, not null-hypothesis testing: the elitist archive makes a test
against zero degenerate. Primary values below are the best structurally
compliant candidates observed in each original run. This is a **post-hoc
sensitivity filter**, not a reconstruction of a constrained adaptive search.

## Headline - findings removed by the best compliant candidate observed

| stratum | origin findings | EA f1 median [min-max] | **EA % of origin** | random f1 median | random % of origin |
|---|---:|---:|---:|---:|---:|
| llama_java | 122 | 8 [3-13] | **6.6%** | 8 | 6.1% |
| llama_python | 253 | 19 [6-32] | **7.5%** | 17 | 6.7% |
| qwen_java | 107 | 8 [3-11] | **7.5%** | 6 | 5.6% |
| qwen_python | 216 | 23 [5-27] | **10.6%** | 12 | 5.6% |

## Estimates with percentile-bootstrap intervals

Intervals are 95% percentile-bootstrap intervals for the run-level median
(20,000 resamples). With only ten runs per stratum they are approximate.

| stratum | n | EA f1 median [95% boot CI] | EA % of origin median [95% boot CI] | EA weighted median [95% boot CI] |
|---|---:|---|---|---|
| llama_java | 10 | 8.0 [7.0, 11.0] | 6.56% [5.74, 9.02] | 23.5 [20.0, 29.0] |
| llama_python | 10 | 19.0 [12.0, 24.5] | 7.51% [4.74, 9.68] | 42.5 [30.0, 55.0] |
| qwen_java | 10 | 8.0 [5.0, 9.5] | 7.48% [4.67, 8.88] | 14.0 [9.0, 15.5] |
| qwen_python | 10 | 23.0 [12.0, 26.0] | 10.65% [5.56, 12.04] | 51.0 [22.0, 57.5] |

## Safe-zone sensitivity - reported optimum versus compliant optimum

`best changed` counts runs whose raw reported optimum was structurally invalid.
The invalid share is the fraction of completed evaluations failing the exact
frontmatter/fenced-block/inline-code preservation contract.

| stratum | EA reported % | EA compliant % | EA best changed | EA invalid share median | random best changed |
|---|---:|---:|---:|---:|---:|
| llama_java | 9.0% | 6.6% | 5/10 | 29.2% | 4/10 |
| llama_python | 9.3% | 7.5% | 5/10 | 45.6% | 6/10 |
| qwen_java | 9.3% | 7.5% | 7/10 | 70.1% | 3/10 |
| qwen_python | 11.8% | 10.6% | 4/10 | 18.2% | 2/10 |

## Severity check

`f1` counts Semgrep findings without regard to severity (ERROR=3, WARNING=1, INFO=0).
The weighted value is the score attached to the candidate selected by raw f1;
it is not a separately optimised best-weighted candidate.
If the weighted reduction is proportionally smaller than the raw reduction,
the search is preferentially removing low-severity findings.

| stratum | EA raw % of origin | EA weighted % of origin | ratio |
|---|---:|---:|---:|
| llama_java | 6.6% | 15.9% | 2.42 |
| llama_python | 7.5% | 9.2% | 1.23 |
| qwen_java | 7.5% | 12.0% | 1.60 |
| qwen_python | 10.6% | 13.7% | 1.29 |

## Per-seed detail

### llama_java

| seed | origin | EA compliant f1 | EA reported f1 | EA % | random compliant f1 | random reported f1 |
|---:|---:|---:|---:|---:|---:|---:|
| 1 | 122 | 11 | 11 | 9.0% | 10 | 11 |
| 2 | 122 | 8 | 10 | 6.6% | 6 | 6 |
| 3 | 122 | 6 | 11 | 4.9% | 7 | 8 |
| 4 | 122 | 9 | 12 | 7.4% | 7 | 7 |
| 5 | 122 | 12 | 12 | 9.8% | 8 | 8 |
| 6 | 122 | 8 | 8 | 6.6% | 8 | 8 |
| 7 | 122 | 8 | 8 | 6.6% | 5 | 7 |
| 8 | 122 | 8 | 10 | 6.6% | 8 | 8 |
| 9 | 122 | 3 | 12 | 2.5% | 6 | 7 |
| 10 | 122 | 13 | 13 | 10.7% | 9 | 9 |

### llama_python

| seed | origin | EA compliant f1 | EA reported f1 | EA % | random compliant f1 | random reported f1 |
|---:|---:|---:|---:|---:|---:|---:|
| 1 | 253 | 23 | 23 | 9.1% | 17 | 17 |
| 2 | 253 | 32 | 32 | 12.6% | 11 | 18 |
| 3 | 253 | 18 | 18 | 7.1% | 20 | 20 |
| 4 | 253 | 12 | 24 | 4.7% | 17 | 21 |
| 5 | 253 | 12 | 23 | 4.7% | 9 | 15 |
| 6 | 253 | 20 | 22 | 7.9% | 15 | 17 |
| 7 | 253 | 6 | 32 | 2.4% | 18 | 21 |
| 8 | 253 | 21 | 21 | 8.3% | 18 | 18 |
| 9 | 253 | 28 | 28 | 11.1% | 17 | 23 |
| 10 | 253 | 14 | 26 | 5.5% | 20 | 20 |

### qwen_java

| seed | origin | EA compliant f1 | EA reported f1 | EA % | random compliant f1 | random reported f1 |
|---:|---:|---:|---:|---:|---:|---:|
| 1 | 107 | 8 | 9 | 7.5% | 5 | 6 |
| 2 | 107 | 7 | 9 | 6.5% | 6 | 6 |
| 3 | 107 | 9 | 10 | 8.4% | 8 | 8 |
| 4 | 107 | 11 | 11 | 10.3% | 6 | 6 |
| 5 | 107 | 5 | 11 | 4.7% | 5 | 6 |
| 6 | 107 | 3 | 9 | 2.8% | 5 | 5 |
| 7 | 107 | 5 | 10 | 4.7% | 5 | 6 |
| 8 | 107 | 8 | 11 | 7.5% | 6 | 6 |
| 9 | 107 | 11 | 11 | 10.3% | 6 | 6 |
| 10 | 107 | 8 | 8 | 7.5% | 6 | 6 |

### qwen_python

| seed | origin | EA compliant f1 | EA reported f1 | EA % | random compliant f1 | random reported f1 |
|---:|---:|---:|---:|---:|---:|---:|
| 1 | 216 | 23 | 23 | 10.6% | 15 | 15 |
| 2 | 216 | 21 | 21 | 9.7% | 11 | 11 |
| 3 | 216 | 12 | 20 | 5.6% | 12 | 12 |
| 4 | 216 | 25 | 25 | 11.6% | 10 | 10 |
| 5 | 216 | 23 | 23 | 10.6% | 11 | 11 |
| 6 | 216 | 5 | 27 | 2.3% | 13 | 13 |
| 7 | 216 | 26 | 28 | 12.0% | 11 | 11 |
| 8 | 216 | 26 | 26 | 12.0% | 15 | 15 |
| 9 | 216 | 9 | 27 | 4.2% | 12 | 21 |
| 10 | 216 | 27 | 27 | 12.5% | 12 | 13 |
