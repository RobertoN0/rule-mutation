# Final consensus prompt→rule maps
_Per-prompt rule sets for CyberSecEval, aggregated over 20 temp=0.6 seeds per config by majority vote (K = strict majority, K=11/20). Built 2026-07-20._

## 1. Per-config consensus (one final map per model × language)

| model | lang | seeds | retrieval prompts | search prompts | r/p (per-seed) | stability | K | search-map r/p | empty | map |
|---|---|--:|--:|--:|--:|--:|--:|--:|--:|---|
| Qwen2.5-Coder-32B | python | 20 | 185 | 184 | 2.90 | 0.709 | 11 | 2.625 | 0 | `rule_maps/final_consensus_map_qwen_python.json` |
| Qwen2.5-Coder-32B | java | 20 | 113 | 113 | 2.54 | 0.738 | 11 | 2.310 | 0 | `rule_maps/final_consensus_map_qwen_java.json` |
| Llama-3.3-70B | python | 20 | 185 | 184 | 3.67 | 0.868 | 11 | 3.560 | 0 | `rule_maps/final_consensus_map_llama_python.json` |
| Llama-3.3-70B | java | 20 | 113 | 113 | 3.35 | 0.862 | 11 | 3.204 | 0 | `rule_maps/final_consensus_map_llama_java.json` |

The Python retrieval sweep contained 185 prompts. Search qualification removes
task 1301 from every Python-containing map because that prompt explicitly asks
for Bash; the runtime population is therefore 184 Python + 113 Java. Sweep
stability/per-seed values above still refer to the original retrieval population
and are preserved under `metadata.prequalification_retrieval_statistics`.

## 2. Cross-model agreement (Qwen vs Llama)

- **python** (185 retrieval prompts, prequalification): consensus agreement Jaccard **0.558**, identical on 15/185 (8%); rules/prompt Qwen 2.63 vs Llama 3.56.
    - Llama+ 0.32  `codeguard-0-framework-and-languages` (Qwen 0.58 / Llama 0.90)
    - Llama+ 0.30  `codeguard-0-input-validation-injection` (Qwen 0.62 / Llama 0.92)
    - Llama+ 0.28  `codeguard-0-safe-c-functions` (Qwen 0.03 / Llama 0.30)
    - Llama+ 0.14  `codeguard-0-supply-chain-security` (Qwen 0.03 / Llama 0.17)
    - Qwen+ 0.14  `codeguard-1-hardcoded-credentials` (Qwen 0.17 / Llama 0.04)
- **java** (113 prompts): consensus agreement Jaccard **0.527**, identical on 12/113 (11%); rules/prompt Qwen 2.31 vs Llama 3.20.
    - Llama+ 0.56  `codeguard-0-framework-and-languages` (Qwen 0.22 / Llama 0.78)
    - Llama+ 0.37  `codeguard-0-input-validation-injection` (Qwen 0.17 / Llama 0.54)
    - Qwen+ 0.15  `codeguard-1-hardcoded-credentials` (Qwen 0.15 / Llama 0.00)
    - Llama+ 0.12  `codeguard-0-data-storage` (Qwen 0.04 / Llama 0.16)
    - Qwen+ 0.11  `codeguard-0-file-handling-and-uploads` (Qwen 0.19 / Llama 0.08)
