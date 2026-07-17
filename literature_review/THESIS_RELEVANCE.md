# Thesis Relevance per Paper
*Quick-reference: how each paper connects to the CodeGuard SBST project.*

---

## Ref C0 — Cisco Project CodeGuard validation study *(PRIMARY REFERENCE — the foundational source for the whole project)*
**Relevance: CRITICAL — the methodology the thesis replicates and extends**

*Grey literature (no peer-reviewed paper exists): Thomas Bartlett, "Can Security Rules Make AI Generated Code Safer? What We Learned From 2,717 Prompts With Project CodeGuard," Cisco Security Blog, 2025-12-09. URL: https://community.cisco.com/t5/security-blogs/can-security-rules-make-ai-generated-code-safer/ba-p/5353605. Local copy: `cisco_codeguard_validation_blog.md`.*

**What Cisco did.** Measured whether giving an AI coding agent explicit Project CodeGuard security rules makes generated code measurably safer. Two otherwise-identical agents (GPT-5, ReAct/LangGraph, "return only code") differing only in tool access — a baseline vs. a CodeGuard agent that can call an MCP server exposing **22 CodeGuard rules**. Paired design: same prompt to both agents, both outputs scanned independently. Static analysis: **Semgrep `p/security-audit`** (+ CodeQL where applicable), **counting only ERROR and WARNING findings**. Three benchmarks — OWASP-style templates (680 prompts, 6 langs), **SecurityEval (121 prompts, 69 CWE)**, **CyberSecEval-instruct (1,916 prompts, 8 langs, 50 CWE)** — 2,717 prompts / 5,434 generations total. Result: findings dropped **415 → 264 (−36.4%)**, every experiment significant at **p < 0.05**; clean-snippet share rose in all three.

**What the thesis inherits (direct methodological parent).**
- The **Semgrep `p/security-audit`** ruleset and the **ERROR+WARNING raw-count** outcome metric (→ the thesis's R3 reporting metric).
- The **datasets**: CyberSecEval-instruct (Paper 37) as primary, SecurityEval (Paper 40) as cross-check.
- The **baseline-vs-rules paired comparison** primitive (the thesis's iteration-0 baseline vs mutated-rule generations).
- **Project CodeGuard rules as the system-under-test** — the artifact the thesis mutates.

**The extension (the thesis's contribution).** Cisco asks *"do rules make code safer?"* and shows that its retrieved CodeGuard rules reduce findings. The thesis treats those rules as a mutable whole-rule-set chromosome and asks whether SBST can find **semantics-preserving repairs that reduce vulnerable generation further**. The primary direction is therefore repair/minimisation (positive f1 means fewer findings than the origin); the retained maximise direction is a secondary robustness experiment, not the main objective.

**Threats-to-validity inheritance.** Cisco's own stated limitations transfer and should be cited: single base model (GPT-5; the thesis uses Qwen2.5-Coder-32B → results may differ by model), Semgrep/CodeQL false positives/negatives (→ Papers 20, 24), single-file snippets, synthetic OWASP templates, no human review.

**Provenance note.** Cisco reports SecurityEval as **121 prompts / 69 CWE**; the SecurityEval *paper* (40) reports **130 samples / 75 CWE**. The thesis's earlier "121" traces to Cisco's usage, not the paper — cite the number matching the source you mean.

**Cite in**: Introduction/Motivation (the question the thesis extends), Methodology (Semgrep ruleset, datasets, baseline-vs-rules design, raw-count metric), Threats to Validity (inherited limitations).

---

## Paper 1 — Metamorphic Testing of LLMs for NLP (191-MR Catalog)
**Relevance: Foundational vocabulary**

Establishes the formal definition of Metamorphic Relations and the taxonomy all eight mutators descend from. The secondary oracle problem (semantic equivalence is hard to verify) directly motivates the `MutationQualityValidator`. The key novel contribution of the thesis vs. this paper: the catalog tests LLMs *as the system under test* (NLP task testing); the thesis tests security rules that *guide* the LLM — a novel elevation of the MT paradigm to instruction-level testing.

**Cite in**: Introduction (MT definition), Methodology (MR taxonomy), Related Work.

---

## Paper 2 — LLMORPH: Automated Metamorphic Testing of LLMs
**Relevance: Direct source of 4 mutators**

`NegationInjectionMutator` (MR-48/76), `SectionReorderMutator` (MR-19/107), `ParaphraseMutator` (MR-51), and `VoiceChangeMutator` all trace directly to named MR identifiers in this paper. The LLM-based few-shot prompting implementation strategy matches how these mutators are built. The recency bias documented here provides theoretical grounding for the `degrade` mode of `SectionReorderMutator` — moving security-critical sections to the end exploits a known architectural bias in autoregressive LLMs.

**Cite in**: Methodology (per-mutator justification), each mutator's docstring.

---

## Paper 3 — Search-Based Selection of MRs (Hyun et al. 2025)
**Relevance: Highest-priority extensions**

Two contributions, both now resolved in the implementation:
1. **Combinatorial MR chaining** — applying multiple mutators per lineage, which Paper 3 shows is the primary source of incremental failure gain over single-MR application. **Now implemented**: the (1+1) EA chains mutations along a parent lineage up to a depth cap (`--max-depth-ea`, default 4), and the random baseline samples chains of length K.
2. **Quality-weighted fitness** — Paper 3's `Context_ASR × PerturbationQuality` motivates separating effectiveness from perturbation quality. The optimizer realises this not as a single product but as a 3-objective Pareto archive admitted by **Pareto dominance** over (f1, f2, f3): effectiveness is the primary axis (f1 = vulnerability-count delta), rule fidelity (f2 = mean SBERT similarity of mutated rules to their originals, sourced from the `MutationQualityValidator`) and −parsimony (f3 = fewer mutated rules) are the perturbation-quality axes. CodeBLEU code-divergence is computed and stored as a diagnostic only, not an objective (see ARIEL 41; Chen & Li 26).

Also validates the current mutator selection: `SynonymReplacement` and `AddRandomWord` are confirmed silver bullets (Paper 3 also reports L33TChanging as a third). The MOEA/D result justifies why SBST outperforms random MR selection — external validation for the search-based approach.

**Cite in**: Methodology (SBST design, silver bullet mutator choice), Future Work (MOEA/D).

---

## Paper 4 — AUGMENT Framework
**Relevance: Source of the quality validation architecture**

The `MutationQualityValidator` implements AUGMENT's three evaluation criteria (instruction adherence, semantic similarity, realism), extended with a thesis-original security-keyword-retention criterion. **Important: in this thesis these criteria are *informational / post-hoc* — they do not gate the search** (`quality.py:7-10`), a deliberate divergence from AUGMENT §5.3, which keeps only passing paraphrases and preserves the original otherwise. Threshold provenance (verified against AUGMENT Appendix C): the **SBERT threshold 0.75 is AUGMENT's global value** (App C.2, Fig 5: "a global SBERT threshold of 0.75 across all paraphrase types") — but AUGMENT calibrated it on `stsb-distilroberta` (a cross-encoder), whereas the thesis uses `all-mpnet-base-v2` (bi-encoder cosine), so the cutoff is *transferred, not re-calibrated*. The realism (perplexity-ratio) criterion uses AUGMENT's general **2.5** realism cutoff (App C.2, Fig 8; AUGMENT's C.3 final rules add a 2.0 *Formal-Style* exception, which the thesis does not replicate) and is **off by default**. The `VoiceChangeMutator` and `SynonymReplacementMutator` are AUGMENT-attributed (note AUGMENT reports voice-change filtering is its least reliable, F1 = 53.64). The critical departure: AUGMENT tests *user fairness*; the thesis uses the same framework to measure *security-instruction robustness*.

**Cite in**: Methodology (validator design), each of the three quality criteria, `VoiceChangeMutator`.

---

## Paper 5 — Instruction-Following Dimension (Heo et al. ICLR 2025)
**Relevance: Mechanistic justification for why mutation works**

Proves via linear probing that instruction-following success is predictable from a single linear direction in the LLM's input embedding space, and that this direction is most influenced by *prompt phrasing* (not task difficulty). This provides the deepest mechanistic justification for why syntax-preserving semantic rewrites are principled attacks on instruction adherence — not noise. Cite in the motivation section to establish that brittleness is an architectural property of LLMs, not an edge case.

**Future experiment**: use the instruction-following dimension as a proxy fitness signal to rank candidate mutations before Semgrep evaluation.

**Cite in**: Introduction/Motivation (why phrasing mutations work), Discussion (interpreting per-mutator results).

---

## Paper 6 — Latent Adversarial Paraphrasing (LAP)
**Relevance: Embedding-distance signal + adversarial paraphrase selection**

LAP is a latent-adversarial-*training* method (it perturbs hidden states). Its usable insight for this thesis is that the **embedding-space distance between an original prompt and a paraphrase predicts behavioral drift** — worst-case paraphrases sit at larger Euclidean distance (Fig 2; Spearman ρ = 0.36, p < 0.05). This supports a near-term `ParaphraseMutator` improvement: among candidates, prefer the one with the *largest* embedding distance from the original (most behaviorally divergent), requiring no gradient access. Note that LAP explicitly reports worst-case paraphrases are *"hardly detectable through conventional metrics such as perplexity"* — so LAP is evidence that perplexity is a *poor* worst-case detector, and must **not** be cited to justify the perplexity criterion or any perplexity↔SBERT threshold calibration.

**Cite in**: Motivation (embedding distance ↔ behavioral drift), Future Work (adversarial candidate selection). **Not** for perplexity/threshold calibration.

---

## Paper 7 — Mixture of Formats (MOF)
**Relevance: Untapped mutation axis — structural formatting**

Identifies that non-semantic Markdown formatting choices (bullet style, header depth, emphasis) cause 10–20% accuracy variance in LLMs. CodeGuard rules contain all of these elements. A `FormatStyleMutator` following the MOF principle would add a complementary mutation axis to the existing prose-level mutators. Lower priority than the existing mutators/fitness work — applicable once existing MRs are validated.

**Cite in**: Future Work (structural mutation extensions).

---

## Paper 8 — Metamorphic Prompt Testing for Code
**Relevance: Structural analogue; validates MT approach for code generation**

Applies the same MT assumption to code generation validation: semantically equivalent prompts should produce functionally equivalent programs. Validates the thesis's core assumption that phrasing variations in instructions should produce consistent code security outcomes. The majority-consensus oracle is not adopted (single-generation design choice), but the structural parallel is cited to situate the thesis within the code-generation MT literature.

**Cite in**: Related Work (MT for code generation, distinguishing thesis approach from output-level MT).

---

## Paper 9 — METAL Framework (Hyun et al. 2023)
**Relevance: Conceptual source of quality-weighted evaluation (PerturbationQuality)**

METAL's `M-ASR × PerturbationQuality` motivates separating effectiveness from perturbation quality. The thesis realises this *concept* as a 3-objective Pareto archive admitted by **Pareto dominance** over (f1, f2, f3) — effectiveness = f1 (vulnerability-count delta); rule fidelity = f2 (mean SBERT similarity, from the `MutationQualityValidator`); −parsimony = f3 (fewer mutated rules) — rather than as a single product; CodeBLEU code-divergence is stored as a diagnostic, not an objective. METAL also validates the focus on sentence-level perturbations (it shows they outperform character/word-level for code-generating LLMs).

**Cite in**: Methodology (quality-weighted evaluation lineage; why effectiveness and quality are separated), Evaluation (per-mutator quality vs effectiveness).

---

## Paper 10 — Tone and Politeness Effects
**Relevance: Evaluation methodology — per-domain reporting**

The key finding is methodological: aggregating results across domains hides significant per-domain effects. The thesis must report results per CWE category and per programming language, not just aggregate Semgrep counts — otherwise a mutator that dramatically affects C buffer-overflow rules but not Python injection rules would appear ineffective in aggregate.
**Cite in**: Evaluation (justification for per-CWE breakdown), Discussion (interpreting aggregate vs. per-category results).

---

## Paper 11 — STELLAR
**Relevance: Architectural inspiration for future structured search**

STELLAR's 4.3× improvement over random testing (via feature discretization + NSGA-II) motivates eventually moving from the current budget-driven (1+1) EA to population-based multi-objective structured search over a discretized rule mutation space. For the thesis scale, the single-archive EA limits expensive evaluations, while STELLAR provides the architectural vision for a larger-budget pipeline. The eight current mutators are already the implicit discrete operator dimension; STELLAR formalizes the full product space.

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
**Relevance: Background — multi-objective prompt evolution (contrasting design point)**

Demonstrates multi-objective evolution of prompts (balancing security and performance) outperforms single-objective optimization. Note: SoS combines its objectives via a **weighted aggregation**, not a pure Pareto scheme — so it is a *contrasting* example to the thesis's **Pareto-over-weighted-sum** choice (cf. Chen & Li, Paper 26), not a validation of it. The crossover and feedback-mutation ideas (agents analyse failures and suggest improvements) remain a useful future analogue of the Semgrep-feedback loop. Not implemented in the current EA.

**Cite in**: Related Work (multi-objective prompt optimization; weighted-sum vs Pareto contrast).

---

## Paper 18 — Artemis: Automated Optimization of LLM-based Agents
**Relevance: Hierarchical evaluation strategy**

Validates that LLM-ensemble mutations (using a secondary LLM to perform intelligent perturbations) outperform random mutations — the thesis already does this for 3 of 8 mutators (the LLM-based ones: negation_injection, voice_change, paraphrase). The actionable contribution is the hierarchical evaluation: cheap filters (SBERT similarity, LLM-as-judge) before expensive validation (Semgrep). This could reduce the number of full generation+Semgrep evaluations needed per candidate.

**Cite in**: Future Work (hierarchical evaluation to reduce computational cost).

---

## Paper 19 — SPRIG: System Prompt Optimization
**Relevance: Background — structural analogue for rule/prompt optimization**

SPRIG optimizes system prompts (the thesis optimizes security rules, which are system prompts). The structural parallel is strong: seed corpus → mutation operations → fitness-guided selection. Adaptive per-mutator selection (tracking success rates to prioritise effective mutators) is a natural future extension, but the canonical citations for it are the bandit papers (34/35/36), **not** SPRIG; the current optimizer uses uniform mutator selection. (Caveat for reuse: the "UCB-based pruning" sometimes attributed to SPRIG is not the paper's contribution, and the local PDF is a different version than the one cited — verify before citing.)

**Cite in**: Related Work (system-prompt optimization).

---

## Paper 20 — SCAFFOLD-CEGIS
**Relevance: CRITICAL threat to validity — Semgrep-only fitness is empirically insufficient**

Proves that iterative optimization against SAST tools teaches LLMs to structurally evade detection patterns rather than produce genuinely secure code. SAST gating *increases* latent security degradation (12.5% → 20.8%). The safe-zone contract is a simplified version of semantic anchoring. The thesis MUST cite this paper in Threats to Validity and acknowledge that the Semgrep-only fitness function is a known limitation.

**Cite in**: Threats to Validity (Semgrep-only limitation), Methodology (safe-zone contract as anchoring).

---

## Paper 21 — ATheNA: Hybrid Fitness in SBST
**Relevance: Formal framework for combining automated + domain-knowledge fitness**

Provides the formal SBST citation for combining an automated fitness `f_AT` (Semgrep) with a domain-knowledge signal `f_MAN` (quality: SBERT similarity, security-keyword retention). Note: ATheNA composes these **additively** (`f = f_AT + f_MAN`), not multiplicatively. In the current design the two concerns are kept separate rather than summed: `f_AT` ≈ the f1 (vulnerability-count) objective, while the domain-knowledge quality signal appears as the f2 rule-fidelity objective (mean SBERT similarity, from the `MutationQualityValidator`) — a separate Pareto axis admitted by dominance, not summed into f1. ATheNA still supports the core claim that domain-knowledge fitness improves SBST effectiveness at low overhead.

**Cite in**: Methodology (hybrid-fitness rationale; why quality is a gate + secondary axis rather than a summed term).

---

## Paper 22 — CodeScore
**Relevance: Future dual-objective evaluation (security + functional correctness)**

CodeScore's NL-only modality could evaluate whether mutated rules still produce functionally valid code. Currently not needed — Semgrep implicitly handles this (syntactically broken code produces parsing errors, not security findings). Cite as future work for a dual-objective evaluation combining security compliance with functional correctness.

**Cite in**: Future Work (if dual-objective evaluation is proposed).

---

## Paper 23 — MST-wi: Metamorphic Security Testing for Web Systems
**Relevance: Low — different domain, conceptual parallel only**

The 76 MRs and 10 structural patterns operate on HTTP requests, not NLP prompts. The relational-oracle concept (equality/subset checking) is analogous to the thesis's baseline-relative evaluation of each chromosome. Cite for completeness in the security-domain MT literature.

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

## Paper 26 — The Weights Can Be Harmful: Pareto Search versus Weighted Search in Multi-Objective SBSE (Chen & Li, TOSEM 2022)
**Relevance: Critical empirical basis for dropping the weighted composite fitness**

Across **38 systems drawn from 3 representative SBSE problems (604 paired comparisons)**, shows Pareto search significantly outperforms weighted-sum search in **up to 77% of cases — given a sufficient (but not unrealistic) search budget**. Weight choices are also fragile: small changes to the weight vector frequently change which solution is selected, making results artifact-sensitive (the textbook explanation is weighted sums' inability to reach non-convex Pareto regions). The old composite formula (`1.0·semgrep_delta + 0.3·rule_div + 0.2·code_div`) had exactly this fragility — no principled basis for the 0.3/0.2 values, and semgrep vs code-divergence are not symmetric co-equal objectives. This is the empirical citation for replacing the weighted sum with **Pareto-dominance archive admission** — which Chen & Li directly advocate (Pareto > weighted).

**Threats-to-validity nuance**: Chen & Li also find weighted search is *more resource-efficient* and may be preferable under tight budgets — and this thesis is budget-limited (~5000 Semgrep evals). The thesis uses Pareto-dominance admission (the option Chen & Li favour), but their budget-efficiency caveat is still worth one sentence in Threats to Validity.

**Note on attribution**: Perplexity misattributed this to "Wang, S. et al." — the correct authors are **Tao Chen & Miqing Li**.

**Cite in**: Methodology (motivation for dropping weighted composite), Threats to Validity (weight sensitivity; budget-efficiency trade-off).

---

## Paper 27 — NSGA-II: A Fast and Elitist Multiobjective Genetic Algorithm (Deb et al., IEEE TEVC 2002)
**Relevance: Foundational Pareto reference — cite to explain what the thesis chose NOT to use**

The canonical multi-objective evolutionary algorithm, providing the formal definition of non-dominated sorting, crowding distance, and Pareto front maintenance that papers 3, 11, and 17 all build on. The thesis discusses Pareto-based alternatives (Papers 3, 17) and explains why they were not adopted — NSGA-II is the reference point for those alternatives.

**Cite in**: Methodology (multi-objective alternatives considered); Related Work (when Papers 3/11/17 are discussed and Pareto concepts are needed).

---

## Paper 28 — Nonlinear Multiobjective Optimization (Miettinen, Kluwer 1999)
**Relevance: Canonical MOO-theory reference — the formal Pareto-optimality definition behind the archive admission rule (and lexicographic ordering as the considered-but-rejected alternative)**

The standard reference textbook for MOO theory. The thesis's archive admits candidates by **Pareto dominance**, so the load-bearing citation is Miettinen's **formal definition of Pareto optimality** (Def 2.2.1, §2.2): a vector is Pareto optimal iff no objective can be improved without worsening another — exactly the `dominates()` relation over (f1, f2, f3) in `chromosome.py`. **Lexicographic ordering** (Ch 4 "A Priori Methods", §4.2) is a *different* a-priori method the thesis considered in an earlier design (the "Thread-1" semgrep-primary / code-divergence-tie-break rule) but did **not** adopt — the implemented optimizer uses Pareto dominance, not lexicographic. Cite §4.2 only when discussing the rejected alternative.

**Cite in**: Methodology (formal Pareto-optimality definition for the admission rule, alongside Chen & Li 26 and ARIEL 41); Related Work (lexicographic ordering as the considered-and-rejected a-priori alternative).

---

## Paper 29 — CodeBLEU: a Method for Automatic Evaluation of Code Synthesis (Ren et al., 2020)
**Relevance: Primary code-divergence metric — closes the NL-SBERT-on-code gap (§5.9)**

Extends BLEU with syntactic AST matching and data-flow graph matching for code evaluation. The four-component metric (n-gram BLEU + keyword-BLEU + AST + data-flow, default weights 0.25 each) is specifically designed to capture structural code differences beyond surface-level token overlap. Implemented in the `k4black/codebleu` PyPI package with first-class support for Python and Java — exactly the two languages the thesis evaluates. The metric replaces `all-mpnet-base-v2` applied to code, which is architecturally mismatched (NL model on code). *Implementation note (disclose in Methodology): `composite_fitness.py` falls back to token-level BLEU if CodeBLEU import/computation fails (`:180-185`), so a small fraction of `code_divergence` values may be token-BLEU rather than CodeBLEU.*

**Cite in**: Methodology (code_divergence metric definition), Evaluation (per-language breakdown).

---

## Paper 30 — TSED: Tree-Structured Edit Distance for Code (Song et al., ACL 2024)
**Relevance: Alternative metric considered and rejected — cite in Future Work**

AST edit distance via tree-sitter + APTED. Perplexity claimed TSED beats CodeBLEU, but TSED never benchmarks against CodeBLEU. Rejected in Thread 2 due to: ~100–200 line adapter requirement, limited language support in the paper's evaluation (missing Java), and modest execution-match correlation (0.19 Spearman on Python). The TSED vs. CodeBLEU ablation is a legitimate future-work item.

**Cite in**: Future Work (code-similarity metric alternatives); Threats to Validity (CodeBLEU limitations context).

---

## Paper 31 — MTEB: Massive Text Embedding Benchmark (Muennighoff et al., EACL 2023)
**Relevance: Empirical justification for `all-mpnet-base-v2` as SBERT model — closes §4.5 gap**

MTEB evaluates 33 models across **58 datasets** (112 languages) and 8 task types; its headline finding is that no single model dominates all tasks — exactly why model choice should be matched to the task (here, symmetric STS). The specific rankings the thesis relies on — `all-mpnet-base-v2` top-tier on **STS**, `multi-qa-mpnet-base-dot-v1` strong on asymmetric retrieval but weaker on symmetric STS, and AUGMENT's `stsb-distilroberta-base-v2` below `all-mpnet-base-v2` on STS — come from the **MTEB leaderboard** (HF), not the paper text, and should be cited as such (with access date). Net: the model choice is justified and already stronger than AUGMENT's on STS.

**Cite in**: Methodology (SBERT model selection — cite the paper for the benchmark, the leaderboard for rankings), Quality Validator section.

---

## Paper 32 — Sentence-BERT: Sentence Embeddings using Siamese BERT-Networks (Reimers & Gurevych, EMNLP 2019)
**Relevance: Foundational reference for all SBERT usage in the thesis pipeline**

The architectural source of the sentence-level embedding approach used throughout. Every call to `compute_sbert_similarity()` in the thesis pipeline is an application of Reimers & Gurevych's siamese network framework. This paper is the missing foundational citation — currently the thesis cites SBERT usage via AUGMENT (Paper 4) and METAL (Paper 9) without citing the originating architecture paper.

**Cite in**: Methodology (SBERT framework introduction); Related Work (sentence embedding foundations).

---

## Paper 33 — SecureBERT 2.0 (Aghaei et al., Cisco AI, 2025)
**Relevance: Marginal — optional future domain-specific embedding alternative (not currently used)**

ModernBERT-based domain-specific embedding model (pretrained on a cybersecurity corpus) — stylistically close to CodeGuard rules. A possible drop-in alternative to `all-mpnet-base-v2` for rule similarity, but **not currently used**; listed only as an optional future ablation. Architectural specifics are deliberately not detailed here — cite from the paper body if and when it is actually adopted.

**Cite in** *(optional)*: Future Work (domain-specific embedding ablation).

---

> **Bandit note (Papers 34–36, 39).** An adaptive bandit mutator-selection path (UCB1 / D-UCB / DYTS / Thompson) was prototyped earlier in the project and then replaced by the current (1+1) EA + Pareto archive with **uniform** mutator selection. The earlier strategy code is recoverable from git history and could be revisited as a future bandit-vs-EA ablation on adaptive mutator selection, but it is **not** part of the current design or source of truth. The papers below are retained only as the citation set for that conditional future ablation.

## Paper 34 — Finite-time Analysis of the Multiarmed Bandit Problem — UCB1 (Auer, Cesa-Bianchi, Fischer, 2002)
**Relevance: Marginal — UCB1 baseline for a possible future bandit-vs-EA ablation (see Bandit note above)**

The foundational UCB1 paper establishing O(log T) regret with exploration bonus `c · √(ln t / n_i)`; the canonical constant is `c = √2` (UCB1 plays argmax x̄_j + √(2 ln n / n_j)). UCB1 would be the canonical baseline if a bandit-vs-EA ablation on adaptive mutator selection is run as future work.

**Cite in** *(conditional)*: Future Work / ablation (adaptive mutator selection), if run.

---

## Paper 35 — On Upper-Confidence Bound Policies for Switching Bandit Problems — D-UCB/SW-UCB (Garivier & Moulines, ALT 2011)
**Relevance: Marginal — non-stationary bandit option for a possible future ablation**

Analyses D-UCB (discount-based) and introduces SW-UCB (sliding window) for non-stationary/switching bandits. The discounted form (originally due to Kocsis & Szepesvári) applies a γ-discount giving exponentially higher weight to recent pulls, which would suit a reward distribution that drifts as mutations compound; it has three hyperparameters (γ, ξ, B) vs DYTS's one. A candidate non-stationary strategy if an adaptive-mutator-selection ablation against the EA is run as future work (see Bandit note).

**Cite in** *(conditional)*: Future Work / ablation (non-stationary mutator selection), if run.

---

## Paper 36 — Adaptive Operator Selection Based on Dynamic Thompson Sampling for MOEA/D — DYTS (Sun & Li, 2020)
**Relevance: Marginal — closest-fit bandit for a possible future mutator-selection ablation**

DYTS decays Beta posterior parameters by γ at each pull (`α_i ← γ·α_i + r; β_i ← γ·β_i + (1−r)`; single hyperparameter γ). The DYTS update itself originates with Gupta, Granmo & Agrawala (2011); Sun & Li apply it to **adaptive operator selection** in an EA (MOEA/D) — i.e. choosing reproduction operators on the fly, the direct analogue of adaptive mutator selection here. Thompson sampling suits sparse Bernoulli-like reward regimes (Chapelle & Li 2011, Paper 39), matching the observed pattern (most mutators generation-inert, occasional wins). DYTS is the best-fit bandit strategy if a bandit-vs-EA ablation is run as future work (see Bandit note).

**Attribution note**: Perplexity cited this as "Li, K. et al." — the correct author order is **Lei Sun, Ke Li**. (Title is "Adaptive Operator Selection Based on Dynamic Thompson Sampling for MOEA/D".)

**Cite in** *(conditional)*: Future Work / ablation (adaptive mutator selection), if run.

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
**Relevance: Marginal — empirical support for Thompson sampling, if a bandit ablation is run**

Shows Thompson sampling is highly competitive and in some cases significantly outperforms UCB on sparse-reward tasks (low-CTR display-ad and news-recommendation), and argues it belongs among the standard baselines. Supports preferring a Thompson-style strategy (DYTS, Paper 36) over UCB-family in sparse regimes. Relevant only to the conditional future bandit path (see Bandit note).

**Cite in** *(conditional)*: Future Work / ablation justification, if run.

---

## Paper 40 — SecurityEval: A Manually-Curated Security Benchmark *(optional)* (Siddiq & Santos, MSR4P&S '22)
**Relevance: Third cross-check dataset — Python-only, 130 samples across 75 CWEs**

Manually curated prompts designed to elicit insecure completions from coding assistants. Python-only focus and small size (**130 samples / 75 CWEs**) make it a low-cost third data point if both CyberSecEval v2 and LLMSecEval cross-checks are already running. (Venue: MSR4P&S '22 — Workshop on Mining Software Repositories Applications for Privacy and Security, co-located with ESEC/FSE 2022; not "MSR-APSEC".)

**Cite in** *(optional)*: Methodology (multi-dataset robustness evaluation).

---

## Paper 41 — ARIEL: Automated Repair of Feature Interaction Failures in ADS (Ben Abdessalem et al., ISSTA 2020)
**Relevance: Primary algorithmic precedent for the repair-oriented (1+1) EA + Pareto archive design**

The direct structural precedent for the optimizer. ARIEL repairs integration rules so safety-requirement tests pass; the thesis searches semantics-preserving edits to natural-language security rules so the guided LLM produces code with fewer Semgrep findings. Both are repair-oriented, expensive-evaluation problems using a (1+1) EA and a many-objective archive, but the chromosome representation, objectives, overflow eviction, and restart implementation are thesis-specific adaptations.

Five concrete mappings into our codebase:
1. **(1+1) EA chosen over GP because evaluations are expensive.** Their justification — "evaluating a pool of patches in each iteration/generation becomes too expensive (in the order of hours)" — is the verbatim argument we use in the Approach chapter for not using NSGA-II / SPEA2 / GP. Our evaluation cost (LLM generation + Semgrep batch) puts us in the same regime.
2. **Multi-objectivization to escape local optima.** "Multi-objectivization can lead to better results than classical single-objective approaches… helps store partial patches that individually fix different faults" — direct support for our 3-objective (f1 = security effect / vulnerability-count delta, f2 = rule fidelity, f3 = −parsimony) decomposition. A scalar f1 alone would ignore how much the rule set was perturbed to get there.
3. **Archive cap with eviction that protects the best repair.** Their cap is `2 × k` where k = number of safety requirements; ours is `cap=6` over the single chromosome archive. On overflow we evict **lexicographically by f1** (lowest f1 first, ties → f2+f3, then age) in [chromosome.py](src/optimizer/chromosome.py) — deliberately *not* ARIEL's lowest-aggregated-`D = Σ Ω_i`, because the three objectives live on different scales and a raw sum could drop the best repair to keep a barely-mutated variant.
4. **Stagnation-restart counter h.** ARIEL's h=8 was picked by preliminary experiments and supplies the precedent for our `restart_h=8` default. The thesis adapts the reset at whole-chromosome level: after h rejected ea-phase attempts, it wipes the front and reseeds it with `ea_init_samples` independent origin-based chromosomes. That is inspired by ARIEL's reset, not an identical per-rule mechanism.
5. **Roulette-Wheel mutator selection weighted by suspiciousness.** ARIEL samples mutators with probability proportional to a fault-localization score. We currently sample uniformly. **This is a clean future-work direction** — we already collect per-mutator archive-add counts in `mutator_stats[name]['archive_adds']`, which a weighted-by-past-success or bandit selection scheme (Papers 34/35/36; see Bandit note) could consume directly.

**Cite in**: Approach (primary methodological precedent), Related Work (single-state vs population-based EA in expensive-evaluation domains), Discussion (adaptation from integration-rule repair to natural-language security-instruction repair).

---

## Paper 42 — A Survey on Handling Computationally Expensive Multiobjective Optimization Problems with EAs (Chugh, Sindhya, Hakanen, Miettinen; Soft Computing 2019, covering 2008–2016)
**Relevance: Background / framing of the field; supplies vocabulary and future-work hooks**

The taxonomic anchor for the Background chapter. The thesis applies an expensive multiobjective EA to a code-security domain that the survey does not cover, but the survey provides the field's vocabulary (Pareto optimality, ideal/nadir, evolution control, function-vs-fitness approximation), the canonical algorithms to namedrop in Related Work (ParEGO, SMS-EGO, MOEA/D-EGO, K-RVEA), and the empirical context that 5000 expensive evaluations sits firmly in the upper-expensive band of the surveyed budgets.

Two specific things to lift directly into the thesis:
1. **Function-evaluation budget framing.** Surveyed budgets range from 50 to 30,000; ours (~5000 Semgrep calls per run) is upper-expensive. This empirically justifies the algorithmic conservatism of (1+1) EA over population-based methods.
2. **The fixed-vs-adaptive evolution control distinction.** Most surveyed algorithms use fixed evolution control (deterministic schedule of when to query the expensive function); we are also fixed. Naming the dichotomy makes our design choice legible.

Three future-work hooks the survey unlocks (all distinct from current implementation):
- **Surrogate on Semgrep fitness.** Train a regressor on rule-text → expected f1 to skip evaluation for clearly-bad mutations. Section 3.3 of the survey gives the framework; Kriging or RBF are the obvious starting points. Note the survey's warning: training-time cost is "usually neglected" but can dominate when the model is heavy — relevant if we ever try this.
- **Fitness *classification* rather than function approximation.** Pareto-SVM (Loshchilov 2010, surveyed §3.7) classifies candidates as "will improve archive / won't" without evaluating the real fitness. For us this would mean a learned predictor over `(rule_text, mutator, parent_entry) → P(archive_add)`.
- **Weighted ensemble of mutator types.** The survey discusses metamodel ensembles in §3.5; the analogue for us is the mutator pool, with the natural extension being weighted-by-past-success sampling — connecting to the ARIEL roulette-wheel point and to a *possible future* adaptive bandit ablation (Papers 34/35/36; see Bandit note). The current optimizer uses uniform mutator selection.

**Cite in**: Background (formal definitions of expensive MOP, Pareto front, evolution control), Related Work (Kriging-based MOO survey landscape — ParEGO/SMS-EGO/MOEA/D-EGO/K-RVEA — for completeness), Future Work (surrogate fitness, classification-based screening, weighted mutator selection).

---

---

## Paper 43 — MORPH: Metamorphic-Based Many-Objective Distillation of LLMs for Code-Related Tasks (Panichella, ICSE 2025)
**Relevance: HIGH (score 4–5) — the closest published precedent; fuses the thesis's two pillars (metamorphic testing + many-objective optimization)**

**What MORPH does.** Robust *knowledge distillation* of code LLMs: it compresses a teacher (CodeBERT / GraphCodeBERT) into a ~3 MB student while making the student robust to *metamorphic code changes*. Distillation is cast as a **many-objective optimization** over four objectives (Eq 1): O1 model size (params), O2 **prediction flips** (robustness — count of inputs where the student's prediction differs between an original snippet and its metamorphic variant, `S(v) ≠ S(v̄)`), O3 FLOPs (efficiency), O4 accuracy/F1 (effectiveness). It solves this with **AGE-MOEA** (Adaptive Geometry Estimation MOEA), using **Latin Hypercube Sampling** for initialization, SBX crossover + polynomial mutation + a custom repair operator, and — crucially for the expensive-evaluation problem — **two Gradient-Boosting surrogate models** that predict accuracy and prediction-flips without training each candidate configuration. Metamorphic variants are generated by *natural, semantics-preserving renaming* of functions and input parameters (synonyms / acronym expansion via ChatGPT-3.5; validated with tree-sitter).

**Results.** Versus AVATAR (the prior SOTA distiller): MORPH students are **47% more robust** (fewer prediction flips), **25% more efficient** (FLOPs), at comparable-or-higher accuracy (up to +6%), at 3 MB. AGE-MOEA beats NSGA-II / NSGA-III / MOEA/D on hypervolume; an ablation confirms metamorphic testing and many-objective optimization are the critical components.

**Why it is the closest precedent (and how the thesis differs).**
- **Same paradigm:** metamorphic testing + many-objective optimization — exactly the thesis's combination. Same author lineage as ARIEL (41): Annibale Panichella, TU Delft.
- **Prediction flips ≈ the thesis's recorded divergence diagnostic.** MORPH's PF (`S(v) ≠ S(v̄)`) measures behavioral change under a semantics-preserving transform; the thesis records `code_divergence = 1 − CodeBLEU` between baseline and mutated-rule generations. This is a conceptual analogue only: CodeBLEU does not steer the search, whose f1 axis is vulnerability reduction.
- **Renaming ≈ the `synonym_replacement` mutator.** MORPH's natural synonym/acronym renaming of identifiers is the code-side analogue of the thesis's prose-side synonym mutation.
- **The two key differences:** (1) *target* — MORPH transforms **code** and model configurations to harden a **code model**; the thesis transforms **security rules** that guide an LLM. (2) *objective* — MORPH minimises prediction flips during robust distillation; the thesis primarily minimises Semgrep-measured vulnerabilities while constraining rule fidelity and parsimony. The adversarial maximise direction remains secondary.
- **Algorithmic contrast:** MORPH uses a population many-objective EA (AGE-MOEA, 4 objectives) with surrogate-assisted evaluation; the thesis uses a budget-driven (1+1) EA + Pareto archive (ARIEL) over 3 objectives. MORPH is the reference for "what a full many-objective + surrogate treatment looks like," and its GBR + LHS surrogates are a concrete instance of the **surrogate-on-expensive-fitness future-work hook** (cf. Chugh survey, 42) — directly relevant if the thesis ever adds a surrogate over Semgrep fitness.

**Cite in**: Related Work (primary anchor — metamorphic + many-objective lineage, alongside ARIEL 41); Approach (justify (1+1) EA vs population many-objective; PF-vs-divergence framing); Future Work (surrogate-assisted MOO via GBR + LHS).

*Entry written from the abstract + §I–IV (method, 4-objective formulation, AGE-MOEA, surrogates, evaluation setup) of the ICSE'25 paper; the per-task numeric tables in §V were not transcribed in full.*

---

## Implementation Summary Table

*"Implemented Elements" / "Priority Extensions" reflect the current EA-only, uniform-selection, Pareto-dominance pipeline. Bandit rows (34/35/36/39) point to the Bandit note above — prototyped, replaced by the Pareto archive, retained only as the future-ablation citation set.*

| Paper | Implemented Elements | Priority Extensions |
|---|---|---|
| 1 — MR Catalog | SBERT validation, MR taxonomy (indirect) | — |
| 2 — LLMORPH | 4 mutators: Negation, SectionReorder ×2, Paraphrase, VoiceChange | Formal style, elaboration hedging |
| 3 — Hyun SBST | (1+1) EA, SynonymReplacement, AddRandomWord, **combinatorial chaining (EA depth-cap)** | Quality/effectiveness split realised as the 3-objective Pareto archive |
| 4 — AUGMENT | Full 3-criteria validator, VoiceChange, Synonym | Formal Style mutation |
| 5 — Heo et al. | Used for thesis framing only | Embedding-based proxy fitness (future) |
| 6 — LAP | Perplexity ratio (informational) | Adversarial candidate selection in Paraphrase |
| 7 — MOF | — | FormatStyleMutator (after existing MRs validated) |
| 8 — Code MT | Core assumption | — |
| 9 — METAL | Synonym, AddWord, SectionReorder, Paraphrase, Negation, SBERT validation | Quality-weighted *concept* realised as f1 effectiveness + f2 fidelity + f3 −parsimony (not a product) |
| 10 — Tone | Per-**language** reporting (motivation) | — (FluffMutator retired) |
| 11 — STELLAR | Implicit discrete operator space | Future: structured multi-objective search |
| 12 — MRSQLGen | Instability assumption | SRBKB targeted mutations (future) |
| 13 — PERSIST | temperature=0 design choice | — (multi-run explicitly out of scope) |
| 14 — CAIBench | Motivation/framing | — |
| 15 — Repetition | — | Optional validity control experiment |
| 16 — DrHall | Instability assumption (conceptual) | — (prompt mutations out of scope) |
| 17 — SoS | — (contrasting weighted-sum example) | Crossover / feedback-mutation (future) |
| 18 — Artemis | LLM-based mutation (via existing mutators) | Hierarchical evaluation filtering |
| 19 — SPRIG | Structural analogue (rule = system prompt) | Adaptive mutator selection (future, via 34/35/36); current selection is uniform |
| 20 — SCAFFOLD-CEGIS | Safe-zone contract; corpus lexicon anchoring; quality gate | **Threat to validity: Semgrep-only is insufficient** |
| 21 — ATheNA | Automated fitness (Semgrep = f_AT) | Quality (f_MAN) is **additive** in ATheNA; here the quality signal (SBERT rule fidelity) is the f2 Pareto objective (not summed into f1), and CodeBLEU code-divergence is a recorded diagnostic |
| 22 — CodeScore | — | Future: functional correctness counterbalance |
| 23 — MST-wi | Relational-oracle analogue in baseline-relative chromosome evaluation | — (web-security domain, not applicable) |
| 24 — SAST-MT | Semgrep as fitness oracle | **Threat to validity: SAST FP/FN blind spots** |
| 25 — zkCraft | Quality validation of LLM mutations | Future: failure-trace-guided re-mutation |
| 26 — Chen & Li TOSEM | — (empirical basis for design decision) | Cited for dropping weighted composite fitness |
| 27 — NSGA-II | — (reference for rejected alternative) | Future: if MOEA/D is ever implemented |
| 28 — Miettinen textbook | Pareto-optimality definition (Def 2.2.1) for the admission rule; lexicographic = considered alternative | Methodology + Related Work |
| 29 — CodeBLEU | **code_divergence metric (implemented)** — 1 − CodeBLEU in CompositeFitnessEvaluator | Per-language dispatch (bd-03k.2) |
| 30 — TSED | — (rejected alternative) | Future: TSED vs CodeBLEU ablation |
| 31 — MTEB | SBERT model justification (`all-mpnet-base-v2`) | Cited in Methodology |
| 32 — Sentence-BERT | SBERT framework foundation | Cited throughout |
| 33 — SecureBERT 2.0 | — (ablation target) | Pilot ablation: 30–50 rule pairs, ~1 day |
| 34 — UCB1 (Auer et al.) | — (see Bandit note) | Future ablation baseline; c = √2 |
| 35 — D-UCB / SW-UCB | — (see Bandit note) | Future ablation candidate (non-stationary) |
| 36 — DYTS (Sun & Li) | — (see Bandit note) | Future ablation candidate (best fit: adaptive operator selection) |
| 37 — CyberSecEval 2 | Primary evaluation dataset (already in pipeline) | Cite as v2 (arXiv:2404.13161) |
| 38 — LLMSecEval | Cross-check dataset (planned) | ~3–4h ingestion adapter |
| 39 — Chapelle & Li *(opt)* | — (see Bandit note) | Future ablation justification only |
| 40 — SecurityEval *(opt)* | — (third cross-check dataset) | Optional; Python-only, **130 samples / 75 CWEs** |
| 41 — ARIEL | **(1+1) EA + Pareto archive, cap=6, restart_h=8, f1-lexicographic overflow eviction** | Roulette-Wheel mutator selection weighted by archive-add rate |
| 42 — Chugh survey | Background framing (expensive MOP vocabulary, evolution control) | Surrogate on Semgrep fitness; Pareto-SVM classification screening; weighted mutator ensemble |
| 43 — MORPH (Panichella) | — (metamorphic + many-objective precedent; PF ≈ divergence; renaming ≈ synonym mutator) | Score 4–5; full entry written. Future: surrogate-assisted MOO (GBR + LHS) |
| **C0 — Cisco CodeGuard blog** | **Primary reference**: Semgrep `p/security-audit` + ERROR/WARNING count, CyberSecEval/SecurityEval datasets, baseline-vs-rules design, CodeGuard rules as SUT | The methodology the thesis **extends** with semantics-preserving rule repair |
