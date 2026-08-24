# RQ4: final three-way Phase-3 baseline comparison

per (stratum, seed): qualified task ids intersected with the per-task maps of the no-rules baseline, the authored baseline, and all five candidates of the stratum. Independent of which candidate is tested, so layer 1 is one comparison per stratum and the layers decompose exactly.

Statistics: Wilcoxon signed-rank with exact permutation p-values over all 2^n sign assignments; Vargha-Delaney A12 oriented so >0.5 favours the condition with fewer findings; matched-pairs rank-biserial correlation.

## Common task set

| Stratum | qualified | three-way common (median) | extra dropped vs pairwise |
|---|---|---|---|
| llama_java | 126 | 113 (110-117) | 8 |
| llama_python | 203 | 195 (192-199) | 6 |
| qwen_java | 126 | 125 (123-126) | 1 |
| qwen_python | 203 | 201 (198-203) | 2 |

## Layer 1: authored rules vs no rules

| Stratum | median delta | % of no-rules | win rate | exact p | Holm | A12 | rank-biserial |
|---|---|---|---|---|---|---|---|
| llama_java | +2.0 | +1.8% | 0.60 | 0.1351 | no | 0.616 (small) | +0.395 |
| llama_python | +19.5 | +7.5% | 0.90 | 8.202e-05 | reject | 0.860 (large) | +0.905 |
| qwen_java | +3.0 | +2.8% | 0.70 | 0.001801 | reject | 0.765 (large) | +0.774 |
| qwen_python | +13.5 | +6.2% | 0.90 | 9.537e-06 | reject | 0.946 (large) | +0.971 |

## Layer 2: candidate vs authored rules

| Candidate | kind | median delta | % of authored | win rate | exact p | Holm | A12 |
|---|---|---|---|---|---|---|---|
| llama_java_r1_561c0c2f | raw | +1.5 | +1.4% | 0.60 | 0.1354 | no | 0.672 |
| llama_java_r2_fe7cf23a | sanitised | +1.0 | +0.9% | 0.65 | 0.2055 | no | 0.636 |
| llama_java_r3_5b524d6c | raw | -0.5 | -0.5% | 0.45 | 0.6569 | no | 0.547 |
| llama_java_r4_2309988f | sanitised | +3.0 | +2.8% | 0.70 | 0.07335 | no | 0.669 |
| llama_java_r5_43b2d360 | raw | +0.0 | +0.0% | 0.45 | 0.6777 | no | 0.496 |
| llama_python_r1_5731e673 | raw | +9.0 | +3.7% | 0.70 | 0.04536 | no | 0.680 |
| llama_python_r2_b7a0e656 | sanitised | -2.0 | -0.8% | 0.35 | 0.5719 | no | 0.456 |
| llama_python_r3_3517cec1 | raw | +7.0 | +2.9% | 0.70 | 0.1674 | no | 0.619 |
| llama_python_r4_411b2a00 | sanitised | +4.0 | +1.6% | 0.70 | 0.03857 | no | 0.734 |
| llama_python_r5_04c4685c | sanitised | +4.0 | +1.6% | 0.60 | 0.1737 | no | 0.586 |
| qwen_java_r1_b3e4754e | sanitised | +2.5 | +2.4% | 0.65 | 0.003448 | no | 0.729 |
| qwen_java_r2_2dbec79a | sanitised | +2.0 | +1.9% | 0.75 | 0.01865 | no | 0.760 |
| qwen_java_r3_d3dd6fd8 | raw | +4.0 | +3.8% | 0.80 | 0.008497 | no | 0.765 |
| qwen_java_r4_37aa0e24 | sanitised | +0.5 | +0.5% | 0.50 | 0.4092 | no | 0.634 |
| qwen_java_r5_24af1719 | sanitised | +2.0 | +1.9% | 0.60 | 0.09525 | no | 0.685 |
| qwen_python_r1_f953f53a | sanitised | +2.0 | +1.0% | 0.55 | 0.6152 | no | 0.522 |
| qwen_python_r2_2004e6c4 | sanitised | +7.0 | +3.4% | 0.55 | 0.02586 | no | 0.693 |
| qwen_python_r3_dec458ea | raw | +7.5 | +3.6% | 0.70 | 0.004368 | no | 0.749 |
| qwen_python_r4_9da15599 | sanitised | +6.0 | +2.9% | 0.65 | 0.09491 | no | 0.662 |
| qwen_python_r5_b7b79cc4 | raw | +0.5 | +0.2% | 0.50 | 0.4107 | no | 0.522 |

## Layer 3: candidate vs no rules

| Candidate | kind | median delta | % of no-rules | win rate | exact p | Holm | A12 |
|---|---|---|---|---|---|---|---|
| llama_java_r1_561c0c2f | raw | +4.0 | +3.6% | 0.65 | 0.009447 | reject | 0.747 |
| llama_java_r2_fe7cf23a | sanitised | +2.5 | +2.3% | 0.60 | 0.02751 | no | 0.739 |
| llama_java_r3_5b524d6c | raw | +2.0 | +1.8% | 0.65 | 0.1557 | no | 0.635 |
| llama_java_r4_2309988f | sanitised | +4.0 | +3.6% | 0.75 | 0.001991 | reject | 0.747 |
| llama_java_r5_43b2d360 | raw | +2.0 | +1.8% | 0.60 | 0.2454 | no | 0.579 |
| llama_python_r1_5731e673 | raw | +23.0 | +8.8% | 0.85 | 4.196e-05 | reject | 0.932 |
| llama_python_r2_b7a0e656 | sanitised | +17.0 | +6.5% | 0.85 | 0.0002766 | reject | 0.849 |
| llama_python_r3_3517cec1 | raw | +24.0 | +9.2% | 0.90 | 8.202e-05 | reject | 0.919 |
| llama_python_r4_411b2a00 | sanitised | +26.0 | +9.9% | 0.90 | 1.144e-05 | reject | 0.949 |
| llama_python_r5_04c4685c | sanitised | +21.0 | +8.0% | 0.90 | 2.098e-05 | reject | 0.918 |
| qwen_java_r1_b3e4754e | sanitised | +6.5 | +6.1% | 0.90 | 2.098e-05 | reject | 0.926 |
| qwen_java_r2_2dbec79a | sanitised | +5.0 | +4.7% | 0.95 | 3.815e-06 | reject | 0.960 |
| qwen_java_r3_d3dd6fd8 | raw | +6.5 | +6.1% | 0.95 | 5.722e-06 | reject | 0.934 |
| qwen_java_r4_37aa0e24 | sanitised | +4.0 | +3.7% | 0.80 | 0.0001526 | reject | 0.854 |
| qwen_java_r5_24af1719 | sanitised | +6.0 | +5.6% | 0.80 | 9.155e-05 | reject | 0.907 |
| qwen_python_r1_f953f53a | sanitised | +15.5 | +7.1% | 1.00 | 1.907e-06 | reject | 0.920 |
| qwen_python_r2_2004e6c4 | sanitised | +18.5 | +8.4% | 1.00 | 1.907e-06 | reject | 0.989 |
| qwen_python_r3_dec458ea | raw | +21.0 | +9.6% | 0.95 | 3.815e-06 | reject | 0.985 |
| qwen_python_r4_9da15599 | sanitised | +19.5 | +8.9% | 1.00 | 1.907e-06 | reject | 0.985 |
| qwen_python_r5_b7b79cc4 | raw | +15.0 | +6.8% | 0.95 | 3.815e-06 | reject | 0.974 |

## Decomposition check

`delta(norules->candidate) == delta(norules->authored) + delta(authored->candidate)`

PASS over 400 (stratum, seed, candidate) triples; largest residual 0.0.
