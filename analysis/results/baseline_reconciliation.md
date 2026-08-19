# Baseline provenance reconciliation

Computed at 2026-08-07T16:33:45.994760+00:00 — **analysis-time derivation, not a run-time record**.
No run artifact was modified.

## Why this document exists

The temperature-0.6 screening baselines predate the provenance-manifest
contract, so they carry a `rules_map` path but no `rules_map_sha256` and no
`population_fingerprint`. Rather than assert provenance that was never
recorded, this reconciles the artifacts directly.

## Map reconciliation

| stratum | final tasks | consensus tasks | missing | rules identical (ordered) | prompt_hash identical | differing | usable |
|---|---:|---:|---:|---:|---:|---:|:--:|
| llama_java | 126 | 227 | 0 | 126 | 126 | 0 | YES |
| llama_python | 203 | 322 | 0 | 203 | 203 | 0 | YES |
| qwen_java | 126 | 227 | 0 | 126 | 126 | 0 | YES |
| qwen_python | 203 | 322 | 0 | 203 | 203 | 0 | YES |

## Map file digests (computed today)

| stratum | file | sha256 |
|---|---|---|
| llama_java | consensus_map_llama_java.json | `b6de02b4d5ff8041d8580ff9da5990c0ca6bed803e7a6a5217862a949d2f2f64` |
| llama_java | final_search_map_llama_java.json | `00720b0cf165114c53c1bacc521ea5949a7ab5c1ee2304e2e900de2a375e08e3` |
| llama_python | consensus_map_llama_python.json | `e13a37563d288cc4e1eb8307dc2ad547f6e5cbb90a3e3cc002e2959729b9ef40` |
| llama_python | final_search_map_llama_python.json | `72acf582db6bcab8dd21da131e6b75ec4efc77d5b2442dd658f206bced6b18ec` |
| qwen_java | consensus_map_qwen_java.json | `41b6270be57b4be97630cc693b3ec73bcd1dd03bc050a2c57b7a9ebc1a54374a` |
| qwen_java | final_search_map_qwen_java.json | `32978066b0d6441dba761d130324ce7bd56a4f0513a0ed2f82eff85718e7a7df` |
| qwen_python | consensus_map_qwen_python.json | `df8c9ff488ae74a90bf919f45b45733a6e220f0b40ad056af8510ebac78c5c80` |
| qwen_python | final_search_map_qwen_python.json | `7c5ef1047b4dc997c278bd99758a04f0bc778898053ec361906935a885b05916` |

## Baseline runs

| run | model | n_cases | temp | seeds | replicates | git sha | referenced map sha256 |
|---|---|---:|---:|---:|---:|---|---|
| llama_java_norules | meta-llama/Llama-3.3-70B-Instruct | 227 | 0.6 | 20 | 20 | `20cba85b61c0` | `—` |
| llama_java_norules_resume | meta-llama/Llama-3.3-70B-Instruct | 227 | 0.6 | 2 | 2 | `20cba85b61c0` | `—` |
| llama_java_withrules | meta-llama/Llama-3.3-70B-Instruct | 227 | 0.6 | 20 | 20 | `20cba85b61c0` | `—` |
| llama_java_withrules_tail | meta-llama/Llama-3.3-70B-Instruct | 227 | 0.6 | 7 | 4 | `20cba85b61c0` | `—` |
| llama_python_norules | meta-llama/Llama-3.3-70B-Instruct | 322 | 0.6 | 20 | 20 | `20cba85b61c0` | `—` |
| llama_python_norules_tail | meta-llama/Llama-3.3-70B-Instruct | 322 | 0.6 | 5 | 4 | `20cba85b61c0` | `—` |
| llama_python_withrules | meta-llama/Llama-3.3-70B-Instruct | 322 | 0.6 | 20 | 20 | `20cba85b61c0` | `—` |
| llama_python_withrules_tail | meta-llama/Llama-3.3-70B-Instruct | 322 | 0.6 | 10 | 0 | `20cba85b61c0` | `—` |
| llama_python_withrules_tailhi | meta-llama/Llama-3.3-70B-Instruct | 322 | 0.6 | 4 | 4 | `20cba85b61c0` | `—` |
| llama_python_withrules_tailmid | meta-llama/Llama-3.3-70B-Instruct | 322 | 0.6 | 4 | 4 | `20cba85b61c0` | `—` |
| qwen_java_norules | Qwen/Qwen2.5-Coder-32B-Instruct | 227 | 0.6 | 20 | 20 | `20cba85b61c0` | `—` |
| qwen_java_withrules | Qwen/Qwen2.5-Coder-32B-Instruct | 227 | 0.6 | 20 | 20 | `20cba85b61c0` | `—` |
| qwen_python_norules | Qwen/Qwen2.5-Coder-32B-Instruct | 322 | 0.6 | 20 | 20 | `20cba85b61c0` | `—` |
| qwen_python_withrules | Qwen/Qwen2.5-Coder-32B-Instruct | 322 | 0.6 | 20 | 20 | `20cba85b61c0` | `—` |

## Verdict

**Baselines may be subset to the final population and used directly.**

## Sentence for the thesis

> Baseline runs predate the provenance-manifest contract; their rule
> assignments were reconciled against the final qualified map by task-index
> and prompt-hash comparison (`baseline_reconciliation.json`), confirming
> identical rule sets for all shared tasks.
