# Implementation ↔ Literature Mapping

*Generated 2026-04-15. Purpose: for every design decision in the rule-mutation pipeline, record what literature validates it and — more importantly — flag choices that currently have **no** reviewed citation.*

The 25 papers referenced below are the ones analysed in `LITERATURE_REVIEW_ANALYSIS.md` / `THESIS_RELEVANCE.md`. Paper numbers match those files.

This document is a **mapping**, not a new literature search. Anything marked **GAP** is an action item: something we rely on but currently justify only by engineering judgment.

---

## How to read this document

Each implementation choice is categorised into one of three tiers:

- **✅ Validated** — an explicit, named citation from our 25-paper set directly supports this choice (not just the general area).
- **🟡 Partial** — literature supports the general approach but not the specific parameter/threshold/variant we chose.
- **❌ GAP** — no reviewed paper justifies this. We rely on engineering judgment, ad-hoc empirical tuning, or convention.

Inside each tier, choices are grouped by subsystem (search, mutation, validation, fitness, generation, evaluation).

---

## Summary dashboard

*(Revised 2026-04-17 after supervisor-prep pass: SBERT/perplexity thresholds aligned to AUGMENT defaults, γ-term **kept** but its reference-code source switched from external JSON to iteration-0 caching, early-stop reclassified as gap, Fluff/VerbWeakening flagged for removal.)*

| Subsystem | ✅ Validated | 🟡 Partial | ❌ GAP |
|---|---|---|---|
| Search algorithm | 3 | 1 | 2 |
| Mutation operators | 6 | 2 | 4 |
| Safe-zone / parsing | 1 | 1 | 1 |
| Quality validator | 6 | 3 | 2 |
| Fitness function | 3 | 2 | 4 |
| Pool / bandit | 3 | 1 | 3 |
| Generation setup | 2 | 1 | 3 |
| Evaluation protocol | 2 | 2 | 3 |
| **Totals** | **26** | **13** | **22** |

Gaps down from 23 to **22** after revision. Biggest remaining concentration: (a) composite-weight choice (α, β, γ), (b) dataset / benchmark selection (CyberSecEval, CWE stratification), (c) hardcoded word lists inside mutators and the validator, (d) deeper search-strategy alternatives beyond UCB1, (e) NL-SBERT-on-code for γ (known weak fit; upgrade path CodeBERT).

---

## 1. Search algorithm

### ✅ Validated

**1.1 Hill climbing as the base SBST loop**
- *Choice:* Single-objective stochastic hill climb over mutated rule text; accept on improvement.
- *Citation:* Paper 3 (Hyun et al. 2025) — uses SBST over MR selection; shows search-based selection outperforms random. Paper 19 (SPRIG) — directly analogous hill-climb over system prompts.
- *Confidence:* Strong. Two papers in the reviewed set use the same structural algorithm on closely related problems.

**1.2 Iterative accept-on-improvement semantics**
- *Choice:* Adopt candidate if fitness strictly improves, else discard.
- *Citation:* Paper 3 (Hyun et al. 2025) — standard SBST acceptance; Paper 19 (SPRIG) — fitness-guided selection step.

**1.3 Mutations compound on current best (not original)**
- *Choice:* `CurrentBestTracker` keeps the accepted text per rule so later mutations stack on earlier accepted ones.
- *Citation:* Paper 3 (Hyun et al. 2025, Table 1) — "1 to 4 perturbation functions in Cmb_MR" explicitly defines combinatorial chaining on the parent candidate.

### 🟡 Partial

**1.5 Random restarts from HillClimbConfig**
- *Choice:* `random_restarts` knob to escape local optima.
- *Support:* Standard SBST technique. No specific paper in our set validates it for this task; user flagged it as a "deeper-experiments" item, not current-run.

### ❌ GAP

**1.4 Early-stop after N iterations without improvement**
- *Choice:* `early_stop_no_improvement` parameter on HillClimbConfig.
- *Status:* **Not actively used in current experiments** (user-confirmed 2026-04-17). Likely dead parameter; candidate for removal.
- *Gap:* No paper in our set validates the specific threshold (5). Since it's not used, low-priority gap.

**1.6 Single-objective scalar optimisation (vs Pareto multi-objective)**
- *Choice:* Maximise the scalar composite `α · semgrep_delta + β · rule_divergence`. No Pareto front maintained.
- *Gap:* Paper 11 (STELLAR) and Paper 17 (SoS) both argue for multi-objective formulations on closely related problems.
- *Status:* **Planned to evolve.** Not a missing-rationale gap so much as an explicit future-work axis (user-confirmed 2026-04-17). Decision should be made before running full-scale experiments.

---

## 2. Mutation operators

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

### ❌ GAP

**2.9 FluffMutator (bureaucratic preamble/postamble + verb weakening)** — *scheduled for removal*
- *Gap:* Thesis original. Closest analogue is Paper 10 (Tone and Politeness) at a pragmatic level, but Paper 10 does not define a mutator of this form.
- *Status (2026-04-17):* User-confirmed to be retired. Will not survive the next round of mutator refinement. Keeping in the mapping only so the decision trail is visible; should not require a literature citation going forward.

**2.10 VerbWeakeningMutator (MUST → should ideally, NEVER → try to avoid, etc.)** — *scheduled for removal / reshape*
- *Gap:* Thesis original. Paper 10 (Tone) and Paper 4 (AUGMENT) touch on register shifting but do not prescribe this specific mapping table.
- *Status (2026-04-17):* User-confirmed to be retired or reshaped in favour of cited mutators. The hardcoded `VERB_WEAKENING_MAP` is explicitly targeted for removal per the user's "less hardcoding is better" rule.

**2.11 Specific hyper-parameters inside rule-based mutators**
- *Gap:*
  - `SynonymReplacement.aug_p = 0.3` — no literature justification for this fraction.
  - `AddRandomWord.aug_p = 0.1` — no literature justification.
  - Negation stopword list (~16 entries) for AddRandomWord — curated by the author; Paper 2 (LLMORPH) defines *negation injection* as a distinct MR, which is the reason we exclude these words, but the exact list is ours.
  - `_SimpleWordInserter` filler-word list (20 adverbs/connectors) — chosen by the author; no paper enumerates this list.

**2.12 `FLUFF_PREFIXES` / `FLUFF_SUFFIXES` template contents**
- *Gap:* The four preamble templates and four postamble templates are hand-authored. No paper prescribes bureaucratic-register templates of this form.

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

### ✅ Validated

**4.1 Three-criteria quality-gating framework (adherence + semantic similarity + fluency)**
- *Citation:* Paper 4 (AUGMENT) — direct source. The validator is an implementation of AUGMENT's framework.

**4.2 SBERT cosine similarity as the semantic-similarity gate**
- *Citation:* Paper 4 (AUGMENT) — uses SBERT. Paper 1 (191-MR Catalog) — validates SBERT for MR oracle purposes.

**4.3 Perplexity ratio as the fluency gate**
- *Citation:* Paper 4 (AUGMENT) — perplexity ratio. Paper 6 (LAP) — provides calibration (ratio ≤ 2.0 ↔ SBERT ≥ 0.80 in >90 % of cases).

**4.4 Per-mutator adherence function (each mutator gets its own check)**
- *Citation:* Paper 4 (AUGMENT) — describes per-mutator adherence tests; our `_adherence_*` functions are that pattern.

### 🟡 Partial

**4.5 SBERT model = `sentence-transformers/all-mpnet-base-v2`** — *elevated priority for next literature pass*
- *Support:* Common default in the sentence-transformers community. Paper 1 and Paper 4 use SBERT but not this exact checkpoint. Safe default, but the *choice of this specific model* has no citation in our review.
- *Status (2026-04-17):* User flagged this as a priority item to validate. Candidates to investigate in the next literature pass: domain-tuned sentence encoders, Instructor-XL, E5-large-v2, GTE-large. Also: should the embedding model differ between *rule* SBERT (natural-language, domain-flavoured) and any future code-embedding use?

**4.6 Security-keyword-retention criterion**
- *Support:* This is a thesis extension to AUGMENT's framework, explicitly framed as "adding a 4th criterion." Paper 4 does not include this criterion. The *idea* of preserving domain-sensitive vocabulary is partially supported by Paper 20 (SCAFFOLD-CEGIS anchoring) and Paper 23 (MST-wi structural invariants).

**4.7 Inline-code retention criterion**
- *Support:* Falls out of Paper 20's anchoring principle. Threshold = 1.0 (exact retention) is our engineering choice.

### ✅ Validated (resolved 2026-04-17 by adopting AUGMENT defaults)

**4.8 SBERT threshold ≥ 0.75 (AUGMENT default)** — *was 0.80, code change pending*
- *Citation:* Paper 4 (AUGMENT) — exact value used. Paper 6 (LAP) provides empirical calibration (perplexity ratio ≤ 2.0 ↔ SBERT ≥ 0.80 in >90% of cases).
- *Action item:* update `MutationQualityValidator.DEFAULT_SBERT_THRESHOLD` in [quality.py](thesis/rule-mutation/src/mutation/quality.py) from 0.80 to 0.75. All prior experiment runs that used 0.80 should be re-noted as having applied a stricter threshold than the literature default.

**4.9 Perplexity ratio threshold ≤ 2.0 (AUGMENT default)** — *was 2.5, code change pending*
- *Citation:* Paper 4 (AUGMENT) and Paper 6 (LAP) both use ≤ 2.0.
- *Action item:* update `MutationQualityValidator.DEFAULT_PERPLEXITY_THRESHOLD` in [quality.py](thesis/rule-mutation/src/mutation/quality.py) from 2.5 to 2.0.

### ❌ GAP

**4.10 Keyword-retention threshold ≥ 0.70**
- *Gap:* Thesis choice. No paper motivates 0.70 vs 0.60 or 0.80.

**4.11 The `_SECURITY_KEYWORDS` frozenset (~30 terms)** — *elevated priority*
- *Gap:* Hand-curated vocabulary (sanitize, validate, escape, encode, injection, xss, csrf, ...). No paper provides this list.
- *Status (2026-04-17):* User flagged as priority. Next-step options: (a) derive programmatically from CWE definitions, (b) adopt a published security-vocabulary corpus, (c) extract terms from the CodeGuard rule set itself (each rule's inline-code spans and frontmatter tags). Option (c) is attractive because it removes the hardcoding entirely.

**4.12 Readability-delta criterion**
- *Gap:* Fifth criterion in the code (`quality.py` has *five* criteria, not three — 2026-04-15 audit). The readability delta is not in AUGMENT. Choice of readability metric and threshold is undocumented in the reviewed literature.

---

## 5. Fitness function

*Revised 2026-04-17: γ-term (code_divergence) **kept**, but its reference code source changed. Old design: load `InterestingCase.control_code` from the `interesting_cases` JSON (Sonnet-era batch output, model-mismatched with current Qwen pipeline). New design: populate `composite_evaluator.reference_codes` at iteration 0 from the fresh Qwen baseline generations that are already being computed for the α-term. Net effect: model-consistent γ, self-contained per-run pipeline, and the `control_code` JSON field becomes optional (retained for debugging/thesis figures).*

**Current formula:** `composite = α · semgrep_delta + β · rule_divergence + γ · code_divergence`
- `rule_divergence = 1 − SBERT(R_orig, R_mut)` (NL SBERT, suitable model)
- `code_divergence = 1 − SBERT(generated_code, iteration-0_reference_code)` (NL SBERT applied to code — known weak fit, see §5.9)
- Default weights (α, β, γ) = (1.0, 0.3, 0.2)

### ✅ Validated

**5.1 Use a SAST tool (Semgrep) as the primary objective signal**
- *Citation:* Paper 21 (ATheNA) — automated oracle `f_AT`. Paper 24 (SAST-MT) — uses SAST as an oracle target, also flags it has false-negatives (threat to validity).

**5.2 Composite fitness that mixes Semgrep with auxiliary signals**
- *Citation:* Paper 3 (Hyun et al. 2025) — `Context_ASR × PerturbationQuality` is the structural analogue. Paper 9 (METAL) — EFM metric. Paper 21 (ATheNA) — formalises `f_AT × f_MAN`.

**5.3 Code-divergence component (SBERT between generated code and iteration-0 reference)**
- *Citation:* Paper 9 (METAL) — output-space divergence. Paper 17 (SoS) — multi-objective fitness interleaving.
- *Architecture (2026-04-17):* reference code is **not** loaded from an external file. It is captured at iteration 0 from the same Qwen baseline run that produces the per-case Semgrep baseline. This ensures the reference is in-distribution with the candidate generations. See §8.2 for the wiring.

### 🟡 Partial

**5.4 SEVERITY_WEIGHTED (ERROR × 3, WARNING × 1, INFO × 0)**
- *Support:* Weighted severity aggregation is conventional in SAST benchmarking. No specific paper in our set prescribes the 3/1/0 weights — these are Semgrep-community defaults.

**5.5 Delta formulation (candidate − baseline) instead of absolute count**
- *Support:* Paper 24 (SAST-MT) implicitly motivates this — absolute SAST counts are unreliable due to FN/FP, but *relative* deltas are more robust. Not a direct recommendation, but a defensible extrapolation.

### ❌ GAP

**5.6 Composite weights α = 1.0, β = 0.3, γ = 0.2**
- *Gap:* Values chosen by engineering judgment: α dominates because Semgrep is the ground truth; β and γ are smoothers. No sensitivity analysis; no paper prescribes these magnitudes. Paper 9 (METAL) uses a *product* `ASR × Quality`, not a weighted sum — we diverged in both form and numerics.
- *Action item:* run a small 2-D sensitivity sweep over (β, γ) holding α fixed; check whether the optimiser trajectory is robust to these choices.

**5.7 `1 − sbert_rule_similarity` as the rule-divergence signal (β component)**
- *Gap:* Hardcoded in [composite_fitness.py:154](thesis/rule-mutation/src/evaluation/composite_fitness.py#L154) as `raw_rule_divergence = 1.0 - sbert_rule_similarity`. Note: this diverges from the original `project_multi_mutator_plan.md`, which proposed `β · (1 − validation_score)` combining SBERT + keyword + inline-code; the implementation uses *just* SBERT drift.
- *Implication:* one less hardcoded weighting decision than the plan suggested — simpler and directly grounded in SBERT. But still no paper validates rule SBERT drift as a fitness smoother specifically.

**5.8 Reference-code source change — track the cleanup**
- *Status (2026-04-17):* the external-reference path from `InterestingCase.control_code` into `CompositeFitnessEvaluator(reference_codes=...)` becomes dead code in the fitness pipeline. The `control_code` JSON field is retained for non-fitness uses (debugging, thesis figures).
- *Code touchpoints:*
  - [hill_climber.py:794-797](thesis/rule-mutation/src/optimizer/hill_climber.py#L794-L797) — extend the existing iter-0 loop to also cache `eval_r.generated_code` into `self.composite_evaluator.reference_codes[tc_id]`.
  - Caller (e.g. `scripts/experiments/run_with_rules_map.py`) — construct `CompositeFitnessEvaluator(reference_codes={}, ...)`; stop pre-loading from interesting_cases.
  - No changes to [composite_fitness.py](thesis/rule-mutation/src/evaluation/composite_fitness.py) internals — the dict contract is unchanged.

**5.9 `all-mpnet-base-v2` for code embedding inside γ**
- *Gap:* Natural-language SBERT applied to code produces noisy embeddings. Paper 9 (METAL) uses output SBERT for NL outputs, not code. Known upgrade path: CodeBERT / UniXcoder / CodeT5+ embedders. Currently we reuse the validator's SBERT to avoid a second model load on DelftBlue.
- *Action item (medium priority):* benchmark all-mpnet vs CodeBERT on a held-out (original_rule → generated_code, mutated_rule → generated_code) pair set; quantify how much γ's ranking changes with the upgrade. If minimal, defend the NL-SBERT choice; otherwise switch.

---

## 6. Multi-mutator pool and bandit

### ✅ Validated

**6.1 UCB1 bandit for mutator selection**
- *Citation:* Paper 19 (SPRIG) — UCB-based pruning for component/mutator selection in system-prompt optimisation. Standard Auer et al. 2002 (not in reviewed set, but referenced by Paper 19).

**6.2 Max mutation depth = 4 per rule**
- *Citation:* Paper 3 (Hyun et al. 2025, Table 1) — "1 to 4 perturbation functions in Cmb_MR."

**6.3 Combinatorial chaining (compound multiple mutators on one rule)**
- *Citation:* Paper 3 (Hyun et al. 2025) — Priority-1 extension in our plan.

### 🟡 Partial

**6.4 UCB1 arms defined as joint `(rule_id, mutator_name)` pairs**
- *Support:* Paper 19 (SPRIG) selects mutators via UCB, but not over a joint (target × mutator) space. Our choice to jointly index is a thesis-specific refinement without a direct citation.

### ❌ GAP

**6.5 UCB1 exploration constant `c = 1.41` (≈ √2)**
- *Gap:* Textbook default (Auer et al. 2002). No paper in our 25-paper set justifies it for this specific application. Would benefit from a sensitivity sweep.

**6.6 UCB1 reward = `max(0.0, marginal_composite_delta)`**
- *Gap:* Clipping negative rewards is an engineering choice to prevent exploration starvation. No paper prescribes this clipping convention.

**6.7 GREEDY_BATCH strategy (mutate all rules per iteration, accept-all on improvement)**
- *Gap:* Custom strategy. None of the 25 papers defines this variant. Closest analogue is Paper 17 (SoS) crossover, but that is genuinely different (population-based).

---

## 7. Generation setup

### ✅ Validated

**7.1 Temperature = 0 for code generation (deterministic)**
- *Citation:* Paper 13 (PERSIST) — high-temperature CoT amplifies behavioural instability; deterministic decoding isolates mutation effect. Paper 8 (Code MT) — single-generation paradigm.

**7.2 Single-model-under-test (no cross-model validation in this pipeline)**
- *Citation:* Paper 3 (Hyun et al. 2025) — single-model setup in their SBST evaluation.

### 🟡 Partial

**7.3 Qwen2.5-Coder-32B-Instruct as the generation model**
- *Support:* Cisco's validation blog (thesis motivation) used a different model. Our choice is driven by DelftBlue GPU availability (A100, 32B fits). No reviewed paper prescribes Qwen2.5-Coder — but none forbid it either; it is a reasonable strong-code-LLM choice.

### ❌ GAP

**7.4 Default sampling parameters besides temperature (top_p, max_new_tokens, etc.)**
- *Gap:* Values in `delftblue_local_backend.py` are engineering defaults, not cited.

**7.5 Quantization setting for inference**
- *Gap:* SLURM script exposes `QUANTIZATION` as an env var. Our default choice is not grounded in a paper.

**7.6 Prompt templating for code generation (how the rule is injected into the chat template)**
- *Gap:* The exact system/user message structure is our convention. Paper 19 (SPRIG) discusses system-prompt optimisation but doesn't prescribe template structure for our case.

---

## 8. Evaluation protocol

### ✅ Validated

**8.1 Per-CWE reporting (not only aggregate)**
- *Citation:* Paper 10 (Tone) — aggregation hides per-domain effects. Paper 14 (CAIBench) — multi-domain cybersecurity evaluation.

**8.2 Baseline control (original rule) computed fresh at iteration 0** — *clarified 2026-04-17*
- *How it works:* the baseline is **not** loaded from an external file. [hill_climber.py:777-797](thesis/rule-mutation/src/optimizer/hill_climber.py#L777-L797) runs `_evaluate_with_per_prompt_rules` with `target_rule_id=None, mutator_fn=None, phase="baseline"` before the iteration loop starts. Per-case Semgrep fitness is cached into `self._baseline_fitness_per_case`, and **per-case generated code will additionally be cached into `self.composite_evaluator.reference_codes` in the same loop** (see §5.8). Both caches are looked up by each subsequent iteration: α uses the fitness cache, γ uses the code cache.
- *Implication:* the pipeline is fully self-contained per run. Baseline Semgrep score and γ reference code come from the same iteration-0 generation → one consistent baseline for both α and γ. External `interesting_cases.control_code` is retained for debugging / thesis figures but no longer needed by the fitness pipeline.
- *Citation:* Paper 17 (SoS) — baseline-relative selection. Paper 20 (SCAFFOLD-CEGIS) — comparison to un-mutated baseline is the key experimental primitive.

### 🟡 Partial

**8.3 CyberSecEval as the evaluation dataset**
- *Support:* CyberSecEval is a well-known Meta AI benchmark; Paper 14 (CAIBench) discusses cybersecurity benchmarks broadly. Our specific choice is not prescribed by any paper in the 25-set; it is an industry-standard default, and `project_rule_mutation.md` explicitly flags it as "still evolving, CWE subdivision is temporary."

**8.4 Separation of "interesting cases" (filtered) vs full prompt set**
- *Support:* Paper 3 (Hyun et al. 2025) and Paper 11 (STELLAR) both do test-case selection/prioritisation, but our specific filtering criteria are a pipeline artefact, not a cited method.

### ❌ GAP

**8.5 CWE-based stratification of the test-case universe**
- *Gap:* Explicitly flagged in `project_rule_mutation.md`: "CWE-based subdivision is temporary." No paper in our review prescribes CWE as the primary stratification axis.

**8.6 Number of test prompts per experiment run (N_CASES)**
- *Gap:* The specific values used in SLURM scripts (5–96–222–1916) are driven by wall-time budget, not by a statistical power argument in the literature.

**8.7 Number of hill-climb iterations (`N_ITERATIONS`)**
- *Gap:* Plan recommends "50 for initial experiments, 150 for full runs" based on "8 rules × 4 depth × ~20 % acceptance." The 20 % acceptance assumption is not literature-backed; it is an empirical guess.

---

## 9. Dataset / input pipeline

### ❌ GAP (entire subsystem)

**9.1 Retrieval-map construction (CWE → rules) via a separate Qwen2.5-Coder-32B run**
- *Gap:* Our two-phase architecture (retrieval-then-mutate) is engineered around DelftBlue's job-length limits and HF cache mechanics. No paper in our set prescribes this two-phase pipeline.

**9.2 `LIMIT_PER_CWE = 5` default**
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
| Few-shot prompt templates for LLM mutators | `llm_based.py` | AUGMENT-style approach is cited; the exact example text and the exact constraints are authored, not from any paper. |
| Jaccard / word-count bounds in per-mutator adherence checks | `quality.py` | Heuristic bounds (e.g. "paraphrase Jaccard ∈ [0.3, 0.8]") are our tuning choices. |
| LLM-mutation retry logic in `validate_with_retry` | `quality.py` | Engineering mechanism — retry on failure, back off after N tries. No cited protocol. |

---

## 11. Priority ranking of gaps to close

*Revised 2026-04-17 after supervisor-prep pass. Items marked ✓ RESOLVED are fixed by the 2026-04-17 decisions; items marked ★ ELEVATED were promoted by user feedback.*

**✓ RESOLVED (no further literature search needed)**
- ~~SBERT 0.80 threshold (§4.8)~~ → reverted to AUGMENT 0.75.
- ~~Perplexity 2.5 threshold (§4.9)~~ → reverted to AUGMENT 2.0.
- ~~Model-mismatched γ reference (old concern)~~ → reference_codes now populated at iteration 0 from fresh Qwen baseline; external interesting_cases.control_code retired from fitness path.
- ~~`validation_score` sub-weights (old §5.7)~~ → never implemented in the running code; plan superseded by single SBERT-drift term.

**★ TOP PRIORITY for next literature pass**
1. **Search-strategy alternatives to UCB1 (§6.5–6.7).** User wants to research Thompson sampling, ε-greedy-with-decay, EXP3 (non-stationary bandits), NSGA-II, simulated annealing. UCB1's stationarity assumption is violated by compounding; the `max(0, ·)` clipping destroys signal; per-prompt attribution is lost in aggregation. These are the three concrete weak spots to address.
2. **Composite-fitness weights α = 1.0, β = 0.3, γ = 0.2 (§5.6).** Paper 9 (METAL) uses a product form; we use a weighted sum. Defend, switch, or run a sensitivity sweep over (β, γ) holding α fixed.
3. **NL-SBERT for γ code-divergence (§5.9).** `all-mpnet-base-v2` on code is a known weak fit. Benchmark CodeBERT / UniXcoder / CodeT5+ as replacement; quantify how much γ rankings change. Cheap ablation, high defensive-value.
4. **SBERT model choice for rule-level similarity (§4.5).** User-flagged. Benchmark domain-specialised encoders (Instructor-XL, E5, GTE) against `all-mpnet-base-v2` for security-rule text.
5. **Security-keyword list (§4.11).** User-flagged: remove hardcoding. Best path is probably deriving from the rule corpus itself (inline-code spans + frontmatter tags) or CWE definitions.
6. **Single-objective vs Pareto (§1.6).** Explicit supervisor decision needed — Paper 11 (STELLAR) and Paper 17 (SoS) favour multi-objective; Paper 3 (Hyun) single-objective.

**MEDIUM PRIORITY**
7. **FluffMutator + VerbWeakeningMutator (§2.9, §2.10).** Scheduled for removal. No literature hunt needed if they are dropped; if reshaped, find prior art in the register-shift / politeness literature.
8. **CyberSecEval + CWE stratification (§8.3, §8.5).** User-confirmed "still evolving." A dataset justification paper — or a principled alternative (CAIBench, BigCodeBench-Security) — is the next research step.
9. **Readability-delta criterion (§4.12).** Fifth validator criterion with no AUGMENT-style citation. Low user-priority but a defensive-review item.

**RESEARCH DELIVERABLES this implies**
- A **search-strategy comparison paper** (item 1) → likely the biggest upcoming literature deliverable.
- A **composite-weight sensitivity memo** (item 2) → can be pure internal ablation, 1–2 day cost.
- A **code-embedding benchmark note** (item 3) → pairwise compare all-mpnet vs CodeBERT on held-out (rule, generated-code) pairs.
- An **SBERT-model benchmark note** (item 4) → small ablation on a held-out rule corpus.

---

## 12. What is safely out of scope

To keep the search focused, the following items are **deliberately** uncited and **should stay uncited**, because they are engineering details or thesis-specific conventions for which no literature is expected:

- Directory layout, file naming, SLURM scripting conventions.
- Conda environment, HF cache path, `activate_sbst.sh`.
- Logging format, `bd` (beads) tracker usage, experiment-results archiving.
- `mask_inline_code` placeholder tokens, restore-map implementation (§3.3).
- The decision to cache SBERT embeddings or lazy-load models.
- Any code-hygiene detail (type hints, dataclass vs class, etc.).

These are listed here only so a future search run doesn't waste effort trying to find literature for them.

---

*End of mapping.*
