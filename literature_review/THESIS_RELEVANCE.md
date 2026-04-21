# Thesis Relevance per Paper
*Quick-reference: how each paper connects to the CodeGuard SBST project*
*Updated 2026-04-02 (added Papers 17–25 from Gemini deep-research pass)*

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

## Implementation Summary Table

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
| 10 — Tone | FluffMutator (indirect) | Per-CWE evaluation reporting |
| 11 — STELLAR | Implicit discrete operator space | Future: structured multi-objective search |
| 12 — MRSQLGen | Instability assumption | SRBKB targeted mutations (future) |
| 13 — PERSIST | temperature=0 design choice | — (multi-run explicitly out of scope) |
| 14 — CAIBench | Motivation/framing | — |
| 15 — Repetition | — | Optional validity control experiment |
| 16 — DrHall | Instability assumption (conceptual) | — (prompt mutations out of scope) |
| 17 — SoS | — | Multi-objective fitness interleaving, crossover operator |
| 18 — Artemis | LLM-based mutation (via existing mutators) | Hierarchical evaluation filtering |
| 19 — SPRIG | Hill climbing over system prompts, Rephrase/Swap ops | **UCB-based mutator selection** |
| 20 — SCAFFOLD-CEGIS | Safe-zone contract (rule-level anchoring) | **Threat to validity: Semgrep-only is insufficient** |
| 21 — ATheNA | Automated fitness (Semgrep) | **Hybrid fitness f_AT + f_MAN (supports EFM)** |
| 22 — CodeScore | — | Future: functional correctness counterbalance |
| 23 — MST-wi | Relational oracle (implicit in hill climber) | — (web-security domain, not applicable) |
| 24 — SAST-MT | Semgrep as fitness oracle | **Threat to validity: SAST FP/FN blind spots** |
| 25 — zkCraft | Quality validation of LLM mutations | Future: failure-trace-guided re-mutation |
