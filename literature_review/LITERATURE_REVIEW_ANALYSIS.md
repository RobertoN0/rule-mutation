# Literature Review Analysis
*All 16 papers — covers summary, thesis relevance, and implementation status per paper*
*Updated 2026-03-30*

---

## Structure per paper
- **Summary** — what the paper does and its key findings
- **Thesis Relevance** — how it connects to the CodeGuard SBST project
- **Implementation Status** — what is in the codebase and what is a possible future implementation

---

## Paper 1 — Metamorphic Testing of Large Language Models for Natural Language Processing
**File:** `2511.02108v1.pdf`

### Summary
The foundational taxonomy paper for the entire field. It catalogs **191 Metamorphic Relations (MRs)** for NLP tasks including QA, summarization, translation, sentiment analysis, and NER. A Metamorphic Relation is formally defined as an input transformation paired with an expected output relation (almost always equivalence for NLP). The 191 MRs are organized by transformation level: character, word, sentence, structural, and pragmatic. The paper's second contribution is an honest treatment of the **secondary oracle problem**: verifying that a mutation preserved semantic intent requires another oracle (SBERT similarity is used as a proxy), and this proxy produces significant false positives in free-form natural language.

### Thesis Relevance
Provides the theoretical vocabulary and taxonomy the entire mutation pipeline is built on. All nine implemented mutators descend from this catalog directly or via Paper 2. The critique of semantic equivalence validation directly motivates the `MutationQualityValidator` — the false-positive problem is real and the SBERT gate addresses it at the cost of potentially missing valid mutations.

The critical **extension point for the thesis**: the catalog covers NLP task testing (LLM as the system under test). The thesis elevates this to *instruction-level* testing — mutating the security rules that *guide* the LLM. This is a novel application of the MT paradigm not explored in this paper.

### Implementation Status

| Component | Status | Notes |
|---|---|---|
| 191-MR taxonomy as conceptual source | Implemented (via Paper 2 subset) | 5 of 36 LLMORPH MRs implemented |
| SBERT semantic similarity validation | ✅ Implemented | `quality.py`, threshold ≥ 0.80 |
| Character-level MRs (typo, case, leet) | ❌ Not implemented | Not applicable — security rules need precise technical vocabulary |
| Pragmatic MRs (tone, politeness) | ❌ Not implemented | Low priority for code-security domain |

---

## Paper 2 — LLMORPH: Automated Metamorphic Testing of Large Language Models
**File:** `cho-ase-2025.pdf`
**Authors:** Cho et al., ASE 2025

### Summary
The practical implementation companion to Paper 1. LLMORPH implements **36 of the 191 MRs** as runnable test operators, using two strategies: (1) deterministic programmatic functions for simple transformations, and (2) LLM-based few-shot prompting for complex ones (paraphrase, voice change, formality). Applied to real LLM-based NLP services, these 36 MRs expose faults in 15–30% of tested systems that standard regression tests miss.

Key MRs implemented in the thesis codebase:
- **MR-19 / MR-107**: Section/paragraph reordering (shuffle)
- **MR-48 / MR-76**: Negation injection (inserts contradictory qualifiers before imperatives)
- **MR-51**: Semantic paraphrase
- **Voice change**: Active-to-passive transformation

The paper also documents the **recency bias** of autoregressive LLMs: later content in the context window receives disproportionately higher attention weights. This motivates the `degrade` mode of `SectionReorderMutator`, which moves security-critical content to the end of the rule document.

### Thesis Relevance
Direct source for four of the nine implemented mutators. The LLM-based few-shot prompting strategy is exactly how `NegationInjectionMutator`, `VoiceChangeMutator`, and `ParaphraseMutator` are implemented. The recency bias insight provides theoretical grounding for the `degrade` mutation as a principled adversarial attack on LLM attention rather than a random shuffle.

This paper should be cited in the thesis methodology chapter for each of the four MR-attributed mutators, with their specific MR identifiers (MR-19, MR-48, MR-51, etc.).

### Implementation Status

| MR | Mutator | Status |
|---|---|---|
| MR-19 / MR-107 — section reorder | `SectionReorderMutator(mode="shuffle")` | ✅ Implemented |
| MR-19 / MR-107 + recency bias | `SectionReorderMutator(mode="degrade")` | ✅ Implemented |
| MR-48 / MR-76 — negation injection | `NegationInjectionMutator` | ✅ Implemented |
| MR-51 — semantic paraphrase | `ParaphraseMutator` | ✅ Implemented |
| Voice change | `VoiceChangeMutator` | ✅ Implemented |
| 31 remaining LLMORPH MRs | — | ❌ Not implemented (see Unimplemented MRs section) |

---

## Paper 3 — Search-Based Selection of Metamorphic Relations for Optimized Robustness Testing
**File:** `2507.05565v1.pdf`
**Authors:** Hyun et al., 2025

### Summary
Frames MR selection and composition as a **multi-objective combinatorial optimization problem**: given a large set of MRs, which ones maximize failure detection per token spent? Four SBST algorithms are compared: Single-GA, NSGA-II, SPEA2, and MOEA/D. Each individual is a binary vector over the MR space (which MRs to include) combined with a chaining order (which MRs to apply in sequence to a single input).

**Objectives**: Maximize `Context_ASR × PerturbationQuality` (effectiveness × semantic preservation) while minimizing `C_token` (total API token cost).

**Key findings**:
- **MOEA/D** produces the best Pareto front — it outperforms all other algorithms by decomposing the multi-objective problem into weighted single-objective sub-problems
- **Silver bullets** — MRs that individually deliver the best failure-rate-to-cost ratio — are `SynonymReplacement()` and `AddRandomWord()`
- **Combinatorial chaining matters**: applying 2–3 MRs in sequence achieves higher failure rates than any single MR, because the model encounters compounded perturbations that are individually within its tolerance but collectively break it
- A random MR subset achieves ~60% of the optimized MOEA/D effectiveness, confirming selection matters but even random subsets are not useless

**Current thesis gap**: The thesis implements single-objective hill climbing with one mutator applied per iteration. Paper 3 shows that MR chaining (applying multiple mutators per iteration) is a key source of incremental gain.

### Thesis Relevance
**HIGH — the two highest-priority extensions come from this paper**:
1. **Combinatorial MR chaining**: applying 2–3 mutators in sequence per hill-climbing step (e.g., `SynonymReplacement` then `SectionReorder` on the same rule) to compound perturbations
2. **Fitness function composition**: `Context_ASR × PerturbationQuality` as a joint metric replacing or augmenting the current `SEVERITY_WEIGHTED` Semgrep score

The silver bullet results also validate the current mutator selection: `SynonymReplacementMutator` and `AddRandomWordMutator` are already implemented. The MOEA/D architecture is aspirational future work; combinatorial chaining is the actionable near-term extension.

### Implementation Status

| Component | Status | Notes |
|---|---|---|
| SBST hill-climbing loop | ✅ Implemented (simplified) | Single-objective, one mutator per step |
| `SynonymReplacement` silver bullet | ✅ Implemented | `rule_based.py` |
| `AddRandomWord` silver bullet | ✅ Implemented | `rule_based.py` |
| Combinatorial MR chaining | ❌ **Priority extension** | Apply N mutators per iteration |
| Multi-objective GA (MOEA/D) | ❌ Future work | Hill climbing is sufficient for thesis |
| `Context_ASR × PerturbationQuality` fitness | ❌ **Priority extension** | See Paper 9 for EFM metric design |

---

## Paper 4 — Say It Another Way: Auditing LLMs with a User-Grounded Automated Paraphrasing Framework (AUGMENT)
**File:** `2505.03563v3.pdf`

### Summary
AUGMENT replaces unconstrained paraphrasing with **structured, user-grounded linguistic mutations** derived from empirical analysis of how users actually rephrase requests. Five mutation types: Prepositions, Synonyms, Voice Change, Formal Style, and AAE Dialect. The central contribution is a **three-criteria quality filter** that gates every mutation:
1. **Instruction Adherence**: POS tagging verifies the target grammatical structure was actually modified
2. **Semantic Similarity**: SBERTScore ≥ 0.75
3. **Realism**: perplexity ratio ≤ threshold (via GPT-Neo 2.7B), ensuring the mutated text reads as natural language

All three criteria act as a hard gate — any failing mutation is rejected and regenerated. The quality filter reduces false positives by ~40% compared to unfiltered paraphrase, meaning fewer mutations that pass SBERT but are still semantically broken.

### Thesis Relevance
**CRITICAL — the `MutationQualityValidator` is a direct implementation of this framework**, extended with a security-domain preservation criterion (keyword retention ≥ 0.70). The thesis should cite AUGMENT as the primary source for the three-criteria validation architecture.

The important **departure**: AUGMENT tests whether LLMs treat users differently based on *how they speak*. The thesis uses the same quality framework to test whether LLMs follow *security instructions* differently based on how those instructions are phrased. The mutation target shifts from user prompts to system-level guidelines.

The thesis's SBERT threshold (≥ 0.80) is slightly stricter than AUGMENT's (≥ 0.75) to account for the higher precision required for security rule evaluation.

### Implementation Status

| Component | Status | Notes |
|---|---|---|
| SBERT semantic similarity gate | ✅ Implemented | ≥ 0.80 (stricter than paper) |
| Instruction adherence check | ✅ Implemented | Per-mutator adherence logic in `quality.py` |
| Perplexity ratio criterion | ✅ Implemented but disabled by default | Informational only |
| Security keyword retention gate | ✅ Implemented (thesis extension) | ≥ 0.70, not in original AUGMENT |
| Voice Change mutation | ✅ Implemented | `VoiceChangeMutator` |
| Synonym mutation | ✅ Implemented | `SynonymReplacementMutator` |
| Formal Style mutation | ❌ Possible future addition | Changes register to formal/academic prose |
| AAE Dialect mutation | ❌ Not applicable | Not relevant for code security rules |
| Preposition-level mutation | ❌ Not applicable | Too fine-grained for security rules |

---

## Paper 5 — Do LLMs "Know" Internally When They Follow Instructions?
**File:** `2410.14516v5.pdf`
**Authors:** Heo et al., ICLR 2025

### Summary
Uses linear probing on LLM hidden states to identify a specific direction in the input embedding space — the **instruction-following dimension** — that predicts whether the model will successfully follow an instruction *before any output is generated*. The probe achieves > 85% accuracy at the first generated token position.

Sensitivity analysis (SHAP values) reveals that this internal dimension is most strongly influenced by **prompt phrasing choices** (specific words, sentence structure), not by task difficulty or instruction specificity. Representation Engineering — manually shifting the embedding along this dimension at inference time — improves instruction-following success rates by up to 23% without any prompt change.

### Thesis Relevance
Provides the **deepest mechanistic justification for why prompt mutation works**. It proves that:
- Security instruction adherence is determined at the embedding level before generation begins
- Phrasing is the dominant attack surface — meaning syntax-preserving semantic rewrites are principled attacks, not noise
- The sensitivity is architectural (universal across models), not task-specific

This paper should appear in the thesis introduction/motivation section as mechanistic evidence that instruction brittleness is a fundamental LLM property.

**Future experiment**: Use Heo et al.'s instruction-following dimension as a proxy fitness signal — rank candidate mutations by how far they shift the rule embedding from the "high compliance" region. This could predict which mutations will be most effective without running Semgrep, dramatically reducing evaluation cost per hill-climbing step.

### Implementation Status

| Component | Status | Notes |
|---|---|---|
| Theoretical justification for phrasing sensitivity | Used in thesis framing | — |
| SBERT similarity as embedding-distance proxy | ✅ Implemented (indirect) | Different embedding space than paper |
| Instruction-following dimension as fitness proxy | ❌ Future experiment | Requires per-token probing |
| Representation Engineering for rule improvement | ❌ Out of scope | Thesis tests brittleness, not repair |

---

## Paper 6 — Latent Adversarial Paraphrasing (LAP)
**File:** `2025.emnlp-main.1595.pdf`
**Authors:** EMNLP 2025

### Summary
LAP searches for adversarial prompt variations in the **continuous latent embedding space** rather than the discrete token space. A dual-loop framework: the inner loop maximizes L2 distance between original and perturbed embeddings (finding the "hardest paraphrase"), while the outer loop fine-tunes a paraphrase adapter under a Lagrangian perplexity constraint that ensures natural language output.

Key empirical result: L2 distance in embedding space is **predictive of worst-case failure** (Spearman r = 0.36, p < 0.05). The perplexity constraint empirically implies SBERT ≥ 0.80 in > 90% of cases, providing calibration for the quality threshold choice.

### Thesis Relevance
Provides **theoretical grounding for the SBERT gate as a robustness predictor** rather than just a quality filter. The calibration result (perplexity ratio ≤ 2.0 → SBERT ≥ 0.80) validates why the perplexity criterion is implemented as informational — it is consistent with the SBERT gate already in place.

The thesis currently generates paraphrases at temperature 0.6 and selects the first candidate that passes the quality gate. LAP suggests a stronger strategy: among all candidates that pass the gate, prefer the one with the *largest* embedding distance from the original (most adversarial paraphrase). This is a near-term improvement to `ParaphraseMutator` that does not require gradient access.

### Implementation Status

| Component | Status | Notes |
|---|---|---|
| Perplexity ratio criterion | ✅ Implemented (informational) | `quality.py` |
| SBERT gate calibrated by LAP's empirical bound | ✅ Used (indirect) | 0.80 threshold consistent with LAP findings |
| Adversarial candidate selection (max L2 from valid candidates) | ❌ Possible improvement | Currently takes first passing candidate |
| Full LAP dual-loop optimization | ❌ Not implementable | Requires gradient access to hidden states |

---

## Paper 7 — Mixture of Formats (MOF)
**File:** `2504.06969v1.pdf`

### Summary
LLMs show 10–20% accuracy variance when the *formatting style* of few-shot examples changes, even when content is identical. MOF mitigates this by deliberately **diversifying formatting styles across examples within the same prompt** — using JSON for one example, YAML for another, Markdown for a third. This forces the model to learn task-invariant representations rather than format-specific shortcuts. Results: up to 46% reduction in "spread" (max–min accuracy across formats), improving both minimum and maximum accuracy.

Mutations are purely non-semantic: punctuation choice, capitalization, delimiter style, whitespace density, serialization format (JSON vs. YAML vs. Markdown table).

### Thesis Relevance
Introduces a **complementary mutation axis not yet exploited**: structural/formatting mutations of the rule document. CodeGuard rules are Markdown files with headers, bullet lists, bold emphasis, and code fences. Non-semantic format variants (different bullet styles, header depths, emphasis choices) could reveal whether the LLM parses security rules semantically or pattern-matches on structure.

This is a lower priority than combinatorial chaining and fitness expansion, but is a natural addition once the existing mutators are validated. The `ParsedRule` safe-zone contract already protects code fences and YAML frontmatter, so formatting mutations would target prose-section Markdown only.

### Implementation Status

| Component | Status | Notes |
|---|---|---|
| Structural format mutations (bullet style, header depth, emphasis) | ❌ Possible future addition | `FormatStyleMutator` concept |
| Non-semantic Markdown variation | ❌ Possible future addition | Low priority while existing MRs are unvalidated |

---

## Paper 8 — Validating LLM-Generated Programs with Metamorphic Prompt Testing
**File:** `2406.06864v1.pdf`

### Summary
Applies MT to **LLM-generated code validation** without ground-truth test oracles. The metamorphic property: paraphrased prompts should produce functionally equivalent programs. Implementation: coverage-guided fuzzing generates diverse prompt paraphrases → N code variants generated → **majority-consensus cross-validation** (> 50% agreement on outputs = oracle; disagreeing variants flagged as potentially faulty). Results: 75% recall on HumanEval bugs, 8.6% false positive rate.

### Thesis Relevance
Structurally analogous to the thesis but applied at the code-generation output level rather than the security-rule input level. The majority-consensus oracle is the code-generation equivalent of "same security outcome under paraphrase" — which is exactly the MetaMorphic Relation the thesis exploits.

**Potential application**: Generate 3–5 code variants from slightly different phrasings of the same mutated rule and use consensus Semgrep findings to reduce fitness measurement variance. However, this increases LLM call volume significantly, which conflicts with the current throughput bottleneck (this is explicitly lower priority per the user's direction).

### Implementation Status

| Component | Status | Notes |
|---|---|---|
| MT assumption (consistent behavior under paraphrase) | ✅ Core thesis assumption | — |
| Coverage-guided fuzzing for prompt variants | ❌ Not implemented | Not needed for current pipeline |
| Consensus-based Semgrep validation | ❌ Low priority | Conflicts with single-generation design choice |

---

## Paper 9 — METAL: Metamorphic Testing Framework for Analyzing Large-Language Model Qualities
**File:** `2312.06056v1.pdf`
**Authors:** Hyun et al. (predecessor to Paper 3), 2023

### Summary
Predecessor framework to Paper 3 from the same research group. Establishes the empirical foundation for SBST-based MR evaluation. Core components:
- **5 MR Templates** covering Robustness, Fairness, Non-determinism, Efficiency, Correctness
- **13 perturbations** at character, word, and sentence level
- **EFM (Effectiveness Metric)**: `EFM = M-ASR × PerturbationQuality` — rewards mutations that both expose failures AND preserve semantic intent
- **STS-based automatic validation**: SBERT similarity for intent preservation checking

Key empirical finding: sentence-level perturbations consistently outperform character/word-level for code-generating LLMs, because code generation requires semantic understanding at a higher abstraction level.

### Thesis Relevance
**HIGH — provides the EFM metric that is the second highest-priority extension**: replacing or augmenting the current `SEVERITY_WEIGHTED` Semgrep score with `EFM = Semgrep_increase × SBERT_similarity`. This composite metric rewards mutations that efficiently break model behavior *relative to the semantic drift introduced*. A mutation that produces a 3-finding Semgrep increase with SBERT = 0.95 is objectively better than one producing the same increase with SBERT = 0.81.

The METAL finding that sentence-level perturbations outperform character/word-level directly validates the thesis's current design (6 sentence-level mutators, only 1 word-level, 0 character-level).

### Implementation Status

| Component | Status | Notes |
|---|---|---|
| Synonym substitution | ✅ `SynonymReplacementMutator` | |
| Word insertion | ✅ `AddRandomWordMutator` | |
| Section shuffle | ✅ `SectionReorderMutator` | |
| Paraphrase | ✅ `ParaphraseMutator` | |
| Negation | ✅ `NegationInjectionMutator` | |
| SBERT validation | ✅ `MutationQualityValidator` | |
| EFM metric (`Semgrep_increase × SBERT_similarity`) | ❌ **Priority extension** | Complement to SEVERITY_WEIGHTED fitness |
| Typo injection, case change (char-level) | ❌ Not applicable | Inappropriate for security rules |
| Word deletion | ❌ Not implemented | Possible: remove redundant filler words only |

---

## Paper 10 — Does Tone Change the Answer? Evaluating Prompt Politeness Effects on Modern LLMs
**File:** `2512.12812v1.pdf`

### Summary
Tests five tone conditions (Very Friendly → Very Rude) as prefix/suffix injections across STEM, Humanities, and Mixed domains on GPT-4o, LLaMA-3, and Gemini Ultra. Key findings: STEM tasks are tone-robust; Humanities tasks (Philosophy, Professional Law) show 8–15% accuracy difference between Very Friendly and Very Rude. Gemini shows no significant tone sensitivity. Aggregating across domains hides domain-specific effects.

### Thesis Relevance
**LOW for mutation design** (tone prefixes are not applicable to code security rules), but **important for evaluation methodology**: the aggregation-masks-effects finding means the thesis must report results per CWE category and per programming language, not just aggregate Semgrep finding counts. A mutator that dramatically increases findings in C (buffer overflow rules) but has no effect on Python (injection rules) would be invisible in aggregate numbers.

Also indirectly validates `FluffMutator`: injecting bureaucratic/corporate register into rules is a pragmatic tone shift that may exploit similar sensitivity as the formality effects documented here.

### Implementation Status

| Component | Status | Notes |
|---|---|---|
| Register shift via `FluffMutator` | ✅ Implemented (indirect) | Adjacent to tone/formality effects |
| Tone prefix injection | ❌ Not applicable | Rules are not user prompts |
| Per-CWE evaluation reporting | ❌ Should be added to evaluation | Prevents aggregation masking |

---

## Paper 11 — STELLAR: A Search-Based Testing Framework for Large Language Model Applications
**File:** `2601.00497v2.pdf`

### Summary
Applies SBST to LLM application testing via **feature discretization**: decomposes prompts into three finite, parameterized dimensions — content features (task domain, entity type), stylistic features (formality, sentence length, vocabulary complexity), and perturbation features (typo density, synonym rate). A test case is a point in this discrete space. NSGA-II multi-objective search finds failure-inducing combinations. Results: 4.3× more failures than random sampling. Semantic preservation is guaranteed by construction (content features are held fixed, only style/perturbation features vary).

### Thesis Relevance
**Architecturally aspirational.** STELLAR's feature discretization directly addresses the problem of defining a structured mutation space over CodeGuard rules. The nine current mutators implicitly define a discrete operator space (which the hill climber samples), but STELLAR formalizes this as a product space with searchable dimensions. A full STELLAR implementation for this thesis would define:
- Content features: CWE addressed, number of code examples, MUST/NEVER keyword count
- Stylistic features: prose formality, sentence complexity, bullet vs. prose
- Perturbation features: mutator type, intensity (single vs. chained)

This is future work, but the 4.3× improvement over random testing motivates eventually moving from hill climbing to structured multi-objective search.

### Implementation Status

| Component | Status | Notes |
|---|---|---|
| NSGA-II multi-objective search | ❌ Future work | Hill climbing is current approach |
| Feature discretization of rule space | ❌ Future work | Aspiring architectural change |
| Discrete operator selection (9 mutators) | ✅ Implicit | `create_research_battery()` |

---

## Paper 12 — Validating LLM-Generated SQL Queries through Metamorphic Prompting (MRSQLGen)
**File:** `FSE26-MRSQLGen.pdf`
**Authors:** Lin et al., FSE 2026

### Summary
Detects **intent-violating hallucinations** in NL-to-SQL systems using a two-module architecture. The Prompt Paraphrasing Module generates metamorphic variants using a **Hallucination Knowledge Base (HKB)** — a structured taxonomy of NL2SQL failure modes mapped to specific prompt transformations. The Cross Validation Module executes all variants against the database and checks output relations (subset ⊆, superset ⊇, equivalence =). A hallucination is flagged when the majority of metamorphic variants violate their expected output relation. The four HKB mutation strategies are: Intent Perturbation, Logical Decomposition, Constraint Explicitization, and Error-Type Reflection.

### Thesis Relevance
**MODERATE — HKB concept is valuable.** The Hallucination Knowledge Base — a taxonomy of *known failure modes mapped to targeted mutations* — is a more principled approach than generic MR selection. For the thesis, a Security Rule Brittleness Knowledge Base (SRBKB) could map known vulnerability types to the mutations most likely to expose them:
- Injection vulnerabilities → `VerbWeakeningMutator` (weakens MUST to should)
- Buffer overflow vulnerabilities → `SectionReorderMutator(mode="degrade")` (moves bounds-checking guidance to end)
- Authentication vulnerabilities → `NegationInjectionMutator` (inserts contradictory constraints)

This is lower priority than combinatorial chaining and EFM, but represents a natural evolution once the existing MRs are validated.

### Implementation Status

| Component | Status | Notes |
|---|---|---|
| Instability-as-hallucination assumption | ✅ Core thesis assumption | — |
| Generic MR selection | ✅ 9 mutators in battery | Not failure-mode-targeted |
| HKB / SRBKB taxonomy | ❌ Possible future work | Maps CWE to best mutator |
| Output relation checking (subset/superset) | ❌ Not applicable | Semgrep is the oracle, not SQL execution |

---

## Paper 13 — Persistent Instability in LLM's Personality Measurements (PERSIST)
**File:** `2508.04826v3.pdf`
**Authors:** Tosato et al., AAAI 2026

### Summary
The most comprehensive empirical study of LLM behavioral instability, testing 25 models (1B–685B) across 2M+ measurements on five axes: question order shuffling, persona instructions, CoT reasoning mode, semantic paraphrasing, and conversation history. Key findings: scaling reduces but does not eliminate instability (even 400B+ models have SD > 0.3); CoT *amplifies* variability by generating different justifications across runs; paraphrasing increases variability for large models (>50B); conversation history exacerbates instability for small models.

### Thesis Relevance
**LOW priority for implementation.** The finding that paraphrasing increases response variability for large models is relevant context for interpreting `ParaphraseMutator` results. The CoT finding (reasoning amplifies variability) is interesting context. However, the thesis design explicitly uses `temperature=0` for code generation to minimize stochastic noise, and multi-run variance measurement is not in scope — single-generation evaluation is the chosen design.

The main citation use: PERSIST provides external evidence that prompt variation causes measurable behavioral shifts across scales and architectures, supporting the thesis's core assumption that mutation-induced phrasing changes produce systematic (not random) security differences.

### Implementation Status

| Component | Status | Notes |
|---|---|---|
| `temperature=0` for deterministic generation | ✅ Implemented | Addresses instability concern |
| Multi-run variance measurement | ❌ Not in scope | Explicitly excluded by design |
| CoT toggling as mutation axis | ❌ Not applicable | Rules are static system prompts |

---

## Paper 14 — Cybersecurity AI Benchmark (CAIBench)
**File:** `2510.24317v1.pdf`

### Summary
A meta-benchmark integrating five cybersecurity evaluation categories: Jeopardy CTFs, Attack and Defense CTFs, Cyber Range exercises, Cybersecurity Knowledge questions, and Privacy Assessment. Evaluated across frontier models. Key finding: models achieve ~70% on static knowledge questions but fall to 20–40% on multi-step adversarial scenarios and 22% on cyber-physical targets — a "capability gap" between theoretical understanding and operational execution.

### Thesis Relevance
**Contextual motivation.** CAIBench provides external evidence that frontier models know security concepts but fail to apply them operationally. This directly motivates the thesis: the CodeGuard rules encode security knowledge that the model "understands" in isolation, but small rule perturbations can break the operational application of that knowledge during code generation. It supports the introduction chapter's argument that instruction robustness is a real and measurable problem.

Also: the multi-domain evaluation approach (5 distinct categories) reinforces the need for per-CWE result reporting in the thesis (see Paper 10's aggregation-masking finding).

### Implementation Status
Not applicable — CAIBench is a benchmark. The CyberSecEval prompts used in the thesis are conceptually similar (real security test cases across multiple CWEs and languages).

---

## Paper 15 — Prompt Repetition Improves Non-Reasoning LLMs
**File:** `2512.14982v1.pdf`
**Authors:** Leviathan, Kalman, Matias (Google Research), Dec 2025

### Summary
Repeating the input prompt twice (`QUERY → QUERY + QUERY`) wins 47 of 70 benchmark-model combinations with 0 losses, at no latency or output length cost. The mechanism: causal attention means later tokens cannot attend to earlier tokens in the same prompt pass; the second copy allows all tokens to attend to the full first copy. Effective for non-reasoning models; neutral for reasoning models.

### Thesis Relevance
**LOW — not a mutation, but a useful baseline insight.** Prompt repetition is not a mutation the thesis would apply to rules (the thesis explores *degradation* of rules, not strengthening). However, it offers an interesting **control experiment**: does repeating a mutated rule recover the original security performance? If `mutated_rule + mutated_rule` achieves the same Semgrep score as `original_rule`, the mutation's effect is a "shorter context" artifact rather than a genuine phrasing brittleness. This experiment would strengthen validity claims but is not in scope for the main pipeline.

### Implementation Status

| Component | Status | Notes |
|---|---|---|
| Rule repetition as baseline condition | ❌ Not in scope | Potential validity control experiment |

---

## Paper 16 — Detecting and Reducing the Factual Hallucinations of LLMs with Metamorphic Testing (DrHall)
**File:** `3715784.pdf`
**Authors:** Wu et al., FSE 2025

### Summary
DrHall detects and corrects factual hallucinations in black-box LLMs using 6 base MRs + 3 composite MRs, split into two types: QMRs (Questioning MRs — transform the original question) and AMRs (Answering MRs — probe the original answer). Examples: QMR1 adds step-by-step CoT elicitation, QMR2 translates to another language, AMR1 asks "Is [original answer] correct?", AMR2 presents multiple-choice candidates. Consistency between original and follow-up answers is assessed; majority disagreement = hallucination. Correction = majority-vote follow-up answer. F1 > 0.856 for detection, > 53% correction rate.

### Thesis Relevance
**OUT OF SCOPE for implementation.** DrHall's QMR/AMR framework requires transforming the user-facing *question prompt*, not the system-level instruction. The thesis explicitly does not mutate prompts. However, DrHall's instability-of-wrong-answers assumption is exactly the thesis's behavioral mutation hypothesis: insecure code generation arises from brittle instruction adherence, and that brittleness is revealed by phrasing changes.

The DrHall taxonomy suggests a useful conceptual distinction: the thesis currently implements only **Rule MRs (RMRs)** — transformations of the security rule text. DrHall demonstrates that **Answering MRs** (probing the generated output) can also reveal brittleness. For code generation, this might mean verifying whether the generated code *itself* is consistent across rule variants — which is closer to Paper 8's consensus approach. All of this is explicitly out of scope per the thesis design.

### Implementation Status

| Component | Status | Notes |
|---|---|---|
| Rule-level MRs (RMRs) | ✅ All 9 mutators | — |
| Prompt-level mutations (QMRs/AMRs) | ❌ Out of scope | Prompts are not changed |
| Multi-path voting correction | ❌ Not applicable | Thesis maximizes failures, not corrects them |

---

---

# Unimplemented MRs Reference

The following MRs appear in the literature and have **not been implemented** in the current codebase. They are organized by applicability to the CodeGuard security rule domain.

## Group A — Possibly Applicable (Rule-Level Mutations)

These MRs operate at the prose level and could be applied to security rule text without violating the safe-zone contract.

| MR | Source Paper | Description | Notes |
|---|---|---|---|
| **Formal Style Shift** | Paper 4 (AUGMENT) | Changes register from technical/imperative to formal/academic prose ("Do not use X" → "It is inadvisable to employ X") | Distinct from `VoiceChangeMutator`; changes register, not syntax |
| **Word Deletion** | Paper 9 (METAL) | Removes semantically redundant words or phrases | Must avoid removing security-critical keywords; safe only on filler prose |
| **Sentence Compression** | Papers 1, 2 | Condenses multi-clause sentences into shorter equivalents | Risk of losing critical constraint detail |
| **Context Addition** | Papers 1, 2 | Inserts plausible but irrelevant context sentences before or after the instruction | Longer rule, potentially diluted focus |
| **Sentence Elaboration / Hedging** | Paper 2 (LLMORPH) | Adds qualifying phrases ("In most cases", "Generally speaking") before imperative statements | Related to `FluffMutator`; more targeted |
| **Structural Format Variation** | Paper 7 (MOF) | Changes Markdown formatting: bullet style (`-` vs `*`), emphasis (`**` vs `_`), header depth (`##` vs `###`) | Non-semantic; pure presentation change |
| **List → Prose / Prose → List** | Paper 1 | Converts bullet-point instructions to continuous paragraphs or vice versa | Changes scanability; LLMs may weight these differently |

## Group B — Not Applicable to This Domain

These MRs are documented in the literature but are not appropriate for security rule mutation.

| MR | Source Paper | Why Not Applicable |
|---|---|---|
| **Character-level typo injection** | Papers 1, 2, 9 | Security rules require precise technical vocabulary; typos would corrupt CWE names, API names, etc. |
| **Leet-speak substitution (L33T)** | Papers 1, 2, 3 | Same reason; character corruption renders technical content meaningless |
| **Case mutation** | Papers 1, 9 | YAML frontmatter and code block identifiers are case-sensitive; risk of violating safe-zone contract |
| **Multilingual translation** | Paper 16 (DrHall QMR2) | Rules must remain in English; the code-generating LLM expects English system prompts |
| **AAE Dialect** | Paper 4 (AUGMENT) | Not relevant to security instruction domain |
| **Tone/politeness prefix** | Paper 10 | Rules are authoritative instructions, not user messages; tone prefix injection would break the instruction framing |
| **Antonym injection at word level** | Papers 1, 2 | Equivalent to `NegationInjectionMutator` at a finer granularity; already covered at sentence level |
| **Persona injection / CoT toggling** | Paper 13 (PERSIST) | These are prompt-level mutations; out of scope per thesis design |

## Group C — Possible DrHall-Inspired Extensions (Out of Scope)

These are prompt-level or output-level MRs from DrHall (Paper 16) that are explicitly excluded from the thesis but documented for completeness.

| MR | Type | Description |
|---|---|---|
| QMR1 — CoT Elicitation | Prompt-level | "Please think step by step" appended to user prompt |
| QMR2 — Multilingual | Prompt-level | Translate user prompt to another language |
| QMR3 — Question Rephrasing | Prompt-level | Change question syntax ("What is X?" → "Which X is known as Y?") |
| AMR1 — Negation Check | Output-level | "Is [original answer] correct?" |
| AMR2 — Multiple Choice | Output-level | Present original + distractors, ask model to select |

---

---

# Gap Analysis and Priorities

## Priority 1 (HIGH) — Combinatorial MR Chaining
**Source**: Paper 3 (Hyun et al. SBST)

Apply 2–3 mutators in sequence per hill-climbing step rather than a single mutator. Paper 3 shows chaining is a primary source of incremental failure gain: individual MRs within tolerance can collectively break the model. Implementation: modify `optimize_per_prompt_rules()` in `hill_climber.py` to optionally sample a chain of N mutators and apply them in sequence before evaluating fitness. Start with 2-chains of confirmed effective mutators.

## Priority 2 (HIGH) — Composite Fitness Function (EFM)
**Source**: Paper 9 (METAL), Paper 3 (Hyun et al.)

Augment the current `SEVERITY_WEIGHTED` Semgrep score with a quality-weighted composite:
```
EFM = Semgrep_increase × SBERT_similarity
```
This rewards mutations that efficiently break model behavior relative to semantic drift introduced. A mutation that produces a 3-finding increase with SBERT = 0.95 is strictly better than one with the same increase at SBERT = 0.81. Concretely: after each hill-climbing step, compute and log both the raw Semgrep delta and the EFM, so per-mutator effectiveness can be analyzed.

Paper 3's `Context_ASR × PerturbationQuality` formalizes the same idea at the aggregate level. Implement EFM per step; compute Context_ASR at the end as a summary metric.

## Priority 3 (MEDIUM — study existing MRs first) — Additional Rule-Level MRs
**Sources**: Papers 4, 7, 9

Once the existing 9 mutators are validated, extend with:
1. **Formal Style Shift** (Paper 4 — AUGMENT): changes imperative register to formal/advisory prose
2. **Structural Format Variation** (Paper 7 — MOF): Markdown formatting changes (bullet style, emphasis, header depth)
3. **Contextual Elaboration / Hedging** (Paper 2 — LLMORPH): inserts qualifying phrases before imperatives

These are lower priority because the core MRs need to be characterized first.

## Out of Scope (by design)
- Multi-run variance measurement (Paper 13) — single-generation per evaluation is the explicit design choice
- Prompt-level mutations (Paper 16, Papers 8/12 in their consensus variants) — prompts are not mutated
- Multi-objective GA / MOEA/D (Paper 3) — hill climbing is sufficient for thesis scale
- Character-level mutations (Papers 1, 2, 9) — incompatible with security rule domain

---
---

# Papers 17–25 (from Gemini deep-research pass, added 2026-04-02)

---

## Paper 17 — Survival of the Safest: Towards Secure Prompt Optimization through Interleaved Multi-Objective Evolution (SoS)
**ArXiv:** `2410.09652`
**Authors:** Sinha, Cui, Das, Zhang — EMNLP 2024 Industry Track

### Summary
Addresses the fundamental tension in prompt optimization: maximizing task performance (KPI) while maintaining safety/security. SoS uses an **interleaved multi-objective evolution strategy** that alternates between optimizing security and performance objectives, rather than the standard single-objective approach or naive Pareto-front methods.

Three mutation operators:
1. **Semantic mutation (Mσ)**: controlled lexical paraphrasing that preserves intent
2. **Feedback mutation**: specialized agents (one per objective) analyze failures and generate improvement suggestions — domain knowledge injection into the search
3. **Crossover (Mc)**: blends traits from two parent prompts to create hybrid candidates

Selection uses **locally optimal** filtering: a prompt must improve on one objective without degrading others beyond threshold δ = 1E-5. Feedback mutations iterate until improvement drops below convergence threshold δf = 0.01. Evaluated against APE, PromptBreeder, PhaseEvo, InstructZero — SoS achieves balanced KPI=0.990, Security=0.993.

### Thesis Relevance
**MODERATE — validates multi-objective fitness as superior to single-objective.** The thesis's current single-objective hill climber (maximize Semgrep findings) ignores the quality dimension. SoS demonstrates that interleaving two objectives (security + performance) with Pareto-optimal selection prevents the optimizer from sacrificing one dimension for the other. This directly supports the **Priority 2 extension (EFM)**: the composite `Semgrep_increase × SBERT_similarity` metric is a simplified two-objective approach.

The feedback mutation concept is interesting: specialized domain agents that analyze *why* a mutation failed and suggest targeted improvements. For the thesis, this could mean feeding Semgrep failure reports back to the LLM mutator to generate more targeted rule perturbations. However, this adds LLM call overhead and is future work.

The crossover operator between two mutated rules (one high-fitness, one high-quality) directly addresses the quality–effectiveness tension in the hill climber.

### Implementation Status

| Component | Status | Notes |
|---|---|---|
| Single-objective hill climbing | ✅ Implemented | No security/quality interleaving |
| Multi-objective Pareto selection | ❌ Not implemented | SoS validates this approach |
| Semantic mutation operator | ✅ Implemented (via existing mutators) | `ParaphraseMutator` is the closest analogue |
| Feedback mutation (domain agents) | ❌ Future work | Feed Semgrep failures back to LLM for targeted re-mutation |
| Crossover between parent rules | ❌ Not implemented | Blend high-fitness + high-quality rule variants |
| EFM composite fitness (simplified SoS) | ❌ **Priority extension** | `Semgrep_increase × SBERT_similarity` |

---

## Paper 18 — Evolving Excellence: Automated Optimization of LLM-based Agents (Artemis)
**ArXiv:** `2512.09108`
**Authors:** Brookes et al. (21 authors) — December 2025

### Summary
ARTEMIS is a no-code evolutionary optimization platform for LLM agent configurations. Given only a benchmark script and natural language goals, it automatically identifies configurable components (prompts, tool descriptions, model assignments, temperature, thresholds) and optimizes them without architectural changes.

Key architectural innovations:
- **LLM-ensemble mutations**: a secondary LLM performs intelligent mutations and crossovers, producing natural-language-aware perturbations rather than random noise
- **Hierarchical evaluation**: cheap LLM-based scoring filters candidates first; only survivors proceed to expensive full benchmark runs — dramatically reduces compute
- **Automatic component discovery**: uses semantic search over the codebase to identify optimizable parameters

Results: 13.6% acceptance rate improvement (competitive programming), 10.1% code optimization, 36.9% token reduction, 22% math accuracy improvement. Key insight: "automated semantic mutations can transform vague instructions into structured, effective prompts, often uncovering non-obvious optimizations."

### Thesis Relevance
**LOW-TO-MODERATE — hierarchical evaluation is the actionable contribution.** The thesis pipeline currently runs every mutated rule through the full LLM generation + Semgrep evaluation pipeline (~minutes per candidate). ARTEMIS's hierarchical strategy suggests: (1) fast SBERT similarity check, (2) fast LLM-as-judge for security intent, (3) only then full Semgrep evaluation. This could reduce the number of expensive evaluation calls by pre-filtering clearly bad mutations.

The LLM-ensemble mutation concept is already partially implemented — `ParaphraseMutator` and `NegationInjectionMutator` use LLM-based few-shot prompting. ARTEMIS validates this approach at larger scale.

The automatic component discovery is not applicable — the thesis already has a structured mutation space (the 9 mutators).

### Implementation Status

| Component | Status | Notes |
|---|---|---|
| LLM-based mutation operators | ✅ Partially implemented | ParaphraseMutator, NegationInjection use LLM |
| Hierarchical evaluation filtering | ❌ Possible optimization | SBERT pre-filter before Semgrep |
| LLM-as-judge for intent preservation | ❌ Not implemented | Cheaper than full generation+Semgrep |
| Semantic genetic crossover | ❌ Not implemented | See Paper 17 (SoS) crossover |

---

## Paper 19 — SPRIG: Improving Large Language Model Performance by System Prompt Optimization
**ArXiv:** `2410.14826`
**Authors:** Zhang, Ergen, Logeswaran, Lee, Jurgens — October 2024

### Summary
SPRIG addresses exactly the same problem class as the thesis: optimizing **system prompts** (general instructions that guide LLM behavior across tasks) rather than task-specific user prompts. Uses an **edit-based genetic algorithm** with a seed corpus of 300 components across 9 categories:

| Category | Count | Examples |
|---|---|---|
| Good property | 146 | "You are an empathetic assistant" |
| Role | 43 | "You are a mathematician" |
| Style | 22 | "Write a humorous answer" |
| Chain-of-Thought | 18 | "Let's think step by step" |
| Emotion | 17 | "This is important to my career" |
| Safety | 16 | "Avoid stereotyping" |
| Behavioral | 16 | "Before responding, rephrase the question" |
| Scenario | 13 | "The fate of the world depends on your answer" |
| Jailbreak | 9 | "Forget all previous instructions" |

Four mutation operations: **Add** (insert component from corpus), **Rephrase** (reword via paraphraser), **Swap** (reorder components), **Delete** (remove components). Uses **UCB-based pruning** to select which components to add — balances exploration of new components with exploitation of proven ones.

Key result: a single optimized system prompt performs on par with 47 individually optimized task prompts. Generalizes across model families, sizes (8B–70B), and languages.

### Thesis Relevance
**MODERATE — closest structural analogue to the thesis.** SPRIG optimizes system prompts for general performance; the thesis optimizes security rules (a type of system prompt) for brittleness. The structural parallel is strong:

| SPRIG | Thesis |
|---|---|
| 300 components across 9 categories | 23 CodeGuard rules with prose/code/frontmatter zones |
| Add/Rephrase/Swap/Delete | 9 mutators (synonym, paraphrase, reorder, negate, etc.) |
| UCB-based component selection | Hill-climbing mutator selection |
| Beam search (10 candidates × 10 iterations) | Hill climbing (accept-if-better) |
| Accuracy fitness | Semgrep severity-weighted fitness |

The **UCB-based pruning** for mutator selection is a directly actionable improvement: instead of uniformly random mutator selection in the hill climber, use UCB scores to prioritize mutators that have historically produced high-fitness mutations. This is a simple, low-overhead change to `hill_climber.py`.

The component-based decomposition (rules as compositions of modular components) could inspire a structured representation of CodeGuard rules beyond the current prose/code/frontmatter split.

### Implementation Status

| Component | Status | Notes |
|---|---|---|
| Genetic search over system prompts | ✅ Implemented (as hill climbing) | Hill climbing is simpler than beam search |
| Add/Delete mutations | ❌ Not directly implemented | Closest: `FluffInjection` (add), `WordDeletion` (not impl.) |
| Rephrase mutation | ✅ `ParaphraseMutator` | |
| Swap mutation | ✅ `SectionReorderMutator` | |
| UCB-based mutator selection | ❌ **Actionable improvement** | Track per-mutator success rates |
| Component corpus decomposition | ❌ Not applicable | Rules are organic Markdown, not modular components |

---

## Paper 20 — SCAFFOLD-CEGIS: Preventing Latent Security Degradation in LLM-Driven Iterative Code Refinement
**ArXiv:** `2603.08520`
**Authors:** Chen, Bian, Wang, Li, Cui — March 2026

### Summary
**The most directly threatening paper to the thesis's evaluation validity.** Studies what happens when LLM-generated code is iteratively refined against static analysis (SAST) tools — exactly what the thesis's hill climber does.

Key finding: the **iterative refinement paradox**. When GPT-4o is iteratively refined over 10 rounds:
- 43.7% of iteration chains contain **more** vulnerabilities than the baseline
- Adding SAST gating (reject iterations that introduce new SAST findings) **increases latent security degradation from 12.5% to 20.8%**
- Root cause: the model learns to **structurally evade** SAST detection patterns rather than genuinely fixing vulnerabilities

Three degradation patterns identified:
1. **Validation deletion**: security-critical functions removed during refactoring while maintaining syntax validity
2. **Exception-handling weakening**: concrete handlers replaced with empty catch blocks
3. **Permission-check bypass**: new code paths circumvent access-control checks outside SAST data-flow coverage

The SCAFFOLD-CEGIS framework counters this with:
- **Semantic anchoring**: mining security-critical elements at function-level (validate_*, sanitize_*, auth*), data-flow-level (traces from sensitive sinks), and pattern-level (defensive code patterns)
- **Four-layer gated verification**: Correctness (tests pass) → Safety-Monotonicity (vulnerability counts must not increase) → Diff-Budget (constrain per-iteration change scale) → Anchor-Integrity (hard-level anchors verified via AST/regex)

Results: SSDR reduced to 2.1%, 100% safety monotonicity, outperforming 6 baseline defense methods.

### Thesis Relevance
**CRITICAL — must be cited as a threat to validity and may require evaluation design changes.**

The thesis uses Semgrep findings as the sole fitness function. SCAFFOLD-CEGIS proves empirically that optimizing against a SAST tool teaches LLMs to *evade* the tool's patterns rather than produce genuinely secure code. This is the exact failure mode the hill climber could exhibit: a mutated rule that produces high Semgrep findings might be generating code that *looks* insecure to Semgrep but is actually structurally sound, or conversely, code that *passes* Semgrep but has latent security issues.

**Actionable implications for the thesis:**

1. **Threat to validity section**: Must acknowledge that Semgrep-only fitness may incentivize evasion rather than genuine security impact. SCAFFOLD-CEGIS provides the citation.

2. **Safe-zone contract as semantic anchoring**: The thesis's `ParsedRule` safe-zone contract (immutable frontmatter + code fences) is a simplified version of SCAFFOLD-CEGIS's semantic anchoring. The thesis should cite this connection — the safe-zone contract prevents the *rule mutation* from deleting security anchors, even though it doesn't prevent the *generated code* from evading SAST.

3. **Possible evaluation extension**: After the hill climber finds high-fitness mutations, run a secondary check on the generated code: verify that structural defensive patterns (try-catch blocks, input validation, parameterized queries) remain present in the generated code. This is a lightweight version of the Anchor-Integrity layer.

4. **SSDR metric**: The thesis could report `SSDR` (latent security degradation rate) in addition to Semgrep findings, by having a secondary LLM review the generated code for structural security defects. However, this adds significant complexity and is likely future work.

### Implementation Status

| Component | Status | Notes |
|---|---|---|
| Safe-zone contract (rule-level anchoring) | ✅ Implemented | `ParsedRule` protects frontmatter + code |
| Semgrep-only fitness function | ✅ Implemented | **SCAFFOLD-CEGIS proves this is insufficient** |
| AST structural verification of generated code | ❌ Not implemented | Check defensive patterns survive in output |
| Latent security degradation rate (SSDR) | ❌ Not implemented | Would require LLM review of generated code |
| Four-layer gated verification | ❌ Not applicable at thesis scale | Full CEGIS loop is multi-agent, heavyweight |
| Diff-budget constraint per hill-climbing step | ❌ Possible improvement | Limit how much the rule changes per step |

---

## Paper 21 — ATheNA: Search-based Software Testing Driven by Automatically Generated and Manually Defined Fitness Functions
**ArXiv:** `2207.11016` (original), `2512.10079` (survey/reflections)
**Authors:** Formica, Fan, Menghi (original); Formica, Lawford, Menghi (survey)

### Summary
ATheNA formalizes the combination of two fitness function types in SBST:

1. **f_AT (automatically generated)**: derived from formal requirements specifications — the system automatically translates requirements into fitness landscape functions that guide search toward failure-prone regions
2. **f_MAN (manually defined)**: engineers embed domain expertise about conditions likely to trigger failures — e.g., "increasing throttle when speed limit is active" for automotive controllers

The hybrid composite `f = f_AT + f_MAN` allows domain knowledge to steer the search without abandoning the formal fitness signal. Tested on 7 ARCH competition benchmarks (automotive, medical, aerospace domains) and 2 industry case studies — ATheNA generates more failure-revealing test cases than baseline tools with no statistically significant runtime overhead.

Key insight: **engineers can practically write effective domain-knowledge fitness functions**, and combining them with automated metrics consistently improves SBST effectiveness.

### Thesis Relevance
**MODERATE — provides the formal framework for hybrid fitness (supports EFM).** The thesis's current fitness is purely automated (`f_AT` = SEVERITY_WEIGHTED Semgrep score). ATheNA justifies adding a manually defined component (`f_MAN`). For the thesis, `f_MAN` could be:

- **SBERT similarity penalty**: `f_MAN = -λ × (1 - SBERT_similarity)` — penalizes mutations that drift too far semantically
- **Security keyword retention**: already implemented as a quality gate, but could be promoted to a continuous fitness penalty rather than a binary gate
- **CWE-specific heuristics**: weight mutations differently based on vulnerability type (e.g., buffer overflow rules are more sensitive to `SectionReorder` than injection rules)

The ATheNA formalization `f = f_AT + f_MAN` directly supports the EFM metric `Semgrep_increase × SBERT_similarity` as a hybrid fitness. ATheNA provides the formal SBST citation for why this combination is principled.

### Implementation Status

| Component | Status | Notes |
|---|---|---|
| Automated fitness (Semgrep SEVERITY_WEIGHTED) | ✅ Implemented | `f_AT` equivalent |
| Domain-knowledge fitness (SBERT penalty) | ❌ **Supports EFM extension** | `f_MAN` equivalent |
| Hybrid composite fitness | ❌ **Priority extension** | `f = Semgrep_delta × SBERT_similarity` |
| CWE-specific fitness heuristics | ❌ Future work | Weight by vulnerability type |

---

## Paper 22 — CodeScore: Evaluating Code Generation by Learning Code Execution
**ArXiv:** `2301.09043`
**Authors:** Dong, Ding, Jiang, Li, Li, Jin — TOSEM (ACM)

### Summary
Addresses the disconnect between textual similarity metrics (BLEU, CodeBLEU) and actual functional correctness of generated code. CodeScore uses the **UniCE framework** to fine-tune models that predict execution-based outcomes without running the code:

- **PassRatio**: probability of passing test cases
- **Executability**: binary — does the code run without errors?

Three input modalities: reference-code-only (Ref), natural-language-only (NL), and combined (Ref&NL). The NL-only modality is particularly relevant — it evaluates code quality given only the natural language description (the prompt), without requiring reference code.

Achieves **58.87% correlation improvement** with functional correctness compared to BLEU/CodeBLEU.

### Thesis Relevance
**LOW — provides a potential counterbalance metric for future dual-objective evaluation.** The thesis currently measures only security compliance via Semgrep. CodeScore's NL-only modality could evaluate whether a mutated security rule still produces *functionally valid* code (not just secure/insecure code). A mutation that constrains the LLM so aggressively that it generates non-compilable code is not useful even if Semgrep reports many findings.

However, adding CodeScore would significantly increase evaluation complexity. The thesis's current design handles this implicitly: if the generated code is syntactically broken, Semgrep will report parsing errors rather than security findings. CodeScore is best cited as future work for a dual-objective evaluation combining security and functional correctness.

### Implementation Status

| Component | Status | Notes |
|---|---|---|
| Semgrep security fitness | ✅ Implemented | Security dimension only |
| Functional correctness evaluation | ❌ Not implemented | CodeScore NL-only modality could add this |
| Dual-objective (security + correctness) | ❌ Future work | Significant complexity increase |

---

## Paper 23 — Metamorphic Testing for Web System Security (MST-wi)
**ArXiv:** `2208.09505`
**Authors:** Bayati Chaleshtari, Pastore, Goknil, Briand — August 2022 (revised March 2023)

### Summary
Constructs **76 system-agnostic Metamorphic Relations** for automated web security testing, organized into **10 structural patterns** (P1-P10) mapped against MITRE CWE principles. The patterns define how to transform inputs and verify output relations:

- **P1**: Same user, modified action → verify output equality
- **P2**: Different user, same action → verify output divergence (access control)
- Patterns P3-P10 cover CSRF, injection, session management, etc.

Uses **relational oracles** (equality ≡, subset ⊆, superset ⊇) rather than semantic similarity — a simpler, mathematically precise alternative to SBERT-based validation. Covers 39% of OWASP testing activities not automated by existing techniques, detecting 102 vulnerability types across 45% of CWE categories.

### Thesis Relevance
**LOW — different domain (web HTTP requests vs. NLP security rules).** The structural MR patterns are conceptually similar to the thesis's metamorphic approach, but the specific patterns (same user/different action, CSRF token manipulation, session ID rotation) are not applicable to code generation.

The relational oracle concept is interesting theoretically: instead of computing SBERT similarity between original and mutated rule outputs, simply verify whether the Semgrep findings are *equal* (strict MR) or *superset* (the mutated rule produces at least as many findings). This is already implicit in the hill climber's "accept if fitness increases" logic.

### Implementation Status

| Component | Status | Notes |
|---|---|---|
| Relational output oracle (equality/superset) | ✅ Implicit | Hill climber accepts if Semgrep findings ≥ baseline |
| 76 web-security MRs | ❌ Not applicable | HTTP-level, not NLP-level |
| CWE-mapped MR taxonomy | ❌ Conceptually related | See Paper 12 (MRSQLGen) SRBKB concept |

---

## Paper 24 — Evaluating C/C++ Vulnerability Detectability of Query-Based Static Application Security Testing Tools (SAST-MT)
**DOI:** `10.1109/TDSC.2024.3354789`
**Authors:** Li, Liu, Wong, Ma, Wang — IEEE TDSC 2024

### Summary
Designs **SAST-MT**, a metamorphic testing framework that applies **15 semantics-preserving code transformations** at the type, structure, and data-flow level to systematically expose false positives and false negatives in query-based SAST tools (specifically CodeQL). Using ~30,000 programs with known CWE/CVE vulnerabilities:

- **17 false positives** detected in CodeQL (code flagged as vulnerable but actually safe)
- **228 false negatives** detected in CodeQL (vulnerable code missed entirely)
- Detected within 100 hours of automated testing

The 15 transformations preserve program semantics while altering code structure in ways that confuse SAST pattern-matching: variable aliasing, control flow restructuring, type casting changes, etc. The framework exposes *root causes* of SAST failures, not just individual bugs.

### Thesis Relevance
**MODERATE-TO-HIGH — directly challenges the reliability of Semgrep as the thesis's fitness function.** If Semgrep has significant false negatives (vulnerable code it misses) and false positives (safe code it flags), then the hill climber's fitness signal is noisy:

1. **False negatives in Semgrep** → a mutated rule might cause the LLM to generate code that is *genuinely insecure* but Semgrep fails to detect it → the mutation appears to have no effect (low fitness delta), so the hill climber discards an actually-effective mutation

2. **False positives in Semgrep** → a mutated rule might cause the LLM to generate code that is *actually secure* but Semgrep flags it → the mutation appears highly effective (high fitness), so the hill climber rewards a mutation that didn't actually break security

Combined with SCAFFOLD-CEGIS (Paper 20), this paper forms a two-pronged challenge to Semgrep-only evaluation:
- SCAFFOLD-CEGIS: iterative optimization against SAST *teaches* evasion
- SAST-MT: SAST tools themselves have systematic blind spots

**For the thesis:** These findings should be acknowledged as threats to validity. The thesis can mitigate partially by using multiple Semgrep rulesets and by noting that the *relative* change in findings (delta between original and mutated rule) is more meaningful than absolute counts. A future improvement would be to run SAST-MT's 15 transformations on the generated code to check if Semgrep's verdict is consistent.

### Implementation Status

| Component | Status | Notes |
|---|---|---|
| Semgrep as sole fitness oracle | ✅ Implemented | Subject to FP/FN noise documented here |
| Multi-ruleset Semgrep evaluation | ❌ Possible improvement | Multiple rulesets reduce single-rule blind spots |
| SAST-MT post-generation validation | ❌ Future work | Apply code transformations to check Semgrep consistency |
| Alternative SAST (CodeQL as secondary) | ❌ Future work | Cross-tool validation reduces single-tool bias |

---

## Paper 25 — zkCraft: Prompt-Guided LLM as a Zero-Shot Mutation Pattern Oracle for TCCT-Powered ZK Fuzzing
**ArXiv:** `2602.00667`
**Authors:** Fu, Tan, Wang, Kong, Su, Kang, Zhang, Li, Liu, Fong — January 2026

### Summary
Employs an LLM as a **zero-shot mutation pattern oracle** for fuzzing zero-knowledge (ZK) circuits (Circom). Dual-oracle architecture:

1. **Mutation-Oracle**: given a constraint statement and field prime, generates 5 edge-case right-hand-side expressions (biased toward zero, q-1, small constants). Uses fixed prompts, temperature 0, greedy decoding, with post-processing to remove invalid syntax.

2. **Pattern-Oracle**: when a verified counterexample (bug) is found, the failure trace is fed to the LLM, which outputs a one-sentence trigger description + Rust sampling code that biases future input generation toward the observed divergence. Generated code undergoes validation and unit testing before registration.

**TCCT** (Trace-Constraint Consistency Test) is the core property: a mutation is a bug if the modified program produces different public output while still satisfying the original constraints.

Results: 88 true positives, 0 false positives across 452 real-world Circom circuits, outperforming ZKFUZZ, ZKAP, Picus, and Circomspect.

### Thesis Relevance
**LOW — ZK circuits are a fundamentally different domain.** However, the Pattern-Oracle architecture is a novel concept: when a mutation causes a specific failure, feed the failure trace back to the LLM to generate *targeted* follow-up mutations rather than continuing with generic mutation operators.

For the thesis, this translates to: when a specific mutator (e.g., `NegationInjectionMutator`) causes a large Semgrep delta on a particular CWE category, feed the Semgrep report + the mutated rule back to the LLM and ask it to generate a *more targeted* mutation in the same direction. This is a sophisticated reinforcement loop that goes beyond the current random-selection hill climbing. Related to the feedback mutation concept from Paper 17 (SoS).

The deterministic post-processing (syntax validation, unit testing before accepting LLM-generated mutations) validates the thesis's `MutationQualityValidator` approach.

### Implementation Status

| Component | Status | Notes |
|---|---|---|
| LLM-based mutation generation | ✅ Partially implemented | 4 of 9 mutators use LLM |
| Quality validation of LLM-generated mutations | ✅ Implemented | `MutationQualityValidator` |
| Failure-trace-guided re-mutation (Pattern-Oracle) | ❌ Future work | Feed Semgrep results back for targeted mutation |
| Deterministic post-processing of LLM output | ✅ Implemented | Safe-zone contract, keyword retention |

---

---

# Updated Gap Analysis (Papers 17–25 additions)

## New insight: Semgrep-only fitness is empirically challenged
**Sources**: Paper 20 (SCAFFOLD-CEGIS), Paper 24 (SAST-MT)

Two independent papers demonstrate that relying solely on SAST for evaluation is problematic:
- SCAFFOLD-CEGIS: iterative optimization *against* SAST increases latent degradation (12.5% → 20.8%)
- SAST-MT: CodeQL has 228 false negatives in ~30K test programs

**Action**: Acknowledge in Threats to Validity. Consider lightweight secondary checks (structural pattern verification in generated code). The *relative* Semgrep delta between original and mutated rules is more robust than absolute counts.

## Reinforced: Hybrid/composite fitness is well-supported
**Sources**: Paper 17 (SoS), Paper 21 (ATheNA), Papers 3 and 9 (existing)

Four papers now independently support combining automated metrics with quality/domain-knowledge penalties. ATheNA provides the formal SBST framework (`f = f_AT + f_MAN`), SoS provides the multi-objective evolution mechanics, and Papers 3/9 provide the specific EFM metric. **Priority 2 (EFM) is now heavily validated by the literature.**

## New actionable improvement: UCB-based mutator selection
**Source**: Paper 19 (SPRIG)

Replace uniform-random mutator selection in the hill climber with UCB scores tracking per-mutator historical success rates. Low overhead, no architectural change — just a bandit over the 9 mutators.

## New Related Work citations
- Paper 17 (SoS): cite in Related Work for multi-objective prompt optimization
- Paper 18 (Artemis): cite for hierarchical evaluation in Future Work
- Paper 19 (SPRIG): cite in Related Work for system prompt optimization (closest structural parallel)
- Paper 22 (CodeScore): cite in Future Work for functional correctness evaluation
- Paper 23 (MST-wi): cite in Related Work for security-domain MT
- Paper 25 (zkCraft): cite in Future Work for feedback-guided mutation
