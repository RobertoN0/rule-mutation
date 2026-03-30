# Thesis Relevance per Paper
*Quick-reference: how each paper connects to the CodeGuard SBST project*
*Updated 2026-03-30*

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
