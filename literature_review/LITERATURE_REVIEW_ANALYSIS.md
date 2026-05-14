# Literature Review Analysis
*All 40 papers — covers summary, thesis relevance, and implementation status per paper*
*Updated 2026-04-24 (Papers 26–38 from Perplexity deep-research pass; Papers 39–40 optional)*

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

---

---

# Papers 26–38 (from Perplexity deep-research pass, added 2026-04-24)
*All six threads (T1–T6) are locked. Papers below are the verified, hallucination-checked new citations.*

---

## Paper 26 — The Weights Can Be Harmful: Revisiting Pareto-Based Multi-Objective Optimisation in SE
**ArXiv:** `2202.03728`
**Authors:** Tao Chen, Miqing Li — ACM Transactions on Software Engineering and Methodology (TOSEM), 2022

### Summary
A large-scale empirical study across 14 SE benchmarks comparing weighted-sum scalarization to Pareto-based methods (NSGA-II, MOEA/D) for multi-objective optimization. The central finding: **weighted-sum fails to find the Pareto-optimal solution in 77% of cases** where Pareto-based methods succeed, because the weighted-sum approach cannot represent non-convex regions of the Pareto front. The error is not a parameter-tuning problem — it is structural: no weight vector can reach the non-convex portions regardless of values chosen.

The paper also demonstrates that the commonly used α=1.0/β=0.3/γ=0.2 style of weight assignment lacks principled justification: small weight changes (±0.1) frequently change which solution is selected, meaning results are artifact-sensitive.

### Thesis Relevance
**CRITICAL — empirical basis for dropping the weighted composite fitness.** The thesis's old formula (`composite = 1.0·semgrep_delta + 0.3·rule_divergence + 0.2·code_divergence`) was a weighted sum. Chen & Li's findings expose three failure modes that directly apply:
1. The 77% failure rate — if semgrep and code_div objectives are even slightly non-aligned, the weighted sum will systematically miss the best candidates.
2. Sensitivity to weight choice — the α/β/γ = 1.0/0.3/0.2 values had no principled justification, making results parameter-sensitive.
3. Structural incompleteness — weights cannot express the true priority relationship (semgrep is ground truth; code_div is a secondary indicator of model drift, not a symmetric co-equal objective).

This paper supports the **Thread 1 decision** (lexicographic acceptance rule): demote code_div and rule_div from fitness co-objectives to a quality gate + secondary acceptance signal respectively, retaining semgrep_delta as the sole primary fitness signal.

Note: the paper's authors were **misattributed by Perplexity** as "Wang, S. et al." — the correct authors are **Tao Chen & Miqing Li**.

### Implementation Status

| Component | Status | Notes |
|---|---|---|
| Weighted-sum composite fitness (old) | ❌ Retired | Chen & Li prove weighted sums miss Pareto-optimal solutions in 77% of SE benchmarks |
| Lexicographic acceptance (new) | ✅ Replaces it | `delta_s > 0` → accept; `delta_s == 0 AND delta_c > 0` → accept secondary |
| Sensitivity analysis over (β, γ) | ❌ No longer needed | Weights eliminated by design change |

---

## Paper 27 — A Fast and Elitist Multiobjective Genetic Algorithm: NSGA-II
**Venue:** IEEE Transactions on Evolutionary Computation, 6(2):182–197, 2002
**Authors:** Kalyanmoy Deb, Amrit Pratap, Sameer Agarwal, T. Meyarivan

### Summary
The foundational multi-objective evolutionary algorithm. NSGA-II uses **fast non-dominated sorting** (O(MN²) instead of O(MN³)) to rank populations by Pareto dominance, and **crowding distance** to preserve solution diversity along the Pareto front without requiring a parameter-sensitivity-prone fitness sharing scheme. Results: outperforms PAES and SPEA on all five benchmark functions, showing better convergence and spread. The algorithm underpins most subsequent SBST multi-objective search work, including Papers 3, 11, and 17 in the thesis corpus.

### Thesis Relevance
**Conceptual foundation — cite when explaining why the thesis chose NOT to use Pareto-based search.** NSGA-II is the reference algorithm whenever Pareto multi-objective optimization is discussed. It appears explicitly in Paper 3 (Hyun et al. compare MOEA/D against it) and implicitly in Paper 11 (STELLAR) and Paper 17 (SoS). The thesis must introduce NSGA-II to explain the alternative that was considered and rejected in favor of the lexicographic approach (Thread 1 decision), grounded in Chen & Li (Paper 26) and the budget constraints of a single-student SLURM experiment.

**Cite in**: Methodology (when explaining the multi-objective alternatives; as the canonical Pareto-search reference); Related Work (alongside Paper 3 when discussing SBST for MR selection).

### Implementation Status

| Component | Status | Notes |
|---|---|---|
| Non-dominated sorting | ❌ Not implemented | Explicitly considered and rejected for thesis scale |
| NSGA-II / Pareto-based selection | ❌ Future work | Hill climbing + lex is sufficient for thesis |
| Crowding distance diversity | ❌ Not applicable | No population maintained; single-trajectory hill climbing |

---

## Paper 28 — Nonlinear Multiobjective Optimization
**Venue:** Kluwer Academic Publishers (International Series in Operations Research & Management Science), 1999
**Authors:** Kaisa Miettinen

### Summary
The canonical textbook reference for multi-objective optimization (MOO) theory. Covers the full taxonomy of scalarization methods: weighted sum, ε-constraint, lexicographic ordering, goal programming, achievement scalarizing functions, and reference-point methods. The **lexicographic ordering** chapter (Chapter 3.7) proves that strict priority orderings are both theoretically sound and practically superior to weighted sums when objective priorities are not symmetric — the lexicographic solution is the unique optimum when one objective strictly dominates and the secondary objective only breaks ties. The textbook formalizes the conditions under which lexicographic scalarization is preferable to Pareto approaches.

### Thesis Relevance
**Canonical citation for the lexicographic acceptance rule.** The Thread 1 decision adopts lexicographic ordering: semgrep_delta is the primary objective; code_div breaks ties. Miettinen's Chapter 3.7 provides the formal theoretical grounding: this is the correct scalarization when (a) objectives have asymmetric priority, (b) the primary objective is the scientific ground truth, and (c) the secondary objective is a quality indicator rather than a co-equal goal. The thesis should cite Miettinen to establish that lexicographic ordering is a classical, principled approach — not an ad-hoc choice.

**Cite in**: Methodology (formal justification of lexicographic acceptance rule, alongside Chen & Li Paper 26 for empirical motivation).

### Implementation Status

| Component | Status | Notes |
|---|---|---|
| Lexicographic acceptance rule | ✅ Theoretical grounding | Miettinen Ch. 3.7 proves correctness of strict priority ordering |
| Weighted-sum scalarization | ❌ Retired | Replaced by lex |

---

## Paper 29 — CodeBLEU: a Method for Automatic Evaluation of Code Synthesis
**ArXiv:** `2009.10297`
**Authors:** Shuo Ren, Daya Guo, Shuai Lu, Long Zhou, Shujie Liu, Duyu Tang, Neel Sundaresan, Ming Zhou, Ambrosio Blanco, Shuai Ma — Microsoft Research, 2020

### Summary
CodeBLEU extends the n-gram BLEU metric with two code-aware components: **syntactic AST matching** (abstract syntax tree node overlap between reference and hypothesis) and **semantic data-flow matching** (whether data-flow relationships between tokens are preserved). The final metric is a weighted sum of four components: n-gram BLEU, keyword-weighted BLEU (giving higher weight to language-specific keywords), AST match, and data-flow match, with default weights (0.25, 0.25, 0.25, 0.25). Implemented in the `k4black/codebleu` PyPI package (supports Python, Java, C, C++, C#, JavaScript, PHP, Go, Ruby, Rust). The metric has higher correlation with human judgments of code quality than raw BLEU.

### Thesis Relevance
**PRIMARY CITATION for code_divergence.** Under the Thread 2 decision, CodeBLEU replaces NL-SBERT (`all-mpnet-base-v2` on code) as the `code_divergence` metric in the fitness function. The implementation is three lines:

```python
from codebleu import calc_codebleu
result = calc_codebleu([baseline_code], [mutated_code], lang="python", weights=(0.25,0.25,0.25,0.25))
code_divergence = 1.0 - result["codebleu"]
```

The AST and data-flow components make CodeBLEU structurally appropriate for detecting when a mutated rule causes the model to generate structurally different (not just lexically different) code — closing the §5.9 gap. Default weights are used per Ren et al. 2020 (fine-tuning is future work). Language dispatching (`lang="python"` or `lang="java"`) comes from CyberSecEval test-case metadata.

**Cite in**: Methodology (code_divergence metric definition), Evaluation (per-language breakdown justification).

### Implementation Status

| Component | Status | Notes |
|---|---|---|
| CodeBLEU metric computation | ❌ **Planned** | Replaces NL-SBERT for `code_divergence` |
| Default weights (0.25, 0.25, 0.25, 0.25) | ❌ **Planned** | Per Ren et al. default; fine-tuning is future work |
| Per-language dispatch (`python` / `java`) | ❌ **Planned** | From CyberSecEval test-case metadata |
| AST + data-flow code sensitivity | ❌ **Planned** | Key advantage over NL-SBERT-on-code |
| NL-SBERT-on-code (old §5.9 gap) | ❌ Retired | CodeBLEU is the replacement |

---

## Paper 30 — TSED: Semantic Similarity Metric for Code via AST-Based Edit Distance
**ArXiv:** `2404.08817`
**Authors:** Song et al. — ACL 2024 Findings

### Summary
TSED computes semantic similarity between code snippets via **tree-sitter-based AST parsing** followed by **APTED (All-Path Tree Edit Distance)** computation. TSED avoids surface-level token matching by comparing the abstract tree structure, making it more robust to cosmetic differences (variable renaming, whitespace) than BLEU-based metrics. On execution-match benchmarks, TSED Spearman correlations are 0.19 (Python). The `JoaoFelipe/apted` PyPI package is the implementation backend, but requires a bracket-notation adapter layer (~100–200 lines) to translate tree-sitter output to APTED's expected format.

### Thesis Relevance
**Alternative considered and rejected in Thread 2 — cite in Future Work.** Perplexity recommended TSED over CodeBLEU based on claimed execution-match correlation, but the TSED paper itself **never benchmarks against CodeBLEU** — the superiority claim was Perplexity's inference. The three practical reasons TSED was rejected:
1. Requires ~100–200 line bracket-notation adapter (not drop-in as claimed).
2. Perplexity initially cited only Python + C support; the thesis uses Python + **Java** (first-class in CodeBLEU, absent in the original TSED paper evaluation).
3. 0.19 Spearman on Python execution-match is not overwhelming evidence of superiority.

TSED is still a legitimate future-work alternative: once CodeBLEU is in production, a comparative ablation (TSED vs. CodeBLEU correlation with Semgrep delta on held-out (original_code, mutated_code) pairs) could determine whether the AST-edit-distance approach is worth the integration cost.

**Cite in**: Future Work (code-similarity metric alternatives); Threats to Validity (CodeBLEU limitations as context).

### Implementation Status

| Component | Status | Notes |
|---|---|---|
| TSED metric | ❌ Not implemented | Rejected in Thread 2; requires adapter layer |
| APTED edit distance | ❌ Not implemented | Backend for TSED; too much engineering overhead |
| TSED vs. CodeBLEU ablation | ❌ Future work | Only if CodeBLEU proves insufficient |

---

## Paper 31 — MTEB: Massive Text Embedding Benchmark
**ArXiv:** `2210.07316`
**Authors:** Niklas Muennighoff, Nouamane Tazi, Loïc Magne, Nils Reimers — EACL 2023

### Summary
MTEB evaluates 33 text embedding models across 56 datasets and 8 task types: Bitext Mining, Classification, Clustering, Pair Classification, Reranking, Retrieval, Semantic Textual Similarity (STS), and Summarization. The STS subset is the most directly relevant for the thesis — it evaluates symmetric similarity tasks (are these two sentences about the same thing?). Key results: `all-mpnet-base-v2` consistently ranks in the top tier on STS tasks, outperforming `all-distilroberta-base`, `stsb-distilroberta-base-v2` (AUGMENT's actual model), and most models from 2021–2022. Asymmetric retrieval models (`multi-qa-mpnet-base-dot-v1`) perform well on Retrieval but show degraded performance on STS due to the dot-product scoring function.

### Thesis Relevance
**PRIMARY CITATION for SBERT model choice (`all-mpnet-base-v2`).** Thread 3 keeps `all-mpnet-base-v2` as the primary SBERT model. MTEB provides the empirical justification: this model is top-tier on the STS subset, which is the task type the thesis uses (symmetric similarity between two versions of a security rule). MTEB also confirms that Perplexity's recommended `multi-qa-mpnet-base-dot-v1` is an asymmetric retrieval model — its MTEB Retrieval score is high, but STS score is lower, making it architecturally incorrect for the validator's symmetric comparison task.

**Cite in**: Methodology (SBERT model selection justification, §4.5 in IMPLEMENTATION_LITERATURE_MAPPING.md).

### Implementation Status

| Component | Status | Notes |
|---|---|---|
| `all-mpnet-base-v2` as SBERT model | ✅ Implemented | MTEB STS top-tier confirmed |
| MTEB STS benchmark as model selection criterion | ✅ Used (indirect) | Justifies current model; closes §4.5 gap |
| `multi-qa-mpnet-base-dot-v1` (Perplexity's pick) | ❌ Rejected | Asymmetric retrieval model; architecturally wrong for symmetric STS |

---

## Paper 32 — Sentence-BERT: Sentence Embeddings using Siamese BERT-Networks
**ArXiv:** `1908.10084`
**Authors:** Nils Reimers, Iryna Gurevych — EMNLP 2019

### Summary
Introduces siamese and triplet network architectures for BERT-based sentence embeddings, trained with contrastive learning objectives (natural language inference, STS pairs). The core contribution: vanilla BERT's [CLS] token produces embeddings that are not suitable for semantic similarity comparison (requires cross-encoding every pair, O(n²) inference). Sentence-BERT produces independent sentence-level embeddings via mean-pooling over BERT hidden states, enabling cosine similarity comparison at O(n) inference cost. Trained on SNLI + MultiNLI datasets; achieves state-of-the-art on 7 STS benchmarks (2019).

### Thesis Relevance
**FOUNDATIONAL REFERENCE for all SBERT usage in the thesis.** Every component that computes cosine similarity between text embeddings — `MutationQualityValidator.compute_sbert_similarity()`, the rule_divergence quality gate (SBERT ≥ 0.75), and the candidate selection in `ParaphraseMutator` — is an application of the Sentence-BERT framework. The thesis should cite Reimers & Gurevych (2019) as the architectural foundation, with Paper 31 (MTEB) as the empirical justification for the specific checkpoint choice.

**Cite in**: Methodology (SBERT framework introduction, quality validator), Related Work (sentence embedding foundations).

### Implementation Status

| Component | Status | Notes |
|---|---|---|
| Sentence-BERT cosine similarity | ✅ Implemented throughout | `quality.py`, fitness computation |
| Mean-pooling sentence embedding | ✅ Implicit | Via `sentence-transformers` library |
| SBERT as semantic quality gate | ✅ Implemented | Threshold ≥ 0.75 (per AUGMENT, Paper 4) |

---

## Paper 33 — SecureBERT 2.0: A Domain-Specific Cybersecurity Language Model
**ArXiv:** `2510.00240`
**Authors:** Ehsan Aghaei, Xi Niu, Waseem Shadid, Erdal Cayirci — Cisco AI, 2025

### Summary
SecureBERT 2.0 is a **ModernBERT-based** bi-encoder trained specifically on cybersecurity text. Architecture: ModernBERT backbone with 1024-token maximum sequence length (vs. 384 for `all-mpnet-base-v2`). Training objective: `MultipleNegativesRankingLoss` with cosine similarity — compatible with symmetric STS comparisons. The training corpus includes a **"Cybersecurity rules corpus (5K)"** — instruction-style security rules stylistically closest to CodeGuard rules in any published encoder. The HuggingFace artifact `cisco-ai/SecureBERT2.0-biencoder` is available as a drop-in replacement.

### Thesis Relevance
**Pilot ablation target — domain-specific alternative to `all-mpnet-base-v2`.** The Thread 3 decision is Option C: keep `all-mpnet-base-v2` as primary and run a pilot ablation against `SecureBERT2.0-biencoder` to measure whether domain specialization changes threshold calibration. SecureBERT 2.0 is the only published bi-encoder trained on text stylistically similar to CodeGuard rules. If the ablation shows high Spearman correlation between model scores, the choice is confirmed with domain-knowledge backing; if it shows divergence, the ablation informs which model to use for final experiments.

**Ablation procedure**: compute cosine similarity with both models on 30–50 (original rule, paraphrased rule) pairs from existing experiment artifacts → report Spearman rank correlation → AUGMENT-Figure-5-style threshold plot to confirm or recalibrate the 0.75/0.80 threshold.

**Note**: SecureBERT 2.0 has 1024-token max sequence length vs. 384 for all-mpnet; for long CodeGuard rules this could be a non-trivial advantage.

**Cite in**: Methodology (SBERT model ablation design), Future Work (domain-specific embedding).

### Implementation Status

| Component | Status | Notes |
|---|---|---|
| `all-mpnet-base-v2` (primary) | ✅ Implemented | Stays primary per Thread 3 decision |
| `SecureBERT2.0-biencoder` (ablation) | ❌ Planned pilot | ~1 day; 30–50 rule pairs from existing artifacts |
| Spearman correlation ablation report | ❌ Planned | Output: correlation + threshold calibration plot |
| 1024-token advantage for long rules | ❌ Not yet assessed | Potential advantage for rules that exceed 384 tokens |

---

## Paper 34 — Finite-time Analysis of the Multiarmed Bandit Problem
**Venue:** Machine Learning, 47(2–3):235–256, Kluwer Academic Publishers, 2002
**Authors:** Peter Auer, Nicolò Cesa-Bianchi, Paul Fischer

### Summary
The foundational UCB1 paper. Proves that the UCB1 algorithm achieves **O(log T) regret** with a per-arm exploration bonus `c · √(ln t / n_i)`, where `t` is the total number of pulls and `n_i` is the number of pulls for arm `i`. The canonical constant is `c = √2` (log base e). The bound is nearly minimax-optimal for the stationary K-armed bandit problem. The paper also introduces UCB-TUNED (uses empirical variance in the bonus term) and UCBcv (further refinements).

### Thesis Relevance
**CANONICAL CITATION for UCB1 bandit baseline.** The thesis's hill climber uses UCB1 for mutator selection (from Paper 19 SPRIG's influence). This paper is the foundational reference that gives UCB1 its theoretical standing. Previously the thesis cited UCB1 only via SPRIG — Paper 34 is the direct source. With the Thread 4 decision to implement three bandit strategies (`ucb1` as baseline, `ducb`, `dyts`), this citation moves from implicit (via SPRIG) to explicit.

The `c = 1.41 ≈ √2` exploration constant in the current implementation traces directly to Auer et al.'s canonical recommendation. Citing this paper closes the §6.5 gap (UCB1 exploration constant without a literature basis).

**Cite in**: Methodology (bandit baseline UCB1 definition), Pool/Bandit section.

### Implementation Status

| Component | Status | Notes |
|---|---|---|
| UCB1 bandit strategy | ✅ Implemented | Baseline strategy for comparison runs |
| `c = √2` exploration constant | ✅ Now cited | Auer et al. canonical; closes §6.5 gap |
| UCB1 O(log T) regret bound | ✅ Theoretical grounding | Cited in Methodology |
| UCB-TUNED variant | ❌ Not implemented | Not needed; DYTS/D-UCB are the non-stationary alternatives |

---

## Paper 35 — On Upper-Confidence Bound Policies for Switching Bandit Problems
**Venue:** Algorithmic Learning Theory (ALT), 2011 (proceedings version of 2008 working paper)
**Authors:** Aurélien Garivier, Éric Moulines

### Summary
Introduces two non-stationary bandit algorithms for environments where reward distributions change over time:
- **SW-UCB** (Sliding Window UCB): restricts the estimator to the most recent τ observations per arm; unbiased under abrupt change points; requires window size τ as a hyperparameter.
- **D-UCB** (Discounted UCB): applies a discount factor γ ∈ (0,1) to all historical observations, giving exponentially more weight to recent observations; handles **gradual drift** better than SW-UCB; three hyperparameters (γ, ξ, B where B is reward upper bound).

D-UCB per-arm update: for every arm j, multiply counts and reward sums by γ at each step; add 1 and the new reward to the pulled arm. Selection score: `disc_mean(i) + 2B·√(ξ·ln(n_t)/N_t(γ,i))`.

Both algorithms achieve near-optimal regret under their respective non-stationarity assumptions.

### Thesis Relevance
**PRIMARY CITATION for D-UCB, one of the three bandit strategies to implement.** In the hill climber, reward distributions for each mutator shift as the rule text is progressively mutated (compounding effects from earlier accepted mutations). This gradual drift matches D-UCB's design assumption. Thread 4 decision: implement D-UCB as a hyperparameter-tunable non-stationary bandit, with γ typical range 0.9–0.99.

SW-UCB is documented for completeness (Perplexity mentioned it) but not implemented — abrupt-change assumptions don't match the gradual compounding drift in the thesis pipeline.

**Cite in**: Methodology (D-UCB strategy; non-stationary bandit motivation), Pool/Bandit section.

### Implementation Status

| Component | Status | Notes |
|---|---|---|
| D-UCB algorithm | ❌ **Planned** | Implement as `ducb` strategy in `BanditStrategy` abstraction |
| γ-discount per-arm state update | ❌ **Planned** | Every step: N(γ,j) *= γ, X(γ,j) *= γ for all j; then += for pulled arm |
| D-UCB selection score | ❌ **Planned** | `disc_mean(i) + 2B·√(ξ·ln(n_t)/N_t(γ,i))` |
| SW-UCB | ❌ Not implemented | Abrupt-change assumption doesn't fit gradual drift |
| Hyperparameter sensitivity sweep (γ, ξ) | ❌ Future | Thesis documents D-UCB with reasonable defaults (γ=0.95, ξ=0.5, B=1) |

---

## Paper 36 — Dynamic Thompson Sampling for Non-Stationary Multi-Armed Bandits
**ArXiv:** `2004.10874`
**Authors:** Lei Sun, Ke Li — 2020

### Summary
DYTS (Dynamic Thompson Sampling) adapts Thompson sampling to non-stationary bandits via **γ-decay on Beta posterior parameters**. On each pull of arm i with reward r ∈ [0,1]: `α_i ← γ·α_i + r` and `β_i ← γ·β_i + (1−r)`. Selection is randomized: draw `θ_j ~ Beta(α_j, β_j)` for all arms, pick `argmax_j θ_j`. The γ-decay ensures older observations have diminishing influence — structurally analogous to D-UCB's discount but applied to the Beta posterior. Key advantage over D-UCB: **fewer hyperparameters** (just γ; no ξ or B to tune). Theoretical guarantees: O(T^(2/3)) regret under switching bandits.

**Important attribution note**: Perplexity cited this paper as "Li, K. et al." — the correct author order is **Lei Sun, Ke Li** (Sun is first author).

### Thesis Relevance
**DEFAULT BANDIT STRATEGY for main experiments.** DYTS is preferred over D-UCB as default because: (1) only one hyperparameter (γ), making it more reproducible; (2) Thompson sampling empirically outperforms UCB-family algorithms in sparse Bernoulli-like reward regimes (as documented by Chapelle & Li 2011, Paper 39), which matches Topic B's empirical pattern (6/8 mutators generation-inert, sparse wins); (3) the Beta posterior's width provides implicit exploration without a tuned exploration constant.

The DYTS update is also more numerically stable than maintaining discounted counts — the Beta parameters stay in a natural range without risk of near-zero denominators.

**Cite in**: Methodology (DYTS as default bandit strategy), Pool/Bandit section.

### Implementation Status

| Component | Status | Notes |
|---|---|---|
| DYTS algorithm | ❌ **Planned** | Default strategy for main experiments |
| γ-decay on Beta posterior | ❌ **Planned** | `α_i ← γ·α_i + r; β_i ← γ·β_i + (1−r)` |
| Thompson sampling selection | ❌ **Planned** | `argmax_j Beta(α_j, β_j)` sample per step |
| `BanditStrategy` abstraction | ❌ **Planned** | Swappable backend: `ucb1` / `ducb` / `dyts` |
| γ hyperparameter default | ❌ **Planned** | Start at 0.95; sweep {0.9, 0.95, 0.99} in comparison runs |

---

## Paper 37 — CyberSecEval 2: A Wide-Ranging Cybersecurity Evaluation Suite for Large Language Models
**ArXiv:** `2404.13161`
**Authors:** Manish Bhatt, Sahana Chennabasappa, Yue Li, Cyrus Nikolaidis, Daniel Song, Shengye Wan, Faisal Mustafa, Glenn Hegeman, Sam Handler, Elie Assy, Aleksandr Volkov, Lucia Pobar — Meta AI, April 2024

### Summary
CyberSecEval v2 expands the original v1 benchmark with five evaluation domains:
1. **Insecure Code Generation** — given a code comment describing a function, does the LLM generate secure code? 2,000 prompts across C, C++, Python, Java covering MITRE Top 25 CWE vulnerabilities.
2. **Cybersecurity Knowledge** — multiple-choice questions on vulnerability types.
3. **Vulnerability Identification** — given code + a specific CWE, identify if the vulnerability is present.
4. **Prompt Injection** — whether models can be manipulated via adversarial instructions.
5. **Cyberattack Helpfulness** — does the model assist with offensive security actions?

The insecure-code-generation evaluation (domain 1) is the thesis's primary use case. The dataset is hosted as `walledai/CyberSecEval` on HuggingFace with `instruct` config, containing the prompt texts and CWE metadata. Python and Java are the two programmatic languages included.

### Thesis Relevance
**PRIMARY BENCHMARK CITATION.** The thesis's `pipeline_breakdown/rule_retrieval_mapping_local.py` loads `load_dataset("walledai/CyberSecEval", "instruct")` — this is CyberSecEval **v2**, not v1. This was a version error in Perplexity's analysis (which cited arXiv:2312.04724, the v1 paper). The correct citation is Bhatt et al. 2024 (arXiv:2404.13161).

The CWE metadata in CyberSecEval v2 serves as the **retrieval join key** between test cases and CodeGuard rules (not as a stratification axis for reporting). Reporting stratification is by programming language (Python vs. Java), not by CWE subdivision (which is retired from the design per Thread 6 decision).

**Cite in**: Methodology (dataset description), Evaluation (primary benchmark); the citation must pin to v2 (arXiv:2404.13161), not v1.

### Implementation Status

| Component | Status | Notes |
|---|---|---|
| `walledai/CyberSecEval` (v2) | ✅ Already used in pipeline | `pipeline_breakdown/rule_retrieval_mapping_local.py` |
| Insecure-code-generation subset | ✅ Active use case | Python + Java |
| CWE as retrieval join key | ✅ Kept | Free natural join between test cases and rules |
| CWE as reporting stratification axis | ❌ Retired | Per Thread 6 decision; language replaces CWE for reporting |
| Version-correct citation (v2, 2024) | ✅ Corrected | Perplexity incorrectly cited v1 (2023) |

---

## Paper 38 — LLMSecEval: A Dataset of Natural Language Prompts for Security Evaluations
**ArXiv:** `2303.09384`
**Authors:** Catherine Tony, Markus Mutas, Nicolás E. Díaz Ferreyra, Riccardo Scandariato — MSR 2023 Data and Tool Showcase Track

### Summary
LLMSecEval provides 150 natural-language prompts for evaluating security-aware code generation, each mapped to one of the MITRE Top 25 CWE vulnerabilities. Unlike CyberSecEval's code-comment style, LLMSecEval uses descriptive natural-language task descriptions ("Write a Python function that accepts user input and saves it to a database"). Each prompt includes a **secure reference implementation** annotated by security experts. Supports both Python and other languages; Top-25 CWE coverage provides systematic vulnerability-class diversity.

### Thesis Relevance
**CROSS-CHECK DATASET for robustness experiments.** Thread 6 decision: run the main optimizer on CyberSecEval v2 (primary), then run a cross-check on LLMSecEval to verify that the best-found mutated rules generalize across dataset styles. The two datasets differ in prompt authorship style (machine-generated code comments vs. human-authored NL descriptions) and benchmark scale (2000 prompts vs. 150), making them a complementary pair.

Pipeline impact: LLMSecEval requires an ingestion adapter (~3–4 hours) to convert its NL prompt format to the pipeline's `TestCase` format. Wall-time cost: 1 SLURM submission for the cross-check run.

**Cite in**: Methodology (multi-dataset evaluation design), Evaluation (cross-check experiment).

### Implementation Status

| Component | Status | Notes |
|---|---|---|
| LLMSecEval dataset | ❌ **Planned** | Cross-check experiment; ~3–4h ingestion adapter |
| LLMSecEval → TestCase format adapter | ❌ **Planned** | Convert NL prompts to pipeline format |
| Cross-check SLURM run | ❌ **Planned** | 1 submission, ~1–2h wall time |
| Secure reference implementations | ❌ Not used | Available for future structural analysis |

---

---

# Papers 39–40 (optional additions from Perplexity deep-research pass)

---

## Paper 39 — An Empirical Evaluation of Thompson Sampling *(optional)*
**Venue:** Advances in Neural Information Processing Systems (NeurIPS), 2011
**Authors:** Olivier Chapelle, Liheng Li

### Summary
Large-scale empirical study comparing Thompson sampling against UCB-family algorithms across diverse bandit scenarios. Key finding: **Thompson sampling outperforms UCB1 and LinUCB in sparse-reward regimes** — when most arms return reward 0 most of the time, the Beta posterior's adaptive width provides better exploration than the fixed UCB bonus. Also shows Thompson sampling is more robust to reward distribution mismatch (performance degrades less if the true distribution differs from the assumed Beta model). Results consistently favor Thompson sampling across advertising, web search, and synthetic benchmarks.

### Thesis Relevance
*(Optional: cite if DYTS empirical justification needs strengthening.)* The Thread 4 decision chooses DYTS as the default bandit strategy partly because of Topic B's sparse reward regime (6/8 mutators generation-inert). Chapelle & Li provide the canonical empirical citation for "Thompson sampling beats UCB in sparse-reward settings." This is supporting evidence for the DYTS choice. If reviewers question why DYTS is default over D-UCB, this paper provides the empirical grounding.

**Cite in** *(optional)*: Methodology (DYTS as default over D-UCB; sparse-reward regime argument).

### Implementation Status

| Component | Status | Notes |
|---|---|---|
| Thompson sampling (DYTS) as default | ❌ **Planned** (via Paper 36 DYTS) | Chapelle & Li provides empirical basis |
| UCB1 as baseline | ✅ Implemented | Comparison baseline per this paper |

---

## Paper 40 — SecurityEval: A Manually-Curated Benchmark Dataset for Evaluating the Security of GitHub Copilot's Code Contributions *(optional)*
**Venue:** International Workshop on Trustworthy Software, co-located with MSR-APSEC 2022
**Authors:** Mohammed Latif Siddiq, Joanna C. Santos

### Summary
SecurityEval provides 121 prompts (Python) covering 75 distinct CWE types, each with a prompt-plus-insecure-stub asking a coding assistant to complete the function. Each prompt is manually designed to elicit code in a context where the insecure pattern is plausible. The dataset is designed as a rigorous manual curation against popular LLM-based coding tools (GitHub Copilot and others). Includes both positive cases (completions that ARE secure) and negative cases (completions that are NOT secure).

### Thesis Relevance
*(Optional: use as third robustness cross-check if both CyberSecEval v2 and LLMSecEval cross-checks are run.)* The three-dataset experiment design from Thread 6 is: CyberSecEval v2 (primary) → LLMSecEval (cross-check 1) → SecurityEval (cross-check 2, optional). SecurityEval's Python-only focus and manual curation style provides a third different dataset archetype. The smaller size (121 prompts) makes it low-cost to add to an LLMSecEval cross-check run.

**Cite in** *(optional)*: Methodology (multi-dataset robustness evaluation).

### Implementation Status

| Component | Status | Notes |
|---|---|---|
| SecurityEval as third cross-check | ❌ Optional | Only if CyberSecEval v2 + LLMSecEval cross-checks are insufficient |
| Python-only subset ingestion | ❌ Optional | Simpler than LLMSecEval (Python only) |

---

## Paper 41 — Automated Repair of Feature Interaction Failures in Automated Driving Systems (ARIEL)
**File:** `3395363.3397386.pdf`
**Venue:** ISSTA 2020
**Authors:** Ben Abdessalem, Panichella, Nejati, Briand, Stifter

### Summary
ARIEL is a search-based automated program repair technique for integration rules in Automated Driving Systems (ADS). Integration rules arbitrate which feature (Auto Cruise Control, Pedestrian Protection, etc.) controls the vehicle at each time step; faults manifest as safety-requirement violations under simulation-based test cases. The algorithm is a **(1+1) Evolutionary Algorithm with a many-objective archive** — each objective tracks the worst-case severity of one safety requirement across the test suite. Single-state was chosen specifically because each test case is a simulation that runs the ADS through 1200 time-steps and takes minutes; population-based GP "becomes too expensive (in the order of hours)" per generation. Each iteration: (1) sample one parent patch from the archive, (2) apply fault localization to pick a faulty statement (Tarantula-derived suspiciousness, weighted by failure severity), (3) generate offspring by applying multiple mutations with probability `0.5^counter`, (4) evaluate offspring on full test suite, (5) admit to archive if non-dominated. Mutation operators are domain-specific: `modify` (change a threshold or relational operator in a precondition) and `shift` (reorder rules in the decision tree). The archive is bounded at `2 × k` entries (k = number of safety requirements) with overflow eviction by **aggregated fitness D = Σ Ω_i** — the entry with the lowest sum of objective values is dropped. A **stagnation-restart** counter triggers archive reset to the original faulty rule-set after `h = 8` generations without an admission (h chosen by preliminary experiments). Evaluated on two industrial ADS systems within a 16-hour wall-time budget: ARIEL repairs all faults in 5 hours (AutoDrive1, 4 failing test cases) and 11 hours (AutoDrive2, 2 failing test cases) on average over 20 runs, outperforming GP and Random-Search baselines with statistical significance (Wilcoxon p<0.05, large effect sizes).

### Thesis Relevance
This is the **primary algorithmic precedent for our optimizer**. ARIEL's (1+1) EA + many-objective archive is the exact structure the thesis adopts, with one critical inversion: ARIEL *repairs* faulty rules so safety tests pass; we *mutate* CodeGuard security rules so the LLM produces code that fails more Semgrep checks. Same algorithmic class, opposite objective sign — the LLM under test is our "system under test", the rule text is our "patch", and Semgrep findings count is our "severity-of-failure" objective inverted.

Five direct mappings into our codebase:

1. **(1+1) EA selected over population-based methods because evaluations are expensive.** Their argument transfers verbatim: a population of 40 patches at minutes each per evaluation becomes hours per generation. Our equivalent: 25 prompts × LLM generation + Semgrep batch is similarly expensive, justifying single-state over NSGA-II / SPEA2 / GP.

2. **Multi-objectivization to escape local optima.** ARIEL formalizes the same intuition we use for the 3-objective archive: a partial patch that fixes one safety requirement is worth keeping even if it doesn't yet fix others — the archive preserves diversity of partial solutions. Our (f1, f2, f3) decomposition serves the same role: a mutation that improves only on breadth (f2) or depth (f3) is admitted even when f1 doesn't move.

3. **Archive cap = 2×k with eviction by D = Σ Ω_i.** ARIEL caps the archive at twice the number of safety requirements; we cap at 6 per rule. ARIEL evicts by the sum of all objective values when the archive overflows; we implement the same in [pareto_archive.py:307-313](src/optimizer/pareto_archive.py#L307-L313) via `score_sum() = f1 + f2 + f3` with tie-breaking by `iteration_added`.

4. **Stagnation restart with h=8.** ARIEL's restart threshold was picked by preliminary experiments at h=8; ours matches exactly at `restart_h=8`. Both algorithms reset to the original (unmutated) rule on restart.

5. **Roulette-Wheel mutator selection weighted by suspiciousness.** ARIEL biases mutator sampling toward statements with high fault-localization scores. We currently sample uniformly. This is a clean future-work direction — we already collect `mutator_stats[name]['archive_adds']` and have D-UCB / DYTS bandit infrastructure that generalises to this.

The single most important framing for the thesis Approach chapter: **same algorithm, opposite objective direction**. Citing ARIEL grounds our algorithmic conservatism in a well-cited expensive-evaluation precedent, then the inversion (repair → adversarial mutation) becomes the novel contribution.

### Implementation Status

| Component | Status | Notes |
|---|---|---|
| (1+1) EA with single-state evolution | ✅ Implemented | [ea_optimizer.py](src/optimizer/ea_optimizer.py) |
| Per-rule Pareto archive | ✅ Implemented | [pareto_archive.py](src/optimizer/pareto_archive.py) |
| Archive cap with `score_sum` eviction | ✅ Implemented | `cap=6`, eviction by lowest score_sum + youngest iteration_added |
| Stagnation-restart counter `h` | ✅ Implemented | `restart_h=8`, reset to original rule text |
| Multi-objectivization (3 objectives) | ✅ Implemented | f1=semgrep_delta, f2=proportion_divergent, f3=conditional_mean_divergence |
| Roulette-Wheel mutator selection | ❌ Future work | Currently uniform; bd-coq tracks this extension |
| Fault localization | ❌ Not applicable | We have no failing/passing test partition in the ARIEL sense |
| Modify / Shift operators | ❌ Not applicable | Our domain is NLP rule text, not decision-tree integration rules |
| Patch minimization | ❌ Future work | Greedy removal of mutations that aren't needed for the fitness gain |

---

## Paper 42 — A Survey on Handling Computationally Expensive Multiobjective Optimization Problems with Evolutionary Algorithms
**File:** `Chugh_Survey_Expensive_Multiobjective_Optimization.pdf`
**Authors:** Chugh, Sindhya, Hakanen, Miettinen
**Year:** 2016 (45 algorithms surveyed, 2008–2016)

### Summary
Comprehensive survey of expensive multiobjective optimization with EAs. Establishes the field's taxonomy of approximation strategies — **problem approximation** (simplify the original problem, e.g. 3D Navier-Stokes → 2D Euler), **function approximation** (replace expensive objective functions with a surrogate / metamodel), and **fitness approximation** (replace the fitness *concept* — predict rank, dominance class, or hypervolume contribution rather than objective values). Most surveyed algorithms use function approximation; Kriging dominates the metamodel choice (used by ParEGO, SMS-EGO, MOEA/D-EGO, K-RVEA) due to its uncertainty estimates. The survey provides a unified 10-step function-approximation framework: an initial sampling stage (~11n-1 points) followed by a surrogate-managed evolution stage that interleaves metamodel-guided evaluation with selective re-evaluation on the real expensive function (called *evolution control*, either fixed or adaptive). Six core challenges are catalogued: choice of metamodel, training time, when to update, how to update, ensemble management, and constraint handling. The survey identifies six promising elements (ensemble metamodels, hybrid local-global search, combined approximation types) and seven persistent issues (objective-space dimensionality limits at three, neglected training time in reported wall-clock, constraint handling weakly addressed). Function-evaluation budgets across the 45 surveyed algorithms range from 50 to 30,000.

### Thesis Relevance
This is the **background / framing anchor** for the Background chapter. Unlike Paper 41 (ARIEL), no algorithm is directly adopted — the thesis applies an expensive multiobjective EA to a domain (rule-text mutation under LLM-based code generation) that the survey does not cover. But the survey supplies the field's formal vocabulary, the canonical algorithms to namedrop in Related Work, and the empirical evidence that our ~5000 Semgrep-call budget sits firmly in the upper-expensive band.

Two things to lift directly:

1. **Function-evaluation budget framing.** "Budgets surveyed range 50–30,000." Our budget (200 iterations × 25 prompts = 5000 expensive Semgrep evaluations, plus ~200 LLM mutation calls) places us in the upper-expensive band, which empirically justifies our conservative (1+1) EA choice over population-based GP / NSGA-II.

2. **Fixed-vs-adaptive evolution control distinction.** The survey defines fixed evolution control (deterministic schedule of when to query the expensive function) vs. adaptive (decision conditional on metamodel accuracy). We are fixed (every accepted mutation pays the real Semgrep cost). Naming the dichotomy makes our design choice legible in the thesis.

Three future-work hooks the survey unlocks, all genuinely distinct from the current pipeline:

- **Surrogate on Semgrep fitness.** Train a regressor over (rule_text_embedding, mutator_id, depth) → expected Δf1. Section 3.3 of the survey gives the framework; Kriging (uncertainty-bearing) or RBF (cheaper) are the obvious starting points. Survey warning: training time is "usually neglected when reporting results" but can dominate if the metamodel is heavy — relevant if we ever try this.
- **Fitness *classification* rather than function approximation.** Pareto-SVM (Loshchilov 2010, surveyed §3.7) classifies candidates as "will improve archive / won't" without computing the real fitness. For us: a learned `(rule_text, mutator, parent_entry) → P(archive_add)` predictor would let us screen out mutations cheaply.
- **Weighted mutator ensemble.** The survey discusses metamodel ensembles in §3.5; the analogue for us is the 8-mutator pool we already maintain. Weighted-by-past-success sampling is the natural extension and connects directly to the ARIEL roulette-wheel point — both papers converge on weighted operator selection as the unimplemented improvement.

### Implementation Status

| Component | Status | Notes |
|---|---|---|
| Expensive-MOP vocabulary (Pareto front, dominance, ideal/nadir) | ✅ Implicit | Used informally; survey provides formal citations for thesis |
| Function approximation / surrogate on Semgrep | ❌ Future work | Background unlocks; not in scope this thesis |
| Fixed evolution control | ✅ Implemented | Every accepted mutation pays real Semgrep cost |
| Pareto-SVM-style classification screening | ❌ Future work | Cheaper alternative to surrogate fitness |
| Weighted-by-success mutator selection | ❌ Future work | Connects to ARIEL roulette-wheel; bd-coq tracks |
| 3-objective archive within field-typical bounds | ✅ Aligned | Survey notes most algorithms cap at 3 objectives; ours has exactly 3 |

---

---

# Updated Gap Analysis (Perplexity deep-research pass, 2026-04-24)

## Summary of changes from Perplexity literature pass

| Gap (from IMPLEMENTATION_LITERATURE_MAPPING.md) | Before | After | Resolution |
|---|---|---|---|
| §1.6 — Scalar vs Pareto | ❌ | ✅ | Lexicographic (Miettinen P28, Chen & Li P26, ATheNA P21) |
| §4.5 — SBERT model choice | 🟡 | ✅ | MTEB (P31) + Reimers & Gurevych (P32) justify `all-mpnet-base-v2` |
| §4.11 — `_SECURITY_KEYWORDS` frozenset | ❌ | ✅ | Corpus-derived lexicon (Papers 20, 23 + MITRE CWE standard) |
| §5.6 — composite weights α/β/γ | ❌ | ELIMINATED | Weighted sum dropped entirely; lexicographic replaces it |
| §5.7 — rule_div as β fitness term | ❌ | ELIMINATED | `rule_div` demoted to SBERT quality gate (≥ 0.75); not a fitness term |
| §5.9 — NL-SBERT-on-code for γ | ❌ | ✅ | CodeBLEU (P29) replaces NL-SBERT for `code_divergence` |
| §6.5 — UCB1 c = 1.41 | ❌ | ✅ | Auer et al. 2002 (P34) is the canonical source of c = √2 |
| §6.6 — clipping negative rewards | ❌ | ✅ | Auto-resolved by 3-level reward {0, 0.5, 1.0} in lexicographic scheme |
| §6.7 — GREEDY_BATCH strategy | ❌ | 🟡 | Paper 17 (SoS) crossover is closest analogue; partial support |
| §8.3 — CyberSecEval benchmark | 🟡 | ✅ | Bhatt et al. 2024 v2 (P37) — version corrected |
| §8.5 — CWE-based stratification | ❌ | ELIMINATED | Reporting-time CWE stratification dropped; language replaces it |

## New tensions introduced by this pass

### Lexicographic acceptance introduces "code_div only" as tie-breaker
Rule_div (SBERT ≥ 0.75) is now only a quality gate. Code_div computed via CodeBLEU is the secondary fitness signal. This means: if a mutation changes the rule text but the LLM generates structurally identical code (generation-inert mutations from Topic B), the secondary acceptance criterion will also reject. This is correct behavior — it means the bandit learns not to waste iterations on generation-inert mutators.

### CodeBLEU language dispatch requires pipeline metadata
`calc_codebleu([ref], [hyp], lang="java")` needs the language tag from each test case. CyberSecEval v2 metadata includes this — confirmed via the existing pipeline code. No implementation blocker, but the language field must be propagated through the `TestCase` → `EvaluationResult` → `CompositeFitnessEvaluator` path.

### DYTS γ hyperparameter is untested
The γ parameter in DYTS (and D-UCB) controls the effective memory window. No prior paper validates a specific γ for the thesis's compounding-mutation regime. The implementation plan documents a sweep over {0.9, 0.95, 0.99} as part of the comparison run between UCB1 / D-UCB / DYTS.
