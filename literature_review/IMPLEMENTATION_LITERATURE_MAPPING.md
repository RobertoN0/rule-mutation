# Implementation ↔ Literature Mapping

The 43 papers (plus the Cisco Project CodeGuard study, Ref C0) referenced below are the ones analysed in `THESIS_RELEVANCE.md` and `INDEX_AND_LINKS.md`. Paper numbers match those files.

This document is a **mapping**, not a new literature search. Anything marked **GAP** is an action item: something we rely on but currently justify only by engineering judgment.

**Current design baseline (source of truth for this document):**

1. **Search** — a (1+1) EA over a single **whole-rule-set chromosome Pareto archive**. A candidate is admitted **iff it is not Pareto-dominated** over three objectives (f1 = security effect / vulnerability-count delta — positive under `--objective-direction minimize` = repair; f2 = rule fidelity, mean SBERT similarity of mutated rules; f3 = −parsimony, negated count of mutated rules) — `chromosome.py` (`dominates`/`try_add`), `search.py`, `engine.py`. Admission uses no weighted-sum composite; on cap overflow, eviction is lexicographic by f1 (lowest f1 first, ties → f2+f3, then age) so the best repair is never dropped. `--optimizer` is `ea | random_search`.
2. **Mutator selection** — **uniform** random over the registry (`search.py`). The registry has **8 mutators**: verb_weakening, synonym_replacement, add_random_word, section_reorder_shuffle, section_reorder_degrade, negation_injection, voice_change, paraphrase.
3. **Code divergence** — `code_divergence = 1 − CodeBLEU` via `composite_fitness.py` (token-BLEU fallback on failure). Computed and stored as a **diagnostic only**, not a search objective.
4. **Quality validation** — the `MutationQualityValidator` **never gates** the search (4 criteria: instruction adherence, SBERT similarity, perplexity ratio (off by default), security-keyword retention). Its SBERT similarity now **feeds the f2 fidelity objective**; the other criteria remain informational.

> **Bandit note.** An adaptive bandit mutator-selection path (UCB1 / D-UCB / DYTS / Thompson — Papers 34/35/36/39) was prototyped earlier in the project and replaced by the current EA + Pareto archive with uniform selection. The earlier strategy code is recoverable from git history and could be revisited as a future bandit-vs-EA ablation, but it is **not** part of the current design. §6 keeps the bandit citation set only for that conditional future ablation.

---

## How to read this document

Each implementation choice is categorised into one of three tiers:

- **✅ Validated** — an explicit, named citation from our paper set directly supports this choice (not just the general area).
- **🟡 Partial** — literature supports the general approach but not the specific parameter/threshold/variant we chose.
- **❌ GAP** — no reviewed paper justifies this. We rely on engineering judgment, ad-hoc empirical tuning, or convention.

Inside each tier, choices are grouped by subsystem (search, mutation, validation, fitness, generation, evaluation).

---

## 1. Search algorithm

### ✅ Validated

**1.1 (1+1) EA + Pareto archive as the base SBST loop**
- *Choice:* Single-state (1+1) EA that mutates whole rule-set chromosomes and admits a candidate into a single Pareto archive when it is not dominated.
- *Citation:* Paper 41 (ARIEL) — the structural precedent for a repair-oriented (1+1) EA with a many-objective archive under expensive evaluation; the thesis adapts that structure to whole natural-language rule-set chromosomes, different objectives, and different overflow handling. Paper 3 (Hyun et al. 2025) — search-based selection outperforms random over the same kind of mutation space. Paper 19 (SPRIG) — analogous fitness-guided search over system prompts.
- *Confidence:* Strong. ARIEL is a direct structural precedent on a closely related problem.

**1.2 Pareto-dominance admission over (f1, f2, f3)**
- *Choice:* Admit a candidate iff neither the origin nor an archive entry dominates it on (f1 = security effect / vulnerability-count delta, f2 = rule fidelity, f3 = −parsimony); evict dominated entries; on cap overflow evict lexicographically by f1 (lowest f1 first, ties → f2+f3, then age), so the best repair is protected.
- *Citation:* **Paper 41 (ARIEL)** — the (1+1) EA + Pareto-archive admission mechanism. **Paper 26 (Chen & Li, TOSEM 2022)** — empirically shows weighted sums miss Pareto-optimal solutions; the case for Pareto over weighted-sum. **Paper 28 (Miettinen 1999)** — the formal Pareto-optimality definition (Def 2.2.1) behind the `dominates()` relation. **Paper 27 (NSGA-II)** — canonical non-dominated-sorting reference. *Lexicographic ordering (Miettinen §4.2) is the considered-and-rejected a-priori alternative, not the implemented rule.*

**1.3 Mutations compound on the parent lineage (not the original)**
- *Choice:* The archive keeps accepted offspring per rule so later mutations stack on earlier accepted ones, up to a depth cap (`--max-depth-ea`, default 4).
- *Citation:* Paper 3 (Hyun et al. 2025, Table 1) — "1 to 4 perturbation functions in Cmb_MR" explicitly defines combinatorial chaining on the parent candidate.

### 🟡 Partial

**1.4 Stagnation wipe/reseed and exhausted-neighbourhood reopen**
- *Choice:* After `restart_h` consecutive rejected **ea-phase** attempts, the runner wipes the whole chromosome front and spends the next `ea_init_samples` evaluations reseeding it with independent origin-based random samples. If no parent has an eligible local move, it instead keeps the front and clears tried-move sets so those neighbourhoods can be explored again. Per-rule depth saturation is handled by an explicit revert move, not by restarting the archive.
- *Support:* ARIEL (41) supplies the stagnation-counter/reset precedent and its empirical `h=8`; the thesis's whole-front wipe followed by a multi-sample chromosome reseed, and the separate exhausted-neighbourhood reopen, are engineering adaptations rather than direct replications of ARIEL's reset.

---

## 2. Mutation operators

*Registry (8 mutators): verb_weakening, synonym_replacement, add_random_word, section_reorder_shuffle, section_reorder_degrade, negation_injection, voice_change, paraphrase.*

### ✅ Validated

**2.1 SynonymReplacementMutator (WordNet-backed via nlpaug)**
- *Citation:* Paper 3 (Hyun et al. 2025) — identified as a silver-bullet MR. Paper 4 (AUGMENT) — used as a paraphrase primitive. Paper 9 (METAL) — word-level MR.

**2.2 AddRandomWordMutator**
- *Citation:* Paper 3 (Hyun et al. 2025) — silver-bullet MR. Paper 9 (METAL) — insertion MR.

**2.3 SectionReorderMutator (shuffle mode)**
- *Citation:* Paper 2 (LLMORPH) MR-19 / MR-107 — reorder MRs. Paper 9 (METAL) — sentence-level reordering.

**2.4 NegationInjectionMutator**
- *Citation:* Paper 2 (LLMORPH) MR-48 / MR-76 — negation-injection MRs.

**2.5 VoiceChangeMutator (active → passive)**
- *Citation:* Paper 4 (AUGMENT) — voice-change is one of AUGMENT's listed paraphrase types. Paper 2 (LLMORPH) — MR-equivalent transformations.

**2.6 ParaphraseMutator (LLM few-shot with linguistic constraints)**
- *Citation:* Paper 2 (LLMORPH) MR-51. Paper 4 (AUGMENT) — synonym-constraint paraphrase prompting. Paper 18 (Artemis) validates LLM-ensemble mutation over random mutation.

### 🟡 Partial

**2.7 SectionReorderMutator (degrade mode — move security-critical section to end)**
- *Support:* Paper 2 (LLMORPH) documents recency bias as an architectural property; Paper 5 (Heo et al.) supports the phrasing-dimension-dominance theory. Neither paper names or evaluates a "move to end to exploit recency bias" mutator specifically — we are extrapolating from observed LLM behaviour.

**2.8 LLM-based mutators reuse the generation backbone (Qwen2.5-Coder-32B)**
- *Support:* Paper 18 (Artemis) uses LLM-ensemble mutation. Paper 25 (zkCraft) uses LLM as zero-shot mutation oracle. Neither specifically validates reusing the *same model under test* as the mutator — we do so for VRAM efficiency, not because a paper recommends it.

**2.9 VerbWeakeningMutator (MUST → should ideally, NEVER → try to avoid, etc.)**
- *Support:* The *mutator* is thesis-original (chosen for the security framing), but its *mechanism* is literature-backed: **Heo (5)** shows instruction-following is dominated by prompt phrasing, and **Tone (10)** shows register/modal shifts measurably change LLM behaviour — so weakening imperative verbs is a principled attack on instruction adherence. Cite 5 + 10 for *why it works*; the specific `VERB_WEAKENING_MAP` table is a thesis design choice. The one mutator without a direct source-paper, but not an unmotivated one.

### ❌ GAP

**2.10 Specific hyper-parameters inside rule-based mutators**
- *Gap:*
  - `SynonymReplacement.aug_p = 0.3` — no literature justification for this fraction.
  - `AddRandomWord.aug_p = 0.1` — no literature justification.
  - Negation stopword list (~16 entries) for AddRandomWord — curated by the author; Paper 2 (LLMORPH) defines *negation injection* as a distinct MR (the reason we exclude these words), but the exact list is ours.
  - `_SimpleWordInserter` filler-word list (20 adverbs/connectors) — chosen by the author; no paper enumerates this list.

---

## 3. Safe-zone contract and rule parsing

### ✅ Validated

**3.1 Concept of mutation-immutable zones (frontmatter + fenced code + inline code)**
- *Citation:* Paper 20 (SCAFFOLD-CEGIS) — "semantic anchoring" of regions that must not be perturbed. Our `ParsedRule.get_mutable_prose()` is explicitly a lightweight form of that principle.

### 🟡 Partial

**3.2 Frontmatter = immutable, fenced code = immutable, inline code = immutable, prose = mutable**
- *Support:* The general principle comes from Paper 20, but the specific three-way split (frontmatter / fenced / inline) is driven by the Markdown format of CodeGuard rules, not by a paper.

### ❌ GAP

**3.3 `mask_inline_code` / `unmask_inline_code` placeholder protocol**
- *Gap:* Implementation detail — how we mask `` `code` `` spans before running nlpaug and restore afterwards. Engineering choice, no citation.

---

## 4. Quality validator (`MutationQualityValidator`)

*The validator is informational / post-hoc and never gates the search (`quality.py`). It has 4 criteria: instruction adherence, SBERT semantic similarity, perplexity ratio (off by default), security-keyword retention.*

### ✅ Validated

**4.1 Multi-criteria quality framework (adherence + semantic similarity + realism)**
- *Citation:* Paper 4 (AUGMENT) — direct source. The validator implements AUGMENT's framework, extended with a thesis-original security-keyword-retention criterion, and used informationally rather than as AUGMENT's gate.

**4.2 SBERT cosine similarity as the semantic-similarity criterion** *(informational/post-hoc — not a gate)*
- *Citation:* Paper 4 (AUGMENT) §5.1 + App C — uses SBERTScore. Paper 32 (Sentence-BERT) — architecture. Paper 1 (191-MR Catalog) — validates SBERT for MR oracle purposes.

**4.3 Perplexity ratio as the realism criterion** *(informational; OFF by default)*
- *Citation:* Paper 4 (AUGMENT) §5.1 + App C.2 (Fig 8) — realism via perplexity ratio; AUGMENT's general realism cutoff is **2.5** (GPT-Neo 2.7B), which the thesis matches. AUGMENT's C.3 final rules add a 2.0 Formal-Style exception, which the thesis does not replicate.
- *Caveat:* LAP (Paper 6) does **not** define a perplexity threshold and reports perplexity is a poor worst-case detector — do not cite LAP for any perplexity calibration.

**4.4 Per-mutator adherence function (each mutator gets its own check)**
- *Citation:* Paper 4 (AUGMENT) — describes per-mutator adherence tests; our `_adherence_*` functions are that pattern.

**4.5 SBERT threshold = 0.75**
- *Citation:* **0.75 is AUGMENT's global SBERT threshold** (Paper 4, App C.2 / Fig 5: "a global SBERT threshold of 0.75 across all paraphrase types"). Model-mismatch caveat: AUGMENT calibrated 0.75 on `stsb-distilroberta` (cross-encoder); the thesis uses `all-mpnet-base-v2` (bi-encoder cosine) — the threshold is transferred, not re-calibrated.

**4.6 Perplexity ratio threshold = 2.5** *(off by default)*
- *Citation:* **2.5 is AUGMENT's value** (Paper 4, App C.2 / Fig 8; perplexity via GPT-Neo 2.7B). Code (`quality.py`), run-script label, and `validation_audit.py` default all use 2.5.

### 🟡 Partial

**4.7 SBERT model = `sentence-transformers/all-mpnet-base-v2`**
- *Citation:* **Paper 31 (MTEB, Muennighoff et al. EACL 2023)** — `all-mpnet-base-v2` ranks top-tier on the STS (symmetric text similarity) subset, which is the exact task type of rule-pair similarity. **Paper 32 (Sentence-BERT, Reimers & Gurevych EMNLP 2019)** — foundational architecture reference.
- *Notes:* AUGMENT (Paper 4) uses `stsb-distilroberta-base-v2`, weaker than `all-mpnet-base-v2` on MTEB STS — the thesis's model is already stronger than the cited prior art. `multi-qa-mpnet-base-dot-v1` uses dot-product similarity (asymmetric retrieval), architecturally wrong for symmetric rule-pair STS.
- *Pilot ablation (future):* **Paper 33 (SecureBERT 2.0)** — domain-specific alternative to test on 30–50 (original, paraphrased) rule pairs; if Spearman correlation with `all-mpnet-base-v2` ≥ 0.90, the current model is confirmed.

**4.8 Security-keyword-retention criterion**
- *Support:* A thesis extension to AUGMENT's framework (a 4th criterion). Paper 4 does not include it. The *idea* of preserving domain-sensitive vocabulary is partially supported by Paper 20 (SCAFFOLD-CEGIS anchoring) and Paper 23 (MST-wi structural invariants).

**4.9 Inline-code retention criterion**
- *Support:* Falls out of Paper 20's anchoring principle. Threshold = 1.0 (exact retention) is our engineering choice.

### ❌ GAP

**4.10 Keyword-retention threshold ≥ 0.70**
- *Gap:* Thesis choice. No paper motivates 0.70 vs 0.60 or 0.80. May need recalibration as the corpus-derived lexicon grows from ~35 to ~100+ terms — flag in Threats to Validity.

**4.11 Security keyword vocabulary (corpus-derived lexicon)**
- *Choice:* `_SECURITY_KEYWORDS` is built once at pipeline startup from: (1) inline-code spans in each rule (`ParsedRule.get_inline_code_tokens()`), (2) frontmatter tag values, (3) CWE IDs from frontmatter. These are author-validated identifiers — rule authors marked them as technical anchors. No hand-curation or external download required.
- *Citation:* **Paper 20 (SCAFFOLD-CEGIS)** — semantic anchoring; inline-code spans are the "security-critical elements" that must not drift. **Paper 23 (MST-wi)** — structural invariants. **MITRE CWE** (standards reference) — CWE IDs are the authoritative vulnerability taxonomy.
- *Optional supplement:* Download MITRE CWE XML once, map CWE ID → name (e.g., "CWE-79" → "cross-site scripting"); ~50 short phrases, pure data lookup.

---

## 5. Fitness function

**Current design:**
- Primary signal: `semgrep_delta = new.semgrep_score − baseline.semgrep_score`.
- Secondary signal: `code_div = 1.0 − codebleu([baseline_code], [mutated_code])` (via `k4black/codebleu`; token-BLEU fallback on failure).
- Admission: **Pareto dominance** over the single whole-chromosome archive's three objectives (f1/f2/f3). No weighted-sum composite for admission (overflow eviction is f1-lexicographic).
- SBERT rule similarity is **not a gate** (the validator never rejects), but it is aggregated into the f2 fidelity objective (see §4).
- **Pareto objectives (f1/f2/f3):** the EA aggregates the per-case signals into f1 = security effect (vulnerability-count delta; positive under `--objective-direction minimize` = repair), f2 = rule fidelity (mean SBERT similarity of mutated rules to their originals), f3 = −parsimony (negated count of mutated rules) (`search.py`). Multi-objectivization is from ARIEL (41); the fidelity + parsimony pair keeps the search close to the original rule set — a conservative-repair framing adopted with the supervisor.

### ✅ Validated

**5.1 Use a SAST tool (Semgrep) as the primary objective signal**
- *Citation:* Paper 21 (ATheNA) — automated oracle `f_AT`. Paper 24 (SAST-MT) — uses SAST as an oracle target, also flags its false-negatives (threat to validity).

**5.2 Separating effectiveness from auxiliary quality signals**
- *Citation:* Paper 3 (Hyun et al. 2025) — `Context_ASR × PerturbationQuality` is the structural analogue. Paper 9 (METAL) — output-space divergence as a fitness signal. Paper 21 (ATheNA) — formalises combining `f_AT` with a domain-knowledge `f_MAN` (additively). The thesis keeps the concerns separate as Pareto objectives: effectiveness (f1) and the two perturbation-quality axes rule fidelity (f2, from the SBERT validator) and −parsimony (f3). CodeBLEU code-divergence is computed and stored as a diagnostic only, not an objective.

**5.3 Code-divergence diagnostic (CodeBLEU between generated code and iteration-0 reference)**
- *Citation:* **Paper 29 (CodeBLEU, Ren et al. 2020)** — the metric definition, default weights (0.25 each), and language-specific AST/data-flow matching, with first-class Python and Java support. Replaces NL-SBERT-on-code, which is architecturally mismatched (NL model on code). Paper 9 (METAL) — output-space divergence as a fitness signal.
- *Architecture:* reference code is captured at iteration 0 from the same Qwen baseline run (see §8.2). `code_div = 1.0 − calc_codebleu([baseline], [mutated], lang=lang, weights=(0.25,0.25,0.25,0.25))`; language tag from CyberSecEval v2 test-case metadata. Implementation note: `composite_fitness.py` falls back to token-level BLEU if CodeBLEU import/computation fails, so a small fraction of `code_divergence` values may be token-BLEU.

### 🟡 Partial

**5.4 SEVERITY_WEIGHTED internal heuristic (ERROR × 3, WARNING × 1, INFO × 0); raw count reported**
- *Support:* Weighted severity aggregation is conventional in SAST benchmarking; no paper prescribes the 3/1/0 weights (Semgrep-community defaults). The design keeps severity-weighting as an **internal search heuristic only** and **reports the raw ERROR+WARNING count** — Cisco's exact metric (Ref C0 / `cisco_codeguard_validation_blog.md`, "counted only ERROR and WARNING findings") — as the headline outcome. This makes results directly Cisco-comparable.
- *Threat to validity to disclose:* the search optimises the weighted signal while the reported metric is unweighted.

**5.5 Delta formulation (candidate − baseline) instead of absolute count**
- *Support:* Paper 24 (SAST-MT) implicitly motivates this — absolute SAST counts are unreliable due to FN/FP, but *relative* deltas are more robust. A defensible extrapolation, not a direct recommendation.

### ❌ GAP

**5.6 Reference-code source (iteration-0 Qwen baseline)**
- *Status:* The baseline reference code for `code_divergence` is captured fresh at iteration 0 from the same Qwen run (see §8.2), not loaded from an external file. The external `interesting_cases.control_code` path is retained for debugging / thesis figures but is not used by the fitness pipeline.
- *Gap:* The choice of iteration-0 self-baseline over an external reference is an engineering decision; no paper prescribes it (though Paper 17 SoS and Paper 20 SCAFFOLD-CEGIS both use baseline-relative comparison).

---

## 6. Multi-mutator pool and selection

**Current selection: uniform random mutator selection** (`search.py`). This is the **standard AOS (adaptive-operator-selection) baseline** that adaptive methods are measured *against* — a citable, unbiased default, not an unmotivated choice (supervisor-endorsed). Assigning per-mutator probabilities (a bandit or weighted scheme) is the documented next step, deferred because the search budget is too small for a bandit to learn (~30–50 iterations ÷ 8 arms). See the **Bandit note** at the top of this document.

### ✅ Validated

**6.1 Max mutation depth = 4 per rule**
- *Citation:* Paper 3 (Hyun et al. 2025, Table 1) — "1 to 4 perturbation functions in Cmb_MR."

**6.2 Combinatorial chaining (compound multiple mutators along a lineage)**
- *Citation:* Paper 3 (Hyun et al. 2025) — combinatorial MR chaining is the primary source of incremental failure gain.

### Future ablation citation set (not implemented — see Bandit note)

If a bandit-vs-EA ablation on adaptive mutator selection is run as future work, the relevant citations are: **Paper 34 (Auer et al. 2002)** — UCB1, `c = √2` exploration constant, bounded reward; **Paper 35 (Garivier & Moulines 2011)** — D-UCB / SW-UCB for non-stationary reward drift; **Paper 36 (Sun & Li 2020)** — DYTS, single-hyperparameter adaptive operator selection in an EA (the closest fit); **Paper 39 (Chapelle & Li 2011)** — empirical support for Thompson sampling in sparse-reward regimes. A mutator-only arm factorization (not joint rule×mutator) is the budget-appropriate design, by the same "reduce complexity to what the budget supports" logic as Paper 26 (Chen & Li). None of this is in the current pipeline.

---

## 7. Generation setup

### ✅ Validated

**7.1 Temperature = 0 for code generation (deterministic)**
- *Citation:* Paper 13 (PERSIST) — high-temperature CoT amplifies behavioural instability; deterministic decoding isolates mutation effect. Paper 8 (Code MT) — single-generation paradigm.

**7.2 Single-model-under-test (no cross-model validation in this pipeline)**
- *Citation:* Paper 3 (Hyun et al. 2025) — single-model setup in their SBST evaluation.

### 🟡 Partial

**7.3 Qwen2.5-Coder-32B-Instruct as the generation model**
- *Support:* Cisco's validation study (thesis motivation) used a different model. Our choice is driven by DelftBlue GPU availability (A100, 32B fits). No reviewed paper prescribes Qwen2.5-Coder — but none forbid it; it is a reasonable strong-code-LLM choice.

### ❌ GAP

**7.4 Default sampling parameters besides temperature (top_p, max_new_tokens, etc.)**
- *Gap:* Values in `delftblue_local_backend.py` are engineering defaults, not cited.

**7.5 Quantization setting for inference**
- *Gap:* The SLURM script exposes quantization as a flag. The default choice is not grounded in a paper.

**7.6 Prompt templating for code generation (how the rule is injected into the chat template)**
- *Gap:* The exact system/user message structure is our convention. Paper 19 (SPRIG) discusses system-prompt optimisation but doesn't prescribe template structure for our case.

---

## 8. Evaluation protocol

### ✅ Validated

**8.1 Per-language reporting (Python + Java) as primary stratification axis**
- *Choice:* Language (Python / Java) is the primary reporting axis — two clean groups, natural statistical comparison (vs. 20+ CWE groups).
- *Citation:* Paper 10 (Tone) — aggregation hides per-domain effects; per-language is the domain split. Paper 14 (CAIBench) — multi-domain cybersecurity evaluation. **Paper 37 (CyberSecEval v2)** — Python + Java are the two programmatic languages in the benchmark.
- *CWE note:* CWE is retained as a **retrieval join key** between test cases and rules (kept in the pipeline). It is only retired as a *reporting* stratification axis. See §8.5 and §9.1.

**8.2 Baseline control (original rule) computed fresh at iteration 0**
- *How it works:* the baseline is **not** loaded from an external file. `engine.py` (`ExperimentEngine`) evaluates the origin chromosome once before the iteration loop, caching per-case Semgrep fitness and per-case generated code (the CodeBLEU reference in `composite_fitness.py`). Each subsequent iteration looks both up: `semgrep_delta` uses the fitness cache, `code_divergence` uses the code cache.
- *Implication:* the pipeline is self-contained per run — one consistent iteration-0 baseline for both signals.
- *Citation:* Paper 17 (SoS) — baseline-relative selection. Paper 20 (SCAFFOLD-CEGIS) — comparison to an un-mutated baseline is the key experimental primitive.

### 🟡 Partial

**8.3 CyberSecEval v2 as the primary evaluation dataset**
- *Citation:* **Paper 37 (Bhatt et al. 2024, arXiv:2404.13161)** — the HuggingFace dataset `walledai/CyberSecEval` with the `instruct` config is v2 (not v1, arXiv:2312.04724). CWE metadata is the retrieval join key between test cases and rules.
- *Multi-dataset strategy:* **Paper 38 (LLMSecEval, Tony et al. MSR 2023)** — cross-check dataset (separate SLURM submission, linear wall-time). Paper 40 (SecurityEval, Siddiq & Santos 2022) *(optional)* — third cross-check.

**8.4 Separation of "interesting cases" (filtered) vs full prompt set**
- *Support:* Paper 3 (Hyun et al. 2025) and Paper 11 (STELLAR) both do test-case selection/prioritisation, but our specific filtering criteria are a pipeline artefact, not a cited method.

**8.5 CWE as retrieval join key, language as reporting axis**
- *Choice:* CWE-based *reporting* stratification is not used; CWE is kept only as a retrieval join key (`rule_retrieval_mapping_local.py`'s `CWE → rules_map`) — a free metadata join requiring no design justification. Reporting uses the Python + Java language split (§8.1).
- *Support:* Paper 10 (Tone) motivates a domain split; the language axis gives two groups with a clean statistical comparison.

### ❌ GAP

**8.6 Number of test prompts per experiment run (N_CASES)**
- *Gap:* The values used in SLURM scripts are driven by wall-time budget, not by a statistical power argument in the literature.

**8.7 Number of EA iterations (`N_ITERATIONS`)**
- *Gap:* "~50 for initial experiments, ~150 for full runs" is based on "8 rules × 4 depth × ~20% acceptance." The 20% acceptance assumption is an empirical guess, not literature-backed.

---

## 9. Dataset / input pipeline

### ❌ GAP (entire subsystem)

**9.1 Retrieval-map construction (CWE → rules) via a separate Qwen2.5-Coder-32B run**
- *Gap:* The two-phase architecture (retrieval-then-mutate) is engineered around DelftBlue's job-length limits and HF cache mechanics. No paper in our set prescribes it.

**9.2 `LIMIT_PER_CWE` default**
- *Gap:* Chosen to keep retrieval runs tractable (Paper 14 CAIBench suggests multi-domain evaluation, but not this specific cap).

**9.3 `alwaysApply` rule handling (crypto-algorithms / digital-certificates / hardcoded-credentials always injected)**
- *Gap:* A CodeGuard platform convention, not a thesis-literature choice.

---

## 10. Mutator-specific implementation details (deep gaps)

The following details are inside individual mutators and, while not load-bearing for the thesis argument, would ideally be traceable to literature for a defensive reviewer. **All of these are currently uncited.**

| Detail | Location | Gap |
|---|---|---|
| nlpaug SynonymAug backend (WordNet vs embeddings) | `rule_based.py:SynonymReplacementMutator` | Choice of WordNet over contextual embeddings is a fallback after transformers>=5.0 broke `ContextualWordEmbsAug`; no paper prefers WordNet for our task. |
| `aug_p` values (0.3 synonym, 0.1 insertion) | `rule_based.py` | No citation for these fractions. |
| Filler-word list | `rule_based.py:_SimpleWordInserter._FILLER_WORDS` | 20 hand-picked words. |
| Negation-stopword list for AddRandomWord | `rule_based.py:_NEGATION_STOPWORDS` | 16 hand-picked words. |
| `_SECURITY_KEYWORDS` for SectionReorder degrade mode | `rule_based.py` | Hand-picked list — distinct from the validator's keyword list above. Potential consistency issue. |
| Few-shot prompt templates for LLM mutators | `llm_based.py` | AUGMENT-style approach is cited; the exact example text and constraints are authored, not from any paper. |
| Jaccard / word-count bounds in per-mutator adherence checks | `quality.py` | Heuristic bounds (e.g. "paraphrase Jaccard ∈ [0.3, 0.8]") are our tuning choices. |

---

## 11. Gap status and remaining work

**Resolved by the current design (no longer open):**
- **Search admission** (§1.2) — Pareto-dominance archive admission (ARIEL 41, Chen & Li 26, Miettinen 28). Implemented in `chromosome.py` / `search.py`.
- **Code divergence** (§5.3) — CodeBLEU (Paper 29), implemented in `composite_fitness.py`.
- **SBERT model** (§4.7) — `all-mpnet-base-v2` justified by MTEB (P31) + Sentence-BERT (P32).
- **SBERT / perplexity thresholds** (§4.5–4.6) — 0.75 / 2.5, both AUGMENT values.
- **Security lexicon** (§4.11) — corpus-derived (Papers 20, 23, MITRE CWE); a `build_security_lexicon()` helper exists in `security_lexicon.py`.
- **CWE → language reporting** (§8.5) — CWE kept as retrieval join key; language is the reporting axis.
- **CyberSecEval citation** (§8.3) — v2 (Bhatt et al. 2024, P37).

**Open, papers done — engineering work remaining:**
1. **`LIMIT_PER_CWE` → `LIMIT_PER_LANGUAGE`** (§8.5) — code change.
2. **SecureBERT 2.0 ablation** (§4.7) — 30–50 rule pairs, ~1 day.
3. **LLMSecEval ingestion adapter** (§8.3) — ~3–4 hours; run after main experiments.

**Open gaps expected to stay uncited (engineering choices):**
4. **Mutator hyperparameters** (§2.10) — `aug_p`, stopword/filler lists.
5. **Generation sampling parameters** (§7.4–7.6) — top_p, max_new_tokens, quantization, prompt template.
6. **N_CASES and N_ITERATIONS** (§8.6–8.7) — defensible as engineering choices with documented rationale; a formal power analysis would be a novel contribution.
7. **Keyword-retention threshold 0.70** (§4.10) — may need recalibration as the lexicon grows.

**Future ablation (not in the current design — see Bandit note):**
8. **Adaptive bandit mutator selection** (§6) — UCB1 / D-UCB / DYTS (Papers 34/35/36/39). Prototyped earlier, replaced by uniform selection; revisit only if a bandit-vs-EA ablation is run.

**Research deliverables remaining:**
- SecureBERT 2.0 ablation note → Spearman correlation + threshold calibration on 30–50 rule pairs (~1 day).
- LLMSecEval cross-check SLURM run → after main experiments (1 submission, ~1–2h wall time).
- (Optional) SecurityEval third cross-check → if LLMSecEval raises generalization questions.

---

## 12. What is safely out of scope

To keep the search focused, the following are **deliberately** uncited and should stay uncited — engineering details or thesis-specific conventions for which no literature is expected:

- Directory layout, file naming, SLURM scripting conventions.
- Python `.venv` environment, HF cache path, env activation.
- Logging format, `bd` (beads) tracker usage, experiment-results archiving.
- `mask_inline_code` placeholder tokens, restore-map implementation (§3.3).
- The decision to cache SBERT embeddings or lazy-load models.
- Any code-hygiene detail (type hints, dataclass vs class, etc.).

These are listed here only so a future search run doesn't waste effort trying to find literature for them.

---

*End of mapping.*
