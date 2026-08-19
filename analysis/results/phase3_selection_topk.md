# Phase 3 selection v2 - top 5 repairs from 5 distinct seeds

pool all chromosomes from every eligible EA run's final archive; rank by f1 desc, f2 desc, f3 desc, cid asc; walk the ranking and keep a chromosome only if its seed is not already represented; stop at K. At most ONE chromosome per run.

## llama_java

| rank | seed | cid | f1 | f2 | rules | order-priority genes |
|---:|---:|---|---:|---:|---:|---:|
| 1 | 10 | `561c0c2f1fe559bb` | 13 | 0.9379 | 6 | 1 |
| 2 | 9 | `fe7cf23a8e0f8bf8` | 12 | 0.9553 | 9 | 0 |
| 3 | 5 | `5b524d6c1e1cbcb2` | 12 | 0.9508 | 7 | 0 |
| 4 | 4 | `2309988fbe1ba1d8` | 12 | 0.9129 | 7 | 1 |
| 5 | 1 | `43b2d3607d7c1f6b` | 11 | 0.9370 | 9 | 2 |

## llama_python

| rank | seed | cid | f1 | f2 | rules | order-priority genes |
|---:|---:|---|---:|---:|---:|---:|
| 1 | 2 | `5731e67389807eda` | 32 | 0.9735 | 5 | 0 |
| 2 | 7 | `b7a0e6568ce947e6` | 32 | 0.9252 | 12 | 1 |
| 3 | 9 | `3517cec12bac0d78` | 28 | 0.8886 | 6 | 1 |
| 4 | 10 | `411b2a009c2a41ef` | 26 | 0.9691 | 8 | 2 |
| 5 | 4 | `04c4685c91254df7` | 24 | 0.9068 | 8 | 1 |

## qwen_java

| rank | seed | cid | f1 | f2 | rules | order-priority genes |
|---:|---:|---|---:|---:|---:|---:|
| 1 | 5 | `b3e4754e40a57478` | 11 | 0.9833 | 11 | 5 |
| 2 | 8 | `2dbec79abbbcb98c` | 11 | 0.9716 | 9 | 6 |
| 3 | 9 | `d3dd6fd8464d03ab` | 11 | 0.9599 | 14 | 4 |
| 4 | 4 | `37aa0e246f365696` | 11 | 0.9289 | 12 | 4 |
| 5 | 7 | `24af1719ec07ac4a` | 10 | 0.9966 | 8 | 5 |

## qwen_python

| rank | seed | cid | f1 | f2 | rules | order-priority genes |
|---:|---:|---|---:|---:|---:|---:|
| 1 | 7 | `f953f53a0b830443` | 28 | 0.9196 | 11 | 3 |
| 2 | 6 | `2004e6c4cf882fd0` | 27 | 0.9741 | 13 | 4 |
| 3 | 10 | `dec458eaa24be405` | 27 | 0.9619 | 11 | 1 |
| 4 | 9 | `9da1559918698f0d` | 27 | 0.9280 | 11 | 3 |
| 5 | 8 | `b7b79cc4bd6de2e5` | 26 | 0.9794 | 15 | 4 |
