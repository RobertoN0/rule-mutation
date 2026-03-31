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
