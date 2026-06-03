# Thesis Relevance per Paper
*Quick-reference: how each paper connects to the CodeGuard SBST project*
*Updated 2026-04-24 (Papers 26–38 from Perplexity deep-research pass; Papers 39–40 optional)*

---

## Paper 1 — Metamorphic Testing of LLMs for NLP (191-MR Catalog)
**Relevance: Foundational vocabulary**

Establishes the formal definition of Metamorphic Relations and the taxonomy all nine mutators descend from. The secondary oracle problem (semantic equivalence is hard to verify) directly motivates the `MutationQualityValidator`. The key novel contribution of the thesis vs. this paper: the catalog tests LLMs *as the system under test* (NLP task testing); the thesis tests security rules that *guide* the LLM — a novel elevation of the MT paradigm to instruction-level testing.

**Cite in**: Introduction (MT definition), Methodology (MR taxonomy), Related Work.

---

## Paper 2 — LLMORPH: Automated Metamorphic Testing of LLMs
**Relevance: Direct source of 4 mutators**

`NegationInjectionMutator` (MR-48/76), `SectionReorderMutator` (MR-19/107), `ParaphraseMutator` (MR-51), and `VoiceChangeMutator` all trace directly to named MR identifiers in this paper. The LLM-based few-shot prompting implementation strategy matches how these mutators are built. The recency bias documented here provides theoretical grounding for the `degrade` mode of `SectionReorderMutator` — moving security-critical sections to the end exploits a known architectural bias in autoregressive LLMs.

**Cite in**: Methodology (per-mutator justification), each mutator's docstring.

---

## Paper 3 — Search-Based Selection of MRs (Hyun et al. 2025)
**Relevance: Highest-priority extensions**

Two extensions come from this paper:
1. **Combinatorial MR chaining** (Priority 1): applying 2–3 mutators per hill-climbing step, which Paper 3 shows is the primary source of incremental failure gain over single-MR application
2. **Composite fitness function** (Priority 2): `Context_ASR × PerturbationQuality` motivates the EFM metric (`Semgrep_increase × SBERT_similarity`)

Also validates the current mutator selection: `SynonymReplacement` and `AddRandomWord` are confirmed silver bullets. The MOEA/D algorithm result justifies why SBST outperforms random MR selection — providing external validation for the hill-climbing approach.

**Cite in**: Methodology (SBST design, silver bullet mutator choice), Future Work (MOEA/D).

---

## Paper 4 — AUGMENT Framework
**Relevance: Source of the quality validation architecture**

The `MutationQualityValidator` is a direct implementation of AUGMENT's three-criteria framework (instruction adherence, SBERT similarity, perplexity ratio), extended with security keyword retention. The thesis's SBERT threshold (≥ 0.80) is slightly stricter than AUGMENT's (≥ 0.75). The `VoiceChangeMutator` and `SynonymReplacementMutator` are also AUGMENT-attributed. The critical departure: AUGMENT tests *user fairness* (whether LLMs treat different speakers equally); the thesis uses the same quality framework to test *security instruction robustness*.

**Cite in**: Methodology (validator design), each of the three quality criteria, `VoiceChangeMutator`.

---

## Paper 5 — Instruction-Following Dimension (Heo et al. ICLR 2025)
**Relevance: Mechanistic justification for why mutation works**

Proves via linear probing that instruction-following success is predictable from a single linear direction in the LLM's input embedding space, and that this direction is most influenced by *prompt phrasing* (not task difficulty). This provides the deepest mechanistic justification for why syntax-preserving semantic rewrites are principled attacks on instruction adherence — not noise. Cite in the motivation section to establish that brittleness is an architectural property of LLMs, not an edge case.

**Future experiment**: use the instruction-following dimension as a proxy fitness signal to rank candidate mutations before Semgrep evaluation.

**Cite in**: Introduction/Motivation (why phrasing mutations work), Discussion (interpreting per-mutator results).

---

## Paper 6 — Latent Adversarial Paraphrasing (LAP)
**Relevance: Calibration of quality threshold and adversarial paraphrase selection**

Provides empirical calibration for the SBERT threshold: perplexity ratio ≤ 2.0 implies SBERT ≥ 0.80 in >90% of cases, validating the perplexity criterion as informational (consistent with the existing SBERT gate). Also suggests a near-term improvement to `ParaphraseMutator`: among all paraphrase candidates that pass the quality gate, prefer the one with the *largest* embedding distance from the original (most adversarial). This does not require gradient access — only comparing candidate embeddings.

**Cite in**: Methodology (quality threshold choice), Future Work (adversarial candidate selection).

---

## Paper 7 — Mixture of Formats (MOF)
**Relevance: Untapped mutation axis — structural formatting**

Identifies that non-semantic Markdown formatting choices (bullet style, header depth, emphasis) cause 10–20% accuracy variance in LLMs. CodeGuard rules contain all of these elements. A `FormatStyleMutator` following the MOF principle would add a complementary mutation axis to the existing prose-level mutators. Lower priority than combinatorial chaining and EFM — applicable once existing MRs are validated.

**Cite in**: Future Work (structural mutation extensions).

---

## Paper 8 — Metamorphic Prompt Testing for Code
**Relevance: Structural analogue; validates MT approach for code generation**

Applies the same MT assumption to code generation validation: semantically equivalent prompts should produce functionally equivalent programs. Validates the thesis's core assumption that phrasing variations in instructions should produce consistent code security outcomes. The majority-consensus oracle is not adopted (single-generation design choice), but the structural parallel is cited to situate the thesis within the code-generation MT literature.

**Cite in**: Related Work (MT for code generation, distinguishing thesis approach from output-level MT).

---

## Paper 9 — METAL Framework (Hyun et al. 2023)
**Relevance: EFM metric — the second highest-priority extension**

The EFM metric (`M-ASR × PerturbationQuality`) adapted to the thesis becomes `Semgrep_increase × SBERT_similarity`. This composite metric rewards efficient mutations — those that break model behavior with minimal semantic drift. Also validates the thesis's design choice to focus on sentence-level perturbations (METAL shows they outperform character/word-level for code-generating LLMs).

**Cite in**: Methodology (quality-weighted fitness rationale), Evaluation (per-mutator EFM comparison).

---

## Paper 10 — Tone and Politeness Effects
**Relevance: Evaluation methodology — per-domain reporting**

The key finding is methodological: aggregating results across domains hides significant per-domain effects. The thesis must report results per CWE category and per programming language, not just aggregate Semgrep counts — otherwise a mutator that dramatically affects C buffer-overflow rules but not Python injection rules would appear ineffective in aggregate. Also provides indirect support for `FluffMutator` as a register-shift mutation exploiting pragmatic sensitivity.

**Cite in**: Evaluation (justification for per-CWE breakdown), Discussion (interpreting aggregate vs. per-category results).

---

## Paper 11 — STELLAR
**Relevance: Architectural inspiration for future structured search**

STELLAR's 4.3× improvement over random testing (via feature discretization + NSGA-II) motivates eventually moving from hill climbing to multi-objective structured search over a discretized rule mutation space. For the thesis scale, hill climbing is sufficient, but STELLAR provides the architectural vision for a next-generation pipeline. The nine current mutators are already the implicit discrete operator dimension; STELLAR formalizes the full product space.

**Cite in**: Future Work (multi-objective structured search over discrete rule features).

---

## Paper 12 — MRSQLGen (Hallucination Detection in NL2SQL)
**Relevance: HKB concept for failure-mode-targeted mutations**

The Hallucination Knowledge Base (HKB) — mapping known failure modes to targeted mutations — is more principled than generic MR selection. For the thesis, a **Security Rule Brittleness Knowledge Base (SRBKB)** could map CWE types to the mutators most likely to expose each: injection vulnerabilities → `VerbWeakeningMutator`, buffer overflows → `SectionReorderMutator(mode="degrade")`, etc. Medium priority for future work.

**Cite in**: Future Work (targeted mutation strategy per vulnerability type).

---

## Paper 13 — PERSIST (Behavioral Instability)
**Relevance: Contextual validation + evaluation methodology warning**

Provides external evidence that LLM behavioral instability persists even at 400B+ scale under paraphrase — supporting the thesis's core assumption. The CoT-amplifies-variability finding is relevant context when interpreting `ParaphraseMutator` results (temperature=0.6 is used for generation). The aggregation-of-instability finding reinforces per-CWE reporting. Multi-run variance measurement is explicitly not implemented — single-generation at temperature=0 is the design choice.

**Cite in**: Motivation (LLM instability is fundamental), Methodology (temperature=0 justification).

---

## Paper 14 — CAIBench
**Relevance: Motivation — capability gap in cybersecurity execution**

Documents the "capability gap": frontier models achieve ~70% on security knowledge questions but fall to 20–40% on operational multi-step tasks. This externally validates the thesis's premise that rule robustness matters — the model "knows" the security concepts encoded in CodeGuard rules, but small phrasing perturbations can break operational application of that knowledge. Also reinforces the need for multi-domain evaluation (per CWE, per language).

**Cite in**: Introduction (motivation for rule robustness), Related Work (cybersecurity LLM evaluation).

---

## Paper 15 — Prompt Repetition
**Relevance: Low — baseline control experiment only**

Prompt repetition strengthens rule adherence; the thesis explores degradation. The only thesis-relevant use: a validity control experiment — does `mutated_rule + mutated_rule` recover the Semgrep performance of `original_rule`? If yes, the mutation's effect is an attention-window artifact rather than genuine phrasing brittleness. Not in scope for the main pipeline.

**Cite in**: Discussion (if validity control experiment is performed).

---

## Paper 16 — DrHall (Hallucination Detection via MT)
**Relevance: Out of scope; validates instability assumption**

Prompt-level QMR/AMR mutations are explicitly excluded (prompts are not changed). The instability-of-wrong-answers assumption (hallucinated answers are brittle across MRs) exactly mirrors the thesis's brittleness hypothesis. DrHall's two-type MR taxonomy (Question MRs vs. Answer MRs) provides a useful conceptual frame for situating the thesis's Rule MRs (RMRs) as a third category in the MT-for-LLMs design space.

**Cite in**: Related Work (MT frameworks for LLM output validation, distinguishing rule-level from prompt/output-level MT).

---

## Paper 17 — Survival of the Safest (SoS)
**Relevance: Multi-objective prompt evolution — validates EFM approach**

Demonstrates that interleaved multi-objective evolution (alternating between security and performance optimization with Pareto-optimal selection) outperforms single-objective prompt optimization. The crossover operator (blending a high-fitness prompt with a high-quality prompt) directly addresses the quality–effectiveness tension in the hill climber. The feedback mutation concept (domain-specific agents analyze failures and suggest improvements) is a sophisticated version of the Semgrep-feedback loop.

**Cite in**: Related Work (multi-objective prompt optimization), Methodology (justification for composite EFM fitness).

---

## Paper 18 — Artemis: Automated Optimization of LLM-based Agents
**Relevance: Hierarchical evaluation strategy**

Validates that LLM-ensemble mutations (using a secondary LLM to perform intelligent perturbations) outperform random mutations — the thesis already does this for 4 of 9 mutators. The actionable contribution is the hierarchical evaluation: cheap filters (SBERT similarity, LLM-as-judge) before expensive validation (Semgrep). This could reduce the number of full generation+Semgrep evaluations needed per hill-climbing step.

**Cite in**: Future Work (hierarchical evaluation to reduce computational cost).

---

## Paper 19 — SPRIG: System Prompt Optimization
**Relevance: Closest structural analogue — UCB-based selection is actionable**

SPRIG optimizes system prompts (the thesis optimizes security rules, which are system prompts). The structural parallel is strong: seed corpus → mutation operations → fitness-guided selection. The **UCB-based pruning** for component/mutator selection is a directly actionable improvement: track per-mutator success rates and use UCB scores to prioritize effective mutators over underperforming ones. Simple change to `hill_climber.py`, no architectural overhaul.

**Cite in**: Related Work (system prompt optimization), Methodology (if UCB selection is implemented).

---

## Paper 20 — SCAFFOLD-CEGIS
**Relevance: CRITICAL threat to validity — Semgrep-only fitness is empirically insufficient**

Proves that iterative optimization against SAST tools teaches LLMs to structurally evade detection patterns rather than produce genuinely secure code. SAST gating *increases* latent security degradation (12.5% → 20.8%). The safe-zone contract is a simplified version of semantic anchoring. The thesis MUST cite this paper in Threats to Validity and acknowledge that the Semgrep-only fitness function is a known limitation.

**Cite in**: Threats to Validity (Semgrep-only limitation), Methodology (safe-zone contract as anchoring).

---

## Paper 21 — ATheNA: Hybrid Fitness in SBST
**Relevance: Formal framework for combining automated + domain-knowledge fitness**

Provides the formal SBST citation for why combining `f_AT` (automated Semgrep fitness) with `f_MAN` (manual SBERT similarity penalty, security keyword retention) is principled. The EFM metric `Semgrep_increase × SBERT_similarity` is exactly a hybrid `f = f_AT × f_MAN` composition. ATheNA validates that domain-knowledge fitness consistently improves SBST effectiveness without significant overhead.

**Cite in**: Methodology (justification for hybrid/composite fitness function).

---

## Paper 22 — CodeScore
**Relevance: Future dual-objective evaluation (security + functional correctness)**

CodeScore's NL-only modality could evaluate whether mutated rules still produce functionally valid code. Currently not needed — Semgrep implicitly handles this (syntactically broken code produces parsing errors, not security findings). Cite as future work for a dual-objective evaluation combining security compliance with functional correctness.

**Cite in**: Future Work (if dual-objective evaluation is proposed).

---

## Paper 23 — MST-wi: Metamorphic Security Testing for Web Systems
**Relevance: Low — different domain, conceptual parallel only**

The 76 MRs and 10 structural patterns operate on HTTP requests, not NLP prompts. The relational oracle concept (equality/subset checking) is already implicit in the hill climber. Cite for completeness in the security-domain MT literature.

**Cite in**: Related Work (security-focused MT approaches).

---

## Paper 24 — SAST-MT: Testing SAST Tools via Metamorphic Testing
**Relevance: Second threat to validity — SAST tools have systematic blind spots**

Demonstrates that CodeQL has 228 false negatives in ~30K programs. Combined with SCAFFOLD-CEGIS (Paper 20), this forms a two-pronged challenge: (1) optimization against SAST teaches evasion, and (2) SAST itself has blind spots. The thesis should acknowledge both. Mitigation: the *relative* Semgrep delta (change between original and mutated rule) is more robust than absolute counts.

**Cite in**: Threats to Validity (SAST reliability), Future Work (cross-tool validation with CodeQL).

---

## Paper 25 — zkCraft: LLM as Zero-Shot Mutation Pattern Oracle
**Relevance: Low — ZK circuit domain, but Pattern-Oracle concept is interesting**

The Pattern-Oracle architecture (feed failure traces back to LLM to generate targeted follow-up mutations) is a sophisticated version of feedback-guided mutation. For the thesis: when a mutator causes a large Semgrep delta on a specific CWE, feed the report back to generate more targeted mutations. Related to SoS feedback mutation (Paper 17).

**Cite in**: Future Work (feedback-guided adaptive mutation).

---

---

## Paper 26 — The Weights Can Be Harmful: Revisiting Pareto-Based MOO in SE (Chen & Li, TOSEM 2022)
**Relevance: Critical empirical basis for dropping the weighted composite fitness**

Demonstrates across 14 SE benchmarks that weighted-sum scalarization fails to find Pareto-optimal solutions in 77% of cases due to inability to represent non-convex Pareto front regions. Small weight perturbations (±0.1) frequently change which solution is selected — making results artifact-sensitive. The old composite formula (`1.0·semgrep_delta + 0.3·rule_div + 0.2·code_div`) had exactly this fragility: there was no principled justification for the 0.3/0.2 values, and semgrep and code_div are not symmetric co-equal objectives. This paper provides the empirical citation for why the lexicographic acceptance rule replaces the weighted sum.

**Note on attribution**: Perplexity misattributed this paper to "Wang, S. et al." — the correct authors are **Tao Chen & Miqing Li**.

**Cite in**: Methodology (motivation for dropping weighted composite), Threats to Validity (sensitivity of weighted sums).

---

## Paper 27 — NSGA-II: A Fast and Elitist Multiobjective Genetic Algorithm (Deb et al., IEEE TEVC 2002)
**Relevance: Foundational Pareto reference — cite to explain what the thesis chose NOT to use**

The canonical multi-objective evolutionary algorithm, providing the formal definition of non-dominated sorting, crowding distance, and Pareto front maintenance that papers 3, 11, and 17 all build on. The thesis discusses Pareto-based alternatives (Papers 3, 17) and explains why they were not adopted — NSGA-II is the reference point for those alternatives.

**Cite in**: Methodology (multi-objective alternatives considered); Related Work (when Papers 3/11/17 are discussed and Pareto concepts are needed).

---

## Paper 28 — Nonlinear Multiobjective Optimization (Miettinen, Kluwer 1999)
**Relevance: Canonical theoretical grounding for lexicographic acceptance rule**

The standard reference textbook for MOO theory. Chapter 3.7 formalizes lexicographic ordering as the correct scalarization when objectives have strict asymmetric priority: the primary objective is optimized first; the secondary objective breaks ties only. Proves that lexicographic ordering produces the unique optimal solution under these conditions — it is not an ad-hoc heuristic, but a classical method with theoretical backing. This is the most important citation for the Thread 1 acceptance rule (`delta_s > 0` → accept; `delta_s == 0 AND delta_c > 0` → accept secondary).

**Cite in**: Methodology (lexicographic acceptance rule formal justification, alongside Chen & Li Paper 26 for empirical motivation).

---

## Paper 29 — CodeBLEU: a Method for Automatic Evaluation of Code Synthesis (Ren et al., 2020)
**Relevance: Primary code-divergence metric — closes the NL-SBERT-on-code gap (§5.9)**

Extends BLEU with syntactic AST matching and data-flow graph matching for code evaluation. The four-component metric (n-gram BLEU + keyword-BLEU + AST + data-flow, default weights 0.25 each) is specifically designed to capture structural code differences beyond surface-level token overlap. Implemented in the `k4black/codebleu` PyPI package with first-class support for Python and Java — exactly the two languages the thesis evaluates. The metric replaces `all-mpnet-base-v2` applied to code, which is architecturally mismatched (NL model on code).

**Cite in**: Methodology (code_divergence metric definition), Evaluation (per-language breakdown).

---

## Paper 30 — TSED: Tree-Structured Edit Distance for Code (Song et al., ACL 2024)
**Relevance: Alternative metric considered and rejected — cite in Future Work**

AST edit distance via tree-sitter + APTED. Perplexity claimed TSED beats CodeBLEU, but TSED never benchmarks against CodeBLEU. Rejected in Thread 2 due to: ~100–200 line adapter requirement, limited language support in the paper's evaluation (missing Java), and modest execution-match correlation (0.19 Spearman on Python). The TSED vs. CodeBLEU ablation is a legitimate future-work item.

**Cite in**: Future Work (code-similarity metric alternatives); Threats to Validity (CodeBLEU limitations context).

---

## Paper 31 — MTEB: Massive Text Embedding Benchmark (Muennighoff et al., EACL 2023)
**Relevance: Empirical justification for `all-mpnet-base-v2` as SBERT model — closes §4.5 gap**

MTEB evaluates 33 models across 56 datasets and 8 task types. The critical finding for the thesis: `all-mpnet-base-v2` ranks in the top tier on the **STS (Symmetric Text Similarity) subset** — the task type that matches the validator's rule-similarity computation. MTEB also confirms that `multi-qa-mpnet-base-dot-v1` (Perplexity's recommendation) performs well on asymmetric retrieval but degrades on symmetric STS, making it architecturally incorrect for the thesis's use case. AUGMENT's actual model (`stsb-distilroberta-base-v2`) ranks lower than `all-mpnet-base-v2` on MTEB STS, meaning the thesis's model choice is already stronger than AUGMENT's.

**Cite in**: Methodology (SBERT model selection), Quality Validator section.

---

## Paper 32 — Sentence-BERT: Sentence Embeddings using Siamese BERT-Networks (Reimers & Gurevych, EMNLP 2019)
**Relevance: Foundational reference for all SBERT usage in the thesis pipeline**

The architectural source of the sentence-level embedding approach used throughout. Every call to `compute_sbert_similarity()` in the thesis pipeline is an application of Reimers & Gurevych's siamese network framework. This paper is the missing foundational citation — currently the thesis cites SBERT usage via AUGMENT (Paper 4) and METAL (Paper 9) without citing the originating architecture paper.

**Cite in**: Methodology (SBERT framework introduction); Related Work (sentence embedding foundations).

---

## Paper 33 — SecureBERT 2.0 (Aghaei et al., Cisco AI, 2025)
**Relevance: Domain-specific SBERT alternative for pilot ablation**

ModernBERT-based bi-encoder trained on a cybersecurity rules corpus (5K samples) — stylistically the closest to CodeGuard rules of any published model. 1024-token max sequence length vs. 384 for `all-mpnet-base-v2`, potentially advantageous for long rules. Training uses `MultipleNegativesRankingLoss` with cosine similarity (symmetric-compatible). No published STS benchmark against `all-mpnet-base-v2` — the ablation is the only way to determine if domain specialization helps.

**Cite in**: Methodology (SBERT ablation design), Future Work (domain-specific embedding).

---

## Paper 34 — Finite-time Analysis of the Multiarmed Bandit Problem — UCB1 (Auer, Cesa-Bianchi, Fischer, 2002)
**Relevance: Canonical bandit baseline — provides explicit citation for c = √2 (closes §6.5)**

The foundational UCB1 paper establishing O(log T) regret with exploration bonus `c · √(ln t / n_i)` where `c = √2` is the canonical constant. The thesis uses UCB1 (currently without explicitly citing this paper — only SPRIG referenced it indirectly). Now needed as an explicit citation since UCB1 is the comparison baseline against D-UCB and DYTS.

**Cite in**: Methodology (bandit baseline definition, §6.5 gap resolution).

---

## Paper 35 — On Upper-Confidence Bound Policies for Switching Bandit Problems — D-UCB/SW-UCB (Garivier & Moulines, ALT 2011)
**Relevance: Primary non-stationary bandit citation — D-UCB handles the gradual drift in the hill climber**

Introduces D-UCB (discount-based) for gradual drift and SW-UCB (sliding window) for abrupt changes. D-UCB applies a γ-discount to all historical observations, giving exponentially higher weight to recent pulls — exactly the right property for the hill climber where compounding mutations change the reward distribution gradually. Three hyperparameters (γ, ξ, B) give more tuning flexibility than DYTS. Implemented alongside DYTS as the deterministic non-stationary bandit option.

**Cite in**: Methodology (D-UCB strategy, non-stationary bandit motivation), Pool/Bandit section.

---

## Paper 36 — Dynamic Thompson Sampling for Non-stationary Multi-armed Bandits — DYTS (Sun & Li, 2020)
**Relevance: Default bandit strategy for main experiments — fewer hyperparameters, better for sparse rewards**

DYTS decays Beta posterior parameters by γ at each pull: `α_i ← γ·α_i + r; β_i ← γ·β_i + (1−r)`. Only one hyperparameter (γ) vs. D-UCB's three (γ, ξ, B). Thompson sampling empirically outperforms UCB-family in sparse Bernoulli-like regimes (Chapelle & Li 2011, Paper 39), matching Topic B's observed pattern (6/8 mutators generation-inert, occasional wins).

**Attribution note**: Perplexity cited this as "Li, K. et al." — correct author order is **Lei Sun, Ke Li**.

**Cite in**: Methodology (DYTS as default bandit), Pool/Bandit section.

---

## Paper 37 — CyberSecEval 2: A Wide-Ranging Cybersecurity Evaluation Suite (Bhatt et al., Meta AI, 2024)
**Relevance: Primary benchmark — version-correct citation for what the pipeline actually uses**

The `walledai/CyberSecEval` HuggingFace dataset is CyberSecEval **v2** (arXiv:2404.13161), not v1 (arXiv:2312.04724) as Perplexity implied. CWE metadata serves as the retrieval join key between test cases and rules (kept). Reporting-time CWE stratification is retired; Python + Java language-based stratification replaces it per Thread 6 decision.

**Cite in**: Methodology (benchmark dataset), Evaluation (primary benchmark, version 2404.13161).

---

## Paper 38 — LLMSecEval: A Dataset of Natural Language Prompts for Security Evaluations (Tony et al., MSR 2023)
**Relevance: Cross-check dataset — different prompt style from CyberSecEval for robustness**

150 human-authored NL prompts covering MITRE Top 25 CWEs, with secure reference implementations. Complements CyberSecEval v2 (2000 machine-style code comments). Cross-check experiment: run the best mutated rules found on CyberSecEval v2 through the LLMSecEval benchmark to verify generalization across prompt styles. Requires a ~3–4 hour ingestion adapter.

**Cite in**: Methodology (multi-dataset evaluation design), Evaluation (cross-check experiment).

---

## Paper 39 — An Empirical Evaluation of Thompson Sampling *(optional)* (Chapelle & Li, NeurIPS 2011)
**Relevance: Empirical basis for choosing DYTS over D-UCB as default in sparse-reward regime**

Demonstrates Thompson sampling consistently outperforms UCB1 and LinUCB across sparse-reward scenarios. Provides the canonical citation for "Thompson sampling is better than UCB when most arms return reward 0 most of the time" — directly applicable to Topic B's generation-inert mutator pattern.

**Cite in** *(optional)*: Methodology (DYTS default justification in sparse-reward regime argument).

---

## Paper 40 — SecurityEval: A Manually-Curated Security Benchmark *(optional)* (Siddiq & Santos, MSR-APSEC 2022)
**Relevance: Third cross-check dataset — Python-only, 121 prompts across 75 CWEs**

Manually curated prompts designed to elicit insecure completions from coding assistants. Python-only focus and small size (121 prompts) make it a low-cost third data point if both CyberSecEval v2 and LLMSecEval cross-checks are already running.

**Cite in** *(optional)*: Methodology (multi-dataset robustness evaluation).

---

## Paper 41 — ARIEL: Automated Repair of Feature Interaction Failures in ADS (Ben Abdessalem et al., ISSTA 2020)
**Relevance: Primary algorithmic precedent for the (1+1) EA + Pareto archive design — inverted objective**

The direct precedent for our optimizer. ARIEL's structure is the (1+1) EA + many-objective archive that the thesis adopts wholesale, with one critical inversion: ARIEL *repairs* rules so safety-requirement tests pass, while we *mutate* rules so the LLM produces code that fails more Semgrep checks. Same algorithmic class, opposite objective sign.

Five concrete mappings into our codebase:
1. **(1+1) EA chosen over GP because evaluations are expensive.** Their justification — "evaluating a pool of patches in each iteration/generation becomes too expensive (in the order of hours)" — is the verbatim argument we use in the Approach chapter for not using NSGA-II / SPEA2 / GP. Our evaluation cost (LLM generation + Semgrep batch) puts us in the same regime.
2. **Multi-objectivization to escape local optima.** "Multi-objectivization can lead to better results than classical single-objective approaches… helps store partial patches that individually fix different faults" — direct support for our 3-objective (f1 = semgrep_delta, f2 = proportion_divergent, f3 = conditional_mean_divergence) decomposition. A scalar f1 alone would miss prompts that move on breadth/depth only.
3. **Archive cap 2×k with eviction by aggregated fitness D = Σ Ω_i.** Their cap is `2 × k` where k = number of safety requirements; ours is `cap=6` per rule. Eviction picks the entry with the lowest `D` (sum of all objectives). We implement the same in [pareto_archive.py:307-313](src/optimizer/pareto_archive.py#L307-L313) via `score_sum()`.
4. **Stagnation-restart counter h with reset to original rule.** ARIEL's h=8 was picked by preliminary experiments and matches our `restart_h=8` choice exactly. They also reset the archive to the original faulty rule on stagnation — we reset to the original CodeGuard rule text identically.
5. **Roulette-Wheel mutator selection weighted by suspiciousness.** ARIEL samples mutators with probability proportional to a fault-localization score. We currently sample uniformly. **This is a clean future-work direction** — we already collect per-mutator archive-add counts in `mutator_stats[name]['archive_adds']`, and our existing bandit-strategy machinery (D-UCB / DYTS) naturally generalises to weighted EA mutator selection.

**Cite in**: Approach (primary methodological precedent), Related Work (single-state vs population-based EA in expensive-evaluation domains), Discussion (the repair-vs-mutation inversion as a novel contribution).

---

## Paper 42 — Chugh et al. 2016 — Survey on Expensive Multiobjective Optimization with EAs
**Relevance: Background / framing of the field; supplies vocabulary and future-work hooks**

The taxonomic anchor for the Background chapter. The thesis applies an expensive multiobjective EA to a code-security domain that the survey does not cover, but the survey provides the field's vocabulary (Pareto optimality, ideal/nadir, evolution control, function-vs-fitness approximation), the canonical algorithms to namedrop in Related Work (ParEGO, SMS-EGO, MOEA/D-EGO, K-RVEA), and the empirical context that 5000 expensive evaluations sits firmly in the upper-expensive band of the surveyed budgets.

Two specific things to lift directly into the thesis:
1. **Function-evaluation budget framing.** Surveyed budgets range from 50 to 30,000; ours (~5000 Semgrep calls per run) is upper-expensive. This empirically justifies the algorithmic conservatism of (1+1) EA over population-based methods.
2. **The fixed-vs-adaptive evolution control distinction.** Most surveyed algorithms use fixed evolution control (deterministic schedule of when to query the expensive function); we are also fixed. Naming the dichotomy makes our design choice legible.

Three future-work hooks the survey unlocks (all distinct from current implementation):
- **Surrogate on Semgrep fitness.** Train a regressor on rule-text → expected f1 to skip evaluation for clearly-bad mutations. Section 3.3 of the survey gives the framework; Kriging or RBF are the obvious starting points. Note the survey's warning: training-time cost is "usually neglected" but can dominate when the model is heavy — relevant if we ever try this.
- **Fitness *classification* rather than function approximation.** Pareto-SVM (Loshchilov 2010, surveyed §3.7) classifies candidates as "will improve archive / won't" without evaluating the real fitness. For us this would mean a learned predictor over `(rule_text, mutator, parent_entry) → P(archive_add)`.
- **Weighted ensemble of mutator types.** The survey discusses metamodel ensembles in §3.5; the analogue for us is the 8-mutator pool we already maintain, and the natural extension is weighted-by-past-success sampling (which connects to the ARIEL roulette-wheel point and to our existing D-UCB / DYTS bandit machinery).

**Cite in**: Background (formal definitions of expensive MOP, Pareto front, evolution control), Related Work (Kriging-based MOO survey landscape — ParEGO/SMS-EGO/MOEA/D-EGO/K-RVEA — for completeness), Future Work (surrogate fitness, classification-based screening, weighted mutator selection).

---

---

## Implementation Summary Table

*Updated 2026-04-24. Papers 26–40 added from Perplexity deep-research pass.*

| Paper | Implemented Elements | Priority Extensions |
|---|---|---|
| 1 — MR Catalog | SBERT validation, MR taxonomy (indirect) | — |
| 2 — LLMORPH | 4 mutators: Negation, SectionReorder ×2, Paraphrase, VoiceChange | Formal style, elaboration hedging |
| 3 — Hyun SBST | Hill climbing, SynonymReplacement, AddRandomWord | **Combinatorial chaining (P1), EFM fitness (P2)** |
| 4 — AUGMENT | Full 3-criteria validator, VoiceChange, Synonym | Formal Style mutation |
| 5 — Heo et al. | Used for thesis framing only | Embedding-based proxy fitness (future) |
| 6 — LAP | Perplexity ratio (informational) | Adversarial candidate selection in Paraphrase |
| 7 — MOF | — | FormatStyleMutator (after existing MRs validated) |
| 8 — Code MT | Core assumption | — |
| 9 — METAL | Synonym, AddWord, SectionReorder, Paraphrase, Negation, SBERT | **EFM metric (P2)** |
| 10 — Tone | FluffMutator (indirect) | Per-**language** evaluation reporting (CWE stratification retired) |
| 11 — STELLAR | Implicit discrete operator space | Future: structured multi-objective search |
| 12 — MRSQLGen | Instability assumption | SRBKB targeted mutations (future) |
| 13 — PERSIST | temperature=0 design choice | — (multi-run explicitly out of scope) |
| 14 — CAIBench | Motivation/framing | — |
| 15 — Repetition | — | Optional validity control experiment |
| 16 — DrHall | Instability assumption (conceptual) | — (prompt mutations out of scope) |
| 17 — SoS | GREEDY_BATCH partial analogue (crossover) | Multi-objective fitness interleaving (future) |
| 18 — Artemis | LLM-based mutation (via existing mutators) | Hierarchical evaluation filtering |
| 19 — SPRIG | Hill climbing over system prompts, Rephrase/Swap ops | **UCB-based mutator-only selection (planned)** |
| 20 — SCAFFOLD-CEGIS | Safe-zone contract; corpus lexicon anchoring; quality gate | **Threat to validity: Semgrep-only is insufficient** |
| 21 — ATheNA | Automated fitness (Semgrep as f_AT) | **Hybrid fitness f_AT + f_MAN (lexicographic implements this)** |
| 22 — CodeScore | — | Future: functional correctness counterbalance |
| 23 — MST-wi | Relational oracle (implicit in hill climber) | — (web-security domain, not applicable) |
| 24 — SAST-MT | Semgrep as fitness oracle | **Threat to validity: SAST FP/FN blind spots** |
| 25 — zkCraft | Quality validation of LLM mutations | Future: failure-trace-guided re-mutation |
| 26 — Chen & Li TOSEM | — (empirical basis for design decision) | Cited for dropping weighted composite fitness |
| 27 — NSGA-II | — (reference for rejected alternative) | Future: if MOEA/D is ever implemented |
| 28 — Miettinen textbook | Lexicographic acceptance rule (theoretical) | Cited in Methodology |
| 29 — CodeBLEU | code_divergence metric (planned) | Per-language dispatch in CompositeFitnessEvaluator |
| 30 — TSED | — (rejected alternative) | Future: TSED vs CodeBLEU ablation |
| 31 — MTEB | SBERT model justification (`all-mpnet-base-v2`) | Cited in Methodology |
| 32 — Sentence-BERT | SBERT framework foundation | Cited throughout |
| 33 — SecureBERT 2.0 | — (ablation target) | Pilot ablation: 30–50 rule pairs, ~1 day |
| 34 — UCB1 (Auer et al.) | UCB1 baseline bandit | Explicit citation for c = √2 |
| 35 — D-UCB / SW-UCB | D-UCB strategy (planned) | Implements as `ducb` in BanditStrategy |
| 36 — DYTS (Sun & Li) | DYTS strategy (planned, default) | Implements as `dyts` in BanditStrategy |
| 37 — CyberSecEval 2 | Primary evaluation dataset (already in pipeline) | Version-corrected citation |
| 38 — LLMSecEval | Cross-check dataset (planned) | ~3–4h ingestion adapter |
| 39 — Chapelle & Li *(opt)* | — (empirical basis for DYTS default) | Cited in bandit-choice justification |
| 40 — SecurityEval *(opt)* | — (third cross-check dataset) | Optional; Python-only, 121 prompts |
| 41 — ARIEL | **(1+1) EA + Pareto archive, cap=6, restart_h=8, score_sum eviction** | Roulette-Wheel mutator selection weighted by archive-add rate |
| 42 — Chugh survey | Background framing (expensive MOP vocabulary, evolution control) | Surrogate on Semgrep fitness; Pareto-SVM classification screening; weighted mutator ensemble |
